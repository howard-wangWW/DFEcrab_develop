"""
Agent记忆模块 - V3.0 简化版

仅基于 MemoryManager 实现，负责 Agent 私有记忆和共享记忆的操作。
去除了对已删除的 MarkdownMemoryManager 的依赖。
"""

import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List

from src.utils.logger import get_logger
from src.memory.long_term import MemoryManager

from .base_module import BaseMemoryModule, ModuleError, PermissionDeniedError
from ..types import (
    MemoryEntry, MemoryType, MemoryCategory,
    TimeRange, MemoryStats
)

logger = get_logger(__name__)


class AgentMemoryModule(BaseMemoryModule):
    """
    Agent记忆模块 - V3.0 简化版

    仅基于 MemoryManager 实现，提供统一的 Agent 记忆管理。
    """

    def __init__(self, config: Dict[str, Any], unified_manager: Any):
        super().__init__(config, unified_manager, MemoryType.AGENT_PRIVATE)

        self.storage_base_path = config.get("storage_base_path", Path("data/memory/agent"))
        self._memory_managers: Dict[str, MemoryManager] = {}
        self._recent_memories_cache: Dict[str, MemoryEntry] = {}
        self._cache_size = config.get("cache_size", 200)

        logger.info("Agent记忆模块已初始化 (V3.0 简化版)")

    async def initialize(self) -> None:
        self._ensure_path_exists(self.storage_base_path)
        self._initialized = True
        logger.info("Agent记忆模块初始化完成")

    def _get_memory_manager(self, agent_id: str, user_id: Optional[str] = None) -> MemoryManager:
        """获取或创建 MemoryManager（user_id 提供时按用户隔离存储）"""
        cache_key = f"{agent_id}:{user_id or ''}"
        if cache_key not in self._memory_managers:
            self._memory_managers[cache_key] = MemoryManager(agent_id=agent_id, user_id=user_id)
        return self._memory_managers[cache_key]
    
    def _convert_to_markdown_format(self, memory_entry: MemoryEntry) -> str:
        """将MemoryEntry转换为Markdown格式"""
        timestamp = memory_entry.metadata.created_at.strftime("%Y-%m-%d %H:%M:%S")
        category = memory_entry.category.value
        
        # 提取标题（第一行）
        lines = memory_entry.content.strip().split('\n')
        title = lines[0] if lines else "无标题"
        body = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
        
        formatted = f"{timestamp} [{category}] {title}"
        if body:
            formatted += f"\n{body}"
        
        return formatted
    
    def _extract_from_markdown_format(self, markdown_content: str, agent_id: str) -> MemoryEntry:
        """从Markdown格式提取MemoryEntry"""
        # 简化解析：假设格式为 "时间戳 [分类] 标题\n内容"
        lines = markdown_content.strip().split('\n', 1)
        if not lines:
            raise ValueError("空的Markdown内容")
        
        header = lines[0]
        content = lines[1] if len(lines) > 1 else ""
        
        # 解析头部
        import re
        pattern = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[([^\]]+)\] (.+)"
        match = re.match(pattern, header)
        
        if not match:
            # 使用简化解析
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            category = "general"
            title = header
        else:
            timestamp_str, category, title = match.groups()
        
        # 合并标题和内容
        full_content = title
        if content:
            full_content += f"\n{content}"
        
        # 解析时间戳
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp = datetime.now()
        
        # 生成ID
        content_hash = hashlib.md5(full_content.encode()).hexdigest()
        memory_id = f"agent_{agent_id}_{content_hash[:12]}"
        
        from ..types import MemoryMetadata
        
        metadata = MemoryMetadata(
            created_at=timestamp,
            accessed_at=datetime.now(),
            access_count=1
        )
        
        return MemoryEntry(
            id=memory_id,
            content=full_content,
            memory_type=MemoryType.AGENT_PRIVATE,
            category=MemoryCategory(category),
            agent_id=agent_id,
            metadata=metadata
        )
    
    async def save_memory(self, memory_entry: MemoryEntry, user_id: Optional[str] = None) -> MemoryEntry:
        """保存Agent记忆 - V3.0 仅使用 MemoryManager"""
        start_time = self._track_operation_start()

        try:
            if memory_entry.memory_type not in [MemoryType.AGENT_PRIVATE, MemoryType.AGENT_SHARED]:
                raise ValueError(f"Agent记忆模块不支持记忆类型: {memory_entry.memory_type}")

            if not self._check_permissions(memory_entry, memory_entry.agent_id):
                raise PermissionDeniedError(f"Agent {memory_entry.agent_id} 没有权限保存记忆")

            memory_manager = self._get_memory_manager(memory_entry.agent_id, user_id)
            memory_manager.add_to_long_term(
                category="patterns",
                content=memory_entry.content,
                tags=[memory_entry.agent_id, "execution"] if memory_entry.agent_id else ["execution"]
            )
            memory_id = f"agent_{memory_entry.agent_id}_{hashlib.md5(memory_entry.content.encode()).hexdigest()[:12]}"
            if memory_id:
                memory_entry.id = memory_id

            cache_key = f"{memory_entry.agent_id}:{memory_entry.id}"
            self._recent_memories_cache[cache_key] = memory_entry

            if len(self._recent_memories_cache) > self._cache_size:
                oldest_key = next(iter(self._recent_memories_cache))
                del self._recent_memories_cache[oldest_key]

            self.stats.total_processed += 1
            elapsed_time = self._track_operation_end(start_time)
            logger.info(f"保存Agent记忆 [{memory_entry.id}] (耗时: {elapsed_time:.2f}ms)")
            return memory_entry

        except Exception as e:
            self.stats.total_errors += 1
            self._log_error(f"保存Agent记忆失败 [{memory_entry.id}]: {e}", exc_info=True)
            raise ModuleError(f"保存Agent记忆失败: {e}")
    
    async def get_memory(self, memory_id: str, agent_id: Optional[str] = None) -> Optional[MemoryEntry]:
        """获取Agent记忆 - V3.0 仅使用 MemoryManager"""
        start_time = self._track_operation_start()

        try:
            if agent_id:
                cache_key = f"{agent_id}:{memory_id}"
                if cache_key in self._recent_memories_cache:
                    cached_entry = self._recent_memories_cache[cache_key]
                    cached_entry.metadata.mark_accessed()
                    elapsed_time = self._track_operation_end(start_time)
                    logger.debug(f"从缓存获取Agent记忆 [{memory_id}] (命中, 耗时: {elapsed_time:.2f}ms)")
                    return cached_entry

            if not agent_id:
                if memory_id.startswith("agent_"):
                    parts = memory_id.split('_')
                    if len(parts) >= 3:
                        agent_id = parts[1]

            if not agent_id:
                logger.warning(f"无法确定Agent ID来查找记忆 [{memory_id}]")
                return None

            memory_manager = self._get_memory_manager(agent_id)
            # 通过搜索查找记忆（MemoryManager 无 get_memory 方法）
            all_results = memory_manager.search_memory(query=memory_id, scope="long_term", limit=1)
            data = all_results[0] if all_results else None
            if data:
                from ..types import MemoryMetadata
                metadata = MemoryMetadata(
                    created_at=datetime.now(),
                    accessed_at=datetime.now(),
                    access_count=1
                )
                memory_entry = MemoryEntry(
                    id=memory_id,
                    content=str(data),
                    memory_type=MemoryType.AGENT_PRIVATE,
                    category=MemoryCategory.GENERAL,
                    agent_id=agent_id,
                    metadata=metadata
                )
                cache_key = f"{agent_id}:{memory_id}"
                self._recent_memories_cache[cache_key] = memory_entry
                elapsed_time = self._track_operation_end(start_time)
                logger.debug(f"获取Agent记忆 [{memory_id}] (耗时: {elapsed_time:.2f}ms)")
                return memory_entry

            logger.debug(f"未找到Agent记忆 [{memory_id}]")
            return None

        except PermissionDeniedError as e:
            self.stats.total_errors += 1
            self._track_operation_end(start_time)
            raise
        except Exception as e:
            self.stats.total_errors += 1
            self._track_operation_end(start_time)
            self._log_error(f"获取Agent记忆失败 [{memory_id}]: {e}", exc_info=True)
            return None
    
    def _check_shared_permission(self, requesting_agent_id: str, target_agent_id: str) -> bool:
        """检查共享记忆权限"""
        # 简化实现：允许访问共享记忆
        # 实际项目中应该实现更复杂的权限控制
        return True
    
    async def get_relevant_memories(
        self,
        agent_id: Optional[str] = None,
        time_range: Optional[TimeRange] = None,
        limit: int = 20,
        user_id: Optional[str] = None
    ) -> List[MemoryEntry]:
        """获取相关Agent记忆"""
        start_time = self._track_operation_start()
        
        try:
            memories = []
            
            if not agent_id:
                # 如果没有指定Agent，返回空列表
                elapsed_time = self._track_operation_end(start_time)
                logger.debug(f"获取相关Agent记忆: 无Agent ID, 返回空列表 (耗时: {elapsed_time:.2f}ms)")
                return memories
            
            # 默认获取最近7天的记忆
            if time_range is None:
                end_date = datetime.now()
                start_date = end_date - timedelta(days=7)
                time_range = TimeRange(start=start_date, end=end_date)
            
            # 从 MemoryManager 获取长期记忆
            try:
                memory_manager = self._get_memory_manager(agent_id, user_id)
                long_term = memory_manager.get_long_term()
                for category in ["patterns", "lessons", "facts"]:
                    entries = long_term.get(category, [])
                    for entry in entries:
                        from ..types import MemoryMetadata
                        content = entry.get("content", "")
                        if not content:
                            continue
                        content_hash = hashlib.md5(content.encode()).hexdigest()
                        memory_id = f"agent_{agent_id}_{content_hash[:12]}"
                        metadata = MemoryMetadata(
                            created_at=datetime.now(),
                            accessed_at=datetime.now(),
                            access_count=1
                        )
                        memory_entry = MemoryEntry(
                            id=memory_id,
                            content=content,
                            memory_type=MemoryType.AGENT_PRIVATE,
                            category=MemoryCategory.GENERAL,
                            agent_id=agent_id,
                            metadata=metadata
                        )
                        memories.append(memory_entry)
            except Exception as e:
                logger.debug(f"从 MemoryManager 获取相关记忆失败: {e}")
            
            # 按时间排序（最新的在前）
            memories.sort(key=lambda m: m.metadata.created_at, reverse=True)
            
            # 限制数量
            memories = memories[:limit]
            
            elapsed_time = self._track_operation_end(start_time)
            logger.debug(f"获取相关Agent记忆: agent_id={agent_id}, 找到 {len(memories)} 条 (耗时: {elapsed_time:.2f}ms)")
            
            return memories
            
        except Exception as e:
            self.stats.total_errors += 1
            elapsed_time = self._track_operation_end(start_time)
            self._log_error(f"获取相关Agent记忆失败: {e}", exc_info=True)
            return []
    
    async def search_memories(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 10
    ) -> List[MemoryEntry]:
        """搜索Agent记忆"""
        start_time = self._track_operation_start()
        
        try:
            # 获取相关记忆用于搜索
            all_memories = await self.get_relevant_memories(
                agent_id=agent_id,
                time_range=None,  # 不限制时间范围
                limit=100  # 获取足够多用于搜索
            )
            
            # 简单的内容过滤
            query_lower = query.lower()
            matching_memories = [
                mem for mem in all_memories
                if query_lower in mem.content.lower()
            ]
            
            # 按时间排序（最新的在前）
            matching_memories.sort(key=lambda m: m.metadata.created_at, reverse=True)
            
            # 限制数量
            matching_memories = matching_memories[:limit]
            
            elapsed_time = self._track_operation_end(start_time)
            logger.info(f"搜索Agent记忆: agent_id={agent_id}, '{query}' -> 找到 {len(matching_memories)} 条 (耗时: {elapsed_time:.2f}ms)")
            
            return matching_memories
            
        except Exception as e:
            self.stats.total_errors += 1
            elapsed_time = self._track_operation_end(start_time)
            self._log_error(f"搜索Agent记忆失败: {e}", exc_info=True)
            return []
    
    async def delete_memory(self, memory_id: str, agent_id: Optional[str] = None) -> bool:
        """删除Agent记忆"""
        # 注意：现有的记忆管理器可能不支持删除
        # 这里主要从缓存中删除
        
        # 从缓存中删除
        if agent_id:
            cache_key = f"{agent_id}:{memory_id}"
            if cache_key in self._recent_memories_cache:
                del self._recent_memories_cache[cache_key]
        
        logger.warning(f"Agent记忆删除受限 [{memory_id}]: 现有的记忆管理器可能不支持删除")
        return False
    
    def get_memory_stats(self) -> MemoryStats:
        """获取Agent记忆统计信息"""
        stats = MemoryStats()
        
        try:
            # 简化实现：统计Agent目录
            if self.storage_base_path.exists():
                agent_dirs = [d for d in self.storage_base_path.iterdir() if d.is_dir()]
                stats.total_memories = len(agent_dirs) * 10  # 估算值
                
                # 计算总大小
                total_size = 0
                for agent_dir in agent_dirs:
                    # 检查Markdown文件
                    memory_dir = agent_dir / "memory"
                    if memory_dir.exists():
                        for md_file in memory_dir.glob("*.md"):
                            if md_file.exists():
                                total_size += md_file.stat().st_size
                    
                    # 检查长期记忆文件
                    long_term_file = agent_dir / "memory.json"
                    if long_term_file.exists():
                        total_size += long_term_file.stat().st_size
                
                stats.total_size_bytes = total_size
            
            stats.by_type = {
                MemoryType.AGENT_PRIVATE.value: stats.total_memories,
                MemoryType.AGENT_SHARED.value: 0  # 简化估算
            }
            
        except Exception as e:
            self._log_error(f"获取Agent记忆统计失败: {e}")
        
        return stats
    
    def _ensure_path_exists(self, path: Path) -> None:
        """确保路径存在"""
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            self._log_debug(f"创建目录: {path}")