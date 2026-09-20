"""
集成到现有 CLI 的示例

在你的主 CLI 中这样使用：

```python
from task_engine import TaskPlanner, TaskExecutor, TaskDisplay

# 1. 创建 LLM 客户端适配器（复用你现有的 AI 客户端）
class MyLLMClient:
    def __init__(self, existing_client):
        self.client = existing_client
    
    def chat(self, prompt: str) -> str:
        # 调用你现有的 AI 接口
        return self.client.generate(prompt)

# 2. 在 CLI 命令中集成
@app.command()
def smart_task(input: str):
    llm = MyLLMClient(my_ai_client)
    planner = TaskPlanner(llm)
    executor = TaskExecutor(llm)
    display = TaskDisplay()
    
    # 分解任务
    plan = planner.plan(input)
    display.show_plan(plan)
    
    # 执行并显示
    plan = executor.execute_sync(plan)
    display.show_result(plan)
```
"""

# 简单的测试脚本
if __name__ == "__main__":
    from example import main
    main()
