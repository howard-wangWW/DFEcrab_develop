# src/core/task/models.py
"""Task Models"""
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime
from uuid import uuid4


class TaskStatus(Enum):
    DRAFT = "draft"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    PENDING_APPROVAL = "pending_approval"
    CONVERTED = "converted"   # 任务类型转化后，原任务置为此状态（V2 契约）


class TaskType(Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"
    TEMPORARY = "temporary"
    PERIODIC = "periodic"
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"


class CollaborationMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HYBRID = "hybrid"


class TaskStepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


def _parse_datetime(value) -> datetime:
    """安全地将字符串或 datetime 转为 datetime 对象"""
    if value is None:
        return datetime.now()
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        value = value.replace('Z', '+00:00')
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.now()
    return datetime.now()


class TaskStep:
    """任务步骤"""
    
    def __init__(self, **kwargs):
        self.step_id = kwargs.get("step_id", f"step_{datetime.now().strftime('%Y%m%d%H%M%S')}")
        self.task_id = kwargs.get("task_id", "")
        self.agent_id = kwargs.get("agent_id", "")
        self.step_order = kwargs.get("step_order", 0)
        self.step_name = kwargs.get("step_name", "")
        self.group = kwargs.get("group", 0)
        
        self.status = kwargs.get("status", TaskStepStatus.PENDING)
        if isinstance(self.status, str):
            self.status = TaskStepStatus(self.status)
        
        self.input_data = kwargs.get("input_data", {})
        self.output_data = kwargs.get("output_data", {})
        self.logs = kwargs.get("logs", "")
        self.error_message = kwargs.get("error_message", "")
        
        self.started_at = _parse_datetime(kwargs.get("started_at"))
        self.completed_at = _parse_datetime(kwargs.get("completed_at"))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "step_order": self.step_order,
            "step_name": self.step_name,
            "group": self.group,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "logs": self.logs,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if isinstance(self.started_at, datetime) else self.started_at,
            "completed_at": self.completed_at.isoformat() if isinstance(self.completed_at, datetime) else self.completed_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TaskStep':
        return cls(**data)


class Task:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "")
        self.task_id = kwargs.get("task_id", self.id or f"task_{datetime.now().strftime('%Y%m%d%H%M%S')}")
        self.topic = kwargs.get("topic", "")
        
        self.status = kwargs.get("status", TaskStatus.PENDING)
        if isinstance(self.status, str):
            self.status = TaskStatus(self.status)
            
        self.type = kwargs.get("type", TaskType.SIMPLE)
        self.task_type = kwargs.get("task_type", self.type)
        if isinstance(self.task_type, str):
            self.task_type = TaskType(self.task_type)
            
        self.title = kwargs.get("title", self.topic)
        self.description = kwargs.get("description", "")
        self.supervisor_agent_id = kwargs.get("supervisor_agent_id", "supervisor_01")
        self.agent_group_config = kwargs.get("agent_group_config", {})
        self.schedule = kwargs.get("schedule", None)
        self.supervisor_session_id = kwargs.get("supervisor_session_id", "")
        
        self.manager_recommendation = kwargs.get("manager_recommendation", None)
        self.execution_mode = kwargs.get("execution_mode", "auto_select")
        self.collaboration_mode = kwargs.get("collaboration_mode", CollaborationMode.SEQUENTIAL)
        if isinstance(self.collaboration_mode, str):
            try:
                self.collaboration_mode = CollaborationMode(self.collaboration_mode)
            except ValueError:
                self.collaboration_mode = CollaborationMode.SEQUENTIAL
        self.selected_agents = kwargs.get("selected_agents", [])
        self.steps = kwargs.get("steps", [])
        self.require_confirmation = kwargs.get("require_confirmation", True)
        self.approved_by = kwargs.get("approved_by", "")
        self.approved_at = kwargs.get("approved_at", None)
        self.retry_config = kwargs.get("retry_config", {"max_attempts": 3, "backoff": "exponential"})
        self.notification_config = kwargs.get("notification_config", {})
        self.trigger_config = kwargs.get("trigger_config", None)
        self.progress = kwargs.get("progress", 0)
        self.current_step = kwargs.get("current_step", "")
        self.error_message = kwargs.get("error_message", "")
        self.parent_task_id = kwargs.get("parent_task_id", "")
        self.result = kwargs.get("result", None)
        self.rejected_by = kwargs.get("rejected_by", "")
        self.rejected_at = kwargs.get("rejected_at", None)
        self.reject_reason = kwargs.get("reject_reason", "")
        
        self.created_at = _parse_datetime(kwargs.get("created_at"))
        self.updated_at = _parse_datetime(kwargs.get("updated_at"))
        self.started_at = _parse_datetime(kwargs.get("started_at"))
        self.completed_at = _parse_datetime(kwargs.get("completed_at"))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "topic": self.topic,
            "title": self.title,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "task_type": self.task_type.value if isinstance(self.task_type, Enum) else self.task_type,
            "description": self.description,
            "supervisor_agent_id": self.supervisor_agent_id,
            "agent_group_config": self.agent_group_config,
            "schedule": self.schedule,
            "supervisor_session_id": self.supervisor_session_id,
            "manager_recommendation": self.manager_recommendation,
            "execution_mode": self.execution_mode,
            "collaboration_mode": self.collaboration_mode.value if isinstance(self.collaboration_mode, Enum) else self.collaboration_mode,
            "selected_agents": self.selected_agents,
            "steps": [step.to_dict() if hasattr(step, 'to_dict') else step for step in self.steps],
            "require_confirmation": self.require_confirmation,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if isinstance(self.approved_at, datetime) else self.approved_at,
            "retry_config": self.retry_config,
            "notification_config": self.notification_config,
            "trigger_config": self.trigger_config,
            "progress": self.progress,
            "current_step": self.current_step,
            "error_message": self.error_message,
            "parent_task_id": self.parent_task_id,
            "result": self.result,
            "rejected_by": self.rejected_by,
            "rejected_at": self.rejected_at.isoformat() if isinstance(self.rejected_at, datetime) else self.rejected_at,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else self.updated_at,
            "started_at": self.started_at.isoformat() if isinstance(self.started_at, datetime) else self.started_at,
            "completed_at": self.completed_at.isoformat() if isinstance(self.completed_at, datetime) else self.completed_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        data = dict(data)
        
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = TaskStatus(data['status'])
        if 'task_type' in data and isinstance(data['task_type'], str):
            data['task_type'] = TaskType(data['task_type'])
        if 'type' in data and isinstance(data['type'], str):
            data['type'] = TaskType(data['type'])
        if 'collaboration_mode' in data and isinstance(data['collaboration_mode'], str):
            try:
                data['collaboration_mode'] = CollaborationMode(data['collaboration_mode'])
            except ValueError:
                pass
        
        if 'steps' in data and isinstance(data['steps'], list):
            data['steps'] = [TaskStep.from_dict(s) if isinstance(s, dict) else s for s in data['steps']]
        
        return cls(**data)


