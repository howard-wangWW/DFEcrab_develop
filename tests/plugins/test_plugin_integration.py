#!/usr/bin/env python3
"""
插件集成测试
测试插件间的协同工作和端到端功能
"""

import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.plugin_framework.builtin.skill_plugin import SkillPlugin
from src.plugin_framework.builtin.memory_plugin import MemoryPlugin
from src.plugin_framework.builtin.agent_plugin import AgentPlugin
from src.plugin_framework.builtin.mcp_plugin import MCPPlugin
from src.plugin_framework.registry import get_plugin_registry, PluginRegistry
from src.plugin_framework.base import PluginMetadata, PluginState
from src.plugin_framework.loader import PluginLoader


class TestPluginIntegration(unittest.TestCase):
    """插件集成测试类"""
    
    def setUp(self):
        """测试前准备"""
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.project_root = Path(self.temp_dir)
        
        # 创建必要的目录结构
        (self.project_root / "skills").mkdir(exist_ok=True)
        (self.project_root / "agents" / "default").mkdir(parents=True, exist_ok=True)
        (self.project_root / "data" / "memory").mkdir(parents=True, exist_ok=True)
        
        # 创建测试技能
        self.test_skill_dir = self.project_root / "skills" / "test_skill"
        self.test_skill_dir.mkdir(exist_ok=True)
        (self.test_skill_dir / "execute.py").write_text("""
def execute(**kwargs):
    return {"success": True, "result": "Test skill executed"}
""")
        
        # 模拟配置
        self.config_patch = patch('src.plugins.builtin.skill_plugin.config')
        self.mock_config = self.config_patch.start()
        self.mock_config.skills_dir = self.project_root / "skills"
        
        # 模拟其他插件配置
        self.agent_config_patch = patch('src.plugins.builtin.agent_plugin.config')
        self.mock_agent_config = self.agent_config_patch.start()
        self.mock_agent_config.model_configs = [{'config_name': 'test_model'}]
        
        self.memory_config_patch = patch('src.plugins.builtin.memory_plugin.config')
        self.mock_memory_config = self.memory_config_patch.start()
        self.mock_memory_config.project_root = self.project_root
        
        # 创建插件实例
        self.skill_plugin = SkillPlugin()
        self.memory_plugin = MemoryPlugin()
        self.agent_plugin = AgentPlugin()
        self.mcp_plugin = MCPPlugin()
        
        # 重置全局注册中心
        from src.plugin_framework.registry import _plugin_registry
        _plugin_registry = None
        
        # 创建新的注册中心
        self.registry = get_plugin_registry()
        
    def tearDown(self):
        """测试后清理"""
        self.config_patch.stop()
        self.agent_config_patch.stop()
        self.memory_config_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    async def _async_test_plugin_registration_and_dependencies(self):
        """测试插件注册和依赖关系"""
        # 注册 MemoryPlugin（无依赖）
        success = self.registry.register(self.memory_plugin)
        self.assertTrue(success)
        self.assertTrue(self.registry.has_plugin("memory"))
        
        # 注册 SkillPlugin（依赖 builtin_tools 和 mcp）
        # 由于 builtin_tools 和 mcp 可能不存在，我们修改依赖列表为空
        with patch.object(self.skill_plugin, 'get_metadata') as mock_metadata:
            mock_metadata.return_value = PluginMetadata(
                name="skill",
                version="1.0.0",
                author="DFEcrab Team",
                description="Skill plugin",
                tags=["core", "skill", "tools"],
                dependencies=[]  # 空依赖以便测试
            )
            success = self.registry.register(self.skill_plugin)
            self.assertTrue(success)
        
        # 注册 AgentPlugin（依赖 skill 和 memory）
        with patch.object(self.agent_plugin, 'get_metadata') as mock_metadata:
            mock_metadata.return_value = PluginMetadata(
                name="agent",
                version="1.0.0",
                author="DFEcrab Team",
                description="Agent plugin",
                tags=["core", "agent"],
                dependencies=["skill", "memory"]  # 依赖已注册的插件
            )
            success = self.registry.register(self.agent_plugin)
            self.assertTrue(success)
        
        # 验证插件都已注册
        self.assertEqual(len(self.registry.list_plugins()), 3)
    
    def test_plugin_registration_and_dependencies(self):
        """测试插件注册和依赖关系（同步包装）"""
        asyncio.run(self._async_test_plugin_registration_and_dependencies())
    
    async def _async_test_skill_plugin_loads_skills(self):
        """测试技能插件加载技能"""
        # 加载插件
        success = await self.skill_plugin.on_load()
        self.assertTrue(success)
        
        # 启动插件
        success = await self.skill_plugin.on_start()
        self.assertTrue(success)
        
        # 验证技能已加载
        skills = self.skill_plugin.list_skills()
        self.assertGreater(len(skills), 0)
        
        # 查找测试技能
        test_skill_found = False
        for skill in skills:
            if skill["name"] == "test_skill":
                test_skill_found = True
                break
        self.assertTrue(test_skill_found, "测试技能应被加载")
    
    def test_skill_plugin_loads_skills(self):
        """测试技能插件加载技能（同步包装）"""
        asyncio.run(self._async_test_skill_plugin_loads_skills())
    
    async def _async_test_agent_plugin_uses_skill_tools(self):
        """测试智能体插件使用技能工具"""
        # 先加载技能插件
        await self.skill_plugin.on_load()
        await self.skill_plugin.on_start()
        
        # 加载智能体插件
        success = await self.agent_plugin.on_load()
        self.assertTrue(success)
        
        # 启动智能体插件
        success = await self.agent_plugin.on_start()
        self.assertTrue(success)
        
        # 验证智能体插件可以访问技能工具
        self.assertIsNotNone(self.agent_plugin._toolkit)
    
    def test_agent_plugin_uses_skill_tools(self):
        """测试智能体插件使用技能工具（同步包装）"""
        asyncio.run(self._async_test_agent_plugin_uses_skill_tools())
    
    async def _async_test_memory_plugin_provides_context(self):
        """测试记忆插件提供上下文"""
        # 加载记忆插件
        success = await self.memory_plugin.on_load()
        self.assertTrue(success)
        
        # 启动记忆插件
        success = await self.memory_plugin.on_start()
        self.assertTrue(success)
        
        # 添加测试记忆
        success = await self.memory_plugin.add_memory("test_agent", "今天学习了插件集成测试", "daily")
        self.assertTrue(success)
        
        # 获取记忆上下文
        context = await self.memory_plugin.get_memory_context("test_agent")
        self.assertIsNotNone(context)
        self.assertIsInstance(context, dict)
    
    def test_memory_plugin_provides_context(self):
        """测试记忆插件提供上下文（同步包装）"""
        asyncio.run(self._async_test_memory_plugin_provides_context())
    
    async def _async_test_skill_plugin_mcp_reference(self):
        """测试技能插件的 MCP 插件引用"""
        # 注册 MCP 插件
        self.registry.register(self.mcp_plugin)
        
        # 加载技能插件
        await self.skill_plugin.on_load()
        
        # 启动技能插件，应获取 MCP 插件引用
        success = await self.skill_plugin.on_start()
        self.assertTrue(success)
        
        # 验证 MCP 插件引用已设置
        self.assertIsNotNone(self.skill_plugin._mcp_plugin)
        self.assertEqual(self.skill_plugin._mcp_plugin, self.mcp_plugin)
    
    def test_skill_plugin_mcp_reference(self):
        """测试技能插件的 MCP 插件引用（同步包装）"""
        asyncio.run(self._async_test_skill_plugin_mcp_reference())
    
    async def _async_test_plugin_loader_integration(self):
        """测试插件加载器集成"""
        # 创建插件加载器
        loader = PluginLoader()
        
        # 模拟插件目录
        plugins_dir = self.project_root / "src" / "plugins" / "builtin"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载插件
        with patch('src.plugins.loader.PLUGINS_DIR', plugins_dir):
            with patch('src.plugins.loader.get_project_root', return_value=self.project_root):
                plugins = await loader.load_plugins()
        
        # 验证插件加载结果
        self.assertIsInstance(plugins, list)
    
    def test_plugin_loader_integration(self):
        """测试插件加载器集成（同步包装）"""
        asyncio.run(self._async_test_plugin_loader_integration())
    
    async def _async_test_end_to_end_plugin_workflow(self):
        """测试端到端插件工作流程"""
        # 1. 注册所有插件
        self.registry.register(self.memory_plugin)
        self.registry.register(self.skill_plugin)
        self.registry.register(self.agent_plugin)
        self.registry.register(self.mcp_plugin)
        
        # 2. 加载所有插件
        for plugin in [self.memory_plugin, self.skill_plugin, self.mcp_plugin, self.agent_plugin]:
            success = await plugin.on_load()
            self.assertTrue(success, f"{plugin.__class__.__name__} 加载失败")
        
        # 3. 启动所有插件
        for plugin in [self.memory_plugin, self.skill_plugin, self.mcp_plugin, self.agent_plugin]:
            success = await plugin.on_start()
            self.assertTrue(success, f"{plugin.__class__.__name__} 启动失败")
        
        # 4. 验证插件间协作
        # 技能插件应有 MCP 插件引用
        self.assertIsNotNone(self.skill_plugin._mcp_plugin)
        
        # 智能体插件应有工具包
        self.assertIsNotNone(self.agent_plugin._toolkit)
        
        # 记忆插件应有配置
        self.assertIsNotNone(self.memory_plugin._config)
        
        # 5. 验证插件状态
        plugin_names = ["memory", "skill", "mcp", "agent"]
        for name in plugin_names:
            metadata = self.registry.get_metadata(name)
            self.assertIsNotNone(metadata, f"插件 {name} 元数据不应为空")
            self.assertEqual(metadata.state, PluginState.RUNNING, f"插件 {name} 应处于运行状态")
    
    def test_end_to_end_plugin_workflow(self):
        """测试端到端插件工作流程（同步包装）"""
        asyncio.run(self._async_test_end_to_end_plugin_workflow())


if __name__ == "__main__":
    unittest.main()