# 任务执行管理系统使用指南

## 📋 概述

任务执行管理系统提供**心跳**、**定时**、**待办**三种模式的任务调度能力，让智能体系统能够：

- ✅ 健康检查和监控
- ✅ 定期执行任务
- ✅ 待办事项管理
- ✅ 任务优先级调度
- ✅ 任务依赖管理
- ✅ 自动重试和失败处理

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────┐
│         TaskScheduler（任务调度器）              │
├─────────────────────────────────────────────────┤
│ 1. HeartbeatManager（心跳管理器）               │
│    - 周期性执行（每秒、每分钟）                 │
│    - 健康检查和状态同步                         │
│    - 失败检测和告警                             │
│                                                 │
│ 2. ScheduledTaskManager（定时任务管理器）       │
│    - Cron 表达式调度                             │
│    - 固定间隔调度                               │
│    - 任务队列管理                               │
│                                                 │
│ 3. TodoManager（待办管理器）                    │
│    - 待办事项 CRUD                              │
│    - 优先级队列（低/普通/高/紧急）              │
│    - 依赖管理                                   │
│    - 条件触发                                   │
└─────────────────────────────────────────────────┘
```

## 🚀 三种任务模式

### 1. 心跳任务（Heartbeat）

**特点：**
- 周期性执行（如每 30 秒）
- 用于健康检查、状态同步
- 可配置重试机制
- 失败自动告警

**示例：**
```python
from src.core.task_scheduler import HeartbeatTask

# Gateway 心跳检查
async def gateway_heartbeat():
    return gateway_is_running

heartbeat_task = HeartbeatTask(
    task_id="gateway_heartbeat",
    name="Gateway 心跳检查",
    interval_seconds=30,  # 每 30 秒
    handler=gateway_heartbeat,
    timeout_seconds=5,
    max_retries=3,
    on_failure=lambda: logger.error("⚠️ Gateway 心跳失败！")
)

scheduler.register_heartbeat(heartbeat_task)
```

**输出：**
```json
{
  "task_id": "gateway_heartbeat",
  "name": "Gateway 心跳检查",
  "interval_seconds": 30,
  "last_beat": "2026-03-29T01:50:21",
  "last_status": true,
  "consecutive_failures": 0,
  "is_running": false,
  "health": "healthy"
}
```

### 2. 定时任务（Scheduled）

**特点：**
- 按 Cron 表达式或固定间隔执行
- 用于定期反思、数据清理
- 支持时区
- 支持并发控制

**示例 1：固定间隔**
```python
from src.core.task_scheduler import ScheduledTask

# 每 5 分钟清理过期会话
async def cleanup_expired_sessions():
    count = await session_manager.cleanup_expired_sessions()
    logger.info(f"清理了 {count} 个过期会话")

cleanup_task = ScheduledTask(
    task_id="cleanup_sessions",
    name="清理过期会话",
    interval_seconds=300,  # 5 分钟
    handler=cleanup_expired_sessions
)

scheduler.register_scheduled_task(cleanup_task)
```

**示例 2：Cron 表达式**
```python
# 每天凌晨 2 点备份数据
async def backup_data():
    logger.info("开始每日数据备份...")
    # 实现备份逻辑

backup_task = ScheduledTask(
    task_id="daily_backup",
    name="每日数据备份",
    cron_expression="0 2 * * *",  # 每天凌晨 2 点
    handler=backup_data
)

scheduler.register_scheduled_task(backup_task)
```

**支持的 Cron 格式：**
```
分 时 日 月 星期

*/5 * * * *    # 每 5 分钟
0 */2 * * *    # 每 2 小时
0 0 * * 0      # 每周日午夜
0 0 1 * *      # 每月 1 号午夜
```

### 3. 待办任务（Todo）

**特点：**
- 一次性或条件触发
- 用于改进计划、用户待办
- 支持 4 个优先级（低/普通/高/紧急）
- 支持依赖关系
- 支持条件触发

**示例 1：基本待办**
```python
from src.core.task_scheduler import TodoTask, TaskPriority

todo = TodoTask(
    task_id="learn_ml",
    title="学习机器学习",
    description="完成吴恩达机器学习课程",
    priority=TaskPriority.HIGH,  # 高优先级
    due_date=datetime(2026, 4, 30)
)

scheduler.add_todo(todo)
```

**示例 2：带依赖的待办**
```python
# 任务 1：学习 Python 基础
todo1 = TodoTask(
    task_id="learn_python",
    title="学习 Python 基础",
    priority=TaskPriority.HIGH
)

# 任务 2：学习机器学习（依赖任务 1）
todo2 = TodoTask(
    task_id="learn_ml",
    title="学习机器学习",
    dependencies=["learn_python"],  # 依赖
    priority=TaskPriority.NORMAL
)

