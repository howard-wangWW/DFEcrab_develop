#!/usr/bin/env python3
"""
MemoryPlugin 单元测试
测试记忆插件的核心功能和 API
"""

import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil

from src.plugin_framework.builtin.memory_plugin import MemoryPlugin
from src.plugin_framework.base import PluginMetadata
from src.memory.global_manager import get_global_memory_manager


class TestMemoryPlugin(unittest.TestCase):
    """记忆插件测试类"""
    
    def setUp(self):
        """测试前准备"""
        self.plugin = MemoryPlugin()
        
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.workspace_dir = Path(self.temp_dir) / "agents"
        self.workspace_dir.mkdir(exist_ok=True)
        
        # 模拟配置
        self.config_patch = patch('src.plugins.builtin.memory_plugin.config')
        self.mock_config = self.config_patch.start()
        self.mock_config.project_root = Path(self.temp_dir)
        
        # 模拟 MarkdownMemoryManager
        self.memory_manager_patch = patch('src.plugins.builtin.memory_plugin.MarkdownMemoryManager')
        self.mock_memory_manager_class = self.memory_manager_patch.start()
        self.mock_memory_manager = AsyncMock(spec=MarkdownMemoryManager)
        self.mock_memory_manager_class.return_value = self.mock_memory_manager
        
    def tearDown(self):
        """测试后清理"""
        self.config_patch.stop()
        self.memory_manager_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_plugin_initialization(self):
        """测试插件初始化"""
        # 验证插件实例创建
        self.assertIsNotNone(self.plugin)
        self.assertIsInstance(self.plugin, MemoryPlugin)
        
        # 验证初始化字段
        self.assertEqual(self.plugin._memory_managers, {})
        self.assertIsNone(self.plugin._config)
    
    def test_metadata_creation(self):
        """测试插件元数据"""
        metadata = self.plugin.get_metadata()
        
        # 验证元数据字段
        self.assertEqual(metadata.name, "memory")
        self.assertEqual(metadata.version, "2.0.0")
        self.assertEqual(metadata.author, "DFEcrab Team")
        self.assertIn("core", metadata.tags)
        self.assertIn("memory", metadata.tags)
        self.assertEqual(metadata.dependencies, [])
    
    async def _async_test_on_load(self):
        """测试插件加载（异步）"""
        success = await self.plugin.on_load()
        self.assertTrue(success)
        self.assertIsNotNone(self.plugin._config)
    
    def test_on_load(self):
        """测试插件加载（同步包装）"""
        asyncio.run(self._async_test_on_load())
    
    async def _async_test_memory_manager_caching(self):
        """测试记忆管理器缓存"""
        # 第一次获取应该创建新的管理器
        manager1 = self.plugin._get_memory_manager("agent1")
        self.assertIsNotNone(manager1)
        self.mock_memory_manager_class.assert_called_once()
        
        # 重置调用计数
        self.mock_memory_manager_class.reset_mock()
        
        # 第二次获取应该返回缓存的管理器
        manager2 = self.plugin._get_memory_manager("agent1")
        self.assertEqual(manager1, manager2)
        self.mock_memory_manager_class.assert_not_called()
        
        # 不同智能体应该创建新的管理器
        manager3 = self.plugin._get_memory_manager("agent2")
        self.assertIsNotNone(manager3)
        self.mock_memory_manager_class.assert_called_once()
    
    def test_memory_manager_caching(self):
        """测试记忆管理器缓存（同步包装）"""
        asyncio.run(self._async_test_memory_manager_caching())
    
    async def _async_test_add_memory(self):
        """测试添加记忆"""
        # 设置模拟返回值
        self.mock_memory_manager.add_memory_entry.return_value = True
        
        # 调用添加记忆
        success = await self.plugin.add_memory("agent1", "测试记忆内容", "daily")
        
        # 验证调用
        self.assertTrue(success)
        self.mock_memory_manager.add_memory_entry.assert_called_once_with(
            "测试记忆内容", "daily"
        )
    
    def test_add_memory(self):
        """测试添加记忆（同步包装）"""
        asyncio.run(self._async_test_add_memory())
    
    async def _async_test_get_memory_context(self):
        """测试获取记忆上下文"""
        # 设置模拟返回值
        self.mock_memory_manager.load_context.return_value = {
            "today": "今日记忆内容",
            "yesterday": "昨日记忆内容",
            "long_term": "长期记忆内容"
        }
        
        # 调用获取记忆上下文
        context = await self.plugin.get_memory_context("agent1")
        
        # 验证结果
        self.assertIn("today", context)
        self.assertIn("yesterday", context)
        self.assertIn("long_term", context)
        self.mock_memory_manager.load_context.assert_called_once()
    
    def test_get_memory_context(self):
        """测试获取记忆上下文（同步包装）"""
        asyncio.run(self._async_test_get_memory_context())
    
    async def _async_test_read_memory(self):
        """测试读取记忆"""
        # 测试读取每日记忆
        self.mock_memory_manager.read_daily_memory.return_value = "每日记忆内容"
        daily_content = await self.plugin.read_memory("agent1", "2024-01-01", "daily")
        self.assertEqual(daily_content, "每日记忆内容")
        self.mock_memory_manager.read_daily_memory.assert_called_once_with("2024-01-01")
        
        # 测试读取长期记忆
        self.mock_memory_manager.read_long_term_memory.return_value = "长期记忆内容"
        long_term_content = await self.plugin.read_memory("agent1", None, "long_term")
        self.assertEqual(long_term_content, "长期记忆内容")
        self.mock_memory_manager.read_long_term_memory.assert_called_once()
    
    def test_read_memory(self):
        """测试读取记忆（同步包装）"""
        asyncio.run(self._async_test_read_memory())
    
    async def _async_test_write_memory(self):
        """测试写入记忆"""
        # 测试写入每日记忆
        self.mock_memory_manager.write_daily_memory.return_value = True
        success = await self.plugin.write_memory("agent1", "测试内容", "daily", True)
        self.assertTrue(success)
        self.mock_memory_manager.write_daily_memory.assert_called_once_with("测试内容", True)
        
        # 测试写入长期记忆
        self.mock_memory_manager.write_long_term_memory.return_value = True
        success = await self.plugin.write_memory("agent1", "测试内容", "long_term", False)
        self.assertTrue(success)
        self.mock_memory_manager.write_long_term_memory.assert_called_once_with("测试内容", False)
    
    def test_write_memory(self):
        """测试写入记忆（同步包装）"""
        asyncio.run(self._async_test_write_memory())
    
    def test_get_tools(self):
        """测试工具注册"""
        tools = self.plugin.get_tools()
        
        # 验证工具数量
        self.assertEqual(len(tools), 6)
        
        # 验证工具名称
        tool_names = [tool.name for tool in tools]
        expected_tools = [
            "add_memory",
            "get_memory_context", 
            "read_memory",
            "write_memory",
            "get_memory_stats",
            "get_all_memory_files"
        ]
        
        for expected in expected_tools:
            self.assertIn(expected, tool_names)
    
    def test_get_memory_prompts(self):
        """测试记忆提示词"""
        prompts = self.plugin.get_memory_prompts()
        
        # 验证提示词
        self.assertIn("system", prompts)
        self.assertIn("flush", prompts)
        self.assertIsInstance(prompts["system"], str)
        self.assertIsInstance(prompts["flush"], str)


if __name__ == "__main__":
    unittest.main()