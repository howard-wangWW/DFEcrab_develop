"""Task Supervisor - 任务监督器

职责：维护任务执行期状态（进度、步骤、审计），并对外提供
progress/dashboard 所需的聚合数据。

历史问题（本次修复）：
`src/gateway/handlers/task_v2_handler.py` 引用了 `supervisor.audit_logger`、
`supervisor.progress_tracker`、`supervisor.get_dashboard_data()`、
`supervisor.coordinate_task()`，但本类从未实现 —— 导致
`/audit`、`/dashboard`、`/execute` 三条链路必抛 AttributeError。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.task.audit import AuditLogger
from src.task.models import TaskProgress, TaskStatus
from src.task.task_manager import TaskManager

logger = logging.getLogger(__name__)


class ProgressTracker:
    """执行期进度跟踪：包装 `TaskProgress`，支持运行时增量更新。"""

    def __init__(self, task_progress: TaskProgress):
        self._progress = task_progress

    @property
    def overall_progress(self) -> float:
        return self._progress.overall_progress

    @property
    def is_complete(self) -> bool:
        return self._progress.is_complete

    @property
    def total_steps(self) -> int:
        return self._progress.total_steps

    @property
    def completed_steps(self) -> int:
        return self._progress.completed_steps

    def update_step(self, step_index: int, status: str, agent_id: str = "",
                    progress: Optional[float] = None) -> None:
        self._progress.update_step(step_index, status, agent_id=agent_id, progress=progress)

    def to_dict(self) -> Dict[str, Any]:
        return self._progress.to_dict()


class SupervisorSession:
    """监督会话 - 管理单个任务的执行与可观测数据。"""

    def __init__(self, task_id: str, task_manager: Optional[TaskManager] = None):
        self.task_id = task_id
        self.task_manager = task_manager or TaskManager()
        self._running = False
        self._start_time: Optional[datetime] = None
        self.audit_logger = self._build_audit_logger()
        self._progress = self._build_progress()

    # ---------- 内部 ----------
    def _audit_dir(self) -> Optional[str]:
        storage_dir = getattr(self.task_manager, "storage_dir", None)
        return str(Path(storage_dir) / "audit") if storage_dir else None

    def _build_audit_logger(self) -> AuditLogger:
        try:
            return AuditLogger(self.task_id, storage_dir=self._audit_dir())
        except Exception:
            return AuditLogger(self.task_id)

    def _build_progress(self) -> ProgressTracker:
        task = self.task_manager.get_task(self.task_id)
        if task:
            return ProgressTracker(TaskProgress.from_task(task))
        return ProgressTracker(TaskProgress(task_id=self.task_id))

    @property
    def progress_tracker(self) -> ProgressTracker:
        """执行期进度（步骤状态变更后自动反映）。"""
        return self._progress

    @property
    def is_running(self) -> bool:
        return self._running

    # ---------- 生命周期 ----------
    async def start(self) -> bool:
        """开始监督任务"""
        task = self.task_manager.get_task(self.task_id)
        if not task:
            logger.error(f"任务不存在: {self.task_id}")
            return False

        if task.status in [TaskStatus.RUNNING, TaskStatus.COMPLETED]:
            logger.warning(f"任务已在运行或已完成: {self.task_id}")
            return False

        self._running = True
        self._start_time = datetime.now()
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.updated_at = datetime.now()
        self.task_manager._save_task(task)
        self._progress = self._build_progress()

        self.audit_logger.log("start", details={"status": task.status.value})
        logger.info(f"开始监督任务: {self.task_id}")
        return True

    async def stop(self) -> None:
        """停止监督"""
        self._running = False
        task = self.task_manager.get_task(self.task_id)
        if task:
            task.status = TaskStatus.CANCELLED
            task.updated_at = datetime.now()
            self.task_manager._save_task(task)
            self.task_manager._save_index()

        self.audit_logger.log("stop", details={"status": "cancelled"})
        logger.info(f"停止监督任务: {self.task_id}")

    # ---------- 进度 ----------
    def update_progress(self, progress: int, current_step: str = "") -> None:
        """更新进度（仅运行中生效）"""
        if not self._running:
            return
        task = self.task_manager.get_task(self.task_id)
        if not task:
            return
        task.progress = progress
        if current_step:
            task.current_step = current_step
        task.updated_at = datetime.now()
        self.task_manager._save_task(task)

    def update_step(self, step_index: int, status: str,
                    output_data: Optional[Dict] = None, logs: str = "") -> None:
        """更新步骤状态：同步持久化 + 进度聚合 + 审计。"""
        task = self.task_manager.update_task_step(self.task_id, step_index, status, output_data, logs)
        agent_id = ""
        if task and task.steps and 0 <= step_index < len(task.steps):
            agent_id = getattr(task.steps[step_index], "agent_id", "") or ""
        self._progress.update_step(step_index, status, agent_id=agent_id)
        self.audit_logger.log(
            f"step_{status}",
            agent=agent_id,
            details={"step_index": step_index, "logs": (logs or "")[:200]},
        )

    def complete(self, success: bool = True) -> None:
        """完成任务"""
        task = self.task_manager.get_task(self.task_id)
        if not task:
            return
        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.completed_at = datetime.now()
        task.updated_at = datetime.now()
        if success:
            task.progress = 100
        self.task_manager._save_task(task)
        self.task_manager._save_index()
        self._running = False
        self.audit_logger.log(
            "complete" if success else "fail",
            details={"progress": task.progress, "error": task.error_message or ""},
        )
        logger.info(f"任务完成: {self.task_id}, success={success}")

    # ---------- 执行 / 看板 ----------
    async def coordinate_task(self, user_input: str = "") -> Dict[str, Any]:
        """执行任务（委托 TaskExecutor，避免与执行引擎重复实现）。"""
        from src.task.executor import TaskExecutor

        task = self.task_manager.get_task(self.task_id)
        if not task:
            return {"success": False, "error": f"任务不存在: {self.task_id}"}

        if task.status == TaskStatus.DRAFT:
            return {"success": False, "error": "任务尚未确认（draft），请先 approve"}

        self.audit_logger.log("execute", details={"user_input": (user_input or "")[:200]})
        ok = await TaskExecutor(self.task_manager).execute_task(
            self.task_id, {"user_input": user_input} if user_input else None
        )
        task = self.task_manager.get_task(self.task_id)
        return {
            "success": bool(ok),
            "task_id": self.task_id,
            "status": task.status.value if task else "unknown",
            "progress": self.progress_tracker.overall_progress,
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """任务看板数据（契约见《TASK_API_V2.md》§8）。"""
        task = self.task_manager.get_task(self.task_id)
        if not task:
            return {}

        progress = TaskProgress.from_task(task)
        members_cfg = (task.agent_group_config or {}).get("members", []) or []
        members = []
        for member in members_cfg:
            if isinstance(member, dict):
                agent_id, role = member.get("agent_id", ""), member.get("role", "")
            else:  # 兼容 TaskMember 之类的对象
                agent_id, role = getattr(member, "agent_ref", ""), getattr(member, "role", "")
            member_progress = progress.member_progress.get(agent_id)
            members.append({
                "agent": agent_id,
                "role": role,
                "status": "completed" if member_progress == 100.0 else ("running" if member_progress else "pending"),
                "progress": member_progress if member_progress is not None else 0.0,
            })

        return {
            "task_id": task.task_id,
            "topic": task.topic,
            "title": task.title,
            "task_type": task.task_type.value if hasattr(task.task_type, "value") else str(task.task_type),
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "progress": task.progress,
            "is_complete": progress.is_complete,
            "members": members,
            "workflow": {
                "total_steps": progress.total_steps,
                "current_step": progress.current_step,
                "steps": [s.to_dict() if hasattr(s, "to_dict") else s for s in (task.steps or [])],
            },
            "audit_summary": self.audit_logger.summary(),
        }


_instance: Optional[SupervisorSession] = None


def get_task_supervisor(task_id: str = "", task_manager: Optional[TaskManager] = None) -> Optional[SupervisorSession]:
    """获取/创建监督会话（指定 task_id 时按需创建）。"""
    global _instance
    if task_id:
        if _instance is None or _instance.task_id != task_id:
            _instance = SupervisorSession(task_id, task_manager)
        return _instance
    return _instance


def create_supervisor(task_id: str, task_manager: Optional[TaskManager] = None) -> SupervisorSession:
    """创建监督会话"""
    return SupervisorSession(task_id, task_manager)