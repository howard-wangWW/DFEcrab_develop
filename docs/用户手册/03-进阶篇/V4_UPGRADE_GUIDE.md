# DFEcrab V4 改进文档

> 基于 Claude Code 架构的深度优化

---

## 一、四层记忆系统

### 概述

DFEcrab 现在支持 4 层优先级记忆体系，参考 Claude Code 的记忆架构设计：

```
┌─────────────────────────────────────────┐
│ Level 4: 企业策略 (最高优先级)           │
│ ~/.dfecrab/enterprise.md                 │
├─────────────────────────────────────────┤
│ Level 3: 项目记忆 (高优先级)             │
│ ./DFECRAB.md                             │
├─────────────────────────────────────────┤
│ Level 2: 自动记忆 (动态优先级)           │
│ .dfecrab/memory/MEMORY.md                │
├─────────────────────────────────────────┤
│ Level 1: 用户记忆 (基础优先级)           │
│ ~/.dfecrab/user.md                       │
└─────────────────────────────────────────┘
```

### 使用方法

#### 1. 创建项目记忆

在项目根目录创建 `DFECRAB.md`：

```markdown
# 项目记忆

## 技术栈
- Python 3.8+
- FastAPI

## 约定
- 使用类型注解
- 编写单元测试

## 常用命令
- ./dfecrab server
- pytest tests/
```

#### 2. 创建用户记忆

在 `~/.dfecrab/user.md` 创建个人偏好：

```markdown
# 用户偏好

## 编码风格
- 简洁直接
- 重视可读性

## 沟通风格
- 使用中文
- 提供代码示例
```

#### 3. 自动记忆

系统会自动记录观察到的模式和架构决策到 `.dfecrab/memory/MEMORY.md`。

### API 参考

```python
from src.core.memory.v4 import FourLayerMemoryManager, create_memory_manager

# 创建管理器
manager = create_memory_manager(
    base_dir="/path/to/project",
    runtime_dir="~/.dfecrab"
)

# 加载所有记忆
layers = manager.load_all()

# 合并记忆
merged = manager.merge()

# 获取系统提示词
prompt = manager.get_system_prompt()

# 记录观察
manager.observe("用户喜欢 async/await")
manager.update_auto_memory()
```

### 条件规则

支持基于 glob 模式的条件规则：

```markdown
# Python 规则
Applies to: **/*.py

## 编码规范
- 使用 Black 格式化
- 遵循 PEP 8
```

---

## 二、插件系统 V2

### 概述

新的插件系统支持：
- 斜杠命令 (Commands)
- 专用代理 (Agents)
- 技能定义 (Skills)
- 事件钩子 (Hooks)

### 插件结构

```
my-plugin/
├── .dfecrab-plugin/
│   └── plugin.json       # 插件清单
├── commands/             # 斜杠命令
│   ├── deploy.md
│   └── test.md
├── agents/               # 专用代理
│   └── reviewer/
│       └── agent.md
├── hooks/                # 事件钩子
│   └── hooks.json
└── README.md
```

### plugin.json 格式

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "我的插件",
  "author": "Your Name",

  "commands": [
    {
      "name": "deploy",
      "description": "部署到生产环境",
      "template": "commands/deploy.md",
      "aliases": ["d"]
    }
  ],

  "agents": [
    {
      "name": "reviewer",
      "description": "代码审查专家",
      "capabilities": ["code_review", "security_analysis"],
      "tools": ["FileRead", "Grep"]
    }
  ],

  "skills": [
    {
      "name": "python-dev",
      "description": "Python 开发最佳实践",
      "file_patterns": ["**/*.py"]
    }
  ],

  "hooks": [
    {
      "type": "pre_commit",
      "handler": "hooks/pre_commit.py:check",
      "priority": 10
    }
  ]
}
```

### 使用命令

```bash
# 安装插件
dfecrab plugin install ./my-plugin

# 列出插件
dfecrab plugin list

# 使用命令
/deploy
/test
```

### API 参考

```python
from src.core.plugins.v2 import PluginManagerV2, create_plugin_manager

# 创建管理器
manager = create_plugin_manager(plugins_dir="/path/to/plugins")

