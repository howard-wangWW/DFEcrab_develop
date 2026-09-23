"""
任务规划技能

分析用户任务，生成执行计划，并跟踪执行状态。
当检测到复杂任务时，由 Planner 生成结构化执行计划。
"""

from typing import Dict, Any, List
from src.agent.planner import get_task_planner


COMPLEXITY_KEYWORDS = [
    "部署", "安装", "配置", "构建", "开发",
    "多个", "一系列", "复杂", "全面",
    "帮我", "请帮我", "能不能",
    "如果", "假设",
    "项目", "系统", "应用",
    "目录", "文件夹", "所有文件", "批量",
    "分析", "了解", "理解", "研究",
    "整理", "总结", "报告",
]

COMPLEXITY_THRESHOLD = 2


def execute(task: str, context: dict = None) -> Dict[str, Any]:
    """
    分析任务并生成执行计划

    Args:
        task: 用户任务描述
        context: 上下文信息（可选）

    Returns:
        包含状态和内容的字典
    """
    try:
        task_lower = task.lower()

        complexity_score = 0
        detected_complexities = []

        for keyword in COMPLEXITY_KEYWORDS:
            if keyword in task_lower:
                complexity_score += 1
                if len(detected_complexities) < 5:
                    detected_complexities.append(keyword)

        if complexity_score >= COMPLEXITY_THRESHOLD:
            is_complex = True
            complexity_level = "high" if complexity_score >= 4 else "medium"
        else:
            is_complex = False
            complexity_level = "low"

        if is_complex:
            plan_data = _generate_plan(task, context)
            plan = _save_plan_to_tracker(task, plan_data, complexity_level)

            return {
                "status": "success",
                "content": _format_complex_plan(task, plan_data, complexity_level, detected_complexities, plan.id)
            }
        else:
            return {
                "status": "success",
                "content": _format_simple_plan(task)
            }

    except Exception as e:
        return {
            "status": "error",
            "content": f"规划失败：{str(e)}"
        }


def _generate_plan(task: str, context: dict = None) -> dict:
    """生成执行计划"""
    steps = []

    task_lower = task.lower()

    if any(k in task_lower for k in ["部署", "安装", "搭建"]):
        steps = [
            {
                "action": "环境检查",
                "description": "检查当前环境和依赖是否满足",
                "tools": ["file_read"],
                "expected": "环境状态报告"
            },
            {
                "action": "准备配置文件",
                "description": "创建或修改必要的配置文件",
                "tools": ["file_write"],
                "expected": "配置文件就绪"
            },
            {
                "action": "执行部署",
                "description": "执行部署命令或脚本",
                "tools": ["execute_python", "shell_command"],
                "expected": "部署完成报告"
            },
            {
                "action": "验证结果",
                "description": "检查部署是否成功",
                "tools": ["file_read", "shell_command"],
                "expected": "验证通过或失败报告"
            }
        ]

    elif any(k in task_lower for k in ["开发", "创建", "编写", "实现"]):
        steps = [
            {
                "action": "需求分析",
                "description": "理解具体需求和约束条件",
                "tools": [],
                "expected": "需求分析结果"
            },
            {
                "action": "方案设计",
                "description": "设计实现方案",
                "tools": [],
                "expected": "设计方案"
            },
            {
                "action": "编写代码",
                "description": "按照方案编写代码",
                "tools": ["file_write", "execute_python"],
                "expected": "代码文件"
            },
            {
                "action": "测试验证",
                "description": "测试代码是否正常工作",
                "tools": ["execute_python"],
                "expected": "测试结果"
            }
        ]

    elif any(k in task_lower for k in ["读取", "查看", "列出", "分析"]):
        if any(k in task_lower for k in ["目录", "文件夹", "项目", "所有文件"]):
            steps = [
                {
                    "action": "列出目录文件",
                    "description": "列出目录下的所有文件",
                    "tools": ["list_dir"],
                    "expected": "目录文件清单"
                },
                {
                    "action": "筛选目标文件",
                    "description": "根据需求筛选需要分析的文件",
                    "tools": [],
                    "expected": "目标文件列表"
                },
                {
                    "action": "逐个读取文件",
                    "description": "读取文件内容",
                    "tools": ["file_read", "word_read"],
                    "expected": "文件内容列表"
                },
                {
                    "action": "综合分析",
                    "description": "分析所有文件内容，整理总结",
                    "tools": [],
                    "expected": "分析总结报告"
                }
            ]
        else:
            steps = [
                {
                    "action": "识别文件路径",
                    "description": "从任务中提取文件路径",
                    "tools": [],
                    "expected": "文件路径"
                },
                {
                    "action": "读取文件",
                    "description": "使用工具读取文件内容",
                    "tools": ["file_read", "word_read"],
                    "expected": "文件内容"
                },
                {
                    "action": "分析内容",
                    "description": "理解文件内容并总结",
                    "tools": [],
                    "expected": "内容摘要"
                }
            ]

    else:
        steps = [
            {
                "action": "理解任务",
                "description": "分析用户意图",
                "tools": [],
                "expected": "任务理解"
            },
            {
                "action": "分解步骤",
                "description": "将任务分解为可执行的步骤",
                "tools": [],
                "expected": "步骤列表"
            },
            {
                "action": "执行",
                "description": "按步骤执行",
                "tools": ["file_read", "execute_python"],
                "expected": "执行结果"
            }
        ]

    return {
        "task": task,
        "steps": steps,
        "estimated_steps": len(steps)
    }


