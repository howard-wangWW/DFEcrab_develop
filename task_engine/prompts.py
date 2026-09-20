"""AI Prompt 模板"""

TASK_PLANNER_PROMPT = """你是一个任务规划专家。请将用户的目标分解为可执行的子任务。

要求：
1. 每个任务应该是原子操作，可在 5-10 分钟内完成
2. 任务之间尽量独立，如有依赖请明确说明
3. 返回 JSON 格式，符合以下 schema：

{
  "goal": "总体目标描述",
  "tasks": [
    {
      "id": "task_1",
      "name": "简短任务名",
      "description": "详细任务描述，包含执行步骤"
    }
  ]
}

用户目标：{user_input}

请直接返回 JSON，不要其他解释。"""


TASK_EXECUTOR_PROMPT = """你是一个任务执行助手。请执行以下任务并返回结果。

任务信息：
- 名称：{task_name}
- 描述：{task_description}
- 上下文：{context}

请执行任务并返回：
1. 执行结果（简洁明了）
2. 如有错误，请明确说明

返回 JSON 格式：
{
  "success": true/false,
  "result": "执行结果描述",
  "error": "错误信息（如有）"
}

请直接返回 JSON，不要其他解释。"""
