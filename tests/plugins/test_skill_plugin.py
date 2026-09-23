#!/usr/bin/env python3
"""
SkillPlugin 单元测试
测试技能插件的核心功能和 MCP 插件协作
"""

import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from pathlib import Path
import tempfile
import shutil

from src.plugin_framework.builtin.skill_plugin import SkillPlugin
from src.plugin_framework.base import PluginMetadata


class TestSkillPlugin(unittest.TestCase):
    """技能插件测试类"""
    
    def setUp(self):
        """测试前准备"""
        self.plugin = SkillPlugin()
        
        # 创建临时技能目录
        self.temp_dir = tempfile.mkdtemp()
        self.skills_dir = Path(self.temp_dir) / "skills"
        self.skills_dir.mkdir(exist_ok=True)
        
        # 模拟配置
        self.config_patch = patch('src.plugins.builtin.skill_plugin.config')
        self.mock_config = self.config_patch.start()
        self.mock_config.skills_dir = self.skills_dir
    
    def tearDown(self):
        """测试后清理"""
        self.config_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_plugin_initialization(self):
        """测试插件初始化"""
        # 验证插件实例创建
        self.assertIsNotNone(self.plugin)
        self.assertIsInstance(self.plugin, SkillPlugin)
        
        # 验证初始化字段
        self.assertIsNone(self.plugin._toolkit)
        self.assertEqual(self.plugin._skills, {})
        self.assertEqual(self.plugin._mcp_tools, [])
        self.assertEqual(self.plugin._plugin_skills, {})
        self.assertEqual(self.plugin._skill_file_mtimes, {})
        self.assertIsNone(self.plugin._hot_reload_task)
        
        # 验证 mcp_plugin 字段为 None（设计意图）
        self.assertIsNone(self.plugin._mcp_plugin,
                         "mcp_plugin 应该为 None，直到通过插件注册表获取")
    
    def test_metadata_creation(self):
        """测试插件元数据创建"""
        metadata = self.plugin._create_metadata()
        
        # 验证元数据基本属性
        self.assertIsInstance(metadata, PluginMetadata)
        self.assertEqual(metadata.name, "skill")
        self.assertEqual(metadata.version, "1.0.0")
        self.assertEqual(metadata.author, "DFEcrab Team")
        self.assertIn("技能", metadata.description)
        
        # 验证依赖声明
        self.assertEqual(metadata.dependencies, ["builtin_tools", "mcp"])
    
    def test_mcp_plugin_field_design(self):
        """测试 MCP 插件字段的设计意图
        
        重点：验证 self._mcp_plugin = None 的设计合理性
        """
        # 确认字段存在且为 None
        self.assertTrue(hasattr(self.plugin, '_mcp_plugin'))
        self.assertIsNone(self.plugin._mcp_plugin)
        
        # 验证元数据中声明了 mcp 依赖
        metadata = self.plugin._create_metadata()
        self.assertIn("mcp", metadata.dependencies,
                     "SkillPlugin 应该声明对 mcp 插件的依赖")
        
        # 验证字段用途说明
        print("\n🔍 MCP 插件字段设计说明:")
        print("  - self._mcp_plugin = None 是预留引用，用于运行时依赖注入")
        print("  - 按照微内核架构，插件应在启动后通过插件注册表获取其他插件实例")
        print("  - 当前实现直接使用 MCPClient，绕过了 MCPPlugin 代理")
        print("  - 如需完善，可在 on_start() 中添加: self._mcp_plugin = registry.get('mcp')")
    
    async def _test_on_load(self):
        """测试插件加载（异步辅助方法）"""
        success = await self.plugin.on_load()
        self.assertTrue(success)
        self.assertIsNotNone(self.plugin._toolkit)
    
    def test_on_load_sync(self):
        """测试插件加载（同步包装）"""
        asyncio.run(self._test_on_load())
    
    @patch('src.plugins.builtin.skill_plugin.ServiceToolkit')
    async def _test_load_traditional_skills(self, mock_toolkit):
        """测试加载传统技能（异步辅助方法）"""
        # 创建测试技能目录
        test_skill_dir = self.skills_dir / "test_skill"
        test_skill_dir.mkdir()
        
        # 创建 execute.py 文件
        execute_file = test_skill_dir / "execute.py"
        execute_file.write_text("""
def execute(**kwargs):
    return {"result": "test success", **kwargs}

SKILL_METADATA = {
    "description": "测试技能",
    "parameters": {"param1": {"type": "string"}}
}
""")
        
        # 加载技能
        await self.plugin.on_load()
        await self.plugin._load_traditional_skills()
        
        # 验证技能已加载
        self.assertIn("test_skill", self.plugin._skills)
    
    def test_load_traditional_skills_sync(self):
        """测试加载传统技能（同步包装）"""
        with patch('src.plugins.builtin.skill_plugin.ServiceToolkit'):
            asyncio.run(self._test_load_traditional_skills())
    
    def test_skill_listing(self):
        """测试技能列表功能"""
        # 模拟一些技能
        self.plugin._skills = {
            "test_skill1": Mock(),
            "test_skill2": Mock()
        }
        
        # 调用 list_skills
        skills = self.plugin.list_skills()
        
        # 验证返回结果
        self.assertEqual(len(skills), 2)
        self.assertEqual(skills[0]["name"], "test_skill1")
        self.assertEqual(skills[0]["type"], "traditional")
    
    def test_get_tools_method(self):
        """测试 get_tools 方法"""
        tools = self.plugin.get_tools()
        
        # 验证工具数量
        self.assertEqual(len(tools), 3)
        
        # 验证工具名称
        tool_names = [tool.name for tool in tools]
        self.assertIn("execute_skill", tool_names)
        self.assertIn("list_skills", tool_names)
        self.assertIn("get_skill_info", tool_names)


if __name__ == '__main__':
    unittest.main()