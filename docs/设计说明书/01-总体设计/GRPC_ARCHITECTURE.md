# DFEcrab gRPC 架构设计文档

> **生成日期**: 2026-04-05
> **适用版本**: DFEcrab v4.0.0 (gRPC架构)
> **文档类型**: 架构设计

---

## 📋 目录

- [架构概述](#架构概述)
- [核心组件](#核心组件)
- [通信协议](#通信协议)
- [服务发现](#服务发现)
- [Session 管理](#session-管理)
- [任务调度](#任务调度)
- [大模型集成](#大模型集成)
- [部署指南](#部署指南)
- [故障排查](#故障排查)

---

## 架构概述

### 整体架构

DFEcrab v4.0 采用 **gRPC 微服务架构**，实现多智能体协同工作：

```
┌─────────────────────────────────────────────────────────────────┐
│                        客户端层                                  │
│  Web UI  │  CLI  │  API 调用  │  定时任务                        │
└─────────────────────────┬───────────────────────────────────────┘
                          │ HTTP (6789)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Gateway 层                                 │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  HTTP Server (6789)                                       │ │
│  │  - 路由管理                                               │ │
│  │  - Session 管理                                           │ │
│  │  - 请求增强（添加上下文）                                  │ │
│  └───────────────────────┬───────────────────────────────────┘ │
│                          │ gRPC                                │
│                          ▼                                     │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Session Manager                                          │ │
│  │  - 创建/查找 Session                                      │ │
│  │  - 生成摘要                                                │ │
│  │  - 加载历史                                                │ │
│  │  - 持久化存储                                              │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Periodic Scheduler                                       │ │
│  │  - 定时任务管理                                            │ │
│  │  - 任务执行调度                                            │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────────┘
                          │ gRPC (Zookeeper 服务发现)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Manager Agent 层                             │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Manager Agent (gRPC :50050)                              │ │
│  │  - 意图识别                                                │ │
│  │  - 任务分流（简单/复杂）                                   │ │
│  │  - 工作流编排                                              │ │
│  │  - 审计日志                                                │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────────┘
                          │ gRPC (Zookeeper 服务发现)
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Worker Agents 层                             │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ Analyst      │  │ Reporter     │  │ File Manager │        │
│  │ Agent        │  │ Agent        │  │ Agent        │        │
│  │ (随机端口)    │  │ (随机端口)    │  │ (随机端口)    │        │
│  │              │  │              │  │              │        │
│  │ - 数据分析    │  │ - 报告生成    │  │ - 文件保存    │        │
│  │ - 信息提取    │  │ - 内容创作    │  │ - 文件管理    │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Zookeeper (2181)                             │
│  - 服务注册                                                     │
│  - 服务发现                                                     │
│  - 健康检查                                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 架构特点

| 特点 | 说明 |
|------|------|
| **服务解耦** | Gateway、Manager、Workers 独立进程，通过 gRPC 通信 |
| **动态发现** | Zookeeper 自动发现和注册服务，支持动态扩缩容 |
| **Session 管理** | 后台框架统一管理，前端无状态 |
| **智能内容生成** | 集成远程大模型（llama.cpp server） |
| **定时任务** | 内置调度器，支持周期性任务执行 |

---

## 核心组件

### 1. Gateway（网关）

**位置**: `src/core/gateway/gateway_grpc.py`

**职责**:
- HTTP API 服务（6789 端口）
- Session 生命周期管理
- 请求增强（添加上下文）
- 定时任务调度
- 调用 Manager Agent

**核心流程**:
```
用户请求 → 检查 session_id
          ├─ 有 → 复用 session
          └─ 无 → 创建新 session → 生成摘要
          
          ↓
       加载历史（最近 10 条）
          ↓
       构建增强消息（含上下文）
          ↓
       gRPC 调用 Manager Agent
          ↓
       保存响应到 session
          ↓
       返回结果（含 session_id）
```

### 2. Manager Agent

**位置**: `services/manager_agent/manager_agent_grpc.py`

**职责**:
- 意图识别（简单/复杂任务）
- 任务分流
- 工作流编排（多 Agent 协作）
- 审计日志记录

**任务类型**:
| 类型 | 说明 | 示例 |
|------|------|------|
| **simple** | 单 Agent 执行 | 写诗、查询 |
| **complex** | 多 Agent 协作 | 数据分析→报告→保存 |

### 3. Worker Agents

**位置**: `services/agent_service/agent_service_grpc.py`

**当前 Agent 列表**:

| Agent | 职责 | 技能 |
|-------|------|------|
| **analyst_agent** | 数据分析 | 数据解析、信息提取 |
| **reporter_agent** | 报告生成 | 报告撰写、内容创作（调用大模型） |
| **file_manager_agent** | 文件管理 | 文件保存、读取 |

**Agent 启动流程**:
```
1. 分配随机端口
2. 注册到 Zookeeper
3. 等待 Manager 调用
```

---

## 通信协议

### HTTP API（客户端 → Gateway）

**端口**: 6789

**核心接口**:

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v2/chat` | POST | 聊天对话 |
| `/api/v2/sessions` | GET | 列出 Session |
| `/api/v2/sessions` | POST | 创建 Session |
| `/api/v2/sessions/{id}` | GET | Session 详情 |
| `/api/v2/sessions/{id}/messages` | GET | Session 消息 |
| `/api/v2/sessions/{id}` | DELETE | 关闭 Session |
| `/health` | GET | 健康检查 |

### gRPC（Gateway → Manager）

**端口**: 50050（固定）

**Protobuf 定义**: `proto/dfecrab.proto`

**核心服务**:
```protobuf
service ManagerService {
  rpc Chat(ChatRequest) returns (ChatResponse);
  rpc ManagerHealth(HealthRequest) returns (ManagerHealthStatus);
}

service AgentService {
  rpc Execute(ExecuteRequest) returns (ExecuteResponse);
  rpc Health(HealthRequest) returns (HealthStatus);
}
```

### gRPC（Manager → Workers）

**端口**: 随机分配

**服务发现**: 通过 Zookeeper 查找 Worker 地址

---

## 服务发现

### Zookeeper 注册

**端口**: 2181

**注册路径**:
```
/dfecrab/services/
  ├── manager_agent/
  │   └── manager_agent_{host}_{timestamp}
  └── worker_agent/
      ├── worker_agent_{host}_{timestamp} (analyst)
      ├── worker_agent_{host}_{timestamp} (reporter)
      └── worker_agent_{host}_{timestamp} (file_manager)
```

**服务发现流程**:
```
Manager 需要调用 Worker
         ↓
   查询 Zookeeper
         ↓
   获取 Worker 列表
         ↓
   根据 metadata.agent_id 匹配
         ↓
   建立 gRPC 连接
```

### 健康检查

**Gateway 健康检查**:
```bash
curl http://localhost:6789/health
```

**响应示例**:
```json
{
  "status": "healthy",
  "gateway": "running",
  "version": "2.0.0-grpc",
  "manager_agent": "healthy",
  "worker_agents": 3,
  "architecture": "Gateway(6789/HTTP) -> Manager(gRPC) -> Workers(gRPC) via Zookeeper",
  "zookeeper": "localhost:2181"
}
```

---

## Session 管理

### 架构设计

Session 由 **Gateway 层** 统一管理：

```
┌─────────────────────────────────────┐
│         Gateway                     │
│                                     │
│  Session Manager                    │
│  ├── 创建/查找 Session              │
│  ├── 生成摘要（首次对话）            │
│  ├── 加载历史（最近 10 条）          │
│  ├── 构建增强消息                   │
│  └── 持久化存储                     │
└─────────────────────────────────────┘
```

### Session 生命周期

```
[创建] → [ACTIVE] ←→ [消息交互]
            ↓
      [120分钟无活动]
            ↓
        [EXPIRED]
            ↓
    [手动关闭/删除]
```

### 数据持久化

**存储位置**: `data/sessions/`

**文件结构**:
```
data/sessions/
├── session_xxx.json              # Session 元数据
├── session_xxx_messages.json     # Session 消息历史
├── periodic_task_id.json         # 定时任务 Session
└── periodic_task_id_messages.json
```

### 定时任务 Session

定时任务使用固定的 session_id：`periodic_{task_id}`

- 同一任务的多次执行共享 session
- 便于通过 API 查看执行历史
- 自动摘要包含执行间隔

---

## 任务调度

### 定时任务调度器

**位置**: `src/core/task/periodic_scheduler.py`

**任务配置**: `data/tasks/*.json`

**调度流程**:
```
启动时加载任务
         ↓
   为每个任务创建定时器
         ↓
   定时触发执行
         ↓
   通过 gRPC 调用 Manager Agent
         ↓
   记录执行结果到 Session
```

### 任务示例

```json
{
  "task_id": "7f3a9c2d1b45",
  "topic": "电网负载监控与报告",
  "task_type": "periodic",
  "schedule": {
    "interval_seconds": 60
  },
  "description": "多智能体协作任务：1) 数据分析师读取电网负载数据并分析 2) 报告撰写员生成简洁分析报告 3) 文件管理员将报告保存到本地文件",
  "agent_group_config": {
    "members": [
      {"agent_id": "analyst_agent", "role": "数据分析"},
      {"agent_id": "reporter_agent", "role": "报告生成"},
      {"agent_id": "file_manager_agent", "role": "文件保存"}
    ]
  }
}
```

---

## 大模型集成

### 架构说明

DFEcrab 通过 **llama.cpp server** 连接远程大模型：

| 配置项 | 值 |
|--------|-----|
| **LLM Server** | `http://192.168.1.150:4096` |
| **模型** | `Qwen3-Coder-30B-A3B-Instruct-4bit` |
| **API 端点** | `/v1/chat/completions` |
| **协议** | OpenAI 兼容 API |

### Agent 调用大模型

当 Agent 需要生成内容时（非规则模板场景）：

```python
# reporter_agent 内部
llm_url = "http://192.168.1.150:4096/v1/chat/completions"

payload = {
    "model": model_name,
    "messages": [
        {"role": "user", "content": prompt}  # prompt 包含完整上下文
    ],
    "stream": False,
    "temperature": 0.7
}

response = requests.post(llm_url, json=payload, timeout=60)
generated_content = response.json()["choices"][0]["message"]["content"]
```

### 上下文传递机制

```
用户请求: "改成秋天"
         ↓
Gateway 构建增强消息:
─────────────────────────
[会话上下文]
主题: 文学创作任务
Session ID: session_xxx

历史对话:
[用户]: 写一首春天的诗
[助手]: # 春之韵...

---
当前消息: 改成秋天
─────────────────────────
         ↓
Agent 提取当前消息
         ↓
调用大模型，传入完整上下文
         ↓
大模型理解上下文，生成秋天的诗
```

---

## 部署指南

### 环境要求

| 组件 | 要求 |
|------|------|
| **Python** | 3.10+ |
| **Zookeeper** | 3.8+ (端口 2181) |
| **llama.cpp server** | 远程服务 (端口 4096) |

### 启动流程

```bash
# 1. 确保 Zookeeper 运行
brew services start zookeeper  # macOS
# 或
docker run -d --name zookeeper -p 2181:2181 zookeeper:3.8

# 2. 激活虚拟环境
cd /Users/zhanghanzhi/DFEcrab
source venv/bin/activate

# 3. 启动所有服务
./dfecrab start
```

### 服务验证

```bash
# 检查 Gateway
curl http://localhost:6789/health

# 检查 Session 管理
curl http://localhost:6789/api/v2/sessions

# 测试对话
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "帮我写一首关于春天的诗"}'
```

### 停止服务

```bash
./dfecrab stop
```

---

## 故障排查

### Gateway 启动失败

**问题**: `ModuleNotFoundError: No module named 'click'`

**解决**: 使用虚拟环境的 Python
```bash
venv/bin/python dfecrab start
```

### Manager Agent 连接失败

**问题**: `Manager Agent不可用`

**排查**:
1. 检查 Zookeeper 是否运行
2. 查看 Manager 日志: `logs/manager_grpc.log`
3. 确认 Manager 已注册到 Zookeeper

### Worker Agent 未找到

**问题**: `未找到Agent服务: xxx_agent`

**排查**:
1. 查看 Worker 日志: `logs/worker_*_grpc.log`
2. 确认 Worker 已启动并注册到 Zookeeper
3. 检查 Zookeeper 节点: `zkCli.sh ls /dfecrab/services/worker_agent`

### 大模型调用失败

**问题**: `大模型调用失败: Connection timed out`

**排查**:
1. 确认 llama.cpp server 地址和端口
2. 测试连接: `curl http://192.168.1.150:4096/v1/models`
3. 检查网络连通性: `ping 192.168.1.150`

---

## 日志文件

| 组件 | 日志文件 |
|------|----------|
| **Gateway** | `logs/gateway_grpc.log` |
| **Manager** | `logs/manager_grpc.log` |
| **Analyst** | `logs/worker_analyst_grpc.log` |
| **Reporter** | `logs/worker_reporter_grpc.log` |
| **File Manager** | `logs/worker_file_manager_grpc.log` |

---

*文档版本：v1.0 | 更新日期：2026-04-05*
