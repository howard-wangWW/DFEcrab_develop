# DFEcrab 插件开发指南

## 概述

DFEcrab 插件系统采用 **微内核架构**，所有核心功能都通过插件实现。插件系统提供完整的生命周期管理、依赖解析、事件订阅、工具注册等功能。本指南将引导你开发自己的 DFEcrab 插件。

### 设计理念
- **松耦合**：插件通过事件和上下文通信，避免硬编码依赖
- **热插拔**：插件可在运行时加载、卸载、重载，无需重启系统
- **模块化**：核心功能分解为独立插件，易于维护和扩展
- **向后兼容**：现有 API 保持不变，插件可无缝集成

### 核心组件
- **Kernel（内核）**：管理插件生命周期和系统服务
- **EventBus（事件总线）**：插件间异步通信机制
- **PluginContext（插件上下文）**：插件访问核心系统的统一接口
- **PluginRegistry（插件注册表）**：插件的全局注册和发现中心

## 快速开始

### 创建一个简单的插件

让我们创建一个简单的 "Hello World" 插件：

1. **创建插件目录结构**
   ```bash
   mkdir -p ~/.dfecrab/plugins/thirdparty/hello_plugin
   cd ~/.dfecrab/plugins/thirdparty/hello_plugin
   ```

2. **创建插件入口文件** (`__init__.py`)
   ```python
   from src.plugins.base import BasePlugin, PluginMetadata, ToolDefinition
   from src.plugins.context import create_plugin_context
   
   # 插件全局实例
   plugin = None
   
   class HelloPlugin(BasePlugin):
       def __init__(self):
           super().__init__()
           self.context = None
       
       def _create_metadata(self) -> PluginMetadata:
           return PluginMetadata(
               name="hello_plugin",
               version="1.0.0",
               author="Your Name",
               description="一个简单的 Hello World 插件",
               tags=["example", "demo"],
               dependencies=["skill"]  # 依赖技能插件
           )
       
       async def on_load(self) -> bool:
           """插件加载回调"""
           self.context = create_plugin_context(self.get_metadata().name)
           self.context.logger.info("HelloPlugin 正在加载...")
           return True
       
       async def on_start(self) -> bool:
           """插件启动回调"""
           self.context.logger.info("HelloPlugin 已启动")
           return True
       
       async def on_stop(self) -> bool:
           """插件停止回调"""
           self.context.logger.info("HelloPlugin 已停止")
           return True
       
       def get_tools(self) -> List[ToolDefinition]:
           """返回工具定义"""
           return [
               ToolDefinition(
                   name="hello",
                   description="打招呼的工具",
                   parameters={
                       "name": {"type": "string", "description": "要打招呼的名字"}
                   }
               )
           ]
   
   # 创建插件实例
   plugin = HelloPlugin()
   ```

3. **创建插件配置文件** (`config.json`，可选)
   ```json
   {
     "greeting": "你好",
     "enabled": true
   }
   ```

4. **手动加载插件**
   ```python
   from src.plugins.loader import get_plugin_loader
   import asyncio
   
   async def test():
       loader = get_plugin_loader()
       success = await loader.load_plugin("hello_plugin", 
                                          "~/.dfecrab/plugins/thirdparty/hello_plugin")
       print(f"加载结果: {success}")
   
   asyncio.run(test())
   ```

## 插件生命周期

插件的生命周期由以下状态组成：

```
UNLOADED → LOADING → LOADED → RUNNING → STOPPING → STOPPED
        ↖─────────────────────────────↗
               ERROR（出错时）
```

### 生命周期回调方法

| 回调方法 | 触发时机 | 典型用途 |
|---------|----------|----------|
| `on_load()` | 插件加载时 | 初始化资源，加载配置 |
| `on_start()` | 插件启动时 | 启动服务，注册工具，订阅事件 |
| `on_stop()` | 插件停止时 | 清理资源，取消订阅 |
| `on_unload()` | 插件卸载时 | 释放所有资源 |

### 示例
```python
class MyPlugin(BasePlugin):
    async def on_load(self) -> bool:
        # 1. 加载配置
        self.config = self.context.config
        
        # 2. 初始化资源
        self.db = await self._connect_database()
        
        return True
    
    async def on_start(self) -> bool:
        # 1. 启动后台任务
        self._task = asyncio.create_task(self._background_worker())
        
        # 2. 注册工具
        self._register_tools()
        
        # 3. 订阅核心事件
        self._sub_id = self.context.subscribe_event("agent.created", 
                                                    self._on_agent_created)
        
        return True
    
    async def on_stop(self) -> bool:
        # 1. 取消事件订阅
        if self._sub_id:
            self.context.unsubscribe_event(self._sub_id)
        
        # 2. 停止后台任务
        if self._task:
            self._task.cancel()
        
        # 3. 关闭数据库连接
        if self.db:
            await self.db.close()
        
        return True
```