def _save_plan_to_tracker(task: str, plan_data: dict, complexity: str):
    """保存计划到任务跟踪器"""
    planner = get_task_planner()
    plan = planner.create_plan(task, plan_data["steps"], complexity)
    return plan


def _format_complex_plan(task: str, plan: dict, level: str, keywords: list, plan_id: str = "") -> str:
    """格式化复杂任务计划"""
    plan_id_str = f"\n**计划ID**: `{plan_id}`" if plan_id else ""

    result = f"""## 任务分析

**原始任务**: {task}

**复杂度等级**: {level.upper()} (检测到: {', '.join(keywords)}){plan_id_str}

**预计步骤数**: {plan['estimated_steps']} 步

## 执行计划

"""

    for i, step in enumerate(plan["steps"], 1):
        tools_str = ", ".join(step["tools"]) if step["tools"] else "无需工具"
        result += f"""### 步骤 {i}: {step['action']}
- **描述**: {step['description']}
- **使用工具**: {tools_str}
- **预期结果**: {step['expected']}

"""

    result += """## 执行原则

1. 按照步骤顺序执行，不要跳跃
2. 每步完成后验证结果
3. 如遇失败，尝试替代方案
4. 最终汇报整体执行结果

## 跟踪命令

- `/plan` - 查看当前计划进度
- `/plan step` - 查看当前步骤详情
- `/plan next` - 执行下一步
- `/plan skip` - 跳过当前步骤
- `/plan cancel` - 取消计划
"""
    return result


def _format_simple_plan(task: str) -> str:
    """格式化简单任务"""
    return f"""## 任务分析

**原始任务**: {task}

**复杂度等级**: LOW

这是一个简单任务，可以直接执行。

## 执行建议

直接调用相关工具完成即可。
"""


def get_current_plan_info() -> dict:
    """获取当前计划信息"""
    planner = get_task_planner()
    return planner.get_progress()


def get_plan_summary() -> str:
    """获取计划摘要"""
    planner = get_task_planner()
    return planner.format_plan_summary()


SKILL_METADATA = {
    "name": "planner",
    "version": "2.0.0",
    "description": "任务规划技能 - 分析任务复杂度、生成执行计划、跟踪执行状态",
    "author": "DFEcrab Team",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "用户任务描述"
            },
            "context": {
                "type": "object",
                "description": "上下文信息（可选）",
                "additionalProperties": True
            }
        },
        "required": ["task"]
    }
}
