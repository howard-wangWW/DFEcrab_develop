"""
plan_router.py — 独立 plan 路由层

为 grpc_server.py 提供可注册的 plan 相关 HTTP 路由处理函数，
不污染 grpc_server.py 主文件。

路由表：
  GET  /api/plan/progress  → 获取当前计划进度
  GET  /api/plan/current   → 获取当前计划详情
  POST /api/plan/cancel    → 取消当前计划
  GET  /api/plan/steps     → 获取所有步骤及其结果
  POST /api/plan/step/execute → 手动执行某一步（留口子给前端手动控制）
"""

import logging
from typing import Any, Dict, Optional

from src.agent.planner import get_task_planner

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 路由处理函数（每个函数签名：async fn(request) -> dict）
# 与 grpc_server.py 的 _handle_xxx 风格保持一致
# ──────────────────────────────────────────────────────────────

async def handle_plan_progress(request) -> Dict[str, Any]:
    """获取当前计划进度

    GET /api/plan/progress

    Response:
        {
            "success": true,
            "data": {
                "has_plan": true,
                "total": 3,
                "completed": 1,
                "percent": 33,
                "plan_id": "plan_abc123",
                "plan_status": "running"
            }
        }
    """
    try:
        planner = get_task_planner()
        progress = planner.get_progress()

        plan = planner.get_current_plan()
        if plan:
            progress["plan_id"] = plan.id
            progress["plan_status"] = plan.status
            # 附上每个步骤的简要状态
            progress["steps"] = [
                {"index": s.index, "description": s.description, "status": s.status}
                for s in plan.steps
            ]

        return {
            "success": True,
            "data": progress,
        }
    except Exception as e:
        logger.error(f"[PlanRouter] 获取进度失败: {e}")
        return {"success": False, "error": str(e)}


async def handle_plan_current(request) -> Dict[str, Any]:
    """获取当前计划详情

    GET /api/plan/current

    Response:
        {
            "success": true,
            "data": {
                "plan_id": "plan_abc123",
                "status": "running",
                "total": 3,
                "completed": 1,
                "steps": [...]
            }
        }
    """
    try:
        planner = get_task_planner()
        plan = planner.get_current_plan()

        if not plan:
            return {
                "success": True,
                "data": None,
                "message": "当前没有计划",
            }

        return {
            "success": True,
            "data": {
                "plan_id": plan.id,
                "status": plan.status,
                "total": plan.total,
                "completed": plan.completed,
                "percent": plan.percent,
                "steps": [s.to_dict() for s in plan.steps],
            },
        }
    except Exception as e:
        logger.error(f"[PlanRouter] 获取当前计划失败: {e}")
        return {"success": False, "error": str(e)}


async def handle_plan_cancel(request) -> Dict[str, Any]:
    """取消当前计划

    POST /api/plan/cancel

    Request Body: {}（可选，当前只支持取消最新计划）

    Response:
        {"success": true, "message": "计划已取消"}
    """
    try:
        planner = get_task_planner()
        plan = planner.get_current_plan()

        if not plan:
            return {
                "success": False,
                "error": "当前没有计划",
            }

        plan_id = plan.id
        planner.cancel_plan()
        planner.clear_step_results()

        logger.info(f"[PlanRouter] 计划已取消: {plan_id}")
        return {
            "success": True,
            "message": f"计划 {plan_id} 已取消",
            "data": {"plan_id": plan_id},
        }
    except Exception as e:
        logger.error(f"[PlanRouter] 取消计划失败: {e}")
        return {"success": False, "error": str(e)}


async def handle_plan_steps(request) -> Dict[str, Any]:
    """获取所有步骤及其结果

    GET /api/plan/steps

    Response:
        {
            "success": true,
            "data": {
                "plan_id": "plan_abc123",
                "steps": [
                    {"index": 1, "description": "...", "status": "done", "result": "..."},
                    ...
                ]
            }
        }
    """
    try:
        planner = get_task_planner()
        plan = planner.get_current_plan()

        if not plan:
            return {"success": False, "error": "当前没有计划"}

        all_results = planner.get_all_step_results()
        steps_detail = []
        for s in plan.steps:
            detail = s.to_dict()
            detail["result"] = all_results.get(s.index)
            steps_detail.append(detail)

        return {
            "success": True,
            "data": {
                "plan_id": plan.id,
                "plan_status": plan.status,
                "total": plan.total,
                "completed": plan.completed,
                "steps": steps_detail,
            },
        }
    except Exception as e:
        logger.error(f"[PlanRouter] 获取步骤失败: {e}")
        return {"success": False, "error": str(e)}


async def handle_plan_step_execute(request) -> Dict[str, Any]:
    """手动执行某一步（预留接口，阶段3 MVP 中前端可通过 plan_handler 控制）

    POST /api/plan/step/execute

    Request Body:
        {"step_index": 1}

    Response:
        {"success": true, "message": "步骤 1 已触发执行"}
    """
    try:
        body = await request.json()
        step_index = body.get("step_index")

        if step_index is None:
            return {"success": False, "error": "缺少 step_index 参数"}

        planner = get_task_planner()
        plan = planner.get_current_plan()

        if not plan:
            return {"success": False, "error": "当前没有计划"}

        # 查找步骤
        target_step = None
        for s in plan.steps:
            if s.index == step_index:
                target_step = s
                break

        if not target_step:
            return {"success": False, "error": f"步骤 {step_index} 不存在"}

        if target_step.status not in ("pending", "failed"):
            return {
                "success": False,
                "error": f"步骤 {step_index} 状态为 {target_step.status}，无法执行",
            }

        # 标记为 running（实际执行由 _react_chat_generator 在 plan 模式中完成）
        planner.start_step(step_index)

        return {
            "success": True,
            "message": f"步骤 {step_index} 已触发执行",
            "data": {
                "step_index": step_index,
                "step_desc": target_step.description,
                "status": "running",
            },
        }
    except Exception as e:
        logger.error(f"[PlanRouter] 手动执行步骤失败: {e}")
        return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────
# 路由注册表（给 grpc_server.py 注册用）
# ──────────────────────────────────────────────────────────────

def get_plan_routes() -> Dict[str, callable]:
    """返回 plan 路由映射表

    格式: { "METHOD /path": handler_function }
    与 grpc_server.py 的 _router.register() 兼容

    Usage:
        from src.gateway.plan_router import get_plan_routes
        for route, handler in get_plan_routes().items():
            self._router.register(route, handler)
    """
    return {
        "GET /api/plan/progress": handle_plan_progress,
        "GET /api/plan/current": handle_plan_current,
        "POST /api/plan/cancel": handle_plan_cancel,
        "GET /api/plan/steps": handle_plan_steps,
        "POST /api/plan/step/execute": handle_plan_step_execute,
    }
