# DFEcrab API 使用指南

> REST API 完整使用说明

**版本**: 4.0.0  
**更新日期**: 2026-04-03

---

## 📋 目录

1. [API 接口说明](#api-接口说明)
2. [基础使用](#基础使用)
3. [对话 API](#对话-api)
4. [智能体管理 API](#智能体管理-api)
5. [技能管理 API](#技能管理-api)
6. [记忆管理 API](#记忆管理-api)
7. [会话管理 API](#会话管理-api)
8. [任务管理 API](#任务管理-api)
9. [工具系统 API](#工具系统-api)
10. [权限系统 API](#权限系统-api)
11. [健康检查与统计](#健康检查与统计)
12. [错误处理](#错误处理)

---

## API 接口说明

### 基础信息

- **基础 URL**: `http://localhost:6789`
- **协议**: HTTP/REST
- **数据格式**: JSON
- **认证**: Token（生产环境）

### API 端点总览

| 分类 | 端点 | 方法 | 说明 |
|------|------|------|------|
| **健康检查** | `/health` | GET | 服务健康状态 |
| **对话** | `/api/chat` | POST | 发送对话消息 |
| **智能体** | `/api/agents` | GET/POST | 智能体管理 |
| **技能** | `/api/skills` | GET | 技能列表 |
| **记忆** | `/api/memory` | GET/POST | 记忆管理 |
| **会话** | `/api/sessions` | GET | 会话管理 |
| **任务** | `/api/tasks` | GET/POST | 任务管理 |
| **统计** | `/api/stats` | GET | 系统统计 |
| **工具** | `/api/tools` | GET | 工具列表 |
| **权限** | `/api/permissions` | GET | 权限信息 |

---

## 基础使用

### 健康检查

```bash
curl http://localhost:6789/health
```

**响应示例**：
```json
{
  "status": "healthy",
  "version": "4.0.0",
  "uptime": 3600
}
```

### 查看系统统计

```bash
curl http://localhost:6789/api/stats
```

**响应示例**：
```json
{
  "agents_count": 3,
  "skills_count": 15,
  "sessions_count": 5,
  "tasks_count": 10,
  "memory_size_mb": 2.5
}
```

---

## 对话 API

### 发送消息

```bash
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "default",
    "message": "你好，请介绍一下自己"
  }'
```

**请求参数**：

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `agent_id` | string | 是 | 智能体 ID |
| `message` | string | 是 | 用户消息 |
| `session_id` | string | 否 | 会话 ID（不传则新建） |
| `stream` | boolean | 否 | 是否流式输出（默认 false） |

**响应示例**：
```json
{
  "success": true,
  "session_id": "session_001",
  "agent_id": "default",
  "message": "你好！我是 DFEcrab 智能助手...",
  "metadata": {
    "tokens_used": 150,
    "processing_time_ms": 1200
  }
}
```

### 流式对话

```bash
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "default",
    "message": "写一首诗",
    "stream": true
  }'
```

---

## 智能体管理 API

### 列出智能体

```bash
curl http://localhost:6789/api/agents
```

**响应示例**：
```json
{
  "agents": [
    {
      "agent_id": "default",
      "agent_type": "react",
      "name": "默认智能体",
      "created_at": "2026-04-01T10:00:00Z"
    },
    {
      "agent_id": "my_assistant",
      "agent_type": "react",
      "name": "我的助手",
      "created_at": "2026-04-02T15:30:00Z"
    }
  ]
}
```

### 创建智能体

```bash
curl -X POST http://localhost:6789/api/agents \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my_assistant",
    "agent_type": "react",
    "name": "我的助手",
    "system_prompt": "你是一个专业的助手"
  }'
```

### 获取智能体详情

```bash
curl http://localhost:6789/api/agents/default
```

### 删除智能体

```bash
curl -X DELETE http://localhost:6789/api/agents/my_assistant
```

---

## 技能管理 API

### 列出技能

```bash
curl http://localhost:6789/api/skills
```

**响应示例**：
```json
{
  "skills": [
    {
      "name": "weather",
      "description": "天气查询技能",
      "status": "active",
      "version": "1.0.0"
    },
    {
      "name": "file-manager",
      "description": "文件管理技能",
      "status": "active",
      "version": "1.0.0"
    }
  ]
}
```

### 获取技能详情

```bash
curl http://localhost:6789/api/skills/weather
```

### 安装技能

```bash
curl -X POST http://localhost:6789/api/skills/install \
  -H "Content-Type: application/json" \
  -d '{
    "skill_name": "weather"
  }'
```

### 卸载技能

```bash
curl -X POST http://localhost:6789/api/skills/uninstall \
  -H "Content-Type: application/json" \
  -d '{
    "skill_name": "weather"
  }'
```

---

## 记忆管理 API

### 查看记忆

```bash
curl http://localhost:6789/api/memory
```

**响应示例**：
```json
{
  "layers": {
    "enterprise": {
      "path": "~/.dfecrab/enterprise.md",
      "size_kb": 2.5,
      "loaded": true
    },
    "project": {
      "path": "./DFECRAB.md",
      "size_kb": 5.0,
      "loaded": true
    },
    "auto": {
      "path": ".dfecrab/memory/MEMORY.md",
      "size_kb": 10.0,
      "loaded": true
    },
    "user": {
      "path": "~/.dfecrab/user.md",
      "size_kb": 1.5,
      "loaded": true
    }
  }
}
```

### 更新记忆

```bash
curl -X POST http://localhost:6789/api/memory/update \
  -H "Content-Type: application/json" \
  -d '{
    "layer": "user",
    "content": "# 用户偏好\n\n## 编码风格\n- 使用类型注解"
  }'
```

### 压缩记忆

```bash
curl -X POST http://localhost:6789/api/memory/compact
```

### 清理记忆

```bash
curl -X POST http://localhost:6789/api/memory/cleanup
```

---

## 会话管理 API

### 列出会话

```bash
curl http://localhost:6789/api/sessions
```

**响应示例**：
```json
{
  "sessions": [
    {
      "session_id": "session_001",
      "agent_id": "default",
      "created_at": "2026-04-03T10:00:00Z",
      "message_count": 15,
      "tokens_used": 2500
    }
  ]
}
```

### 获取会话详情

```bash
curl http://localhost:6789/api/sessions/session_001
```

### 获取会话历史记录

```bash
curl http://localhost:6789/api/sessions/session_001/history
```

### 删除会话

```bash
curl -X DELETE http://localhost:6789/api/sessions/session_001
```

---

## 任务管理 API

### 查看任务统计

```bash
curl http://localhost:6789/api/tasks/stats
```

**响应示例**：
```json
{
  "total_tasks": 10,
  "pending": 3,
  "in_progress": 2,
  "completed": 5,
  "scheduled_tasks": 2,
  "heartbeat_tasks": 1
}
```

### 列出任务

```bash
curl http://localhost:6789/api/tasks
```

### 创建待办任务

```bash
curl -X POST http://localhost:6789/api/tasks/todos \
  -H "Content-Type: application/json" \
  -d '{
    "title": "学习机器学习",
    "description": "系统学习 ML 基础知识",
    "priority": 3
  }'
```

### 更新任务状态

```bash
curl -X PUT http://localhost:6789/api/tasks/todos/task_001 \
  -H "Content-Type: application/json" \
  -d '{
    "status": "completed"
  }'
```

### 删除任务

```bash
curl -X DELETE http://localhost:6789/api/tasks/todos/task_001
```

---

## 工具系统 API

### 列出工具

```bash
curl http://localhost:6789/api/tools
```

**响应示例**：
```json
{
  "tools": [
    {
      "name": "FileRead",
      "description": "读取文件内容",
      "permission_level": "Read-only",
      "parameters": {
        "file_path": "string (必需)",
        "offset": "number (可选)",
        "limit": "number (可选)"
      }
    },
    {
      "name": "FileEdit",
      "description": "编辑文件（diff 模式）",
      "permission_level": "Write",
      "parameters": {
        "file_path": "string (必需)",
        "old_string": "string (必需)",
        "new_string": "string (必需)",
        "replace_all": "boolean (可选)"
      }
    },
    {
      "name": "Bash",
      "description": "执行 shell 命令",
      "permission_level": "Shell",
      "parameters": {
        "command": "string (必需)",
        "timeout": "number (可选)",
        "cwd": "string (可选)"
      }
    }
  ]
}
```

### 获取工具 Schema

```bash
curl http://localhost:6789/api/tools/schemas
```

### 执行工具（高级）

```bash
curl -X POST http://localhost:6789/api/tools/execute \
  -H "Content-Type: application/json" \
  -d '{
    "tool_name": "FileRead",
    "params": {
      "file_path": "README.md"
    },
    "context": {
      "agent_id": "default",
      "session_id": "session_001"
    }
  }'
```

---

## 权限系统 API

### 查看权限模式

```bash
curl http://localhost:6789/api/permissions
```

**响应示例**：
```json
{
  "permission_mode": "default",
  "levels": {
    "Read-only": ["FileRead", "Glob", "Grep", "WebFetch", "WebSearch", "TaskList"],
    "Write": ["FileEdit", "FileWrite", "TaskCreate"],
    "Shell": ["Bash"],
    "Unsafe": []
  }
}
```

### 更新权限模式

```bash
curl -X PUT http://localhost:6789/api/permissions \
  -H "Content-Type: application/json" \
  -d '{
    "permission_mode": "strict"
  }'
```

---

## 健康检查与统计

### 健康检查

```bash
curl http://localhost:6789/health
```

### 系统统计

```bash
curl http://localhost:6789/api/stats
```

### 版本信息

```bash
curl http://localhost:6789/api/version
```

**响应示例**：
```json
{
  "version": "4.0.0",
  "build_date": "2026-04-03",
  "python_version": "3.10.12"
}
```

---

## 错误处理

### 错误响应格式

```json
{
  "success": false,
  "error": {
    "code": "AGENT_NOT_FOUND",
    "message": "智能体 'unknown' 不存在",
    "details": {}
  }
}
```

### 常见错误码

| 错误码 | 说明 | 解决方法 |
|--------|------|---------|
| `AGENT_NOT_FOUND` | 智能体不存在 | 检查 agent_id 是否正确 |
| `SESSION_NOT_FOUND` | 会话不存在 | 检查 session_id 是否正确 |
| `SKILL_NOT_FOUND` | 技能不存在 | 检查技能名称是否正确 |
| `PERMISSION_DENIED` | 权限不足 | 检查权限配置 |
| `INVALID_REQUEST` | 请求格式错误 | 检查请求参数 |
| `INTERNAL_ERROR` | 服务器内部错误 | 查看日志文件 |

### 查看日志

```bash
# 查看 Gateway 日志
tail -f logs/gateway.log

# 查看错误日志
grep ERROR logs/gateway.log
```

---

## API 使用示例

### 完整对话流程

```bash
# 1. 检查服务状态
curl http://localhost:6789/health

# 2. 查看可用智能体
curl http://localhost:6789/api/agents

# 3. 发送对话消息
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "default",
    "message": "你好"
  }'

# 4. 查看会话历史
curl http://localhost:6789/api/sessions/session_001/history

# 5. 查看系统统计
curl http://localhost:6789/api/stats
```

### 使用 Python 调用

```python
import requests

BASE_URL = "http://localhost:6789"

# 健康检查
response = requests.get(f"{BASE_URL}/health")
print(response.json())

# 发送对话消息
response = requests.post(
    f"{BASE_URL}/api/chat",
    json={
        "agent_id": "default",
        "message": "你好"
    }
)
print(response.json())

# 查看智能体列表
response = requests.get(f"{BASE_URL}/api/agents")
print(response.json())
```

### 使用 curl 的便捷方式

```bash
# 定义别名
alias dfecrab-api="curl -s http://localhost:6789"

# 使用
dfecrab-api/health
dfecrab-api/api/agents
dfecrab-api/api/stats
```

---

## 高级用法

### 批量操作

```bash
# 批量创建智能体
for name in assistant1 assistant2 assistant3; do
  curl -X POST http://localhost:6789/api/agents \
    -H "Content-Type: application/json" \
    -d "{
      \"agent_id\": \"$name\",
      \"agent_type\": \"react\"
    }"
done
```

### 监控脚本

```bash
#!/bin/bash
# 监控 DFEcrab 服务状态

while true; do
  status=$(curl -s http://localhost:6789/health | jq -r '.status')
  if [ "$status" != "healthy" ]; then
    echo "[$(date)] DFEcrab 服务异常: $status"
    # 可以添加告警逻辑
  fi
  sleep 60
done
```

---

## 相关文档

- [API 参考 V4](../API_REFERENCE_V4.md) - 详细 API 接口说明
- [V4 升级指南](../V4_UPGRADE_GUIDE.md) - 从旧版本升级
- [命令参考](../04-参考篇/COMMAND_REFERENCE.md) - 命令行工具说明
- [权限配置](../01-基础篇/PERMISSION_SETUP.md) - 权限系统配置

---

**版本**: 4.0.0  
**更新日期**: 2026-04-03  
**维护者**: DFEcrab Team
