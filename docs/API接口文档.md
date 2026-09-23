# DFEcrab API 接口文档

> 生成日期：2026-04-06  
> 适用版本：DFEcrab v4.0.0-grpc  
> 后端技术：Python (自定义 HTTP Server + gRPC + Zookeeper)

---

## 基础信息

### 服务地址

| 服务 | 地址 | 说明 |
|------|------|------|
| **HTTP API** | `http://localhost:6789` | 主 API 端口 |
| **gRPC** | `localhost:2181` (Zookeeper) | 服务发现与负载均衡 |
| **健康检查** | `http://localhost:6789/health` | 服务状态 |

### 架构说明

DFEcrab 采用 gRPC 架构：
- **对外**：HTTP API (6789端口)
- **对内**：gRPC + Zookeeper (2181端口) 调用 Manager 和 Workers
- **服务发现**：通过 Zookeeper 实现动态服务注册与发现

```
用户 -> HTTP(6789) -> Gateway -> gRPC -> Manager(随机端口)
                                      ↓
                                 Zookeeper(2181)
                                      ↓
                                 Workers(随机端口)
```

### 通用响应格式

**成功响应**:
```json
{
  "success": true,
  "data": { ... }
}
```

**错误响应**:
```json
{
  "success": false,
  "error": "错误描述信息"
}
```

---

## API 路由列表

### 现有 11 个路由

| 序号 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 0 | GET | `/health` | 健康检查 |
| 1 | POST | `/api/v2/chat` | 聊天对话 |
| 2 | GET | `/api/v2/sessions` | 获取所有会话 |
| 3 | POST | `/api/v2/sessions` | 创建新会话 |
| 4 | GET | `/api/v2/sessions/{session_id}` | 获取会话详情 |
| 5 | GET | `/api/v2/sessions/{session_id}/messages` | 获取会话消息历史 |
| 6 | DELETE | `/api/v2/sessions/{session_id}` | 删除会话 |
| 7 | POST | `/api/v2/tasks` | 创建任务 |
| 8 | GET | `/api/v2/tasks` | 获取任务列表 |
| 9 | GET | `/api/v2/tasks/{task_id}` | 获取任务详情 |
| 10 | DELETE | `/api/v2/tasks/{task_id}` | 删除任务 |

---

## 核心接口详解

### 1. 健康检查

#### GET /health

**响应示例**:
```json
{
  "gateway": "running",
  "version": "2.0.0-grpc",
  "manager_agent": "healthy",
  "worker_agents": 3,
  "architecture": "Gateway(6789/HTTP) -> Manager(gRPC) -> Workers(gRPC) via Zookeeper"
}
```

---

### 2. 聊天对话 ⭐⭐⭐⭐⭐

#### POST /api/v2/chat

**描述**: 核心聊天接口，自动识别任务类型并调度智能体

**请求体**:
```json
{
  "message": "你好，请帮我分析电网情况",
  "session_id": "可选，不传会自动创建"
}
```

**响应示例**:
```json
{
  "success": true,
  "session_id": "session_abc123",
  "task_type": "simple",
  "agents_used": ["reporter_agent"],
  "message": "根据数据分析，今日电网负荷...",
  "gateway_elapsed_ms": 10091,
  "audit_log_id": "audit_xxx"
}
```

**任务类型说明**:
- `simple`: 简单任务，调用单个 Agent
- `complex`: 复杂任务，多 Agent 协作

---

### 3. 会话管理 ⭐⭐⭐⭐⭐

#### GET /api/v2/sessions

**描述**: 获取所有会话列表

**响应示例**:
```json
{
  "success": true,
  "count": 14,
  "sessions": [
    {
      "id": "session_abc123",
      "user_id": "default",
      "agent_id": "default",
      "client_type": "api",
      "status": "active",
      "topic": "未命名会话",
      "summary": "数据分析任务",
      "created_at": "2026-04-06T19:35:41.286052",
      "last_active": "2026-04-06T19:36:22.200089",
      "message_count": 2,
      "summary_generated": true
    }
  ]
}
```

---

#### GET /api/v2/sessions/{session_id}

**描述**: 获取指定会话详情

**响应示例**:
```json
{
  "success": true,
  "session": {
    "id": "session_abc123",
    "user_id": "default",
    "agent_id": "default",
    "status": "active",
    "topic": "电网分析",
    "summary": "复杂任务",
    "created_at": "2026-04-06T19:35:41",
    "last_active": "2026-04-06T19:36:22",
    "message_count": 2
  }
}
```

