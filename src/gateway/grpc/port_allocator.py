"""
端口分配工具

提供可靠的端口分配机制：
1. 随机选择端口
2. 检查端口可用性
3. 避免端口冲突
4. 服务停止时释放端口
"""

import socket
import random
import logging
from typing import Optional, Set

logger = logging.getLogger(__name__)


class PortAllocator:
    """端口分配器"""
    
    def __init__(self, start: int = 50000, end: int = 60000):
        """
        初始化端口分配器
        
        Args:
            start: 端口范围起始
            end: 端口范围结束
        """
        self.start = start
        self.end = end
        self._allocated_ports: Set[int] = set()
    
    def allocate_port(self, max_attempts: int = 100) -> int:
        """
        分配一个可用端口
        
        策略：
        1. 随机选择端口
        2. 检查是否已被自己分配
        3. 检查系统端口是否可用（SOCKET绑定测试）
        4. 如果不可用，重新随机（最多max_attempts次）
        5. 如果随机失败，顺序扫描（兜底）
        
        Args:
            max_attempts: 最大尝试次数
            
        Returns:
            可用端口号
            
        Raises:
            RuntimeError: 无法找到可用端口
        """
        # 阶段1：随机尝试
        for attempt in range(max_attempts):
            port = random.randint(self.start, self.end)
            
            # 检查是否已被自己分配
            if port in self._allocated_ports:
                continue
            
            # 检查系统级别是否可用
            if self._is_port_available(port):
                self._allocated_ports.add(port)
                logger.info(f"✅ 分配端口: {port} (随机，尝试{attempt+1}次)")
                return port
        
        # 阶段2：顺序扫描（兜底）
        logger.warning(f"⚠️ 随机{max_attempts}次都失败，开始顺序扫描...")
        port = self._scan_sequential()
        
        if port:
            self._allocated_ports.add(port)
            return port
        
        raise RuntimeError(
            f"❌ 无法在 {self.start}-{self.end} 范围内找到可用端口"
        )
    
    def release_port(self, port: int):
        """
        释放端口（服务停止时调用）
        
        Args:
            port: 要释放的端口
        """
        if port in self._allocated_ports:
            self._allocated_ports.remove(port)
            logger.info(f"👋 释放端口: {port}")
    
    def get_allocated_count(self) -> int:
        """获取已分配端口数量"""
        return len(self._allocated_ports)
    
    def _is_port_available(self, port: int) -> bool:
        """
        检查端口是否可用
        
        原理：尝试绑定端口，成功说明可用，失败说明已被占用
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('127.0.0.1', port))
                return True
            except OSError:
                return False
    
    def _scan_sequential(self) -> Optional[int]:
        """顺序扫描找到第一个可用端口"""
        for port in range(self.start, self.end):
            if port not in self._allocated_ports and self._is_port_available(port):
                logger.info(f"✅ 顺序扫描找到端口: {port}")
                return port
        
        return None


# 全局单例
_global_allocator = PortAllocator()


def get_available_port() -> int:
    """获取一个可用端口（全局函数）"""
    return _global_allocator.allocate_port()


def release_port(port: int):
    """释放端口（全局函数）"""
    _global_allocator.release_port(port)


def get_allocated_port_count() -> int:
    """获取已分配端口数量"""
    return _global_allocator.get_allocated_count()
