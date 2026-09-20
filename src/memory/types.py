"""
统一记忆管理器的类型定义和枚举

提供所有记忆相关的数据类型、枚举和配置类。
"""

from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from pathlib import Path


class MemoryType(Enum):
    """
    记忆类型枚举
    
    定义系统中所有支持的记忆类型，用于区分不同的记忆存储和用途。
    """
    DAILY = "daily"           # 每日记忆（按时间聚合，HierarchicalMemoryManager）
    AGENT_PRIVATE = "agent_private"  # Agent私有记忆（Markdown格式）
    AGENT_SHARED = "agent_shared"    # Agent共享记忆（其他Agent可见）
    GLOBAL = "global"         # 全局共享记忆（所有Agent可见）
    TEMPORARY = "temporary"   # 临时缓存记忆（会话级）
    LEGACY_PERMANENT = "legacy_permanent"     # 传统系统：永久记忆
    LEGACY_LONG_TERM = "legacy_long_term"     # 传统系统：长期记忆
    LEGACY_SHORT_TERM = "legacy_short_term"   # 传统系统：短期记忆


class MemoryCategory(Enum):
    """
    记忆内容分类
    
    用于对记忆内容进行分类，便于检索和组织。
    """
    GENERAL = "general"       # 一般信息
    CONVERSATION = "conversation"    # 对话记录
    TASK_PROGRESS = "task_progress"  # 任务进度
    ERROR_LOG = "error_log"          # 错误日志
    CONFIG_CHANGE = "config_change"  # 配置变更
    SYSTEM_EVENT = "system_event"    # 系统事件
    USER_FEEDBACK = "user_feedback"  # 用户反馈
    LEARNING_OUTCOME = "learning_outcome"  # 学习成果


class MemoryPriority(Enum):
    """
    记忆优先级
    
    用于控制记忆的重要性和保留策略。
    """
    CRITICAL = "critical"     # 关键信息，必须保留
    HIGH = "high"             # 重要信息，长期保留
    NORMAL = "normal"         # 一般信息，适时清理
    LOW = "low"               # 低优先级信息，可短时保留
    TEMPORARY = "temporary"   # 临时信息，会话结束可清理


@dataclass
class MemoryMetadata:
    """
    记忆元数据
    
    存储记忆的附加信息，用于检索、索引和管理。
    """
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    accessed_at: Optional[datetime] = None
    access_count: int = 0
    version: int = 1
    tags: List[str] = field(default_factory=list)
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    
    def mark_accessed(self) -> None:
        """标记记忆被访问"""
        self.accessed_at = datetime.now()
        self.access_count += 1
    
    def mark_updated(self) -> None:
        """标记记忆被更新"""
        self.updated_at = datetime.now()
        self.version += 1


