"""
全局记忆模块 - V3.0 简化版

管理全局共享记忆，使用 GlobalMemoryManager 替代已删除的 HierarchicalMemoryManager。
电网知识库已移除（与新知识库系统冲突），全局模块仅负责每日日志的写入。
"""

from pathlib import Path
from typing import Dict, Any, Optional, List

from src.utils.logger import get_logger
from src.memory.global_manager import get_global_memory_manager

from .base_module import BaseMemoryModule, ModuleError, PermissionDeniedError
from ..types import (
    MemoryEntry, MemoryType,
    TimeRange, MemoryStats
)

logger = get_logger(__name__)


class GlobalMemoryModule(BaseMemoryModule):
    """
    全局记忆模块 - V3.0

    基于 GlobalMemoryManager，提供全局共享和长期记忆的访问。
    """

    def __init__(self, config: Dict[str, Any], unified_manager: Any):
        super().__init__(config, unified_manager, MemoryType.GLOBAL)
        self.storage_base_path = config.get("storage_base_path", Path("data/memory/global"))
        self._global_mgr = get_global_memory_manager()
        logger.info("GlobalMemoryModule 已初始化 (V3.0 简化版)")

    async def initialize(self) -> None:
        self._initialized = True
        logger.info("全局记忆模块初始化完成")

    async def save_memory(self, memory_entry: MemoryEntry, user_id: Optional[str] = None) -> MemoryEntry:
        if memory_entry.memory_type != MemoryType.GLOBAL:
            raise ModuleError(f"全局记忆模块不支持记忆类型: {memory_entry.memory_type}")
        if not self._check_permission(memory_entry):
            raise PermissionDeniedError("权限不足，无法保存全局记忆")

        logger.info(f"保存全局记忆 [{memory_entry.id}]: {memory_entry.content[:50]}...")
        try:
            self._global_mgr.save_daily_memory(
                content=memory_entry.content,
                category=memory_entry.category.value if hasattr(memory_entry.category, 'value') else "general",
                user_id=user_id
            )
            self.stats.total_processed += 1
            logger.debug(f"全局记忆保存成功 [{memory_entry.id}]")
            return memory_entry
        except Exception as e:
            logger.error(f"保存全局记忆失败 [{memory_entry.id}]: {e}")
            raise ModuleError(f"保存全局记忆失败: {e}")

    async def get_memory(self, memory_id: str, agent_id: Optional[str] = None) -> Optional[MemoryEntry]:
        logger.debug(f"获取全局记忆 [{memory_id}]")
        try:
            # 电网知识库已移除，按 memory_id 无法定位全局记忆条目，返回 None
            return None
        except Exception as e:
            logger.warning(f"获取全局记忆失败 [{memory_id}]: {e}")
            return None

    async def get_relevant_memories(
        self,
        agent_id: Optional[str] = None,
        time_range: Optional[TimeRange] = None,
        limit: int = 20,
        user_id: Optional[str] = None
    ) -> List[MemoryEntry]:
        logger.debug(f"获取相关全局记忆 (agent_id={agent_id}, limit={limit})")
        # 电网知识库已移除（与新知识库系统冲突），全局模块不再提供知识条目
        return []

    async def search_memories(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 10
    ) -> List[MemoryEntry]:
        logger.debug(f"搜索全局记忆: '{query}'")
        try:
            all_memories = await self.get_relevant_memories(agent_id=agent_id, limit=100)
            query_lower = query.lower()
            matched = [m for m in all_memories if query_lower in m.content.lower()]
            if not matched and all_memories:
                matched = all_memories
            return matched[:limit]
        except Exception as e:
            logger.warning(f"搜索全局记忆失败: {e}")
            return []

    async def delete_memory(self, memory_id: str, agent_id: Optional[str] = None) -> bool:
        logger.warning(f"尝试删除全局记忆 [{memory_id}] - 全局记忆通常不允许删除")
        return False

    def get_stats(self) -> MemoryStats:
        base_stats = super().get_stats()
        try:
            gm_stats = self._global_mgr.get_stats()
            base_stats.update(gm_stats)
        except Exception as e:
            logger.warning(f"获取全局记忆统计信息失败: {e}")
        return base_stats

    def _check_permissions(self, memory_entry: MemoryEntry, agent_id: Optional[str] = None) -> bool:
        return True

    def _check_permission(self, memory_entry: MemoryEntry) -> bool:
        return True