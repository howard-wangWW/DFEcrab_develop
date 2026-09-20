# DFEcrab 项目全局梳理

## 项目概述

**DFEcrab** 是一个轻量级智能体系统，基于 AgentScope 架构开发，参考 OpenClaw 的设计理念，实现了微内核 + 服务化的分布式智能体系统。

**版本**: V4.0
**核心特性**: 分布式、多智能体、服务化、插件化、权限控制、会话持久化、上下文引擎

## 📊 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-03-01 | 初始版本 |
| 2.0 | 2026-03-29 | 按三书一册重构 |
| 3.0 | 2026-03-29 | 增加分层记忆、任务规划、技能系统 |
| 4.0 | 2026-04-03 | 集成 OpenClaw 核心设计：权限系统、斜杠命令、Agent循环、工具系统、会话持久化、上下文引擎、工作区配置 |

## 🎯 核心功能

### 1. 任务规划系统

- **planner 技能**：复杂度检测 + 执行计划生成
- 渐进式改进，阶段1已完成
- 参考 OpenClaw 架构设计

### 2. 分层记忆系统

- **project_memory 技能**：分层记忆管理
- **memory_maintenance 技能**：自动汇总
- GLOBAL.md：全局配置 + 人格定义
- DAILY/WEEKLY/MONTHLY/LONG_TERM：分层存储
- 定时任务：每周/每月自动汇总

### 3. 技能系统

- 7个内置技能：planner, project_memory, memory_maintenance, list_dir, file_read, word_read, kdocs_read
- 支持目录结构和单文件技能
- ServiceToolkit 集成

### 4. Agent 系统

- 基于 agentscope ReActAgent
- 支持多 agent
- 全局共享记忆
- 系统提示词注入记忆上下文

### 5. 权限系统 (Permissions)

**文件**: `src/core/security/permissions.py`

四级权限控制模型，集成自 claw-code-agent 的安全设计：

| 权限级别 | 说明 | 启用标志 |
|----------|------|----------|
| Read-only | 只读操作（默认） | - |
| Write | 文件写入权限 | `--allow-write` |
| Shell | Shell 命令执行权限 | `--allow-shell` |
| Unsafe | 破坏性命令执行权限 | `--unsafe` |

**核心功能**:
- `AgentPermissions`: 权限配置数据类，支持序列化/反序列化
- `PermissionLevel`: 权限级别枚举
- 破坏性命令检测：正则模式匹配（rm -rf, dd, shutdown, git reset --hard 等）
- `check_command_safety()`: 命令安全检查
- `ToolPermissionContext`: 工具级别权限拒绝规则
- 权限提示注入：自动注入到 system prompt

### 6. 斜杠命令系统 (Slash Commands)

**文件**: `src/core/commands/slash_commands.py`

本地命令处理系统，在模型查询前拦截处理，无需调用模型即可响应：

| 命令 | 别名 | 功能 |
|------|------|------|
| `/help` | `/commands` | 显示可用命令列表 |
| `/context` | `/usage` | 显示会话上下文用量估算 |
| `/context-raw` | `/env` | 显示原始环境快照 |
| `/prompt` | `/system-prompt` | 渲染有效系统提示词 |
| `/permissions` | - | 显示当前权限模式 |
| `/model` | - | 显示或切换活跃模型 |
| `/tools` | - | 列出已注册工具及权限状态 |
| `/memory` | - | 显示加载的记忆文件 |
| `/status` | `/session` | 显示运行时/会话状态摘要 |
| `/clear` | - | 清除临时运行时状态 |

**核心组件**:
- `ParsedSlashCommand`: 解析后的命令对象
- `SlashCommandResult`: 命令执行结果
- `SlashCommandContext`: 命令执行上下文
- `preprocess_slash_command()`: 预处理入口

### 7. Agent 循环 (Enhanced Agent Loop)

**文件**: `src/core/agent/enhanced_loop.py`

完整的编程循环，集成自 claw-code-agent 的 LocalCodingAgent 设计：

