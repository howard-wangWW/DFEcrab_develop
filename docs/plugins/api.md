# DFEcrab 插件系统 API 参考

## 概述

DFEcrab 插件系统采用微内核架构，所有核心功能都通过插件实现。插件系统提供完整的生命周期管理、依赖解析、事件订阅、工具注册等功能。

## 核心概念

### 插件类型
- **内置插件 (Builtin Plugins):** 系统核心功能插件，位于 `plugins/builtin/`
- **第三方插件 (Third-party Plugins):** 用户安装的插件，位于 `plugins/thirdparty/`
- **技能插件 (Skill Plugins):** 提供特定功能或工具的插件

### 插件状态
```python
UNLOADED    # 未加载
LOADING     # 加载中
LOADED      # 已加载
RUNNING     # 运行中
STOPPING    # 停止中
STOPPED     # 已停止
ERROR       # 错误状态
```

## 插件基类

### PluginInterface
所有插件的抽象基类，定义插件的基本接口。

```python
from src.plugins.base import PluginInterface

class MyPlugin(PluginInterface):
    def get_metadata(self) -> PluginMetadata:
        """获取插件元数据"""
        pass
    
    async def load(self) -> bool:
        """加载插件"""
        pass
    
    async def unload(self) -> bool:
        """卸载插件"""
        pass
    
    async def initialize(self) -> bool:
        """初始化插件"""
        return True
    
    async def start(self) -> bool:
        """启动插件"""
        return True
    
    async def stop(self) -> bool:
        """停止插件"""
        return True
    
    def get_tools(self) -> List[ToolDefinition]:
        """获取插件提供的工具"""
        return []
```

### BasePlugin
推荐使用的插件基类，提供了默认实现。

```python
from src.plugins.base import BasePlugin

class MyPlugin(BasePlugin):
    def _create_metadata(self) -> PluginMetadata:
        """创建插件元数据"""
        return PluginMetadata(
            name="my_plugin",
            version="1.0.0",
            author="Your Name",
            description="My awesome plugin",
            tags=["utility", "demo"],
            dependencies=["skill", "agent"]  # 依赖其他插件
        )
    
    async def on_load(self) -> bool:
        """加载回调"""
        # 初始化资源
        return True
    
    async def on_start(self) -> bool:
        """启动回调"""
        # 启动服务
        return True
    
    async def on_stop(self) -> bool:
        """停止回调"""
        # 清理资源
        return True
```

## 插件上下文

PluginContext 提供插件访问核心系统的统一接口。

### 获取插件上下文
```python
from src.plugins.context import create_plugin_context, get_plugin_context

# 创建插件上下文
context = create_plugin_context("my_plugin", "1.0.0")

# 或获取已存在的上下文
context = get_plugin_context("my_plugin")
```

### 上下文功能
```python
# 配置访问
config = context.config  # 获取插件配置

# 日志记录
context.logger.info("插件启动")
context.logger.error("发生错误")

# 数据目录
data_dir = context.data_dir   # ~/.dfecrab/plugins/my_plugin
cache_dir = context.cache_dir  # ~/.dfecrab/cache/plugins/my_plugin

# 核心服务访问
memory_manager = context.get_memory_manager()
session_manager = context.get_session_manager()
agent_manager = context.get_agent_manager()
skill_manager = context.get_skill_manager()

# 事件系统
subscription_id = context.subscribe_event("message.received", on_message_received)
context.publish_event("my_plugin.custom_event", {"data": "value"})
context.unsubscribe_event(subscription_id)

# 服务注册和获取
context.register_service("my_service", my_service_instance)
service = context.get_service("my_service")
```

## 插件注册表

### 获取插件注册表
```python
from src.plugins.registry import get_plugin_registry

registry = get_plugin_registry()
```

### 注册表功能
```python
# 插件发现
plugins = registry.list_plugins()           # 列出所有插件
loaded = registry.list_loaded_plugins()     # 列出已加载的插件
running = registry.list_running_plugins()   # 列出正在运行的插件

# 插件获取
plugin = registry.get("agent")               # 获取插件实例
metadata = registry.get_metadata("agent")    # 获取插件元数据

# 依赖检查
missing = registry.check_dependencies("my_plugin")  # 检查未满足的依赖
dependents = registry.get_dependent_plugins("agent")  # 获取依赖该插件的其他插件

# 工具和记忆提示词
tools = registry.get_tools_from_all_plugins()        # 从所有插件获取工具
prompts = registry.get_memory_prompts_from_all_plugins()  # 从所有插件获取记忆提示词

# 事件钩子
registry.register_hook("agent.created", on_agent_created)
await registry.trigger_hook("agent.created", agent_id="123")
```