---

#### GET /api/v2/sessions/{session_id}/messages

**描述**: 获取会话的消息历史

**响应示例**:
```json
{
  "success": true,
  "count": 2,
  "messages": [
    {
      "role": "user",
      "content": "请分析当前电网运行状态，生成一份详细的调度报告",
      "timestamp": "2026-04-06T19:35:41.286188",
      "metadata": {}
    },
    {
      "role": "assistant",
      "content": "复杂任务完成！执行了 3 个步骤: analyst_agent -> reporter_agent -> file_manager_agent",
      "timestamp": "2026-04-06T19:36:22.200084",
      "metadata": {}
    }
  ]
}
```

---

#### POST /api/v2/sessions

**描述**: 创建新会话

**请求体**:
```json
{
  "user_id": "default",
  "agent_id": "default",
  "topic": "新会话主题"
}
```

---

#### DELETE /api/v2/sessions/{session_id}

**描述**: 删除指定会话

---

### 4. 任务管理

#### GET /api/v2/tasks

**描述**: 获取所有任务列表（包含定时任务）

**响应示例**:
```json
{
  "success": true,
  "tasks": [
    {
      "task_id": "periodic_7f3a9c2d1b45",
      "name": "电网负载监控与报告",
      "interval": 60,
      "enabled": true,
      "last_run": "2026-04-06T19:39:22",
      "next_run": "2026-04-06T19:40:22"
    }
  ]
}
```

---

#### POST /api/v2/tasks

**描述**: 创建新任务

**请求体**:
```json
{
  "name": "我的任务",
  "message": "执行分析",
  "interval": 60,
  "enabled": true
}
```

---

#### GET /api/v2/tasks/{task_id}

**描述**: 获取任务详情

---

#### DELETE /api/v2/tasks/{task_id}

**描述**: 删除任务

---

## 使用示例

### 查看所有会话

```bash
curl http://localhost:6789/api/v2/sessions
```

### 查看指定会话消息

```bash
curl http://localhost:6789/api/v2/sessions/session_abc123/messages
```

### 发送聊天消息

```bash
curl -X POST http://localhost:6789/api/v2/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请介绍一下自己"}'
```

### Python 调用示例

```python
import requests
import json

API_BASE = "http://localhost:6789"

# 查看所有会话
def get_sessions():
    resp = requests.get(f"{API_BASE}/api/v2/sessions")
    data = resp.json()
    for s in data.get("sessions", []):
        print(f"{s['id']} - {s['summary']} ({s['message_count']}条消息)")

# 查看会话消息
def get_messages(session_id):
    resp = requests.get(f"{API_BASE}/api/v2/sessions/{session_id}/messages")
    data = resp.json()
    for msg in data.get("messages", []):
        print(f"[{msg['role']}] {msg['content']}")

# 发送聊天
def chat(message):
    resp = requests.post(f"{API_BASE}/api/v2/chat", json={"message": message})
    data = resp.json()
    print(f"任务类型: {data.get('task_type')}")
    print(f"使用智能体: {' -> '.join(data.get('agents_used', []))}")
    print(f"响应: {data.get('message')}")
```

---

## 配置说明

### 主配置文件 dfecrab.json

```json
{
  "version": "1.0.0",
  "model": {
    "provider": "ollama",
    "model_name": "deepseek-v3.1:671b-cloud",
    "api_base": "http://localhost:11434/v1",
    "timeout": 120
  },
  "gateway": {
    "host": "localhost",
    "port": 6789
  },
  "default_agent": {
    "agent_id": "default",
    "system_prompt": "你是一个名为 DFEcrab 的智能助手，专为电网运维提供服务。"
  }
}
```

### 可用智能体

| Agent ID | 说明 |
|----------|------|
| `default` | 默认智能体 |
| `reporter_agent` | 报告生成 |
| `analyst_agent` | 数据分析 |
| `file_manager_agent` | 文件管理 |

---

## 审计日志

每次请求都会生成审计日志，保存在 `data/tasks/audit/` 目录：

```json
{
  "audit_id": "audit_225a90e5af7c",
  "session_id": "session_b4261d51aba9",
  "timestamp": "2026-04-06T19:35:35.291908",
  "intent": {
    "type": "simple",
    "target_agent": "reporter_agent"
  },
  "result": {
    "success": true,
    "task_type": "simple",
    "agents_used": ["reporter_agent"]
  }
}
```

---

*文档生成时间: 2026-04-06*  
*后端负责人: DFEcrab Team*