scheduler.add_todo(todo1)
scheduler.add_todo(todo2)
# todo2 会在 todo1 完成后自动执行
```

**示例 3：带条件的待办**
```python
todo = TodoTask(
    task_id="send_report",
    title="发送日报",
    condition="datetime.now().hour >= 18",  # 18 点后执行
    handler=send_daily_report
)

scheduler.add_todo(todo)
```

## 📡 API 接口

### 1. 获取任务统计

```bash
GET /api/tasks/stats
```

**返回：**
```json
{
  "success": true,
  "stats": {
    "heartbeat_tasks": 1,
    "scheduled_tasks": 2,
    "todo_tasks": 5,
    "pending_todos": 3,
    "total_executions": 150,
    "total_failures": 2,
    "success_rate": 0.987
  }
}
```

### 2. 查看心跳任务

```bash
GET /api/tasks/heartbeats
```

**返回：**
```json
{
  "success": true,
  "count": 1,
  "heartbeats": [
    {
      "task_id": "gateway_heartbeat",
      "name": "Gateway 心跳检查",
      "interval_seconds": 30,
      "last_beat": "2026-03-29T01:50:21",
      "last_status": true,
      "consecutive_failures": 0,
      "is_running": false,
      "health": "healthy"
    }
  ]
}
```

### 3. 查看定时任务

```bash
GET /api/tasks/scheduled
```

**返回：**
```json
{
  "success": true,
  "count": 2,
  "tasks": [
    {
      "task_id": "cleanup_sessions",
      "name": "清理过期会话",
      "cron_expression": null,
      "interval_seconds": 300,
      "last_run": "2026-03-29T01:50:21",
      "next_run": "2026-03-29T01:55:21",
      "run_count": 1,
      "is_enabled": true
    },
    {
      "task_id": "daily_backup",
      "name": "每日数据备份",
      "cron_expression": "0 2 * * *",
      "interval_seconds": null,
      "last_run": null,
      "next_run": null,
      "run_count": 0,
      "is_enabled": true
    }
  ]
}
```

### 4. 查看待办任务

```bash
# 查看所有待办
GET /api/tasks/todos

# 按状态筛选
GET /api/tasks/todos?status=pending

# 按优先级筛选
GET /api/tasks/todos?priority=3
```

**返回：**
```json
{
  "success": true,
  "count": 2,
  "todos": [
    {
      "task_id": "todo_20260329015028",
      "title": "学习机器学习",
      "description": "完成吴恩达机器学习课程",
      "priority": "HIGH",
      "status": "pending",
      "due_date": "2026-04-30T23:59:59",
      "dependencies": [],
      "created_at": "2026-03-29T01:50:28",
      "completed_at": null
    }
  ]
}
```

### 5. 添加待办任务

```bash
POST /api/tasks/todos
Content-Type: application/json

{
  "title": "实现向量搜索",
  "description": "为记忆系统添加向量搜索功能",
  "priority": 4,  // 1=低，2=普通，3=高，4=紧急
  "due_date": "2026-04-15T23:59:59",
  "dependencies": ["learn_vector_db"],
  "condition": "datetime.now().hour >= 9"
}
```

**返回：**
```json
{
  "success": true,
  "message": "已添加待办任务：实现向量搜索",
  "task_id": "todo_20260329015030"
}
```

### 6. 完成待办任务

```bash
POST /api/tasks/todos/{task_id}/complete
Content-Type: application/json

{
  "result": "已完成"
}
```

**返回：**
```json
{
  "success": true,
  "message": "待办任务已完成：todo_20260329015028"
}
```

## 🔧 使用场景

### 场景 1：系统健康监控

```python
# 注册系统心跳
async def check_gateway_health():
    return gateway_running and database_connected

heartbeat = HeartbeatTask(
    task_id="system_health",
    name="系统健康检查",
    interval_seconds=60,  # 每分钟
    handler=check_gateway_health,
    on_failure=send_alert_email
)

scheduler.register_heartbeat(heartbeat)
```

### 场景 2：定期数据清理

```python
# 每小时清理过期会话
cleanup_task = ScheduledTask(
    task_id="hourly_cleanup",
    name="每小时清理",
    interval_seconds=3600,
    handler=cleanup_expired_data
)

scheduler.register_scheduled_task(cleanup_task)
```

### 场景 3：改进计划管理

```python
# 从自我反思系统生成的改进计划
improvement_todo = TodoTask(
    task_id="improve_response_diversity",
    title="提高回答多样性",
    description="避免重复回答相似问题",
    priority=TaskPriority.HIGH,
    dependencies=["analyze_repetition_patterns"],
    handler=implement_diversity_improvement
)

scheduler.add_todo(improvement_todo)
```

### 场景 4：定时备份

```python
# 每天凌晨 2 点备份
backup_task = ScheduledTask(
    task_id="daily_backup",
    name="每日备份",
    cron_expression="0 2 * * *",
    handler=backup_all_data
)

