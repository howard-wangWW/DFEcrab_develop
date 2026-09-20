"""轻量任务调度器（待办 / 心跳 / 定时 三类内存作业 + 待办持久化）。

职责边界：
- 本模块只管"待办(todo)/心跳(heartbeat)/定时(scheduled)"三类轻量作业的登记与状态；
- 真正的 cron/周期触发由 `src.task.periodic_scheduler.PeriodicScheduler` 负责；
- 业务任务（Task）的 CRUD 由 `src.task.task_manager.TaskManager` 负责。

历史问题：gateway 的 `/api/tasks/todos*`、`/api/tasks/stats` 直接调用了
TaskManager 上并不存在的方法（list_todos/add_todo/complete_todo/get_stats），
导致接口恒失败。本次把这三个接口收敛到本模块，并给待办加持久化。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskPriority(IntEnum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _iso(value) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) else None


@dataclass
class HeartbeatTask:
    task_id: str
    name: str
    interval_seconds: int
    handler: Callable
    timeout_seconds: int = 5
    max_retries: int = 3
    last_run: Optional[datetime] = None
    run_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "interval_seconds": self.interval_seconds,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "last_run": _iso(self.last_run),
            "run_count": self.run_count,
        }


@dataclass
class ScheduledTask:
    task_id: str
    name: str
    handler: Callable
    interval_seconds: Optional[int] = None
    cron_expression: Optional[str] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    is_enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "interval_seconds": self.interval_seconds,
            "cron_expression": self.cron_expression,
            "last_run": _iso(self.last_run),
            "next_run": _iso(self.next_run),
            "run_count": self.run_count,
            "is_enabled": self.is_enabled,
        }


@dataclass
class TodoTask:
    task_id: str
    title: str
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    due_date: Optional[datetime] = None
    dependencies: List[str] = field(default_factory=list)
    condition: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "priority": int(self.priority),
            "priority_label": self.priority.name.lower(),
            "status": self.status.value if isinstance(self.status, Enum) else str(self.status),
            "due_date": _iso(self.due_date),
            "dependencies": self.dependencies,
            "condition": self.condition,
            "context": self.context,
            "created_at": _iso(self.created_at),
            "completed_at": _iso(self.completed_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TodoTask":
        data = dict(data or {})
        try:
            data["priority"] = TaskPriority(int(data.get("priority", TaskPriority.NORMAL)))
        except (TypeError, ValueError):
            data["priority"] = TaskPriority.NORMAL
        try:
            data["status"] = TaskStatus(data.get("status", TaskStatus.PENDING.value))
        except ValueError:
            data["status"] = TaskStatus.PENDING
        for key in ("due_date", "created_at", "completed_at"):
            raw = data.get(key)
            if isinstance(raw, str) and raw:
                try:
                    data[key] = datetime.fromisoformat(raw)
                except ValueError:
                    data[key] = None
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known.pop("handler", None)
        return cls(**known)


class TaskScheduler:
    """轻量作业调度器（单进程内存 + 待办 JSON 持久化）。"""

    def __init__(self, tasks_dir: str = "data/tasks"):
        self.tasks_dir = Path(tasks_dir)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._todo_file = self.tasks_dir / "todos.json"
        self._heartbeat_tasks: Dict[str, HeartbeatTask] = {}
        self._scheduled_tasks: Dict[str, ScheduledTask] = {}
        self._todos: Dict[str, TodoTask] = {}
        self._running = False
        self._load_todos()

    # ---------- 持久化 ----------
    def _load_todos(self) -> None:
        if not self._todo_file.exists():
            return
        try:
            data = json.loads(self._todo_file.read_text(encoding="utf-8"))
            for item in data if isinstance(data, list) else []:
                todo = TodoTask.from_dict(item)
                if todo.task_id:
                    self._todos[todo.task_id] = todo
            logger.info(f"✅ 已恢复 {len(self._todos)} 个待办")
        except Exception as e:
            logger.warning(f"⚠️ 读取待办失败: {e}")

    def _save_todos(self) -> None:
        try:
            self._todo_file.write_text(
                json.dumps([t.to_dict() for t in self._todos.values()], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"⚠️ 保存待办失败: {e}")

    # ---------- 生命周期 ----------
    def start(self):
        self._running = True

    def stop(self):
        self._running = False
        self._save_todos()

    # ---------- 心跳 / 定时登记 ----------
    def register_heartbeat_task(self, task: HeartbeatTask):
        self._heartbeat_tasks[task.task_id] = task

    def register_scheduled_task(self, task: ScheduledTask):
        self._scheduled_tasks[task.task_id] = task

    def get_heartbeat_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self._heartbeat_tasks.get(task_id)
        return task.to_dict() if task else None

    def list_heartbeats(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self._heartbeat_tasks.values()]

    def list_scheduled_tasks(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self._scheduled_tasks.values()]

    # ---------- 待办 ----------
    def create_todo(self, title: str, description: str = "",
                    priority: Any = TaskPriority.NORMAL,
                    due_date: Any = None,
                    dependencies: Optional[List[str]] = None) -> Optional[TodoTask]:
        title = (title or "").strip()
        if not title:
            return None
        try:
            priority = TaskPriority(int(priority))
        except (TypeError, ValueError):
            priority = TaskPriority.NORMAL
        if isinstance(due_date, str) and due_date:
            try:
                due_date = datetime.fromisoformat(due_date)
            except ValueError:
                due_date = None
        todo = TodoTask(
            task_id=f"todo_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}",
            title=title,
            description=description or "",
            priority=priority,
            due_date=due_date if isinstance(due_date, datetime) else None,
            dependencies=list(dependencies or []),
        )
        self._todos[todo.task_id] = todo
        self._save_todos()
        return todo

    def add_todo(self, task: TodoTask) -> bool:
        if not isinstance(task, TodoTask) or not task.task_id:
            return False
        if task.task_id in self._todos:
            return False
        self._todos[task.task_id] = task
        self._save_todos()
        return True

    def get_todo(self, task_id: str) -> Optional[TodoTask]:
        return self._todos.get(task_id)

    def remove_todo(self, task_id: str) -> bool:
        existed = self._todos.pop(task_id, None) is not None
        if existed:
            self._save_todos()
        return existed

    def list_todos(self, status: Optional[TaskStatus] = None,
                   priority: Optional[TaskPriority] = None) -> List[TodoTask]:
        todos = list(self._todos.values())
        if status is not None:
            todos = [todo for todo in todos if todo.status == status]
        if priority is not None:
            todos = [todo for todo in todos if todo.priority == priority]
        todos.sort(key=lambda t: (t.status == TaskStatus.COMPLETED, -int(t.priority), t.created_at))
        return todos

    def complete_todo(self, task_id: str, result: Any = None) -> bool:
        task = self._todos.get(task_id)
        if not task:
            return False
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        if result is not None:
            task.context["result"] = result
        self._save_todos()
        return True

    # ---------- 统计 ----------
    def get_stats(self) -> Dict[str, Any]:
        todos = list(self._todos.values())
        return {
            "running": self._running,
            "heartbeat_count": len(self._heartbeat_tasks),
            "scheduled_count": len(self._scheduled_tasks),
            "todo_count": len(todos),
            "todo_pending": sum(1 for t in todos if t.status == TaskStatus.PENDING),
            "todo_completed": sum(1 for t in todos if t.status == TaskStatus.COMPLETED),
        }


_instance: Optional[TaskScheduler] = None


def get_task_scheduler(tasks_dir: str = "data/tasks") -> TaskScheduler:
    """获取全局单例（首次调用决定存储目录）。"""
    global _instance
    if _instance is None:
        _instance = TaskScheduler(tasks_dir=tasks_dir)
    return _instance


#: 语义化别名（新代码优先使用）
get_default_scheduler = get_task_scheduler