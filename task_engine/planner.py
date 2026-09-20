"""任务分解器 - TaskPlanner"""

import json
import uuid
from typing import Optional, Callable, Any
from .models import Task, TaskPlan
from .prompts import TASK_PLANNER_PROMPT


class TaskPlanner:
    """
    任务分解器
    
    接收用户输入，调用 AI 分解成结构化任务列表
    """

    def __init__(self, llm_client: Any, prompt_template: str = TASK_PLANNER_PROMPT):
        """
        Args:
            llm_client: LLM 客户端，需实现 chat(user_input) -> str 方法
            prompt_template: Prompt 模板
        """
        self.llm_client = llm_client
        self.prompt_template = prompt_template

    def plan(
        self,
        user_input: str,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> TaskPlan:
        """
        分解用户输入为任务计划
        
        Args:
            user_input: 用户的目标/需求
            on_progress: 进度回调函数
            
        Returns:
            TaskPlan: 结构化任务计划
        """
        if on_progress:
            on_progress("正在分析需求，生成任务计划...")

        # 构建 prompt
        prompt = self.prompt_template.format(user_input=user_input)

        # 调用 LLM
        response = self.llm_client.chat(prompt)

        if on_progress:
            on_progress("正在解析任务结构...")

        # 解析 JSON 响应
        plan_data = self._parse_response(response)

        # 构建 TaskPlan
        tasks = [
            Task(
                id=t.get("id", f"task_{uuid.uuid4().hex[:8]}"),
                name=t["name"],
                description=t["description"],
            )
            for t in plan_data["tasks"]
        ]

        return TaskPlan(
            goal=plan_data.get("goal", user_input),
            tasks=tasks,
        )

    def _parse_response(self, response: str) -> dict:
        """解析 LLM 的 JSON 响应"""
        # 尝试提取 JSON（处理可能的 markdown 包裹）
        response = response.strip()

        # 移除 markdown 代码块标记
        if response.startswith("```"):
            lines = response.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = "\n".join(lines)

        # 查找 JSON 边界
        start = response.find("{")
        end = response.rfind("}") + 1

        if start != -1 and end > start:
            response = response[start:end]

        return json.loads(response)
