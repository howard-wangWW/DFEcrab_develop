"""
记忆搜索系统

提供基于 BM25 的关键词检索引擎（MemorySearchEngine），
按用户隔离检索三类记忆语料：用户级记忆、Agent 经验、每日日志。
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..types import MemoryEntry, MemoryConfig, SearchResult

__all__ = [
    "MemorySearchEngine",
]

from .keyword_search import MemorySearchEngine
