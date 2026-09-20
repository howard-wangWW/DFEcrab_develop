"""
记忆功能模块 - V3.0 简化版

提供两种核心记忆模块：
1. AgentMemoryModule - 智能体私有记忆（跨会话持久化）
2. GlobalMemoryModule - 全局共享记忆（只读）

设计原则：简单、实用、易维护
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..unified_memory_manager import UnifiedMemoryManager

__all__ = [
    "BaseMemoryModule",
    "AgentMemoryModule",
    "GlobalMemoryModule",
    "ModuleError",
    "PermissionDeniedError"
]

try:
    from .base_module import BaseMemoryModule, ModuleError, PermissionDeniedError
    from .agent_module import AgentMemoryModule
    from .global_module import GlobalMemoryModule
except ImportError as e:
    import warnings
    warnings.warn(f"记忆模块导入失败: {e}")
    
    class BaseMemoryModule:
        def __init__(self, *args, **kwargs):
            raise ImportError("BaseMemoryModule 无法导入")
    
    class ModuleError(Exception):
        pass
    
    class PermissionDeniedError(Exception):
        pass
    
    class AgentMemoryModule(BaseMemoryModule):
        pass
    
    class GlobalMemoryModule(BaseMemoryModule):
        pass