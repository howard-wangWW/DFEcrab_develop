# DFEcrab 任务管理 V2 API 文档

> 版本：v2.0  
> 日期：2026-04-04  
> 基础 URL：`http://localhost:6789`

---

## 概述

任务管理 V2 API 提供统一的任务管理能力，支持：
- 临时任务（Session 团队模式）
- 周期任务（专用 Agent 模式）
- 任务进度追踪
- 审计日志查询
- 任务类型转化

---

## API 端点

### 1. 创建任务

**POST** `/api/v2/tasks`

**请求体**：
```json
{
  "topic": "任务主题",
  "task_type": "temporary|periodic",
  "description": "任务描述",
  "supervisor_agent_id": "监管 Agent ID",
  "agent_group_config": {
    "members": [
      {"agent_id": "qwencode", "role": "designer"},
      {"agent_id": "codebuddy", "role": "developer"}
    ]
  },
  "schedule": {"cron": "0 9 * * 1"}  // 仅周期任务需要
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "abc123",
    "topic": "任务主题",
    "task_type": "temporary",
    "status": "pending",
    "supervisor_session_id": "sess_xyz",
    "agent_group": {
      "task_id": "abc123",
      "task_type": "temporary",
      "mode": "session_team",
      "members": [...],
      "overall_progress": 0.0,
      "is_complete": false
    }
  }
}
```

---

### 2. 列出任务

**GET** `/api/v2/tasks?task_type=temporary&status=pending&limit=100`

**查询参数**：
- `task_type`: 过滤任务类型（temporary/periodic）
- `status`: 过滤状态（pending/running/completed/failed/cancelled/converted）
- `limit`: 返回数量限制（默认 100）

**响应**：
```json
{
  "success": true,
  "data": {
    "tasks": [
      {
        "task_id": "abc123",
        "topic": "任务主题",
        "task_type": "temporary",
        "status": "pending",
        "created_at": "2026-04-04T10:00:00"
      }
    ],
    "count": 1
  }
}
```

---

### 3. 获取任务详情

**GET** `/api/v2/tasks/{task_id}`

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "abc123",
    "topic": "任务主题",
    "task_type": "temporary",
    "status": "running",
    "description": "任务描述",
    "supervisor_session_id": "sess_xyz",
    "supervisor_agent_id": "supervisor_01",
    "agent_group_config": {...},
    "progress": {
      "task_id": "abc123",
      "total_steps": 5,
      "completed_steps": 2,
      "current_step": 2,
      "overall_progress": 40.0,
      "is_complete": false,
      "member_progress": {...},
      "started_at": "2026-04-04T10:00:00",
      "completed_at": null
    },
    "created_at": "2026-04-04T10:00:00",
    "started_at": "2026-04-04T10:00:00",
    "completed_at": null,
    "schedule": null,
    "last_run": null,
    "next_run": null,
    "run_count": 0
  }
}
```

---

### 4. 转化任务类型

**POST** `/api/v2/tasks/{task_id}/convert`

**请求体**：
```json
{
  "target_type": "periodic"
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "original_task_id": "abc123",
    "new_task_id": "def456",
    "new_task_type": "periodic"
  }
}
```

---

### 5. 删除任务

**DELETE** `/api/v2/tasks/{task_id}`

**响应**：
```json
{
  "success": true,
  "message": "Task deleted"
}
```

---

### 6. 获取任务进度

**GET** `/api/v2/tasks/{task_id}/progress`

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "abc123",
    "status": "running",
    "progress": 40.0,
    "is_complete": false,
    "total_steps": 5,
    "completed_steps": 2,
    "member_progress": {
      "sess_a1": 100.0,
      "sess_b2": 50.0
    }
  }
}
```

---

### 7. 获取审计日志

**GET** `/api/v2/tasks/{task_id}/audit?agent=qwencode&action=assign_step&limit=100`

**查询参数**：
- `agent`: 过滤 Agent
- `action`: 过滤操作类型
- `limit`: 返回数量限制（默认 100）

**响应**：
```json
{
  "success": true,
  "data": {
    "logs": [
      {
        "task_id": "abc123",
        "action": "assign_step",
        "agent": "qwencode",
        "details": {"step": 1},
        "timestamp": "2026-04-04T10:00:00"
      }
    ],
    "count": 1
  }
}
```

---

### 8. 获取看板数据

**GET** `/api/v2/tasks/{task_id}/dashboard`

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "abc123",
    "topic": "任务主题",
    "status": "running",
    "progress": 40.0,
    "is_complete": false,
    "members": [
      {
        "agent": "qwencode",
        "role": "designer",
        "status": "completed",
        "progress": 100.0
      },
      {
        "agent": "codebuddy",
        "role": "developer",
        "status": "running",
        "progress": 50.0
      }
    ],
    "workflow": {
      "total_steps": 5,
      "current_step": 2,
      "steps": [...]
    },
    "audit_summary": {
      "total_actions": 10,
      "by_agent": {"qwencode": 5, "codebuddy": 5},
      "by_action": {"assign_step": 5, "step_completed": 5},
      "last_action": {...}
    }
  }
}
```

---

### 9. 执行任务

**POST** `/api/v2/tasks/{task_id}/execute`

**请求体**：
```json
{
  "user_input": "请帮我分析这个 bug"
}
```

**响应**：
```json
{
  "success": true,
  "data": {
    "task_id": "abc123",
    "status": "completed",
    "progress": 100.0
  }
}
```

---

## 错误响应

所有 API 在失败时返回统一格式：

```json
{
  "success": false,
  "error": "错误描述信息"
}
```

---

## 使用示例

### curl 示例

**创建临时任务**：
```bash
curl -X POST http://localhost:6789/api/v2/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "分析电网故障",
    "task_type": "temporary",
    "description": "分析最近的电网故障原因",
    "supervisor_agent_id": "supervisor_01",
    "agent_group_config": {
      "members": [
        {"agent_id": "qwencode", "role": "designer"},
        {"agent_id": "codebuddy", "role": "developer"}
      ]
    }
  }'
```

**查询任务进度**：
```bash
curl http://localhost:6789/api/v2/tasks/abc123/progress
```

**获取审计日志**：
```bash
curl "http://localhost:6789/api/v2/tasks/abc123/audit?limit=50"
```

---

## 数据模型

### TaskType
- `temporary`: 临时任务（Session 团队模式）
- `periodic`: 周期任务（专用 Agent 模式）

### TaskStatus
- `pending`: 待执行
- `running`: 执行中
- `completed`: 已完成
- `failed`: 失败
- `cancelled`: 已取消
- `converted`: 已转化

### MemberMode
- `session_team`: Session 团队（轻量）
- `dedicated_agent`: 专用 Agent（独立）

---

*文档版本: 1.0*  
*最后更新: 2026-04-04*
