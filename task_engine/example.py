"""任务引擎使用示例"""

import asyncio
from task_engine import TaskPlanner, TaskExecutor, TaskDisplay


class MockLLMClient:
    """模拟 LLM 客户端用于测试"""

    def __init__(self, plan_response: str = None, exec_response: str = None):
        self.plan_response = plan_response or self._default_plan()
        self.exec_response = exec_response or '{"success": true, "result": "任务已完成"}'
        self.call_count = 0

    def _default_plan(self) -> str:
        return '''
{
  "goal": "分析项目代码结构",
  "tasks": [
    {
      "id": "task_1",
      "name": "扫描项目文件",
      "description": "遍历项目目录，识别所有源代码文件"
    },
    {
      "id": "task_2",
      "name": "分析依赖关系",
      "description": "解析 import/require 语句，构建依赖图"
    },
    {
      "id": "task_3",
      "name": "生成结构报告",
      "description": "输出项目结构树和模块关系"
    }
  ]
}
'''

    def chat(self, prompt: str) -> str:
        self.call_count += 1
        # 简单判断是规划还是执行
        if "分解" in prompt or "规划" in prompt:
            return self.plan_response
        return self.exec_response


def main():
    # 初始化组件
    llm = MockLLMClient()
    planner = TaskPlanner(llm)
    executor = TaskExecutor(llm)
    display = TaskDisplay()

    # 用户输入
    user_input = "帮我分析这个 Python 项目的代码结构"

    # 1. 显示欢迎信息
    display.console.print("[bold blue]🚀 任务引擎已启动[/bold blue]\n")

    # 2. 任务分解
    display.show_message("正在分解任务...")
    plan = planner.plan(user_input)
    display.show_plan(plan)

    # 3. 执行任务（带实时显示）
    display.console.print("[bold]开始执行任务...[/bold]\n")

    def on_progress(progress: float):
        display.console.print(f"\r进度：{progress * 100:.0f}%", end="")

    plan = executor.execute_sync(
        plan=plan,
        on_plan_progress=on_progress,
    )

    # 4. 显示结果
    display.show_result(plan)


if __name__ == "__main__":
    main()