scheduler.register_scheduled_task(backup_task)
```

## 📊 任务优先级

| 优先级 | 值 | 说明 | 使用场景 |
|--------|----|------|----------|
| LOW | 1 | 低优先级 | 可延后的任务 |
| NORMAL | 2 | 普通优先级 | 日常任务 |
| HIGH | 3 | 高优先级 | 重要任务 |
| CRITICAL | 4 | 紧急优先级 | 需要立即处理的任务 |

## 📈 任务状态

| 状态 | 说明 |
|------|------|
| pending | 待执行 |
| running | 执行中 |
| completed | 已完成 |
| failed | 失败 |
| cancelled | 已取消 |
| retrying | 重试中 |

## 🔍 监控和调试

### 查看任务日志

```bash
# 查看任务调度日志
grep "task_scheduler" /tmp/gateway.log

# 查看心跳日志
grep "心跳" /tmp/gateway.log

# 查看定时任务执行日志
grep "定时任务" /tmp/gateway.log
```

### 查看持久化的待办

```bash
# 待办任务保存在
cat tasks/todos.json
```

## 💡 最佳实践

### 1. 合理设置心跳间隔

```python
# 关键系统：10-30 秒
critical_heartbeat = HeartbeatTask(
    interval_seconds=15,
    ...
)

# 非关键系统：1-5 分钟
normal_heartbeat = HeartbeatTask(
    interval_seconds=300,
    ...
)
```

### 2. 使用 Cron 表达式处理复杂调度

```python
# 工作日早上 9 点
"0 9 * * 1-5"

# 每周一和周五
"0 9 * * 1,5"

# 每月 1 号和 15 号
"0 9 1,15 * *"
```

### 3. 为待办设置合理的截止时间

```python
# 紧急任务：今天
urgent = TodoTask(
    due_date=datetime.now().replace(hour=23, minute=59),
    priority=TaskPriority.CRITICAL
)

# 长期任务：下个月
long_term = TodoTask(
    due_date=datetime.now() + timedelta(days=30),
    priority=TaskPriority.LOW
)
```

### 4. 使用依赖管理任务顺序

```python
# 任务执行顺序：A → B → C
task_a = TodoTask(task_id="step_a", ...)
task_b = TodoTask(task_id="step_b", dependencies=["step_a"], ...)
task_c = TodoTask(task_id="step_c", dependencies=["step_b"], ...)
```

### 5. 定期检查任务统计

```bash
# 每天检查任务执行情况
curl http://localhost:6789/api/tasks/stats

# 关注成功率
if success_rate < 0.95:
    # 调查失败原因
```

## 🎯 与自我反思系统集成

任务调度系统与自我反思系统无缝集成：

```python
# 自我反思生成的改进计划自动转为待办任务
async def create_improvement_todo(reflection_report):
    for improvement in reflection_report.improvement_plan:
        todo = TodoTask(
            task_id=f"improve_{improvement.action_type}",
            title=improvement.description,
            priority=TaskPriority(improvement.priority),
            handler=implement_improvement
        )
        scheduler.add_todo(todo)
```

## 📝 配置文件

任务调度器会自动保存和加载：

```
tasks/
└── todos.json  # 待办任务持久化
```

系统重启后会自动加载未完成的待办任务。

---

**文档版本**：1.0
**创建时间**：2026-03-29
**状态**：已实现并测试通过

## 🎓 完整示例

### 示例：创建智能助手任务管理系统

```python
import asyncio
from src.core.task_scheduler import (
    get_task_scheduler,
    HeartbeatTask, ScheduledTask, TodoTask,
    TaskPriority
)
from datetime import datetime, timedelta

async def setup_assistant_tasks():
    scheduler = get_task_scheduler()
    
    # 1. 系统心跳
    async def check_system_health():
        return True  # 检查数据库、API 等
    
    health_task = HeartbeatTask(
        task_id="system_health",
        name="系统健康检查",
        interval_seconds=60,
        handler=check_system_health
    )
    scheduler.register_heartbeat(health_task)
    
    # 2. 定时清理
    async def cleanup_old_messages():
        # 清理 7 天前的消息
        pass
    
    cleanup_task = ScheduledTask(
        task_id="cleanup_messages",
        name="清理旧消息",
        interval_seconds=3600,  # 每小时
        handler=cleanup_old_messages
    )
    scheduler.register_scheduled_task(cleanup_task)
    
    # 3. 用户待办
    user_todo = TodoTask(
        task_id="user_task_1",
        title="学习 Python",
        description="完成第 5 章练习",
        priority=TaskPriority.HIGH,
        due_date=datetime.now() + timedelta(days=7)
    )
    scheduler.add_todo(user_todo)
    
    print("✅ 任务管理系统已配置")

# 启动
asyncio.run(setup_assistant_tasks())
```

这个示例展示了如何为智能助手配置完整的任务管理系统！