## 插件上下文

`PluginContext` 是插件访问核心系统的统一接口。

### 创建和获取上下文

```python
from src.plugins.context import create_plugin_context, get_plugin_context

# 在插件中创建上下文（通常在 on_load 中）
self.context = create_plugin_context(self.get_metadata().name)

# 在其他地方获取上下文
context = get_plugin_context("my_plugin")
```

### 上下文功能

```python
# 1. 配置访问
config = self.context.config
my_setting = config.get("my_setting", "default")

# 2. 日志记录
self.context.logger.debug("调试信息")
self.context.logger.info("插件已启动")
self.context.logger.warning("警告信息")
self.context.logger.error("错误信息")

# 3. 目录管理
data_dir = self.context.data_dir   # ~/.dfecrab/plugins/my_plugin
cache_dir = self.context.cache_dir  # ~/.dfecrab/cache/plugins/my_plugin

# 4. 核心服务访问
memory_manager = self.context.get_memory_manager()
session_manager = self.context.get_session_manager()
agent_manager = self.context.get_agent_manager()
skill_manager = self.context.get_skill_manager()

# 5. 事件系统
# 发布事件
self.context.publish_event("my_plugin.custom_event", {"data": "value"})

# 订阅事件
subscription_id = self.context.subscribe_event("message.received", 
                                               self._on_message)

# 取消订阅
self.context.unsubscribe_event(subscription_id)

# 6. 服务注册和获取
self.context.register_service("my_service", MyService())
service = self.context.get_service("my_service")
```

## 工具注册

插件可以通过 `get_tools()` 方法向系统注册工具。这些工具将自动添加到智能体的工具包中。

### 工具定义

```python
from src.plugins.base import ToolDefinition

def get_tools(self) -> List[ToolDefinition]:
    return [
        ToolDefinition(
            name="my_tool",                      # 工具名称
            description="我的自定义工具",          # 工具描述
            parameters={                          # 参数定义
                "param1": {
                    "type": "string",            # 参数类型
                    "description": "参数1描述",   # 参数描述
                    "required": True             # 是否必需
                },
                "param2": {
                    "type": "integer",
                    "description": "参数2描述",
                    "required": False,
                    "default": 42                # 默认值
                }
            }
        )
    ]
```

### 工具实现

工具函数的实现需要遵循以下约定：

```python
from src.plugins.base import PluginTool

class MyPlugin(BasePlugin):
    def get_tools(self) -> List[ToolDefinition]:
        return [
            ToolDefinition(
                name="calculate_sum",
                description="计算两个数的和",
                parameters={
                    "a": {"type": "number", "description": "第一个数", "required": True},
                    "b": {"type": "number", "description": "第二个数", "required": True}
                }
            )
        ]
    
    @PluginTool("calculate_sum")
    async def calculate_sum_tool(self, a: float, b: float) -> dict:
        """工具实现函数"""
        result = a + b
        return {"result": result}
```

## 事件系统

DFEcrab 使用事件总线实现插件间松耦合通信。

### 核心事件

| 事件类型 | 触发时机 | 事件数据 |
|---------|----------|----------|
| `plugin.loaded` | 插件加载完成 | `{"plugin_name": "plugin", "metadata": {...}}` |
| `plugin.started` | 插件启动完成 | `{"plugin_name": "plugin", "metadata": {...}}` |
| `agent.created` | 智能体创建时 | `{"agent_id": "id", "agent_name": "name"}` |
| `message.received` | 收到消息时 | `{"session_id": "id", "message": {...}, "from": "user"}` |
| `skill.loaded` | 技能加载时 | `{"skill_name": "name", "skill_path": "path"}` |

### 订阅事件

```python
class MyPlugin(BasePlugin):
    async def on_start(self) -> bool:
        # 订阅单个事件
        self._msg_sub = self.context.subscribe_event(
            "message.received",
            self._on_message_received
        )
        
        # 订阅通配符事件
        self._plugin_sub = self.context.subscribe_event(
            "plugin.*",
            self._on_plugin_event
        )
        
        return True
    
    async def _on_message_received(self, data):
        """处理消息事件"""
        self.context.logger.info(f"收到消息: {data['message']}")
```

### 发布自定义事件

```python
# 发布简单事件
self.context.publish_event("my_plugin.task_started", {"task_id": "123"})
```

## 配置管理

插件支持多层配置：全局配置 → 项目配置 → 用户配置 → 插件配置。

### 配置文件结构

1. **全局配置** (`~/.dfecrab/config.json`)
2. **项目配置** (`项目目录/.dfecrab/config.json`)
3. **用户配置** (`~/.dfecrab/plugins/my_plugin/config.json`)
4. **插件默认配置** (插件目录中的 `config.json`)

