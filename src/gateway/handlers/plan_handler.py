"""
规划系统处理器

处理计划相关的 HTTP 请求
"""

from typing import Dict, Any, Optional
from src.agent.planner import get_task_planner


class PlanHandler:
    """规划系统处理器"""

    @staticmethod
    async def get_current(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取当前计划"""
        try:
            planner = get_task_planner()
            progress = planner.get_progress()

            if not progress.get("has_plan"):
                return {"success": True, "data": {"has_plan": False}}

            summary = planner.format_plan_summary()

            return {
                "success": True,
                "data": {
                    "has_plan": True,
                    "progress": progress,
                    "summary": summary
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_list(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取计划列表"""
        try:
            planner = get_task_planner()
            plans = planner.get_all_plans()

            return {
                "success": True,
                "data": {
                    "plans": plans
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def next_step(request: Any) -> Dict[str, Any]:
        """执行下一步"""
        try:
            body = await request.json()
            result = body.get("result", "")

            planner = get_task_planner()
            current_step = planner.get_current_step()

            if not current_step:
                return {"success": False, "error": "没有正在执行的计划"}

            # complete_step 接受 step_index，传入当前步骤的 index
            planner.complete_step(current_step.index)

            next_step = planner.get_current_step()
            if next_step:
                return {
                    "success": True,
                    "data": {
                        "message": "步骤完成，已进入下一步",
                        "next_step": next_step.to_dict()
                    }
                }
            else:
                return {
                    "success": True,
                    "data": {
                        "message": "所有步骤已完成",
                        "completed": True
                    }
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def skip(request: Optional[Any] = None) -> Dict[str, Any]:
        """跳过当前步骤"""
        try:
            planner = get_task_planner()
            current_step = planner.get_current_step()

            if not current_step:
                return {"success": False, "error": "没有正在执行的计划"}

            planner.skip_step(current_step.index)

            next_step = planner.get_current_step()
            if next_step:
                return {
                    "success": True,
                    "data": {
                        "message": "已跳过当前步骤",
                        "next_step": next_step.to_dict()
                    }
                }
            else:
                return {
                    "success": True,
                    "data": {
                        "message": "所有步骤已完成",
                        "completed": True
                    }
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def cancel(request: Optional[Any] = None) -> Dict[str, Any]:
        """取消计划"""
        try:
            planner = get_task_planner()
            planner.cancel_plan()

            return {
                "success": True,
                "data": {
                    "message": "计划已取消"
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
