"""
Manager Agent - gRPC版本（随机端口）

职责：
1. 意图识别：判断任务是简单还是复杂
2. 任务分流：
   - 简单任务：通过ZK发现并调用单个Agent
   - 复杂任务：通过ZK发现并编排多个Agent协作
3. 统一审计：记录所有会话和执行结果

通过Zookeeper自动发现和调用Worker Agents，无需硬编码端口。
"""

import argparse
import json
import logging
import re
import socket
import sys
import time
import httpx
import asyncio
import threading
from concurrent import futures
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import grpc

# 添加项目路径（必须放在项目内部 import 之前）
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src" / "core" / "grpc"))
LOG_DIR = PROJECT_ROOT / "logs"

# 统一日志模块（移到 sys.path 设置之后）
from src.utils.logging_setup import setup_root_logging
LOG_DIR.mkdir(parents=True, exist_ok=True)

from src.gateway.grpc import dfecrab_pb2
from src.gateway.grpc import dfecrab_pb2_grpc
from src.gateway.grpc.zk_registry import ZKServiceRegistry, ZKServiceDiscovery
from src.gateway.grpc.port_allocator import get_available_port, release_port
from src.memory.long_term import MemoryManager

# 配置日志（统一封装：启动 Banner、单文件滚动、第三方库降级）
setup_root_logging(LOG_DIR / "manager_agent.log", service_name="manager_agent")

logger = logging.getLogger(__name__)


# 审计日志目录
AUDIT_DIR = PROJECT_ROOT / "data" / "tasks" / "audit"

# 线程局部用户上下文：gRPC 同步 handler 在多线程下执行，
# 用 threading.local 保存当前请求的 user_id，供 _call_agent_grpc 透传到 Worker。
_thread_local_user = threading.local()


