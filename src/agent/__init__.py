"""
智能体层 - agent 域

管理 Agent 核心逻辑：ReAct 循环、LLM 适配、多智能体协作、任务规划。
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.loop import ReActLoop
    from src.agent.planner import TaskPlanner, Plan

__all__ = [
    'ReActLoop', 'run_react_loop',
    'TaskPlanner', 'Plan', 'get_task_planner',
]


def __getattr__(name: str):
    if name in {"ReActLoop", "run_react_loop"}:
        from src.agent.loop import ReActLoop, run_react_loop

        return {
            "ReActLoop": ReActLoop,
            "run_react_loop": run_react_loop,
        }[name]
    if name in {"TaskPlanner", "Plan", "get_task_planner"}:
        from src.agent.planner import TaskPlanner, Plan, get_task_planner

        return {
            "TaskPlanner": TaskPlanner,
            "Plan": Plan,
            "get_task_planner": get_task_planner,
        }[name]
    raise AttributeError(f"module 'src.agent' has no attribute {name!r}")
