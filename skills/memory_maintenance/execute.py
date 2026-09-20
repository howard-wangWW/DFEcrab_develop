"""
记忆维护技能

手动触发记忆维护任务：
- 每周汇总
- 每月汇总
- 提取长期记忆
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.agentscope_compat import ServiceResponse, ServiceExecStatus
from src.memory.global_manager import get_global_memory_manager


def execute(action: str) -> ServiceResponse:
    """
    执行记忆维护操作

    Args:
        action: 操作类型
            - "weekly": 执行每周汇总
            - "monthly": 执行每月汇总
            - "extract": 提取长期记忆
            - "all": 执行所有维护任务

    Returns:
        ServiceResponse 对象
    """
    try:
        manager = get_global_memory_manager()

        def _has(method_name: str) -> bool:
            return callable(getattr(manager, method_name, None))

        def _compat_message(label: str) -> ServiceResponse:
            stats = manager.get_stats()
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content=f"✅ {label}\n当前版本使用简化记忆管理器，无需额外汇总任务。\n\n统计信息：{stats}"
            )

        if action == "weekly":
            if not _has("weekly_summary"):
                return _compat_message("每周汇总兼容检查完成")
            success = manager.weekly_summary()
            if success:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content="✅ 每周汇总完成"
                )
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content="⚠️ 每周汇总失败，可能没有数据"
            )

        elif action == "monthly":
            if not _has("monthly_summary"):
                return _compat_message("每月汇总兼容检查完成")
            success = manager.monthly_summary()
            if success:
                if _has("extract_long_term_memory"):
                    manager.extract_long_term_memory()
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content="✅ 每月汇总完成，长期记忆已更新"
                )
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content="⚠️ 每月汇总失败，可能没有数据"
            )

        elif action == "extract":
            if not _has("extract_long_term_memory"):
                return _compat_message("长期记忆提取兼容检查完成")
            manager.extract_long_term_memory()
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content="✅ 长期记忆已更新"
            )

        elif action == "all":
            if not (_has("weekly_summary") and _has("monthly_summary") and _has("extract_long_term_memory")):
                return _compat_message("记忆维护任务兼容检查完成")
            manager.weekly_summary()
            manager.monthly_summary()
            manager.extract_long_term_memory()
            stats = manager.get_stats()
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content=f"""✅ 记忆维护任务全部完成

统计信息：
- 每日记忆：{stats.get('daily_count', 0)} 个
- 每周汇总：{stats.get('weekly_count', 0)} 个
- 每月汇总：{stats.get('monthly_count', 0)} 个
"""
            )

        else:
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"未知操作：{action}，支持：weekly, monthly, extract, all"
            )

    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"记忆维护失败：{str(e)}"
        )


SKILL_METADATA = {
    "name": "memory_maintenance",
    "version": "1.0.0",
    "description": "记忆维护技能 - 手动触发记忆汇总和长期记忆提取",
    "author": "DFEcrab Team",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型",
                "enum": ["weekly", "monthly", "extract", "all"]
            }
        },
        "required": ["action"]
    }
}