### 访问配置

```python
class MyPlugin(BasePlugin):
    async def on_load(self) -> bool:
        # 通过上下文访问配置
        config = self.context.config
        
        # 获取配置值（带默认值）
        enabled = config.get("enabled", True)
        max_retries = config.get("max_retries", 3)
        endpoint = config.get("api_endpoint")
        
        # 验证必需配置
        if not endpoint:
            self.context.logger.error("缺少必需的 api_endpoint 配置")
            return False
        
        return True
```

## 依赖管理

插件可以声明对其他插件的依赖，系统会自动按依赖顺序加载。

### 声明依赖

```python
class MyPlugin(BasePlugin):
    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="my_plugin",
            version="1.0.0",
            dependencies=[
                "memory",   # 依赖记忆插件
                "agent",    # 依赖智能体插件
                "skill",    # 依赖技能插件
                "mcp"       # 依赖 MCP 插件
            ]
        )
```

### 访问依赖插件

插件可以通过注册表访问其依赖的插件实例：

```python
class SkillPlugin(BasePlugin):
    async def on_start(self) -> bool:
        # 获取插件注册表
        from src.plugins.registry import get_plugin_registry
        registry = get_plugin_registry()
        
        # 获取依赖的插件实例
        memory_plugin = registry.get("memory")
        agent_plugin = registry.get("agent")
        mcp_plugin = registry.get("mcp")
        
        if not mcp_plugin:
            self.context.logger.warning("MCP 插件未找到")
            self._mcp_plugin = None
        else:
            self._mcp_plugin = mcp_plugin
        
        return True
```

## 测试插件

### 单元测试

为插件编写单元测试：

```python
# tests/plugins/test_my_plugin.py
import unittest
from unittest.mock import Mock
from src.plugins.base import PluginMetadata

class TestMyPlugin(unittest.TestCase):
    def setUp(self):
        from plugins.thirdparty.my_plugin import plugin
        self.plugin = plugin
        self.plugin.context = Mock()
        self.plugin.context.logger = Mock()
    
    def test_metadata_creation(self):
        """测试插件元数据"""
        metadata = self.plugin.get_metadata()
        self.assertEqual(metadata.name, "my_plugin")
        self.assertEqual(metadata.version, "1.0.0")
        self.assertIn("memory", metadata.dependencies)
    
    def test_tool_registration(self):
        """测试工具注册"""
        tools = self.plugin.get_tools()
        self.assertGreater(len(tools), 0)
        tool_names = [t.name for t in tools]
        self.assertIn("my_tool", tool_names)
```

### 集成测试

```python
# tests/integration/test_plugin_integration.py
import unittest
import asyncio
from src.core.kernel import Kernel

class TestPluginIntegration(unittest.TestCase):
    def setUp(self):
        self.kernel = Kernel()
    
    async def asyncSetUp(self):
        await self.kernel.start()
    
    async def asyncTearDown(self):
        await self.kernel.stop()
    
    async def test_plugin_loading(self):
        """测试插件加载集成"""
        plugins = self.kernel.list_plugins()
        self.assertGreater(len(plugins), 0)
        
        plugin_names = [p.name for p in plugins]
        self.assertIn("memory", plugin_names)
        self.assertIn("agent", plugin_names)
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

### 3. 性能优化
- 使用异步 I/O 操作
- 缓存频繁访问的数据
- 批量处理操作

### 4. 安全性
- 验证输入参数
- 限制资源使用
- 记录敏感操作

## 发布插件

### 1. 打包插件
```bash
# 创建插件包
cd hello_plugin
tar -czf hello_plugin-v1.0.0.tar.gz __init__.py config.json README.md
```

### 2. 发布到 ClawHub
```json
{
  "name": "hello_plugin",
  "version": "1.0.0",
  "description": "一个简单的 Hello World 插件",
  "author": "Your Name",
  "dependencies": ["skill"],
  "download_url": "https://example.com/hello_plugin-v1.0.0.tar.gz"
}
```

### 3. 安装插件
```bash
# 通过 ClawHub 安装
curl -X POST http://localhost:8000/api/skills/install \
  -H "Content-Type: application/json" \
  -d '{"skill_name": "hello_plugin", "skill_url": "https://example.com/hello_plugin-v1.0.0.tar.gz"}'
```

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
- 通过 `context.config` 访问配置

### 4. 事件未触发
**问题:** 插件订阅的事件未触发

**解决方案:**
- 确认事件名称拼写正确
- 检查事件发布者是否正常工作
- 确认订阅发生在插件启动之后

---

## 下一步

- 查看 [API 参考](/docs/plugins/api.md) 了解详细接口
- 参考 [内置插件](/src/plugins/builtin/) 的实现
- 尝试修改 [示例插件](/examples/hello_plugin/) 添加新功能