## 插件加载器

### 获取插件加载器
```python
from src.plugins.loader import get_plugin_loader

loader = get_plugin_loader()
```

### 加载器功能
```python
# 加载插件
count = await loader.load_all()  # 加载所有插件
success = await loader.load_plugin("my_plugin", plugin_path)

# 卸载和重新加载
success = await loader.unload_plugin("my_plugin")
success = await loader.reload_plugin("my_plugin")

# 列出可用插件
available = loader.list_available_plugins()  # ["builtin/agent", "builtin/skill", ...]
```

## 插件开发示例

### 1. 创建插件目录结构
```
plugins/thirdparty/my_plugin/
├── __init__.py      # 插件入口文件
├── config.json      # 插件配置（可选）
└── README.md        # 插件文档（可选）
```

### 2. 实现插件类
```python
# plugins/thirdparty/my_plugin/__init__.py
from src.plugins.base import BasePlugin, PluginMetadata, ToolDefinition
from src.plugins.context import create_plugin_context

# 插件全局实例
plugin = None

class MyPlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.context = None
    
    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="my_plugin",
            version="1.0.0",
            author="Developer",
            description="示例插件",
            tags=["example", "demo"],
            dependencies=["skill"]  # 依赖技能插件
        )
    
    async def on_load(self) -> bool:
        # 创建插件上下文
        self.context = create_plugin_context(self.get_metadata().name)
        self.context.logger.info("插件正在加载...")
        return True
    
    async def on_start(self) -> bool:
        self.context.logger.info("插件已启动")
        
        # 注册工具
        self._register_tools()
        
        # 订阅事件
        self.context.subscribe_event("message.received", self._on_message)
        return True
    
    async def on_stop(self) -> bool:
        self.context.logger.info("插件已停止")
        return True
    
    def _register_tools(self):
        """注册插件提供的工具"""
        # 在插件中定义工具函数
        pass
    
    def get_tools(self) -> List[ToolDefinition]:
        """返回工具定义"""
        return [
            ToolDefinition(
                name="my_tool",
                description="我的自定义工具",
                parameters={
                    "param1": {"type": "string", "description": "参数1"}
                }
            )
        ]
    
    async def _on_message(self, message):
        """处理消息事件"""
        self.context.logger.debug(f"收到消息: {message}")

# 创建插件实例
plugin = MyPlugin()
```

### 3. 安装插件
```bash
# 将插件目录复制到插件目录
cp -r my_plugin ~/.dfecrab/plugins/thirdparty/
```

### 4. 加载插件
可以通过以下方式加载插件：

**通过 Gateway API:**
```bash
# 列出可用插件
curl http://localhost:8000/api/plugins

# 重新加载特定插件
curl -X POST http://localhost:8000/api/plugins/my_plugin/reload

# 重新加载所有插件
curl -X POST http://localhost:8000/api/plugins/reload
```

**通过代码:**
```python
from src.plugins.loader import get_plugin_loader

loader = get_plugin_loader()
await loader.load_all()  # 加载所有插件
```

## 插件配置

### 配置文件
插件可以通过 `config.json` 文件配置：
```json
{
  "my_setting": "value",
  "enabled": true,
  "max_retries": 3
}
```

### 访问配置
```python
# 通过上下文访问
config = context.config
my_setting = config.get("my_setting", "default")

# 或通过全局配置
from src.config.config import config
plugin_config = config.get("plugins", {}).get("my_plugin", {})
```

## 最佳实践

### 1. 错误处理
```python
async def on_load(self) -> bool:
    try:
        # 初始化逻辑
        return True
    except Exception as e:
        self.context.logger.error(f"加载失败: {e}")
        return False
```

### 2. 资源管理
```python
async def on_start(self):
    # 启动时分配资源
    self._connect_database()
    self._start_background_task()

async def on_stop(self):
    # 停止时释放资源
    self._disconnect_database()
    self._stop_background_task()
```

### 3. 依赖管理
```python
def _create_metadata(self):
    return PluginMetadata(
        name="my_plugin",
        dependencies=[
            "agent",    # 需要智能体插件
            "memory",   # 需要记忆插件
            "skill"     # 需要技能插件
        ]
    )
```