**循环流程**:
1. 斜杠命令预处理
2. 上下文构建
3. 模型查询
4. 工具调用执行
5. 结果注入
6. 循环迭代（最大 12 轮）
7. 会话持久化

**核心组件**:
- `EnhancedAgentLoop`: 增强版 Agent 循环主类
- `ToolCall`: 工具调用记录
- `ToolExecutionResult`: 工具执行结果
- `AssistantTurn`: 助手回复轮次
- `UsageStats`: Token 用量统计
- `AgentRunResult`: Agent 运行结果
- 支持流式输出 (`run_stream()`)

### 8. 工具系统 (Unified Tools)

**文件**: `src/core/tools/unified_tools.py`

统一工具接口，集成 claw-code-agent 的工具设计：

**7 个核心工具**:
| 工具 | 功能 | 权限要求 |
|------|------|----------|
| `list_dir` | 列出目录 | 无 |
| `read_file` | 读取文件 | 无 |
| `write_file` | 写入文件 | Write |
| `edit_file` | 编辑文件 | Write |
| `glob_search` | 通配符搜索 | 无 |
| `grep_search` | 正则搜索 | 无 |
| `bash` | Shell 命令 | Shell |

**核心组件**:
- `AgentTool`: 统一工具接口（支持 OpenAI function calling 格式转换）
- `ToolExecutionContext`: 工具执行上下文
- `ToolExecutionResult`: 标准化执行结果
- `ToolStreamUpdate`: 流式工具更新
- `execute_tool()`: 同步执行
- `execute_tool_streaming()`: 流式执行
- 路径安全验证：防止逃逸工作目录
- 输出截断：防止超大输出

### 9. 会话持久化 (Session Persistence)

**文件**: `src/core/session/persistence.py`

完整的会话序列化/反序列化、transcript 持久化、会话恢复功能：

**存储结构**:
```
data/sessions/
├── {session_id}.json          # 完整会话快照
├── {session_id}.json.gz       # 压缩版本（可选）
├── {session_id}_transcript.json  # 纯 transcript
└── {session_id}_history.json     # 文件历史
```

**核心组件**:
- `SessionPersistence`: 会话持久化管理器
- `SessionSnapshot`: 完整会话快照
- `ToolCallRecord`: 工具调用记录
- `FileHistoryEntry`: 文件历史条目
- `UsageStats`: 使用统计

**核心功能**:
- 会话 CRUD 操作
- Transcript 持久化与加载
- 文件历史回放 (`replay_file_history()`)
- 压缩历史回放 (`replay_compacted_history()`)
- Gzip 压缩/解压支持
- Session 对象还原 (`load_session_as_object()`)

### 10. 上下文引擎 (Context Engine)

**文件**: `src/core/context/engine.py`

上下文管理与用量估算系统：

**核心功能**:
- CLAUDE.md 自动发现：从 cwd 向上遍历父目录查找记忆文件
- Git 状态缓存集成：分支、status、最近 commit、user name
- 上下文用量估算：token 计数（启发式：4 字符/token）
- 上下文报告生成：分级统计（system prompt, user context, messages, tool calls）
- 动态提示词边界标记

**核心组件**:
- `ContextUsageReport`: 上下文用量报告
- `discover_memory_bundle()`: 发现工作区记忆文件
- `get_git_status_cached()`: Git 状态缓存查询
- `collect_context_usage()`: 收集上下文用量
- `format_context_usage_report()`: 格式化报告

**支持的记忆文件**:
- `CLAUDE.md`
- `.claude/CLAUDE.md`
- `CLAUDE.local.md`
- `.claude/rules/*.md`

### 11. 工作区配置 (Workspace Config)

**文件**: `src/core/workspace/config.py`

工作区 Markdown 配置文件解析器，参考 OpenClaw 的工作区设计：

**配置文件**:
| 文件 | 用途 |
|------|------|
| `AGENTS.md` | Agent 说明与角色定义 |
| `SOUL.md` | 人格/灵魂定义（行为准则与风格） |
| `TOOLS.md` | 工具说明与能力描述 |
| `USER.md` | 用户画像与偏好 |
| `HEARTBEAT.md` | 心跳任务说明 |