def _get_local_ip(peer_host: str, peer_port: int = 2181) -> str:
    """
    获取本机对外可达的内网 IP。
    向 ZK 地址发起 UDP connect（不实际发包），让内核选出出口网卡。
    失败则回退 127.0.0.1。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((peer_host, peer_port))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

def _get_current_user_id() -> str:
    """获取当前线程请求的用户 ID（由 Chat/ChatStream 设置）"""
    return getattr(_thread_local_user, "user_id", "") or ""


class ManagerAgentServiceImpl(dfecrab_pb2_grpc.ManagerServiceServicer):
    """Manager Agent gRPC服务实现"""
    
    def __init__(self, zk_hosts: str = None):
        from src.config.config_loader import config as _cfg
        if zk_hosts is None:
            zk_hosts = _cfg.zk_hosts
        # 记忆管理器（统一管理短期、长期、全局记忆）
        self.memory_mgr = MemoryManager(agent_id="manager_agent")
        
        self.session_history: Dict[str, List[Dict]] = {}
        self._max_session_history: int = 500  # 最大 session 数，超出后 LRU 淘汰
        self._session_last_access: Dict[str, float] = {}  # session 最后访问时间
        self.audit_logs: List[Dict] = []
        
        # 加载Agent配置（快速加载，不等待模型检查）
        self.config = self._load_config()
        self.llm_config = {}  # 先置空，后台异步加载
        self._alive_model_configs = []  # 先置空，后台异步加载
        
        # 动态Agent描述缓存（启动时扫描所有agents目录）
        self._agent_descriptions: Dict[str, str] = {}
        self._last_refresh_time: float = 0
        self._refresh_interval: float = 5.0
        self._agents_dir_mtime: float = 0
        self._agents_dir_snapshot: Dict[str, float] = {}
        self._reload_agent_descriptions()
        
        # Zookeeper服务发现
        self.zk_discovery = ZKServiceDiscovery(zk_hosts=zk_hosts)
        self.zk_registry = ZKServiceRegistry(zk_hosts=zk_hosts)
        
        # 连接Zookeeper
        if not self.zk_discovery.connect():
            logger.error("❌ Zookeeper服务发现连接失败")
        if not self.zk_registry.connect():
            logger.error("❌ Zookeeper服务注册连接失败")
        
        # 创建审计日志目录
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        
        logger.info("🧠 Manager Agent Service初始化完成")
        logger.info(f"🔍 Zookeeper: {zk_hosts}")
        logger.info(f"💾 记忆管理器已初始化")
        
        # 后台异步加载模型配置（不阻塞启动）
        threading.Thread(target=self._async_load_llm_config, daemon=True).start()
        logger.info("🔄 模型配置将在后台异步加载...")
        


    
    def Chat(self, request, context):
        """聊天接口（同步版本，因为gRPC handler不支持async）"""
        try:
            _thread_local_user.user_id = request.user_id or ""
            message = request.message
            session_id = request.session_id if request.session_id else f"session_{uuid4().hex[:12]}"

            # ── 检测内部命令：Agent描述重新加载 ──
            if message and message.strip().startswith('__INTERNAL__:'):
                return self._handle_internal_command(message, session_id)

            logger.info(f"\n{'='*60}")
            logger.info(f"📨 收到聊天请求 [Session: {session_id}]")
            logger.info(f"💬 内容: {message}")

            # 处理消息
            result = self.process_message(message, session_id)
            
            # 返回响应
            # 确保 timestamp 是字符串格式（符合 protobuf 定义）
            import time
            timestamp = str(int(time.time()))
            
            payload = {
                "message": result.get("message", ""),
                "structured": result.get("structured"),
                "manager_think": result.get("manager_think", ""),
                "execution_flow": result.get("execution_flow", [])
            }
            return dfecrab_pb2.ChatResponse(
                success=bool(result.get("success", False)),
                session_id=str(result.get("session_id", session_id)),
                message=json.dumps(payload, ensure_ascii=False),
                task_type=str(result.get("task_type", "unknown")),
                agents_used=[str(a) for a in result.get("agents_used", [])],
                audit_log_id=str(result.get("audit_log_id", "")),
                error=str(result.get("error", "")),
                timestamp=timestamp
            )
            
        except Exception as e:
            logger.error(f"❌ 聊天处理失败: {e}")
            import traceback
            traceback.print_exc()
            
            return dfecrab_pb2.ChatResponse(
                success=False,
                session_id=request.session_id or f"session_{uuid4().hex[:12]}",
                message=f"处理失败: {str(e)}",
                task_type="error",
                agents_used=[],
                audit_log_id="",
                error=str(e),
                timestamp=datetime.now().isoformat()
            )
    
    def ChatStream(self, request, context):
        """流式聊天接口（server streaming）"""
        try:
            _thread_local_user.user_id = request.user_id or ""
            message = request.message
            session_id = request.session_id if request.session_id else f"session_{uuid4().hex[:12]}"

            # ── 检测内部命令 ──
            if message and message.strip().startswith('__INTERNAL__:'):
                response = self._handle_internal_command(message, session_id)
                yield dfecrab_pb2.StreamChatResponse(
                    final=response
                )
                return

            logger.info(f"\n{'='*60}")
            logger.info(f"📨 收到流式聊天请求 [Session: {session_id}]")
            logger.info(f"💬 内容: {message}")
            
            # 发送流开始事件
            yield dfecrab_pb2.StreamChatResponse(
                start=dfecrab_pb2.StreamStart(session_id=session_id)
            )
            
            # 处理消息（流式版本）
            for event in self.process_message_stream(request.message, session_id):
                yield event
            
        except Exception as e:
            logger.error(f"❌ 流式聊天处理失败: {e}")
            import traceback
            traceback.print_exc()
            yield dfecrab_pb2.StreamChatResponse(
                error=dfecrab_pb2.StreamError(message=f"处理失败: {str(e)}")
            )
    
    def ManagerHealth(self, request, context):
        """健康检查"""
        # 从Zookeeper获取Worker数量
        workers = self.zk_discovery.discover_service("worker_agent")
        
        return dfecrab_pb2.ManagerHealthStatus(
            healthy=True,
            service="manager_agent",
            worker_count=len(workers),
            session_count=len(self.session_history),
            timestamp=datetime.now().isoformat()
        )
    
    def process_message(self, message: str, session_id: str) -> Dict:
        """
        处理用户消息（非流式版本，供 Chat() RPC 调用）

        流程：
        1. 记录到短期记忆（session交互）
        2. 意图识别 - 判断简单/复杂任务（非流式 + json_object）
        3. 任务分流 - 选择执行策略
        4. 执行任务 - 通过Zookeeper发现并调用Worker Agents
        5. 记录审计 - 保存执行日志
        6. 更新长期记忆 - 从任务中学习经验
        
        注意：此方法不可含 yield 语句，否则会变成生成器，
        导致 Chat() RPC 的调用方拿到生成器对象而不是 Dict。
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🧠 [Manager] 开始处理消息")
        logger.info(f"   ├─ Session ID: {session_id}")
        logger.info(f"   ├─ 消息长度: {len(message)} 字符")
        logger.info(f"   └─ 消息内容: {message}")

        # 0. 任务开始时强制探活，确定这轮对话使用哪个模型
        logger.info("   🔍 正在探测大模型存活状态...")
        self.llm_config = self._load_llm_config()
        self._alive_model_configs = self._load_all_alive_configs()
        if not self.llm_config:
            logger.error("   ❌ 无法获取可用的模型配置，将触发强制降级逻辑")
        else:
            logger.info(f"   ✅ 本轮对话已锁定使用模型: {self.llm_config.get('model_name', 'unknown')}")

        # 1. 记录用户消息到短期记忆
        logger.info(f"📝 [Manager] 步骤1: 记录用户消息到短期记忆")
        self.memory_mgr.add_to_short_term(session_id, {
            "role": "user",
            "content": message
        })
        
        # 初始化session历史（兼容性保留）
        if session_id not in self.session_history:
            self.session_history[session_id] = []
        self.session_history[session_id].append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat()
        })
        self._session_last_access[session_id] = time.time()
        self._trim_session_history()

        # 2. 意图识别 — 非流式版本（使用 json_object 确保纯JSON输出）
        logger.info(f"🔍 [Manager] 步骤2: 意图识别（非流式 + json_object）")

        dynamic_prompt = self._build_dynamic_system_prompt()
        
        # ★ [修复] 使用非流式意图识别（response_format=json_object），
        #    绝不使用流式 yield，确保方法正确返回 Dict 而非生成器对象
        clean_message = self._clean_user_message(message)
        prompt = f"""用户消息：{clean_message}

分析用户意图，输出纯JSON（禁止<think>/Markdown/额外文字）：

输出格式（字段名必须完全一致，禁止用 target/agent/agent_id 替代 target_agent）：
1. simple/chat（Manager直接回复）：
{{"type":"simple","category":"chat","reason":"理由"}}

2. simple/其他（1个Agent）：
{{"type":"simple","category":"query","target_agent":"agent_id","reason":"理由"}}

3. complex（≥2个Agent协作）：
{{"type":"complex","category":"xxx","reason":"理由","workflow":{{"steps":[{{"agent":"xxx","action":"xxx","description":"xxx"}},...]}}}}

分类说明：
- category=chat: 问候/闲聊/知识问答/感谢，Manager直接回复，无target_agent
- category=query: 需要查询数据，根据system_prompt中的路由规则选择合适的Agent
- category=file: 文件操作
- 其他情况根据system_prompt中的Agent能力和路由规则选择合适的Agent

规则：
- 步骤越少越好，能用1步不用2步
- 不确定→simple/chat
- 严格按照 system_prompt 中的路由规则选择Agent
- 只输出JSON，不要任何其他内容
- ⭐ crucial: simple非chat时，target_agent和category必须同时出现，缺一不可
- ⭐ crucial: 字段名必须是 target_agent，绝对禁止用 target、agent、agent_id 等别名"""

        system_prompt = self._truncate_agent_list(dynamic_prompt, max_chars=2000)
        intent = self._call_llm_with_fallback(prompt, system_prompt, response_format={"type": "json_object"})
        
        if intent:
            intent = self._parse_intent_json(intent)
            intent = self._normalize_intent_aliases(intent)
            intent = self._validate_intent_agents(intent)

        if not intent:
            intent = {"type": "simple", "category": "chat", "reason": "意图识别失败，降级为chat"}

        task_type = intent.get('type', 'unknown')
        category = intent.get('category', '')
        logger.info(f"   ├─ 类型: {task_type}")
        logger.info(f"   ├─ 分类: {category}")
        logger.info(f"   ├─ 原因: {intent.get('reason', 'N/A')}")
        if task_type == 'complex' and 'workflow' in intent:
            steps = intent['workflow'].get('steps', [])
            logger.info(f"   └─ 工作流步骤: {len(steps)} 个")
            for idx, step in enumerate(steps, 1):
                logger.info(f"      {idx}. {step.get('agent')} - {step.get('action', 'N/A')}")
        elif task_type == 'simple' and category != 'chat':
            logger.info(f"   └─ 目标智能体: {intent.get('target_agent', 'N/A')}")
        else:
            logger.info(f"   └─ 无额外参数")

        # 3. 任务分流和执行
        logger.info(f"⚙️ [Manager] 步骤3: 任务分流和执行")
        result = self._dispatch_and_execute(intent, message, session_id)
        
        logger.info(f"✅ [Manager] 任务执行完成")
        logger.info(f"   ├─ 任务类型: {result.get('task_type')}")
        logger.info(f"   ├─ 成功: {result.get('success')}")
        logger.info(f"   ├─ 使用智能体: {result.get('agents_used', [])}")
        if result.get('success'):
            logger.info(f"   └─ 结果摘要: {str(result.get('message', ''))[:150]}...")
        else:
            logger.error(f"   └─ 错误: {result.get('message', 'Unknown error')}")
        
        # 4. 记录审计日志
        logger.info(f"📋 [Manager] 步骤4: 记录审计日志")
        audit_id = self._save_audit_log(session_id, message, intent, result)
        logger.info(f"   └─ 审计日志ID: {audit_id}")

        # 5. 记录AI响应到短期记忆
        logger.info(f"💾 [Manager] 步骤5: 记录AI响应到短期记忆")
        response_message = result.get("message", "")
        self.memory_mgr.add_to_short_term(session_id, {
            "role": "assistant",
            "content": response_message
        })
        self.session_history[session_id].append({
            "role": "assistant",
            "content": response_message,
            "timestamp": datetime.now().isoformat()
        })

        # 6. 更新长期记忆（从任务中学习）
        logger.info(f"🧠 [Manager] 步骤6: 更新长期记忆")
        self._learn_from_task(message, intent, result)

        logger.info(f"🎉 [Manager] 消息处理完成")
        logger.info(f"{'='*80}\n")

        return {
            "success": result.get("success", False),
            "session_id": session_id,
            "message": response_message,
            "structured": result.get("structured"),
            "task_type": result.get("task_type"),
            "agents_used": result.get("agents_used", []),
            "manager_think": result.get("manager_think", ""),
            "execution_flow": result.get("execution_flow", []),
            "audit_log_id": audit_id,
            "timestamp": datetime.now().isoformat()
        }
    def process_message_stream(self, message: str, session_id: str):
        """
        流式处理用户消息
        
        返回 StreamChatResponse 事件生成器
        """
        logger.info(f"\n{'='*80}")
        logger.info(f"🧠 [Manager] 开始流式处理消息")
        logger.info(f"   ├─ Session ID: {session_id}")
        logger.info(f"   ├─ 消息长度: {len(message)} 字符")
        logger.info(f"   └─ 消息内容: {message}")

        # 0. 任务开始时强制探活，确定这轮对话使用哪个模型
        logger.info("   🔍 正在探测大模型存活状态...")
        self.llm_config = self._load_llm_config()
        self._alive_model_configs = self._load_all_alive_configs()
        if not self.llm_config:
            logger.error("   ❌ 无法获取可用的模型配置，将触发强制降级逻辑")
        else:
            logger.info(f"   ✅ 本轮对话已锁定使用模型: {self.llm_config.get('model_name', 'unknown')}")

        # 1. 记录用户消息到短期记忆
        logger.info(f"📝 [Manager] 步骤1: 记录用户消息到短期记忆")
        self.memory_mgr.add_to_short_term(session_id, {
            "role": "user",
            "content": message
        })
        
        # 初始化session历史（兼容性保留）
        if session_id not in self.session_history:
            self.session_history[session_id] = []
        self.session_history[session_id].append({
            "role": "user",
            "content": message,
            "timestamp": datetime.now().isoformat()
        })
        self._session_last_access[session_id] = time.time()
        self._trim_session_history()

        # 2. 意图识别 — 流式版本
        logger.info(f"🔍 [Manager] 步骤2: 意图识别（流式）")

        # ★ 检测并剥离 Gateway 预分析结果（兼容旧版 Gateway，但不再跳过 thinking）
        intent_prefix = "__INTENT__:"
        intent_from_gateway = None
        if message.startswith(intent_prefix):
            newline_idx = message.find("\n\n")
            if newline_idx != -1:
                try:
                    intent_json_str = message[len(intent_prefix):newline_idx]
                    intent_from_gateway = json.loads(intent_json_str)
                    # 剥离头部，保留真实用户消息
                    message = message[newline_idx+2:]
                    logger.debug(f"📦 [Manager] 收到 Gateway 预分析结果（作为参考）: {intent_from_gateway.get('type')}/{intent_from_gateway.get('category')}")
                except Exception as e:
                    logger.warning(f"⚠️ [Manager] 解析 Gateway intent 失败: {e}")

        # ✅ 始终走 LLM thinking 流程（Manager 回归核心职责）
        # 先发 think_start
        yield dfecrab_pb2.StreamChatResponse(
            step=dfecrab_pb2.AgentStep(
                step=0, agent="manager_agent", action="think_start",
                answer="正在分析用户意图...",
                timestamp=datetime.now().isoformat()
            )
        )

        # 流式调用 LLM 做意图识别
        dynamic_prompt = self._build_dynamic_system_prompt()
        intent = None
        reasoning_event_count = 0
        for stream_event in self._call_llm_for_intent_stream_yield(message, dynamic_prompt):
            if stream_event["type"] == "reasoning":
                reasoning_event_count += 1
                if reasoning_event_count <= 3:  # 只记录前3个事件
                    logger.debug(f"💭 [Think] reasoning #{reasoning_event_count}: {stream_event['content'][:50]}")
                yield dfecrab_pb2.StreamChatResponse(
                    step=dfecrab_pb2.AgentStep(
                        step=0, agent="manager_agent", action="think",
                        answer=stream_event["content"],
                        timestamp=datetime.now().isoformat()
                    )
                )
            elif stream_event["type"] == "done":
                logger.info(f"💭 [Think] 共输出 {reasoning_event_count} 个 reasoning 事件")
                # 发 think_end
                yield dfecrab_pb2.StreamChatResponse(
                    step=dfecrab_pb2.AgentStep(
                        step=0, agent="manager_agent", action="think_end",
                        answer=stream_event.get("reasoning", ""),
                        timestamp=datetime.now().isoformat()
                    )
                )
                intent = stream_event["intent"]
                break

        if not intent:
            # 如果 LLM thinking 失败，使用 Gateway 预分析结果作为降级
            if intent_from_gateway:
                intent = intent_from_gateway
                logger.info(f"🔄 [Manager] LLM thinking 失败，使用 Gateway 预分析结果降级")
            else:
                intent = {"type": "simple", "category": "chat", "reason": "意图识别失败，降级为chat"}

        task_type = intent.get('type', 'unknown')
        category = intent.get('category', '')
        logger.info(f"   ├─ 类型: {task_type}")
        logger.info(f"   ├─ 分类: {category}")
        logger.info(f"   ├─ 原因: {intent.get('reason', 'N/A')}")
        if task_type == 'complex' and 'workflow' in intent:
            steps = intent['workflow'].get('steps', [])
            logger.info(f"   └─ 工作流步骤: {len(steps)} 个")
            for idx, step in enumerate(steps, 1):
                logger.info(f"      {idx}. {step.get('agent')} - {step.get('action', 'N/A')}")
        elif task_type == 'simple' and category != 'chat':
            logger.info(f"   └─ 目标智能体: {intent.get('target_agent', 'N/A')}")
        else:
            logger.info(f"   └─ 无额外参数")

        # 3. 任务分流和执行（流式版本）
        logger.info(f"⚙️ [Manager] 步骤3: 任务分流和执行（流式）")
        final_event = None
        error_event = None
        for event in self._dispatch_and_execute_stream(intent, message, session_id):
            if event.HasField('final'):
                final_event = event
            elif event.HasField('error'):
                # 错误事件直接透传，但继续循环检查是否有 final
                yield event
                error_event = event
                logger.warning(f"⚠️ [Manager] 收到错误事件，继续等待最终结果...")
            else:
                yield event
        
        # 如果没有 final 事件但有 error 事件，构造一个失败的 result
        if not final_event and error_event:
            logger.info(f"📋 [Manager] 步骤4: 任务执行出错，构造错误结果")
            # 从 error 事件中提取错误信息
            error_msg = error_event.error.message if error_event.HasField('error') else "未知错误"
            result = {
                "success": False,
                "message": error_msg,
                "task_type": task_type,
                "agents_used": [intent.get('target_agent', 'unknown')],
                "error": error_msg,
            }
            
            # 5. 更新长期记忆（从任务中学习 - 失败教训）
            logger.info(f"🧠 [Manager] 步骤5: 更新长期记忆（失败教训）")
            self._learn_from_task(message, intent, result)
            
            logger.info(f"🎉 [Manager] 流式消息处理完成（出错）")
            logger.info(f"{'='*80}\n")
            return

        # 4-6. 流结束后执行审计日志、记忆更新和长期记忆学习
        if final_event:
            result = {
                "success": final_event.final.success,
                "message": final_event.final.message,
                "task_type": final_event.final.task_type,
                "agents_used": list(final_event.final.agents_used),
                "error": final_event.final.error,
            }

            # 4. 记录审计日志
            logger.info(f"📋 [Manager] 步骤4: 记录审计日志")
            audit_id = self._save_audit_log(session_id, message, intent, result)
            logger.info(f"   └─ 审计日志ID: {audit_id}")

            # 5. 记录AI响应到短期记忆
            logger.info(f"💾 [Manager] 步骤5: 记录AI响应到短期记忆")
            response_message = final_event.final.message
            self.memory_mgr.add_to_short_term(session_id, {
                "role": "assistant",
                "content": response_message
            })
            self.session_history[session_id].append({
                "role": "assistant",
                "content": response_message,
                "timestamp": datetime.now().isoformat()
            })

            # 6. 更新长期记忆（从任务中学习）
            logger.info(f"🧠 [Manager] 步骤6: 更新长期记忆")
            self._learn_from_task(message, intent, result)

            # 发送包含 audit_log_id 的最终事件
            yield dfecrab_pb2.StreamChatResponse(
                final=dfecrab_pb2.ChatResponse(
                    success=final_event.final.success,
                    session_id=final_event.final.session_id,
                    message=final_event.final.message,
                    task_type=final_event.final.task_type,
                    agents_used=final_event.final.agents_used,
                    audit_log_id=audit_id,
                    error=final_event.final.error,
                    timestamp=datetime.now().isoformat()
                )
            )
        else:
            logger.warning(f"⚠️ [Manager] 未收到最终事件")
            yield dfecrab_pb2.StreamChatResponse(
                error=dfecrab_pb2.StreamError(message="未收到任务执行结果")
            )

        logger.info(f"🎉 [Manager] 流式消息处理完成")
        logger.info(f"{'='*80}\n")
    
    def _load_config(self) -> Dict:
        """加载 Manager Agent 配置"""
        config_file = PROJECT_ROOT / "agents" / "manager_agent" / "config.json"
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"agent_id": "manager_agent"}

    def _async_load_llm_config(self):
        """后台异步加载模型配置（不阻塞启动）"""
        try:
            logger.info("🔄 [Manager] 开始后台加载模型配置...")
            self.llm_config = self._load_llm_config()
            self._alive_model_configs = self._load_all_alive_configs()
            # ★ 新增：初始化 LLMService
            self._init_llm_service()
            if self.llm_config:
                logger.info(f"✅ [Manager] 模型配置加载完成: {self.llm_config.get('model_name', 'unknown')}")
            else:
                logger.warning("⚠️ [Manager] 模型配置加载失败，请求时将重试")
        except Exception as e:
            logger.error(f"❌ [Manager] 模型配置加载异常: {e}")

    def _init_llm_service(self):
        """初始化 LLMService（统一适配器）"""
        try:
            from src.agent.llm.service import LLMService
            if self.llm_config and self.llm_config.get("api_base"):
                self._llm_service = LLMService(self.llm_config)
                logger.info(f"✅ [Manager] LLMService 初始化成功")
            else:
                self._llm_service = None
                logger.warning("⚠️ [Manager] 无可用配置，LLMService 未初始化")
        except Exception as e:
            logger.error(f"❌ [Manager] LLMService 初始化失败: {e}")
            self._llm_service = None

    def _load_llm_config(self) -> Dict:
        """加载 LLM 配置：优先 agent 指定模型 → 探活 → fallback chain"""
        from src.services.model_manager import model_manager
        
        # 第1步：读 agent config.json 的 model_config，默认 qwen3
        preferred_model = self.config.get("model_config", "qwen3")
        logger.info(f"🔍 [Manager] 优先使用模型: {preferred_model}")
        
        # 第2步：在 model_providers 中查找并探活
        provider_cfg = model_manager.get_provider_config(preferred_model)
        if provider_cfg and provider_cfg.get("enabled", False):
            if model_manager._check_alive(provider_cfg, verify_content=True):
                logger.info(f"✅ [Manager] 指定模型 {preferred_model} 存活，使用")
                return {
                    "api_base": provider_cfg.get("api_base", ""),
                    "model_name": provider_cfg.get("model_name", ""),
                    "timeout": provider_cfg.get("timeout", 600),
                    "max_tokens": provider_cfg.get("max_tokens", 2048),
                    "api_key": provider_cfg.get("api_key", "not-needed"),
                    "think_config": provider_cfg.get("think_config", {})
                }
            else:
                logger.warning(f"⚠️ [Manager] 指定模型 {preferred_model} 探活失败，进入 fallback")
        else:
            logger.info(f"ℹ️ [Manager] 指定模型 {preferred_model} 未在 model_providers 中找到，进入 fallback")
        
        # 第3步：fallback — 按 fallback chain 依次探活
        alive_configs = model_manager.get_all_alive_configs()
        if alive_configs:
            fallback = alive_configs[0]
            logger.info(f"✅ [Manager] 降级使用模型: {fallback.get('name', 'unknown')}")
            return {
                "api_base": fallback.get("api_base", ""),
                "model_name": fallback.get("model_name", ""),
                "timeout": fallback.get("timeout", 600),
                "max_tokens": fallback.get("max_tokens", 2048),
                "api_key": fallback.get("api_key", "not-needed"),
                "think_config": fallback.get("think_config", {})
            }
        
        logger.error("❌ [Manager] 所有模型均无法连接！Manager 必须降级运行")
        return {}

    def _load_all_alive_configs(self) -> List[Dict]:
        """加载所有存活的模型配置列表（用于请求级 fallback 轮询）"""
        from src.services.model_manager import model_manager
        
        alive_configs = model_manager.get_all_alive_configs()
        if not alive_configs:
            logger.error("❌ 无任何存活模型配置")
            return []
        
        result = []
        for cfg in alive_configs:
            result.append({
                "name": cfg.get("name", "unknown"),
                "api_base": cfg.get("api_base", ""),
                "model_name": cfg.get("model_name", ""),
                "timeout": cfg.get("timeout", 600),
                "max_tokens": cfg.get("max_tokens", 2048),
                "api_key": cfg.get("api_key", "not-needed")
            })
        
        alive_names = [c["name"] for c in result]
        logger.info(f"📋 请求级 fallback 可用模型: {alive_names}")
        return result

    def _scan_agent_descriptions(self) -> Dict[str, Dict]:
        """扫描 agents/ 目录，提取每个 Agent 的完整描述信息"""
        descriptions = {}
        agents_dir = PROJECT_ROOT / "agents"
        if not agents_dir.exists():
            logger.warning("⚠️ agents 目录不存在")
            return descriptions

        # 优先从 agents_index.json 读取描述
        index_file = PROJECT_ROOT / "config" / "agents_index.json"
        index_info = {}
        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                    index_info = index_data.get("agents", {})
            except Exception as e:
                logger.warning(f"⚠️ 读取 {index_file} 失败: {e}")

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            config_file = agent_dir / "config.json"
            if not config_file.exists():
                continue
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                aid = cfg.get("agent_id", "")
                if not aid or aid == "manager_agent":
                    continue
                
                # 从 index 获取详细信息，没有则从 config.json 获取
                index_entry = index_info.get(aid, {})
                descriptions[aid] = {
                    "name": index_entry.get("name", cfg.get("name", aid)),
                    "description": index_entry.get("description", cfg.get("description", "") or cfg.get("name", aid)),
                    "icon": index_entry.get("icon", cfg.get("icon", "🤖")),
                    "agent_type": cfg.get("agent_type", "worker"),
                    "skills": index_entry.get("skills", cfg.get("skills", [])),
                }
            except Exception as e:
                logger.warning(f"⚠️ 读取 {config_file} 失败: {e}")
                continue
        logger.info(f"📋 扫描到 {len(descriptions)} 个可用 Agent")
        return descriptions

    def _reload_agent_descriptions(self) -> None:
        """重新加载所有 Agent 描述"""
        self._agent_descriptions = self._scan_agent_descriptions()
        logger.info(f"✅ 已重新加载 Agent 描述，共 {len(self._agent_descriptions)} 个")

    def _build_agent_list_prompt(self) -> str:
        """构建可调用 Agent 列表字符串，包含描述信息"""
        parts = []
        for aid, info in self._agent_descriptions.items():
            icon = info.get("icon", "🤖")
            name = info.get("name", aid)
            desc = info.get("description", "")
            parts.append(f"{icon} {aid}({name}): {desc}")
        return "\n".join(parts)

    def _build_dynamic_system_prompt(self) -> str:
        """构建动态系统提示词：优先替换 {{AGENT_LIST}} 占位符，兼容旧【可调用Agent】格式"""
        base_prompt = self.config.get("system_prompt", "")
        agent_list = self._build_agent_list_prompt()

        if "{{AGENT_LIST}}" in base_prompt:
            return base_prompt.replace("{{AGENT_LIST}}", agent_list)

        # 兼容旧格式：从基础 prompt 中替换【可调用Agent】部分
        lines = base_prompt.split('\n')
        new_lines = []
        in_agent_section = False
        for line in lines:
            if '【可调用Agent】' in line:
                in_agent_section = True
                new_lines.append(line)
                new_lines.append(agent_list)
                continue
            if in_agent_section:
                if line.startswith('【'):
                    in_agent_section = False
                    new_lines.append(line)
                else:
                    continue
            else:
                new_lines.append(line)

        return '\n'.join(new_lines)

    def _get_current_think_config(self) -> Dict:
        """获取当前模型的思考标签配置
        
        优先级：
        1. 当前 llm_config 中的 think_config（如果有）
        2. 全局 dfecrab.json 中的 think_config
        3. 默认配置
        """
        # 默认配置
        default_config = {
            "start_tags": ["<think>", "<thinking>"],
            "end_tags": ["思考标签", "</thinking>", "</think>"],
            "reasoning_fields": ["reasoning_content", "reasoning"],
            "max_tag_len": 20
        }
        
        # 1. 检查 llm_config 中是否有 think_config
        model_think_config = self.llm_config.get("think_config", {})
        if model_think_config:
            result = {
                "start_tags": model_think_config.get("start_tags", default_config["start_tags"]),
                "end_tags": model_think_config.get("end_tags", default_config["end_tags"]),
                "reasoning_fields": model_think_config.get("reasoning_fields", default_config["reasoning_fields"]),
                "max_tag_len": model_think_config.get("max_tag_len", default_config["max_tag_len"])
            }
            return result
        
        # 2. 检查全局配置
        try:
            from src.config.config_loader import config as _cfg
            global_think_config = _cfg.config_data.get("think_config", {})
            if global_think_config:
                result = {
                    "start_tags": global_think_config.get("start_tags", default_config["start_tags"]),
                    "end_tags": global_think_config.get("end_tags", default_config["end_tags"]),
                    "reasoning_fields": global_think_config.get("reasoning_fields", default_config["reasoning_fields"]),
                    "max_tag_len": global_think_config.get("max_tag_len", default_config["max_tag_len"])
                }
                return result
        except Exception:
            pass
        
        # 3. 返回默认配置
        return default_config

    def _get_model_think_config(self, model_config: Dict) -> Dict:
        """根据模型配置获取对应的 think_config
        
        在模型配置中查找 think_config，如果没有则使用全局配置
        """
        default_config = {
            "start_tags": ["<think>", "<thinking>"],
            "end_tags": ["思考标签", "</thinking>", "</think>"],
            "reasoning_fields": ["reasoning_content", "reasoning"],
            "max_tag_len": 20
        }
        
        # 检查模型配置中的 think_config
        model_think_config = model_config.get("think_config", {})
        if model_think_config:
            return {
                "start_tags": model_think_config.get("start_tags", default_config["start_tags"]),
                "end_tags": model_think_config.get("end_tags", default_config["end_tags"]),
                "reasoning_fields": model_think_config.get("reasoning_fields", default_config["reasoning_fields"]),
                "max_tag_len": model_think_config.get("max_tag_len", default_config["max_tag_len"])
            }
        
        # 回退到全局配置
        return self._get_current_think_config()

    async def _call_llm_async(self, prompt: str, system_prompt: str = "", response_format: Optional[Dict] = None) -> str:
        if not self.llm_config.get("api_base"):
            return None
        api_base = self.llm_config["api_base"]
        model_name = self.llm_config.get("model_name", "default")
        timeout = self.llm_config.get("timeout", 600)
        max_tokens = self.llm_config.get("max_tokens", 2048)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        url = f"{api_base}/chat/completions"
        payload = {"model": model_name, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
        if response_format:
            payload["response_format"] = response_format
        headers = {"Content-Type": "application/json"}
        if self.llm_config.get("api_key") and self.llm_config["api_key"] != "not-needed":
            headers["Authorization"] = f"Bearer {self.llm_config['api_key']}"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"❌ LLM API call failed: {e}")
        return None

    async def _call_llm_async_stream(self, prompt: str, system_prompt: str = ""):
        """流式调用 LLM，逐个 yield {"token": str, "reasoning": str}
        
        统一处理多模型思考格式：
        1. reasoning_content 字段（标准格式）
        2. content 字段中的标签包裹（如 <think>...思考标签）
        3. 标签可能被拆分到多个 chunk，需要用 buffer 累积检测
        """
        if not self.llm_config.get("api_base"):
            return
        api_base = self.llm_config["api_base"]
        model_name = self.llm_config.get("model_name", "default")
        timeout = self.llm_config.get("timeout", 600)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        url = f"{api_base}/chat/completions"
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2048,
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        if self.llm_config.get("api_key") and self.llm_config["api_key"] != "not-needed":
            headers["Authorization"] = f"Bearer {self.llm_config['api_key']}"
        
        # ★ 从配置获取当前模型的思考标签配置
        think_config = self._get_current_think_config()
        start_tags = think_config["start_tags"]
        end_tags = think_config["end_tags"]
        reasoning_fields = think_config["reasoning_fields"]
        max_tag_len = think_config["max_tag_len"]
        
        logger.debug(f"🧠 [ThinkConfig] start_tags={start_tags}, end_tags={end_tags}, reasoning_fields={reasoning_fields}")
        
        # 状态机变量
        in_think = False        # 当前是否在思考模式
        tag_buffer = ""        # 用于检测被拆分的标签
        reasoning_count = 0    # 统计 reasoning 事件数量
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            # 流结束
                            if tag_buffer:
                                # 输出缓冲区剩余内容
                                if in_think:
                                    reasoning_count += 1
                                    yield {"token": "", "reasoning": tag_buffer}
                                else:
                                    yield {"token": tag_buffer, "reasoning": ""}
                                    tag_buffer = ""
                            logger.debug(f"📦 [Stream] 流结束，共输出 {reasoning_count} 个 reasoning 事件")
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content", "")
                            
                            # ★ 1. 处理标准格式的 reasoning_content 字段
                            reasoning = ""
                            for field in reasoning_fields:
                                val = delta.get(field, "")
                                if val:
                                    reasoning = val
                                    break
                            
                            if reasoning:
                                reasoning_count += 1
                                yield {"token": "", "reasoning": reasoning}
                                continue
                            
                            # 空 token 跳过
                            if not token:
                                continue
                            
                            # ========== 2. 处理 content 中的思考标签格式 ==========
                            # 将新 token 加入缓冲区
                            combined = tag_buffer + token
                            
                            # 检查缓冲区中是否包含完整的标签
                            while combined:
                                # 检查所有开始标签
                                found_start_idx = -1
                                found_start_tag = None
                                for start_tag in start_tags:
                                    idx = combined.lower().find(start_tag.lower())
                                    if idx >= 0 and (found_start_idx == -1 or idx < found_start_idx):
                                        found_start_idx = idx
                                        found_start_tag = start_tag
                                
                                # 检查所有结束标签
                                found_end_idx = -1
                                found_end_tag = None
                                for end_tag in end_tags:
                                    idx = combined.lower().find(end_tag.lower())
                                    if idx >= 0 and (found_end_idx == -1 or idx < found_end_idx):
                                        found_end_idx = idx
                                        found_end_tag = end_tag
                                
                                # 找到开始标签
                                if found_start_idx >= 0:
                                    before = combined[:found_start_idx]
                                    if before:
                                        if in_think:
                                            reasoning_count += 1
                                            yield {"token": "", "reasoning": before}
                                        else:
                                            yield {"token": before, "reasoning": ""}
                                    combined = combined[found_start_idx + len(found_start_tag):]
                                    in_think = True
                                    tag_buffer = ""
                                    continue
                                
                                # 找到结束标签
                                if found_end_idx >= 0:
                                    before = combined[:found_end_idx]
                                    if before:
                                        reasoning_count += 1
                                        yield {"token": "", "reasoning": before}
                                    combined = combined[found_end_idx + len(found_end_tag):]
                                    in_think = False
                                    tag_buffer = ""
                                    continue
                                
                                # 没有找到完整标签，检查是否可能是被拆分的标签
                                possible_split = False
                                all_tags = start_tags + end_tags
                                for tag in all_tags:
                                    lower_combined = combined.lower()
                                    for i in range(1, min(len(tag), max_tag_len) + 1):
                                        if lower_combined.endswith(tag[:i].lower()):
                                            split_point = len(combined) - i
                                            tag_buffer = combined[split_point:]
                                            combined = combined[:split_point]
                                            possible_split = True
                                            break
                                    if possible_split:
                                        break
                                
                                if not possible_split:
                                    # 不是标签的一部分，可以安全输出
                                    if combined:
                                        if in_think:
                                            reasoning_count += 1
                                            yield {"token": "", "reasoning": combined}
                                        else:
                                            yield {"token": combined, "reasoning": ""}
                                    tag_buffer = ""
                                    combined = ""
                                    break
                                else:
                                    # 输出前面的内容，保留可能是标签的部分
                                    if combined:
                                        if in_think:
                                            reasoning_count += 1
                                            yield {"token": "", "reasoning": combined}
                                        else:
                                            yield {"token": combined, "reasoning": ""}
                                    combined = ""
                                    break
                            
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"❌ LLM 流式调用失败: {e}")

    async def _call_llm_async_stream_v2(self, prompt: str, system_prompt: str = ""):
        """流式调用 LLM（v2版本，使用 LLMService 适配器）
        
        与 v1 版本兼容，返回相同的格式：
        {"token": str, "reasoning": str}
        """
        # 如果 LLMService 已初始化，优先使用
        if hasattr(self, '_llm_service') and self._llm_service:
            try:
                async for event in self._llm_service.call_stream(prompt, system_prompt):
                    yield event
                return
            except Exception as e:
                logger.warning(f"⚠️ LLMService 调用失败，回退到 v1: {e}")
        
        # 回退到 v1 版本
        async for event in self._call_llm_async_stream(prompt, system_prompt):
            yield event

    def _call_llm(self, prompt: str, system_prompt: str = "", response_format: Optional[Dict] = None) -> str:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self._call_llm_async(prompt, system_prompt, response_format))
                return result
            finally:
                loop.close()
        except Exception as e:
            return None

    def _call_llm_with_fallback(self, prompt: str, system_prompt: str = "", response_format: Optional[Dict] = None) -> str:
        """请求级模型轮询：按优先级逐个尝试所有存活的模型，直到某个返回有效内容。
        
        与 session 级探活（_load_llm_config）独立：
        - _load_llm_config 只在对话开始时做一次，确定主模型
        - _call_llm_with_fallback 每次 LLM 调用都尝试所有存活模型
        - 只有所有模型都返回空/异常，才返回 None
        """
        # 先试当前主模型
        if self.llm_config.get("api_base"):
            logger.info(f"   → 尝试主模型 [{(self.llm_config.get('model_name', 'unknown'))}]")
            result = self._call_llm(prompt, system_prompt, response_format)
            if result:
                logger.info(f"   ✅ 主模型返回有效内容")
                return result
            logger.warning(f"   ⚠️ 主模型返回空，将尝试备用模型")
        
        # 再试所有备用模型
        for idx, model_cfg in enumerate(self._alive_model_configs):
            name = model_cfg.get("name", f"备用{idx}")
            api_base = model_cfg.get("api_base", "")
            model_name = model_cfg.get("model_name", "")
            
            # 跳过已经试过的主模型
            if api_base == self.llm_config.get("api_base") and \
               model_name == self.llm_config.get("model_name"):
                continue
            
            logger.info(f"   → 尝试备用模型 [{name}] ({model_name})")
            result = self._call_llm_with_config(
                prompt, system_prompt, model_cfg, response_format
            )
            if result:
                logger.info(f"   ✅ 备用模型 [{name}] 返回有效内容")
                # 自动切换主模型为当前成功的备用模型
                self.llm_config = dict(model_cfg)
                from src.services.model_manager import model_manager
                model_manager.switch_provider(name)
                return result
            logger.warning(f"   ⚠️ 备用模型 [{name}] 返回空，继续尝试下一个")
        
        logger.error("❌ 所有模型均返回空，fallback 失败")
        return None

    def _call_llm_with_config(self, prompt: str, system_prompt: str, model_cfg: Dict, response_format: Optional[Dict] = None) -> str:
        """使用指定模型配置调用 LLM（同步封装）"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self._call_llm_async_with_config(prompt, system_prompt, model_cfg, response_format)
                )
                return result
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"❌ _call_llm_with_config 异常: {e}")
            return None

    async def _call_llm_async_with_config(self, prompt: str, system_prompt: str, model_cfg: Dict, response_format: Optional[Dict] = None) -> str:
        """使用指定配置异步调用 LLM"""
        api_base = model_cfg.get("api_base", "")
        model_name = model_cfg.get("model_name", "default")
        timeout = model_cfg.get("timeout", 600)
        max_tokens = model_cfg.get("max_tokens", 2048)
        api_key = model_cfg.get("api_key", "not-needed")
        
        if not api_base:
            return None
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        url = f"{api_base}/chat/completions"
        payload = {"model": model_name, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens}
        if response_format:
            payload["response_format"] = response_format
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"❌ 备用模型 [{model_name}] API 调用失败: {e}")
        return None

    def _clean_user_message(self, message: str) -> str:
        """清洗用户消息：去除系统模板污染 + 解析相对时间
        
        网关（gateway_grpc.py）会在消息前加上时间模板：
          [当前时间]
          当前日期: 2026年5月6日 星期三
          
          [新会话] 或 [会话上下文]
          主题: xxx
          Session ID: xxx
          
          消息: {原始用户消息}
        
        本方法：
        1. 剥离 <think> 标签
        2. 提取真正的用户消息（去除系统模板前缀）
        3. 解析相对时间（如"上周"→"2026-04-27~2026-05-03"）
        """
        text = self._strip_think_tags(message)
        text = self._extract_user_content(text)
        text = self._resolve_time_in_message(text)
        return text.strip()

    def _extract_user_content(self, message: str) -> str:
        """从 Gateway 增强消息中提取真实的用户内容"""
        if not message:
            return message
        
        # 多种分隔符模式，按优先级匹配
        patterns = [
            r'当前消息:\s*(.+)',           # "---\n当前消息: {用户消息}"
            r'消息:\s*(.+)',                # "[新会话]\n消息: {用户消息}"
            r'---\s*\n+(.+)',              # "历史对话:\n...\n---\n{用户消息}"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, message, re.DOTALL)
            if match:
                extracted = match.group(1).strip()
                if extracted:
                    logger.debug(f"   📬 提取用户内容(模式:{pattern}): {extracted[:80]}...")
                    return extracted
        
        # 如果都没有匹配到模板，说明消息本身就是原始内容，直接返回
        # 但尝试去掉 [当前时间] 开头的时间戳前缀（如果存在）
        clean = re.sub(r'^\[当前时间\]\s*\n.*?$', '', message, flags=re.MULTILINE).strip()
        if clean != message:
            logger.debug(f"   📬 移除 [当前时间] 前缀")
            return clean
            
        return message

    def _resolve_time_in_message(self, message: str) -> str:
        """将消息中的相对时间（上周、本月、今天等）解析为精确日期"""
        if not message:
            return message
        
        try:
            from src.utils.time_parser import parse_time
            resolved_text, time_info = parse_time(message)
            
            if time_info.get("resolved"):
                dates = time_info.get("dates", [])
                date_range = time_info.get("date_range", [])
                descriptions = time_info.get("date_descriptions", [])
                
                if descriptions:
                    logger.info(f"   🕐 时间解析: {'; '.join(descriptions)}")
                if dates:
                    logger.info(f"   📅 解析到日期: {dates}")
                if date_range:
                    logger.info(f"   📅 解析到周范围: {date_range}")
                
                # 缓存 time_info 供后续使用
                self._last_time_info = time_info
                self._last_resolved_text = resolved_text
                return resolved_text
            else:
                # 未解析到时间，清空缓存
                self._last_time_info = {}
                self._last_resolved_text = resolved_text
        except Exception as e:
            logger.warning(f"   ⚠️ 时间解析异常（跳过）: {e}")
            self._last_time_info = {}
        
        return message

    def _handle_internal_command(self, message: str, session_id: str) -> dfecrab_pb2.ChatResponse:
        """处理内部命令（如 RELOAD_AGENTS）"""
        cmd = message.strip().split(':', 1)[1].strip() if ':' in message else message.strip()
        import time
        timestamp = str(int(time.time()))

        if cmd == 'RELOAD_AGENTS':
            try:
                self._reload_agent_descriptions()
                logger.info("✅ 内部命令执行成功: RELOAD_AGENTS")
                return dfecrab_pb2.ChatResponse(
                    success=True,
                    session_id=session_id,
                    message=json.dumps({"message": "Agent描述已重新加载"}, ensure_ascii=False),
                    task_type="internal",
                    agents_used=[],
                    audit_log_id="",
                    error="",
                    timestamp=timestamp
                )
            except Exception as e:
                logger.error(f"❌ 内部命令执行失败: RELOAD_AGENTS - {e}")
                return dfecrab_pb2.ChatResponse(
                    success=False,
                    session_id=session_id,
                    message=f"RELOAD_AGENTS 失败: {str(e)}",
                    task_type="error",
                    agents_used=[],
                    audit_log_id="",
                    error=str(e),
                    timestamp=timestamp
                )

        logger.warning(f"⚠️ 未知内部命令: {cmd}")
        return dfecrab_pb2.ChatResponse(
            success=False,
            session_id=session_id,
            message=f"未知内部命令: {cmd}",
            task_type="error",
            agents_used=[],
            audit_log_id="",
            error="unknown_command",
            timestamp=timestamp
        )

    def _auto_check_agent_updates(self) -> bool:
        """智能刷新Agent列表：时间间隔控制 + 目录变更检测 + 文件快照比对"""
        now = time.time()
        if (now - self._last_refresh_time) < self._refresh_interval:
            return False

        agents_dir = PROJECT_ROOT / "agents"
        if not agents_dir.exists():
            return False

        current_mtime = agents_dir.stat().st_mtime
        if current_mtime == self._agents_dir_mtime and self._agents_dir_snapshot:
            self._last_refresh_time = now
            return False

        current_snapshot = {}
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            config_file = agent_dir / "config.json"
            if config_file.exists():
                current_snapshot[agent_dir.name] = config_file.stat().st_mtime

        if current_snapshot != self._agents_dir_snapshot:
            self._reload_agent_descriptions()
            logger.info(f"🔄 Agent列表已刷新（检测到配置变更），当前 {len(self._agent_descriptions)} 个可用Agent")

        self._last_refresh_time = now
        self._agents_dir_mtime = current_mtime
        self._agents_dir_snapshot = current_snapshot
        return True

    def _identify_intent(self, message: str) -> Dict:
        """意图识别：由 LLM 模型判断，不做任何硬编码规则匹配
        在入口处统一清洗消息（去模板 + 解析时间），
        清洗后的消息用于 LLM 识别。
        LLM 全不可用时降级为 chat 类型（Manager 直接回复），
        不进行关键词/规则匹配。
        """
        logger.info(f"🔍 [Manager] 开始意图识别...")
        
        # 0. 自动检查 agents/ 目录是否有变更
        self._auto_check_agent_updates()
        
        # 1. 统一清洗消息：去系统模板 + 解析相对时间
        clean_message = self._clean_user_message(message)
        if clean_message != message:
            logger.info(f"   🧹 已清洗消息（原始长度 {len(message)} → 清洗后 {len(clean_message)}）")
        
        # 1. 调用LLM进行意图识别（完全模型驱动，使用动态构建的Agent列表）
        dynamic_prompt = self._build_dynamic_system_prompt()
        llm_intent = self._call_llm_for_intent(clean_message, dynamic_prompt)
        
        if llm_intent:
            # 验证：确保LLM返回的Agent在当前可用列表中
            llm_intent = self._validate_intent_agents(llm_intent)
            logger.info(f"✅ [Manager] LLM意图识别成功: {llm_intent.get('type')}")
            # 提取思考过程
            think_content = llm_intent.pop("_think_process", "")
            if think_content:
                llm_intent["_think_process"] = think_content
            return llm_intent
        
        # 2. LLM全不可用时，降级为 simple/chat 类型（Manager直接回复）
        #    P3阶段不做任何硬编码规则匹配，保持模型驱动的纯净
        logger.warning(f"⚠️ [Manager] LLM意图识别失败，降级为 simple/chat 类型")
        intent = {
            "type": "simple",
            "category": "chat",
            "reason": "LLM不可用，Manager直接回复",
            "_think_process": "所有模型均不可用，降级为simple/chat由Manager直接回复"
        }
        logger.info(f"✅ [Manager] 降级意图: {intent.get('type')}/{intent.get('category')}")
        return intent

    def _validate_intent_agents(self, intent: Dict) -> Dict:
        """验证意图中的Agent是否在当前可用列表中，移除不存在的Agent并降级"""
        available_agents = set(self._agent_descriptions.keys())
        task_type = intent.get("type", "unknown")

        if task_type == "simple" and intent.get("category") != "chat":
            target = intent.get("target_agent", "")
            if target and target not in available_agents:
                logger.warning(f"⚠️ [Manager] LLM返回的target_agent '{target}' 不在可用列表 {available_agents} 中，降级为chat")
                intent["type"] = "simple"
                intent["category"] = "chat"
                intent["reason"] = f"Agent '{target}' 不存在，降级为Manager直接回复"
                intent.pop("target_agent", None)
        elif task_type == "complex":
            workflow = intent.get("workflow", {})
            steps = workflow.get("steps", [])
            valid_steps = []
            removed_agents = []
            for step in steps:
                agent_id = step.get("agent", "")
                if agent_id in available_agents:
                    valid_steps.append(step)
                else:
                    removed_agents.append(agent_id)
                    logger.warning(f"⚠️ [Manager] 工作流中的Agent '{agent_id}' 不在可用列表 {available_agents} 中，已移除")

            if removed_agents:
                workflow["steps"] = valid_steps
                if not valid_steps:
                    logger.warning(f"⚠️ [Manager] 工作流中所有Agent均不可用，降级为chat")
                    intent["type"] = "simple"
                    intent["category"] = "chat"
                    intent["reason"] = f"工作流中的Agent {removed_agents} 均不存在，降级为Manager直接回复"
                    intent.pop("workflow", None)
                elif len(valid_steps) == 1:
                    logger.info(f"   📋 工作流只剩1步，降级为simple任务")
                    intent["type"] = "simple"
                    intent["category"] = intent.get("category", "query")
                    intent["target_agent"] = valid_steps[0].get("agent", "")
                    intent.pop("workflow", None)
                    intent["reason"] = intent.get("reason", "") + f" (已移除不存在的Agent: {removed_agents})"

        return intent

    def _call_llm_for_intent(self, message: str, system_prompt: str) -> Optional[Dict]:
        """调用LLM进行意图识别，返回解析后的意图字典"""
        try:
            # 双重清洗：message 已由 _identify_intent 统一清洗过，此处再加一道保险
            clean_message = self._clean_user_message(message)
            prompt = f"""用户消息：{clean_message}

