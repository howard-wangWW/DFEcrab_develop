# src/core/task/executor.py
"""Task Executor - 任务执行引擎"""
import asyncio
import json
import logging
import time
from typing import Dict, Any, Optional, List
from datetime import datetime

from src.task.task_manager import TaskManager
from src.task.supervisor import SupervisorSession
from src.task.models import TaskStatus

logger = logging.getLogger(__name__)


class TaskExecutor:
    """任务执行引擎 - 直接调用智能体"""
    
    def __init__(self, task_manager: Optional[TaskManager] = None):
        self.task_manager = task_manager or TaskManager()
    
    async def execute_task(self, task_id: str, task_data: Optional[Dict] = None) -> bool:
        """执行任务"""
        task = self.task_manager.get_task(task_id)
        if not task:
            logger.error(f"❌ 任务不存在: {task_id}")
            return False
        
        if task.status == TaskStatus.DRAFT:
            logger.warning(f"⚠️ 任务需要先确认才能执行: {task_id}")
            return False
        
        if task.status in [TaskStatus.RUNNING, TaskStatus.COMPLETED]:
            logger.warning(f"⚠️ 任务状态不允许执行: {task_id}, status={task.status}")
            return False
        
        supervisor = SupervisorSession(task_id, self.task_manager)
        if not await supervisor.start():
            logger.error(f"❌ 启动监督失败: {task_id}")
            return False
        
        try:
            logger.info(f"🚀 开始执行任务: {task_id}")
            logger.info(f"   📋 标题: {task.title or task.topic}")
            logger.info(f"   📋 描述: {task.description}")
            
            selected_agents = task.selected_agents
            if not selected_agents:
                logger.warning(f"⚠️ 任务没有关联智能体，无法执行")
                supervisor.complete(success=False)
                return False
            
            logger.info(f"   📋 智能体列表: {selected_agents}")
            logger.info(f"   📋 协同模式: {task.collaboration_mode.value}")
            
            if task.collaboration_mode.value == "sequential":
                result = await self._execute_sequential(task, supervisor, selected_agents)
            elif task.collaboration_mode.value == "parallel":
                result = await self._execute_parallel(task, supervisor, selected_agents)
            else:
                result = await self._execute_sequential(task, supervisor, selected_agents)
            
            if result:
                supervisor.complete(success=True)
                logger.info(f"✅ 任务执行完成: {task_id}")
                return True
            else:
                supervisor.complete(success=False)
                logger.error(f"❌ 任务执行失败: {task_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 任务执行异常 {task_id}: {e}")
            import traceback
            traceback.print_exc()
            supervisor.complete(success=False)
            task = self.task_manager.get_task(task_id)
            if task:
                task.error_message = str(e)
                self.task_manager._save_task(task)
            return False
    
    async def _execute_sequential(self, task, supervisor, agent_ids: List[str]) -> bool:
        """顺序执行"""
        total_steps = len(agent_ids)
        previous_result = None
        
        for i, agent_id in enumerate(agent_ids):
            try:
                step_name = f"步骤{i+1}: {agent_id}"
                supervisor.update_step(i, "running", logs=f"开始执行 {agent_id}")
                supervisor.update_progress(int((i / total_steps) * 100), step_name)
                
                logger.info(f"   🤖 [{i+1}/{total_steps}] 调用: {agent_id}")
                
                input_data = {
                    "task_id": task.task_id,
                    "task_description": task.description,
                    "step": i + 1,
                    "total_steps": total_steps
                }
                if previous_result:
                    input_data["previous_result"] = previous_result
                    logger.info(f"      └─ 传入上一步结果")
                
                result = await self._call_agent(agent_id, input_data, task, supervisor)
                
                if result.get("success"):
                    output = result.get("output", {})
                    supervisor.update_step(
                        i, 
                        "completed", 
                        output_data=output,
                        logs=f"{agent_id} 执行成功"
                    )
                    previous_result = output
                    logger.info(f"   ✅ {agent_id} 执行成功")
                else:
                    error_msg = result.get("error", "未知错误")
                    supervisor.update_step(i, "failed", logs=f"{agent_id} 执行失败: {error_msg}")
                    logger.error(f"   ❌ {agent_id} 执行失败: {error_msg}")
                    return False
                    
            except Exception as e:
                logger.error(f"   ❌ {agent_id} 执行异常: {e}")
                supervisor.update_step(i, "failed", logs=f"{agent_id} 执行异常: {str(e)}")
                return False
        
        supervisor.update_progress(100, "任务完成")
        task = self.task_manager.get_task(task.task_id)
        if task:
            task.result = previous_result
            self.task_manager._save_task(task)
        
        logger.info(f"   🎉 所有步骤执行完成")
        return True
    
    async def _execute_parallel(self, task, supervisor, agent_ids: List[str]) -> bool:
        """并行执行"""
        total_steps = len(agent_ids)
        
        tasks = []
        for i, agent_id in enumerate(agent_ids):
            input_data = {
                "task_id": task.task_id,
                "task_description": task.description,
                "step": i + 1,
                "total_steps": total_steps
            }
            tasks.append(self._call_agent(agent_id, input_data, task, supervisor))
        
        logger.info(f"   📋 并行执行 {len(tasks)} 个智能体")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_success = True
        outputs = []
        for i, result in enumerate(results):
            agent_id = agent_ids[i]
            if isinstance(result, Exception):
                logger.error(f"   ❌ {agent_id} 执行异常: {result}")
                supervisor.update_step(i, "failed", logs=f"{agent_id} 执行异常: {str(result)}")
                all_success = False
            elif result.get("success"):
                output = result.get("output", {})
                supervisor.update_step(
                    i, 
                    "completed", 
                    output_data=output,
                    logs=f"{agent_id} 执行成功"
                )
                outputs.append(output)
                logger.info(f"   ✅ {agent_id} 执行成功")
            else:
                supervisor.update_step(
                    i, 
                    "failed", 
                    logs=f"{agent_id} 执行失败: {result.get('error', '未知错误')}"
                )
                logger.error(f"   ❌ {agent_id} 执行失败")
                all_success = False
        
        if all_success:
            supervisor.update_progress(100, "任务完成")
            task = self.task_manager.get_task(task.task_id)
            if task:
                task.result = outputs
                self.task_manager._save_task(task)
            logger.info(f"   🎉 所有步骤执行完成")
            return True
        else:
            return False
    
    async def _call_agent(self, agent_id: str, input_data: Dict, task,
                          supervisor: Optional[SupervisorSession] = None) -> Dict[str, Any]:
        """调用单个智能体（含审计埋点）"""
        try:
            logger.info(f"      📤 调用 {agent_id}")
            if supervisor is not None:
                supervisor.audit_logger.log(
                    "agent_call", agent=agent_id,
                    details={"step": input_data.get("step"), "total_steps": input_data.get("total_steps")},
                )

            # 尝试通过 gRPC 调用
            result = await self._call_agent_grpc(agent_id, input_data, task)
            if result and result.get("success"):
                if supervisor is not None:
                    supervisor.audit_logger.log("agent_success", agent=agent_id)
                return result

            if supervisor is not None:
                supervisor.audit_logger.log(
                    "agent_failed", agent=agent_id, details={"error": result.get("error", "") if result else ""}
                )
            return {
                "success": False, 
                "error": f"无法调用智能体 {agent_id}"
            }
            
        except Exception as e:
            logger.error(f"      ❌ 调用 {agent_id} 失败: {e}")
            if supervisor is not None:
                supervisor.audit_logger.log("agent_failed", agent=agent_id, details={"error": str(e)})
            return {"success": False, "error": str(e)}
    
    async def _call_agent_grpc(self, agent_id: str, input_data: Dict, task) -> Dict[str, Any]:
        """通过 gRPC 调用智能体"""
        try:
            from src.gateway.grpc import dfecrab_pb2
            from src.gateway.grpc.zk_registry import ZKServiceDiscovery
            import grpc
            from src.gateway.grpc import dfecrab_pb2_grpc
            
            import os

            # ZK 地址配置化（原先硬编码 127.0.0.1:2181，跨机部署必失败）
            zk_hosts = os.environ.get("ZK_HOSTS") or os.environ.get("DFECRAB_ZK_HOSTS") or "127.0.0.1:2181"
            zk = ZKServiceDiscovery(zk_hosts=zk_hosts)
            if not zk.connect():
                return {"success": False, "error": "Zookeeper 连接失败"}
            
            instances = zk.discover_service("worker_agent")
            agent_instance = None
            for inst in instances:
                metadata = inst.get("metadata", {})
                if metadata.get("agent_id") == agent_id:
                    agent_instance = inst
                    break
            
            zk.close()
            
            if not agent_instance:
                return {"success": False, "error": f"未找到智能体: {agent_id}"}
            
            host = agent_instance['host']
            port = agent_instance['port']
            logger.info(f"      📡 连接: {host}:{port}")
            
            channel = grpc.insecure_channel(f"{host}:{port}")
            stub = dfecrab_pb2_grpc.AgentServiceStub(channel)
            
            # 构建指令
            instruction = input_data.get("task_description", "")
            if input_data.get("previous_result"):
                instruction += f"\n\n上一步结果: {json.dumps(input_data['previous_result'], ensure_ascii=False)}"
            
            # 构建 input_data
            input_data_map = {}
            for key, value in input_data.items():
                if isinstance(value, str):
                    input_data_map[key] = value
                else:
                    input_data_map[key] = json.dumps(value, ensure_ascii=False)
            
            # 创建请求
            request = dfecrab_pb2.ExecuteRequest(
                session_id=task.task_id,
                instruction=instruction,
                input_data=input_data_map,
                timeout=60,
                user_id=getattr(task, "user_id", "") or "",
            )
            
            logger.info(f"      📝 指令: {instruction[:100]}...")
            
            start_time = time.time()
            
            # 调用 Execute 方法
            response = await asyncio.to_thread(stub.Execute, request, timeout=60.0)
            
            elapsed = time.time() - start_time
            channel.close()
            
            logger.info(f"      ✅ 响应时间: {elapsed:.2f}s")
            
            # ===== 详细打印响应信息 =====
            logger.info(f"      📊 响应详情:")
            logger.info(f"         success: {response.success}")
            logger.info(f"         agent_id: {response.agent_id}")
            logger.info(f"         session_id: {response.session_id}")
            logger.info(f"         memory_updated: {response.memory_updated}")
            logger.info(f"         execution_time_ms: {response.execution_time_ms}")
            logger.info(f"         timestamp: {response.timestamp}")
            
            if response.result:
                logger.info(f"         result: {response.result[:200]}..." if len(response.result) > 200 else f"         result: {response.result}")
            
            if response.error:
                logger.error(f"         error: {response.error}")
            
            # 检查响应
            if response.success:
                return {
                    "success": True,
                    "output": {
                        "result": response.result,
                        "agent_id": response.agent_id,
                        "session_id": response.session_id,
                        "execution_time_ms": response.execution_time_ms,
                        "duration_seconds": round(elapsed, 2)
                    }
                }
            else:
                error_msg = response.error if response.error else "执行失败"
                logger.error(f"      ❌ 智能体执行失败: {error_msg}")
                return {"success": False, "error": error_msg}
                
        except grpc.RpcError as e:
            logger.warning(f"      ⚠️ gRPC 错误: {e.code()} - {e.details()}")
            return {"success": False, "error": f"gRPC 错误: {e.details()}"}
        except Exception as e:
            logger.warning(f"      ⚠️ gRPC 调用失败: {e}")
            return {"success": False, "error": str(e)}