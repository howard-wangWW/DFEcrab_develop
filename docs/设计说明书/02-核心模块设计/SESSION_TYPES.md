# Session 类型扩展设计

## 一、Session 类型

```
┌─────────────────────────────────────────────────────────────────┐
│                     Session 类型                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 常驻Session (resident)                                      │
│     ┌─────────────────┐                                        │
│     │  CLI进程持续运行  │  ← 一直在线，处理实时请求              │
│     │  用户交互、实时   │                                        │
│     └─────────────────┘                                        │
│                                                                 │
│  2. 定时任务Session (scheduled)                                  │
│     ┌─────────────────┐                                        │
│     │  按计划启动/停止  │  ← cron调度，周期性任务                │
│     │  扫描、备份、清理  │                                        │
│     └─────────────────┘                                        │
│                                                                 │
│  3. 事件触发Session (triggered)                                  │
│     ┌─────────────────┐                                        │
│     │  事件发生时启动   │  ← 按需启动，处理完退出                │
│     │  告警处理、应急   │                                        │
│     └─────────────────┘                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 二、典型场景

### 场景1：运维监控组

```
Group: 运维监控组
├── user-interaction (Agent)
│   ├── session_user_primary    [常驻]  ← 处理用户实时请求
│   └── session_user_standby    [常驻]  ← 主备切换
│
├── fault-analyzer (Agent)
│   ├── session_fault_primary   [常驻]  ← 实时监控告警
│   ├── session_fault_standby   [常驻]  ← 主备
│   ├── session_health_check    [定时]  ← 每小时健康检查
│   └── session_log_cleanup     [定时]  ← 每天凌晨清理日志
│
└── risk-analyzer (Agent)
    ├── session_risk_scan       [定时]  ← 每天安全扫描
    ├── session_compliance      [定时]  ← 每周合规检查
    └── session_alert_handler   [触发]  ← 收到告警时启动
```

### 场景2：数据处理组

```
Group: 数据处理组
├── data-collector (Agent)
│   ├── session_realtime        [常驻]  ← 实时数据收集
│   ├── session_batch           [定时]  ← 每小时批量同步
│   └── session_init            [触发]  ← 新数据源初始化
│
├── data-processor (Agent)
│   ├── session_hourly          [定时]  ← 每小时处理
│   ├── session_daily           [定时]  ← 每日汇总
│   └── session_adhoc           [触发]  ← 手动触发处理
│
└── data-cleaner (Agent)
    ├── session_cleanup         [定时]  ← 每天凌晨清理
    └── session_archive         [定时]  ← 每周归档
```

## 三、配置示例

```json
{
  "agents": [
    {
      "id": "agent_fault",
      "role": "fault-analyzer",
      
      "sessions": [
        {
          "id": "session_fault_primary",
          "type": "resident",
          "role": "primary",
          "session_prompt": "实时监控，处理告警"
        },
        {
          "id": "session_health_check",
          "type": "scheduled",
          "schedule": {
            "cron": "0 * * * *",
            "timezone": "Asia/Shanghai",
            "timeout": 300,
            "retry": 3
          },
          "session_prompt": "执行系统健康检查",
          "on_complete": "notify_group"
        },
        {
          "id": "session_log_cleanup",
          "type": "scheduled",
          "schedule": {
            "cron": "0 2 * * *",
            "timezone": "Asia/Shanghai"
          },
          "session_prompt": "清理过期日志"
        }
      ]
    },
    {
      "id": "agent_risk",
      "role": "risk-analyzer",
      
      "sessions": [
        {
          "id": "session_risk_scan",
          "type": "scheduled",
          "schedule": {
            "cron": "0 3 * * *",
            "timezone": "Asia/Shanghai"
          },
          "session_prompt": "执行每日安全扫描"
        },
        {
          "id": "session_alert_handler",
          "type": "triggered",
          "trigger": {
            "events": ["security_alert", "critical_error"],
            "max_instances": 1,
            "cooldown": 60
          },
          "session_prompt": "处理安全告警"
        }
      ]
    }
  ]
}
```

## 四、调度器实现

### 4.1 核心类

```python
# scheduler.py

class SessionType(Enum):
    RESIDENT = "resident"      # 常驻
    SCHEDULED = "scheduled"    # 定时
    TRIGGERED = "triggered"    # 触发

class SessionScheduler:
    """Session调度器"""
    
    def register_session(
        self,
        session_id: str,
        agent_id: str,
        session_type: str,
        schedule_config: Dict = None,  # 定时配置
        trigger_config: Dict = None,   # 触发配置
        on_complete: str = None,
        on_failure: str = None
    ) -> ScheduledSession
    
    async def start(self)
    async def stop(self)
    async def run_now(self, session_id: str) -> bool
    async def trigger_event(self, event_name: str, event_data: Dict)
    def get_status(self) -> Dict
```

### 4.2 Cron解析器

```python
class CronParser:
    """
    支持5字段标准cron格式：
    minute hour day_of_month month day_of_week
    
    示例:
    - "0 * * * *"      每小时整点
    - "*/15 * * * *"   每15分钟
    - "0 2 * * *"      每天凌晨2点
    - "0 3 * * 1-5"    周一到周五凌晨3点
    """
    
    def get_next_run(self, after: datetime = None) -> datetime
    def get_next_n_runs(self, n: int) -> List[datetime]
