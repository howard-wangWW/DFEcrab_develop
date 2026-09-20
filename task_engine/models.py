"""数据模型定义"""

from enum import Enum
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def icon(self) -> str:
        icons = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "🔄",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️",
        }
        return icons.get(self, "❓")

    @property
    def color(self) -> str:
        colors = {
            TaskStatus.PENDING: "dim",
            TaskStatus.RUNNING: "blue",
            TaskStatus.COMPLETED: "green",
            TaskStatus.FAILED: "red",
            TaskStatus.SKIPPED: "yellow",
        }
        return colors.get(self, "white")


class Task(BaseModel):
    id: str = Field(description="任务唯一标识")
    name: str = Field(description="任务名称")
    description: str = Field(description="任务描述")
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def start(self) -> None:
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self, result: Any = None) -> None:
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = datetime.now()

    def fail(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = datetime.now()

    @property
    def duration(self) -> Optional[float]:
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()


class TaskPlan(BaseModel):
    goal: str = Field(description="总体目标")
    tasks: List[Task] = Field(description="子任务列表")
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def progress(self) -> float:
        if not self.tasks:
            return 0.0
        completed = sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)
        return completed / len(self.tasks)

    @property
    def status_summary(self) -> Dict[TaskStatus, int]:
        summary = {s: 0 for s in TaskStatus}
        for task in self.tasks:
            summary[task.status] += 1
        return summary