**核心组件**:
- `WorkspaceConfig`: 工作区完整配置
- `AgentInfo`: Agent 信息
- `SoulProfile`: 人格/灵魂配置
- `ToolInfo`: 工具信息
- `UserProfile`: 用户画像
- `HeartbeatTask`: 心跳任务
- `load_workspace_config()`: 加载工作区配置
- `build_system_prompt_from_workspace()`: 从工作区构建系统提示词

**特性**:
- Markdown frontmatter 解析
- 按标题分割内容区块
- 列表项和键值对自动提取
- 系统提示词自动组装

---

## 项目结构总览

```
DFEcrab/
├── src/                          # 核心源代码
│   ├── core/                     # 核心组件
│   │   ├── gateway/              # 网关层（新版）
│   │   │   ├── gateway_core.py   # 网关核心
│   │   │   ├── gateway_v2.py     # 网关V2
│   │   │   ├── event_bus.py      # 事件总线
│   │   │   ├── service_locator.py # 服务定位器
│   │   │   └── protocol/         # 协议层
│   │   │       ├── http_server.py # HTTP协议
│   │   │       └── websocket.py   # WebSocket协议
│   │   ├── tui/                  # 终端UI
│   │   │   ├── tui.py            # TUI主程序
│   │   │   └── tui_v2.py         # TUI V2
│   │   ├── agent_manager.py       # 智能体管理器
│   │   ├── memory_manager.py     # 记忆管理器
│   │   ├── heartbeat_manager.py   # 心跳管理器
│   │   └── invariants.py          # 不变量管理器
│   │
│   ├── services/                  # 服务层
│   │   ├── service_registry.py    # 服务注册中心
│   │   ├── agent_service.py       # 智能体服务
│   │   ├── skill_service.py       # 技能服务
│   │   ├── memory_service.py      # 记忆服务
│   │   ├── message_bus.py         # 消息总线
│   │   ├── auth_service.py        # 认证服务
│   │   ├── monitoring_service.py   # 监控服务
│   │   ├── model_manager.py        # 模型管理器
│   │   ├── session_manager.py      # 会话管理器
│   │   ├── session_compactor.py    # 会话压缩器
│   │   ├── node_manager.py         # 节点管理器
│   │   ├── service_directory.py    # 服务目录
│   │   ├── discovery_service.py    # 服务发现
│   │   └── service_discovery.py    # 服务发现（备用）
│   │
│   ├── plugins/                    # 插件系统
│   │   ├── base.py                # 插件基类
│   │   ├── registry.py            # 插件注册中心
│   │   ├── loader.py              # 插件加载器
│   │   └── example/               # 示例插件
│   │
│   ├── routing/                    # 路由系统
│   │   ├── channel_adapter.py      # 渠道适配器
│   │   └── message_router.py       # 消息路由器
│   │
│   ├── models/                     # 模型层
│   ├── storage/                    # 存储层
│   ├── monitoring/                 # 监控层
│   ├── utils/                      # 工具层
│   │   ├── logger.py              # 日志工具
│   │   └── vector_utils.py        # 向量工具
│   │
│   ├── config/                     # 配置层
│   │   └── config.py              # 配置管理
│   │
│   └── skills/                     # 内置技能
│
├── agents/                         # 智能体数据
│   ├── default/                   # 默认智能体
│   ├── 阿蟹/                     # 智能体：阿蟹
│   ├── 孝蟹/                     # 智能体：孝蟹
│   └── test_agent/                # 测试智能体
│
├── skills/                         # 技能目录
│   ├── calculate/                 # 计算技能
│   ├── echo/                     # 回显技能
│   ├── file_manager/             # 文件管理技能
│   ├── web_search/               # 网页搜索技能
│   ├── weather/                  # 天气技能
│   └── pdf-tools/                # PDF工具技能
│
├── tests/                         # 测试文件
│   ├── test_agent_lifecycle.py   # 智能体生命周期测试
│   └── ...
│
├── logs/                          # 日志目录
│   └── gateway.log               # 网关日志
│
├── build/                        # 构建目录
├── dist/                         # 分发目录
├── pids/                         # PID文件
├── workspace/                    # 工作空间
│
├── dfecrab                      # 主程序入口
├── dfecrab.json                 # 配置文件
├── requirements.txt             # 依赖列表
└── README.md                    # 项目说明
```

