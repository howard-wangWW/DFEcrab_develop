# DFEcrab API 文档

## 概述

DFEcrab Gateway 提供 REST API 接口，默认地址：`http://localhost:6789`

## 健康检查

### GET /health

检查 Gateway 运行状态。

**响应示例：**
```json
{
  "status": "healthy",
  "gateway": "running",
  "version": "2.0.0"
}
```

---

## 模型管理

### GET /api/models

获取所有模型列表。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "current_provider": "deepseek",
    "fallback_chain": ["deepseek", "zhipu"],
    "providers": [
      {"config_name": "ollama_qwen", "model_name": "deepseek-v3.1:671b-cloud"},
      {"config_name": "zhipu_glm4_flash", "model_name": "glm-4-flash"}
    ]
  }
}
```

### GET /api/models/current

获取当前使用的模型。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "current_provider": "deepseek",
    "config": {
      "model_name": "deepseek-v3.1:671b-cloud",
      "config_name": "ollama_qwen"
    }
  }
}
```

### POST /api/models/switch

切换模型供应商。

**请求体：**
```json
{
  "provider": "zhipu"
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "已切换到供应商: zhipu",
  "data": {
    "current_provider": "zhipu",
    "config": {
      "model_name": "glm-4-flash",
      "config_name": "zhipu_glm4_flash"
    }
  }
}
```

---

## 记忆系统

### GET /api/memory/stats

获取记忆系统统计信息。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "learnings": {
      "sessions": 0,
      "errors": 0,
      "recoveries": 0,
      "performance": 0
    },
    "memory": {
      "daily_count": 1,
      "weekly_count": 1,
      "monthly_count": 0,
      "has_long_term": false
    }
  }
}
```

### GET /api/memory/learnings

获取学习记录。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "learnings": [
      {
        "title": "用户名称: 张三",
        "category": "user_info",
        "date": "2026-03-29T17:10:33",
        "content": {...}
      }
    ]
  }
}
```

### GET /api/memory/recent

获取最近记忆内容。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "current_model": "deepseek: deepseek-v3.1:671b-cloud",
    "recent_memory": "## 2026-03-29\n\n..."
  }
}
```

### GET /api/memory/search

语义搜索记忆。

**参数：**
- `q`: 搜索查询（必填）
- `limit`: 返回数量，默认 5

**响应示例：**
```json
{
  "success": true,
  "data": {
    "query": "Python项目",
    "results": [
      {
        "id": "doc_0_20260329171033",
        "content": "使用 Python 开发 Web 应用",
        "score": 0.95,
        "timestamp": "2026-03-29T17:10:33"
      }
    ]
  }
}
```

---

## 事件索引

### GET /api/events/stats

获取事件统计。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "total": 6,
    "categories": {
      "user_info": 4,
      "decision": 1,
      "test": 1
    },
    "importances": {
      "high": 6
    },
    "last_updated": "2026-03-29T17:10:33"
  }
}
```

### GET /api/events/recent

获取最近事件。

**参数：**
- `limit`: 返回数量，默认 20

### GET /api/events/search

搜索事件。

**参数：**
- `q`: 搜索查询
- `limit`: 返回数量，默认 10

### POST /api/events/add

添加新事件。

**请求体：**
```json
{
  "title": "重要决策",
  "category": "decision",
  "content": "决定使用 FastAPI 框架",
  "importance": "high",
  "tags": ["技术选型", "后端"]
}
```

---

## 容错机制

### GET /api/fallback/status

获取容错状态。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "fallback": {
      "default": {
        "current_model": "deepseek",
        "state": "normal",
        "failure_count": 0,
        "config": {
          "primary": "deepseek",
          "fallbacks": ["zhipu"]
        }
      }
    },
    "circuit_breakers": {
      "agent_chat": {
        "state": "closed",
        "failure_count": 0
      }
    }
  }
}
```

---

## 规划系统

### GET /api/plan/current

获取当前执行计划。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "has_plan": true,
    "progress": {
      "plan_id": "plan_20260329120000",
      "task": "开发一个 Web 项目",
      "status": "in_progress",
      "total_steps": 4,
      "completed_steps": 1,
      "current_step": 2,
      "progress_percent": 25
    },
    "summary": "## 当前执行计划\n\n**任务**: 开发一个 Web 项目\n..."
  }
}
```

### GET /api/plan/list

获取计划列表。

**响应示例：**
```json
{
  "success": true,
  "data": {
    "plans": [
      {
        "id": "plan_20260329120000",
        "task": "开发一个 Web 项目",
        "status": "in_progress",
        "complexity": "medium",
        "created_at": "2026-03-29",
        "steps_count": 4
      }
    ]
  }
}
```

### POST /api/plan/next

完成当前步骤，进入下一步。

**请求体：**
```json
{
  "result": "已完成环境检查"
}
```

### POST /api/plan/skip

跳过当前步骤。

### POST /api/plan/cancel

取消当前计划。

---

## 对话

### POST /api/chat

发送对话请求。

**请求体：**
```json
{
  "message": "你好",
  "agent_id": "default",
  "client_id": "test_client"
}
```

**响应示例：**
```json
{
  "success": true,
  "data": {
    "response": "你好！有什么可以帮助你的吗？",
    "session_id": "abc123",
    "model_info": "deepseek: deepseek-v3.1:671b-cloud"
  }
}
```

---

## TUI 命令

在 TUI 中可使用以下命令：

| 命令 | 说明 |
|------|------|
| `/models` | 显示所有模型供应商 |
| `/models list` | 同上 |
| `/models switch <name>` | 切换供应商 |
| `/models current` | 显示当前模型 |
| `/memory` | 显示记忆统计 |
| `/memory stats` | 同上 |
| `/memory learnings` | 显示学习记录 |
| `/memory recent` | 显示最近记忆 |
| `/memory search <词>` | 语义搜索记忆 |
| `/help` | 显示帮助 |
| `/clear` | 清屏 |
| `/status` | 系统状态 |
