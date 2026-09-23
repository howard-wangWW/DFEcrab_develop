"""Test plugin loader."""
import unittest
from unittest.mock import Mock, AsyncMock, patch
import tempfile
import shutil
from pathlib import Path

# 添加src目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.plugin_framework.loader import PluginLoader
from src.plugin_framework.base import BasePlugin, PluginMetadata, PluginState


class TestPluginLoader(unittest.TestCase):
    """Test plugin loader."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.plugin_dir = Path(self.temp_dir) / "plugins"
        self.plugin_dir.mkdir(parents=True)
        
        # 创建内置和第三方目录
        (self.plugin_dir / "builtin").mkdir()
        (self.plugin_dir / "thirdparty").mkdir()
        
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir)
    
    def test_plugin_loader_init(self):
        """Test plugin loader initialization."""
        loader = PluginLoader(str(self.plugin_dir))
        self.assertEqual(loader.plugin_dir, self.plugin_dir)
    
    def test_ensure_plugin_dir(self):
        """Test ensure plugin directory exists."""
        loader = PluginLoader(str(self.plugin_dir))
        loader.ensure_plugin_dir()
        
        # 检查目录是否存在
        self.assertTrue(self.plugin_dir.exists())
        self.assertTrue((self.plugin_dir / "builtin").exists())
        self.assertTrue((self.plugin_dir / "thirdparty").exists())
    
    @patch('src.plugins.loader.get_plugin_registry')
    def test_load_plugin_directory(self, mock_registry):
        """Test loading a plugin from directory."""
        # 创建一个目录插件
        plugin_path = self.plugin_dir / "builtin" / "test_plugin"
        plugin_path.mkdir()
        
        # 创建 __init__.py
        init_file = plugin_path / "__init__.py"
        init_file.write_text("""
from src.plugin_framework.base import BasePlugin, PluginMetadata

class TestPlugin(BasePlugin):
    def _create_metadata(self):
        return PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            author="test",
            description="Test plugin"
        )
    
    async def on_initialize(self):
        return True
    
    async def on_start(self):
        return True

plugin = TestPlugin()
""")
        
        # Mock registry
        mock_registry.return_value.has_plugin.return_value = False
        mock_registry.return_value.register.return_value = True
        
        loader = PluginLoader(str(self.plugin_dir))
        
        # 测试异步加载
        import asyncio
        result = asyncio.run(loader.load_plugin("test_plugin", plugin_path))
        self.assertTrue(result)
    
    def test_is_plugin_directory(self):
        """Test plugin directory detection."""
        loader = PluginLoader(str(self.plugin_dir))
        
        # Create a plugin directory
        plugin_dir = self.plugin_dir / "builtin" / "test_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("# plugin")
        
        self.assertTrue(loader._is_plugin_directory(plugin_dir))
        
        # Non-plugin directory (no __init__.py)
        non_plugin_dir = self.plugin_dir / "builtin" / "not_plugin"
        non_plugin_dir.mkdir()
        self.assertFalse(loader._is_plugin_directory(non_plugin_dir))
    
    def test_is_plugin_file(self):
        """Test plugin file detection."""
        loader = PluginLoader(str(self.plugin_dir))
        
        # Plugin file
        plugin_file = self.plugin_dir / "builtin" / "plugin.py"
        plugin_file.write_text("# plugin")
        self.assertTrue(loader._is_plugin_file(plugin_file))
        
        # Non-plugin file (not .py)
        non_plugin = self.plugin_dir / "builtin" / "plugin.txt"
        non_plugin.write_text("# not plugin")
        self.assertFalse(loader._is_plugin_file(non_plugin))
        
        # __init__.py should not be considered a single-file plugin
        init_file = self.plugin_dir / "builtin" / "__init__.py"
        init_file.write_text("# init")
        self.assertFalse(loader._is_plugin_file(init_file))
    
    def test_get_plugin_main_file(self):
        """Test getting plugin main file."""
        loader = PluginLoader(str(self.plugin_dir))
        
        # Directory plugin
        plugin_dir = self.plugin_dir / "builtin" / "dir_plugin"
        plugin_dir.mkdir()
        init_file = plugin_dir / "__init__.py"
        init_file.write_text("# plugin")
        
        main_file = loader._get_plugin_main_file(plugin_dir)
        self.assertEqual(main_file, init_file)
        
        # File plugin
        plugin_file = self.plugin_dir / "builtin" / "file_plugin.py"
        plugin_file.write_text("# plugin")
        main_file = loader._get_plugin_main_file(plugin_file)
        self.assertEqual(main_file, plugin_file)
        
        # Invalid path
        invalid = self.plugin_dir / "builtin" / "invalid.txt"
        invalid.write_text("# not plugin")
        main_file = loader._get_plugin_main_file(invalid)
        self.assertIsNone(main_file)
    
    def test_discover_plugins(self):
        """Test plugin discovery."""
        loader = PluginLoader(str(self.plugin_dir))
        
        # Create directory plugin
        plugin_dir = self.plugin_dir / "builtin" / "dir_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("# plugin")
        
        # Create file plugin
        plugin_file = self.plugin_dir / "builtin" / "file_plugin.py"
        plugin_file.write_text("# plugin")
        
        plugins = loader._discover_plugins()
        plugin_names = [name for name, _ in plugins]
        
        self.assertIn("builtin/dir_plugin", plugin_names)
        self.assertIn("builtin/file_plugin", plugin_names)
    
    def test_list_available_plugins(self):
        """Test listing available plugins."""
        loader = PluginLoader(str(self.plugin_dir))
        
        # Create plugins
        plugin_dir = self.plugin_dir / "builtin" / "dir_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("# plugin")
        
        plugin_file = self.plugin_dir / "builtin" / "file_plugin.py"
        plugin_file.write_text("# plugin")
        
        available = loader.list_available_plugins()
        
        self.assertIn("builtin/dir_plugin", available)
        self.assertIn("builtin/file_plugin", available)


if __name__ == '__main__':
    unittest.main()