"""
记忆层 - memory 域

架构（单一门面 + 分层引擎）：
- UnifiedMemoryManager —— 统一门面/编排（对话记忆闭环：注入画像、自动提取、
  滚动摘要、检索）。组合调用下方各引擎：
    - GlobalMemoryManager   每日日志 / 全局共享（src.memory.global_manager）
    - MemoryManager         Agent 长期记忆 agents/{agent}/memory.json（src.memory.long_term）
    - UserMemoryManager     用户级记忆（src.memory.user_manager）
    - MemorySearchEngine    BM25 检索（src.memory.search）
- types —— 数据结构（MemoryEntry / MemoryType / MemoryCategory / MemoryConfig）

统一入口建议：from src.memory import UnifiedMemoryManager
（历史调用方可继续直接 import 各引擎子模块，行为不变）
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory.unified_manager import UnifiedMemoryManager
    from src.memory.types import MemoryConfig
    from src.memory.global_manager import get_global_memory_manager

__all__ = [
    'UnifiedMemoryManager',
    'get_global_memory_manager',
    'MemoryConfig',
]


def __getattr__(name: str):
    if name == "UnifiedMemoryManager":
        from src.memory.unified_manager import UnifiedMemoryManager

        return UnifiedMemoryManager
    if name == "get_global_memory_manager":
        from src.memory.global_manager import get_global_memory_manager

        return get_global_memory_manager
    if name == "MemoryConfig":
        from src.memory.types import MemoryConfig

        return MemoryConfig
    raise AttributeError(f"module 'src.memory' has no attribute {name!r}")
