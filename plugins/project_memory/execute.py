"""
项目记忆技能

用于管理项目相关的长期记忆，包括：
- 项目背景和目标
- 正在进行的工作
- 已完成的任务
- 技术决策和方案
- 重要文件位置

使用分层记忆管理：
- DAILY/: 每日记忆（按天保存）
- WEEKLY/: 每周汇总
- MONTHLY/: 每月汇总
- LONG_TERM.md: 长期记忆
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agentscope.service import ServiceResponse, ServiceExecStatus
from src.memory.global_manager import get_global_memory_manager


def execute(
    action: str,
    agent_id: str = "dfecrab",
    content: str = None,
    category: str = "general"
) -> ServiceResponse:
    """
    管理项目记忆

    Args:
        action: 操作类型
            - "save": 保存记忆
            - "load": 加载记忆
            - "list": 列出所有记忆
            - "search": 搜索记忆
            - "stats": 查看统计
        agent_id: 智能体 ID (默认 default)
        content: 要保存的内容 (save 时需要)
        category: 记忆分类 (默认 general)
            - general: 通用信息
            - background: 项目背景
            - progress: 工作进度
            - decision: 技术决策
            - file_location: 文件位置
            - todo: 待办事项

    Returns:
        ServiceResponse 对象
    """
    try:
        manager = MarkdownMemoryManager(agent_id)
        global_manager = get_global_memory_manager()

        if action == "save":
            if not content:
                return ServiceResponse(
                    status=ServiceExecStatus.ERROR,
                    content="保存记忆时需要提供 content 参数"
                )

            memory_entry = _format_memory_entry(content, category)

            # 1. 保存到 agent 私有记忆
            success = manager.add_memory_entry(memory_entry, memory_type="long_term")

            # 2. 保存到分层全局记忆
            daily_success = global_manager.save_daily_memory(content, category)

            if success or daily_success:
                location = []
                if success:
                    location.append("私有记忆")
                if daily_success:
                    location.append(f"全局记忆(DAILY/{global_manager._get_today_file().name})")

                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content=f"✅ 已保存记忆到 [{category}] 分类\n- 保存位置：{' + '.join(location)}\n\n{memory_entry}"
                )
            else:
                return ServiceResponse(
                    status=ServiceExecStatus.ERROR,
                    content="保存记忆失败"
                )

        elif action == "load":
            context = global_manager.load_all_context()
            if context:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content=f"📚 项目记忆：\n\n{context}"
                )
            else:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content="暂无项目记忆"
                )

        elif action == "list":
            stats = global_manager.get_stats()
            private_manager = MarkdownMemoryManager(agent_id)
            private_stats = private_manager.get_memory_stats()

            info = f"""📋 记忆统计：

## 全局分层记忆
- 每日记忆：{stats.get('daily_count', 0)} 个文件
- 每周汇总：{stats.get('weekly_count', 0)} 个文件
- 每月汇总：{stats.get('monthly_count', 0)} 个文件
- 长期记忆：{'有' if stats.get('has_long_term') else '无'}

## 私有记忆
- 总条目数：{private_stats.get('total_entries', 0)}

如需查看详细内容，请说"读取项目记忆"。"""
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content=info
            )

        elif action == "search":
            if not content:
                return ServiceResponse(
                    status=ServiceExecStatus.ERROR,
                    content="搜索记忆时需要提供 content 参数（关键词）"
                )

            context = global_manager.load_all_context()
            if not context:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content="暂无记忆，无法搜索"
                )

            lines = context.split("\n")
            matched = []
            for line in lines:
                if content.lower() in line.lower():
                    matched.append(line.strip())

            if matched:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content=f"🔍 搜索结果（关键词：{content}）：\n\n" + "\n".join(matched[:20])
                )
            else:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content=f"未找到包含'{content}'的记忆"
                )

        elif action == "stats":
            stats = global_manager.get_stats()
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content=f"📊 记忆统计：\n\n{stats}"
            )

        else:
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"未知操作：{action}，支持的操作为：save, load, list, search, stats"
            )

    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"记忆操作失败：{str(e)}"
        )


def _format_memory_entry(content: str, category: str) -> str:
    """格式化记忆条目"""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    category_emoji = {
        "general": "📝",
        "background": "🏢",
        "progress": "📊",
        "decision": "⚖️",
        "file_location": "📁",
        "todo": "✅"
    }

    emoji = category_emoji.get(category, "📝")
    return f"\n{emoji} [{category.upper()}] {timestamp}\n{content}\n"


def save_memory(agent_id: str, content: str, category: str = "general") -> bool:
    """直接保存记忆的辅助函数"""
    try:
        manager = MarkdownMemoryManager(agent_id)
        global_manager = get_global_memory_manager()

        memory_entry = _format_memory_entry(content, category)
        manager.add_memory_entry(memory_entry, memory_type="long_term")
        global_manager.save_daily_memory(content, category)
        return True
    except Exception:
        return False


SKILL_METADATA = {
    "name": "project_memory",
    "version": "2.0.0",
    "description": "项目记忆技能 - 分层记忆管理（每日/每周/每月/长期）",
    "author": "DFEcrab Team",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：save(保存), load(读取), list(统计), search(搜索), stats(状态)",
                "enum": ["save", "load", "list", "search", "stats"]
            },
            "agent_id": {
                "type": "string",
                "description": "智能体 ID（默认 default）",
                "default": "default"
            },
            "content": {
                "type": "string",
                "description": "记忆内容（save/search 时需要）"
            },
            "category": {
                "type": "string",
                "description": "记忆分类",
                "enum": ["general", "background", "progress", "decision", "file_location", "todo"],
                "default": "general"
            }
        },
        "required": ["action"]
    }
}