---

## 核心架构

### 1. 分层架构（V4.0）

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                     │
│                    (TUI / Web / API / CLI)               │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                     Gateway Layer                        │
│    (Gateway Core / HTTP Server / WebSocket / Auth)      │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                     Kernel Layer (微内核)                 │
│    Plugin System │ EventBus │ Service Registry          │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                   Core Modules Layer                     │
│  Agent Loop │ Tools │ Permissions │ Slash Commands      │
│  Session Persistence │ Context Engine │ Workspace Config │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                     Service Layer                       │
│  Agent │ Skill │ Memory │ Message │ Auth │ Monitor     │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                   Infrastructure Layer                   │
│       Config │ Logger │ Vector Utils │ Storage          │
└─────────────────────────────────────────────────────────┘
```

### 2. Agent 循环架构（V4.0 新增）

```
用户输入
   │
   ▼
┌─────────────────────┐
│  斜杠命令预处理       │ ← 本地拦截，无需模型
│  (Slash Commands)    │
└─────────┬───────────┘
          │ should_query?
          ▼
┌─────────────────────┐
│  上下文构建           │ ← Context Engine
│  (Context Build)     │   + Workspace Config
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  模型查询             │ ← LLM API 调用
│  (Model Query)       │
└─────────┬───────────┘
          ▼
┌─────────────────────┐     有工具调用？
│  工具调用执行         │ ────► 是 ──► 权限检查 ──► 执行 ──► 结果注入
│  (Tool Execution)    │              │
└─────────┬───────────┘              ▼
          │ 无工具调用           ┌──────────────┐
          ▼                     │ 循环迭代       │
┌─────────────────────┐         │ (max 12 turns) │
│  会话持久化           │         └──────────────┘
│  (Session Persist)   │
└─────────────────────┘
```

### 3. 服务架构

```
┌──────────────────────────────────────────────────────────┐
│                    Service Registry                      │
│              (服务注册中心 - 依赖注入)                    │
└──────────────────────────────────────────────────────────┘
        │        │        │        │        │
        ▼        ▼        ▼        ▼        ▼
   ┌─────────┬────────┬────────┬────────┬────────┐
   │ Agent   │ Skill  │ Memory │ Message│  Auth  │
   │Service  │Service │Service │ Bus    │Service │
   └─────────┴────────┴────────┴────────┴────────┘
        │        │        │        │        │
        ▼        ▼        ▼        ▼        ▼
   ┌─────────┬────────┬────────┬────────┬────────┐
   │ Plugin  │ Tool   │ Cache │  Cross│  JWT   │
   │Manager  │Registry│       │ Node  │ Tokens │
   └─────────┴────────┴────────┴────────┴────────┘
```

### 3. 分布式架构

```
    ┌─────────────┐     ┌─────────────┐
    │   Node A    │     │   Node B    │
    │  ┌───────┐  │     │  ┌───────┐  │
    │  │ Agent │  │     │  │ Agent │  │
    │  │ 阿蟹  │  │◄───►│  │ 孝蟹  │  │
    │  └───────┘  │     │  └───────┘  │
    │      │      │     │      │      │
    │  ┌─────────┐│     │  ┌─────────┐│
    │  │ Gateway │ │     │  │ Gateway │ │
    │  │   V2   │ │     │  │   V2    │ │
    │  └────┬────┘│     │  └────┬────┘│
    └───────┼─────┘     └───────┼─────┘
            │                   │
            └─────────┬─────────┘
                      │
                      ▼
            ┌─────────────────┐
            │   Message Bus   │
            │  (服务发现+通信)  │
            └─────────────────┘
