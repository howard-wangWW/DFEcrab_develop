"""任务域 HTTP 接口层（自包含，不依赖 gateway 内部实现）

设计目标（对齐 knowledge / plan_router 的"独立模块"做法）：
- 任务相关路由**全部**收口在本文件，grpc_server.py 只做一次注册；
- 本模块只依赖 `src.task.*`，不 import gateway，避免循环依赖与巨石文件；
- 统一响应契约：`{"success": bool, "data": {...}}`，失败 `{"success": false, "error": "..."}`；
- 兼容旧字段：关键接口同时保留历史顶层字段（如 `tasks`/`count`/`progress`），前端无需改版。

注册方式（grpc_server.py）：
    from src.task.api_routes import get_task_routes
    for spec, handler in get_task_routes().items():
        method_str, path = spec.split(" ", 1)
        ... append RouteRule(...)

历史问题（本次修复）：
1. 路由在 `HTTPServer.__init__` 与 `grpc_server._register_routes` 里注册了两套，
   先注册者胜出 → grpc 里那套是死代码；且 api_routes 每请求 `TaskManager()` 新建实例，
   反复重读全部任务文件、内存态与网关不一致。
2. `/api/v2/tasks/{id}/convert` 调用了不存在的 `TaskManager.update_task`；
3. `/api/tasks/todos*`、`/api/tasks/stats` 调用了 TaskManager 上不存在的待办方法；
4. DELETE 任务时误调 stub 调度器方法 → 删除成功却返回 400。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, Optional

from src.task.agent_group import AgentGroup
from src.task.audit import AuditLogger
from src.task.models import TaskProgress, TaskStatus, TaskType
from src.task.periodic_scheduler import get_periodic_scheduler, preview_schedule
from src.task.scheduler import TaskPriority, get_task_scheduler
from src.task.task_manager import get_task_manager

logger = logging.getLogger(__name__)

#: 任务存储根目录（与网关保持一致；可用环境变量覆盖）
TASKS_DIR = os.environ.get("DFECRAB_TASKS_DIR", "data/tasks")


# ──────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────

async def _body(request) -> Dict[str, Any]:
    """安全读取请求体（兼容无 body / 非法 JSON / 非 dict）"""
    try:
        data = await request.json() if getattr(request, "body", None) else {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _qp(request, key: str, default: Any = None) -> Any:
    try:
        return request.query_params.get(key, default)
    except Exception:
        return default


def _qint(request, key: str, default: int) -> int:
    try:
        return int(_qp(request, key, default))
    except (TypeError, ValueError):
        return default


def _path_param(request, task_id: Optional[str]) -> Optional[str]:
    if task_id:
        return task_id
    try:
        return request.path_params.get("task_id")
    except Exception:
        return None


def _ok(data: Any = None, **legacy) -> Dict[str, Any]:
    """成功响应；legacy 字段平铺到顶层，兼容历史契约。"""
    resp: Dict[str, Any] = {"success": True}
    if data is not None:
        resp["data"] = data
    resp.update(legacy)
    return resp


def _err(message: str, **legacy) -> Dict[str, Any]:
    resp: Dict[str, Any] = {"success": False, "error": message}
    resp.update(legacy)
    return resp


def _parse_task_type(raw) -> Optional[TaskType]:
    if not raw:
        return None
    try:
        return TaskType(raw)
    except ValueError:
        return None


def _parse_task_status(raw) -> Optional[TaskStatus]:
    if not raw:
        return None
    try:
        return TaskStatus(raw)
    except ValueError:
        return None


def _audit_logger(task_id: str) -> AuditLogger:
    return AuditLogger(task_id, storage_dir=f"{TASKS_DIR}/audit")


# ──────────────────────────────────────────────────────────────
# V2 任务 CRUD
# ──────────────────────────────────────────────────────────────

async def handle_create_task(request) -> Dict[str, Any]:
    """POST /api/v2/tasks — 创建任务

    body: {topic|title*, task_type?, description?, supervisor_agent_id?,
           agent_group_config*, schedule?, require_confirmation?, collaboration_mode?,
           execution_mode?, selected_agents?}

    schedule（task_type=periodic/scheduled 时）：
        {"cron": "0 9 * * 1", "timezone": "Asia/Shanghai"}   或
        {"interval_seconds": 3600, "timezone": "Asia/Shanghai"}
    非法 schedule 直接返回 success=false（错误信息可展示给用户），
    合法时响应带回 schedule_preview.next_runs（前端可直接显示"下次执行时间"）。
    """
    try:
        body = await _body(request)
        topic = (body.get("topic") or body.get("title") or "").strip()
        if not topic:
            return _err("topic (或 title) is required")

        agent_group_config = body.get("agent_group_config") or {}
        if not agent_group_config.get("members"):
            return _err("agent_group_config.members is required")

        task_type = _parse_task_type(body.get("task_type") or "temporary")
        if task_type is None:
            return _err(f"非法 task_type: {body.get('task_type')}（可选 {[t.value for t in TaskType]}）")

        manager = get_task_manager(TASKS_DIR)
        result = manager.create_task(
            topic=topic,
            task_type=task_type,
            description=body.get("description", ""),
            supervisor_agent_id=body.get("supervisor_agent_id", "supervisor_01"),
            agent_group_config=agent_group_config,
            schedule=body.get("schedule"),
            execution_mode=body.get("execution_mode", "auto_select"),
            require_confirmation=bool(body.get("require_confirmation", True)),
            collaboration_mode=body.get("collaboration_mode"),
            selected_agents=body.get("selected_agents"),
            retry_config=body.get("retry_config"),
            notification_config=body.get("notification_config"),
            trigger_config=body.get("trigger_config"),
            parent_task_id=body.get("parent_task_id", ""),
        )
        task = result["task"]
        agent_group = AgentGroup(task_id=task.task_id, task_type=task_type, config=agent_group_config)

        return _ok({
            "task_id": task.task_id,
            "topic": task.topic,
            "title": task.title,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "supervisor_session_id": task.supervisor_session_id,
            "supervisor_agent_id": task.supervisor_agent_id,
            "agent_group": agent_group.to_dict(),
            "manager_recommendation": result.get("manager_recommendation"),
            "available_agents": result.get("available_agents", []),
            "approval_url": result.get("approval_url"),
            "schedule": result.get("schedule"),
            "schedule_preview": result.get("schedule_preview"),
            "task": task.to_dict(),
        })
    except Exception as e:
        logger.error(f"[TaskAPI] 创建任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_list_tasks(request) -> Dict[str, Any]:
    """GET /api/v2/tasks?task_type=&status=&limit=&offset="""
    try:
        task_type = _parse_task_type(_qp(request, "task_type"))
        status = _parse_task_status(_qp(request, "status"))
        limit = _qint(request, "limit", 100)
        offset = _qint(request, "offset", 0)

        result = get_task_manager(TASKS_DIR).list_tasks(
            task_type=task_type, status=status, limit=limit, offset=offset
        )
        tasks = [
            {
                "task_id": t.task_id,
                "topic": t.topic,
                "title": t.title,
                "task_type": t.task_type.value if hasattr(t.task_type, "value") else str(t.task_type),
                "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                "progress": t.progress,
                "created_at": t.created_at.isoformat() if hasattr(t.created_at, "isoformat") else str(t.created_at),
            }
            for t in result.get("tasks", [])
        ]
        payload = {
            "tasks": tasks,
            "count": result.get("count", 0),
            "limit": result.get("limit", limit),
            "offset": result.get("offset", offset),
            "available_agents": result.get("available_agents", []),
        }
        # 兼容旧顶层字段
        return _ok(payload, tasks=tasks, count=payload["count"])
    except Exception as e:
        logger.error(f"[TaskAPI] 列出任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_get_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """GET /api/v2/tasks/{task_id} — 任务详情（含 progress 快照）"""
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        task = get_task_manager(TASKS_DIR).get_task(task_id)
        if not task:
            return _err(f"任务不存在: {task_id}")
        data = task.to_dict()
        data["progress"] = TaskProgress.from_task(task).to_dict()
        return _ok(data)
    except Exception as e:
        logger.error(f"[TaskAPI] 获取任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_delete_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """DELETE /api/v2/tasks/{task_id} — 删除任务（含定时作业与审计清理）"""
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        manager = get_task_manager(TASKS_DIR)
        if not manager.get_task(task_id):
            return _err(f"任务不存在: {task_id}")
        if not manager.delete_task(task_id):
            return _err(f"任务删除失败: {task_id}")
        return _ok({"task_id": task_id}, message=f"任务 {task_id} 已删除")
    except Exception as e:
        logger.error(f"[TaskAPI] 删除任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_convert_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """POST /api/v2/tasks/{task_id}/convert — 转化任务类型

    body: {target_type: "periodic"|"temporary"|..., schedule?: {...}}
    """
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        body = await _body(request)
        target_type = _parse_task_type(body.get("target_type") or body.get("task_type"))
        if target_type is None:
            return _err("target_type 必填且需为合法任务类型")
        manager = get_task_manager(TASKS_DIR)
        if not manager.get_task(task_id):
            return _err(f"任务不存在: {task_id}")

        new_task = manager.convert_task(task_id, target_type, schedule=body.get("schedule"))
        if new_task is None:
            return _err(f"任务转化失败: {task_id}")
        return _ok({
            "original_task_id": task_id,
            "new_task_id": new_task.task_id,
            "new_task_type": new_task.task_type.value,
            "schedule": new_task.schedule,
            "schedule_status": manager.get_schedule_status(new_task.task_id),
            "task": new_task.to_dict(),
        })
    except ValueError as e:
        # schedule 非法：返回可读原因，原任务不被转化
        return _err(str(e))
    except Exception as e:
        logger.error(f"[TaskAPI] 转化任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_approve_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """POST /api/v2/tasks/{task_id}/approve — 确认/拒绝任务

    body: {approved: bool, approved_by?: str,
           modified_config?: {agents?: [...], collaboration_mode?: str,
                              schedule?: {cron|interval_seconds, timezone}}}

    `modified_config.schedule` 支持"在确认弹窗里由用户直接选时间"：
    非法时间规则会返回 success=false（任务保持 DRAFT），合法则返回排期结果
    （schedule_registered / next_run），前端可直接展示"下次执行时间"。
    """
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        body = await _body(request)
        approved = body.get("approved")
        if not isinstance(approved, bool):
            return _err("body 需含布尔字段 approved")

        manager = get_task_manager(TASKS_DIR)
        task = manager.approve_task(
            task_id=task_id,
            approved=approved,
            approved_by=body.get("approved_by", "system"),
            modified_config=body.get("modified_config"),
        )
        if not task:
            return _err(f"任务不存在: {task_id}")

        schedule_status = manager.get_schedule_status(task_id)
        payload = {
            "task_id": task_id,
            "status": task.status.value,
            "message": "任务已确认" if approved else "任务已拒绝",
            "schedule_status": schedule_status,
        }
        # 周期性任务确认后若未排期，明确告知原因（避免"已确认却没排期"的静默状态）
        if approved and schedule_status.get("is_scheduled") and not schedule_status.get("registered"):
            payload["message"] = f"任务已确认，但未排期：{schedule_status.get('error') or '缺少时间规则'}"
        return _ok(payload)
    except ValueError as e:
        # schedule 非法等业务校验错误：返回可读原因，任务状态不变
        return _err(str(e))
    except Exception as e:
        logger.error(f"[TaskAPI] 审批任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_pause_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """POST /api/v2/tasks/{task_id}/pause — 暂停定时/周期任务"""
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        manager = get_task_manager(TASKS_DIR)
        if not manager.get_task(task_id):
            return _err(f"任务不存在: {task_id}")

        scheduler = get_periodic_scheduler(TASKS_DIR)
        if not scheduler.get_job(task_id):
            return _err(f"任务不在调度器中（可能未确认或非定时任务）: {task_id}")

        if not scheduler.pause_job(task_id):
            return _err(f"暂停失败: {task_id}")
        task = manager.update_task_status(task_id, TaskStatus.PAUSED)
        return _ok({
            "task_id": task_id,
            "status": task.status.value if task else TaskStatus.PAUSED.value,
            "next_run": None,
        }, message="任务已暂停")
    except Exception as e:
        logger.error(f"[TaskAPI] 暂停任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_resume_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """POST /api/v2/tasks/{task_id}/resume — 恢复定时/周期任务"""
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        manager = get_task_manager(TASKS_DIR)
        if not manager.get_task(task_id):
            return _err(f"任务不存在: {task_id}")

        scheduler = get_periodic_scheduler(TASKS_DIR)
        if not scheduler.get_job(task_id):
            return _err(f"任务不在调度器中（可能未确认或非定时任务）: {task_id}")

        if not scheduler.resume_job(task_id):
            return _err(f"恢复失败: {task_id}")
        task = manager.update_task_status(task_id, TaskStatus.PENDING)
        job = scheduler.get_job(task_id)
        return _ok({
            "task_id": task_id,
            "status": task.status.value if task else TaskStatus.PENDING.value,
            "next_run": job.next_run if job else None,
        }, message="任务已恢复")
    except Exception as e:
        logger.error(f"[TaskAPI] 恢复任务失败: {e}", exc_info=True)
        return _err(str(e))


async def _run_task(task_id: str, user_input: str = "", background: bool = False) -> Dict[str, Any]:
    """共用执行逻辑：background=True 时后台执行并立即返回。"""
    from src.task.supervisor import SupervisorSession

    manager = get_task_manager(TASKS_DIR)
    task = manager.get_task(task_id)
    if not task:
        return _err(f"任务不存在: {task_id}")
    if task.status == TaskStatus.DRAFT:
        return _err("任务尚未确认（draft），请先调用 /approve")
    if task.status == TaskStatus.RUNNING:
        return _err(f"任务正在执行中: {task_id}")

    supervisor = SupervisorSession(task_id, manager)
    if background:
        asyncio.create_task(supervisor.coordinate_task(user_input))
        manager.update_task_status(task_id, TaskStatus.RUNNING)
        return _ok({"task_id": task_id, "status": TaskStatus.RUNNING.value, "background": True})

    result = await supervisor.coordinate_task(user_input)
    return _ok({
        "task_id": task_id,
        "status": result.get("status"),
        "progress": result.get("progress"),
    }) if result.get("success") else _err(result.get("error", "任务执行失败"), data=result)


async def handle_trigger_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """POST /api/v2/tasks/{task_id}/trigger — 手动触发执行

    body: {user_input?: str, background?: bool}
    """
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        body = await _body(request)
        return await _run_task(
            task_id,
            user_input=body.get("user_input", ""),
            background=bool(body.get("background", False)),
        )
    except Exception as e:
        logger.error(f"[TaskAPI] 触发任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_execute_task(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """POST /api/v2/tasks/{task_id}/execute — 执行任务（与 trigger 同引擎）

    body: {user_input?: str, background?: bool}
    """
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        body = await _body(request)
        return await _run_task(
            task_id,
            user_input=body.get("user_input", ""),
            background=bool(body.get("background", False)),
        )
    except Exception as e:
        logger.error(f"[TaskAPI] 执行任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_preview(request) -> Dict[str, Any]:
    """POST /api/v2/tasks/preview — 预览 Manager 推荐（不创建任务）

    body: {description*: str, mode?: str}
    """
    try:
        body = await _body(request)
        description = (body.get("description") or "").strip()
        if not description:
            return _err("description 为必填项")
        recommendation = get_task_manager(TASKS_DIR).preview_recommendation(
            description, body.get("mode", "auto_select")
        )
        return _ok(recommendation)
    except Exception as e:
        logger.error(f"[TaskAPI] 预览推荐失败: {e}", exc_info=True)
        return _err(str(e))


# ──────────────────────────────────────────────────────────────
# 进度 / 审计 / 看板
# ──────────────────────────────────────────────────────────────

async def handle_get_progress(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """GET /api/v2/tasks/{task_id}/progress — 任务进度"""
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        manager = get_task_manager(TASKS_DIR)
        task = manager.get_task(task_id)
        if not task:
            return _err(f"任务不存在: {task_id}")

        base = manager.get_task_progress(task_id) or {}
        base.update(TaskProgress.from_task(task).to_dict())
        return _ok(base)
    except Exception as e:
        logger.error(f"[TaskAPI] 获取进度失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_get_audit(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """GET /api/v2/tasks/{task_id}/audit?agent=&action=&limit= — 任务审计日志"""
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        if not get_task_manager(TASKS_DIR).get_task(task_id):
            return _err(f"任务不存在: {task_id}")

        logs = _audit_logger(task_id).get_logs(
            agent=_qp(request, "agent"),
            action=_qp(request, "action"),
            limit=_qint(request, "limit", 100),
        )
        entries = [entry.to_dict() for entry in logs]
        payload = {"logs": entries, "count": len(entries), "task_id": task_id}
        # 兼容旧顶层字段 audits
        return _ok(payload, audits=entries, count=len(entries))
    except Exception as e:
        logger.error(f"[TaskAPI] 获取审计失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_get_dashboard(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """GET /api/v2/tasks/{task_id}/dashboard — 任务看板"""
    try:
        from src.task.supervisor import SupervisorSession

        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        manager = get_task_manager(TASKS_DIR)
        if not manager.get_task(task_id):
            return _err(f"任务不存在: {task_id}")
        return _ok(SupervisorSession(task_id, manager).get_dashboard_data())
    except Exception as e:
        logger.error(f"[TaskAPI] 获取看板失败: {e}", exc_info=True)
        return _err(str(e))


# ──────────────────────────────────────────────────────────────
# 轻量作业：心跳 / 定时 / 待办 / 统计
# ──────────────────────────────────────────────────────────────

async def handle_list_heartbeats(request) -> Dict[str, Any]:
    """GET /api/tasks/heartbeats — 心跳任务状态"""
    try:
        scheduler = get_task_scheduler(TASKS_DIR)
        payload = {
            "stats": scheduler.get_stats(),
            "heartbeats": scheduler.list_heartbeats(),
        }
        return _ok(payload, stats=payload["stats"])
    except Exception as e:
        logger.error(f"[TaskAPI] 查询心跳失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_list_scheduled(request) -> Dict[str, Any]:
    """GET /api/tasks/scheduled — 定时/周期任务列表"""
    try:
        tasks = get_periodic_scheduler(TASKS_DIR).list_tasks()
        return _ok({"count": len(tasks), "tasks": tasks}, count=len(tasks), tasks=tasks)
    except Exception as e:
        logger.error(f"[TaskAPI] 查询定时任务失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_list_todos(request) -> Dict[str, Any]:
    """GET /api/tasks/todos?status=&priority= — 待办列表"""
    try:
        from src.task.scheduler import TaskStatus as SchedulerStatus

        scheduler = get_task_scheduler(TASKS_DIR)
        status = None
        raw_status = _qp(request, "status")
        if raw_status:
            try:
                status = SchedulerStatus(raw_status)
            except ValueError:
                status = None
        priority = None
        raw_priority = _qp(request, "priority")
        if raw_priority:
            try:
                priority = TaskPriority(int(raw_priority))
            except (TypeError, ValueError):
                priority = None

        todos = [t.to_dict() for t in scheduler.list_todos(status=status, priority=priority)]
        return _ok({"count": len(todos), "todos": todos}, count=len(todos), todos=todos)
    except Exception as e:
        logger.error(f"[TaskAPI] 查询待办失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_add_todo(request) -> Dict[str, Any]:
    """POST /api/tasks/todos — 新增待办

    body: {title*, description?, priority? (1-4 或 low/normal/high/critical),
           due_date?: ISO 字符串, dependencies?: []}
    """
    try:
        body = await _body(request)
        title = (body.get("title") or "").strip()
        if not title:
            return _err("title 为必填项")

        priority = body.get("priority", TaskPriority.NORMAL)
        if isinstance(priority, str):
            name = priority.strip().upper()
            priority = TaskPriority[name] if name in TaskPriority.__members__ else TaskPriority.NORMAL

        todo = get_task_scheduler(TASKS_DIR).create_todo(
            title=title,
            description=body.get("description", ""),
            priority=priority,
            due_date=body.get("due_date"),
            dependencies=body.get("dependencies"),
        )
        if not todo:
            return _err("创建待办失败")
        return _ok({"todo": todo.to_dict()}, task_id=todo.task_id)
    except Exception as e:
        logger.error(f"[TaskAPI] 新增待办失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_complete_todo(request, task_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """POST /api/tasks/todos/{task_id}/complete — 完成待办"""
    try:
        task_id = _path_param(request, task_id) or kwargs.get("task_id")
        scheduler = get_task_scheduler(TASKS_DIR)
        if not scheduler.get_todo(task_id):
            return _err(f"待办不存在: {task_id}")
        body = await _body(request)
        if not scheduler.complete_todo(task_id, body.get("result")):
            return _err(f"完成待办失败: {task_id}")
        todo = scheduler.get_todo(task_id)
        return _ok({"todo": todo.to_dict() if todo else None})
    except Exception as e:
        logger.error(f"[TaskAPI] 完成待办失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_preview_schedule(request) -> Dict[str, Any]:
    """GET /api/v2/tasks/schedule/preview — 校验时间规则并预览未来执行时间

    前端"时间选择器 → cron"实现后先调这里：合法则直接拿到 next_runs 展示，
    不合法则把 error 文案提示给用户（不用自己实现 cron 解析）。

    query（二选一）：
        cron=0 9 * * 1          5 字段：分 时 日 月 周
        interval_seconds=3600   固定间隔（秒）
    可选：
        timezone=Asia/Shanghai（默认）
        count=5（1~20，默认 5）

    响应 data:
        {ok, kind: "cron"|"interval"|null, timezone, error, warning,
         next_runs: ["2026-09-28T09:00:00+08:00", ...]}
    """
    try:
        schedule: Dict[str, Any] = {}
        cron = (_qp(request, "cron") or "").strip()
        interval = (_qp(request, "interval_seconds") or "").strip()
        if cron:
            schedule["cron"] = cron
        if interval:
            schedule["interval_seconds"] = interval
        tz = _qp(request, "timezone")
        if tz:
            schedule["timezone"] = tz
        if not schedule:
            return _err("需提供 cron 或 interval_seconds 之一")

        count = _qint(request, "count", 5)
        result = preview_schedule(schedule, count=count)
        # 校验失败仍返回 data（ok=false + error 文案），HTTP 层面保持成功，前端直接取字段
        return _ok(result, **{k: v for k, v in result.items() if k != "next_runs"})
    except Exception as e:
        logger.error(f"[TaskAPI] 预览调度失败: {e}", exc_info=True)
        return _err(str(e))


async def handle_get_stats(request) -> Dict[str, Any]:
    """GET /api/tasks/stats — 任务统计（任务 + 调度 + 待办）"""
    try:
        stats = {
            "tasks": get_task_manager(TASKS_DIR).get_stats(),
            "scheduled": get_periodic_scheduler(TASKS_DIR).get_stats(),
            "todos": get_task_scheduler(TASKS_DIR).get_stats(),
        }
        return _ok(stats, stats=stats)
    except Exception as e:
        logger.error(f"[TaskAPI] 获取统计失败: {e}", exc_info=True)
        return _err(str(e))


# ──────────────────────────────────────────────────────────────
# 路由表（注册顺序：静态路径在前，参数化路径在后）
# ──────────────────────────────────────────────────────────────

def get_task_routes() -> Dict[str, Callable]:
    """返回任务路由映射表：{"METHOD /path": handler}"""
    return {
        # V2 任务
        "POST /api/v2/tasks/preview": handle_preview,
        "GET /api/v2/tasks/schedule/preview": handle_preview_schedule,
        "POST /api/v2/tasks": handle_create_task,
        "GET /api/v2/tasks": handle_list_tasks,
        "GET /api/v2/tasks/{task_id}": handle_get_task,
        "DELETE /api/v2/tasks/{task_id}": handle_delete_task,
        "POST /api/v2/tasks/{task_id}/convert": handle_convert_task,
        "POST /api/v2/tasks/{task_id}/approve": handle_approve_task,
        "POST /api/v2/tasks/{task_id}/pause": handle_pause_task,
        "POST /api/v2/tasks/{task_id}/resume": handle_resume_task,
        "POST /api/v2/tasks/{task_id}/trigger": handle_trigger_task,
        "POST /api/v2/tasks/{task_id}/execute": handle_execute_task,
        "GET /api/v2/tasks/{task_id}/progress": handle_get_progress,
        "GET /api/v2/tasks/{task_id}/audit": handle_get_audit,
        "GET /api/v2/tasks/{task_id}/dashboard": handle_get_dashboard,
        # 轻量作业
        "GET /api/tasks/heartbeats": handle_list_heartbeats,
        "GET /api/tasks/scheduled": handle_list_scheduled,
        "GET /api/tasks/stats": handle_get_stats,
        "GET /api/tasks/todos": handle_list_todos,
        "POST /api/tasks/todos": handle_add_todo,
        "POST /api/tasks/todos/{task_id}/complete": handle_complete_todo,
    }


__all__ = ["get_task_routes", "TASKS_DIR"]