分析用户意图，输出纯JSON（禁止<think>/Markdown/额外文字）：

输出格式（字段名必须完全一致，禁止用 target/agent/agent_id 替代 target_agent）：
1. simple/chat（Manager直接回复）：
{{"type":"simple","category":"chat","reason":"理由"}}

2. simple/其他（1个Agent）：
{{"type":"simple","category":"query","target_agent":"agent_id","reason":"理由"}}

3. complex（≥2个Agent协作）：
{{"type":"complex","category":"xxx","reason":"理由","workflow":{{"steps":[{{"agent":"xxx","action":"xxx","description":"xxx"}},...]}}}}

分类说明：
- category=chat: 问候/闲聊/知识问答/感谢，Manager直接回复，无target_agent
- category=query: 需要查询数据，根据system_prompt中的路由规则选择合适的Agent
- category=file: 文件操作
- 其他情况根据system_prompt中的Agent能力和路由规则选择合适的Agent

规则：
- 步骤越少越好，能用1步不用2步
- 不确定→simple/chat
- 严格按照 system_prompt 中的路由规则选择Agent
- 只输出JSON，不要任何其他内容
- ⭐ crucial: simple非chat时，target_agent和category必须同时出现，缺一不可
- ⭐ crucial: 字段名必须是 target_agent，绝对禁止用 target、agent、agent_id 等别名"""
            
            # ★ [新增] 截断 system_prompt 到 2000 字，减少推理时间
            system_prompt = self._truncate_agent_list(system_prompt, max_chars=2000)

            response = self._call_llm_with_fallback(prompt, system_prompt, response_format={"type": "json_object"})

            # ★ [新增] 打印原始响应用于诊断
            if response:
                logger.info(f"📨 [意图识别] 原始LLM响应 (前300字): {response[:300]}")
            else:
                logger.warning("⚠️ [意图识别] LLM返回空")
                return None

            # ★ [增强] 使用增强解析器处理LLM响应
            intent = self._parse_intent_json(response)

            # ★ [新增] 别名归一化兜底：将target/agent/agent_id自动映射为target_agent
            intent = self._normalize_intent_aliases(intent)

            # ★ [新增] 保存原始LLM响应和思考过程
            if response:
                raw_text = response.strip()
                think_clean = re.sub(r'<think>[\s\S]*?</think>', '', raw_text, flags=re.DOTALL).strip()
                json_start = think_clean.find('{')
                think_process = think_clean[:json_start].strip() if json_start > 0 else ""
                
                if intent:
                    intent["_think_raw"] = response
                    intent["_think_process"] = think_process or intent.get("reason", "正在分析用户意图...")

            if not intent:
                logger.warning("⚠️ [意图识别] JSON解析失败，降级为chat")
                return {"type": "simple", "category": "chat", "reason": "意图识别JSON解析失败，降级为chat"}

            # 标准化验证：simple类型需要category，complex需要workflow
            if intent.get("type") == "simple":
                category = intent.get("category", "")
                if category == "chat":
                    # chat不需要target_agent
                    pass
                elif "target_agent" not in intent:
                    # 缺target_agent时降级为chat
                    intent["type"] = "simple"
                    intent["category"] = "chat"
                    intent["reason"] = intent.get("reason", "未指定目标Agent，降级为chat")
            elif intent.get("type") == "complex":
                if "workflow" not in intent or "steps" not in intent.get("workflow", {}):
                    # 缺workflow时降级为chat
                    intent["type"] = "simple"
                    intent["category"] = "chat"
                    intent["reason"] = intent.get("reason", "缺workflow，降级为chat")
            else:
                # 未知type一律降级为chat
                intent["type"] = "simple"
                intent["category"] = "chat"
                intent["reason"] = "未知类型，降级为chat"
                    
            return intent
            
        except Exception as e:
            logger.error(f"❌ LLM意图识别异常: {e}")
            return None

    def _strip_think_tags(self, text) -> str:
        """基础版思维链剥离（兼容旧调用方）"""
        return self._strip_cot(text)

    def _strip_cot(self, text) -> str:
        """增强版思维链剥离 - 处理模型输出的各种思考过程格式（使用配置的标签）
        
        处理多种模型的思考格式:
        - 配置化的开始/结束标签（如 <think>...思考标签）
        - 孤立的标签（只有开始或只有结束）
        - "Here's a thinking process:" + 编号推理步骤
        - Draft/Self-Correction/Verification 等推理前缀
        - 中文推理前缀（"用户问题是", "让我思考一下"等）
        """
        import re
        if text is None:
            return ""
        if not isinstance(text, str):
            try:
                text = json.dumps(text, ensure_ascii=False, default=str)
            except Exception:
                text = str(text)

        # ★ 获取当前模型的思考标签配置
        think_config = self._get_current_think_config()
        start_tags = think_config["start_tags"]
        end_tags = think_config["end_tags"]
        all_tags = start_tags + end_tags

        # 1. 移除所有开始标签+内容+结束标签的完整组合
        for start_tag in start_tags:
            for end_tag in end_tags:
                pattern = f'{re.escape(start_tag)}[\\s\\S]*?{re.escape(end_tag)}'
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # 2. 移除孤立的标签（不管开始还是结束）
        for tag in all_tags:
            text = re.sub(re.escape(tag), '', text, flags=re.IGNORECASE)

        # 3. "Here's a thinking process:" + 完整多行推理内容
        #    匹配直到遇到双换行+中文字符（答案开始）
        pattern = r"Here's a thinking process:[\s\S]*?(?=\n\n[\u4e00-\u9fff])"
        text = re.sub(pattern, '', text, flags=re.DOTALL)
        # 4. 兜底：如果上面没匹配到（没有双换行+中文），则删除 "Here's..." 之后的全部
        if "Here's a thinking process:" in text or "Here’s a thinking process:" in text:
            text = re.sub(r"Here['']?s a thinking process:[\s\S]*$", '', text, flags=re.DOTALL)

        # 5. 删除常见的中文推理前缀（一行或多行）
        reasoning_prefixes = [
            r'用户问题是',
            r'当前技能列表',
            r'仔细看技能列表',
            r'再仔细看技能列表',
            r'哦，用户的问题是',
            r'让我思考一下',
            r'我再检查一遍',
            r'我再仔细检查',
            r'所以结论是',
            r'所以，我将回复',
            r'所以，最终的输出是',
            r'但是，等等',
            r'不过，作为',
            r'因此，输出应该是',
            r'有没有可能',
            r'有没有可能漏掉了',
            r'正在分析用户意图',
            r'分析用户意图',
        ]
        for prefix in reasoning_prefixes:
            text = re.sub(prefix, '', text)

        # 6. 清理[编号. **标题**]格式的推理步骤（如 "1.  **Analyze User Input:**"）
        text = re.sub(r'\d+\.\s+\*{2}.+?\*{2}[\s\S]*?(?=\n\d+\.|\n\n|$)', '', text, flags=re.DOTALL)
        # 7. 清理 Draft/Self-Correction 等推理标记
        text = re.sub(r'(?m)^(Draft|Self-Correction|Verification|Self-Check|Final Check)[:\s].*$', '', text)
        # 8. 清理思考步骤中的 emoji 标记和特殊符号
        text = re.sub(r'[✅☑️✓✗⬜🔍]', '', text)
        text = re.sub(r'Ready\..*?✅', '', text)

        # 9. 压缩多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _parse_intent_json(self, raw: str) -> Optional[Dict]:
        """从LLM响应中鲁棒地提取并解析意图JSON（兼容各种格式异常）"""
        if not raw:
            return None

        import re
        text = raw.strip()

        # ★ 0. ###END### 分隔符优先处理：只取两个 ###END### 之间的内容
        endsep_matches = list(re.finditer(r'###END###', text))
        if len(endsep_matches) >= 2:
            # 取第一个 ###END### 到第二个 ###END### 之间的内容
            start = endsep_matches[0].end()
            end = endsep_matches[1].start()
            between = text[start:end].strip()
            logger.info(f"🔗 检测到 ###END### 分隔符，提取分隔符间内容: {between[:200]}")
            # 如果之间有内容且包含 {，则优先用这段
            if between and '{' in between:
                text = between
            else:
                # 分隔符之间无 JSON，取第二个 ###END### 之前的所有内容
                text = text[:endsep_matches[1].end()]
        elif len(endsep_matches) == 1:
            # 只有一个 ###END###，取它之前的内容
            text = text[:endsep_matches[0].start()].strip()
            logger.info(f"🔗 检测到单个 ###END### 分隔符，取之前内容: {text[:200]}")

        # 1. 去除 <think> 标签
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.DOTALL).strip()
        # 2. 去除 Markdown 代码块标记
        for marker in ['```json', '```']:
            if text.startswith(marker):
                text = text[len(marker):]
            if text.endswith('```'):
                text = text[:-3]
        text = text.strip()
        # 3. 去除可能的前导文字（直到遇到第一个 {）
        brace_idx = text.find('{')
        if brace_idx > 0:
            text = text[brace_idx:]
        elif brace_idx < 0:
            logger.warning(f"⚠️ 响应中未找到JSON起始标记，使用字段提取兜底: {raw[:200]}")
            return self._extract_intent_fields(raw)

        # 4. 用括号计数法精确提取最外层 JSON 对象（避免跨多个JSON对象）
        json_str = ""
        depth = 0
        in_string = False
        escape = False
        start_idx = None

        for i, ch in enumerate(text):
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not in_string:
                in_string = True
                if start_idx is None:
                    start_idx = i
            elif ch == '"' and in_string:
                in_string = False
            elif not in_string:
                if ch == '{':
                    if depth == 0:
                        start_idx = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start_idx is not None:
                        json_str = text[start_idx:i+1]
                        break

        # 兜底：括号计数失败则用正则非贪婪匹配
        if not json_str:
            json_match = re.search(r'\{[\s\S]*?\}', text)
            if json_match:
                json_str = json_match.group()

        if not json_str:
            logger.warning(f"⚠️ 响应中未找到JSON对象，使用字段提取兜底: {raw[:200]}")
            return self._extract_intent_fields(raw)

        # 5. 尝试解析（含容错修复）：逐步尝试各种修复策略
        attempts = [
            json_str,                                    # 原始
            json_str.replace("'", '"'),                  # 单引号→双引号
            re.sub(r',(\s*[}\]])', r'\1', json_str),    # 去掉末尾逗号
            json_str.replace("，", ",").replace("：", ":").replace("“", '"').replace("”", '"'),  # 中文标点
            re.sub(r'(\w+)\s*：\s*', r'\1: ', json_str),  # 中文冒号
        ]
        # 去重
        seen = set()
        unique_attempts = []
        for a in attempts:
            if a not in seen:
                seen.add(a)
                unique_attempts.append(a)

        for attempt in unique_attempts:
            try:
                return json.loads(attempt)
            except json.JSONDecodeError:
                continue

        # 6. 所有解析尝试失败，使用字段提取兜底
        logger.warning(f"⚠️ JSON解析全部失败，使用字段提取兜底: {json_str[:200]}")
        return self._extract_intent_fields(text)

    def _normalize_intent_aliases(self, intent: Dict) -> Dict:
        """把LLM常见的字段别名统一成代码标准字段，兜底方案"""
        if not isinstance(intent, dict):
            return intent

        # 1. target_agent 别名映射（按优先级尝试）
        for alias in ("target", "agent", "agent_id", "selected_agent"):
            if alias in intent and "target_agent" not in intent:
                intent["target_agent"] = intent.pop(alias)
                break

        # 2. simple非chat但缺少category时，默认query
        if intent.get("type") == "simple" and "target_agent" in intent:
            if not intent.get("category") or intent["category"] == "chat":
                intent["category"] = "query"

        # 3. 确保reason存在
        if "reason" not in intent:
            intent["reason"] = intent.get("target_agent", "用户查询")

        return intent

    def _remap_agent_by_keywords(self, message: str, original_agent: str) -> Optional[str]:
        """关键词匹配修正 agent_id（模型自创名称时的代码辅助兜底）"""
        message_lower = message.lower()
        # 按关键词优先级匹配
        for agent_id, info in self._agent_descriptions.items():
            for keyword in info.get("keywords", []) or []:
                kw = str(keyword).strip().lower()
                if not kw or len(kw) < 2:
                    continue
                if kw in message_lower:
                    return agent_id
        return None

    def _extract_intent_fields(self, text: str) -> Optional[Dict]:
        """用正则直接从文本中提取意图字段（JSON解析失败时的兜底方案）"""
        import re

        text_lower = text.lower()

        # 提取 type
        type_match = re.search(r'["\']?type["\']?\s*[:：]\s*["\']?(\w+)["\']?', text_lower)
        intent_type = type_match.group(1) if type_match else "simple"

        # 提取 category
        category_match = re.search(r'["\']?category["\']?\s*[:：]\s*["\']?(\w+)["\']?', text_lower)
        category = category_match.group(1) if category_match else "chat"

        # 提取 target_agent
        agent_match = re.search(r'["\']?target_agent["\']?\s*[:：]\s*["\']?([^"\s,}]+)["\']?', text_lower)
        target_agent = agent_match.group(1) if agent_match else ""

        # 提取 reason
        reason_match = re.search(r'["\']?reason["\']?\s*[:：]\s*["\']?([^"}\n]+)["\']?', text, re.IGNORECASE)
        reason = reason_match.group(1).strip() if reason_match else "模型输出格式异常，字段提取兜底"

        # 提取 workflow（尝试找 { ... } 结构）
        workflow = None
        workflow_match = re.search(r'["\']?workflow["\']?\s*[:：]\s*(\{[\s\S]*?\})', text, re.IGNORECASE)
        if workflow_match:
            try:
                workflow = json.loads(workflow_match.group(1))
            except Exception:
                pass

        result = {
            "type": intent_type,
            "category": category,
            "reason": reason
        }
        if target_agent:
            result["target_agent"] = target_agent
        if workflow:
            result["workflow"] = workflow

        # 如果文本中包含 workflow/steps 关键字但正则没提取到，强制标记为 complex
        if not workflow and ("workflow" in text_lower or "steps" in text_lower):
            result["type"] = "complex"
            if result.get("category") == "chat":
                result["category"] = "query"

        logger.info(f"📨 [字段提取兜底] 提取结果: {result}")
        return result

    def _async_gen_to_sync(self, async_gen):
        """将 async generator 转换为同步迭代器
        
        在单独线程中创建并运行 event loop，通过 queue 传递数据。
        线程完全负责 loop 的创建和销毁，避免跨线程操作问题。
        """
        from queue import Queue, Empty
        import threading
        
        queue = Queue()
        sentinel = object()
        error_holder = []
        
        # 在单独线程中创建、运行、关闭 event loop
        def run_loop():
            local_loop = asyncio.new_event_loop()
            try:
                async def _runner():
                    try:
                        async for item in async_gen:
                            queue.put(('item', item))
                    except Exception as e:
                        error_holder.append(e)
                    finally:
                        queue.put(('stop', sentinel))
                
                local_loop.run_until_complete(_runner())
                
                # 取消所有待处理任务
                for task in asyncio.all_tasks(local_loop):
                    task.cancel()
                if local_loop.is_running():
                    local_loop.stop()
            finally:
                local_loop.close()
        
        # 启动线程运行 event loop
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        
        # 在当前线程消费 queue
        while True:
            try:
                status, value = queue.get(timeout=600)
                if status == 'stop':
                    break
                yield value
            except Empty:
                logger.error("⏰ [意图识别] 等待流式响应超时")
                break
        
        thread.join(timeout=10)
        
        if error_holder:
            raise error_holder[0]

    def _call_llm_for_intent_stream_yield(self, message: str, system_prompt: str):
        """意图识别生成器 — 流式调用，实时输出思考内容
        
        实时 yield reasoning 事件（think 流），
        思考结束后拼接所有思考内容作为 think_end 的内容。
        
        yield events:
        {"type": "reasoning", "content": token}  ← 实时思考流
        {"type": "done", "intent": intent, "reasoning": accumulated_reasoning}
        """
        try:
            clean_message = self._clean_user_message(message)
            prompt = f"""用户消息：{clean_message}