```

### 4.3 执行流程

```
┌───────────────────────────────────────────────────────────────┐
│                     定时任务执行流程                           │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  1. 调度循环 (每秒检查)                                        │
│     │                                                         │
│     ▼                                                         │
│  2. 检查 next_run <= now?                                     │
│     │                                                         │
│     YES                                                       │
│     ▼                                                         │
│  3. 状态 = RUNNING, 创建执行任务                               │
│     │                                                         │
│     ▼                                                         │
│  4. 执行回调 (带超时控制)                                       │
│     │                                                         │
│     ├── 成功 ──► 状态 = COMPLETED, 通知Group, 计算下次时间     │
│     │                                                         │
│     ├── 超时 ──► 状态 = TIMEOUT, 检查重试次数                  │
│     │              │                                          │
│     │              ├── retry_count < max ──► 延迟重试          │
│     │              │                                          │
│     │              └── 重试耗尽 ──► 通知失败                    │
│     │                                                         │
│     └── 失败 ──► 同上处理                                      │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

### 4.4 与Group集成

```python
# 在 SAGManager 中集成调度器

class SAGManager:
    def __init__(self):
        self.scheduler = SessionScheduler()
        
        # 设置执行回调
        self.scheduler.set_execution_callback(self._execute_session)
        self.scheduler.set_notify_callback(self._notify_group)
    
    async def _execute_session(self, session_id, agent_id, context):
        """执行Session（启动CLI或触发任务）"""
        # 根据session_type决定执行方式
        if context.get("type") == "scheduled":
            # 启动定时任务CLI
            return await self._start_scheduled_cli(session_id, agent_id)
        elif context.get("type") == "triggered":
            # 处理触发事件
            return await self._handle_triggered_event(
                session_id, agent_id, context.get("event"), context.get("data")
            )
    
    async def _notify_group(self, agent_id, session_id, data):
        """通知Group其他成员"""
        # 通过CLICommunication广播
        await self.communication.broadcast(
            from_cli=session_id,
            topic=f"group.{self.group_id}.events",
            payload=data
        )
```

### 4.5 配置示例（完整）

```json
{
  "group": {
    "id": "ops_monitoring",
    "name": "运维监控组"
  },
  "agents": [
    {
      "id": "fault_analyzer",
      "role": "故障分析",
      "sessions": [
        {
          "id": "fault_primary",
          "type": "resident",
          "role": "primary",
          "session_prompt": "实时监控，处理告警"
        },
        {
          "id": "health_check",
          "type": "scheduled",
          "role": "task",
          "schedule": {
            "cron": "0 * * * *",
            "timezone": "Asia/Shanghai",
            "timeout": 300,
            "retry": 3,
            "retry_delay": 60
          },
          "session_prompt": "执行系统健康检查",
          "on_complete": "notify_group"
        },
        {
          "id": "log_cleanup",
          "type": "scheduled",
          "role": "task",
          "schedule": {
            "cron": "0 2 * * *",
            "timeout": 600
          },
          "session_prompt": "清理过期日志"
        }
      ]
    },
    {
      "id": "risk_analyzer", 
      "role": "风险分析",
      "sessions": [
        {
          "id": "risk_scan",
          "type": "scheduled",
          "schedule": {
            "cron": "0 3 * * *"
          },
          "session_prompt": "每日安全扫描"
        },
        {
          "id": "alert_handler",
          "type": "triggered",
          "trigger": {
            "events": ["security_alert", "critical_error"],
            "max_instances": 1,
            "cooldown": 60
          },
          "session_prompt": "处理安全告警"
        }
      ]
    }
  ]
}
```

## 五、状态管理

### 5.1 调度状态

```
PENDING ──► RUNNING ──► COMPLETED
               │
               ├──► TIMEOUT ──► RETRYING ──► PENDING
               │                              │
               │                              └──► FAILED (重试耗尽)
               │
               └──► FAILED ──► RETRYING
```

### 5.2 持久化

调度配置保存在 `~/.dfecrab/schedules/` 目录：
- 每个Session一个JSON文件
- 包含调度配置和运行时状态
- 调度器启动时自动加载

```json
// ~/.dfecrab/schedules/health_check.json
{
  "session_id": "health_check",
  "agent_id": "fault_analyzer",
  "session_type": "scheduled",
  "status": "pending",
  "last_run": "2024-01-15T10:00:00",
  "next_run": "2024-01-15T11:00:00",
  "retry_count": 0,
  "schedule_config": {
    "cron": "0 * * * *",
    "timeout": 300,
    "retry": 3
  }
}
```

## 六、API接口

### 6.1 注册Session
```python
scheduler.register_session(
    session_id="health_check",
    agent_id="fault_analyzer",
    session_type="scheduled",
    schedule_config={
        "cron": "0 * * * *",
        "timeout": 300,
        "retry": 3
    },
    on_complete="notify_group"
)
```

### 6.2 手动执行
```python
await scheduler.run_now("health_check")
```

### 6.3 触发事件
```python
await scheduler.trigger_event("security_alert", {
    "severity": "high",
    "source": "firewall"
})
```

### 6.4 查看状态
```python
status = scheduler.get_status()
# {
#   "running": true,
#   "total_sessions": 5,
#   "by_type": {"scheduled": 3, "triggered": 2},
#   "sessions": {...}
# }
```
