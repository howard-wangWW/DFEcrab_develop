"""
Kernel 核心模块测试
"""

import os
import sys
import asyncio
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.kernel import Kernel, get_kernel, reset_kernel
from src.core.event import EventBus, get_event_bus, reset_event_bus
from src.plugin_framework.base import BasePlugin, PluginMetadata, PluginState
from src.plugin_framework.loader import PluginLoader, get_plugin_loader
from src.plugin_framework.registry import PluginRegistry, get_plugin_registry


class MockPlugin(BasePlugin):
    """模拟插件用于测试"""
    
    def __init__(self, name="mock_plugin", dependencies=None):
        super().__init__()
        self._name = name
        self._dependencies = dependencies or []
        self.load_called = False
        self.initialize_called = False
        self.start_called = False
        self.stop_called = False
        self.unload_called = False
    
    def _create_metadata(self) -> PluginMetadata:
        """创建元数据"""
        return PluginMetadata(
            name=self._name,
            version="1.0.0",
            author="Test Author",
            description="Mock plugin for testing",
            dependencies=self._dependencies
        )
    
    async def on_load(self) -> bool:
        """加载回调"""
        self.load_called = True
        return True
    
    async def on_initialize(self) -> bool:
        """初始化回调"""
        self.initialize_called = True
        return True
    
    async def on_start(self) -> bool:
        """启动回调"""
        self.start_called = True
        return True
    
    async def on_stop(self) -> bool:
        """停止回调"""
        self.stop_called = True
        return True
    
    async def on_unload(self) -> bool:
        """卸载回调"""
        self.unload_called = True
        return True


class TestKernel(unittest.TestCase):
    """Kernel 测试类"""
    
    def setUp(self):
        """测试前准备"""
        # 创建临时插件目录
        self.temp_dir = tempfile.mkdtemp()
        self.plugin_dir = Path(self.temp_dir) / "plugins" / "builtin"
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理全局实例
        reset_kernel()
        reset_event_bus()
        
        # 创建测试配置
        self.config = {
            "plugin_dir": str(self.temp_dir)
        }
        
        # 创建内核实例
        self.kernel = Kernel(self.config)
    
    def tearDown(self):
        """测试后清理"""
        # 停止内核
        if self.kernel.is_running():
            asyncio.run(self.kernel.stop())
        
        # 清理临时目录
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
        # 重置全局实例
        reset_kernel()
        reset_event_bus()
    
    def test_kernel_initialization(self):
        """测试内核初始化"""
        self.assertIsNotNone(self.kernel)
        self.assertEqual(self.kernel.config, self.config)
        self.assertFalse(self.kernel.is_running())
        self.assertEqual(str(self.kernel.plugin_dir), self.temp_dir)
    
    def test_kernel_start_stop(self):
        """测试内核启动和停止"""
        # 启动内核
        success = asyncio.run(self.kernel.start())
        self.assertTrue(success)
        self.assertTrue(self.kernel.is_running())
        
        # 统计信息
        stats = self.kernel.get_stats()
        self.assertTrue(stats["running"])
        self.assertIsNotNone(stats["startup_time"])
        
        # 停止内核
        success = asyncio.run(self.kernel.stop())
        self.assertTrue(success)
        self.assertFalse(self.kernel.is_running())
    
    def test_kernel_restart(self):
        """测试内核重启"""
        # 启动内核
        success = asyncio.run(self.kernel.start())
        self.assertTrue(success)
        
        # 重启内核
        success = asyncio.run(self.kernel.restart())
        self.assertTrue(success)
        self.assertTrue(self.kernel.is_running())
    
    def test_get_kernel_singleton(self):
        """测试内核单例模式"""
        kernel1 = get_kernel(self.config)
        kernel2 = get_kernel()
        
        self.assertIs(kernel1, kernel2)
        
        # 重置后应该获取新实例
        reset_kernel()
        kernel3 = get_kernel()
        self.assertIsNot(kernel1, kernel3)
    
    def test_plugin_management_without_plugins(self):
        """测试无插件时的插件管理"""
        # 启动内核（没有插件）
        success = asyncio.run(self.kernel.start())
        self.assertTrue(success)
        
        # 列出插件
        plugins = self.kernel.list_plugins()
        self.assertEqual(len(plugins), 0)
        
        # 获取不存在的插件
        plugin = self.kernel.get_plugin("nonexistent")
        self.assertIsNone(plugin)
        
        # 获取不存在的插件元数据
        metadata = self.kernel.get_plugin_metadata("nonexistent")
        self.assertIsNone(metadata)
    
    def test_event_bus_integration(self):
        """测试事件总线集成"""
        # 启动内核
        success = asyncio.run(self.kernel.start())
        self.assertTrue(success)
        
        # 创建事件处理器
        event_received = False
        event_data = None
        
        async def event_handler(event):
            nonlocal event_received, event_data
            event_received = True
            event_data = event.data
        
        # 订阅事件
        if self.kernel.event_bus:
            handler_id = self.kernel.event_bus.subscribe("test.event", event_handler)
            
            # 发布事件
            asyncio.run(self.kernel.emit_event("test.event", {"key": "value"}))
            
            # 等待事件处理（异步）
            async def wait_for_event():
                await asyncio.sleep(0.1)
            
            asyncio.run(wait_for_event())
            
            # 验证事件被处理
            self.assertTrue(event_received)
            self.assertEqual(event_data, {"key": "value"})
            
            # 取消订阅
            self.kernel.event_bus.unsubscribe(handler_id)
    
    def test_service_registration(self):
        """测试服务注册"""
        # 模拟服务
        mock_service = Mock()
        mock_service.name = "test_service"
        
        # 注册服务
        self.kernel.register_service("test_service", mock_service)
        
        # 获取服务
        service = self.kernel.get_service("test_service")
        self.assertIs(service, mock_service)
        
        # 检查服务是否存在
        self.assertTrue(self.kernel.has_service("test_service"))
        
        # 列出服务
        services = self.kernel.list_services()
        self.assertIn("test_service", services)
        
        # 获取不存在的服务
        none_service = self.kernel.get_service("nonexistent")
        self.assertIsNone(none_service)
        
        self.assertFalse(self.kernel.has_service("nonexistent"))
    
    @patch.object(PluginLoader, 'load_all')
    @patch.object(PluginLoader, 'unload_plugin')
    async def test_plugin_lifecycle_mocked(self, mock_unload, mock_load_all):
        """测试插件生命周期（使用模拟）"""
        # 模拟插件加载器返回加载了1个插件
        mock_load_all.return_value = 1
        
        # 启动内核
        success = await self.kernel.start()
        self.assertTrue(success)
        
        # 验证插件加载器被调用
        mock_load_all.assert_called_once()
        
        # 模拟卸载插件
        mock_unload.return_value = True
        
        # 卸载插件
        success = await self.kernel.unload_plugin("test_plugin")
        self.assertTrue(success)
        
        # 验证卸载被调用
        mock_unload.assert_called_once_with("test_plugin")
    
    def test_kernel_stats(self):
        """测试内核统计信息"""
        stats = self.kernel.get_stats()
        
        self.assertIsInstance(stats, dict)
        self.assertIn("running", stats)
        self.assertIn("plugin_count", stats)
        self.assertIn("running_plugins", stats)
        self.assertIn("service_count", stats)
        self.assertIn("plugin_dir", stats)
        
        self.assertFalse(stats["running"])
        self.assertEqual(stats["plugin_count"], 0)
        self.assertEqual(stats["running_plugins"], 0)
        self.assertEqual(stats["service_count"], 0)


