"""
TaskPlanner - P1-7 MVP

让 LLM 判断任务是否需要拆分为多个步骤。
如需拆分，输出 JSON steps，然后逐个步骤跑 ReAct 子任务。
"""

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


class PlanStep:
    """单个计划步骤"""
    def __init__(self, description: str, suggested_tool: str = "", index: int = 0):
        self.index = index
        self.description = description
        self.suggested_tool = suggested_tool
        self.status = "pending"  # pending | running | done | skipped | failed

    def to_dict(self) -> Dict:
        return {
            "index": self.index,
            "description": self.description,
            "suggested_tool": self.suggested_tool,
            "status": self.status,
        }


class Plan:
    """执行计划"""
    def __init__(self, plan_id: str = "", steps: Optional[List[PlanStep]] = None):
        self.id = plan_id or f"plan_{uuid.uuid4().hex[:8]}"
        self.steps = steps or []
        self.status = "pending"  # pending | running | completed | cancelled

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def completed(self) -> int:
        return sum(1 for s in self.steps if s.status in ("done", "skipped"))

    @property
    def percent(self) -> int:
        if self.total == 0:
            return 100
        return int(self.completed / self.total * 100)

    def get_current_step(self) -> Optional[PlanStep]:
        for s in self.steps:
            if s.status == "pending":
                return s
        return None


class TaskPlanner:
    """任务规划器 — 让 LLM 判断是否需要拆步骤"""

    def __init__(self):
        self.current_plan: Optional[Plan] = None
        # ★ S3.1: 每步执行结果缓存（plan_id → {step_index: result}）
        self._step_results: Dict[str, Dict[int, Any]] = {}

    async def plan(
        self,
        user_message: str,
        llm_adapter,  # LLMAdapter 实例
        enabled_skills: Optional[List[str]] = None,
    ) -> Plan:
        """让 LLM 判断任务是否需要拆分成多个步骤

        如需要拆步骤，LLM 返回 JSON:
          {"steps":[{"description":"步骤描述","suggested_tool":"工具名（可选）"}]}
        如果不需要拆分，返回:
          {"steps":[]}
        """
        skills_hint = ""
        if enabled_skills:
            skills_hint = f"可用工具: {', '.join(enabled_skills[:20])}"

        prompt = f"""判断以下任务是否需要拆分为多个步骤执行。
{skills_hint}

如需拆分，输出 JSON 格式（只输出 JSON，不要其他内容）：
{{"steps":[{{"description":"步骤描述","suggested_tool":"可选工具名"}}]}}

如果不需要拆分（可以直接回答或一步完成），返回：
{{"steps":[]}}

任务: {user_message}"""

        try:
            result = await llm_adapter.call(
                prompt=prompt,
                system_prompt="你是任务规划助手。只输出 JSON，不要输出其他内容。",
            )
            # 清理可能的 markdown 代码块包裹
            result = result.strip()
            if result.startswith("```"):
                result = result.split("\n", 1)[-1]
                if result.endswith("```"):
                    result = result[:-3]
                result = result.strip()
                if result.startswith("json"):
                    result = result[4:].strip()

            data = json.loads(result)
            raw_steps = data.get("steps", [])

            if not raw_steps:
                logger.info("[Planner] 无需拆分步骤，直接执行")
                plan = Plan(steps=[])
            else:
                steps = [
                    PlanStep(
                        description=s.get("description", ""),
                        suggested_tool=s.get("suggested_tool", ""),
                        index=i + 1,
                    )
                    for i, s in enumerate(raw_steps)
                ]
                plan = Plan(steps=steps)
                logger.info(
                    f"[Planner] 任务拆分为 {len(steps)} 步: "
                    + ", ".join(s.description[:40] for s in steps)
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[Planner] LLM 返回格式错误 ({e})，默认不拆分")
            plan = Plan(steps=[])
        except Exception as e:
            logger.warning(f"[Planner] 规划失败 ({e})，默认不拆分")
            plan = Plan(steps=[])

        self.current_plan = plan
        return plan

    def get_current_plan(self) -> Optional[Plan]:
        return self.current_plan

    def get_current_step(self) -> Optional[PlanStep]:
        """返回当前正在执行的 step（status="in_progress" 的那条）
        
        如果没有 current_plan 或没有 running 步骤，返回第一个 pending 步骤。
        都没有则返回 None。
        """
        if not self.current_plan:
            return None
        for s in self.current_plan.steps:
            if s.status == "running":
                return s
        # fallback: 返回第一个 pending 步骤
        for s in self.current_plan.steps:
            if s.status == "pending":
                return s
        return None

    def get_all_plans(self) -> List[Plan]:
        """返回历史 plan 列表（MVP: 单 plan，返回 current_plan 的列表）"""
        if self.current_plan:
            return [self.current_plan]
        return []

    def cancel_plan(self):
        """取消当前计划，将 current_plan.status 置为 cancelled"""
        if self.current_plan:
            self.current_plan.status = "cancelled"
            logger.info(f"[Planner] 计划已取消: {self.current_plan.id}")

    def get_progress(self) -> Dict[str, Any]:
        if not self.current_plan:
            return {"has_plan": False, "total": 0, "completed": 0, "percent": 100}
        return {
            "has_plan": True,
            "total": self.current_plan.total,
            "completed": self.current_plan.completed,
            "percent": self.current_plan.percent,
        }

    def format_plan_summary(self) -> str:
        if not self.current_plan or not self.current_plan.steps:
            return "无需分步执行"
        lines = [f"任务计划 ({self.current_plan.completed}/{self.current_plan.total}):"]
        for s in self.current_plan.steps:
            icon = {"pending": "⏳", "running": "▶️", "done": "✅", "skipped": "⏭️", "failed": "❌"}.get(s.status, "❓")
            lines.append(f"  {icon} 步骤{s.index}: {s.description}")
        return "\n".join(lines)

    def complete_step(self, step_index: int):
        if self.current_plan:
            for s in self.current_plan.steps:
                if s.index == step_index:
                    s.status = "done"
                    break

    def skip_step(self, step_index: int):
        if self.current_plan:
            for s in self.current_plan.steps:
                if s.index == step_index:
                    s.status = "skipped"
                    break

    def fail_step(self, step_index: int):
        if self.current_plan:
            for s in self.current_plan.steps:
                if s.index == step_index:
                    s.status = "failed"
                    break

    def start_step(self, step_index: int):
        if self.current_plan:
            for s in self.current_plan.steps:
                if s.index == step_index:
                    s.status = "running"
                    break

    # ★ S3.1: 步骤结果缓存（plan 模式逐步骤执行时用）

    def set_step_result(self, step_index: int, result: Any):
        """保存某步的执行结果"""
        if not self.current_plan:
            return
        plan_id = self.current_plan.id
        if plan_id not in self._step_results:
            self._step_results[plan_id] = {}
        self._step_results[plan_id][step_index] = result
        logger.debug(f"[Planner] 步骤 {step_index} 结果已保存")

    def get_step_result(self, step_index: int) -> Optional[Any]:
        """获取某步的执行结果"""
        if not self.current_plan:
            return None
        return self._step_results.get(self.current_plan.id, {}).get(step_index)

    def get_all_step_results(self) -> Dict[int, Any]:
        """获取所有步骤的执行结果"""
        if not self.current_plan:
            return {}
        return self._step_results.get(self.current_plan.id, {})

    def clear_step_results(self):
        """清除当前 plan 的步骤结果缓存"""
        if self.current_plan:
            self._step_results.pop(self.current_plan.id, None)


_instance = TaskPlanner()


def get_task_planner() -> TaskPlanner:
    return _instance