```

---

## 核心组件详解

### 1. 网关层 (Gateway Layer)

#### Gateway Core (新版)
- **文件**: `src/core/gateway/gateway_core.py`
- **功能**: 网关核心，整合所有网关组件
- **特性**:
  - 服务定位器 (ServiceLocator)
  - 事件总线 (EventBus)
  - HTTP/WebSocket 双协议支持
  - Token 认证机制

#### Gateway V2 (主版本)
- **文件**: `src/core/gateway/gateway_v2.py`
- **功能**: 主要的网关实现
- **特性**:
  - REST API 服务
  - 服务协调
  - 响应处理

### 2. 服务层 (Service Layer)

| 服务 | 文件 | 功能 |
|------|------|------|
| **Agent Service** | `services/agent_service.py` | 智能体生命周期管理 |
| **Skill Service** | `services/skill_service.py` | 技能加载和执行 |
| **Memory Service** | `services/memory_service.py` | 记忆存储和检索 |
| **Message Bus** | `services/message_bus.py` | 智能体间通信 |
| **Auth Service** | `services/auth_service.py` | 用户认证和授权 |
| **Monitoring** | `services/monitoring_service.py` | 系统监控和统计 |
| **Model Manager** | `services/model_manager.py` | AI 模型配置管理 |
| **Session Manager** | `services/session_manager.py` | 会话管理 |
| **Session Compactor** | `services/session_compactor.py` | 会话压缩优化 |
| **Node Manager** | `services/node_manager.py` | 节点注册和心跳 |
| **Service Directory** | `services/service_directory.py` | 服务注册和发现 |
| **Discovery Service** | `services/discovery_service.py` | 自动服务发现 |

### 3. 插件系统 (Plugin System)

| 组件 | 文件 | 功能 |
|------|------|------|
| **Plugin Base** | `plugins/base.py` | 插件接口和生命周期 |
| **Plugin Registry** | `plugins/registry.py` | 插件注册和管理 |
| **Plugin Loader** | `plugins/loader.py` | 插件加载和初始化 |

### 4. 路由系统 (Routing System)

| 组件 | 文件 | 功能 |
|------|------|------|
| **Channel Adapter** | `routing/channel_adapter.py` | 多渠道适配 |
| **Message Router** | `routing/message_router.py` | 消息路由和分发 |

---

## 智能体管理

### 智能体数据结构
```
agents/
└── {agent_id}/
    ├── config.json      # 智能体配置
    ├── memory.json      # 记忆数据
    ├── metadata.json    # 元数据
    ├── tools.json       # 工具配置
    ├── indices/         # 向量索引
    │   ├── short_term.ann
    │   └── permanent.ann
    ├── PERSONALITY.md   # 个性设定
    └── cron.json        # 定时任务
```

### 内置智能体
- **阿蟹 (a_xie)**: 默认助手
- **孝蟹 (xiao_xie)**: 辅助智能体
- **test_agent**: 测试用智能体

---

## 技能系统 (Skills)

### 技能结构
```
skills/
└── {skill_name}/
    ├── SKILL.md        # 技能定义
    ├── execute.py      # 执行脚本
    └── _meta.json      # 元数据
