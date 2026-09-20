"""任务执行器 - TaskExecutor"""

import asyncio
from typing import Optional, Callable, Any, Dict
from .models import Task, TaskPlan, TaskStatus
from .prompts import TASK_EXECUTOR_PROMPT


class TaskExecutor:
    """
    任务执行器
    
    逐步执行子任务，更新状态，返回结果
    """

    def __init__(
        self,
        llm_client: Any,
        prompt_template: str = TASK_EXECUTOR_PROMPT,
        max_concurrent: int = 1,
    ):
        """
        Args:
            llm_client: LLM 客户端，需实现 chat(user_input) -> str 方法
            prompt_template: Prompt 模板
            max_concurrent: 最大并发任务数
        """
        self.llm_client = llm_client
        self.prompt_template = prompt_template
        self.max_concurrent = max_concurrent

    async def execute_plan(
        self,
        plan: TaskPlan,
        context: Optional[Dict[str, Any]] = None,
        on_task_start: Optional[Callable[[Task], None]] = None,
        on_task_complete: Optional[Callable[[Task], None]] = None,
        on_plan_progress: Optional[Callable[[float], None]] = None,
    ) -> TaskPlan:
        """
        执行任务计划
        
        Args:
            plan: 任务计划
            context: 执行上下文（传递之前任务的结果）
            on_task_start: 任务开始回调
            on_task_complete: 任务完成回调
            on_plan_progress: 整体进度回调
            
        Returns:
            TaskPlan: 执行后的任务计划（包含结果）
        """
        context = context or {}

        for i, task in enumerate(plan.tasks):
            # 执行单个任务
            await self._execute_task(
                task=task,
                context=context,
                on_start=on_task_start,
                on_complete=on_task_complete,
            )

            # 更新上下文
            context[f"task_{task.id}"] = {
                "result": task.result,
                "error": task.error,
                "status": task.status,
            }

            # 进度回调
            if on_plan_progress:
                on_plan_progress(plan.progress)

            # 如果任务失败且是 critical 任务，可选择停止
            if task.status == TaskStatus.FAILED:
                if task.metadata.get("critical", True):
                    # 标记剩余任务为跳过
                    for remaining_task in plan.tasks[i + 1:]:
                        remaining_task.status = TaskStatus.SKIPPED
                    break

        return plan

    async def _execute_task(
        self,
        task: Task,
        context: Dict[str, Any],
        on_start: Optional[Callable[[Task], None]] = None,
        on_complete: Optional[Callable[[Task], None]] = None,
    ) -> None:
        """执行单个任务"""
        if on_start:
            task.start()
            on_start(task)

        try:
            # 构建 prompt
            prompt = self.prompt_template.format(
                task_name=task.name,
                task_description=task.description,
                context=context,
            )

            # 调用 LLM 执行
            response = await self._chat_async(prompt)

            # 解析结果
            result = self._parse_response(response)

            if result.get("success", False):
                task.complete(result=result.get("result"))
            else:
                task.fail(error=result.get("error", "Unknown error"))

        except Exception as e:
            task.fail(error=str(e))

        if on_complete:
            on_complete(task)

    async def _chat_async(self, prompt: str) -> str:
        """异步调用 LLM"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.llm_client.chat, prompt)

    def _parse_response(self, response: str) -> dict:
        """解析 LLM 的 JSON 响应"""
        import json

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

    def execute_sync(
        self,
        plan: TaskPlan,
        context: Optional[Dict[str, Any]] = None,
        on_task_start: Optional[Callable[[Task], None]] = None,
        on_task_complete: Optional[Callable[[Task], None]] = None,
        on_plan_progress: Optional[Callable[[float], None]] = None,
    ) -> TaskPlan:
        """同步执行包装器"""
        return asyncio.run(
            self.execute_plan(
                plan=plan,
                context=context,
                on_task_start=on_task_start,
                on_task_complete=on_task_complete,
                on_plan_progress=on_plan_progress,
            )
        )