class TestEventBus(unittest.TestCase):
    """事件总线测试类"""
    
    def setUp(self):
        """测试前准备"""
        reset_event_bus()
        self.event_bus = get_event_bus()
    
    def tearDown(self):
        """测试后清理"""
        reset_event_bus()
    
    def test_event_bus_creation(self):
        """测试事件总线创建"""
        self.assertIsNotNone(self.event_bus)
        
        # 验证是同一个实例
        event_bus2 = get_event_bus()
        self.assertIs(self.event_bus, event_bus2)
    
    def test_event_subscription(self):
        """测试事件订阅"""
        # 创建模拟处理器
        handler_called = False
        
        def event_handler(event):
            nonlocal handler_called
            handler_called = True
        
        # 订阅事件
        handler_id = self.event_bus.subscribe("test.event", event_handler)
        self.assertIsNotNone(handler_id)
        
        # 发布事件
        asyncio.run(self.event_bus.publish("test.event", {"data": "test"}))
        
        # 验证处理器被调用
        self.assertTrue(handler_called)
        
        # 取消订阅
        success = self.event_bus.unsubscribe(handler_id)
        self.assertTrue(success)
    
    def test_event_wildcard_subscription(self):
        """测试通配符事件订阅"""
        # 创建模拟处理器
        event_types = []
        
        def event_handler(event):
            event_types.append(event.event_type)
        
        # 订阅通配符事件
        handler_id = self.event_bus.subscribe("plugin.*", event_handler)
        
        # 发布不同的事件
        asyncio.run(self.event_bus.publish("plugin.loaded", {"name": "test"}))
        asyncio.run(self.event_bus.publish("plugin.unloaded", {"name": "test"}))
        asyncio.run(self.event_bus.publish("system.start", {}))
        
        # 验证只有插件事件被处理
        self.assertEqual(len(event_types), 2)
        self.assertIn("plugin.loaded", event_types)
        self.assertIn("plugin.unloaded", event_types)
        self.assertNotIn("system.start", event_types)
    
    def test_event_middleware(self):
        """测试事件中间件"""
        # 创建模拟中间件
        middleware_called = False
        
        async def test_middleware(event, next_fn):
            nonlocal middleware_called
            middleware_called = True
            await next_fn()
        
        # 添加中间件
        self.event_bus.add_middleware(test_middleware)
        
        # 创建模拟处理器
        handler_called = False
        
        def event_handler(event):
            nonlocal handler_called
            handler_called = True
        
        # 订阅事件
        self.event_bus.subscribe("test.event", event_handler)
        
        # 发布事件
        asyncio.run(self.event_bus.publish("test.event"))
        
        # 验证中间件和处理器都被调用
        self.assertTrue(middleware_called)
        self.assertTrue(handler_called)
    
    def test_event_bus_stats(self):
        """测试事件总线统计信息"""
        # 订阅几个事件
        def handler1(event):
            pass
        
        def handler2(event):
            pass
        
        self.event_bus.subscribe("event1", handler1)
        self.event_bus.subscribe("event2", handler2)
        self.event_bus.add_middleware(lambda e, n: n())
        
        stats = self.event_bus.get_stats()
        
        self.assertIsInstance(stats, dict)
        self.assertIn("running", stats)
        self.assertIn("event_types", stats)
        self.assertIn("total_handlers", stats)
        self.assertIn("middleware_count", stats)
        
        self.assertEqual(stats["total_handlers"], 2)
        self.assertEqual(stats["middleware_count"], 1)


if __name__ == "__main__":
    unittest.main()