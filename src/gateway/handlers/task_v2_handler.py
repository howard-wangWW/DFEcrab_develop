"""
Task V2 Handler - 任务管理 API Handler

提供 RESTful API 接口：
- POST   /api/v2/tasks                      # 创建任务
- GET    /api/v2/tasks                      # 列出任务
- GET    /api/v2/tasks/{task_id}            # 任务详情
- POST   /api/v2/tasks/{task_id}/convert    # 转化任务类型
- DELETE /api/v2/tasks/{task_id}            # 取消任务
- GET    /api/v2/tasks/{task_id}/progress   # 获取进度
- GET    /api/v2/tasks/{task_id}/audit      # 获取审计日志
- GET    /api/v2/tasks/{task_id}/dashboard  # 获取看板数据
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.task.models import TaskStatus, TaskType
from src.task.task_manager import TaskManager
from src.task.supervisor import SupervisorSession
from src.task.agent_group import AgentGroup

logger = logging.getLogger(__name__)


class TaskV2Handler:
    """任务管理 API Handler"""
    
    def __init__(self, task_manager: TaskManager, storage_dir: str = "data/tasks"):
        self.task_manager = task_manager
        self.storage_dir = storage_dir
        self._supervisors: Dict[str, SupervisorSession] = {}
    
    async def handle_create_task(self, request) -> Dict[str, Any]:
        """
        创建任务

        请求体：
        {
            "topic": "任务主题",
            "task_type": "temporary|periodic",
            "description": "任务描述",
            "supervisor_agent_id": "监管 Agent ID",
            "agent_group_config": {
                "members": [
                    {"agent_id": "qwencode", "role": "designer"},
                    {"agent_id": "codebuddy", "role": "developer"},
                ]
            },
            "schedule": {"cron": "0 9 * * 1"}  # 仅周期任务
        }
        """
        try:
            # 解析请求体
            if hasattr(request, 'json'):
                body = await request.json()
            else:
                body = request
            
            # 兼容：topic 缺失时用 title 兜底
            topic = body.get("topic") or body.get("title")
            task_type_str = body.get("task_type", "temporary")
            description = body.get("description", "")
            supervisor_agent_id = body.get("supervisor_agent_id", "supervisor_01")
            agent_group_config = body.get("agent_group_config", {})
            schedule = body.get("schedule")
            
            if not topic:
                return {"success": False, "error": "topic (或 title) is required"}
            if not agent_group_config.get("members"):
                return {"success": False, "error": "agent_group_config.members is required"}
            
            task_type = TaskType(task_type_str)
            
            result = self.task_manager.create_task(
                topic=topic,
                task_type=task_type,
                description=description,
                supervisor_agent_id=supervisor_agent_id,
                agent_group_config=agent_group_config,
                schedule=schedule,
            )
            # create_task 返回的是 {"task": <Task>, ...} 字典，取出真正的 Task 对象
            task = result["task"]
            
            # 创建 SupervisorSession（参数对齐真实签名 task_id/task_manager）
            agent_group = AgentGroup(
                task_id=task.task_id,
                task_type=task_type,
                config=agent_group_config,
            )
            supervisor = SupervisorSession(
                task_id=task.task_id,
                task_manager=self.task_manager,
            )
            self._supervisors[task.task_id] = supervisor
            
            return {
                "success": True,
                "data": {
                    "task_id": task.task_id,
                    "topic": task.topic,
                    "task_type": task.task_type.value,
                    "status": task.status.value,
                    "supervisor_session_id": task.supervisor_session_id,
                    "agent_group": agent_group.to_dict(),
                },
            }
        
        except Exception as e:
            logger.error(f"Failed to create task: {e}")
            return {"success": False, "error": str(e)}
    
    async def handle_list_tasks(
        self,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """列出任务"""
        try:
            tt = TaskType(task_type) if task_type else None
            st = TaskStatus(status) if status else None
            
            result = self.task_manager.list_tasks(task_type=tt, status=st, limit=limit, offset=offset)
            
            task_list = result.get("tasks", [])
            return {
                "success": True,
                "data": {
                    "tasks": [
                        {
                            "task_id": t.task_id,
                            "topic": t.topic,
                            "task_type": t.task_type.value if hasattr(t.task_type, 'value') else t.task_type,
                            "status": t.status.value if hasattr(t.status, 'value') else t.status,
                            "created_at": t.created_at.isoformat() if hasattr(t.created_at, 'isoformat') else str(t.created_at),
                        }
                        for t in task_list
                    ],
                    "count": result.get("count", 0),
                    "limit": limit,
                    "offset": offset,
                },
            }
        
        except Exception as e:
            logger.error(f"Failed to list tasks: {e}")
            return {"success": False, "error": str(e)}
    
    async def handle_get_task(self, task_id: str) -> Dict[str, Any]:
        """获取任务详情"""
        task = self.task_manager.get_task(task_id)
        if not task:
            return {"success": False, "error": "Task not found"}
        
        return {
            "success": True,
            "data": task.to_dict(),
        }
    
    async def handle_convert_task(self, task_id: str, target_type: str) -> Dict[str, Any]:
        """转化任务类型"""
        try:
            target = TaskType(target_type)
            new_task = self.task_manager.convert_task(task_id, target)
            
            if not new_task:
                return {"success": False, "error": "Task not found"}
            
            return {
                "success": True,
                "data": {
                    "original_task_id": task_id,
                    "new_task_id": new_task.task_id,
                    "new_task_type": new_task.task_type.value,
                },
            }
        
        except Exception as e:
            logger.error(f"Failed to convert task: {e}")
            return {"success": False, "error": str(e)}
    
    async def handle_delete_task(self, task_id: str) -> Dict[str, Any]:
        """取消/删除任务"""
        success = self.task_manager.delete_task(task_id)
        if not success:
            return {"success": False, "error": "Task not found"}
        
        # 清理 SupervisorSession
        if task_id in self._supervisors:
            del self._supervisors[task_id]
        
        return {"success": True, "message": "Task deleted"}
    
    async def handle_get_progress(self, task_id: str) -> Dict[str, Any]:
        """获取任务进度"""
        progress = self.task_manager.get_task_progress(task_id)
        if not progress:
            return {"success": False, "error": "Task not found"}
        
        return {"success": True, "data": progress}
    
    async def handle_get_audit_log(
        self,
        task_id: str,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """获取审计日志"""
        # 尝试从 SupervisorSession 获取
        supervisor = self._supervisors.get(task_id)
        if supervisor:
            logs = supervisor.audit_logger.get_logs(agent=agent, action=action, limit=limit)
        else:
            # 如果 SupervisorSession 不存在，尝试从文件加载
            from src.task.audit import AuditLogger
            audit_logger = AuditLogger(task_id, storage_dir=f"{self.storage_dir}/audit")
            logs = audit_logger.get_logs(agent=agent, action=action, limit=limit)
        
        return {
            "success": True,
            "data": {
                "logs": [l.to_dict() for l in logs],
                "count": len(logs),
            },
        }
    
    async def handle_get_dashboard(self, task_id: str) -> Dict[str, Any]:
        """获取看板数据"""
        supervisor = self._supervisors.get(task_id)
        if not supervisor:
            return {"success": False, "error": "Task not found or no supervisor"}
        
        return {
            "success": True,
            "data": supervisor.get_dashboard_data(),
        }
    
    async def handle_execute_task(self, task_id: str, user_input: str) -> Dict[str, Any]:
        """执行任务"""
        supervisor = self._supervisors.get(task_id)
        if not supervisor:
            return {"success": False, "error": "Task not found or no supervisor"}
        
        try:
            await supervisor.coordinate_task(user_input)
            
            return {
                "success": True,
                "data": {
                    "task_id": task_id,
                    "status": supervisor.task.status.value,
                    "progress": supervisor.progress_tracker.overall_progress,
                },
            }
        
        except Exception as e:
            logger.error(f"Failed to execute task {task_id}: {e}")
            return {"success": False, "error": str(e)}