```

### 内置技能
| 技能 | 功能 |
|------|------|
| calculate | 数学计算 |
| echo | 回显消息 |
| file_manager | 文件管理 |
| web_search | 网页搜索 |
| weather | 天气查询 |
| pdf-tools | PDF处理 |
| get-time | 获取时间 |
| get-weekday | 获取星期 |

---

## 配置文件

### dfecrab.json
```json
{
  "gateway": {
    "host": "0.0.0.0",
    "http_port": 6789,
    "ws_port": 6790
  },
  "models": [...],
  "agents": {...}
}
```

---

## 启动方式

### 1. TUI 模式（默认）
```bash
./dfecrab
```

### 2. Server 模式
```bash
./dfecrab server
```

### 3. Gateway 管理
```bash
./dfecrab gateway start
./dfecrab gateway stop
./dfecrab gateway restart
./dfecrab gateway status
```

### 4. 远程 TUI
```bash
./dfecrab remote [host] [port]
```

---

## API 端点

### Gateway API
| 方法 | 端点 | 功能 |
|------|------|------|
| GET | /health | 健康检查 |
| GET | /api/agents | 列出智能体 |
| POST | /api/agents | 创建智能体 |
| GET | /api/agents/{id} | 获取智能体 |
| PUT | /api/agents/{id} | 更新智能体 |
| DELETE | /api/agents/{id} | 删除智能体 |
| POST | /api/agents/{id}/switch | 切换智能体 |
| GET | /api/messages | 获取消息 |
| POST | /api/messages/send | 发送消息 |
| GET | /api/services | 列出服务 |
| GET | /api/events | 获取事件历史 |

---

## 测试文件

| 文件 | 功能 |
|------|------|
| `test_gateway_core.py` | Gateway 核心测试 |
| `test_plugins.py` | 插件系统测试 |
| `test_routing.py` | 消息路由测试 |
| `test_session_memory.py` | 会话记忆测试 |
| `test_discovery.py` | 服务发现测试 |
| `test_invariants.py` | 不变量测试 |
| `test_model_support.py` | 模型支持测试 |

---

## 架构特点（V4.0）

| 维度 | 说明 |
|------|------|
| **微内核架构** | Kernel 负责插件管理、事件分发和系统生命周期 |
| **插件化** | 插件系统作为一等公民，支持热插拔 |
| **权限控制** | 四级权限模型（Read-only/Write/Shell/Unsafe），破坏性命令检测 |
| **斜杠命令** | 10+ 本地命令，模型查询前拦截，无需调用模型 |
| **Agent 循环** | 完整的编程循环：斜杠命令→上下文→模型→工具→持久化 |
| **统一工具** | 7 个核心工具，OpenAI function calling 格式，路径安全验证 |
| **会话持久化** | 完整序列化/反序列化，transcript 持久化，文件历史回放 |
| **上下文引擎** | CLAUDE.md 自动发现，Git 状态集成，token 用量估算 |
| **工作区配置** | Markdown 配置文件（AGENTS/SOUL/TOOLS/USER/HEARTBEAT） |
| **事件驱动** | 内置事件总线，发布-订阅模式 |
| **分布式** | 支持多节点部署，服务发现机制 |
| **安全性** | JWT 认证，权限控制，命令安全检查 |
| **监控** | 全面的系统监控，psutil 集成 |
| **流式输出** | Agent 循环和工具执行均支持流式输出 |

## 技术栈

| 类别 | 技术 |
|------|------|
| **核心** | Python 3.8+, asyncio |
| **框架** | AgentScope |
| **协议** | HTTP, WebSocket |
| **认证** | JWT, bcrypt |
| **搜索** | Annoy, scikit-learn |
| **监控** | psutil |
| **日志** | logging |

---

## 下一步发展方向

### 短期目标
1. 完善斜杠命令系统（实现 /context, /prompt, /tools 等命令的完整功能）
2. 增强上下文引擎（集成 tiktoken 进行精确 token 计数）
3. 工具系统扩展（支持 MCP 工具、自定义工具注册）

### 中期目标
1. 支持更多消息渠道
2. 实现 WebSocket 实时通信
3. 开发 Web 管理界面
4. 工作区配置热重载

### 长期目标
1. 分布式多节点部署
2. 容器化部署 (Docker/K8s)
3. 边缘计算支持
4. 多模型智能路由

---

## 参考资料

- [OpenClaw 架构](https://github.com/openclaw/openclaw)
- [OpenClaw claw-code-agent 设计](https://github.com/openclaw/claw-code-agent)
- [AgentScope 文档](https://agentscope.gitcode.com)
- [微服务架构模式](https://microservices.io)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)

---

**文档版本**: 4.0
**更新日期**: 2026-04-03
**状态**: 已完成