# 加载所有插件
await manager.load_all_plugins()

# 执行命令
result = await manager.execute_command("deploy", {})

# 执行钩子
results = await manager.execute_hooks(HookType.PRE_COMMIT, context)
```

---

## 三、统一工具系统

### 概述

新的工具系统提供：
- 统一的工具调用接口
- 权限控制
- 执行审计
- JSON Schema 支持

### 内置工具

| 工具 | 说明 | 权限 |
|------|------|------|
| FileRead | 读取文件内容 | READ |
| FileEdit | 编辑文件（diff模式） | WRITE |
| FileWrite | 写入文件 | WRITE |
| Glob | 文件模式匹配 | READ |
| Grep | 文本搜索 | READ |
| Bash | 执行shell命令 | EXECUTE |
| WebFetch | 获取网页内容 | READ |
| WebSearch | 网络搜索 | READ |
| TaskCreate | 创建任务 | WRITE |
| TaskList | 列出任务 | READ |

### 使用方法

```python
from src.core.tools import (
    ToolExecutor,
    ToolExecutionContext,
    PermissionLevel
)

# 创建执行器
executor = ToolExecutor()

# 创建上下文
context = ToolExecutionContext(
    agent_id="my_agent",
    session_id="session_001",
    working_directory=Path("/path/to/project"),
    permissions=[PermissionLevel.READ, PermissionLevel.WRITE]
)

# 执行工具
result = await executor.execute(
    "FileRead",
    {"file_path": "README.md"},
    context
)

print(result.output)
```

### 工具 Schema

```python
# 获取工具的 JSON Schema（用于 LLM 工具调用）
schemas = executor.get_tool_schemas()

# 示例输出
{
    "name": "FileRead",
    "description": "读取文件内容",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文件路径"
            },
            "limit": {
                "type": "number",
                "description": "读取行数限制"
            }
        },
        "required": ["file_path"]
    }
}
```

### 扩展工具

添加自定义工具：

```python
from src.core.tools import BaseTool, ToolDefinition, ToolParameter

class MyTool(BaseTool):
    @property
    def name(self) -> str:
        return "MyTool"

    @property
    def description(self) -> str:
        return "我的自定义工具"

    async def execute(self, params, context):
        # 实现工具逻辑
        return ToolResult(
            success=True,
            status=ToolStatus.SUCCESS,
            output="执行成功"
        )

# 注册工具
executor.registry.register(MyTool())
```

---

## 四、技能迁移

### 迁移工具

已提供技能迁移工具，将旧版技能转换为新插件格式：

```bash
python scripts/migrate_skills.py
```

### 迁移结果

- 成功迁移: 32 个技能
- 失败: 0 个

### 手动迁移

如需手动迁移，请参考：

1. 创建插件目录结构
2. 转换 `SKILL.md` 的 YAML 元数据到 `plugin.json`
3. 将触发词转换为命令
4. 更新 `execute.py` 为新工具接口

---

## 五、配置更新

### dfecrab.json 更新

```json
{
  "version": "4.0.0",

  "memory": {
    "system": "v4",
    "auto_update": true,
    "max_lines": 200
  },

  "plugins": {
    "directory": "plugins",
    "auto_load": true,
    "marketplace_url": "https://plugins.dfecrab.ai"
  },

  "tools": {
    "extended": true,
    "permission_mode": "default"
  }
}
```

---

## 六、变更日志

### v4.0.0 (2026-04-02)

**新功能**:
- 四层记忆系统（参考 Claude Code）
- 插件系统 V2（命令/代理/技能/钩子）
- 统一工具系统（权限控制/审计）
- 技能迁移工具

**改进**:
- 记忆优先级合并机制
- 条件规则支持
- JSON Schema 工具定义

**迁移**:
- 32 个技能已迁移到新插件格式

---

## 七、后续计划

1. **MCP 协议支持** - 集成 Model Context Protocol
2. **Agent 协作增强** - 优化多代理协作模式
3. **Web UI** - 开发 Web 管理界面
4. **插件市场** - 建立插件生态系统

---

*文档版本: 4.0.0*
*更新时间: 2026-04-02*
