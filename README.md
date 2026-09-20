# DFEcrab v4.1 - 电网运维智能助手

<div align="center">

[![Version](https://img.shields.io/badge/version-4.1.0-blue.svg)](https://github.com/DFEcrab/DFEcrab)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**基于微内核 + 插件化架构的电网运维智能体平台（模型驱动意图识别 + ReAct 工具循环）**

[文档中心](./docs/README.md) | [快速开始](#-快速开始) | [架构说明](./docs/设计说明书/01-总体设计/ARCHITECTURE_V2.md)

</div>

---

## 📖 项目简介

DFEcrab 是专为**电网调度与故障评估**场景设计的分布式智能体系统，采用微内核 + 插件化架构，提供灵活的智能体管理与任务执行能力。v4.1 重点重构了对话链路：意图识别改为 LLM 模型驱动（参考 Dify/LangGraph/CrewAI），ReAct 循环加入死循环防护与 final 保证。

### 核心特性

| 特性 | 说明 |
|------|------|
| 🌐 **Gateway 系统** | 统一对外入口，负责 HTTP / WebSocket / gRPC 路由与服务编排 |
| 🤖 **Agent 系统** | ReAct 循环（含死循环防护）、任务规划、多智能体协作与 LLM 适配 |
| 🎯 **意图识别** | LLM 模型驱动分类 chat/task/complex，规则仅作降级兜底（参考 Dify） |
| 🧠 **记忆系统** | 短期记忆、长期记忆、共享记忆、语义检索与压缩 |
| 📋 **任务系统** | 任务管理、待办调度、周期调度、监督执行 |
| 💬 **会话系统** | 会话生命周期管理与历史过滤 |
| 🛠️ **技能系统** | 技能发现、技能加载、工具注册与黑名单过滤 |
| 🔌 **插件框架** | 插件注册表、插件加载器、Agent 插件封装 |
| 🔄 **反思系统** | 对话样本、反思报告、改进行动、事件索引 |
| 📊 **监控系统** | 性能指标、Hook、健康检查与运行时不变量 |
| 🔗 **MCP 系统** | MCP 配置管理、缓存工具读取、Server 暴露入口 |
| ⚙️ **配置/工具系统** | 统一配置、日志处理、时间解析、路径工具 |

### 当前系统清单

目前项目中可以明确识别的核心系统如下：

| 系统 | 对应包 | 作用 |
|------|--------|------|
| Gateway | `src.gateway` | 对外 API、协议接入、服务编排 |
| Agent | `src.agent` | ReAct、Planner、LLM 适配 |
| Multi-Agent | `src.agent.multi` | 自评估、求助、确认协作 |
| Memory | `src.memory` | 短期/长期/共享记忆与检索 |
| Task | `src.task` | 任务管理、调度、监督 |
| Session | `src.session` | 会话生命周期与历史过滤 |
| Skill | `src.skill` | 技能加载、工具注册 |
| Plugin Framework | `src.plugin_framework` | 插件基类、注册表、加载器 |
| Reflection | `src.reflection` | 反思报告、事件索引、改进行动 |
| Monitoring | `src.monitoring` | 性能监控、Hook、不变量检查 |
| MCP | `src.mcp` | MCP 配置与缓存工具管理 |
| Config | `src.config` | 全局配置读取 |
| Utils | `src.utils` | 日志处理、时间解析等工具 |

---

## 📦 快速开始

### 安装

```bash
# 进入项目根目录
cd <你的项目根目录>

# 创建并激活虚拟环境（线上为 Python 3.12.7）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 验证启动器（使用项目自带的 venv 运行）
./dfecrab --version
```

### 配置

项目当前常用配置文件位于 `config/` 目录，例如：

- `config/dfecrab.json`
- `config/gateway.yaml`
- `config/multi_agent.json`
- `config/mcporter.json`

其中 `gateway.yaml`、`multi_agent.json`、`mcporter.json` 更偏向运行期配置，`dfecrab.json` 可作为模型配置参考。模型与网关配置示例如下：

```json
{
  "model": {
    "provider": "openai_compatible",
    "api_base": "http://192.168.1.150:4096/v1",
    "model_name": "Qwen3-Coder-30B"
  },
  "gateway": {
    "host": "localhost",
    "port": 6789
  }
}
```

### 启动服务

```bash
# 方式 1：启动完整 gRPC 架构（Gateway + Agent + 知识库 + 本地 MCP）
./dfecrab start

# 方式 2：查看服务状态
./dfecrab status

# 方式 3：停止服务
./dfecrab stop

# 方式 4：发送对话
./dfecrab chat "你好"

# 方式 5：知识库操作（上传/检索/问答/文档列表/统计/健康）
./dfecrab kb --help

# 方式 6：单独管理知识库 / 本地 MCP 服务
./dfecrab start-knowledge && ./dfecrab stop-knowledge
./dfecrab start-mcp && ./dfecrab stop-mcp
```

### 系统体检

仓库内置了一份系统健康检查脚本，可用于排查各个子系统是否跑通：

```bash
# 标准体检
python scripts/check_system_health.py

# JSON 输出，方便接运维或 CI
python scripts/check_system_health.py --json

# 深度体检（会执行插件加载）
python scripts/check_system_health.py --deep
```

当前体检覆盖：

- `grpc`
- `gateway_import`
- `memory`
- `task`
- `reflection`
- `skill`
- `plugin`
- `multi_agent`

### API 调用

```bash
# 对话 API（v2 流式，模型驱动意图识别）
curl -X POST http://localhost:6789/api/v2/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"你好","session_id":"s1","user_id":"test"}'

# 列出智能体
curl http://localhost:6789/api/agents

# 任务管理
curl http://localhost:6789/api/tasks
```

事件流类型：`thinking` / `tool_call` / `tool_result` / `plan_created` / `plan_step` / `final` / `error`

---

## 🏗️ 架构说明

### 整体架构

```
┌──────────────────────────────────────────────┐
│          Application Layer                   │
│        (TUI / CLI / API Client)              │
└──────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│           Gateway Layer                      │
│   HTTP | WebSocket | gRPC | Router           │
└──────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│  Intent Classifier (LLM 模型驱动)            │
│  chat → 直接调 LLM                           │
│  task → ReActLoop(tool_choice=auto)          │
│  complex → Planner 拆步 + ReActLoop          │
└──────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│            Kernel Layer                      │
│    Plugin System · EventBus                  │
└──────────────────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│          Service Layer                       │
│  AgentService | SkillService |              │
│  MemoryService | TaskService                 │
└──────────────────────────────────────────────┘
```

### 对话链路（v4.1 重构）

```
用户输入
   │
   ▼
IntentClassifier.classify()  ← LLM 模型驱动（_llm_classify）
   │  超时 2s 降级为规则模式（_rule_classify）
   │  日志：[Intent] message='...', intent=<chat|task|complex>, tool_choice=<none|auto>
   │
   ├─ chat ──────► LLM 直答 → final 事件（不调工具）
   │
   ├─ task ──────► ReActLoop.run(tool_choice=auto)
   │                 │  重复工具检测（同工具同参数第2次跳过）
   │                 │  到 max_iterations 强制 tool_choice=none → final
   │                 └─► thinking + tool_call + tool_result + final
   │
   └─ complex ───► Planner 拆步（plan_created 事件）
                     │  每步内部走 ReActLoop(tool_choice=auto)
                     └─► plan_created + plan_step×N + final
```

**P0 修复要点（v4.1）**：
- `tool_choice` 按意图动态设置（chat→none，task/complex→auto），不再硬编码 "required"
- ReActLoop 重复工具检测 + 到上限强制生成 final（不再 yield error）
- `planner`/`project_memory` 加入 ToolRegistry 黑名单，不被 LLM 当工具调用
- `max_iterations` 从 AgentConfig 读取（默认 10），不再硬编码 5
- Intent 日志格式 `[Intent] message='...', intent=..., tool_choice=...`

详细架构说明请参考 [ARCHITECTURE_V2.md](./docs/设计说明书/01-总体设计/ARCHITECTURE_V2.md)

---

## 📚 文档导航

完整文档已按"三书一册"标准整理：

### 📘 设计说明书
- [项目概览](./docs/设计说明书/01-总体设计/PROJECT_OVERVIEW.md)
- [架构设计](./docs/设计说明书/01-总体设计/ARCHITECTURE_V2.md)
- [核心模块设计](./docs/设计说明书/02-核心模块设计/)

### 📗 用户手册  
- [快速入门](./docs/用户手册/01-基础篇/QUICKSTART.md)
- [API 使用](./docs/用户手册/02-使用篇/API_USAGE.md)
- [技能开发](./docs/用户手册/03-进阶篇/SKILL_DEVELOPMENT.md)

### 📙 测试报告
- [测试结果](./docs/测试报告/)

---

## 🔧 核心系统

| 系统 | 说明 | 关键入口 |
|------|------|----------|
| **Gateway** | 对外 HTTP/WebSocket/gRPC 接入层 | `src.gateway.grpc_server` |
| **Agent** | ReAct 循环、任务规划、LLM 适配 | `src.agent` |
| **Memory** | 记忆存储、语义检索、压缩 | `src.memory` |
| **Task** | 任务管理、调度、监督 | `src.task` |
| **Session** | 会话实体与历史过滤 | `src.session` |
| **Skill** | 技能加载与工具注册 | `src.skill` |
| **Plugin Framework** | 插件注册表、加载器、Agent 插件封装 | `src.plugin_framework` |
| **Reflection** | 反思报告、事件与改进行动 | `src.reflection` |
| **Monitoring** | 性能指标、Hook、健康检查 | `src.monitoring` |
| **MCP** | MCP 配置、缓存工具、Server 暴露入口 | `src.mcp` |

---

## 🚀 未来规划

### v4.1 (计划中)

- 🔜 **权限系统** - 四级权限控制（Read/Write/Shell/Unsafe）
- 🔜 **斜杠命令** - 本地快捷指令，无需模型调用
- 🔜 **增强循环** - Agent 完整编程循环优化
- 🔜 **统一工具** - 7 个核心元能力标准化

### v5.0 (愿景)

- 📍 **会话持久化** - 完整 transcript 序列化与回放
- 📍 **上下文引擎** - CLAUDE.md 自动发现、Token 估算
- 📍 **工作区配置** - AGENTS.md/SOUL.md驱动配置
- 📍 **自我反思** - AI驱动的持续改进机制

---

## 💻 开发指南

### 项目结构

```
DFEcrab/
├── src/
│   ├── gateway/              # 网关与协议接入
│   ├── agent/                # ReAct、LLM、多智能体
│   ├── memory/               # 记忆与检索
│   ├── task/                 # 任务与调度
│   ├── session/              # 会话与历史过滤
│   ├── skill/                # 技能加载与工具注册
│   ├── plugin_framework/     # 插件框架
│   ├── reflection/           # 反思与事件
│   ├── monitoring/           # 性能监控与 Hook
│   ├── mcp/                  # MCP 配置与缓存工具
│   ├── config/               # 配置模块
│   ├── utils/                # 日志、时间等工具
│   └── services/             # 服务注册与管理
├── skills/                   # 技能实现目录
├── plugins/                  # 插件实现目录
├── agents/                   # Agent 定义目录
├── scripts/                  # 启动与巡检脚本
├── config/                   # 配置文件
└── docs/                     # 项目文档
```

### 创建新插件

```python
from src.plugin_framework import BasePlugin

class MyPlugin(BasePlugin):
    name = "my_plugin"
    version = "1.0.0"
    
    async def on_load(self, config=None) -> bool:
        return True
    
    async def on_start(self) -> bool:
        return True
```

### 创建新技能

技能建议放在 `skills/<skill_name>/` 目录下，最少包含：

- `SKILL.md`：技能说明
- `execute.py`：执行逻辑
- `_meta.json`：元信息

---

## 📊 技术栈

| 类别 | 技术选型 |
|------|----------|
| **语言** | Python 3.10+ |
| **框架** | AgentScope (智能体框架) |
| **HTTP** | httpx / aiohttp |
| **数据验证** | pydantic |
| **并发** | asyncio |

---

## 🐛 故障排除

### Gateway 启动失败

```bash
# 先跑系统体检
python scripts/check_system_health.py --json

# 查看 Gateway 日志
tail -f logs/gateway_grpc.log

# 通过项目入口查看状态
./dfecrab status
```

### 插件加载失败

```bash
# 检查插件目录
ls -la plugins/

# 深度体检插件系统
python scripts/check_system_health.py --deep
```

---

## 📝 版本历史

### v4.1 (2026-08)

**对话链路重构（P0 修复）：**
- ✅ 意图识别改为 LLM 模型驱动（`_llm_classify`），规则仅作降级兜底
- ✅ `tool_choice` 按意图动态设置（chat→none，task/complex→auto）
- ✅ ReActLoop 重复工具检测 + 到上限强制生成 final
- ✅ `planner`/`project_memory` 加入 ToolRegistry 黑名单
- ✅ `max_iterations` 从 AgentConfig 读取（默认 10）
- ✅ Intent 日志 `[Intent] message=..., intent=..., tool_choice=...`

### v4.0 (2026-04)

**核心特性：**
- ✅ 微内核 + 插件化架构重构
- ✅ Plugin System 标准化接口
- ✅ Agent/Skill/Memory/Task四大服务
- ✅ EventBus异步通信机制
- ✅ Gateway多协议支持（HTTP/WebSocket/gRPC）

### v3.x 系列

- **v3.2** - 服务层初步设计
- **v3.1** - 事件总线引入
- **v3.0** - 微内核架构探索

---

## 🤝 贡献

欢迎参与 DFEcrab 项目开发！

### 开发流程

1. Fork 项目并创建分支
2. 实现功能或修复 Bug
3. 编写单元测试
4. 提交 Pull Request

### 代码规范

- 遵循 PEP 8 规范
- 添加必要的类型注解
- 为公共 API 编写文档字符串

---

## 📞 联系方式

- **项目主页**: [GitHub](https://github.com/DFEcrab/DFEcrab)
- **问题反馈**: [Issues](https://github.com/DFEcrab/DFEcrab/issues)

---

<div align="center">

**DFEcrab Team** © 2026  
[文档中心](./docs/README.md) | [MIT License](LICENSE)

Made with ❤️ for power grid operations
</div>
