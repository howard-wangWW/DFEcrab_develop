# Hello Plugin - DFEcrab 插件示例

## 概述

这是一个 DFEcrab 插件系统的示例插件，展示了如何创建、配置和使用插件。

## 功能特性

- ✅ **完整的生命周期管理**: 加载、启动、停止、卸载
- ✅ **工具注册**: 提供多个自定义工具供智能体使用
- ✅ **事件系统**: 订阅和发布事件
- ✅ **配置管理**: 通过配置文件自定义插件行为
- ✅ **后台任务**: 演示如何运行后台任务
- ✅ **统计信息**: 提供插件使用统计
- ✅ **依赖管理**: 声明依赖其他插件

## 目录结构

```
hello_plugin/
├── __init__.py      # 插件主文件
├── config.json      # 插件配置文件
└── README.md        # 插件文档
```

## 安装和使用

### 1. 安装插件

```bash
# 将插件复制到插件目录
cp -r hello_plugin ~/.dfecrab/plugins/thirdparty/

# 或创建软链接
ln -s $(pwd)/hello_plugin ~/.dfecrab/plugins/thirdparty/hello
```

### 2. 加载插件

插件会在系统启动时自动加载，也可以通过 API 手动加载：

```bash
# 重新加载所有插件
curl -X POST http://localhost:8000/api/plugins/reload

# 重新加载特定插件
curl -X POST http://localhost:8000/api/plugins/hello/reload
```

### 3. 验证插件状态

```bash
# 列出所有插件
curl http://localhost:8000/api/plugins

# 获取插件详情
curl http://localhost:8000/api/plugins/hello
```

### 4. 使用插件工具

插件提供了以下工具：

1. **hello_say_hello** - 打招呼工具
   ```python
   # 参数
   name: str = "World"    # 姓名
   times: int = 1        # 重复次数
   
   # 使用示例
   result = await hello_say_hello(name="Alice", times=3)
   # 返回: "你好, Alice! 你好, Alice! 你好, Alice!"
   ```

2. **hello_get_stats** - 获取统计信息
   ```python
   # 参数
   reset: bool = False   # 是否重置计数器
   
   # 使用示例
   stats = await hello_get_stats()
   # 返回: {"plugin_name": "hello", "message_count": 42, ...}
   ```

3. **hello_trigger_event** - 触发自定义事件
   ```python
   # 参数
   event_type: str = "hello.custom"
   message: str = "Hello from plugin!"
   
   # 使用示例
   success = await hello_trigger_event(event_type="hello.test", message="Hello World!")
   ```

## 配置选项

在 `config.json` 文件中可以配置：

```json
{
  "greeting": "你好",           // 问候语
  "max_count": 500,             // 最大消息计数
  "enable_background_task": true, // 是否启用后台任务
  "log_level": "INFO",          // 日志级别
  "auto_start": true            // 是否自动启动
}
```

## 事件系统

### 订阅的事件
- **message.received**: 监听默认智能体的消息

### 发布的事件
- **hello.started**: 插件启动时
- **hello.stopped**: 插件停止时
- **hello.milestone**: 每收到10条消息时
- **hello.agent_started**: 智能体启动时
- **hello.agent_stopped**: 智能体停止时
- **hello.custom**: 通过工具触发

## 开发指南

### 1. 插件生命周期

```python
class HelloPlugin(BasePlugin):
    async def on_load(self) -> bool:
        # 插件加载时调用
        return True
    
    async def on_start(self) -> bool:
        # 插件启动时调用
        return True
    
    async def on_stop(self) -> bool:
        # 插件停止时调用
        return True
```

### 2. 注册工具

```python
def get_tools(self) -> List[ToolDefinition]:
    return [
        ToolDefinition(
            name="tool_name",
            description="工具描述",
            parameters={
                "param1": {"type": "string", "description": "参数描述"}
            }
        )
    ]
```

### 3. 使用插件上下文

```python
# 获取上下文
context = create_plugin_context("hello")

# 访问配置
config = context.config

# 记录日志
context.logger.info("信息")

# 使用数据目录
data_file = context.data_dir / "data.json"

# 订阅事件
context.subscribe_event("event.type", handler)

# 发布事件
context.publish_event("event.type", data)
```

### 4. 处理依赖

```python
def _create_metadata(self) -> PluginMetadata:
    return PluginMetadata(
        name="hello",
        dependencies=["skill"]  # 依赖技能插件
    )
```

## 调试和故障排除

### 查看插件日志

```python
import logging
logging.getLogger("plugin.hello").setLevel(logging.DEBUG)
```

### 检查插件状态

```python
from src.plugins.registry import get_plugin_registry

registry = get_plugin_registry()
plugin = registry.get("hello")
metadata = registry.get_metadata("hello")

print(f"状态: {metadata.state}")
print(f"依赖: {metadata.dependencies}")
```

### 手动测试工具

```python
async def test_tool():
    from src.plugins.registry import get_plugin_registry
    
    registry = get_plugin_registry()
    hello_plugin = registry.get("hello")
    
    if hello_plugin:
        result = await hello_plugin.hello_say_hello(name="Test")
        print(f"结果: {result}")
```

## 扩展插件

### 添加新工具

1. 在 `get_tools()` 方法中添加工具定义
2. 实现对应的异步方法
3. 方法名需与工具名一致

### 添加新事件

1. 在适当的地方调用 `context.publish_event()`
2. 在其他插件中订阅这些事件

### 添加配置项

1. 在 `config.json` 中添加配置项
2. 在 `on_load()` 方法中读取配置

## API 参考

### 工具 API
- `hello_say_hello(name: str, times: int) -> str`
- `hello_get_stats(reset: bool) -> Dict[str, Any]`
- `hello_trigger_event(event_type: str, message: str) -> bool`

### 配置 API
- 通过 `context.config` 访问配置
- 支持 JSON 格式配置文件

### 事件 API
- `context.subscribe_event(event_type, callback, filter_func) -> str`
- `context.publish_event(event_type, data)`
- `context.unsubscribe_event(subscription_id) -> bool`

## 许可证

MIT License