class TaskProgress:
    """任务进度聚合（单一事实源：由 Task.steps 计算，供 progress/dashboard 接口复用）。

    字段与《TASK_API_V2.md》契约一致：
        task_id / total_steps / completed_steps / current_step
        overall_progress / is_complete / member_progress / started_at / completed_at
    """

    #: 视为“已完成”的步骤状态
    DONE_STATUSES = ("completed", "skipped")

    def __init__(self, task_id: str, total_steps: int = 0, **kwargs):
        self.task_id = task_id
        self.total_steps = int(total_steps or 0)
        self.completed_steps = int(kwargs.get("completed_steps") or 0)
        self.current_step = kwargs.get("current_step", "")
        self.member_progress: Dict[str, float] = dict(kwargs.get("member_progress") or {})
        self.started_at = kwargs.get("started_at")
        self.completed_at = kwargs.get("completed_at")

    # ---------- 计算 ----------
    @property
    def overall_progress(self) -> float:
        """整体进度百分比（0~100）。无步骤时回落到成员进度的均值。"""
        if self.total_steps > 0:
            return round(self.completed_steps / self.total_steps * 100, 1)
        if self.member_progress:
            return round(sum(self.member_progress.values()) / len(self.member_progress), 1)
        return 0.0

    @property
    def is_complete(self) -> bool:
        return self.total_steps > 0 and self.completed_steps >= self.total_steps

    def update_step(self, step_index: int, status: str, agent_id: str = "", progress: float = None) -> None:
        """更新某一步的状态，并同步 completed_steps / member_progress。"""
        status = status.value if isinstance(status, Enum) else str(status)
        if status in self.DONE_STATUSES:
            self.completed_steps = min(self.completed_steps + 1, self.total_steps) if self.total_steps else self.completed_steps + 1
        elif status == "running":
            self.current_step = step_index
        if agent_id:
            if progress is None:
                progress = 100.0 if status in self.DONE_STATUSES else (50.0 if status == "running" else 0.0)
            self.member_progress[agent_id] = float(progress)

    @classmethod
    def from_task(cls, task: 'Task') -> 'TaskProgress':
        """由 Task 对象（含 steps）构建进度快照。"""
        steps = list(getattr(task, "steps", None) or [])
        prog = cls(task_id=task.task_id, total_steps=len(steps),
                   current_step=task.current_step,
                   started_at=task.started_at.isoformat() if isinstance(task.started_at, datetime) else None,
                   completed_at=task.completed_at.isoformat() if isinstance(task.completed_at, datetime) else None)
        for step in steps:
            status = step.status.value if hasattr(step.status, "value") else str(step.status)
            if status in cls.DONE_STATUSES:
                prog.completed_steps += 1
            if getattr(step, "agent_id", ""):
                prog.member_progress[step.agent_id] = 100.0 if status in cls.DONE_STATUSES else (50.0 if status == "running" else 0.0)
        return prog

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "overall_progress": self.overall_progress,
            "is_complete": self.is_complete,
            "member_progress": self.member_progress,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class AuditLogEntry:
    """任务审计日志条目（写入 data/tasks/audit/<task_id>.json）。"""

    def __init__(self, **kwargs):
        self.audit_id = kwargs.get("audit_id") or f"audit_{uuid4().hex[:12]}"
        self.task_id = kwargs.get("task_id", "")
        self.action = kwargs.get("action", "")
        self.agent = kwargs.get("agent", "")
        self.details = kwargs.get("details") or {}
        ts = kwargs.get("timestamp")
        self.timestamp = ts if isinstance(ts, str) and ts else datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "task_id": self.task_id,
            "action": self.action,
            "agent": self.agent,
            "details": self.details,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditLogEntry':
        return cls(**(data or {}))