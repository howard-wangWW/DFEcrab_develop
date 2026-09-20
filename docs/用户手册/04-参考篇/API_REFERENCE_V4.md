# DFEcrab API 参考 V4

## 记忆系统 API

### FourLayerMemoryManager

四层记忆管理器，管理企业、项目、自动、用户四个层级的记忆。

#### 初始化

```python
from src.core.memory.v4 import FourLayerMemoryManager, create_memory_manager

# 方式1：直接创建
manager = FourLayerMemoryManager(
    base_dir=Path("/path/to/project"),
    runtime_dir=Path("~/.dfecrab")
)

# 方式2：便捷函数
manager = create_memory_manager(
    base_dir="/path/to/project",
    runtime_dir="~/.dfecrab"
)
```

#### 方法

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `load_all(force_reload)` | force_reload: bool | List[MemoryContent] | 加载所有记忆层 |
| `merge(include_empty)` | include_empty: bool | MergedMemory | 合并所有记忆 |
| `get_system_prompt()` | - | str | 获取系统提示词 |
| `observe(observation)` | observation: str | None | 记录观察 |
| `update_auto_memory(force)` | force: bool | bool | 更新自动记忆 |
| `create_layer_file(level, content)` | level: MemoryLevel, content: str | bool | 创建记忆文件 |
| `compact_auto_memory()` | - | bool | 压缩自动记忆 |
| `get_status()` | - | Dict | 获取系统状态 |

### MemoryLevel

记忆层级枚举：

```python
from src.core.memory.v4 import MemoryLevel

# 层级定义
MemoryLevel.ENTERPRISE  # 4 - 企业策略
MemoryLevel.PROJECT     # 3 - 项目记忆
MemoryLevel.AUTO        # 2 - 自动记忆
MemoryLevel.USER        # 1 - 用户记忆

# 获取优先级
level = MemoryLevel.PROJECT
level.priority  # 返回 3
level.display_name  # 返回 "项目记忆"
```

### 条件规则

```python
from src.core.memory.v4.rules import (
    ConditionalRule,
    RuleRegistry,
    RuleLoader
)

# 创建规则
rule = ConditionalRule(
    name="Python 规则",
    description="Python 文件规则",
    applies_to=["**/*.py"],
    content="遵循 PEP 8 规范"
)

# 使用注册表
registry = RuleRegistry()
registry.register(rule)

# 获取适用规则
rules = registry.get_applicable_rules("src/main.py")

# 从目录加载规则
rules = RuleLoader.load_from_directory(Path(".claude/rules"))
```

---

## 插件系统 API

### PluginManagerV2

插件管理器 V2，管理插件的加载、注册和执行。

#### 初始化

```python
from src.core.plugins.v2 import PluginManagerV2, create_plugin_manager

# 方式1：直接创建
manager = PluginManagerV2(plugins_dir=Path("plugins"))

# 方式2：便捷函数
manager = create_plugin_manager(plugins_dir="plugins")
```

#### 异步方法

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `discover_plugins()` | - | List[Path] | 发现所有插件 |
| `load_plugin(plugin_path)` | plugin_path: Path | PluginManifest | 加载单个插件 |
| `load_all_plugins()` | - | Dict[str, bool] | 加载所有插件 |
| `execute_command(name, context)` | name: str, context: Dict | Dict | 执行命令 |
| `execute_hooks(type, context)` | type: HookType, context: Dict | List[Dict] | 执行钩子 |

#### 同步方法

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `get_command_suggestions(prefix)` | prefix: str | List[str] | 获取命令建议 |
| `get_status()` | - | Dict | 获取系统状态 |

### PluginManifest

插件清单数据类：

```python
from src.core.plugins.v2 import PluginManifest, CommandSpec, AgentSpec

# 从字典创建
manifest = PluginManifest.from_dict({
    "name": "my-plugin",
    "version": "1.0.0",
    "commands": [
        {"name": "deploy", "description": "部署"}
    ]
})

# 转换为字典
data = manifest.to_dict()
```

### HookType

钩子类型枚举：

```python
from src.core.plugins.v2 import HookType

HookType.SESSION_START   # 会话开始
HookType.SESSION_END     # 会话结束
HookType.PRE_TOOL_USE    # 工具调用前
HookType.POST_TOOL_USE   # 工具调用后
HookType.PRE_COMMIT      # 提交前
HookType.POST_COMMIT     # 提交后
HookType.ON_ERROR        # 错误时
HookType.ON_MEMORY_UPDATE # 记忆更新时
```

---

## 工具系统 API

### ToolExecutor

工具执行器，统一管理工具的调用和执行。