分析用户意图，输出JSON：

输出格式（字段名必须完全一致，禁止用 target/agent/agent_id 替代 target_agent）：
1. simple/chat（Manager直接回复）：
{{"type":"simple","category":"chat","reason":"理由"}}

2. simple/其他（1个Agent）：
{{"type":"simple","category":"query","target_agent":"agent_id","reason":"理由"}}

3. complex（≥2个Agent协作）：
{{"type":"complex","category":"xxx","reason":"理由","workflow":{{"steps":[{{"agent":"xxx","action":"xxx","description":"xxx"}},...]}}}}

分类说明：
- category=chat: 问候/闲聊/知识问答/感谢，Manager直接回复，无target_agent
- category=query: 需要查询数据，根据system_prompt中的路由规则选择合适的Agent
- category=file: 文件操作
- 其他情况根据system_prompt中的Agent能力和路由规则选择合适的Agent

规则：
- 步骤越少越好，能用1步不用2步
- 不确定→simple/chat
- 严格按照 system_prompt 中的路由规则选择Agent
- ⭐ crucial: simple非chat时，target_agent和category必须同时出现，缺一不可
- ⭐ crucial: 字段名必须是 target_agent，绝对禁止用 target、agent、agent_id 等别名"""

            system_prompt = self._truncate_agent_list(system_prompt, max_chars=2000)

            # ★ 流式调用，实时输出思考内容（使用 v2 适配器，自动回退到 v1）
            full_content = ""
            full_reasoning = ""
            
            # 自定义异步迭代器，在消费流的同时实时 yield reasoning
            async def stream_with_yield():
                nonlocal full_content, full_reasoning
                async for chunk in self._call_llm_async_stream_v2(prompt, system_prompt):
                    token = chunk.get("token", "")
                    reasoning = chunk.get("reasoning", "")
                    if reasoning:
                        full_reasoning += reasoning
                        # 立即 yield reasoning 事件
                        yield {"type": "reasoning", "content": reasoning}
                    if token:
                        full_content += token
            
            # 消费流式响应（通过桥接函数将 async generator 转换为同步迭代器）
            for event in self._async_gen_to_sync(stream_with_yield()):
                yield event
            
            # 如果模型没有返回思考内容，尝试从 content 中提取思考标签内容
            if not full_reasoning and full_content:
                extracted_reasoning = self._extract_think_content(full_content)
                if extracted_reasoning:
                    full_reasoning = extracted_reasoning
                    # 分段 yield 提取到的思考内容
                    for i in range(0, len(extracted_reasoning), 50):
                        chunk = extracted_reasoning[i:i+50]
                        yield {"type": "reasoning", "content": chunk}
            
            if not full_content:
                logger.warning("⚠️ [意图识别] LLM返回空，降级为chat")
                yield {"type": "done", "intent": {"type": "simple", "category": "chat", "reason": "意图识别LLM返回空，降级为chat"}, "reasoning": full_reasoning}
                return

            logger.info(f"📨 [意图识别] 原始LLM响应 (前300字): {full_content[:300]}")
            
            # 清洗 content：去掉思考标签
            clean_content = self._remove_think_tags(full_content)

            # 解析意图
            intent = self._parse_intent_json(clean_content)
            intent = self._normalize_intent_aliases(intent)
            intent = self._validate_intent_agents(intent)

            if not intent:
                intent = {"type": "simple", "category": "chat", "reason": "意图识别JSON解析失败，降级为chat"}

            logger.info(f"✅ [Manager] 意图识别成功: {intent.get('type')}/{intent.get('category')}")
            if intent.get("target_agent"):
                logger.info(f"   └─ 目标Agent: {intent['target_agent']}")

            # 如果模型没有返回思考内容，用结构化文本作为 think_end 内容
            if not full_reasoning:
                full_reasoning = self._build_manager_think_text(intent, clean_message)
            
            logger.info(f"🧠 [Manager Think] 思考内容长度: {len(full_reasoning)} 字符")

            yield {"type": "done", "intent": intent, "reasoning": full_reasoning}
        except Exception as e:
            logger.error(f"❌ 意图识别异常: {e}")
            import traceback
            traceback.print_exc()
            yield {"type": "done", "intent": {"type": "simple", "category": "chat", "reason": "意图识别异常，降级为chat"}, "reasoning": ""}

    def _truncate_agent_list(self, prompt: str, max_chars: int = 2000) -> str:
        """截断系统提示词中的 Agent 列表，加速推理"""
        if not prompt or len(prompt) <= max_chars:
            return prompt
        # 保留前 70%，后 30%，中间省略
        head_len = int(max_chars * 0.7)
        tail_len = max_chars - head_len
        truncated = prompt[:head_len] + "\n...(Agent列表中间省略，共省略" + str(len(prompt) - max_chars) + "字符)...\n" + prompt[-tail_len:]
        logger.info(f"✂️ system_prompt 已截断: {len(prompt)} → {len(truncated)} 字符")
        return truncated
    
    def _extract_think_content(self, text: str) -> str:
        """从模型输出中提取思考标签内的内容（使用配置的标签）"""
        if not text:
            return ""
        
        # 获取当前模型的思考标签配置
        think_config = self._get_current_think_config()
        start_tags = think_config["start_tags"]
        end_tags = think_config["end_tags"]
        
        # 遍历所有可能的开始/结束标签组合
        for start_tag in start_tags:
            for end_tag in end_tags:
                # 构建正则表达式匹配标签内的内容
                pattern = f'{re.escape(start_tag)}([\\s\\S]*?){re.escape(end_tag)}'
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    content = match.group(1).strip()
                    if content:
                        return content
        return ""

    def _remove_think_tags(self, text: str) -> str:
        """移除文本中的思考标签及其内容（使用配置的标签）"""
        if not text:
            return ""
        
        # 获取当前模型的思考标签配置
        think_config = self._get_current_think_config()
        start_tags = think_config["start_tags"]
        end_tags = think_config["end_tags"]
        all_tags = start_tags + end_tags
        
        # 移除所有开始标签+内容+结束标签的完整组合
        for start_tag in start_tags:
            for end_tag in end_tags:
                pattern = f'{re.escape(start_tag)}[\\s\\S]*?{re.escape(end_tag)}'
                text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # 移除单独的标签（不管开始还是结束）
        for tag in all_tags:
            text = re.sub(re.escape(tag), '', text, flags=re.IGNORECASE)
        
        # 清理多余的空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _build_manager_think_text(self, intent: Dict, message: str) -> str:
        task_type = intent.get("type", "unknown")
        category = intent.get("category", "")
        workflow = intent.get("workflow", {})
        steps = workflow.get("steps", [])

        if task_type == "simple" and category == "chat":
            return "【chat】直接回复"
        if steps:
            agent_names = [s.get("agent", "未知") for s in steps]
            return f"【{category}】按 {' → '.join(agent_names)} 流程处理"
        if intent.get("target_agent"):
            target = intent.get("target_agent", "未知")
            return f"【{category}】交到{target}智能体"
        return "【unknown】继续处理"

    def _generate_manager_summary(self, intent: Dict, message: str) -> str:
        result = self._build_manager_think_text(intent, message)
        if len(result) > 200:
            result = result[:197] + "..."
        return result

    def _load_sql_metadata(self) -> Dict:
        """加载SQL生成器所需的元数据（表结构字段定义）
        
        用于在调用sql_generator_agent前注入meta_cache.json，
        防止字段幻觉（模型创造不存在的字段名）。
        """
        meta_cache_path = PROJECT_ROOT / "agents" / "sql_generator_agent" / "meta_cache.json"
        if meta_cache_path.exists():
            try:
                with open(meta_cache_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                logger.info(f"   📚 已加载SQL元数据: {len(metadata)} 张表")
                return metadata
            except Exception as e:
                logger.warning(f"   ⚠️ SQL元数据加载失败: {e}")
        else:
            logger.warning(f"   ⚠️ 未找到SQL元数据文件: {meta_cache_path}")
        return {}

    def _dispatch_and_execute(self, intent: Dict, message: str, session_id: str) -> Dict:
        """根据意图分发并执行任务"""
        task_type = intent.get("type", "unknown")
        category = intent.get("category", "")
        
        if task_type == "simple":
            if category == "chat":
                # simple/chat：Manager直接回复
                return self._execute_chat(intent, message, session_id)
            else:
                # simple/其他（如 query/file）：调用单个Agent
                return self._execute_simple_task(intent, message, session_id)
        
        elif task_type == "complex":
            # complex：多Agent协作
            return self._execute_complex_task(intent, message, session_id)
        
        # 兜底：降级为chat
        logger.warning(f"⚠️ 无法识别的任务类型 {task_type}/{category}，降级为chat")
        return self._execute_chat(intent, message, session_id)
    
    def _dispatch_and_execute_stream(self, intent: Dict, message: str, session_id: str):
        """流式版本：根据意图分发并执行任务，每一步yield事件
        注意：think_start/think_end 已在 process_message_stream 中发送，本函数不再重复。
        """
        # ── Phase 3: 发送 manager 决策总结 ──
        summary = self._generate_manager_summary(intent, message)
        yield dfecrab_pb2.StreamChatResponse(
            step=dfecrab_pb2.AgentStep(
                step=0,
                agent="manager_agent",
                action="manager_decision",
                answer=summary,
                timestamp=datetime.now().isoformat()
            )
        )
        
        task_type = intent.get("type", "unknown")
        category = intent.get("category", "")
        
        if task_type == "simple" and category == "chat":
            # chat类型：直接返回最终结果，无需多余 thinking/think_end
            result = self._execute_chat(intent, message, session_id)
            yield dfecrab_pb2.StreamChatResponse(
                final=dfecrab_pb2.ChatResponse(
                    success=result.get("success", False),
                    session_id=session_id,
                    message=result.get("message", ""),
                    task_type="simple",
                    agents_used=[],
                    audit_log_id="",
                    error=result.get("error", ""),
                    timestamp=datetime.now().isoformat()
                )
            )
        elif task_type == "complex":
            # complex：多Agent协作
            yield from self._execute_complex_task_stream(intent, message, session_id)
        elif task_type == "simple":
            # simple/非chat：调用单个Agent
            yield from self._execute_simple_task_stream(intent, message, session_id)
        else:
            yield dfecrab_pb2.StreamChatResponse(
                error=dfecrab_pb2.StreamError(message=f"无法识别的任务类型: {task_type}/{category}")
            )

    def _execute_chat(self, intent: Dict, message: str, session_id: str) -> Dict:
        """
        执行chat类型任务：Manager直接回复用户，不调用任何其他Agent
        
        P3架构下，日常对话/问候/问答等由Manager直接处理，
        不走Agent发现和分发链路。
        """
        logger.info(f"💬 [Manager] 执行chat任务: Manager直接回复")
        
        # 使用友好的聊天prompt，直接回复用户
        system_prompt = "你是DFEcrab智能助手。请简短、自然地回复用户的消息。保持友好、热情的语气。禁止输出<think>标签，禁止输出JSON。直接回复用户即可。"
        response = self._call_llm_with_fallback(message, system_prompt)
        
        if not response:
            response = "你好，我是 DFEcrab，有什么可以帮你的吗？"
        
        response = self._strip_cot(response)
        
        return {
            "success": True,
            "message": response,
            "task_type": "simple",
            "agents_used": [],
            "manager_think": intent.get("_think_process", ""),
            "execution_flow": [{"step": 1, "agent": "manager_agent", "action": "direct_chat", "answer": response}]
        }
    
    def _execute_simple_task(self, intent: Dict, message: str, session_id: str) -> Dict:
        """执行简单任务 - 通过Zookeeper发现并调用Agent"""
        target_agent_id = intent.get("target_agent", "").strip()

        logger.info(f"🚀 执行简单任务 -> [{target_agent_id}] (len={len(target_agent_id)})")
        logger.info(f"   ├─ Session ID: {session_id}")
        logger.info(f"   └─ 分类: {intent.get('category', 'N/A')}")

        if not target_agent_id:
            logger.warning(f"⚠️ simple任务无target_agent，降级为chat")
            return self._execute_chat(intent, message, session_id)

        # 双重保险：校验Agent是否在可用列表中
        if target_agent_id not in self._agent_descriptions:
            logger.warning(f"⚠️ [Manager] simple任务Agent '{target_agent_id}' 不在可用列表中，降级为chat")
            return self._execute_chat(intent, message, session_id)

        logger.info(f"   ⏭️ 进入服务发现流程")
        try:
            # 通过Zookeeper发现服务（重试3次，应对ZK临时节点重建延迟）
            logger.info(f"   🔍 服务发现: 查找 {target_agent_id}")
            service_instance = None
            for retry in range(3):
                service_instance = self._discover_agent_service(target_agent_id)
                if service_instance:
                    break
                if retry < 2:
                    logger.warning(
                        f"   ⚠️ 未找到 {target_agent_id}，等待2s后重试 ({retry+1}/3)..."
                    )
                    time.sleep(2)

            if not service_instance:
                logger.warning(f"   ❌ 重试3次后仍未找到 Agent 服务: {target_agent_id}")
                return {
                    "success": False,
                    "message": f"未找到Agent服务: {target_agent_id}",
                    "task_type": "simple",
                    "agents_used": []
                }

            logger.info(f"   ✅ 发现服务: {service_instance['host']}:{service_instance['port']}")
            
            # 调用gRPC服务 - 使用传入的 session_id
            logger.info(f"   📡 调用 gRPC: {service_instance['host']}:{service_instance['port']}")
            result = self._call_agent_grpc(
                host=service_instance["host"],
                port=service_instance["port"],
                session_id=session_id,  # 使用传入的 session_id
                input_data={"message": message},
                instruction=message
            )

            if result.get("success"):
                # 解析 Worker 返回的结果
                worker_result = json.loads(result.get("result", "{}"))
                logger.info(f"   ✅ Agent执行成功")
                logger.info(f"   📤 Worker 输出键: {list(worker_result.keys())}")
                
                # 检测是否为结构化输出（包含 answer_final）
                if "answer_final" in worker_result:
                    answer = worker_result.get("answer_final", "")
                    other = worker_result.get("other", {})
                    # 替换 conversation_id 占位符为真实的 session_id
                    if other.get("conversation_id") == "{{SESSION_ID}}":
                        other["conversation_id"] = session_id
                    result_content = self._strip_think_tags(answer)
                    structured_other = other
                else:
                    # 兼容旧格式：提取实际消息（如果有）
                    result_content = worker_result.get("content") or worker_result.get("report_content") or worker_result.get("analysis_result") or worker_result.get("message") or str(worker_result)
                    result_content = self._strip_think_tags(result_content)
                    structured_other = None
                return {
                    "success": True,
                    "message": result_content,
                    "structured": structured_other,
                    "task_type": "simple",
                    "agents_used": [target_agent_id],
                    "manager_think": intent.get("_think_process", ""),
                    "execution_flow": [{"step": 1, "agent": target_agent_id, "action": "single_agent_execute", "answer": result_content}]
                }
            else:
                logger.error(f"   ❌ Agent执行失败: {result.get('error')}")
                return {
                    "success": False,
                    "message": f"Agent执行失败: {result.get('error')}",
                    "task_type": "simple",
                    "agents_used": [target_agent_id]
                }

        except Exception as e:
            logger.error(f"❌ 简单任务执行失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"执行失败: {str(e)}",
                "task_type": "simple",
                "agents_used": [target_agent_id]
            }
    
    def _execute_simple_task_stream(self, intent: Dict, message: str, session_id: str):
        """流式版本：执行简单任务，yield步骤事件和最终结果"""
        target_agent_id = intent.get("target_agent", "").strip()
        logger.info(f"🚀 执行简单任务（流式） -> [{target_agent_id}]")
        logger.info(f"   ├─ Session ID: {session_id}")
        logger.info(f"   └─ 分类: {intent.get('category', 'N/A')}")

        if not target_agent_id:
            logger.warning(f"⚠️ simple流式任务无target_agent，降级为chat")
            result = self._execute_chat(intent, message, session_id)
            yield dfecrab_pb2.StreamChatResponse(
                final=dfecrab_pb2.ChatResponse(
                    success=result.get("success", False),
                    session_id=session_id,
                    message=result.get("message", ""),
                    task_type="simple",
                    agents_used=[],
                    audit_log_id="",
                    error=result.get("error", ""),
                    timestamp=datetime.now().isoformat()
                )
            )
            return

        # 双重保险：校验Agent是否在可用列表中，不在则用关键词修正
        if target_agent_id not in self._agent_descriptions:
            logger.warning(f"⚠️ [Manager] Agent '{target_agent_id}' 不在可用列表中，尝试代码辅助修正")
            corrected_id = self._remap_agent_by_keywords(message, target_agent_id)
            if corrected_id and corrected_id in self._agent_descriptions:
                logger.info(f"   ✅ 代码辅助修正: {target_agent_id}→{corrected_id}")
                intent["target_agent"] = corrected_id
                target_agent_id = corrected_id
            else:
                logger.warning(f"⚠️ 无法修正Agent '{target_agent_id}'，降级为chat")
                result = self._execute_chat(intent, message, session_id)
                yield dfecrab_pb2.StreamChatResponse(
                    final=dfecrab_pb2.ChatResponse(
                        success=result.get("success", False),
                        session_id=session_id,
                        message=result.get("message", ""),
                        task_type="simple",
                        agents_used=[],
                        audit_log_id="",
                        error=result.get("error", ""),
                        timestamp=datetime.now().isoformat()
                    )
                )
                return

        logger.info(f"   ⏭️ 进入服务发现流程")
        try:
            # 发送执行进度事件
            yield dfecrab_pb2.StreamChatResponse(
                step=dfecrab_pb2.AgentStep(
                    step=0,
                    agent=target_agent_id,
                    action="executing",
                    answer=f"正在调用 {target_agent_id}...",
                    timestamp=datetime.now().isoformat()
                )
            )

            # 通过Zookeeper发现服务（重试3次，应对ZK临时节点重建延迟）
            logger.info(f"   🔍 服务发现: 查找 {target_agent_id}")
            service_instance = None
            for retry in range(3):
                service_instance = self._discover_agent_service(target_agent_id)
                if service_instance:
                    break
                if retry < 2:
                    logger.warning(
                        f"   ⚠️ 未找到 {target_agent_id}，等待2s后重试 ({retry+1}/3)..."
                    )
                    time.sleep(2)

            if not service_instance:
                logger.warning(f"   ❌ 重试3次后仍未找到 Agent 服务: {target_agent_id}")
                yield dfecrab_pb2.StreamChatResponse(
                    error=dfecrab_pb2.StreamError(message=f"未找到Agent服务: {target_agent_id}")
                )
                return

            logger.info(f"   ✅ 发现服务: {service_instance['host']}:{service_instance['port']}")
            
            # 发送智能体思考开始事件
            yield dfecrab_pb2.StreamChatResponse(
                step=dfecrab_pb2.AgentStep(
                    step=1,
                    agent=target_agent_id,
                    action="thinking",
                    answer="",
                    timestamp=datetime.now().isoformat()
                )
            )
            
            # 调用gRPC服务
            logger.info(f"   📡 调用 gRPC: {service_instance['host']}:{service_instance['port']}")
            result = self._call_agent_grpc(
                host=service_instance["host"],
                port=service_instance["port"],
                session_id=session_id,
                input_data={"message": message},
                instruction=message
            )

            if result.get("success"):
                # 解析 Worker 返回的结果
                worker_result = json.loads(result.get("result", "{}"))
                logger.info(f"   ✅ Agent执行成功")
                
                # 检测是否为结构化输出（包含 answer_final）
                if "answer_final" in worker_result:
                    answer = worker_result.get("answer_final", "")
                    other = worker_result.get("other", {})
                    # 替换 conversation_id 占位符为真实的 session_id
                    if other.get("conversation_id") == "{{SESSION_ID}}":
                        other["conversation_id"] = session_id
                    result_content = self._strip_think_tags(answer)
                    structured_other = other
                else:
                    # 兼容旧格式：提取实际消息（如果有）
                    result_content = worker_result.get("content") or worker_result.get("report_content") or worker_result.get("analysis_result") or worker_result.get("message") or str(worker_result)
                    result_content = self._strip_think_tags(result_content)
                    structured_other = None
                
                # yield agent step event（传完整 JSON 含 other，供 Gateway Phase 5 解析）
                if structured_other:
                    step_answer = json.dumps({
                        "answer_final": result_content,
                        "other": structured_other
                    }, ensure_ascii=False)
                else:
                    step_answer = result_content
                yield dfecrab_pb2.StreamChatResponse(
                    step=dfecrab_pb2.AgentStep(
                        step=1,
                        agent=target_agent_id,
                        action="single_agent_execute",
                        answer=step_answer,
                        timestamp=datetime.now().isoformat()
                    )
                )
                
                # yield final response（嵌入 structured_other 供 Gateway Phase 5 解析）
                if structured_other:
                    final_msg = json.dumps({
                        "answer_final": result_content,
                        "other": structured_other
                    }, ensure_ascii=False)
                else:
                    final_msg = result_content

                yield dfecrab_pb2.StreamChatResponse(
                    final=dfecrab_pb2.ChatResponse(
                        success=True,
                        session_id=session_id,
                        message=final_msg,
                        task_type="simple",
                        agents_used=[target_agent_id],
                        audit_log_id="",
                        error="",
                        timestamp=datetime.now().isoformat()
                    )
                )
            else:
                logger.error(f"   ❌ Agent执行失败: {result.get('error')}")
                yield dfecrab_pb2.StreamChatResponse(
                    error=dfecrab_pb2.StreamError(message=f"Agent执行失败: {result.get('error')}")
                )

        except Exception as e:
            logger.error(f"❌ 简单任务执行失败: {e}")
            import traceback
            traceback.print_exc()
            yield dfecrab_pb2.StreamChatResponse(
                error=dfecrab_pb2.StreamError(message=f"执行失败: {str(e)}")
            )
    
    def _execute_complex_task(self, intent: Dict, message: str, session_id: str) -> Dict:
        """执行复杂任务 - 编排多个Agent协作"""
        # 防御性判断：如果 intent 中没有 workflow，降级为 simple 任务
        workflow = intent.get("workflow")
        if not workflow:
            logger.warning(f"⚠️ [Manager] complex 任务缺少 workflow，降级为 simple 任务执行")
            return self._execute_simple_task(intent, message, session_id)
        
        agents_used = []
        final_result = None

        logger.info(f"\n{'─'*60}")
        logger.info(f"🚀 [Manager] 执行复杂任务 - 工作流编排")
        logger.info(f"   ├─ 步骤数: {len(workflow['steps'])}")
        logger.info(f"   └─ Session ID: {session_id}")
        logger.info(f"{'─'*60}")

        try:
            previous_result = {"message": message}
            step_outputs = []

            for i, step in enumerate(workflow["steps"]):
                agent_id = step["agent"]
                step_num = len(agents_used) + 1

                logger.info(f"\n  📍 步骤 {step_num}/{len(workflow['steps'])}: {agent_id}")
                logger.info(f"     ├─ 角色: {step.get('role', 'N/A')}")
                logger.info(f"     └─ 描述: {step.get('description', 'N/A')}")

                # 双重保险：校验Agent是否在可用列表中
                if agent_id not in self._agent_descriptions:
                    logger.warning(f"⚠️ [Manager] 工作流步骤 {step_num} 的Agent '{agent_id}' 不在可用列表中，跳过")
                    continue

                # 记录执行进度（非流式版本，仅打日志）
                logger.info(f"     🔄 正在执行第 {step_num}/{len(workflow['steps'])} 步: {step.get('description', agent_id)}...")

                # 通过Zookeeper发现服务
                logger.info(f"     🔍 服务发现: 查找 {agent_id}")
                service_instance = self._discover_agent_service(agent_id)

                if not service_instance:
                    raise Exception(f"未找到Agent服务: {agent_id}")

                logger.info(f"     ✅ 发现服务: {service_instance['host']}:{service_instance['port']}")

                # 准备输入数据：显式传递原始请求、SQL 和上一步结果
                import re
                sql_match = re.search(r'(?i)SQL[：:]\s*(SELECT.+)', message)
                extracted_sql = sql_match.group(1).strip() if sql_match else ""
                if i == 0:
                    input_data = {"message": message, "original_request": message}
                    if agent_id == "sql_generator_agent":
                        input_data["sql_query"] = extracted_sql
                        # 注入元数据，防止字段幻觉
                        input_data["metadata"] = self._load_sql_metadata()
                        # 注入时间信息
                        input_data["time_info"] = getattr(self, '_last_time_info', {})
                        input_data["resolved_message"] = getattr(self, '_last_resolved_text', message)
                        # === 根据用户消息决定查询模式 ===
                        if re.search(r'简报|日报', message):
                            input_data["query_mode"] = "report"
                            logger.info("     📋 [query_mode] report（简报/日报 → 3表查询）")
                        elif re.search(r'跳闸', message):
                            input_data["query_mode"] = "tiaozha"
                            logger.info("     📋 [query_mode] tiaozha（跳闸统计 → 3表查询）")
                        elif re.search(r'早会材料', message):
                            input_data["query_mode"] = "zaohui"
                            logger.info("     📋 [query_mode] zaohui（早会材料 → 1表查询）")
                        elif re.search(r'重过载|过载.*趋势|过载.*情况|过载.*近期', message):
                            if re.search(r'配变', message):
                                input_data["query_mode"] = "guozai_trend_pb"
                                logger.info("     📋 [query_mode] guozai_trend_pb（配变重过载趋势 → 1表查询）")
                            elif re.search(r'馈线|线路', message):
                                input_data["query_mode"] = "guozai_trend_feeder"
                                logger.info("     📋 [query_mode] guozai_trend_feeder（馈线重过载趋势 → 1表查询）")
                            else:
                                input_data["query_mode"] = "guozai_trend"
                                logger.info("     📋 [query_mode] guozai_trend（重过载趋势 → 2表查询）")
                        else:
                            input_data["query_mode"] = "normal"
                            logger.info("     📋 [query_mode] normal（普通查询 → 单表查询）")
                    else:
                        input_data["sql_query"] = extracted_sql
                else:
                    input_data = {
                        "original_request": message,
                        "sql_query": extracted_sql,
                        "upstream_result": previous_result
                    }
                    if agent_id == "dm_agent" and isinstance(previous_result, dict):
                        # 对 dm_agent 进行数据清洗，只传 sql_query，丢弃庞大的上下文
                        # 同时传递 query_mode 和 time_info 用于模板输出
                        input_data = {
                            "sql_query": previous_result.get("sql", extracted_sql),
                            "query_mode": previous_result.get("query_mode", input_data.get("query_mode", "normal")),
                            "time_info": input_data.get("time_info", {}),
                            "resolved_message": input_data.get("resolved_message", message)
                        }
                    elif agent_id == "kunming":
                        input_data["query_result"] = previous_result
                        if isinstance(previous_result, dict) and previous_result.get("query_mode"):
                            input_data["query_mode"] = previous_result["query_mode"]
                logger.info(f"     📥 [Input] 传入数据: {json.dumps(input_data, ensure_ascii=False, default=str)}")

                # 记录智能体思考阶段（非流式版本，仅打日志）
                logger.info(f"     🤔 [{agent_id}] 开始思考...")

                # 调用gRPC服务 - 使用同一个 Session ID
                logger.info(f"     📡 调用 gRPC: {service_instance['host']}:{service_instance['port']}")
                result = self._call_agent_grpc(
                    host=service_instance["host"],
                    port=service_instance["port"],
                    session_id=session_id,  # 使用传入的 Session ID，所有步骤共享
                    input_data=input_data,
                    instruction=step["description"]
                )

                agents_used.append(agent_id)

                if not result.get("success"):
                    logger.error(f"     ❌ Agent执行失败: {result.get('error')}")
                    raise Exception(f"Agent {agent_id} 执行失败: {result.get('error')}")

                previous_result = json.loads(result.get("result", "{}"))
                final_result = result
                
                # 记录每步的输出（优先使用stream_text纯文字字段）
                content = previous_result.get("stream_text") or \
                          previous_result.get("content") or \
                          previous_result.get("report_content") or \
                          previous_result.get("analysis_result") or \
                          previous_result.get("message") or \
                          str(previous_result)
                          
                step_outputs.append({
                    "agent_id": agent_id,
                    "role": step.get("role", "N/A"),
                    "action": step.get("action", "workflow_step"),
                    "output": self._strip_think_tags(content)
                })
                
                exec_time = result.get('execution_time_ms', 'N/A')
                logger.info(f"     ✅ 执行成功 (耗时: {exec_time}ms)")
                logger.info(f"     📤 [Output] 返回数据: {json.dumps(previous_result, ensure_ascii=False, default=str)}")

            logger.info(f"\n{'─'*60}")
            logger.info(f"✅ [Manager] 复杂任务完成，使用了 {len(agents_used)} 个Agent")
            logger.info(f"   └─ 执行链: {' -> '.join(agents_used)}")
            logger.info(f"{'─'*60}\n")
            
            # 如果所有步骤都被跳过（Agent均不可用），降级为chat
            if not agents_used:
                logger.warning(f"⚠️ [Manager] 工作流中所有Agent均不可用，降级为chat")
                return self._execute_chat(intent, message, session_id)

            execution_flow = []
            for idx, so in enumerate(step_outputs):
                execution_flow.append({"step": idx + 1, "agent": so["agent_id"], "action": so.get("action", "workflow_step"), "answer": self._strip_think_tags(so["output"])})
            final_message = execution_flow[-1]["answer"] if execution_flow else ""
            return {
                "success": True,
                "message": final_message,
                "task_type": "complex",
                "agents_used": agents_used,
                "manager_think": intent.get("_think_process", ""),
                "execution_flow": execution_flow,
                "final_result": final_result
            }

        except Exception as e:
            logger.error(f"\n{'─'*60}")
            logger.error(f"❌ [Manager] 复杂任务执行失败: {e}")
            logger.error(f"   ├─ 已完成步骤: {agents_used}")
            logger.error(f"   └─ 错误详情: {str(e)}")
            logger.error(f"{'─'*60}\n")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"工作流执行失败: {str(e)}",
                "task_type": "complex",
                "agents_used": agents_used
            }
    
    def _execute_complex_task_stream(self, intent: Dict, message: str, session_id: str):
        """流式版本：执行复杂任务，每个步骤yield事件，最后yield最终结果"""
        # 防御性判断：如果 intent 中没有 workflow，降级为 simple 流式任务
        workflow = intent.get("workflow")
        if not workflow:
            logger.warning(f"⚠️ [Manager] complex 流式任务缺少 workflow，降级为 simple 流式任务执行")
            yield from self._execute_simple_task_stream(intent, message, session_id)
            return
        
        agents_used = []
        step_outputs = []
        
        logger.info(f"\n{'─'*60}")
        logger.info(f"🚀 [Manager] 执行复杂任务（流式） - 工作流编排")
        logger.info(f"   ├─ 步骤数: {len(workflow['steps'])}")
        logger.info(f"   └─ Session ID: {session_id}")
        logger.info(f"{'─'*60}")

        try:
            previous_result = {"message": message}

            for i, step in enumerate(workflow["steps"]):
                agent_id = step["agent"]
                step_num = len(agents_used) + 1

                logger.info(f"\n  📍 步骤 {step_num}/{len(workflow['steps'])}: {agent_id}")
                logger.info(f"     ├─ 角色: {step.get('role', 'N/A')}")
                logger.info(f"     └─ 描述: {step.get('description', 'N/A')}")

                # 双重保险：校验Agent是否在可用列表中
                if agent_id not in self._agent_descriptions:
                    logger.warning(f"⚠️ [Manager] 工作流步骤 {step_num} 的Agent '{agent_id}' 不在可用列表中，跳过")
                    continue

                # 记录执行进度（非流式版本，仅打日志）
                logger.info(f"     🔄 正在执行第 {step_num}/{len(workflow['steps'])} 步: {step.get('description', agent_id)}...")

                # 通过Zookeeper发现服务
                logger.info(f"     🔍 服务发现: 查找 {agent_id}")
                service_instance = self._discover_agent_service(agent_id)

                if not service_instance:
                    yield dfecrab_pb2.StreamChatResponse(
                        error=dfecrab_pb2.StreamError(message=f"未找到Agent服务: {agent_id}")
                    )
                    return

                logger.info(f"     ✅ 发现服务: {service_instance['host']}:{service_instance['port']}")

                # 准备输入数据：显式传递原始请求、SQL 和上一步结果
                import re
                sql_match = re.search(r'(?i)SQL[：:]\s*(SELECT.+)', message)
                extracted_sql = sql_match.group(1).strip() if sql_match else ""
                if i == 0:
                    input_data = {"message": message, "original_request": message}
                    if agent_id == "sql_generator_agent":
                        input_data["sql_query"] = extracted_sql
                        # 注入元数据，防止字段幻觉
                        input_data["metadata"] = self._load_sql_metadata()
                        # === 根据用户消息决定查询模式 ===
                        if re.search(r'简报|日报', message):
                            input_data["query_mode"] = "report"
                            logger.info("     📋 [query_mode] report（简报/日报 → 3表查询）")
                        elif re.search(r'跳闸', message):
                            input_data["query_mode"] = "tiaozha"
                            logger.info("     📋 [query_mode] tiaozha（跳闸统计 → 3表查询）")
                        elif re.search(r'早会材料', message):
                            input_data["query_mode"] = "zaohui"
                            logger.info("     📋 [query_mode] zaohui（早会材料 → 1表查询）")
                        elif re.search(r'重过载|过载.*趋势|过载.*情况|过载.*近期', message):
                            if re.search(r'配变', message):
                                input_data["query_mode"] = "guozai_trend_pb"
                                logger.info("     📋 [query_mode] guozai_trend_pb（配变重过载趋势 → 1表查询）")
                            elif re.search(r'馈线|线路', message):
                                input_data["query_mode"] = "guozai_trend_feeder"
                                logger.info("     📋 [query_mode] guozai_trend_feeder（馈线重过载趋势 → 1表查询）")
                            else:
                                input_data["query_mode"] = "guozai_trend"
                                logger.info("     📋 [query_mode] guozai_trend（重过载趋势 → 2表查询）")
                        else:
                            input_data["query_mode"] = "normal"
                            logger.info("     📋 [query_mode] normal（普通查询 → 单表查询）")
                    else:
                        input_data["sql_query"] = extracted_sql
                else:
                    input_data = {
                        "original_request": message,
                        "sql_query": extracted_sql,
                        "upstream_result": previous_result
                    }
                    if agent_id == "dm_agent" and isinstance(previous_result, dict):
                        # 对 dm_agent 进行数据清洗，只传 sql_query，丢弃庞大的上下文
                        # 同时传递 query_mode 和 time_info 用于模板输出
                        input_data = {
                            "sql_query": previous_result.get("sql", extracted_sql),
                            "query_mode": previous_result.get("query_mode", input_data.get("query_mode", "normal")),
                            "time_info": input_data.get("time_info", {}),
                            "resolved_message": input_data.get("resolved_message", message)
                        }
                    elif agent_id == "kunming":
                        input_data["query_result"] = previous_result
                        if isinstance(previous_result, dict) and previous_result.get("query_mode"):
                            input_data["query_mode"] = previous_result["query_mode"]
                    elif agent_id == "reporter_agent":
                        input_data["analysis_result"] = previous_result.get("analysis_result", previous_result) if isinstance(previous_result, dict) else previous_result
                        # ★ 传递工作流执行链，让 reporter 生成反映实际执行流程的流程图
                        execution_flow = []
                        for idx, s in enumerate(workflow["steps"], 1):
                            execution_flow.append({
                                "step": idx,
                                "agent": s["agent"],
                                "description": s.get("description", ""),
                                "role": s.get("role", "")
                            })
                        input_data["execution_flow"] = execution_flow
                    elif agent_id == "file_manager_agent":
                        input_data["report_content"] = previous_result.get("report_content", previous_result) if isinstance(previous_result, dict) else previous_result
                logger.info(f"     📥 [Input] 传入数据: {json.dumps(input_data, ensure_ascii=False, default=str)}")

                # 记录智能体思考阶段（非流式版本，仅打日志）
                logger.info(f"     🤔 [{agent_id}] 开始思考...")

                # 调用gRPC服务 - 使用同一个 Session ID
                logger.info(f"     📡 调用 gRPC: {service_instance['host']}:{service_instance['port']}")
                result = self._call_agent_grpc(
                    host=service_instance["host"],
                    port=service_instance["port"],
                    session_id=session_id,  # 使用传入的 Session ID，所有步骤共享
                    input_data=input_data,
                    instruction=step["description"]
                )

                agents_used.append(agent_id)

                if not result.get("success"):
                    logger.error(f"     ❌ Agent执行失败: {result.get('error')}")
                    yield dfecrab_pb2.StreamChatResponse(
                        error=dfecrab_pb2.StreamError(message=f"Agent {agent_id} 执行失败: {result.get('error')}")
                    )
                    return

                # 发送智能体思考结束事件
                yield dfecrab_pb2.StreamChatResponse(
                    step=dfecrab_pb2.AgentStep(
                        step=step_num,
                        agent=agent_id,
                        action="think_end",
                        answer="",
                        timestamp=datetime.now().isoformat()
                    )
                )

                previous_result = json.loads(result.get("result", "{}"))
                
                # 记录每步的输出（优先使用stream_text纯文字字段）
                content = previous_result.get("stream_text") or \
                          previous_result.get("content") or \
                          previous_result.get("report_content") or \
                          previous_result.get("analysis_result") or \
                          previous_result.get("message") or \
                          str(previous_result)
                content = self._strip_think_tags(content)
                
                step_outputs.append({
                    "agent_id": agent_id,
                    "role": step.get("role", "N/A"),
                    "action": step.get("action", "workflow_step"),
                    "output": content
                })
                
                # yield agent step event
                yield dfecrab_pb2.StreamChatResponse(
                    step=dfecrab_pb2.AgentStep(
                        step=step_num,
                        agent=agent_id,
                        action=step.get("action", "workflow_step"),
                        answer=content,
                        timestamp=datetime.now().isoformat()
                    )
                )
                
                exec_time = result.get('execution_time_ms', 'N/A')
                logger.info(f"     ✅ 执行成功 (耗时: {exec_time}ms)")
                logger.info(f"     📤 [Output] 返回数据: {json.dumps(previous_result, ensure_ascii=False, default=str)}")

            logger.info(f"\n{'─'*60}")
            logger.info(f"✅ [Manager] 复杂任务完成，使用了 {len(agents_used)} 个Agent")
            logger.info(f"   └─ 执行链: {' -> '.join(agents_used)}")
            logger.info(f"{'─'*60}\n")
            
            # 如果所有步骤都被跳过（Agent均不可用），降级为chat
            if not agents_used:
                logger.warning(f"⚠️ [Manager] 工作流中所有Agent均不可用，降级为chat")
                result = self._execute_chat(intent, message, session_id)
                yield dfecrab_pb2.StreamChatResponse(
                    final=dfecrab_pb2.ChatResponse(
                        success=result.get("success", False),
                        session_id=session_id,
                        message=result.get("message", ""),
                        task_type="simple",
                        agents_used=[],
                        audit_log_id="",
                        error="",
                        timestamp=datetime.now().isoformat()
                    )
                )
                return

            execution_flow = []
            for idx, so in enumerate(step_outputs):
                execution_flow.append({"step": idx + 1, "agent": so["agent_id"], "action": so.get("action", "workflow_step"), "answer": so["output"]})
            final_message = execution_flow[-1]["answer"] if execution_flow else ""
            
            # yield final response
            yield dfecrab_pb2.StreamChatResponse(
                final=dfecrab_pb2.ChatResponse(
                    success=True,
                    session_id=session_id,
                    message=final_message,
                    task_type="complex",
                    agents_used=agents_used,
                    audit_log_id="",
                    error="",
                    timestamp=datetime.now().isoformat()
                )
            )

        except Exception as e:
            logger.error(f"\n{'─'*60}")
            logger.error(f"❌ [Manager] 复杂任务执行失败: {e}")
            logger.error(f"   ├─ 已完成步骤: {agents_used}")
            logger.error(f"   └─ 错误详情: {str(e)}")
            logger.error(f"{'─'*60}\n")
            import traceback
            traceback.print_exc()
            yield dfecrab_pb2.StreamChatResponse(
                error=dfecrab_pb2.StreamError(message=f"工作流执行失败: {str(e)}")
            )
    
    def _discover_agent_service(self, agent_id: str) -> Optional[Dict]:
        """通过Zookeeper发现Agent服务（支持worker_agent和default_agent两种类型）"""
        # 同时查询 worker_agent 和 default_agent，合并结果
        instances = self.zk_discovery.discover_service("worker_agent") or []
        default_instances = self.zk_discovery.discover_service("default_agent") or []
        instances = instances + default_instances
        
        if not instances:
            logger.warning(f"⚠️ 未找到任何可用的Agent实例")
            return None
        
        # 根据metadata中的agent_id匹配，兼容metadata缺失的情况（与Gateway逻辑保持一致）
        for instance in instances:
            metadata = instance.get("metadata", {})
            # 优先从 metadata 读取 agent_id
            instance_agent_id = metadata.get("agent_id")
            
            # fallback: 从 service_id 解析（与 Gateway 逻辑保持一致）
            if not instance_agent_id:
                service_id = instance.get("service_id", "")
                if '_agent_' in service_id:
                    # 兼容旧格式: xxx_agent_hostname_time_random
                    instance_agent_id = service_id.split('_agent_')[0]
                else:
                    # 备用方案: default_hostname_time_random / kunming_hostname...
                    parts = service_id.split('_')
                    instance_agent_id = parts[0] if parts else "unknown"
            
            if instance_agent_id == agent_id:
                logger.info(f"🔍 发现 {agent_id}: {instance['host']}:{instance['port']}")
                return instance
        
        logger.error(f"❌ 未找到精确匹配的 Agent: {agent_id}")
        return None
    
    def _call_agent_grpc(
        self,
        host: str,
        port: int,
        session_id: str,
        input_data: Dict,
        instruction: str,
        max_retries: int = 1
    ) -> Dict:
        """调用Agent的gRPC服务，支持重试"""
        channel = None
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                options = [
                    ('grpc.max_send_message_length', 50 * 1024 * 1024),
                    ('grpc.max_receive_message_length', 50 * 1024 * 1024),
                    ('grpc.enable_retries', 0)
                ]
                channel = grpc.insecure_channel(f"{host}:{port}", options=options)
                stub = dfecrab_pb2_grpc.AgentServiceStub(channel)

                request = dfecrab_pb2.ExecuteRequest(
                    session_id=session_id,
                    input_data={k: str(v) for k, v in input_data.items()},
                    skills=[],
                    instruction=instruction,
                    timeout=600,
                    user_id=_get_current_user_id(),
                )

                response = stub.Execute(request, timeout=600.0)

                return {
                    "success": response.success,
                    "agent_id": response.agent_id,
                    "result": response.result,
                    "error": response.error,
                    "execution_time_ms": response.execution_time_ms
                }

            except grpc.RpcError as e:
                last_error = e
                logger.warning(f"⚠️ gRPC调用失败 (尝试 {attempt + 1}/{max_retries + 1}): {e}")
                if attempt < max_retries:
                    time.sleep(1)
            except Exception as e:
                last_error = e
                logger.error(f"❌ 调用Agent失败: {e}")
                break
            finally:
                if channel:
                    try:
                        channel.close()
                    except Exception:
                        pass

        return {
            "success": False,
            "error": f"gRPC调用失败（已重试{max_retries}次）: {str(last_error)}"
        }
    
    def _trim_session_history(self):
        """LRU 淘汰最久未访问的 session，防止内存无限增长"""
        if len(self.session_history) <= self._max_session_history:
            return
        # 按最后访问时间排序，淘汰最旧的
        excess = len(self.session_history) - self._max_session_history
        sorted_sessions = sorted(self._session_last_access.items(), key=lambda x: x[1])
        for session_id, _ in sorted_sessions[:excess]:
            self.session_history.pop(session_id, None)
            self._session_last_access.pop(session_id, None)
            logger.info(f"🗑️ [LRU] 淘汰旧 session: {session_id[:20]}...")
    
    def _save_audit_log(self, session_id: str, message: str, intent: Dict, result: Dict) -> str:
        """保存审计日志"""
        audit_id = f"audit_{uuid4().hex[:12]}"
        
        audit_entry = {
            "audit_id": audit_id,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "user_message": message,
            "intent": intent,
            "result": result,
            "agents_used": result.get("agents_used", [])
        }
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audit_file = AUDIT_DIR / f"{audit_id}_{timestamp}.json"
        
        try:
            with open(audit_file, 'w', encoding='utf-8') as f:
                json.dump(audit_entry, f, indent=2, ensure_ascii=False)
            logger.info(f"📝 审计日志已保存: {audit_file}")
        except Exception as e:
            logger.error(f"⚠️ 审计日志保存失败: {e}（不影响主流程）")
        
        return audit_id
    
    def _learn_from_task(self, message: str, intent: Dict, result: Dict):
        """
        从任务中学习经验，更新长期记忆
        
        Args:
            message: 用户消息
            intent: 意图识别结果
            result: 执行结果
        """
        task_type = result.get("task_type")
        success = result.get("success", False)
        agents_used = result.get("agents_used", [])
        
        # 1. 记录成功模式
        if success and agents_used:
            pattern = f"任务类型:{task_type}, 使用Agents:{' -> '.join(agents_used)}, 成功执行"
            self.memory_mgr.add_to_long_term(
                "successful_patterns",
                pattern,
                tags=[task_type] + agents_used
            )
            logger.debug(f"📚 记录成功模式: {pattern}")
        
        # 2. 记录失败教训
        if not success:
            error_msg = result.get("message", "未知错误")
            lesson = f"任务类型:{task_type}, 失败原因:{error_msg}"
            self.memory_mgr.add_to_long_term(
                "lessons_learned",
                lesson,
                tags=[task_type, "failure"]
            )
            logger.debug(f"⚠️  记录失败教训: {lesson}")

def _register_with_retry(registry, port: int, service_id: str) -> bool:
    """注册到 Zookeeper，带重试和断连后后台兜底自动重新注册"""
    max_retries = 5
    retry_delay = 2

    # 解析 ZK 地址作为探针目标，自动探测本机对外可达 IP
    try:
        _zk_host, _zk_port = registry.zk_hosts.split(":")
        _zk_port = int(_zk_port)
    except Exception:
        _zk_host, _zk_port = registry.zk_hosts, 2181

    def _do_register() -> bool:
        local_ip = _get_local_ip(_zk_host, _zk_port)
        return registry.register_service(
            service_name="manager_agent",
            service_id=service_id,
            host=local_ip,          # ← 动态获取真实 IP
            port=port,
            metadata={"agent_id": "manager_agent", "version": "1.0.0"},
        )
    # ── 1. 初次注册（指数退避重试） ──
    for attempt in range(1, max_retries + 1):
        if registry.zk and not registry.zk.connected:
            logger.warning(
                f"⏳ Zookeeper 连接已断开，等待重连 (尝试 {attempt}/{max_retries})..."
            )
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
            continue

        if _do_register():
            logger.info(f"✅ 服务注册成功，服务ID: {service_id}")
            break

        logger.warning(
            f"⏳ 服务注册失败 (尝试 {attempt}/{max_retries})，{retry_delay}秒后重试..."
        )
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 30)
    else:
        logger.warning("⚠️ 初次注册全部失败，将以后台线程持续重试")

    # ── 2. 始终启动后台守护线程：监控 ZK 状态，断连后自动重新注册 ──
    logger.info("🔄 启动 ZK 注册守护线程（每 10 秒检查一次）...")

    def _watchdog():
        instance_path = f"{registry.base_path}/manager_agent/{service_id}"
        while True:
            try:
                if registry.zk and registry.zk.connected:
                    # 检查 ephemeral 节点是否仍然存在
                    if not registry.zk.exists(instance_path):
                        logger.warning(
                            "⚠️ ZK 临时节点已丢失（可能因断连被删除），重新注册..."
                        )
                        _do_register()
                else:
                    logger.debug("⏳ ZK 未连接，等待重连后恢复注册...")
            except Exception as e:
                logger.debug(f"⏳ 注册守护线程异常: {e}")
            time.sleep(10)

    t = threading.Thread(target=_watchdog, daemon=True)
    t.start()
    return True


def serve(port: int = None, zk_hosts: str = None):
    """启动gRPC服务"""
    if zk_hosts is None:
        from src.config.config_loader import config as _cfg
        zk_hosts = _cfg.zk_hosts
    
    # 动态分配端口（如果未指定）
    if port is None:
        from src.gateway.grpc.port_allocator import get_available_port
        port = get_available_port()
        logger.info(f"🎯 动态分配端口: {port}")
    logger.info(f"🚀 正在启动 Manager Agent...")
    
    # 1. 连接到Zookeeper
    registry = ZKServiceRegistry(zk_hosts=zk_hosts)
    if not registry.connect():
        logger.error("❌ Zookeeper连接失败")
        return
    
    # 2. 创建gRPC服务器
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    service_impl = ManagerAgentServiceImpl(zk_hosts=zk_hosts)
    dfecrab_pb2_grpc.add_ManagerServiceServicer_to_server(service_impl, server)
    
    # 3. 绑定端口并启动
    server.add_insecure_port(f'[::]:{port}')
    server.start()
    
    # 4. 注册到Zookeeper（带重试：ZK 连接抖动时自动恢复）
    hostname = socket.gethostname()
    service_id = f"manager_agent_{hostname}_{int(time.time())}"

    _register_with_retry(registry, port, service_id)

    logger.info(f"✅ Manager Agent 已启动")
    logger.info(f"   📝 Zookeeper: {zk_hosts}")
    logger.info(f"   🆔 服务ID: {service_id}")
    local_ip = _get_local_ip(zk_hosts.split(":")[0], int(zk_hosts.split(":")[1]) if ":" in zk_hosts else 2181)
    logger.info(f"   📍 地址: {local_ip}:{port}")
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("\n👋 正在停止 Manager Agent...")
        registry.deregister_service("manager_agent", service_id)
        server.stop(0)
        registry.close()
        service_impl.zk_discovery.close()
        logger.info("✅ Manager Agent 已停止")


def main():
    from src.config.config_loader import config as _cfg
    parser = argparse.ArgumentParser(description="Manager Agent gRPC Service")
    parser.add_argument("--port", type=int, default=None, help="gRPC端口（不指定则动态分配）")
    parser.add_argument("--zk-hosts", default=_cfg.zk_hosts, help="Zookeeper地址")
    args = parser.parse_args()
    
    serve(args.port, args.zk_hosts)


if __name__ == "__main__":
    main()