### 4. 事件驱动设计
```python
async def on_start(self):
    # 订阅核心事件
    self._message_sub = self.context.subscribe_event("message.received", self._on_message)
    self._agent_sub = self.context.subscribe_event("agent.created", self._on_agent_created)

async def on_stop(self):
    # 取消订阅
    if self._message_sub:
        self.context.unsubscribe_event(self._message_sub)
```

## API 参考

### PluginInterface
- `get_metadata() -> PluginMetadata`
- `load() -> bool`
- `unload() -> bool`
- `initialize() -> bool`
- `start() -> bool`
- `stop() -> bool`
- `get_tools() -> List[ToolDefinition]`
- `get_memory_prompts() -> Dict[str, str]`

### PluginContext
- `config: Dict[str, Any]` - 插件配置
- `logger` - 日志器
- `data_dir: Path` - 数据目录
- `cache_dir: Path` - 缓存目录
- `get_memory_manager()` - 获取记忆管理器
- `get_session_manager()` - 获取会话管理器
- `get_agent_manager()` - 获取智能体管理器
- `get_skill_manager()` - 获取技能管理器
- `publish_event(event_type, data)` - 发布事件
- `subscribe_event(event_type, callback, filter_func)` - 订阅事件
- `unsubscribe_event(subscription_id)` - 取消订阅

### PluginRegistry
- `register(plugin, dependencies) -> bool`
- `unregister(name) -> bool`
- `get(name) -> Optional[PluginInterface]`
- `get_metadata(name) -> Optional[PluginMetadata]`
- `list_plugins() -> List[PluginMetadata]`
- `list_loaded_plugins() -> List[str]`
- `list_running_plugins() -> List[str]`
- `has_plugin(name) -> bool`
- `check_dependencies(name) -> List[str]`
- `get_dependent_plugins(name) -> List[str]`
- `register_hook(event, callback)`
- `trigger_hook(event, *args, **kwargs)`
- `get_tools_from_all_plugins() -> List[Dict[str, Any]]`
- `get_memory_prompts_from_all_plugins() -> Dict[str, str]`

### PluginLoader
- `load_all() -> int`
- `load_plugin(name, plugin_path) -> bool`
- `unload_plugin(name) -> bool`
- `reload_plugin(name) -> bool`
- `list_available_plugins() -> List[str]`

## 常见问题

### 1. 插件加载失败
**问题:** 插件加载时出现 `ModuleNotFoundError`

**解决方案:**
- 检查插件目录结构是否正确
- 确保 `__init__.py` 文件存在
- 检查依赖插件是否已加载

### 2. 工具未显示
**问题:** 插件工具在列表中不可见

**解决方案:**
- 确认插件已成功启动（状态为 RUNNING）
- 检查 `get_tools()` 方法是否正确返回工具定义
- 确认工具名称没有冲突

### 3. 配置不生效
**问题:** 插件配置未正确加载

**解决方案:**
- 检查 `config.json` 文件格式是否正确
- 确认配置文件位于插件根目录
- 通过 `context.config` 访问配置而不是全局配置

### 4. 事件未触发
**问题:** 插件订阅的事件未触发

**解决方案:**
- 确认事件名称拼写正确
- 检查事件发布者是否正常工作
- 确认订阅发生在插件启动之后

## 调试插件

### 启用调试日志
```python
import logging
logging.getLogger("plugin.my_plugin").setLevel(logging.DEBUG)
```

### 检查插件状态
```python
from src.plugins.registry import get_plugin_registry

registry = get_plugin_registry()
plugin = registry.get("my_plugin")
metadata = registry.get_metadata("my_plugin")

print(f"插件状态: {metadata.state}")
print(f"依赖检查: {registry.check_dependencies('my_plugin')}")
```

### 手动加载插件
```python
from src.plugins.loader import get_plugin_loader
import asyncio

async def test_plugin():
    loader = get_plugin_loader()
    success = await loader.load_plugin("my_plugin", Path("path/to/my_plugin"))
    print(f"加载结果: {success}")

asyncio.run(test_plugin())
```

## 更新日志
- v1.0.0: 初始插件系统发布
- v1.1.0: 添加 PluginContext 支持
- v1.2.0: 增强事件系统支持
- v1.3.0: 添加工具自动注册功能