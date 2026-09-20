# DFEcrab 任务管理 V2 使用指南

> 版本：v2.0  
> 日期：2026-04-04  
> 状态：✅ 完成

---

## 📋 概述

DFEcrab 任务管理 V2 系统提供完整的任务管理能力，支持：

- **临时任务**：指令性、多次交互、可放弃/转化
- **周期任务**：自动执行、定期运行、持续积累
- **AgentGroup 编组**：Session 团队模式 + 专用 Agent 模式
- **实时进度追踪**：WebSocket 推送
- **完整审计日志**：所有操作可追溯
- **TUI 任务看板**：终端界面展示

---

## 🚀 快速开始

### 1. 创建任务

```bash
# 创建临时任务
curl -X POST http://localhost:6789/api/v2/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "分析电网故障",
    "task_type": "temporary",
    "description": "分析最近的电网故障原因",
    "agent_group_config": {
      "members": [
        {"agent_id": "qwencode", "role": "designer"},
        {"agent_id": "codebuddy", "role": "developer"}
      ]
    }
  }'
```

### 2. 查询任务进度

```bash
curl http://localhost:6789/api/v2/tasks/{task_id}/progress
```

### 3. 获取审计日志

```bash
curl http://localhost:6789/api/v2/tasks/{task_id}/audit
```

### 4. 运行任务看板

```bash
cd /Users/zhanghanzhi/DFEcrab--
python3 -m src.core.task.task_dashboard
```

---

## 📖 详细使用

### 任务类型

| 类型 | 说明 | 适用场景 |
|------|------|---------|
| `temporary` | 临时任务（Session 团队模式） | 一次性任务、临时分析 |
| `periodic` | 周期任务（专用 Agent 模式） | 定期报告、持续监控 |

### AgentGroup 模式

| 模式 | 说明 | 特点 |
|------|------|------|
| `session_team` | Session 团队 | 轻量、快速、知识共享 |
| `dedicated_agent` | 专用 Agent | 独立状态、可积累经验 |

### WebSocket 订阅

```javascript
const ws = new WebSocket('ws://localhost:6790/ws');

ws.onopen = () => {
  // 认证
  ws.send(JSON.stringify({
    type: 'auth_request',
    data: { method: 'token', token: 'your_token' }
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  if (msg.type === 'auth_response' && msg.data.success) {
    // 订阅所有任务
    ws.send(JSON.stringify({
      type: 'subscribe',
      data: { event_type: 'task:*' }
    }));
  }
  
  if (msg.type === 'task_progress') {
    console.log(`任务进度：${msg.data.progress.overall_progress}%`);
  }
};
```

---

## 📊 API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v2/tasks` | POST | 创建任务 |
| `/api/v2/tasks` | GET | 列出任务 |
| `/api/v2/tasks/{task_id}` | GET | 任务详情 |
| `/api/v2/tasks/{task_id}/convert` | POST | 转化任务类型 |
| `/api/v2/tasks/{task_id}` | DELETE | 删除任务 |
| `/api/v2/tasks/{task_id}/progress` | GET | 获取进度 |
| `/api/v2/tasks/{task_id}/audit` | GET | 获取审计日志 |
| `/api/v2/tasks/{task_id}/dashboard` | GET | 获取看板数据 |
| `/api/v2/tasks/{task_id}/execute` | POST | 执行任务 |

---

## 🎯 最佳实践

### 1. 任务主题

为每个任务设置明确的主题：

```json
{
  "topic": "2026-Q2 电网故障分析",
  "description": "分析 2026 年第二季度电网故障原因，提出改进建议"
}
```

### 2. Agent 角色分配

根据任务需求分配合适的 Agent 角色：

```json
{
  "agent_group_config": {
    "members": [
      {"agent_id": "qwencode", "role": "designer"},
      {"agent_id": "codebuddy", "role": "developer"},
      {"agent_id": "dfecrab", "role": "reviewer"}
    ]
  }
}
```

### 3. 周期任务调度

使用 cron 表达式设置周期任务：

```json
{
  "task_type": "periodic",
  "schedule": {
    "cron": "0 9 * * 1"  // 每周一上午 9 点
  }
}
```

### 4. 任务转化

临时任务可转化为周期任务：

```bash
curl -X POST http://localhost:6789/api/v2/tasks/{task_id}/convert \
  -H "Content-Type: application/json" \
  -d '{"target_type": "periodic"}'
```

---

## 🔧 配置

### 存储目录

任务数据默认存储在 `data/tasks/`：

```
data/tasks/
├── {task_id}.json          # 任务数据
└── audit/
    └── {task_id}.json      # 审计日志
```

### WebSocket 配置

WebSocket 端口：`6790`（HTTP 端口 + 1）

---

## 📝 示例

### Python 示例

```python
from src.core.task import TaskManager, TaskType

# 创建任务管理器
tm = TaskManager(storage_dir="data/tasks")

# 创建临时任务
task = tm.create_task(
    topic="分析电网故障",
    task_type=TaskType.TEMPORARY,
    description="分析最近的电网故障原因",
    supervisor_agent_id="supervisor_01",
    agent_group_config={
        "members": [
            {"agent_id": "qwencode", "role": "designer"},
            {"agent_id": "codebuddy", "role": "developer"},
        ]
    },
)

print(f"任务创建成功：{task.task_id}")

# 查询进度
progress = tm.get_task_progress(task.task_id)
print(f"进度：{progress['progress']}%")
```

### 周期任务示例

```python
# 创建周期任务
periodic_task = tm.create_task(
    topic="每周运维报告",
    task_type=TaskType.PERIODIC,
    description="生成每周运维报告",
    supervisor_agent_id="supervisor_01",
    agent_group_config={
        "members": [
            {"agent_id": "dfecrab", "role": "analyst"},
        ]
    },
    schedule={"cron": "0 9 * * 1"},  # 每周一 9:00
)
```

---

## ❓ 常见问题

### Q: 如何查看任务进度？

A: 使用 `/api/v2/tasks/{task_id}/progress` 端点，或通过 WebSocket 订阅实时推送。

### Q: 任务转化后原任务会怎样？

A: 原任务状态标记为 `converted`，新任务继承原任务的配置和主题。

### Q: 如何清理已完成的任务？

A: 使用 `DELETE /api/v2/tasks/{task_id}` 删除任务，或定期清理 `data/tasks/` 目录。

### Q: WebSocket 推送不工作？

A: 确保：
1. WebSocket 服务已启动（端口 6790）
2. 客户端已认证
3. 已订阅任务事件（`task:*` 或 `task:{task_id}`）

---

## 📚 相关文档

- [API 文档](./TASK_API_V2.md)
- [WebSocket 推送文档](./WEBSOCKET_PUSH.md)
- [系统设计文档](../../设计说明书/02-核心模块设计/TASK_MANAGEMENT_SYSTEM.md)
- [实现总结](../../集成分析/TASK_V2_IMPLEMENTATION_SUMMARY.md)

---

*文档版本: 1.0*  
*最后更新: 2026-04-04*