@dataclass
class MemoryEntry:
    """
    记忆条目
    
    系统中的基本记忆单元，包含内容和元数据。
    """
    id: str                    # 唯一标识符
    content: str               # 记忆内容
    memory_type: MemoryType    # 记忆类型
    category: MemoryCategory   # 内容分类
    
    # 上下文信息
    agent_id: Optional[str] = None      # 归属的Agent ID
    session_id: Optional[str] = None    # 所属会话ID
    parent_id: Optional[str] = None     # 父记忆ID（用于关联记忆）
    
    # 元数据
    metadata: MemoryMetadata = field(default_factory=MemoryMetadata)
    priority: MemoryPriority = MemoryPriority.NORMAL
    
    # 存储信息
    storage_path: Optional[Path] = None  # 存储路径（用于文件系统存储）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式，便于序列化"""
        return {
            'id': self.id,
            'content': self.content,
            'memory_type': self.memory_type.value,
            'category': self.category.value,
            'agent_id': self.agent_id,
            'session_id': self.session_id,
            'parent_id': self.parent_id,
            'metadata': {
                'created_at': self.metadata.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': self.metadata.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.metadata.updated_at else None,
                'accessed_at': self.metadata.accessed_at.strftime('%Y-%m-%d %H:%M:%S') if self.metadata.accessed_at else None,
                'access_count': self.metadata.access_count,
                'version': self.metadata.version,
                'tags': self.metadata.tags,
                'custom_fields': self.metadata.custom_fields
            },
            'priority': self.priority.value,
            'storage_path': str(self.storage_path) if self.storage_path else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryEntry':
        """从字典格式创建MemoryEntry"""
        metadata_dict = data.get('metadata', {})
        
        # 解析时间字段
        created_at = datetime.fromisoformat(metadata_dict.get('created_at')) if metadata_dict.get('created_at') else datetime.now()
        updated_at = datetime.fromisoformat(metadata_dict['updated_at']) if metadata_dict.get('updated_at') else None
        accessed_at = datetime.fromisoformat(metadata_dict['accessed_at']) if metadata_dict.get('accessed_at') else None
        
        metadata = MemoryMetadata(
            created_at=created_at,
            updated_at=updated_at,
            accessed_at=accessed_at,
            access_count=metadata_dict.get('access_count', 0),
            version=metadata_dict.get('version', 1),
            tags=metadata_dict.get('tags', []),
            custom_fields=metadata_dict.get('custom_fields', {})
        )
        
        return cls(
            id=data['id'],
            content=data['content'],
            memory_type=MemoryType(data['memory_type']),
            category=MemoryCategory(data['category']),
            agent_id=data.get('agent_id'),
            session_id=data.get('session_id'),
            parent_id=data.get('parent_id'),
            metadata=metadata,
            priority=MemoryPriority(data.get('priority', 'normal')),
            storage_path=Path(data['storage_path']) if data.get('storage_path') else None
        )


@dataclass
class SearchResult:
    """
    搜索结果
    
    包含记忆搜索的结果及其相关性评分。
    """
    memory_entry: MemoryEntry   # 匹配的记忆条目
    score: float                # 相关性评分 (0.0-1.0)
    search_type: str            # 搜索类型: "vector", "keyword", "hybrid"
    match_snippets: List[str] = field(default_factory=list)  # 匹配片段
    metadata: Dict[str, Any] = field(default_factory=dict)   # 附加元数据
    
    def __lt__(self, other: 'SearchResult') -> bool:
        """用于排序：按评分降序"""
        return self.score > other.score


@dataclass
class ContextBundle:
    """
    上下文数据包
    
    为Agent提供的一组相关记忆，用于生成回复或执行任务。
    """
    memories: List[MemoryEntry] = field(default_factory=list)  # 相关记忆条目
    summary: Optional[str] = None                              # 上下文摘要
    timestamp: datetime = field(default_factory=datetime.now)  # 生成时间
    
    def to_text(self, include_summary: bool = True) -> str:
        """将上下文转换为文本格式，便于模型使用"""
        text_parts = []
        
        if include_summary and self.summary:
            text_parts.append(f"摘要: {self.summary}\n")
        
        for i, memory in enumerate(self.memories, 1):
            meta = memory.metadata
            time_str = meta.created_at.strftime("%Y-%m-%d %H:%M")
            text_parts.append(f"[{i}] {time_str} [{memory.memory_type.value}/{memory.category.value}]: {memory.content}")
        
        return "\n".join(text_parts)


@dataclass
class TimeRange:
    """
    时间范围
    
    用于指定记忆检索的时间条件。
    """
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    
    def contains(self, timestamp: datetime) -> bool:
        """检查时间戳是否在范围内"""
        if self.start and timestamp < self.start:
            return False
        if self.end and timestamp > self.end:
            return False
        return True


@dataclass
class MemoryStats:
    """
    记忆系统统计信息
    """
    total_memories: int = 0                     # 总记忆数量
    by_type: Dict[str, int] = field(default_factory=dict)      # 按类型统计
    by_category: Dict[str, int] = field(default_factory=dict)  # 按分类统计
    total_size_bytes: int = 0                   # 总存储大小（字节）
    last_cleanup: Optional[datetime] = None     # 最后一次清理时间
    average_retrieval_time_ms: float = 0.0      # 平均检索时间（毫秒）
    
    def __str__(self) -> str:
        """格式化输出统计信息"""
        lines = [f"记忆系统统计:"]
        lines.append(f"  总记忆数量: {self.total_memories:,}")
        lines.append(f"  总存储大小: {self.total_size_bytes:,} bytes ({self.total_size_bytes / 1024 / 1024:.2f} MB)")
        
        if self.by_type:
            lines.append("  按类型统计:")
            for mem_type, count in sorted(self.by_type.items()):
                lines.append(f"    {mem_type}: {count:,}")
        
        if self.average_retrieval_time_ms > 0:
            lines.append(f"  平均检索时间: {self.average_retrieval_time_ms:.2f} ms")
        
        if self.last_cleanup:
            lines.append(f"  最后清理时间: {self.last_cleanup.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)


@dataclass
class MemoryConfig:
    """
    记忆系统配置
    
    控制统一记忆管理器的各种行为参数。
    """
    # 存储配置
    storage_base_path: Path = field(default_factory=lambda: Path("data/memory"))
    enable_vector_index: bool = True
    
    # 缓存配置
    memory_cache_size: int = 1000          # 内存缓存大小
    enable_memory_cache: bool = True
    
    # 搜索配置
    keyword_search_enabled: bool = True
    vector_search_enabled: bool = False   # 暂时禁用向量搜索
    hybrid_search_enabled: bool = False   # 暂时禁用混合搜索，仅使用关键词搜索
    
    # 向量搜索配置
    embedding_dim: int = 384              # 向量嵌入维度（原 vector_dimension）
    annoy_trees: int = 10                 # Annoy 索引的树数量
    similarity_threshold: float = 0.0     # 相似度阈值（临时设为0以观察所有结果）
    
    # 混合搜索配置
    vector_weight: float = 0.6            # 向量搜索结果权重
    keyword_weight: float = 0.4           # 关键词搜索结果权重
    rrf_k: int = 60                       # RRF 融合常数
    
    # 清理策略
    cleanup_enabled: bool = True
    cleanup_interval_days: int = 30
    automatic_compaction: bool = True
    
    # 兼容性配置
    enable_legacy_api: bool = True         # 启用传统API桥接
    migration_mode: str = "auto"           # auto/manual/off
    
    # 监控配置
    enable_monitoring: bool = True
    stats_update_interval_seconds: int = 300  # 5分钟
    
    def validate(self) -> None:
        """验证配置的有效性"""
        if self.similarity_threshold < 0 or self.similarity_threshold > 1:
            raise ValueError(f"similarity_threshold 必须在 0-1 之间，当前值: {self.similarity_threshold}")
        
        if self.memory_cache_size < 0:
            raise ValueError(f"memory_cache_size 必须大于 0，当前值: {self.memory_cache_size}")
        
        if self.migration_mode not in ["auto", "manual", "off"]:
            raise ValueError(f"migration_mode 必须是 'auto', 'manual' 或 'off'，当前值: {self.migration_mode}")