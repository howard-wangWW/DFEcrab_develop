"""
统一记忆管理器 - V3.0 简化版

提供一致的API来访问记忆系统：
- Agent私有记忆 (每个智能体的长期经验)
- 全局共享记忆 (所有智能体共享的领域知识)

简化设计：只保留核心功能，去除四层优先级/每日日志/传统模块。
向后兼容：通过 get_memory_manager() 桥接到 MemoryManager。
"""

import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import uuid

from src.utils.logger import get_logger

from .types import (
    MemoryType, MemoryCategory, MemoryPriority,
    MemoryEntry, SearchResult, ContextBundle, TimeRange,
    MemoryStats, MemoryConfig as UnifiedMemoryConfig
)
from .modules import AgentMemoryModule, GlobalMemoryModule

logger = get_logger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    memory_entry: MemoryEntry
    timestamp: float
    access_count: int = 0


class UnifiedMemoryManager:
    """
    统一记忆管理器
    
    所有记忆操作的统一入口点，提供一致的API访问各种记忆系统。
    内部使用模块化架构，每个模块负责特定类型的记忆操作。
    """
    
    def __init__(self, config: Optional[UnifiedMemoryConfig] = None):
        """
        初始化统一记忆管理器
        
        Args:
            config: 记忆系统配置，如果为None则使用默认配置
        """
        self.config = config or UnifiedMemoryConfig()
        self.config.validate()
        
        # 初始化模块
        self.modules: Dict[MemoryType, Any] = {}
        self._initialize_modules()
        
        # 初始化存储适配器（V3.0 后不再使用，仅保留占位，避免引用未导入类型）
        self.storage_adapters: Dict[str, Any] = {}
        self._initialize_storage()
        
        # 初始化搜索系统（V3.0 后不加载搜索引擎，避免引用未导入类型）
        self.search_engine: Optional[Any] = None
        self._initialize_search()
        
        # 缓存系统（内存缓存）
        self.memory_cache: Dict[str, CacheEntry] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        
        # 统计信息
        self.stats = MemoryStats()
        self._last_stats_update = time.time()
        
        # 兼容性桥接（用于向后兼容）
        self._compatibility_bridges: Dict[str, Any] = {}
        
        logger.info(f"统一记忆管理器已初始化 (配置: {self.config})")
    
    def _initialize_modules(self) -> None:
        """初始化功能模块 - V3.0 只保留 Agent + Global"""
        from .modules.agent_module import AgentMemoryModule
        from .modules.global_module import GlobalMemoryModule

        agent_config = self._get_module_config("agent")
        self.modules[MemoryType.AGENT_PRIVATE] = AgentMemoryModule(
            config=agent_config, unified_manager=self
        )
        self.modules[MemoryType.AGENT_SHARED] = self.modules[MemoryType.AGENT_PRIVATE]

        global_config = self._get_module_config("global")
        self.modules[MemoryType.GLOBAL] = GlobalMemoryModule(
            config=global_config, unified_manager=self
        )

        logger.info(f"已初始化 {len(self.modules)} 个记忆模块 (Agent + Global)")
    
    def _get_module_config(self, module_type: str) -> Dict[str, Any]:
        """获取模块配置"""
        # TODO: 从全局配置中读取模块特定配置
        # 每日记忆模块使用 shared_memory 路径以保持兼容性
        if module_type == "daily":
            storage_base_path = self.config.storage_base_path.parent / "shared_memory"
        else:
            storage_base_path = self.config.storage_base_path / module_type
        
        return {
            "storage_base_path": storage_base_path,
            "enable_cache": self.config.enable_memory_cache,
            "logger": logger
        }
    
    def _initialize_storage(self) -> None:
        """初始化存储适配器 - V3.0 简化版

        V3.0 后记忆写入直接走 long_term.MemoryManager / GlobalMemoryManager，
        storage 适配器仅作统计占位且从未被使用，不再初始化，
        避免每次实例化都生成 data/memory/filesystem、data/memory/metadata 空目录。
        """
        self.storage_adapters = {}
    
    def _initialize_search(self) -> None:
        """初始化搜索系统

        启用关键词检索引擎（BM25），按用户隔离检索用户记忆 / Agent 经验 / 每日日志。
        """
        from .search.keyword_search import MemorySearchEngine
        self.search_engine = MemorySearchEngine()
        logger.info(f"已初始化记忆检索引擎: {self.search_engine.__class__.__name__}")
    
    def _generate_memory_id(self) -> str:
        """生成唯一的记忆ID"""
        timestamp = int(time.time() * 1000)
        random_part = uuid.uuid4().hex[:8]
        return f"memory_{timestamp}_{random_part}"
    
    def _get_cache_key(self, memory_id: str, agent_id: Optional[str] = None) -> str:
        """生成缓存键"""
        if agent_id:
            return f"{agent_id}:{memory_id}"
        return memory_id
    
    def _update_stats(self) -> None:
        """更新统计信息"""
        current_time = time.time()
        if current_time - self._last_stats_update < self.config.stats_update_interval_seconds:
            return
        
        try:
            # 收集各模块的统计信息
            total_memories = 0
            by_type = {}
            
            for mem_type, module in self.modules.items():
                stats = module.get_stats()
                total_memories += stats.get("count", 0)
                by_type[mem_type.value] = stats.get("count", 0)
            
            self.stats.total_memories = total_memories
            self.stats.by_type = by_type
            self.stats.total_size_bytes = self._calculate_total_size()
            self._last_stats_update = current_time
            
            logger.debug(f"统计信息已更新: {self.stats}")
            
        except Exception as e:
            logger.error(f"更新统计信息时出错: {e}")
    
    def _calculate_total_size(self) -> int:
        """计算总存储大小"""
        total_size = 0
        for adapter_name, adapter in self.storage_adapters.items():
            try:
                adapter_stats = adapter.get_stats()
                total_size += adapter_stats.get("size_bytes", 0)
            except Exception as e:
                logger.warning(f"获取适配器 {adapter_name} 统计信息失败: {e}")
        
        return total_size
    
    # ==================== 公共 API 方法 ====================
    
    async def add_memory(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.AGENT_PRIVATE,
        agent_id: Optional[str] = None,
        category: MemoryCategory = MemoryCategory.GENERAL,
        metadata: Optional[Dict[str, Any]] = None,
        priority: MemoryPriority = MemoryPriority.NORMAL,
        user_id: Optional[str] = None
    ) -> str:
        """
        添加新的记忆
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型
            agent_id: 归属的Agent ID
            category: 内容分类
            metadata: 额外的元数据
            priority: 记忆优先级
            user_id: 用户 ID，提供后 Agent 私有记忆按用户隔离存储
            
        Returns:
            memory_id: 新创建的记忆ID
        """
        try:
            start_time = time.time()
            
            # 生成记忆ID
            memory_id = self._generate_memory_id()
            
            # 创建记忆条目
            memory_entry = MemoryEntry(
                id=memory_id,
                content=content,
                memory_type=memory_type,
                category=category,
                agent_id=agent_id,
                priority=priority
            )
            
            # 添加额外的元数据
            if metadata:
                memory_entry.metadata.custom_fields.update(metadata)
            
            # 获取对应的模块
            module = self.modules.get(memory_type)
            if not module:
                raise ValueError(f"不支持的记忆类型: {memory_type}")
            
            # 调用模块的保存方法
            saved_entry = await module.save_memory(memory_entry, user_id=user_id)
            
            # 更新缓存
            if self.config.enable_memory_cache:
                cache_key = self._get_cache_key(memory_id, agent_id)
                self.memory_cache[cache_key] = CacheEntry(
                    memory_entry=saved_entry,
                    timestamp=time.time()
                )
            
            # 触发索引更新（异步，防御：引擎可能未实现 index_memory）
            if self.search_engine and hasattr(self.search_engine, "index_memory"):
                try:
                    asyncio.create_task(self.search_engine.index_memory(saved_entry))
                except Exception as _idx_e:
                    logger.debug(f"触发记忆索引失败（不影响写入）: {_idx_e}")
            
            elapsed_time = (time.time() - start_time) * 1000
            logger.info(f"已添加记忆 [{memory_id}] (类型: {memory_type.value}, 耗时: {elapsed_time:.2f}ms)")
            
            return memory_id
            
        except Exception as e:
            logger.error(f"添加记忆失败: {e}", exc_info=True)
            raise
    
    async def get_memory(
        self,
        memory_id: str,
        agent_id: Optional[str] = None,
        include_related: bool = False
    ) -> MemoryEntry:
        """
        获取记忆
        
        Args:
            memory_id: 记忆ID
            agent_id: Agent ID（用于权限检查）
            include_related: 是否包含相关记忆
            
        Returns:
            MemoryEntry: 记忆条目
        """
        try:
            start_time = time.time()
            
            # 首先检查缓存
            cache_key = self._get_cache_key(memory_id, agent_id)
            if self.config.enable_memory_cache and cache_key in self.memory_cache:
                cache_entry = self.memory_cache[cache_key]
                cache_entry.access_count += 1
                self.cache_hits += 1
                
                elapsed_time = (time.time() - start_time) * 1000
                logger.debug(f"从缓存获取记忆 [{memory_id}] (命中, 耗时: {elapsed_time:.2f}ms)")
                return cache_entry.memory_entry
            
            self.cache_misses += 1
            
            # 从所有模块中查找记忆
            memory_entry = None
            for module in self.modules.values():
                try:
                    entry = await module.get_memory(memory_id, agent_id=agent_id)
                    if entry:
                        memory_entry = entry
                        break
                except Exception as e:
                    logger.debug(f"模块 {module.__class__.__name__} 查找记忆失败: {e}")
                    continue
            
            if not memory_entry:
                raise ValueError(f"未找到记忆: {memory_id}")
            
            # 标记访问
            memory_entry.metadata.mark_accessed()
            
            # 更新缓存
            if self.config.enable_memory_cache:
                self.memory_cache[cache_key] = CacheEntry(
                    memory_entry=memory_entry,
                    timestamp=time.time(),
                    access_count=1
                )
                # 如果缓存太大，清理最旧的条目
                if len(self.memory_cache) > self.config.memory_cache_size:
                    self._cleanup_cache()
            
            elapsed_time = (time.time() - start_time) * 1000
            logger.debug(f"从存储获取记忆 [{memory_id}] (未命中, 耗时: {elapsed_time:.2f}ms)")
            
            return memory_entry
            
        except Exception as e:
            logger.error(f"获取记忆失败 [{memory_id}]: {e}", exc_info=True)
            raise
    
    async def search_memory(
        self,
        query: str,
        user_id: Optional[str] = None,
        scope: str = "all",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索记忆（BM25，按用户隔离）

        Args:
            query: 搜索查询
            user_id: 用户 ID
            scope: 检索范围 all | user_memory | agent_memory | daily
            limit: 返回条数

        Returns:
            [{score, source, doc_id, title, content}]
        """
        try:
            if not self.search_engine:
                return []
            results = self.search_engine.search(
                query=query, user_id=user_id, scope=scope, limit=limit)
            logger.info(f"搜索完成: '{query}' -> 找到 {len(results)} 个结果 (scope={scope})")
            return results
        except Exception as e:
            logger.error(f"搜索记忆失败: {e}", exc_info=True)
            return []
    
    async def get_context(
        self,
        agent_id: Optional[str] = None,
        include_types: Optional[List[MemoryType]] = None,
        time_range: Optional[TimeRange] = None,
        max_memories: int = 20,
        user_id: Optional[str] = None
    ) -> ContextBundle:
        """
        获取上下文数据包
        
        Args:
            agent_id: Agent ID
            include_types: 包含的记忆类型列表
            time_range: 时间范围限制
            max_memories: 最大记忆数量
            user_id: 用户 ID，提供后只检索该用户的 Agent 私有记忆
            
        Returns:
            ContextBundle: 上下文数据包
        """
        try:
            start_time = time.time()
            
            # 收集符合条件的记忆
            memories: List[MemoryEntry] = []
            
            # 确定要搜索的记忆类型 - V3.0 只保留 Agent + Global
            if include_types is None:
                include_types = [
                    MemoryType.AGENT_PRIVATE,
                    MemoryType.AGENT_SHARED,
                    MemoryType.GLOBAL
                ]
            
            # 从每个模块收集记忆
            for mem_type in include_types:
                module = self.modules.get(mem_type)
                if not module:
                    continue
                
                try:
                    module_memories = await module.get_relevant_memories(
                        agent_id=agent_id,
                        user_id=user_id,
                        time_range=time_range,
                        limit=max_memories // len(include_types)
                    )
                    memories.extend(module_memories)
                except Exception as e:
                    logger.warning(f"模块 {mem_type.value} 获取相关记忆失败: {e}")
            
            # 按时间排序（最新的在前）
            memories.sort(key=lambda m: m.metadata.created_at, reverse=True)
            
            # 限制数量
            memories = memories[:max_memories]
            
            # 生成摘要
            summary = self._generate_context_summary(memories)
            
            bundle = ContextBundle(
                memories=memories,
                summary=summary,
                timestamp=datetime.now()
            )
            
            elapsed_time = (time.time() - start_time) * 1000
            logger.debug(f"生成上下文: {len(memories)} 个记忆 (耗时: {elapsed_time:.2f}ms)")
            
            return bundle
            
        except Exception as e:
            logger.error(f"获取上下文失败: {e}", exc_info=True)
            return ContextBundle()
    
    async def get_user_profile(self, user_id: str = "default") -> str:
        """获取用户画像文本（供 Manager system_prompt 注入）

        从全局记忆中提取用户相关信息（常驻地、偏好、历史任务），
        格式化为简短文本注入到 Manager 的 system_prompt。

        Args:
            user_id: 用户 ID

        Returns:
            str: 用户画像文本，如 "常驻地: 昆明; 偏好: 简洁回复; 历史任务: 查天气、跳闸统计"
                 无记忆时返回 "（暂无用户画像）"
        """
        try:
            # 优先读取用户级记忆（data/memory/users/{user_id}/memories.json 的结构化 KV）
            try:
                from src.memory.user_manager import UserMemoryManager
                user_memories = UserMemoryManager.list_memories(user_id)
                if user_memories:
                    parts = []
                    for m in user_memories:
                        key = (m.get("key") or "").strip()
                        content = (m.get("content") or "").strip()
                        if key and content:
                            parts.append(f"{key}: {content}")
                    if parts:
                        profile_text = "; ".join(parts)
                        logger.debug(f"[Memory] 用户画像（用户级记忆）: {profile_text[:100]}")
                        return profile_text
            except Exception as e:
                logger.debug(f"[Memory] 读取用户级记忆失败（降级）: {e}")

            # 降级：从全局记忆获取用户相关记忆
            context_bundle = await self.get_context(
                agent_id=None,  # 全局记忆
                include_types=[MemoryType.GLOBAL],
                max_memories=20
            )

            if not context_bundle.memories:
                return "（暂无用户画像）"

            # 提取关键信息
            locations = []
            preferences = []
            recent_tasks = []

            for mem in context_bundle.memories[:20]:
                content = mem.content.lower()
                # 提取常驻地（简单关键词匹配）
                if "常驻地" in content or "城市" in content or "所在地" in content:
                    for city in ["烟台", "昆明", "北京", "上海", "广州", "深圳"]:
                        if city in content:
                            if city not in locations:
                                locations.append(city)
                # 提取历史任务
                if "用户消息" in content or "会话" in content:
                    # 截取前30字作为任务摘要
                    task_summary = mem.content[:30].replace("\n", " ").strip()
                    if task_summary and task_summary not in recent_tasks:
                        recent_tasks.append(task_summary)

            parts = []
            if locations:
                parts.append(f"常驻地: {', '.join(locations[:2])}")
            if recent_tasks:
                parts.append(f"近期任务: {'; '.join(recent_tasks[-3:])}")

            if not parts:
                return "（暂无用户画像）"

            profile_text = "; ".join(parts)
            logger.debug(f"[Memory] 用户画像: {profile_text[:100]}")
            return profile_text

        except Exception as e:
            logger.warning(f"[Memory] 获取用户画像失败（降级）: {e}")
            return "（暂无用户画像）"

    async def build_context_text(
        self,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """构建对话注入的三段式记忆上下文（用户画像 + 相关经验 + 近期日志）

        Args:
            agent_id: 当前 Agent ID
            user_id: 用户 ID

        Returns:
            格式化记忆上下文文本；无记忆时返回空字符串
        """
        parts: List[str] = []

        # 1. 用户画像（用户级记忆 KV）
        if user_id:
            try:
                from src.memory.user_manager import UserMemoryManager
                user_mems = UserMemoryManager.list_memories(user_id)
                if user_mems:
                    kv = "; ".join(
                        f"{m.get('key')}: {m.get('content')}"
                        for m in user_mems[:3] if m.get('key') and m.get('content')
                    )
                    if kv:
                        parts.append(f"[用户画像] {kv}")
            except Exception as e:
                logger.debug(f"[Memory] 加载用户画像失败: {e}")

        # 2. 相关经验（Agent 长期记忆）
        if agent_id:
            try:
                from src.memory.long_term import MemoryManager
                mm = MemoryManager(agent_id=agent_id, user_id=user_id)
                lt = mm.long_term_memory.get("long_term", {}) or {}
                exp_parts: List[str] = []

                # ★ 反思闭环修复（重要）：
                #   MemoryManager.add_to_long_term 是 list.append（见 long_term.py:274），
                #   所以列表**末尾才是最新的**经验。原实现取 [:2] / [:1] 会永远读到
                #   「最早写入的那条」，导致 Reflector 后续积累的教训从未真正注入 prompt，
                #   反思闭环形同虚设。这里改为取「最近若干条」，并按新→旧排序。
                _MAX_PATTERN = 2      # 注入的成功模式条数
                _MAX_LESSON = 3       # 注入的经验教训条数
                _SNIPPET = 200        # 单条摘要截断长度（原 80 会把一句话教训截碎）

                recent_patterns = list(lt.get("patterns") or [])[-_MAX_PATTERN:]
                for p in reversed(recent_patterns):
                    c = p.get("content", "") if isinstance(p, dict) else str(p)
                    if c:
                        exp_parts.append(c[:_SNIPPET])

                recent_lessons = list(lt.get("lessons") or [])[-_MAX_LESSON:]
                for l in reversed(recent_lessons):
                    c = l.get("content", "") if isinstance(l, dict) else str(l)
                    if c:
                        exp_parts.append(f"[教训] {c[:_SNIPPET]}")

                if exp_parts:
                    parts.append("[相关经验] " + "; ".join(exp_parts))
            except Exception as e:
                logger.debug(f"[Memory] 加载相关经验失败: {e}")

        # 3. 近期日志（最近 1 天 DAILY 摘要）
        if user_id:
            try:
                from src.memory.global_manager import get_global_memory_manager
                daily = get_global_memory_manager().load_recent_daily(1, user_id)
                if daily:
                    parts.append(f"[近期日志] {daily[:80]}")
            except Exception as e:
                logger.debug(f"[Memory] 加载近期日志失败: {e}")

        return "\n".join(parts)

    def _generate_context_summary(self, memories: List[MemoryEntry]) -> str:
        """生成上下文摘要"""
        if not memories:
            return "暂无相关记忆。"
        
        # 按类型统计
        type_counts = {}
        category_counts = {}
        
        for mem in memories:
            type_counts[mem.memory_type.value] = type_counts.get(mem.memory_type.value, 0) + 1
            category_counts[mem.category.value] = category_counts.get(mem.category.value, 0) + 1
        
        # 构建摘要
        summary_parts = [f"共找到 {len(memories)} 条相关记忆："]
        
        if type_counts:
            type_str = ", ".join([f"{k}({v})" for k, v in type_counts.items()])
            summary_parts.append(f"记忆类型分布: {type_str}")
        
        if category_counts:
            category_str = ", ".join([f"{k}({v})" for k, v in category_counts.items()])
            summary_parts.append(f"内容分类: {category_str}")
        
        # 添加时间范围信息
        if len(memories) >= 2:
            oldest = min(m.metadata.created_at for m in memories)
            newest = max(m.metadata.created_at for m in memories)
            time_span = newest - oldest
            days = time_span.days
            hours = time_span.seconds // 3600
            
            time_str_parts = []
            if days > 0:
                time_str_parts.append(f"{days}天")
            if hours > 0:
                time_str_parts.append(f"{hours}小时")
            
            if time_str_parts:
                summary_parts.append(f"时间跨度: {''.join(time_str_parts)}")
        
        return " | ".join(summary_parts)
    
    # ==================== 管理方法 ====================
    
    async def get_stats(self) -> MemoryStats:
        """
        获取记忆系统统计信息
        
        Returns:
            MemoryStats: 统计信息
        """
        self._update_stats()
        
        # 添加缓存命中率
        total_requests = self.cache_hits + self.cache_misses
        if total_requests > 0:
            hit_rate = self.cache_hits / total_requests * 100
            self.stats.average_retrieval_time_ms = 0  # TODO: 计算实际平均时间
        
        return self.stats
    
    def _cleanup_cache(self) -> None:
        """清理缓存（删除最旧的条目）"""
        if not self.memory_cache:
            return
        
        # 按访问时间和频率排序
        cache_entries = sorted(
            self.memory_cache.items(),
            key=lambda x: (x[1].timestamp, -x[1].access_count)
        )
        
        # 删除最旧的20%条目
        remove_count = max(1, len(cache_entries) // 5)
        for i in range(remove_count):
            key, _ = cache_entries[i]
            del self.memory_cache[key]
        
        logger.debug(f"清理缓存: 移除了 {remove_count} 个条目")
    
    async def migrate_legacy_data(self) -> Dict[str, Any]:
        """
        迁移旧系统的数据到新系统
        
        Returns:
            Dict[str, Any]: 迁移报告
        """
        logger.info("开始迁移旧系统数据...")
        report = {
            "total_migrated": 0,
            "failed": 0,
            "migrated_types": [],
            "details": [],
            "start_time": datetime.now().isoformat()
        }
        
        try:
            # 迁移每日记忆（data/shared_memory/DAILY/*.md）
            daily_path = Path("data/shared_memory/DAILY")
            if daily_path.exists() and daily_path.is_dir():
                for file_path in daily_path.glob("*.md"):
                    try:
                        # 从文件名解析日期
                        date_str = file_path.stem
                        content = file_path.read_text(encoding="utf-8").strip()
                        if not content:
                            continue
                        
                        # 检查是否已存在该日期的记忆
                        # 简单检查：如果内容包含日期标记，则可能已迁移
                        # 此处简化处理，直接创建新记忆
                        memory_id = await self.add_memory(
                            content=content,
                            memory_type=MemoryType.DAILY,
                            category=MemoryCategory.GENERAL,
                            priority=MemoryPriority.NORMAL
                        )
                        report["details"].append({
                            "file": str(file_path),
                            "memory_id": memory_id,
                            "type": "daily",
                            "status": "success"
                        })
                        report["total_migrated"] += 1
                        logger.debug(f"迁移每日记忆文件: {file_path.name} -> {memory_id}")
                    except Exception as e:
                        logger.error(f"迁移文件失败 {file_path}: {e}")
                        report["failed"] += 1
                        report["details"].append({
                            "file": str(file_path),
                            "error": str(e),
                            "status": "failed"
                        })
                
                if report["total_migrated"] > 0:
                    report["migrated_types"].append("daily")
            
            # 迁移Agent私有记忆（data/memory/agents/*/*.md）
            agents_path = Path("data/memory/agents")
            if agents_path.exists() and agents_path.is_dir():
                for agent_dir in agents_path.iterdir():
                    if agent_dir.is_dir():
                        agent_id = agent_dir.name
                        for file_path in agent_dir.glob("*.md"):
                            try:
                                content = file_path.read_text(encoding="utf-8").strip()
                                if not content:
                                    continue
                                
                                memory_id = await self.add_memory(
                                    content=content,
                                    memory_type=MemoryType.AGENT_PRIVATE,
                                    agent_id=agent_id,
                                    category=MemoryCategory.CONVERSATION,
                                    priority=MemoryPriority.NORMAL
                                )
                                report["details"].append({
                                    "file": str(file_path),
                                    "memory_id": memory_id,
                                    "type": "agent_private",
                                    "agent_id": agent_id,
                                    "status": "success"
                                })
                                report["total_migrated"] += 1
                            except Exception as e:
                                logger.error(f"迁移Agent记忆失败 {file_path}: {e}")
                                report["failed"] += 1
                                report["details"].append({
                                    "file": str(file_path),
                                    "error": str(e),
                                    "status": "failed"
                                })
                
                if report["total_migrated"] > 0:
                    report["migrated_types"].append("agent_private")
            
            logger.info(f"数据迁移完成: 成功 {report['total_migrated']} 条, 失败 {report['failed']} 条")
            report["end_time"] = datetime.now().isoformat()
            report["success"] = report["failed"] == 0
            return report
            
        except Exception as e:
            logger.error(f"数据迁移过程失败: {e}", exc_info=True)
            report["error"] = str(e)
            report["end_time"] = datetime.now().isoformat()
            report["success"] = False
            return report
    
    async def cleanup_expired(self, days: int = 30) -> Dict[str, Any]:
        """
        清理过期记忆
        
        Args:
            days: 过期天数阈值（早于该天数的记忆将被清理）
            
        Returns:
            Dict[str, Any]: 清理报告
        """
        logger.info(f"开始清理过期记忆（超过 {days} 天）...")
        report = {
            "total_checked": 0,
            "cleaned": 0,
            "skipped": 0,
            "details": [],
            "start_time": datetime.now().isoformat()
        }
        
        try:
            threshold_date = datetime.now() - timedelta(days=days)
            
            # 遍历所有记忆条目（通过搜索引擎的内存映射获取已索引的记忆）
            # 注意：这只清理了已索引的记忆，未索引的记忆可能不会被清理
            # 实际部署中需要更全面的清理策略
            if self.search_engine and hasattr(self.search_engine, '_memory_map'):
                memory_map = self.search_engine._memory_map
                for memory_id, entry in memory_map.items():
                    report["total_checked"] += 1
                    
                    # 检查记忆是否过期且为低优先级
                    is_expired = entry.metadata.created_at < threshold_date
                    is_low_priority = entry.priority in [MemoryPriority.LOW, MemoryPriority.TEMPORARY]
                    
                    if is_expired and is_low_priority:
                        try:
                            # 从搜索引擎中移除（如果需要）
                            if hasattr(self.search_engine, 'remove_from_index'):
                                await self.search_engine.remove_from_index(memory_id)
                            
                            # 从对应模块中删除记忆
                            module = self.modules.get(entry.memory_type)
                            if module and hasattr(module, 'delete_memory'):
                                await module.delete_memory(memory_id, entry.agent_id)
                            
                            # 从缓存中移除
                            if self.config.enable_memory_cache:
                                cache_key = self._get_cache_key(memory_id, entry.agent_id)
                                if cache_key in self.memory_cache:
                                    del self.memory_cache[cache_key]
                            
                            report["cleaned"] += 1
                            report["details"].append({
                                "memory_id": memory_id,
                                "type": entry.memory_type.value,
                                "agent_id": entry.agent_id,
                                "reason": f"过期且低优先级 (创建于 {entry.metadata.created_at})",
                                "status": "cleaned"
                            })
                            logger.debug(f"清理过期记忆: {memory_id}")
                        except Exception as e:
                            logger.error(f"清理记忆失败 {memory_id}: {e}")
                            report["skipped"] += 1
                            report["details"].append({
                                "memory_id": memory_id,
                                "error": str(e),
                                "status": "failed"
                            })
                    else:
                        report["skipped"] += 1
            
            logger.info(f"记忆清理完成: 检查 {report['total_checked']} 条, 清理 {report['cleaned']} 条, 跳过 {report['skipped']} 条")
            report["end_time"] = datetime.now().isoformat()
            report["success"] = True
            return report
            
        except Exception as e:
            logger.error(f"记忆清理过程失败: {e}", exc_info=True)
            report["error"] = str(e)
            report["end_time"] = datetime.now().isoformat()
            report["success"] = False
            return report
    
    # ==================== 向后兼容方法 ====================
    
    def get_global_memory_manager(self):
        """获取全局记忆管理器实例（向后兼容）"""
        from .global_manager import get_global_memory_manager
        return get_global_memory_manager()

    def get_memory_manager(self):
        """获取MemoryManager实例（向后兼容）"""
        if "legacy" not in self._compatibility_bridges:
            from src.memory.long_term import MemoryManager
            self._compatibility_bridges["legacy"] = MemoryManager()

        return self._compatibility_bridges["legacy"]


# ──────────────────────────────────────────────────────────────
# 进程级单例（C-1）：ReAct / Reflector / 网关 / API 共享同一实例
# ──────────────────────────────────────────────────────────────

_UNIFIED_SINGLETON: Optional["UnifiedMemoryManager"] = None
_UNIFIED_LOCK: "threading.Lock" = None


def _get_unified_lock() -> "threading.Lock":
    global _UNIFIED_LOCK
    if _UNIFIED_LOCK is None:
        import threading
        _UNIFIED_LOCK = threading.Lock()
    return _UNIFIED_LOCK


def get_unified_manager() -> "UnifiedMemoryManager":
    """获取进程级统一记忆管理器单例（C-1）。

    安全性：本实例所有读写方法均显式传 agent_id / user_id（如
    build_context_text(agent_id=..., user_id=...)），内部 AgentMemoryModule 按
    (agent_id, user_id) 缓存各自 MemoryManager —— 共享实例不会产生数据串扰。

    替代各调用点直接 ``UnifiedMemoryManager()`` 的写法，避免一次请求内
    重复初始化记忆模块与检索引擎（日志实证：一次请求初始化 ×2、长期记忆加载 ×3）。
    """
    global _UNIFIED_SINGLETON
    if _UNIFIED_SINGLETON is None:
        with _get_unified_lock():
            if _UNIFIED_SINGLETON is None:
                _UNIFIED_SINGLETON = UnifiedMemoryManager()
    return _UNIFIED_SINGLETON