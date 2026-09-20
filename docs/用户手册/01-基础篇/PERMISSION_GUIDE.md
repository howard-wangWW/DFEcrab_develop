# 权限配置指南

> 本文档介绍 DFEcrab 的四级权限系统，帮助您安全地配置和管理 Agent 权限。

## 目录

- [概述](#概述)
- [四级权限说明](#四级权限说明)
- [如何配置权限](#如何配置权限)
- [权限使用示例](#权限使用示例)
- [工具权限要求](#工具权限要求)
- [常见问题解答](#常见问题解答)
- [最佳实践](#最佳实践)

---

## 概述

DFEcrab 采用分级权限模型，确保 Agent 在安全的范围内执行操作。权限系统的设计原则是**最小权限原则**——默认情况下 Agent 只拥有只读权限，需要额外权限时必须显式启用。

权限系统核心组件位于 `src/core/security/permissions.py`。

---

## 四级权限说明

DFEcrab 提供四个级别的权限控制，从低到高依次为：

### 1. Read-only（只读）

**默认权限级别**

| 属性 | 值 |
|------|-----|
| 权限级别 | `read_only` |
| 文件写入 | 禁用 |
| Shell 执行 | 禁用 |
| 破坏性命令 | 禁用 |

**能力范围：**
- 读取文件内容
- 查看目录结构
- 搜索代码和文本
- 分析项目架构
- 查看配置信息

**适用场景：**
- 代码审查
- 项目分析
- 文档阅读
- 安全审计

### 2. Write（写入）

| 属性 | 值 |
|------|-----|
| 权限级别 | `write` |
| 文件写入 | 启用 |
| Shell 执行 | 禁用 |
| 破坏性命令 | 禁用 |

**能力范围：**
- 包含 Read-only 所有能力
- 创建新文件
- 编辑现有文件
- 删除文件
- 修改配置

**适用场景：**
- 代码编写和修改
- 文档编辑
- 配置文件调整
- 项目重构

### 3. Shell（Shell 执行）

| 属性 | 值 |
|------|-----|
| 权限级别 | `shell` |
| 文件写入 | 启用 |
| Shell 执行 | 启用（安全命令） |
| 破坏性命令 | 禁用 |

**能力范围：**
- 包含 Write 所有能力
- 执行安全的 Shell 命令（如 `ls`、`git status`、`python script.py`）
- 运行测试
- 构建项目
- 安装依赖

**被阻止的破坏性命令示例：**
```bash
rm -rf /          # 强制递归删除
dd if=/dev/zero   # 磁盘写入
shutdown          # 关机
reboot            # 重启
mkfs              # 格式化文件系统
chmod -R 777      # 递归设置 777 权限
git reset --hard  # Git 硬重置
git clean -fd     # Git 清理未跟踪文件
sudo rm           # sudo 删除
```

**适用场景：**
- 自动化构建和测试
- 依赖安装
- 项目初始化
- 脚本执行

### 4. Unsafe（不安全操作）

| 属性 | 值 |
|------|-----|
| 权限级别 | `unsafe` |
| 文件写入 | 启用 |
| Shell 执行 | 启用 |
| 破坏性命令 | 启用 |

**能力范围：**
- 包含 Shell 所有能力
- 执行破坏性命令（如删除文件、Git 硬重置等）

**警告：** 此权限级别允许执行可能不可逆的操作，请谨慎使用。

**适用场景：**
- 清理构建产物
- Git 仓库重置
- 系统级维护操作

---

## 如何配置权限

### 方法一：命令行参数

启动 DFEcrab 时通过命令行参数配置权限：

```bash
# 只读模式（默认）
./dfecrab

# 启用文件写入
./dfecrab --allow-write

# 启用 Shell 执行
./dfecrab --allow-shell

# 启用破坏性命令（谨慎使用）
./dfecrab --unsafe

# 组合使用
./dfecrab --allow-write --allow-shell
```

### 方法二：配置文件

在 `dfecrab.json` 中配置默认权限：

```json
{
  "permissions": {
    "allow_file_write": false,
    "allow_shell_commands": false,
    "allow_destructive_shell_commands": false
  }
}
```

### 方法三：权限对象创建

在代码中创建权限配置：

```python
from src.core.security import AgentPermissions, PermissionLevel

# 从标志位创建
perms = AgentPermissions.from_flags(
    allow_write=True,
    allow_shell=True,
    unsafe=False
)

# 直接创建
perms = AgentPermissions(
    allow_file_write=True,
    allow_shell_commands=True,
    allow_destructive_shell_commands=False
)

# 查看权限级别
print(perms.level)  # PermissionLevel.SHELL
```

### 方法四：从字典加载

```python
from src.core.security import AgentPermissions

config = {
    'allow_file_write': True,
    'allow_shell_commands': True,
    'allow_destructive_shell_commands': False
}

perms = AgentPermissions.from_dict(config)
```

---

## 权限使用示例

### 示例 1：代码审查（只读）

```bash
# 启动只读模式的 Agent
./dfecrab

# Agent 可以执行的操作：
# - 读取源代码文件
# - 分析项目结构
# - 搜索特定代码模式
# - 查看配置文件

# Agent 无法执行的操作：
# - 修改任何文件
# - 运行 Shell 命令
# - 删除文件
```

### 示例 2：代码编写（写入权限）

```bash
# 启动带写入权限的 Agent
./dfecrab --allow-write

# Agent 可以执行的操作：
# - 创建新的 Python 文件
# - 编辑现有代码
# - 修复 Bug
# - 重构代码结构

# Agent 无法执行的操作：
# - 运行测试验证修改
# - 安装新依赖
# - 执行 Shell 脚本
```

### 示例 3：自动化构建（Shell 权限）

```bash
# 启动带 Shell 执行权限的 Agent
./dfecrab --allow-write --allow-shell

# Agent 可以执行的操作：
# - 运行 pytest tests/
# - 执行 python setup.py build
# - 运行 pip install -e .
# - 执行 git status 查看状态
# - 运行 lint 工具

# Agent 无法执行的操作：
# - 删除整个目录
# - 执行 git reset --hard
# - 格式化磁盘
```

### 示例 4：仓库清理（Unsafe 模式）

```bash
# 启动完整权限的 Agent（谨慎使用）
./dfecrab --allow-write --allow-shell --unsafe

# Agent 可以执行的操作：
# - git clean -fd（清理未跟踪文件）
# - git reset --hard（硬重置到指定提交）
# - rm -rf build/（删除构建目录）
# - 所有上述权限级别的操作
```

### 示例 5：在代码中检查权限

```python
from src.core.security import (
    AgentPermissions,
    ensure_write_permission,
    ensure_shell_permission,
    check_command_safety,
    get_permission_summary
)

# 创建权限对象
perms = AgentPermissions.from_flags(allow_write=True, allow_shell=True)

# 检查写入权限
try:
    ensure_write_permission(perms)
    print("有写入权限")
except PermissionError as e:
    print(f"权限不足: {e}")

# 检查 Shell 权限并验证命令安全性
try:
    ensure_shell_permission(perms, command="ls -la")
    print("命令可以执行")
except PermissionError as e:
    print(f"命令被阻止: {e}")

# 获取权限摘要
summary = get_permission_summary(perms)
print(summary)
# 输出:
# 权限级别: shell
# 文件写入: ✅
# Shell 执行: ✅
# 破坏性命令: ❌
```

---

## 工具权限要求

不同工具对权限的要求如下：

| 工具名称 | 最低权限要求 | 说明 |
|---------|-------------|------|
| `read_file` | Read-only | 读取文件内容 |
| `list_directory` | Read-only | 列出目录内容 |
| `grep_search` | Read-only | 搜索文件内容 |
| `glob` | Read-only | 文件模式匹配 |
| `write_file` | Write | 创建或覆盖文件 |
| `edit` | Write | 编辑文件内容 |
| `bash` / `shell` | Shell | 执行 Shell 命令 |
| `execute` | Shell | 执行脚本 |

当权限不足时，工具会抛出 `ToolPermissionError` 或 `PermissionError`。

---

## 常见问题解答

### Q1: 为什么默认是只读权限？

遵循最小权限原则，确保 Agent 在未经明确授权的情况下不会修改任何文件或执行命令。这可以防止意外的数据丢失或系统损坏。

### Q2: 如何查看当前权限状态？

在 DFEcrab 交互界面中输入：

```
/permissions
```

或在代码中使用：

```python
from src.core.security import get_permission_summary
print(get_permission_summary(permissions))
```

### Q3: 权限可以在运行时修改吗？

权限在启动时确定，运行时无法动态提升权限。这是安全设计的一部分，防止权限提升攻击。如需不同权限级别，请重新启动 DFEcrab 并指定相应参数。

### Q4: 哪些命令被视为破坏性命令？

系统使用正则表达式模式检测破坏性命令，包括但不限于：

- `rm` 及其变体（删除文件）
- `dd`（磁盘写入）
- `shutdown` / `reboot`（关机/重启）
- `mkfs`（格式化）
- `chmod -R 777`（递归设置 777 权限）
- `git reset --hard`（Git 硬重置）
- `git clean -fd`（Git 清理未跟踪文件）
- 任何使用 `sudo` 的删除或写入命令

完整模式列表请参考 `src/core/security/permissions.py` 中的 `DESTRUCTIVE_COMMAND_PATTERNS`。

### Q5: 如何临时执行一个破坏性命令？

如果您需要执行某个特定的破坏性命令，有两种方式：

1. **启动时启用 Unsafe 模式**（不推荐）：
   ```bash
   ./dfecrab --unsafe
   ```

2. **手动执行命令**（推荐）：
   在终端中手动执行该命令，而不是通过 Agent 执行。这样可以保持 Agent 的安全边界。

### Q6: 权限配置会影响哪些工具？

权限配置会影响所有需要相应权限的工具。例如：
- 没有 `--allow-write` 时，`write_file`、`edit` 等工具会被阻止
- 没有 `--allow-shell` 时，`bash`、`shell`、`execute` 等工具会被阻止

可以使用以下代码查看被阻止的工具列表：

```python
blocked = permissions.get_blocked_tools()
print(f"被阻止的工具: {', '.join(blocked)}")
```

### Q7: 权限设置后如何验证是否生效？

启动 DFEcrab 后，使用 `/permissions` 命令查看当前权限状态。或者在代码中：

```python
from src.core.security import AgentPermissions

perms = AgentPermissions.from_flags(allow_write=True, allow_shell=True)
print(perms.to_dict())
# 输出:
# {
#     'allow_file_write': True,
#     'allow_shell_commands': True,
#     'allow_destructive_shell_commands': False,
#     'level': 'shell'
# }
```

### Q8: macOS 系统下的权限问题如何解决？

macOS 有额外的系统级权限限制（SIP、隐私权限等）。如果遇到权限问题：

```bash
# 一键设置权限
./setup_permissions.sh

# 或运行检查工具
python3 -m src.utils.permission_checker

# 手动设置目录权限
chmod -R 755 logs pids workspace skills agents runs
chmod 644 dfecrab.json
chmod 755 dfecrab
```

如果仍然无法写入，请在 macOS 系统偏好设置中：
1. 安全性与隐私 -> 隐私 -> 完全磁盘访问权限
2. 添加您的终端或 IDE 应用
3. 重启终端

---

## 最佳实践

### 1. 遵循最小权限原则

始终从最低权限开始，仅在需要时提升权限：

```bash
# 推荐：按需启用权限
./dfecrab --allow-write          # 只需要写入
./dfecrab --allow-write --allow-shell  # 需要写入和执行

# 不推荐：默认启用所有权限
./dfecrab --allow-write --allow-shell --unsafe
```

### 2. 使用权限检查工具

定期检查和修复项目权限：

```bash
# 检查当前权限状态
python3 -m src.utils.permission_checker

# 一键修复
./setup_permissions.sh
```

### 3. 生产环境安全

在生产环境中：
- **永远不要**启用 Unsafe 模式
- **永远不要**使用 `--unsafe` 标志
- 只启用完成任务所需的最小权限集
- 定期审计 Agent 的操作日志

### 4. 开发环境配置

在开发环境中，可以根据需要启用更多权限，但仍建议：
- 默认情况下只启用 Write 和 Shell 权限
- 避免启用 Unsafe 模式
- 使用版本控制跟踪所有更改

### 5. 权限配置版本化

将权限配置纳入版本控制：

```bash
# 跟踪配置文件
git add dfecrab.json
git commit -m "配置 Agent 权限设置"
```

### 6. 权限提示注入

权限信息会被自动注入到 system prompt 中，Agent 会收到当前权限状态的提示：

```
⚠️ 权限限制: 文件写入被禁用（需要 --allow-write）; Shell 命令执行被禁用（需要 --allow-shell）; 破坏性命令被禁用（需要 --unsafe）
```

或

```
✅ 完整权限已启用
```

这有助于 Agent 了解自己的能力边界。

---

## 相关文档

- [斜杠命令使用指南](./SLASH_COMMANDS.md) - 了解 `/permissions` 等斜杠命令
- [工具系统使用指南](../02-使用篇/TOOLS_USAGE.md) - 了解工具如何与权限系统集成
- [工作区配置指南](../02-使用篇/WORKSPACE_CONFIG.md) - 了解工作区配置

---

**文档版本**: 1.0  
**最后更新**: 2026-04-04  
**维护者**: DFEcrab Team
