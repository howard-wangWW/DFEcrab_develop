#!/usr/bin/env python3
"""
MCPPlugin 单元测试
测试 MCP 插件的核心功能和服务器管理
"""

import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil

from src.plugin_framework.builtin.mcp_plugin import MCPPlugin
from src.plugin_framework.base import PluginMetadata


class TestMCPPlugin(unittest.TestCase):
    """MCP 插件测试类"""
    
    def setUp(self):
        """测试前准备"""
        self.plugin = MCPPlugin()
        
        # 模拟 MCP 客户端库
        self.mcp_client_patch = patch('src.plugins.builtin.mcp_plugin.MCPClient')
        self.mock_mcp_client_class = self.mcp_client_patch.start()
        self.mock_mcp_client = AsyncMock()
        self.mock_mcp_client_class.return_value = self.mock_mcp_client
        
        self.mcp_config_patch = patch('src.plugins.builtin.mcp_plugin.MCPConfigManager')
        self.mock_mcp_config_class = self.mcp_config_patch.start()
        self.mock_mcp_config = Mock()
        self.mock_mcp_config_class.return_value = self.mock_mcp_config
        
    def tearDown(self):
        """测试后清理"""
        self.mcp_client_patch.stop()
        self.mcp_config_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_plugin_initialization(self):
        """测试插件初始化"""
        self.assertIsNotNone(self.plugin)
        self.assertIsInstance(self.plugin, MCPPlugin)
        self.assertEqual(self.plugin._mcp_clients, {})
        self.assertEqual(self.plugin._mcp_tools, {})
        self.assertIsNone(self.plugin._config_manager)
    
    def test_metadata_creation(self):
        """测试插件元数据"""
        metadata = self.plugin.get_metadata()
        self.assertEqual(metadata.name, "mcp")
        self.assertEqual(metadata.version, "1.0.0")
        self.assertEqual(metadata.author, "DFEcrab Team")
        self.assertIn("core", metadata.tags)
        self.assertIn("mcp", metadata.tags)
        self.assertEqual(metadata.dependencies, [])
    
    async def _async_test_on_load_success(self):
        """测试插件加载成功"""
        success = await self.plugin.on_load()
        self.assertTrue(success)
        self.assertIsNotNone(self.plugin._config_manager)
        self.mock_mcp_config_class.assert_called_once()
    
    def test_on_load_success(self):
        asyncio.run(self._async_test_on_load_success())
    
    async def _async_test_on_load_import_failure(self):
        """测试插件加载时导入失败"""
        with patch('src.plugins.builtin.mcp_plugin.MCPClient', side_effect=ImportError("No module")):
            success = await self.plugin.on_load()
            self.assertFalse(success)
    
    def test_on_load_import_failure(self):
        asyncio.run(self._async_test_on_load_import_failure())
    
    async def _async_test_connect_all_servers(self):
        """测试连接所有服务器"""
        self.mock_mcp_config.list_servers.return_value = ["server1", "server2"]
        mock_config1 = {"command": "python script1.py"}
        mock_config2 = {"command": "python script2.py"}
        self.mock_mcp_config.get_server.side_effect = [mock_config1, mock_config2]
        self.mock_mcp_client.connect.return_value = True
        self.mock_mcp_client.tools = {"tool1": Mock(), "tool2": Mock()}
        
        success = await self.plugin.connect_all_servers()
        self.assertTrue(success)
        self.assertEqual(len(self.plugin._mcp_clients), 2)
        self.assertEqual(len(self.plugin._mcp_tools), 4)
        self.mock_mcp_config.list_servers.assert_called_once()
        self.assertEqual(self.mock_mcp_config.get_server.call_count, 2)
        self.assertEqual(self.mock_mcp_client_class.call_count, 2)
        self.assertEqual(self.mock_mcp_client.connect.call_count, 2)
    
    def test_connect_all_servers(self):
        asyncio.run(self._async_test_connect_all_servers())
    
    def test_get_mcp_tools(self):
        """测试获取 MCP 工具"""
        self.plugin._mcp_tools = {
            "server1.tool1": {"server": "server1", "tool_name": "tool1"},
            "server1.tool2": {"server": "server1", "tool_name": "tool2"},
            "server2.tool1": {"server": "server2", "tool_name": "tool1"}
        }
        all_tools = self.plugin.get_mcp_tools()
        self.assertEqual(len(all_tools), 3)
        server1_tools = self.plugin.get_mcp_tools("server1")
        self.assertEqual(len(server1_tools), 2)
        server3_tools = self.plugin.get_mcp_tools("server3")
        self.assertEqual(len(server3_tools), 0)
    
    def test_get_tools(self):
        """测试工具注册"""
        self.plugin._mcp_tools = {
            "server1.tool1": {"server": "server1", "tool_name": "tool1", "description": "Test tool"}
        }
        tools = self.plugin.get_tools()
        self.assertEqual(len(tools), 4)
        tool_names = [tool.name for tool in tools]
        expected = ["list_mcp_servers", "list_mcp_tools", "execute_mcp_tool", "reload_mcp_servers"]
        for name in expected:
            self.assertIn(name, tool_names)


if __name__ == "__main__":
    unittest.main()