#### 初始化

```python
from src.core.tools import ToolExecutor, ToolExecutionContext

# 创建执行器
executor = ToolExecutor()
```

#### 方法

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `execute(tool_name, params, context)` | tool_name: str, params: Dict, context: ToolExecutionContext | ToolResult | 执行工具 |
| `get_tool_schemas()` | - | List[Dict] | 获取工具 Schema |

### ToolExecutionContext

工具执行上下文：

```python
from src.core.tools import ToolExecutionContext, PermissionLevel

context = ToolExecutionContext(
    agent_id="agent_001",
    session_id="session_001",
    user_id="user_001",
    working_directory=Path("/path/to/project"),
    environment={"DEBUG": "1"},
    permissions=[
        PermissionLevel.READ,
        PermissionLevel.WRITE,
        PermissionLevel.EXECUTE
    ]
)
```

### ToolResult

工具执行结果：

```python
from src.core.tools import ToolResult, ToolStatus

result = await executor.execute("FileRead", {"file_path": "README.md"}, context)

# 属性
result.success       # bool - 是否成功
result.status        # ToolStatus - 状态枚举
result.output        # Any - 输出内容
result.error         # Optional[str] - 错误信息
result.execution_time_ms  # float - 执行时间
result.metadata      # Dict - 元数据
```

### PermissionLevel

权限级别枚举：

```python
from src.core.tools import PermissionLevel

PermissionLevel.READ      # 只读权限
PermissionLevel.WRITE     # 写入权限
PermissionLevel.EXECUTE   # 执行权限
PermissionLevel.ADMIN     # 管理员权限
```

### ToolStatus

工具状态枚举：

```python
from src.core.tools import ToolStatus

ToolStatus.SUCCESS           # 成功
ToolStatus.ERROR             # 错误
ToolStatus.TIMEOUT           # 超时
ToolStatus.PERMISSION_DENIED # 权限拒绝
ToolStatus.CANCELLED         # 已取消
```

### ToolRegistry

工具注册表：

```python
from src.core.tools import ToolRegistry

# 创建注册表（自动加载内置和扩展工具）
registry = ToolRegistry()

# 方法
registry.register(tool)       # 注册工具
registry.unregister(name)     # 注销工具
registry.get(name)            # 获取工具
registry.list_tools()         # 列出所有工具
registry.get_definitions()    # 获取所有定义
```

---

## 内置工具参数参考

### FileRead

```python
{
    "file_path": "path/to/file",  # 必需
    "offset": 0,                   # 可选，起始行号
    "limit": 2000                  # 可选，读取行数
}
```

### FileEdit

```python
{
    "file_path": "path/to/file",  # 必需
    "old_string": "原文本",        # 必需
    "new_string": "新文本",        # 必需
    "replace_all": false           # 可选，是否替换全部
}
```

### FileWrite

```python
{
    "file_path": "path/to/file",  # 必需
    "content": "文件内容",         # 必需
    "mode": "write",              # 可选，write/append
    "create_dirs": true           # 可选，是否创建目录
}
```

### Glob

```python
{
    "pattern": "**/*.py",  # 必需，glob模式
    "path": ".",           # 可选，搜索目录
    "limit": 100           # 可选，结果数量限制
}
```

### Grep

```python
{
    "pattern": "search_term",  # 必需，正则表达式
    "path": ".",               # 可选，搜索路径
    "glob": "*.py",            # 可选，文件过滤
    "case_sensitive": true,    # 可选，区分大小写
    "context": 0               # 可选，上下文行数
}
```

### Bash

```python
{
    "command": "ls -la",   # 必需
    "timeout": 120000,     # 可选，超时毫秒
    "cwd": "."             # 可选，工作目录
}
```

### WebFetch

```python
{
    "url": "https://example.com",  # 必需
    "prompt": "提取主要内容",       # 可选
    "raw": false,                  # 可选，返回原始HTML
    "timeout": 30                  # 可选，超时秒数
}
```

### WebSearch

```python
{
    "query": "search query",   # 必需
    "max_results": 5,          # 可选，最大结果数
    "engine": "duckduckgo"     # 可选，搜索引擎
}
```

### TaskCreate

```python
{
    "subject": "任务标题",      # 必需
    "description": "任务描述",  # 必需
    "priority": "normal",      # 可选，low/normal/high/critical
    "due_date": "2026-04-30"   # 可选，截止日期
}
```

### TaskList

```python
{
    "status": "all",   # 可选，pending/in_progress/completed/all
    "limit": 20        # 可选，结果数量限制
}
```

---

*API 版本: 4.0.0*
*更新时间: 2026-04-02*
