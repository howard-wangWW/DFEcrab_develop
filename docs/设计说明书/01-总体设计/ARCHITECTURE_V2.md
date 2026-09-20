# DFEcrab V4 架构说明

## 项目定位

**DFEcrab v4.0 - 电网运维智能助手**  
基于微内核 + 插件化架构的智能体管理平台，专为电力调度与故障评估场景设计。

---

## v4.0 核心特性

| 特性 | 状态 | 说明 |
|------|------|------|
| **微内核架构** | ✅ 已实现 | 核心精简，功能插件化 |
| **插件系统** | ✅ 已实现 | 标准化接口，热插拔支持 |
| **服务层设计** | ✅ 已实现 | Agent/Skill/Memory/Task 服务解耦 |
| **事件总线** | ✅ 已实现 | 异步事件驱动通信 |
| **Gateway 多协议** | ✅ 已实现 | HTTP/WebSocket/gRPC 支持 |
| **会话管理** | ✅ 已实现 | 基础会话生命周期管理 |
| **任务调度** | ✅ 已实现 | 待办任务管理 |

---

## V4.0 架构设计

### 整体架构图

```
┌──────────────────────────────────────────────────────────────┐
│                      Application Layer                        │
│              (TUI / CLI / API Client / Remote)                │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                       Gateway Layer                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │ HTTP Server │ WebSocket/gRPC │ API Router    │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                        Kernel Layer                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Plugin System                           │   │
│  │  Loader │ Registry │ BasePlugin Interface           │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              EventBus                                │   │
│  │  Publish/Subscribe · Async Communication             │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                       Service Layer                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │AgentService │ SkillService  │ MemoryService │ Task     │
│  │             │               │               │ Service  │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心组件详解

### 1. Gateway Layer（网关层）

**位置：** `src/core/gateway/`

| 文件 | 功能 |
|------|------|
| `gateway.py` | 主入口，协调各组件启动 |
| `gateway_core.py` | 核心逻辑调度 |
| `event_bus.py` | 发布订阅事件总线 |
| `service_locator.py` | 服务注册与发现 |

**协议支持：**
- HTTP Server (`protocol/http_server.py`)
- WebSocket/gRPC (`protocol/websocket.py`, `gateway_grpc.py`)

---

### 2. Plugin System（插件系统）

**位置：** `src/plugins/`

#### 核心组件

| 文件 | 功能 |
|------|------|
| `base.py` | BasePlugin 抽象基类定义 |
| `loader.py` | PluginLoader - 插件加载器 |
| `registry.py` | PluginRegistry - 插件注册表 |

#### 插件接口规范

```python
class BasePlugin(ABC):
    """插件基类"""
    
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    @abstractmethod
    def version(self) -> str: ...
    
    async def on_load(self, config: dict = None) -> bool: ...
    async def on_start(self) -> bool: ...
    async def on_stop(self) -> bool: ...
    async def on_unload(self) -> bool: ...
```

#### 已实现插件

| 插件 | 文件 | 功能 |
|------|------|------|
| **AgentPlugin** | `agent_plugin.py` | 智能体生命周期管理、对话执行 |

---

### 3. Service Layer（服务层）

**位置：** `src/core/gateway/services/`

#### 核心服务

| 服务 | 文件 | 功能描述 |
|------|------|----------|
| **AgentService** | `agent_service.py` | - 创建/删除/切换智能体<br>- 对话执行与流式输出<br>- 会话管理 |
| **SkillService** | `skill_service.py` | - 技能发现与加载<br>- 技能执行接口<br>- MCP 工具集成 |
| **MemoryService** | `memory_service.py` | - Markdown 格式记忆存储<br>- 长期/短期记忆管理<br>- 记忆压缩与检索 |
| **TaskService** | `task_service.py` | - 待办任务管理<br>- 优先级调度<br>- 任务状态追踪 |

---

### 4. EventBus（事件总线）

**位置：** `src/core/event.py`

异步事件驱动机制，支持组件间松耦合通信：

```python
# 发布事件
event_bus.publish("agent.created", {"agent_id": "default"})

# 订阅事件
@event_bus.subscribe("agent.*")
async def on_agent_event(data):
    print(f"Agent event: {data}")
```

**支持的事件类型：**
- `agent.*` - 智能体相关事件
- `skill.*` - 技能相关事件
- `memory.*` - 记忆相关事件
- `task.*` - 任务相关事件

---

### 5. Session Management（会话管理）

**位置：** `src/core/session_manager/`

基础会话生命周期管理功能：

| 文件 | 功能 |
|------|------|
| `session_manager.py` | 会话创建、切换、销毁 |
| `base_session.py` | 会话基类定义 |

**核心能力：**
- 多会话并发支持
- 会话状态持久化
- 对话历史追踪

---

## 配置系统

### dfecrab.json 配置项

```json
{
  "model": {
    "provider": "openai_compatible",
    "api_base": "http://192.168.1.150:4096/v1",
    "model_name": "Qwen3-Coder-30B"
  },
  "gateway": {
    "host": "localhost",
    "port": 6789,
    "api_version": "v1"
  },
  "directories": {
    "skills": "skills",
    "logs": "logs",
    "memory": "memory",
    "workspace": "workspace",
    "agents": "agents"
  }
}
```

---

## 开发指南

### 创建新服务

```python
# src/core/gateway/services/my_service.py
from src.core.gateway.services.base import BaseService

class MyService(BaseService):
    name = "my_service"
    
    async def initialize(self) -> bool:
        # 初始化逻辑
        return True
    
    async def execute(self, **kwargs):
        # 服务执行逻辑
        return {"result": "..."}
```

### 创建新插件

```python
# src/plugins/my_plugin.py
from src.plugins.registry import BasePlugin

class MyPlugin(BasePlugin):
    name = "my_plugin"
    version = "1.0.0"
    
    async def on_load(self, config=None) -> bool:
        return True
    
    async def on_start(self) -> bool:
        return True
```

---

## 技术栈

| 类别 | 技术选型 |
|------|----------|
| **语言** | Python 3.10+ |
| **框架** | AgentScope (智能体框架) |
| **HTTP** | httpx / aiohttp |
| **序列化** | pydantic |
| **日志** | logging + file rotation |
| **并发** | asyncio |

---

## 版本规划

### v4.0 (当前版本 - 2026-04)

**已实现：**
- ✅ 微内核架构设计
- ✅ 插件系统基础框架
- ✅ 四大核心服务（Agent/Skill/Memory/Task）
- ✅ 事件总线通信机制
- ✅ Gateway 多协议支持

### v4.1 (未来规划)

**计划功能：**
- 🔜 权限系统与破坏性命令检测
- 🔜 斜杠命令系统（本地快捷指令）
- 🔜 Agent 增强循环（流式输出优化）
- 🔜 统一工具系统标准化

### v5.0 (长期愿景)

**规划方向：**
- 📍 分级权限系统（Read/Write/Shell/Unsafe）
- 📍 会话完整持久化与回放
- 📍 上下文引擎（CLAUDE.md 发现、Token 估算）
- 📍 工作区配置驱动（AGENTS.md/SOUL.md）
- 📍 自我反思与持续改进机制

---

## 参考资源

- [用户手册](../用户手册/README.md) - 详细使用指南
- [API 文档](../API 接口文档.md) - RESTful API 参考
- [设计说明书](./01-总体设计/PROJECT_OVERVIEW.md) - 项目概览

---

**文档版本：** v4.0 (实际架构版)  
**更新时间：** 2026-04-06  
**状态：** ✅ 基于实际代码更新
