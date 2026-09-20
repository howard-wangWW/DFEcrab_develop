"""Task 域模块（任务能力自包含，对齐 knowledge 域的组织方式）

职责划分：
    models.py              数据模型与枚举（Task/TaskStep/TaskProgress/AuditLogEntry）
    task_manager.py        任务 CRUD 与持久化（data/tasks/*.json + task_index.json）
    audit.py               任务级审计日志（data/tasks/audit/<task_id>.json）
    scheduler.py           轻量调度器（待办/心跳，持久化 todos.json）
    periodic_scheduler.py  周期/定时调度（cron/interval，重启自动恢复）
    supervisor.py          执行期进度跟踪与看板聚合
    executor.py            执行引擎（顺序/并行/混合）
    api_routes.py          HTTP 接口层（get_task_routes()，由网关统一注册）

网关（src/gateway/grpc_server.py）只做一件事：
    _register_task_routes() → for spec, handler in get_task_routes().items(): 注册
任务业务逻辑不再散落在网关里。
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.task.task_manager import TaskManager
    from src.task.models import (
        Task,
        TaskStatus,
        TaskType,
        TaskStep,
        CollaborationMode,
        TaskProgress,
        AuditLogEntry,
    )
    from src.task.periodic_scheduler import PeriodicScheduler
    from src.task.scheduler import HeartbeatTask, ScheduledTask, TaskPriority, TodoTask
    from src.task.supervisor import SupervisorSession
    from src.task.manager_agent import ManagerAgent

__all__ = [
    'Task',
    'TaskStatus',
    'TaskType',
    'TaskStep',
    'CollaborationMode',
    'TaskProgress',
    'AuditLogEntry',
    'TaskManager',
    'get_task_manager',
    'PeriodicScheduler',
    'get_periodic_scheduler',
    'HeartbeatTask',
    'ScheduledTask',
    'TaskPriority',
    'TodoTask',
    'get_task_scheduler',
    'SupervisorSession',
    'get_task_supervisor',
    'create_supervisor',
    'ManagerAgent',
    'TaskExecutor',
    'get_task_routes',
]


def __getattr__(name: str):
    if name in {'Task', 'TaskStatus', 'TaskType', 'TaskStep', 'CollaborationMode',
                'TaskProgress', 'AuditLogEntry'}:
        from src.task import models
        return {
            'Task': models.Task,
            'TaskStatus': models.TaskStatus,
            'TaskType': models.TaskType,
            'TaskStep': models.TaskStep,
            'CollaborationMode': models.CollaborationMode,
            'TaskProgress': models.TaskProgress,
            'AuditLogEntry': models.AuditLogEntry,
        }[name]
    if name in {'TaskManager', 'get_task_manager'}:
        from src.task.task_manager import TaskManager, get_task_manager
        return {'TaskManager': TaskManager, 'get_task_manager': get_task_manager}[name]
    if name in {'PeriodicScheduler', 'get_periodic_scheduler'}:
        from src.task.periodic_scheduler import PeriodicScheduler, get_periodic_scheduler
        return {
            'PeriodicScheduler': PeriodicScheduler,
            'get_periodic_scheduler': get_periodic_scheduler,
        }[name]
    if name in {'HeartbeatTask', 'ScheduledTask', 'TaskPriority', 'TodoTask', 'get_task_scheduler'}:
        from src.task.scheduler import (
            HeartbeatTask,
            ScheduledTask,
            TaskPriority,
            TodoTask,
            get_task_scheduler,
        )
        return {
            'HeartbeatTask': HeartbeatTask,
            'ScheduledTask': ScheduledTask,
            'TaskPriority': TaskPriority,
            'TodoTask': TodoTask,
            'get_task_scheduler': get_task_scheduler,
        }[name]
    if name in {'SupervisorSession', 'get_task_supervisor', 'create_supervisor'}:
        from src.task.supervisor import SupervisorSession, get_task_supervisor, create_supervisor
        return {
            'SupervisorSession': SupervisorSession,
            'get_task_supervisor': get_task_supervisor,
            'create_supervisor': create_supervisor,
        }[name]
    if name == 'ManagerAgent':
        from src.task.manager_agent import ManagerAgent
        return ManagerAgent
    if name == 'TaskExecutor':
        from src.task.executor import TaskExecutor
        return TaskExecutor
    if name == 'get_task_routes':
        from src.task.api_routes import get_task_routes
        return get_task_routes
    raise AttributeError(f"module 'src.task' has no attribute {name!r}")
