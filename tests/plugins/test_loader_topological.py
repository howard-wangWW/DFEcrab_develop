"""Test topological sort and dependency resolution."""
import unittest
import tempfile
import shutil
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.plugin_framework.loader import PluginLoader


class TestTopologicalSort(unittest.TestCase):
    """Test topological sort functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.plugin_dir = Path(self.temp_dir) / "plugins"
        self.plugin_dir.mkdir(parents=True)
        
        # Create directories
        (self.plugin_dir / "builtin").mkdir()
        (self.plugin_dir / "thirdparty").mkdir()
        
        self.loader = PluginLoader(str(self.plugin_dir))
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir)
    
    def create_plugin_with_deps(self, name: str, dependencies: list):
        """Create a plugin with dependencies."""
        plugin_dir = self.plugin_dir / "builtin" / name
        plugin_dir.mkdir()
        
        init_content = f'''
from src.plugin_framework.base import BasePlugin, PluginMetadata

PLUGIN_DEPENDENCIES = {dependencies}

class {name.capitalize()}Plugin(BasePlugin):
    def _create_metadata(self):
        return PluginMetadata(
            name="{name}",
            version="1.0.0",
            author="test",
            description="Test plugin"
        )
    
    async def on_initialize(self):
        return True
    
    async def on_start(self):
        return True

plugin = {name.capitalize()}Plugin()
'''
        (plugin_dir / "__init__.py").write_text(init_content)
        return plugin_dir
    
    def test_topological_sort_linear(self):
        """Test topological sort with linear dependencies."""
        # Create plugins: a -> b -> c (a depends on nothing, b depends on a, c depends on b)
        self.create_plugin_with_deps("a", [])
        self.create_plugin_with_deps("b", ["a"])
        self.create_plugin_with_deps("c", ["b"])
        
        # Build plugin list
        plugins = []
        for name in ["a", "b", "c"]:
            plugin_path = self.plugin_dir / "builtin" / name
            deps = self.loader._get_plugin_dependencies(plugin_path)
            plugins.append((name, plugin_path, deps))
        
        # Perform topological sort
        sorted_plugins = self.loader._topological_sort(plugins)
        sorted_names = [name for name, _, _ in sorted_plugins]
        
        # Expected order: a, b, c (or any topological order)
        # Since a has no dependencies, b depends on a, c depends on b
        # Valid order: a, b, c
        self.assertEqual(len(sorted_plugins), 3)
        self.assertEqual(set(sorted_names), {"a", "b", "c"})
        
        # Check that a comes before b, and b comes before c
        a_idx = sorted_names.index("a")
        b_idx = sorted_names.index("b") 
        c_idx = sorted_names.index("c")
        self.assertLess(a_idx, b_idx)
        self.assertLess(b_idx, c_idx)
    
    def test_topological_sort_dag(self):
        """Test topological sort with DAG."""
        # Create plugins with diamond dependencies:
        #   a
        #  / \
        # b   c
        #  \ /
        #   d
        self.create_plugin_with_deps("a", [])
        self.create_plugin_with_deps("b", ["a"])
        self.create_plugin_with_deps("c", ["a"])
        self.create_plugin_with_deps("d", ["b", "c"])
        
        plugins = []
        for name in ["a", "b", "c", "d"]:
            plugin_path = self.plugin_dir / "builtin" / name
            deps = self.loader._get_plugin_dependencies(plugin_path)
            plugins.append((name, plugin_path, deps))
        
        sorted_plugins = self.loader._topological_sort(plugins)
        sorted_names = [name for name, _, _ in sorted_plugins]
        
        self.assertEqual(len(sorted_plugins), 4)
        self.assertEqual(set(sorted_names), {"a", "b", "c", "d"})
        
        # Verify constraints
        a_idx = sorted_names.index("a")
        b_idx = sorted_names.index("b")
        c_idx = sorted_names.index("c")
        d_idx = sorted_names.index("d")
        
        self.assertLess(a_idx, b_idx)
        self.assertLess(a_idx, c_idx)
        self.assertLess(b_idx, d_idx)
        self.assertLess(c_idx, d_idx)
    
    def test_topological_sort_cycle(self):
        """Test topological sort detects cycle."""
        # Create plugins with cycle: a -> b -> a
        self.create_plugin_with_deps("a", ["b"])  # a depends on b
        self.create_plugin_with_deps("b", ["a"])  # b depends on a
        
        plugins = []
        for name in ["a", "b"]:
            plugin_path = self.plugin_dir / "builtin" / name
            deps = self.loader._get_plugin_dependencies(plugin_path)
            plugins.append((name, plugin_path, deps))
        
        # Should raise ValueError
        with self.assertRaises(ValueError) as ctx:
            self.loader._topological_sort(plugins)
        
        self.assertIn("检测到循环依赖", str(ctx.exception))
    
    def test_dependency_detection(self):
        """Test dependency detection from plugin files."""
        # Create plugin with dependencies
        plugin_dir = self.create_plugin_with_deps("test", ["dep1", "dep2"])
        
        deps = self.loader._get_plugin_dependencies(plugin_dir)
        self.assertEqual(deps, ["dep1", "dep2"])
    
    def test_load_all_with_dependencies(self):
        """Test load_all respects dependencies."""
        # Create plugins with dependencies
        self.create_plugin_with_deps("base", [])
        self.create_plugin_with_deps("middle", ["base"])
        self.create_plugin_with_deps("top", ["middle"])
        
        # Load all plugins
        import asyncio
        loaded_count = asyncio.run(self.loader.load_all())
        
        # Should load 3 plugins
        self.assertEqual(loaded_count, 3)
        
        # Verify they were loaded in correct order
        # (loader should log order, but we can't easily capture it)
        # At least verify they're all loaded
        available = self.loader.list_available_plugins()
        self.assertEqual(len(available), 3)


if __name__ == '__main__':
    unittest.main()