#!/usr/bin/env python3
"""
AgentPlugin 单元测试
测试智能体插件的核心功能和生命周期管理
"""

import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil
import json

from src.plugin_framework.builtin.agent_plugin import AgentPlugin
from src.plugin_framework.base import PluginMetadata


class TestAgentPlugin(unittest.TestCase):
    """智能体插件测试类"""
    
    def setUp(self):
        """测试前准备"""
        self.plugin = AgentPlugin()
        
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.skills_dir = Path(self.temp_dir) / "skills"
        self.skills_dir.mkdir(exist_ok=True)
        
        # 创建 tools.json 配置文件
        self.agents_dir = Path(self.temp_dir) / "agents" / "default"
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.tools_config_file = self.agents_dir / "tools.json"
        with open(self.tools_config_file, 'w') as f:
            json.dump({"enabled_skills": ["test_skill"]}, f)
        
        # 模拟 config
        self.config_patch = patch('src.plugins.builtin.agent_plugin.config')
        self.mock_config = self.config_patch.start()
        self.mock_config.model_configs = [{'config_name': 'test_model'}]
        
        # 模拟 agentscope 相关模块
        self.agentscope_patch = patch('src.plugins.builtin.agent_plugin.agentscope')
        self.mock_agentscope = self.agentscope_patch.start()
        self.mock_agentscope.init = Mock()
        
        # 模拟 AgentManager
        self.agent_manager_patch = patch('src.plugins.builtin.agent_plugin.AgentManager')
        self.mock_agent_manager_class = self.agent_manager_patch.start()
        self.mock_agent_manager = AsyncMock()
        self.mock_agent_manager_class.return_value = self.mock_agent_manager
        self.mock_agent_manager.list_saved_agents.return_value = []
        
        # 模拟 ServiceToolkit
        self.toolkit_patch = patch('src.plugins.builtin.agent_plugin.ServiceToolkit')
        self.mock_toolkit_class = self.toolkit_patch.start()
        self.mock_toolkit = Mock()
        self.mock_toolkit_class.return_value = self.mock_toolkit
        self.mock_toolkit.add = Mock()
        
        # 模拟 ReActAgent
        self.react_agent_patch = patch('src.plugins.builtin.agent_plugin.ReActAgent')
        self.mock_react_agent_class = self.react_agent_patch.start()
        self.mock_react_agent = Mock()
        self.mock_react_agent.name = "test_agent"
        self.mock_react_agent_class.return_value = self.mock_react_agent
        
    def tearDown(self):
        """测试后清理"""
        self.config_patch.stop()
        self.agentscope_patch.stop()
        self.agent_manager_patch.stop()
        self.toolkit_patch.stop()
        self.react_agent_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_plugin_initialization(self):
        """测试插件初始化"""
        # 验证插件实例创建
        self.assertIsNotNone(self.plugin)
        self.assertIsInstance(self.plugin, AgentPlugin)
        
        # 验证初始化字段
        self.assertEqual(self.plugin._agents, {})
        self.assertIsNone(self.plugin._current_agent)
        self.assertIsNone(self.plugin._toolkit)
    
    def test_metadata_creation(self):
        """测试插件元数据"""
        metadata = self.plugin.get_metadata()
        
        # 验证元数据字段
        self.assertEqual(metadata.name, "agent")
        self.assertEqual(metadata.version, "1.0.0")
        self.assertEqual(metadata.author, "DFEcrab Team")
        self.assertIn("core", metadata.tags)
        self.assertIn("agent", metadata.tags)
        
        # 验证依赖声明
        self.assertEqual(metadata.dependencies, ["skill", "memory"])
    
    async def _async_test_on_load(self):
        """测试插件加载（异步）"""
        success = await self.plugin.on_load()
        self.assertTrue(success)
        
        # 验证初始化调用
        self.mock_agentscope.init.assert_called_once()
        self.mock_agent_manager_class.assert_called_once()
    
    def test_on_load(self):
        """测试插件加载（同步包装）"""
        asyncio.run(self._async_test_on_load())
    
    async def _async_test_on_start(self):
        """测试插件启动"""
        # 模拟加载技能成功
        with patch.object(self.plugin, '_load_skills', Mock()):
            with patch.object(self.plugin, '_load_saved_agents', AsyncMock()):
                # 模拟创建默认智能体
                with patch.object(self.plugin, 'create_agent', AsyncMock(return_value={"agent_id": "dfecrab"})):
                    success = await self.plugin.on_start()
                    
                    self.assertTrue(success)
                    self.plugin._load_skills.assert_called_once()
                    self.plugin._load_saved_agents.assert_called_once()
    
    def test_on_start(self):
        """测试插件启动（同步包装）"""
        asyncio.run(self._async_test_on_start())
    
    async def _async_test_create_agent(self):
        """测试创建智能体"""
        # 模拟 _publish_event 方法
        self.plugin._publish_event = AsyncMock()
        self.plugin._get_agent_info = Mock(return_value={"agent_id": "test_agent"})
        
        # 调用创建智能体
        result = await self.plugin.create_agent("test_agent")
        
        # 验证结果
        self.assertIsNotNone(result)
        self.assertIn("agent_id", result)
        
        # 验证智能体被添加
        self.assertIn("test_agent", self.plugin._agents)
        
        # 验证相关调用
        self.mock_react_agent_class.assert_called_once()
        self.plugin._publish_event.assert_called_once_with(
            "agent.created", {"agent_id": "test_agent"}
        )
    
    def test_create_agent(self):
        """测试创建智能体（同步包装）"""
        asyncio.run(self._async_test_create_agent())
    
    async def _async_test_delete_agent(self):
        """测试删除智能体"""
        # 先创建一个智能体
        self.plugin._agents["test_agent"] = self.mock_react_agent
        self.plugin._current_agent = self.mock_react_agent
        self.mock_react_agent.name = "test_agent"
        
        # 模拟 _publish_event 方法
        self.plugin._publish_event = AsyncMock()
        
        # 调用删除智能体
        success = await self.plugin.delete_agent("test_agent")
        
        # 验证结果
        self.assertTrue(success)
        self.assertNotIn("test_agent", self.plugin._agents)
        self.assertIsNone(self.plugin._current_agent)
        
        # 验证相关调用
        self.plugin._publish_event.assert_called_once_with(
            "agent.removed", {"agent_id": "test_agent"}
        )
    
    def test_delete_agent(self):
        """测试删除智能体（同步包装）"""
        asyncio.run(self._async_test_delete_agent())
    
    async def _async_test_switch_agent(self):
        """测试切换智能体"""
        # 创建两个智能体
        mock_agent1 = Mock()
        mock_agent1.name = "agent1"
        mock_agent2 = Mock()
        mock_agent2.name = "agent2"
        
        self.plugin._agents["agent1"] = mock_agent1
        self.plugin._agents["agent2"] = mock_agent2
        self.plugin._current_agent = mock_agent1
        
        # 模拟 _publish_event 方法
        self.plugin._publish_event = AsyncMock()
        
        # 切换到 agent2
        success = await self.plugin.switch_agent("agent2")
        
        # 验证结果
        self.assertTrue(success)
        self.assertEqual(self.plugin._current_agent, mock_agent2)
        
        # 验证事件发布
        self.plugin._publish_event.assert_called_once_with(
            "agent.switched", {"agent_id": "agent2"}
        )
        
        # 测试切换到不存在的智能体
        self.plugin._publish_event.reset_mock()
        success = await self.plugin.switch_agent("nonexistent")
        self.assertFalse(success)
        self.plugin._publish_event.assert_not_called()
    
    def test_switch_agent(self):
        """测试切换智能体（同步包装）"""
        asyncio.run(self._async_test_switch_agent())
    
    async def _async_test_chat(self):
        """测试聊天功能"""
        # 创建模拟智能体
        mock_agent = Mock()
        mock_agent.name = "test_agent"
        mock_agent.reply = Mock(return_value="测试回复")
        
        self.plugin._agents["test_agent"] = mock_agent
        
        # 测试与现有智能体聊天
        response = await self.plugin.chat("test_agent", "你好")
        
        # 验证结果
        self.assertEqual(response, "测试回复")
        mock_agent.reply.assert_called_once()
        
        # 测试与不存在的智能体聊天（应自动创建）
        self.mock_react_agent_class.reset_mock()
        mock_new_agent = Mock()
        mock_new_agent.name = "new_agent"
        mock_new_agent.reply = Mock(return_value="新智能体回复")
        self.mock_react_agent_class.return_value = mock_new_agent
        
        with patch.object(self.plugin, 'create_agent', AsyncMock(return_value={"agent_id": "new_agent"})):
            response = await self.plugin.chat("new_agent", "你好")
            
            # 验证智能体创建和回复
            self.plugin.create_agent.assert_called_once()
            mock_new_agent.reply.assert_called_once()
    
    def test_chat(self):
        """测试聊天功能（同步包装）"""
        asyncio.run(self._async_test_chat())
    
    def test_reload_skills(self):
        """测试重新加载技能"""
        # 模拟 _load_skills 方法
        self.plugin._load_skills = Mock()
        
        # 调用重新加载技能
        success = asyncio.run(self.plugin.reload_skills())
        
        # 验证结果
        self.assertTrue(success)
        self.plugin._load_skills.assert_called_once()
    
    def test_get_tools(self):
        """测试工具注册"""
        with patch('src.plugins.builtin.agent_plugin.ToolDefinition') as mock_tool_def:
            # 模拟工具定义
            mock_tool = Mock()
            mock_tool_def.return_value = mock_tool
            
            # 获取工具
            tools = self.plugin.get_tools()
            
            # 验证工具定义被调用
            self.assertGreater(mock_tool_def.call_count, 0)
            
            # 验证返回的工具列表
            self.assertIsInstance(tools, list)
    
    def test_save_agent(self):
        """测试保存智能体"""
        # 创建模拟智能体
        self.plugin._agents["test_agent"] = self.mock_react_agent
        
        # 调用保存智能体
        success = asyncio.run(self.plugin.save_agent("test_agent"))
        
        # 验证结果
        self.assertTrue(success)
        self.mock_agent_manager.save_agent.assert_called_once_with("test_agent")
        
        # 测试保存不存在的智能体
        self.mock_agent_manager.reset_mock()
        success = asyncio.run(self.plugin.save_agent("nonexistent"))
        self.assertFalse(success)
        self.mock_agent_manager.save_agent.assert_not_called()


if __name__ == "__main__":
    unittest.main()