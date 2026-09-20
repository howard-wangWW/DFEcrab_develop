# 斜杠命令使用指南

> 本文档介绍 DFEcrab 的 10 个内置斜杠命令，帮助您高效地与 Agent 交互。

## 目录

- [概述](#概述)
- [命令完整说明](#命令完整说明)
- [使用示例](#使用示例)
- [命令别名](#命令别名)
- [常见问题解答](#常见问题解答)
- [最佳实践](#最佳实践)

---

## 概述

DFEcrab 提供 10 个内置斜杠命令，这些命令在**模型查询前本地处理**，无需调用模型服务器即可响应。这意味着：

- **响应速度快**：不依赖模型推理
- **离线可用**：即使模型服务器不可用也能工作
- **资源消耗低**：不消耗 token 配额

斜杠命令系统位于 `src/core/commands/slash_commands.py`。

### 命令格式

```
/command [arguments]
```

- 命令以 `/` 开头
- 命令名称不区分大小写
- 参数可选，用空格分隔

---

## 命令完整说明

### 1. /help - 显示帮助信息

**别名**: `/commands`

**描述**: 显示所有内置斜杠命令的列表及其描述。

**用法**:
```
/help
/commands
```

**输出示例**:
```markdown
# Slash Commands

- `/help` (`/commands`): Show built-in slash commands
- `/context` (`/usage`): Show estimated session context usage
- `/context-raw` (`/env`): Show raw environment & context snapshot
- `/prompt` (`/system-prompt`): Render the effective system prompt
- `/permissions`: Show active tool permission mode
- `/model`: Show or update the active model
- `/tools`: List registered tools with permission status
- `/memory`: Show loaded CLAUDE.md memory bundle
- `/status` (`/session`): Show runtime/session status summary
- `/clear`: Clear ephemeral runtime state

These commands are handled locally before the model loop.
They do not require the model server to be available.
```

---

### 2. /context - 显示上下文用量估算

**别名**: `/usage`

**描述**: 显示当前会话的上下文使用情况估算，包括 token 用量分解。

**用法**:
```
/context
/usage
```

**输出示例**:
```markdown
# Context Usage

Context estimation is not fully implemented yet.
This feature will show token usage breakdown similar to the npm runtime.
```

**注意**: 此功能正在完善中，当前显示占位信息。

---

### 3. /context-raw - 显示原始环境快照

**别名**: `/env`

**描述**: 显示原始环境和上下文快照，包含工作区路径、Agent ID、会话 ID 等底层信息。

**用法**:
```
/context-raw
/env
```

**输出示例**:
```markdown
# Raw Context Snapshot

**Workspace**: /Users/zhanghanzhi/DFEcrab
**Agent ID**: agent_001
**Session ID**: session_abc123
```

**适用场景**:
- 调试会话状态
- 确认当前工作区路径
- 查看 Agent 和会话标识符

---

### 4. /prompt - 显示系统提示词

**别名**: `/system-prompt`

**描述**: 渲染并显示当前生效的系统提示词，包含所有上下文信息。

**用法**:
```
/prompt
/system-prompt
```

**输出示例**:
```markdown
# System Prompt

System prompt rendering is not fully implemented yet.
This feature will show the assembled system prompt with all context.
```

**注意**: 此功能正在完善中，将显示组装后的完整系统提示词。

---

### 5. /permissions - 显示权限状态

**描述**: 显示当前激活的工具权限模式和配置。

**用法**:
```
/permissions
```

**输出示例**:
```markdown
# Permissions

Permission system is integrated. Use CLI flags to enable:

- `--allow-write`: Enable file write operations
- `--allow-shell`: Enable shell command execution
- `--unsafe`: Enable destructive shell operations
```

**适用场景**:
- 确认当前权限配置
- 了解如何启用特定权限
- 调试权限相关问题

---

### 6. /model - 显示或切换模型

**描述**: 显示当前使用的模型，或切换到其他模型。

**用法**:
```
/model              # 显示当前模型
/model <name>       # 切换到指定模型
```

**输出示例**:
```markdown
# Model

Current model configuration is managed via `dfecrab.json`.
Use `/model <name>` to switch (not implemented yet).
```

**切换模型示例**（功能完善后）:
```
/model gpt-4
/model claude-3-sonnet
```

**注意**: 模型切换功能正在完善中。当前请通过修改 `dfecrab.json` 配置文件来更改模型。

---

### 7. /tools - 列出已注册工具

**描述**: 列出所有已注册的工具及其权限状态。

**用法**:
```
/tools
```

**输出示例**:
```markdown
# Registered Tools

Tool listing requires integration with the skill plugin.
This feature will show all registered tools with their permission status.
```

**注意**: 此功能需要与技能插件集成，完善后将显示所有工具及其权限状态。

---

### 8. /memory - 显示记忆状态

**描述**: 显示已加载的 CLAUDE.md 记忆包和记忆系统状态。

**用法**:
```
/memory
```

**输出示例**:
```markdown
# Memory

Memory reporting requires integration with the memory plugin.
This feature will show loaded CLAUDE.md files and discovered memory bundles.
```

**注意**: 此功能需要与记忆插件集成，完善后将显示记忆加载状态。

---

### 9. /status - 显示运行状态摘要

**别名**: `/session`

**描述**: 显示运行时和会话状态摘要，包括 Agent ID、会话 ID、工作区路径、消息数量等。

**用法**:
```
/status
/session
```

**输出示例**:
```markdown
# Status

**Agent ID**: agent_001
**Session ID**: session_abc123
**Workspace**: /Users/zhanghanzhi/DFEcrab
**Messages**: 15

Slash command system is active and functional.
```

**适用场景**:
- 查看当前会话状态
- 确认消息数量
- 调试会话问题

---

### 10. /clear - 清除运行时状态

**描述**: 清除当前进程的临时 Python Agent 状态。

**用法**:
```
/clear
```

**输出示例**:
```
Cleared ephemeral Python agent state for this process.
```

**适用场景**:
- 重置会话状态
- 清理内存占用
- 重新开始对话

---

## 使用示例

### 示例 1：查看可用命令

```
/help
```

这是最常用的命令，当您不确定有哪些可用命令时使用。

### 示例 2：检查当前权限

```
/permissions
```

在尝试执行文件操作或 Shell 命令前，先确认当前权限配置。

### 示例 3：查看会话状态

```
/status
```

了解当前会话的运行情况，包括消息数量和会话标识符。

### 示例 4：调试上下文问题

```
/context-raw
```

当遇到路径或上下文相关问题时，使用此命令查看原始环境信息。

### 示例 5：清理会话状态

```
/clear
```

当会话状态异常或需要重新开始时，使用此命令清除临时状态。

### 示例 6：组合使用调试

```
/status        # 查看会话状态
/permissions   # 查看权限配置
/context-raw   # 查看环境快照
/tools         # 查看工具注册状态
```

这一组命令可以帮助您全面了解当前系统状态。

---

## 命令别名

为方便使用，部分命令提供了别名：

| 主命令 | 别名 | 说明 |
|--------|------|------|
| `/help` | `/commands` | 显示帮助信息 |
| `/context` | `/usage` | 显示上下文用量 |
| `/context-raw` | `/env` | 显示原始环境快照 |
| `/prompt` | `/system-prompt` | 显示系统提示词 |
| `/status` | `/session` | 显示运行状态 |

**使用提示**:
- 主命令和别名功能完全相同
- 建议使用较短的命令（如 `/env` 而非 `/context-raw`）
- 命令不区分大小写（`/Help` 和 `/help` 等效）

---

## 常见问题解答

### Q1: 斜杠命令是否需要网络连接？

不需要。斜杠命令在本地处理，不依赖模型服务器。即使模型服务器不可用，斜杠命令仍然可以正常工作。

### Q2: 斜杠命令会消耗 token 吗？

不会。斜杠命令在模型查询前被拦截处理，不会发送到模型服务器，因此不消耗任何 token。

### Q3: 如果输入了不存在的命令会怎样？

系统会返回错误提示：

```
Unknown command: <command_name>. Use `/help` to see available commands.
```

### Q4: 斜杠命令可以在脚本中使用吗？

斜杠命令设计用于交互式对话中使用。在脚本中，建议直接使用 Python API 调用相应功能。

### Q5: 如何知道当前输入被当作斜杠命令还是普通文本？

规则很简单：
- 以 `/` 开头且匹配已知命令 -> 作为斜杠命令处理
- 以 `/` 开头但不匹配已知命令 -> 返回错误提示
- 不以 `/` 开头 -> 作为普通文本发送给模型

### Q6: 命令参数如何使用？

部分命令支持参数，格式为 `/command arg1 arg2`。例如：

```
/model gpt-4
```

当前大多数命令的参数支持正在完善中。

### Q7: 斜杠命令的输出格式是什么？

斜杠命令的输出使用 Markdown 格式，包含标题、列表、代码块等元素，便于阅读和理解。

### Q8: 可以自定义或添加新的斜杠命令吗？

当前斜杠命令是内置的。未来版本可能支持插件化扩展自定义命令。如需添加自定义命令，可以修改 `src/core/commands/slash_commands.py` 文件。

### Q9: 斜杠命令的执行顺序是什么？

1. 用户输入文本
2. 系统检测是否以 `/` 开头
3. 解析命令名称和参数
4. 查找匹配的命令处理器
5. 执行处理器并返回结果
6. 如果未找到命令，返回错误提示或作为普通文本发送

### Q10: MCP 斜杠命令是什么？

MCP（Model Context Protocol）斜杠命令是预留功能，用于支持外部工具集成。当前尚未实现，输入时会提示：

```
MCP slash commands are not implemented yet.
```

---

## 最佳实践

### 1. 善用 /help 命令

当您不确定有什么可用命令时，随时使用 `/help` 获取完整命令列表。

### 2. 调试时使用命令组合

遇到问题时，按顺序执行以下命令快速诊断：

```
/status        -> 确认会话状态
/permissions   -> 确认权限配置
/context-raw   -> 确认环境信息
/tools         -> 确认工具状态
```

### 3. 操作前检查权限

在执行文件修改或 Shell 命令前，先使用 `/permissions` 确认当前权限配置，避免权限不足导致的错误。

### 4. 定期使用 /clear 清理状态

长时间运行的会话可能积累临时状态。定期使用 `/clear` 可以保持系统清爽。

### 5. 利用别名提高效率

记住常用命令的短别名可以提高操作效率：

```
/env      而非 /context-raw
/session  而非 /status
/usage    而非 /context
```

### 6. 关注命令局限性

了解哪些功能尚未完全实现（如 `/context`、`/model`、`/tools`、`/memory`），避免依赖占位信息做决策。

---

## 相关文档

- [权限配置指南](./PERMISSION_GUIDE.md) - 了解权限系统
- [工具系统使用指南](../02-使用篇/TOOLS_USAGE.md) - 了解工具系统
- [工作区配置指南](../02-使用篇/WORKSPACE_CONFIG.md) - 了解工作区配置

---

**文档版本**: 1.0  
**最后更新**: 2026-04-04  
**维护者**: DFEcrab Team
