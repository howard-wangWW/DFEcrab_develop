# DFEcrab v4.0 快速入门指南

> 5 分钟快速上手 DFEcrab 智能体操作系统

**版本**: 4.0.0  
**更新日期**: 2026-04-03

---

## 📋 目录

1. [系统要求](#系统要求)
2. [快速安装](#快速安装)
3. [v4.0 功能快速入门](#v40-功能快速入门)
4. [权限系统使用说明](#权限系统使用说明)
5. [斜杠命令使用说明](#斜杠命令使用说明)
6. [基本使用](#基本使用)
7. [下一步](#下一步)

---

## 系统要求

- **Python**: 3.10+
- **操作系统**: macOS / Linux / Windows
- **内存**: 4GB+ 推荐
- **磁盘**: 500MB+ 可用空间

---

## 快速安装

### 1. 安装依赖

```bash
cd /Users/zhanghanzhi/DFEcrab
pip install -e .
```

### 2. 验证安装

```bash
dfecrab --version
```

### 3. 配置权限（重要）

```bash
# 运行权限设置脚本
./setup_permissions.sh

# 或运行权限检查工具
python3 -m src.utils.permission_checker
```

### 4. 启动服务

```bash
# 方式 1：启动 TUI 界面
./dfecrab

# 方式 2：启动服务器模式
dfecrab gateway start

# 方式 3：命令行对话
dfecrab chat "你好"
```

---

## v4.0 功能快速入门

### 1. 分级权限系统

v4.0 引入了四级权限控制，确保系统安全：

| 权限级别 | 说明 | 可用工具 |
|---------|------|---------|
| **Read-only** | 只读操作 | FileRead, Glob, Grep, WebFetch, WebSearch |
| **Write** | 读写操作 | + FileEdit, FileWrite, TaskCreate |
| **Shell** | 执行命令 | + Bash |
| **Unsafe** | 无限制 | 所有工具 |

**查看当前权限**：
```bash
/permissions
```

**配置权限模式**：
在 `dfecrab.json` 中配置：
```json
{
  "tools": {
    "permission_mode": "default"
  }
}
```

### 2. 斜杠命令系统

10 个本地命令，无需模型调用即可响应：

| 命令 | 别名 | 说明 |
|------|------|------|
| `/help` | `/commands` | 显示可用命令列表 |
| `/status` | `/session` | 显示运行时/会话状态 |
| `/tools` | - | 列出已注册工具及权限状态 |
| `/permissions` | - | 显示当前工具权限模式 |
| `/context` | `/usage` | 显示估计的会话上下文使用量 |
| `/context-raw` | `/env` | 显示原始环境和上下文快照 |
| `/prompt` | `/system-prompt` | 渲染有效的系统提示 |
| `/memory` | - | 显示已加载的 CLAUDE.md 记忆包 |
| `/model` | - | 显示或更新活动模型 |
| `/clear` | - | 清除临时运行时状态 |

**使用示例**：
```bash
# 查看帮助
/help

# 查看系统状态
/status

# 查看工具列表
/tools

# 查看权限
/permissions
```

### 3. 统一工具系统

10 个核心工具，支持流式执行：

| 工具 | 说明 | 所需权限 |
|------|------|---------|
| FileRead | 读取文件内容 | Read-only |
| FileEdit | 编辑文件（diff 模式） | Write |
| FileWrite | 写入文件 | Write |
| Glob | 文件模式匹配搜索 | Read-only |
| Grep | 文本搜索 | Read-only |
| Bash | 执行 shell 命令 | Shell |
| WebFetch | 获取网页内容 | Read-only |
| WebSearch | 网络搜索 | Read-only |
| TaskCreate | 创建任务 | Write |
| TaskList | 列出任务 | Read-only |

### 4. 四层记忆系统

参考 Claude Code 架构设计的四层记忆：

```
┌─────────────────────────────────────────┐
│ Level 4: 企业策略 (最高优先级)           │
│ ~/.dfecrab/enterprise.md                │
├─────────────────────────────────────────┤
│ Level 3: 项目记忆 (高优先级)             │
│ ./DFECRAB.md                            │
├─────────────────────────────────────────┤
│ Level 2: 自动记忆 (动态优先级)           │
│ .dfecrab/memory/MEMORY.md               │
├─────────────────────────────────────────┤
│ Level 1: 用户记忆 (基础优先级)           │
│ ~/.dfecrab/user.md                      │
└─────────────────────────────────────────┘
```

**创建项目记忆**：
在项目根目录创建 `DFECRAB.md`：
```markdown
# 项目记忆

## 技术栈
- Python 3.10+
- FastAPI

## 约定
- 使用类型注解
- 编写单元测试
```

**创建用户记忆**：
在 `~/.dfecrab/user.md` 创建个人偏好：
```markdown
# 用户偏好

## 编码风格
- 简洁直接
- 重视可读性
```

### 5. 插件系统 V2

支持以下扩展能力：
- **斜杠命令** - 自定义本地命令
- **专用代理** - 特定领域的智能体
- **技能定义** - 文件模式匹配的技能
- **事件钩子** - 生命周期事件处理

**插件结构**：
```
my-plugin/
├── .dfecrab-plugin/
│   └── plugin.json       # 插件清单
├── commands/             # 斜杠命令
├── agents/               # 专用代理
├── hooks/                # 事件钩子
└── README.md
```

---

## 权限系统使用说明

### 权限级别详解

#### Read-only（只读）
- **适用场景**: 信息查询、文件读取、搜索
- **可用工具**: FileRead, Glob, Grep, WebFetch, WebSearch, TaskList
- **安全级别**: 最高，不会修改任何数据

#### Write（写入）
- **适用场景**: 文件编辑、任务创建
- **可用工具**: Read-only 所有工具 + FileEdit, FileWrite, TaskCreate
- **安全级别**: 高，会修改文件但不会执行命令

#### Shell（执行）
- **适用场景**: 需要执行 shell 命令
- **可用工具**: Write 所有工具 + Bash
- **安全级别**: 中，可以执行任意命令

#### Unsafe（无限制）
- **适用场景**: 完全信任的场景
- **可用工具**: 所有工具
- **安全级别**: 低，无限制访问

### 权限配置

**方式 1：配置文件**
```json
{
  "tools": {
    "permission_mode": "default"
  }
}
```

**方式 2：运行时查看**
```bash
/permissions
```

**方式 3：权限检查工具**
```bash
python3 -m src.utils.permission_checker
```

### 权限问题排查

如果遇到权限问题：

```bash
# 1. 检查当前权限
/permissions

# 2. 运行权限检查
python3 -m src.utils.permission_checker

# 3. 自动修复权限
./setup_permissions.sh

# 4. 手动设置权限
chmod -R 755 logs pids workspace skills agents
chmod 644 dfecrab.json
```

---

## 斜杠命令使用说明

### 基本用法

斜杠命令以 `/` 开头，在模型查询前本地处理，响应速度极快（< 5ms）。

### 常用命令

#### /help - 查看帮助

```bash
/help
```

显示所有可用的斜杠命令及其说明。

#### /status - 查看状态

```bash
/status
```

显示：
- 当前会话信息
- 智能体信息
- 模型配置
- 记忆加载状态
- 工具注册状态

#### /tools - 查看工具

```bash
/tools
```

显示：
- 已注册工具列表
- 工具权限状态
- 工具描述

#### /permissions - 查看权限

```bash
/permissions
```

显示当前工具权限模式。

#### /context - 查看上下文

```bash
/context
```

显示估计的 token 使用量和上下文大小。

#### /memory - 查看记忆

```bash
/memory
```

显示已加载的四层记忆内容。

#### /model - 查看/切换模型

```bash
# 查看当前模型
/model

# 切换模型
/model qwen:7b
```

#### /clear - 清除状态

```bash
/clear
```

清除临时运行时状态，释放内存。

### 命令别名

许多命令有别名，例如：
- `/commands` = `/help`
- `/session` = `/status`
- `/usage` = `/context`
- `/env` = `/context-raw`
- `/system-prompt` = `/prompt`

---

## 基本使用

### 命令行交互

```bash
# 启动 TUI
./dfecrab

# 在 TUI 中使用
> 你好，请介绍一下自己
> /status
> /tools
> 帮我创建一个 Python 文件
```

### API 调用

```bash
# 对话 API (v2版本)
curl -X POST http://localhost:6789/api/v2/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 查看会话
curl http://localhost:6789/api/v2/sessions

# 查看任务
curl http://localhost:6789/api/v2/tasks
```

### 智能体管理

```bash
# 创建智能体
dfecrab agent create my_assistant

# 切换智能体
dfecrab agent switch my_assistant

# 列出智能体
dfecrab agent list
```

### 技能管理

```bash
# 列出技能
dfecrab skill list

# 安装技能
dfecrab skill install weather

# 开发技能
dfecrab skill create my_skill
```

---

## 下一步

- 📖 [安装指南](./INSTALLATION.md) - 详细安装步骤
- ⚙️ [配置指南](./CONFIGURATION.md) - 配置文件说明
- 🔐 [权限配置](./PERMISSION_SETUP.md) - 权限系统配置
- 📚 [API 使用](../02-使用篇/API_USAGE.md) - REST API 调用
- 🛠️ [技能使用](../02-使用篇/SKILLS_USAGE.md) - 技能管理
- 🐳 [Docker 部署](../02-使用篇/DOCKER_DEPLOYMENT.md) - Docker 部署指南
- 📄 [V4 升级指南](../V4_UPGRADE_GUIDE.md) - 从旧版本升级

---

**版本**: 4.0.0  
**更新日期**: 2026-04-03  
**维护者**: DFEcrab Team
