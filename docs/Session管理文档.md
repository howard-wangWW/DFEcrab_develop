# DFEcrab Session 管理系统文档

> 生成日期：2026-04-05
> 适用版本：DFEcrab v4.0.0 (gRPC架构)
> 文档类型：架构设计 + API 文档

---

## 📋 目录

- [架构设计](#架构设计)
- [Session 生命周期](#session-生命周期)
- [前后台交互流程](#前后台交互流程)
- [API 接口](#api-接口)
- [前端使用指南](#前端使用指南)
- [定时任务 Session 管理](#定时任务-session-管理)
- [数据持久化](#数据持久化)

---

## 架构设计

### 设计原则

**Session 管理由后台框架全权负责**，前端只负责：
- 保存 session_id（用于后续请求）
- 显示 session 列表和摘要
- 提供用户交互（新建、切换、关闭）

### 核心组件

```
┌─────────────────────────────────────────────────┐
│              前端（Web/CLI/API）                  │
│  - 可选传入 session_id                          │
│  - 显示返回的 session_id 和 summary             │
│  - 支持：新建、列表、查看、关闭 session          │
└──────────────────┬──────────────────────────────┘
                   │ HTTP POST /api/v2/chat
                   ▼
┌─────────────────────────────────────────────────┐
│          Gateway (后台框架)                       │
│                                                 │
│  1. 检查请求是否带 session_id：                  │
│     ├─ 有 → 复用现有 session                    │
│     └─ 无 → 创建新 session                      │
│                                                 │
│  2. 新 session 首次对话时：                      │
│     ├─ 调用规则引擎生成 session 摘要             │
│     ├─ 保存到 session 元数据                     │
│     └─ 返回给前端 session_id + summary          │
│                                                 │
│  3. 构建增强消息（包含上下文）：                  │
│     ├─ 最近 5 条历史对话                         │
│     ├─ session 摘要                             │
│     └─ session_id                               │
│                                                 │
│  4. 调用 Manager Agent（gRPC）                   │
│                                                 │
│  5. 保存 AI 响应到 session 历史                   │
│  6. 持久化 session 到文件系统                     │
│  7. 返回响应（含 session_id 和 summary）          │
└──────────────────┬──────────────────────────────┘
                   │ gRPC（带 session_id）
                   ▼
┌─────────────────────────────────────────────────┐
│          Manager Agent                           │
│  - 接收增强后的消息（已含上下文）                 │
│  - 根据 session_id 识别连续对话                   │
│  - 执行任务（简单/复杂）                          │
│  - 返回结果                                      │
└─────────────────────────────────────────────────┘
```

---

## Session 生命周期

### 状态流转

```
[创建] → [ACTIVE] ←→ [消息交互]
            ↓
      [120分钟无活动]
            ↓
        [EXPIRED]
            ↓
    [手动关闭/删除]
            ↓
        [CLOSED/删除]
```

### 关键节点

| 节点 | 触发条件 | 后台动作 |
|------|----------|----------|
| **创建** | 用户首次发消息（不带 session_id）| 生成 session_id，初始化元数据 |
| **摘要生成** | 新 session 首次对话 | 分析消息内容，生成任务摘要 |
| **消息记录** | 每次用户/AI 消息 | 添加到 session 历史（最大 100 条）|
| **持久化** | 每次 AI 响应后 | 保存 session 元数据和消息到文件 |
| **过期** | 120 分钟无活动 | 标记为 EXPIRED，不再接受新消息 |
| **关闭** | 用户主动关闭 | 标记为 CLOSED，保留历史 |
| **清理** | 定时任务（每 5 分钟）| 自动标记过期 session |

---

## 前后台交互流程

### 场景 1：用户开始新对话

```
前端                          后台
 │                             │
 │  POST /api/v2/chat          │
 │  {                          │
 │    "message": "帮我写诗"     │
 │    // 不带 session_id       │
 │  }                          │
 ├────────────────────────────>│
 │                             │ 1. 创建新 session
 │                             │ 2. 生成摘要："文学创作任务"
 │                             │ 3. 保存用户消息
 │                             │ 4. 调用 Manager Agent
 │                             │ 5. 保存 AI 响应
 │                             │ 6. 持久化到文件
 │                             │
 │  {                          │
 │    "success": true,         │
 │    "session_id": "session_xxx", │
 │    "session_summary": "文学创作任务",│
 │    "is_new_session": true,  │
 │    "message": "# 春之韵..." │
 │  }                          │
 │<────────────────────────────┤
 │                             │
 │ 保存 session_id 到本地存储   │
```

### 场景 2：用户继续对话

```
前端                          后台
 │                             │
 │  POST /api/v2/chat          │
 │  {                          │
 │    "message": "改成秋天",    │
 │    "session_id": "session_xxx" │  // 使用上次返回的 ID
 │  }                          │
 ├────────────────────────────>│
 │                             │ 1. 查找 session（验证未过期）
 │                             │ 2. 加载最近 10 条消息历史
 │                             │ 3. 构建增强消息（含上下文）
 │                             │    [会话上下文]
 │                             │    主题: 文学创作任务
 │                             │    历史对话:
 │                             │    [用户]: 帮我写诗
 │                             │    [助手]: # 春之韵...
 │                             │    ---
 │                             │    当前消息: 改成秋天
 │                             │ 4. 调用 Manager Agent
 │                             │ 5. 保存响应到 session
 │                             │
 │  {                          │
 │    "success": true,         │
 │    "session_id": "session_xxx", │  // 相同 ID
 │    "session_summary": "文学创作任务",│
 │    "is_new_session": false, │  // 标记为现有会话
 │    "message": "# 秋思..."   │
 │  }                          │
 │<────────────────────────────┤
```

### 场景 3：用户开新话题

```
前端                          后台
 │                             │
 │  POST /api/v2/chat          │
 │  {                          │
 │    "message": "分析电网数据"  │
 │    // 不带 session_id       │  // 故意不带，创建新会话
 │  }                          │
 ├────────────────────────────>│
 │                             │ 1. 创建新 session
 │                             │ 2. 生成摘要："数据分析 + 电网监控任务"
 │                             │ 3. ...（同场景 1）
 │                             │
 │  {                          │
 │    "session_id": "session_yyy", │  // 新的 ID
 │    "session_summary": "数据分析 + 电网监控任务",│
 │    "is_new_session": true,  │
 │    ...                      │
 │  }                          │
 │<────────────────────────────┤
 │                             │
 │ 保存新的 session_id          │
 │ 旧的 session_xxx 仍保留      │
 │ 用户可随时切换回去            │
```

---

## API 接口

### 1. 聊天对话（核心接口）

**POST** `/api/v2/chat`

**描述**: 发送消息并获取 AI 响应

**请求体**:
```json
{
  "message": "帮我写一首关于春天的诗",
  "session_id": "可选，不提供则创建新 session",
  "user_id": "可选，默认 default"
}
```

**响应**:
```json
{
  "success": true,
  "session_id": "session_fc4f1bd28fa4",
  "session_summary": "文学创作任务",
  "is_new_session": true,
  "message": "# 春之韵\n\n春风拂面柳依依...",
  "task_type": "simple",
  "agents_used": ["reporter_agent"],
  "audit_log_id": "audit_xxx",
  "gateway_elapsed_ms": 4
}
```

**关键字段说明**:
- `session_id`: 会话 ID，**前端应保存此 ID** 用于后续对话
- `session_summary`: 会话摘要，**前端可显示给用户**了解当前上下文
- `is_new_session`: 是否为新创建的 session

---

### 2. 列出所有 Session

**GET** `/api/v2/sessions?limit=50`

**描述**: 获取用户的所有会话列表

**查询参数**:
- `limit`: 返回数量限制（默认 50）

**响应**:
```json
{
  "success": true,
  "count": 3,
  "sessions": [
    {
      "id": "session_fc4f1bd28fa4",
      "user_id": "default",
      "status": "active",
      "topic": "未命名会话",
      "summary": "文学创作任务",
      "created_at": "2026-04-05T17:24:00.723577",
      "last_active": "2026-04-05T17:24:31.650351",
      "message_count": 4,
      "summary_generated": true
    }
  ]
}
```

**前端用途**: 显示 session 列表，让用户选择切换会话

---

### 3. 创建新 Session（可选）

**POST** `/api/v2/sessions`

**描述**: 显式创建空 session（可选，通常不需要）

**请求体**:
```json
{
  "topic": "电网监控",
  "user_id": "default"
}
```

**响应**:
```json
{
  "success": true,
  "session": {
    "id": "session_xxx",
    "topic": "电网监控",
    ...
  }
}
```

**说明**: 通常不需要调用此接口，用户首次发消息时会自动创建 session

---

### 4. 获取 Session 详情

**GET** `/api/v2/sessions/{session_id}`

**描述**: 获取单个 session 的元数据

**响应**:
```json
{
  "success": true,
  "session": {
    "id": "session_fc4f1bd28fa4",
    "status": "active",
    "summary": "文学创作任务",
    "message_count": 4,
    "created_at": "2026-04-05T17:24:00.723577",
    "last_active": "2026-04-05T17:24:31.650351",
    ...
  }
}
```

---

### 5. 获取 Session 消息历史

**GET** `/api/v2/sessions/{session_id}/messages?limit=20`

**描述**: 获取 session 的消息历史

**查询参数**:
- `limit`: 返回消息数量（默认 20）

**响应**:
```json
{
  "success": true,
  "count": 4,
  "messages": [
    {
      "role": "user",
      "content": "帮我写一首关于春天的诗",
      "timestamp": "2026-04-05T17:24:00.723577"
    },
    {
      "role": "assistant",
      "content": "# 春之韵\n\n春风拂面柳依依...",
      "timestamp": "2026-04-05T17:24:01.123456"
    }
  ]
}
```

**前端用途**: 显示历史对话记录，支持重新加载会话

---

### 6. 关闭 Session

**DELETE** `/api/v2/sessions/{session_id}`

**描述**: 关闭指定 session

**响应**:
```json
{
  "success": true,
  "message": "会话已关闭: session_xxx"
}
```

**说明**: 关闭后 session 不再接受新消息，但历史记录保留

---

## 前端使用指南

### Vue3 完整示例

```typescript
// stores/session.ts
import { ref } from 'vue'

interface Session {
  id: string
  summary: string
  message_count: number
  last_active: string
  status: string
}

const currentSessionId = ref<string | null>(null)
const sessionSummary = ref<string>('')
const sessions = ref<Session[]>([])

// 发送消息
async function sendMessage(message: string) {
  const payload: any = { message }
  
  // 如果有当前 session，带上 session_id
  if (currentSessionId.value) {
    payload.session_id = currentSessionId.value
  }
  
  const response = await fetch('http://localhost:6789/api/v2/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  
  const data = await response.json()
  
  if (data.success) {
    // 保存 session_id（可能是新的或现有的）
    currentSessionId.value = data.session_id
    sessionSummary.value = data.session_summary
    
    // 如果是新会话，刷新列表
    if (data.is_new_session) {
      await loadSessions()
    }
    
    return data.message
  } else {
    throw new Error(data.error)
  }
}

// 加载 session 列表
async function loadSessions() {
  const response = await fetch('http://localhost:6789/api/v2/sessions')
  const data = await response.json()
  sessions.value = data.sessions
}

// 切换 session
async function switchSession(sessionId: string) {
  currentSessionId.value = sessionId
  
  // 获取 session 详情
  const response = await fetch(`http://localhost:6789/api/v2/sessions/${sessionId}`)
  const data = await response.json()
  sessionSummary.value = data.session.summary
  
  // 加载消息历史
  await loadMessages(sessionId)
}

// 新建 session（开新话题）
function startNewConversation() {
  currentSessionId.value = null
  sessionSummary.value = ''
  messages.value = []
}

// 关闭 session
async function closeSession(sessionId: string) {
  await fetch(`http://localhost:6789/api/v2/sessions/${sessionId}`, {
    method: 'DELETE'
  })
  await loadSessions()
}
```

### 关键要点

1. **保存 session_id**: 每次收到响应后保存 `session_id`
2. **后续请求带上**: 后续请求在请求体中包含 `session_id`
3. **显示摘要**: 使用 `session_summary` 提示用户当前上下文
4. **检查新会话**: 根据 `is_new_session` 判断是否刷新列表
5. **开新话题**: 不带 `session_id` 即可创建新会话

---

## 定时任务 Session 管理

### 设计说明

定时任务也通过 Session Manager 统一管理，特点：

- **Session ID 格式**: `periodic_{task_id}`
- **固定 ID**: 同一任务的多次执行使用相同 session_id
- **便于查询**: 可通过 API 查看定时任务执行历史
- **自动摘要**: 首次执行时生成摘要（包含执行间隔）

### 查看定时任务 Session

```bash
# 列出所有 session（包括定时任务）
curl http://localhost:6789/api/v2/sessions

# 查看特定定时任务的 session
curl http://localhost:6789/api/v2/sessions/periodic_7f3a9c2d1b45

# 查看定时任务的执行历史
curl http://localhost:6789/api/v2/sessions/periodic_7f3a9c2d1b45/messages
```

### 响应示例

```json
{
  "success": true,
  "session": {
    "id": "periodic_7f3a9c2d1b45",
    "summary": "定时任务 - 电网负载监控与报告 (多智能体协作)（每60秒）",
    "message_count": 12,
    "status": "active",
    "topic": "定时任务: 电网负载监控与报告 (多智能体协作)"
  }
}
```

---

## 数据持久化

### 存储位置

```
data/sessions/
├── session_fc4f1bd28fa4.json           # Session 元数据
├── session_fc4f1bd28fa4_messages.json  # Session 消息历史
├── periodic_7f3a9c2d1b45.json
└── periodic_7f3a9c2d1b45_messages.json
```

### Session 元数据格式

```json
{
  "id": "session_fc4f1bd28fa4",
  "user_id": "default",
  "agent_id": "default",
  "client_type": "api",
  "status": "active",
  "topic": "未命名会话",
  "summary": "文学创作任务",
  "created_at": "2026-04-05T17:24:00.723577",
  "last_active": "2026-04-05T17:24:31.650351",
  "message_count": 4,
  "summary_generated": true
}
```

### 消息历史格式

```json
[
  {
    "role": "user",
    "content": "帮我写一首关于春天的诗",
    "timestamp": "2026-04-05T17:24:00.723577",
    "metadata": {}
  },
  {
    "role": "assistant",
    "content": "# 春之韵\n\n...",
    "timestamp": "2026-04-05T17:24:01.123456",
    "metadata": {}
  }
]
```

### 持久化策略

- **每次 AI 响应后**: 立即保存 session 元数据和消息
- **服务启动时**: 自动加载所有 session 到内存
- **过期清理**: 每 5 分钟检查一次，标记 120 分钟无活动的 session

---

## 测试验证

### 完整测试流程

```bash
# 1. 首次对话（自动创建 session）
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "帮我写一首关于春天的诗"}'

# 响应包含:
# "session_id": "session_xxx"
# "session_summary": "文学创作任务"
# "is_new_session": true

# 2. 继续对话（使用 session_id）
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "改成关于秋天的", "session_id": "session_xxx"}'

# 响应:
# "is_new_session": false
# "session_summary": "文学创作任务"

# 3. 开新话题（不带 session_id）
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "分析电网数据"}'

# 响应:
# "session_id": "session_yyy" (新 ID)
# "session_summary": "数据分析 + 电网监控任务"
# "is_new_session": true

# 4. 列出所有 session
curl http://localhost:6789/api/v2/sessions

# 5. 查看 session 消息历史
curl http://localhost:6789/api/v2/sessions/session_xxx/messages

# 6. 关闭 session
curl -X DELETE http://localhost:6789/api/v2/sessions/session_xxx
```

---

## 大模型集成

### 架构说明

DFEcrab 通过 **llama.cpp server** 连接远程大模型，支持 OpenAI 兼容 API。

**当前配置：**
- **LLM Server**: `http://192.168.1.150:4096`
- **模型**: `Qwen3-Coder-30B-A3B-Instruct-4bit`
- **API 端点**: `/v1/chat/completions`

### Agent 如何调用大模型

当 Agent 需要生成内容时（非规则模板场景），会调用远程大模型：

```python
# Agent 内部调用大模型
llm_url = "http://192.168.1.150:4096/v1/chat/completions"
model_name = "/Users/e8900ai/LLM_Fine/models/qwen/Qwen3-Coder-30B-A3B-Instruct-4bit"

payload = {
    "model": model_name,
    "messages": [
        {"role": "user", "content": prompt}  # prompt 包含完整上下文
    ],
    "stream": False,
    "temperature": 0.7
}

response = requests.post(llm_url, json=payload, timeout=60)
result = response.json()
generated_content = result["choices"][0]["message"]["content"]
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
Agent 提取当前消息 + 上下文:
  - 检测到非电网任务
  - 调用大模型，传入完整上下文
  - 大模型理解"改成秋天"是在修改诗歌
         ↓
大模型生成:
  "秋风染红叶，雁阵向南飞。
   霜露沾草尖，收获满田归。"
```

### 配置方法

**1. 编辑 `dfecrab.json`：**
```json
{
  "model": {
    "provider": "ollama",
    "model_name": "qwen3.5:4b",
    "model_type": "ollama_chat",
    "config_name": "ollama_qwen",
    "api_base": "http://192.168.1.150:4096/v1",
    "timeout": 60
  }
}
```

**2. Agent 调用代码：**
见 `services/agent_service/agent_service_grpc.py` 中的 `_execute_reporter_skills` 方法。

### 测试验证

```bash
# 测试大模型 API 是否可用
curl http://192.168.1.150:4096/v1/models

# 测试对话
curl http://192.168.1.150:4096/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "/Users/e8900ai/LLM_Fine/models/qwen/Qwen3-Coder-30B-A3B-Instruct-4bit",
    "messages": [{"role": "user", "content": "写一首关于秋天的诗"}],
    "stream": false,
    "max_tokens": 200
  }'
```

---

## 总结

### 前台职责（前端）

- ✅ 保存 `session_id`（每次响应后）
- ✅ 后续请求带上 `session_id`（继续对话）
- ✅ 不带 `session_id`（开新话题）
- ✅ 显示 `session_summary`（提示用户上下文）
- ✅ 提供 session 列表供用户切换
- ✅ 支持新建、关闭 session

### 后台职责（框架）

- ✅ 创建/查找 session
- ✅ 生成 session 摘要（首次对话）
- ✅ 加载 session 历史（最近 10 条）
- ✅ 构建增强消息（包含上下文）
- ✅ 保存消息到 session 历史
- ✅ 持久化到文件系统
- ✅ 过期自动清理
- ✅ 统一管理所有 session（包括定时任务）
- ✅ 调用远程大模型生成智能内容

---

*文档版本：v1.1 | 更新日期：2026-04-05*
