# Task Engine - 任务分解与执行引擎

独立的 CLI 任务处理模块，可集成到现有系统中。

## 架构

```
task_engine/
├── __init__.py      # 公共接口导出
├── models.py        # 数据模型 (Task, TaskPlan, TaskStatus)
├── planner.py       # TaskPlanner - 任务分解
├── executor.py      # TaskExecutor - 任务执行
├── display.py       # TaskDisplay - CLI 可视化
├── prompts.py       # AI Prompt 模板
└── example.py       # 使用示例
```

## 快速开始

```python
from task_engine import TaskPlanner, TaskExecutor, TaskDisplay

# 初始化（传入你的 LLM 客户端）
llm = MyLLMClient()  # 需实现 chat(prompt) -> str 方法
planner = TaskPlanner(llm)
executor = TaskExecutor(llm)
display = TaskDisplay()

# 1. 分解任务
plan = planner.plan("帮我分析项目代码结构")
display.show_plan(plan)

# 2. 执行任务
plan = executor.execute_sync(plan)
display.show_result(plan)
```

## 数据结构

### Task
```json
{
  "id": "task_1",
  "name": "任务名称",
  "description": "任务描述",
  "status": "pending|running|completed|failed|skipped",
  "result": "执行结果",
  "error": "错误信息"
}
```

### TaskPlan
```json
{
  "goal": "总体目标",
  "tasks": [...],
  "created_at": "2024-01-01T00:00:00"
}
```

## 回调函数

```python
# 任务开始回调
def on_task_start(task: Task):
    print(f"开始：{task.name}")

# 任务完成回调
def on_task_complete(task: Task):
    print(f"完成：{task.name} - {task.result}")

# 进度回调
def on_progress(progress: float):
    print(f"进度：{progress * 100:.0f}%")

# 执行
executor.execute_sync(
    plan=plan,
    on_task_start=on_task_start,
    on_task_complete=on_task_complete,
    on_plan_progress=on_progress,
)
```

## 依赖

- rich (CLI 显示)
- pydantic (数据模型)

## 运行示例

```bash
cd task_engine
python example.py
```
