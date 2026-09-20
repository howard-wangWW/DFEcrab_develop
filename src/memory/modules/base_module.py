"""
记忆功能模块基类

定义所有功能模块必须实现的接口，确保一致的模块行为。
每个模块负责特定类型的记忆操作（每日、Agent、全局等）。
"""

import abc
import time
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from dataclasses import dataclass, field

from ..types import (
    MemoryEntry, MemoryType, MemoryCategory,
    TimeRange, MemoryStats
)

if TYPE_CHECKING:
    from ..unified_memory_manager import UnifiedMemoryManager


@dataclass
class ModuleStats:
    """模块统计信息"""
    total_processed: int = 0
    total_errors: int = 0
    average_response_time_ms: float = 0.0
    last_operation_time: Optional[float] = None


class BaseMemoryModule(abc.ABC):
    """
    记忆功能模块基类
    
    所有功能模块必须继承此类并实现抽象方法。
    模块负责特定记忆类型的完整生命周期管理。
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        unified_manager: "UnifiedMemoryManager",
        memory_type: MemoryType
    ):
        """
        初始化功能模块
        
        Args:
            config: 模块配置
            unified_manager: 统一管理器引用
            memory_type: 本模块处理的记忆类型
        """
        self.config = config
        self.unified_manager = unified_manager
        self.memory_type = memory_type
        self.stats = ModuleStats()
        
        # 性能跟踪
        self._response_times = []
        self._initialized = False
        
        # 存储适配器引用
        self.storage_adapter = None
        
        self._post_init()
    
    def _post_init(self) -> None:
        """子类可选的初始化后处理"""
        pass
    
    @abc.abstractmethod
    async def initialize(self) -> None:
        """
        初始化模块
        
        执行必要的初始化操作，如建立存储连接、加载索引等。
        """
        pass
    
    @abc.abstractmethod
    async def save_memory(self, memory_entry: MemoryEntry) -> MemoryEntry:
        """
        保存记忆条目
        
        Args:
            memory_entry: 要保存的记忆条目
            
        Returns:
            保存后的记忆条目（可能包含更新的信息）
        
        Raises:
            ModuleError: 保存失败时抛出
        """
        pass
    
    @abc.abstractmethod
    async def get_memory(self, memory_id: str, agent_id: Optional[str] = None) -> Optional[MemoryEntry]:
        """
        获取记忆条目
        
        Args:
            memory_id: 记忆ID
            agent_id: Agent ID（用于权限检查）
            
        Returns:
            记忆条目，如果未找到则返回None
        
        Raises:
            ModuleError: 获取失败时抛出
        """
        pass
    
    @abc.abstractmethod
    async def get_relevant_memories(
        self,
        agent_id: Optional[str] = None,
        time_range: Optional[TimeRange] = None,
        limit: int = 20
    ) -> List[MemoryEntry]:
        """
        获取相关记忆
        
        Args:
            agent_id: Agent ID
            time_range: 时间范围限制
            limit: 返回结果数量限制
            
        Returns:
            相关记忆条目列表
        """
        pass
    
    @abc.abstractmethod
    async def search_memories(
        self,
        query: str,
        agent_id: Optional[str] = None,
        limit: int = 10
    ) -> List[MemoryEntry]:
        """
        搜索记忆
        
        Args:
            query: 搜索查询
            agent_id: Agent ID
            limit: 返回结果数量限制
            
        Returns:
            匹配的记忆条目列表
        """
        pass
    
    async def update_memory(self, memory_entry: MemoryEntry) -> MemoryEntry:
        """
        更新记忆条目
        
        默认实现，子类可覆盖以优化特定类型的更新。
        
        Args:
            memory_entry: 更新后的记忆条目
            
        Returns:
            更新后的记忆条目
        
        Raises:
            ModuleError: 更新失败时抛出
            NotFoundError: 记忆条目不存在时抛出
        """
        return await self.save_memory(memory_entry)
    
    async def delete_memory(self, memory_id: str, agent_id: Optional[str] = None) -> bool:
        """
        删除记忆条目
        
        Args:
            memory_id: 要删除的记忆ID
            agent_id: Agent ID（用于权限检查）
            
        Returns:
            bool: 是否成功删除
        
        Raises:
            ModuleError: 删除失败时抛出
        """
        raise NotImplementedError("删除功能需要子类实现")
    
    async def batch_save(self, memory_entries: List[MemoryEntry]) -> List[MemoryEntry]:
        """
        批量保存记忆条目
        
        默认实现为循环调用save_memory，子类可优化批量操作。
        
        Args:
            memory_entries: 要保存的记忆条目列表
            
        Returns:
            保存后的记忆条目列表
        """
        results = []
        for entry in memory_entries:
            try:
                result = await self.save_memory(entry)
                results.append(result)
            except Exception as e:
                self._log_error(f"批量保存记忆失败 [{entry.id}]: {e}")
                self.stats.total_errors += 1
                continue
        
        self.stats.total_processed += len(memory_entries)
        return results
    
    async def batch_delete(self, memory_ids: List[str], agent_id: Optional[str] = None) -> Dict[str, bool]:
        """
        批量删除记忆条目
        
        Args:
            memory_ids: 要删除的记忆ID列表
            agent_id: Agent ID（用于权限检查）
            
        Returns:
            字典：{记忆ID: 是否成功删除}
        """
        results = {}
        for mem_id in memory_ids:
            try:
                success = await self.delete_memory(mem_id, agent_id)
                results[mem_id] = success
            except Exception as e:
                self._log_error(f"批量删除记忆失败 [{mem_id}]: {e}")
                self.stats.total_errors += 1
                results[mem_id] = False
        
        self.stats.total_processed += len(memory_ids)
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取模块统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "module_type": self.memory_type.value,
            "total_processed": self.stats.total_processed,
            "total_errors": self.stats.total_errors,
            "average_response_time_ms": self.stats.average_response_time_ms,
            "last_operation_time": self.stats.last_operation_time,
            "initialized": self._initialized,
        }
    
    def get_memory_stats(self) -> MemoryStats:
        """
        获取记忆统计信息
        
        Returns:
            MemoryStats: 记忆统计信息
        """
        # TODO: 子类应该实现具体的统计收集
        return MemoryStats(
            total_memories=0,
            by_type={self.memory_type.value: 0},
            total_size_bytes=0
        )
    
    def _track_operation_start(self) -> float:
        """记录操作开始时间"""
        return time.time()
    
    def _track_operation_end(self, start_time: float) -> float:
        """记录操作结束时间并更新统计"""
        elapsed_time = (time.time() - start_time) * 1000
        self._response_times.append(elapsed_time)
        
        # 保持最近的100个时间记录
        if len(self._response_times) > 100:
            self._response_times.pop(0)
        
        # 更新平均响应时间
        self.stats.average_response_time_ms = sum(self._response_times) / len(self._response_times)
        self.stats.last_operation_time = time.time()
        
        return elapsed_time
    
    def _log_error(self, message: str, exc_info: bool = False) -> None:
        """记录错误日志"""
        import logging
        logger = logging.getLogger(f"{self.__class__.__name__}.{self.memory_type.value}")
        logger.error(message, exc_info=exc_info)
    
    def _log_debug(self, message: str) -> None:
        """记录调试日志"""
        import logging
        logger = logging.getLogger(f"{self.__class__.__name__}.{self.memory_type.value}")
        logger.debug(message)
    
    def _log_info(self, message: str) -> None:
        """记录信息日志"""
        import logging
        logger = logging.getLogger(f"{self.__class__.__name__}.{self.memory_type.value}")
        logger.info(message)
    
    def _validate_memory_type(self, memory_entry: MemoryEntry) -> None:
        """验证记忆条目的类型"""
        if memory_entry.memory_type != self.memory_type:
            raise ValueError(
                f"模块 {self.memory_type.value} 不能处理类型 {memory_entry.memory_type.value} 的记忆条目"
            )
    
    def _check_permissions(self, memory_entry: MemoryEntry, agent_id: Optional[str] = None) -> bool:
        """
        检查权限
        
        默认实现：如果记忆条目有agent_id，则只有对应的agent可以访问。
        子类可以覆盖此方法以实现更复杂的权限控制。
        
        Args:
            memory_entry: 要检查的记忆条目
            agent_id: 请求访问的Agent ID
            
        Returns:
            bool: 是否允许访问
        """
        # 如果记忆条目没有agent_id，则所有人都可以访问（全局记忆）
        if not memory_entry.agent_id:
            return True
        
        # 如果记忆条目有agent_id，则只有对应的agent或特定共享情况可以访问
        return agent_id == memory_entry.agent_id or memory_entry.memory_type == MemoryType.AGENT_SHARED


class ModuleError(Exception):
    """模块相关错误"""
    pass


class PermissionDeniedError(ModuleError):
    """权限拒绝错误"""
    pass


class ValidationError(ModuleError):
    """验证错误"""
    pass