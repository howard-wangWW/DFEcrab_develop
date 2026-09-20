# 定时任务增强技术方案

**版本**：v4.3.0  
**创建日期**：2026-03-30  
**目标**：完善定时任务系统的企业级功能

---

## 📋 目录

1. [现状分析](#1-现状分析)
2. [设计目标](#2-设计目标)
3. [技术方案](#3-技术方案)
4. [实施计划](#4-实施计划)

---

## 1. 现状分析

### 1.1 当前功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 基础定时任务 | ✅ | 支持 Cron 表达式和固定间隔 |
| 心跳任务 | ✅ | 支持定期健康检查 |
| 待办任务 | ✅ | 支持任务管理 |
| 自然语言设置 | ✅ (v4.2.0) | 支持自然语言交互 |
| TUI 管理界面 | ✅ (v4.2.0) | TUI 界面管理 |

### 1.2 功能差距

| 功能 | 当前状态 | 目标 | 差距 |
|------|---------|------|------|
| **Web UI 管理** | ❌ | 添加 Web 界面管理定时任务 | 🔴 大 |
| **任务持久化** | ⚠️ 部分支持 | 使用 SQLite 存储任务状态 | 🟡 中 |
| **任务依赖** | ❌ | 支持任务执行顺序依赖 | 🔴 大 |
| **任务重试** | ⚠️ 基础支持 | 完善重试策略和告警 | 🟡 中 |
| **任务监控** | ⚠️ 基础日志 | 添加 Prometheus 监控指标 | 🟡 中 |

---

## 2. 设计目标

### 2.1 核心功能

1. **Web UI 管理** - 浏览器界面管理定时任务
2. **完整持久化** - SQLite 存储所有任务状态和历史
3. **任务依赖** - 支持任务执行顺序依赖（DAG）
4. **智能重试** - 失败自动重试 + 多渠道告警
5. **监控指标** - Prometheus + Grafana 完整监控

### 2.2 企业级特性

- **高可用** - 任务执行失败自动重试
- **可观测** - 完整的监控指标和告警
- **易管理** - Web UI 和 API 双重管理方式
- **可扩展** - 支持分布式任务执行

---

## 3. 技术方案

### 3.1 Web UI 管理

#### 3.1.1 架构

```
┌─────────────────────────────────────────────────────────┐
│                    Vue3 前端                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ 任务列表 │  │ 任务编辑 │  │ 执行历史 │              │
│  └──────────┘  └──────────┘  └──────────┘              │
├─────────────────────────────────────────────────────────┤
│                    FastAPI 后端                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  RESTful API                                    │   │
│  │  - GET    /api/schedules  (列表)               │   │
│  │  - POST   /api/schedules  (创建)               │   │
│  │  - PUT    /api/schedules/{id} (更新)           │   │
│  │  - DELETE /api/schedules/{id} (删除)           │   │
│  │  - POST   /api/schedules/{id}/run (执行)       │   │
│  │  - GET    /api/schedules/{id}/logs (日志)      │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

#### 3.1.2 页面设计

**任务列表页**：
```
┌─────────────────────────────────────────────────────────┐
│  📋 定时任务管理                                  [+新建]│
├─────────────────────────────────────────────────────────┤
│  搜索：[________________]  状态：[全部 ▼]  筛选 [应用]  │
├─────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────┐ │
│  │ ✓ 每日备份                                        │ │
│  │   ⏰ 每天 02:00 │ 📅 下次：明天 02:00 │ ✅ 正常  │ │
│  │   最后执行：今天 02:00 | 耗时：2m30s             │ │
│  ├───────────────────────────────────────────────────┤ │
│  │ ✓ 系统健康检查                                    │ │
│  │   ⏰ 每 30 分钟   │ 📅 下次：15:30      │ ✅ 正常  │ │
│  │   最后执行：15:00 | 耗时：5s                     │ │
│  ├───────────────────────────────────────────────────┤ │
│  │ ☐ 生成周报                                        │ │
│  │   ⏰ 每周五 17:00 │ 📅 下次：04-04 17:00 │ ⏸️ 暂停│ │
│  │   最后执行：03-28 17:00 | 耗时：1m20s            │ │
│  └───────────────────────────────────────────────────┘ │
│                                                         │
│  共 3 个任务 | 运行中：2 | 已暂停：1 | 失败：0          │
└─────────────────────────────────────────────────────────┘
```

**任务编辑页**：
```
┌─────────────────────────────────────────────────────────┐
│  ✏️ 编辑任务：每日备份                            [保存]│
├─────────────────────────────────────────────────────────┤
│                                                         │
│  任务名称：[每日备份___________________________]        │
│                                                         │
│  执行时间：                                             │
│  ○ 固定间隔    ○ Cron 表达式    ○ 自然语言             │
│                                                         │
│  [每天 02:00________________] (Cron: 0 2 * * *)        │
│                                                         │
│  任务类型：                                             │
│  [执行 Python 脚本 ▼]                                   │
│                                                         │
│  脚本路径：[/path/to/backup.py________________]         │
│  参数：[--full --compress_______________________]       │
│                                                         │
│  重试策略：                                             │
│  最大重试：[3___] 次    退避策略：[指数退避 ▼]          │
│                                                         │
│  告警通知：                                             │
│  ☑ 邮件  ☑ 钉钉  ☐ 企业微信  ☐ 短信                   │
│  告警条件：失败 [3___] 次后告警                         │
│                                                         │
│  任务依赖：（可选）                                     │
│  前置任务：[选择前置任务 ▼]                             │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 3.2 任务持久化

#### 3.2.1 数据库 Schema

```sql
-- 定时任务表
CREATE TABLE schedules (
    task_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    
    -- 执行配置
    cron_expression TEXT NOT NULL,
    human_readable TEXT,
    interval_seconds INTEGER,
    timezone TEXT DEFAULT 'Asia/Shanghai',
    
    -- 任务内容
    task_type TEXT NOT NULL,  -- python/shell/http/webhook
    task_config TEXT NOT NULL,  -- JSON 格式配置
    
    -- 依赖关系
    dependencies TEXT,  -- JSON 数组，依赖的 task_id 列表
    
    -- 重试策略
    retry_enabled BOOLEAN DEFAULT TRUE,
    max_retries INTEGER DEFAULT 3,
    retry_backoff TEXT DEFAULT 'exponential',  -- linear/exponential/fixed
    retry_delay_seconds INTEGER DEFAULT 60,
    
    -- 告警配置
    alert_enabled BOOLEAN DEFAULT TRUE,
    alert_on_failure INTEGER DEFAULT 3,  -- 失败 N 次后告警
    alert_channels TEXT,  -- JSON 数组，['email', 'dingtalk']
    alert_recipients TEXT,  -- JSON 数组，收件人列表
    
    -- 状态信息
    agent_id TEXT DEFAULT 'default',
    status TEXT DEFAULT 'active',  -- active/paused/disabled
    created_at TEXT NOT NULL,
    updated_at TEXT,
    created_by TEXT,
    
    -- 执行统计
    last_run TEXT,
    next_run TEXT,
    run_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_duration_seconds REAL,
    avg_duration_seconds REAL
);

-- 执行历史表
CREATE TABLE execution_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    execution_id TEXT UNIQUE NOT NULL,
    
    -- 执行时间
    scheduled_time TEXT,  -- 计划执行时间
    started_at TEXT,      -- 实际开始时间
    completed_at TEXT,    -- 实际完成时间
    
    -- 执行结果
    status TEXT NOT NULL,  -- success/failed/timeout/cancelled
    exit_code INTEGER,
    output TEXT,          -- 标准输出
    error_output TEXT,    -- 错误输出
    
    -- 重试信息
    retry_count INTEGER DEFAULT 0,
    is_retry BOOLEAN DEFAULT FALSE,
    parent_execution_id TEXT,  -- 父执行 ID（如果是重试）
    
    -- 依赖信息
    waited_for_dependencies TEXT,  -- 等待的依赖任务
    
    FOREIGN KEY (task_id) REFERENCES schedules(task_id)
);

-- 依赖关系表
CREATE TABLE task_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    depends_on_task_id TEXT NOT NULL,
    dependency_type TEXT DEFAULT 'success',  -- success/completion
    max_wait_seconds INTEGER DEFAULT 3600,   -- 最大等待时间
    
    UNIQUE(task_id, depends_on_task_id),
    FOREIGN KEY (task_id) REFERENCES schedules(task_id),
    FOREIGN KEY (depends_on_task_id) REFERENCES schedules(task_id)
);

-- 告警历史表
CREATE TABLE alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    execution_id TEXT,
    alert_type TEXT NOT NULL,  -- failure/timeout/dependency
    channel TEXT NOT NULL,     -- email/dingtalk/wechat/sms
    recipient TEXT,
    sent_at TEXT NOT NULL,
    status TEXT DEFAULT 'sent',  -- sent/failed
    error_message TEXT,
    
    FOREIGN KEY (task_id) REFERENCES schedules(task_id)
);

-- 索引
CREATE INDEX idx_schedules_status ON schedules(status);
CREATE INDEX idx_schedules_next_run ON schedules(next_run);
CREATE INDEX idx_execution_history_task ON execution_history(task_id);
CREATE INDEX idx_execution_history_status ON execution_history(status);
CREATE INDEX idx_dependencies_task ON task_dependencies(task_id);
```

### 3.3 任务依赖

#### 3.3.1 依赖关系设计

```python
# src/core/scheduler_dependencies.py

from enum import Enum
from typing import List, Dict, Set, Optional
from dataclasses import dataclass
from collections import defaultdict

class DependencyType(Enum):
    SUCCESS = "success"      # 依赖任务成功
    COMPLETION = "completion" # 依赖任务完成（无论成功失败）

@dataclass
class TaskDependency:
    """任务依赖"""
    task_id: str
    depends_on: str
    dependency_type: DependencyType = DependencyType.SUCCESS
    max_wait_seconds: int = 3600

class DependencyResolver:
    """依赖解析器"""
    
    def __init__(self):
        self.dependencies: List[TaskDependency] = []
    
    def add_dependency(self, dep: TaskDependency) -> None:
        """添加依赖关系"""
        # 检测循环依赖
        if self._has_cycle(dep.task_id, dep.depends_on):
            raise ValueError(f"检测到循环依赖：{dep.task_id} -> {dep.depends_on}")
        
        self.dependencies.append(dep)
    
    def _has_cycle(self, from_task: str, to_task: str) -> bool:
        """检测是否有循环依赖（DFS）"""
        visited = set()
        stack = [to_task]
        
        while stack:
            current = stack.pop()
            if current == from_task:
                return True
            if current in visited:
                continue
            visited.add(current)
            
            # 添加当前任务的所有依赖
            for dep in self.dependencies:
                if dep.task_id == current:
                    stack.append(dep.depends_on)
        
        return False
    
    def get_execution_order(self, task_ids: List[str]) -> List[str]:
        """获取执行顺序（拓扑排序）"""
        # 构建图
        graph = defaultdict(list)
        in_degree = defaultdict(int)
        
        for task_id in task_ids:
            in_degree[task_id] = 0
        
        for dep in self.dependencies:
            if dep.task_id in task_ids and dep.depends_on in task_ids:
                graph[dep.depends_on].append(dep.task_id)
                in_degree[dep.task_id] += 1
        
        # Kahn 算法
        queue = [tid for tid in task_ids if in_degree[tid] == 0]
        result = []
        
        while queue:
            # 选择优先级最高的（可以按优先级排序）
            current = queue.pop(0)
            result.append(current)
            
            for next_task in graph[current]:
                in_degree[next_task] -= 1
                if in_degree[next_task] == 0:
                    queue.append(next_task)
        
        if len(result) != len(task_ids):
            raise ValueError("存在循环依赖，无法确定执行顺序")
        
        return result
    
    def can_execute(self, task_id: str, task_status: Dict[str, str]) -> bool:
        """检查任务是否可以执行"""
        for dep in self.dependencies:
            if dep.task_id != task_id:
                continue
            
            dep_status = task_status.get(dep.depends_on)
            if not dep_status:
                return False  # 依赖任务还未执行
            
            if dep.dependency_type == DependencyType.SUCCESS:
                if dep_status != 'success':
                    return False
            elif dep.dependency_type == DependencyType.COMPLETION:
                if dep_status not in ['success', 'failed']:
                    return False
        
        return True
```

### 3.4 任务重试

#### 3.4.1 重试策略

```python
# src/core/scheduler_retry.py

import asyncio
import time
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass

class BackoffStrategy(Enum):
    FIXED = "fixed"           # 固定延迟
    LINEAR = "linear"         # 线性退避
    EXPONENTIAL = "exponential"  # 指数退避

@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3
    backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    base_delay_seconds: float = 60.0
    max_delay_seconds: float = 3600.0
    jitter: bool = True  # 是否添加随机抖动

class RetryExecutor:
    """重试执行器"""
    
    def __init__(self, config: RetryConfig):
        self.config = config
    
    def calculate_delay(self, retry_count: int) -> float:
        """计算延迟时间"""
        if self.config.backoff_strategy == BackoffStrategy.FIXED:
            delay = self.config.base_delay_seconds
        
        elif self.config.backoff_strategy == BackoffStrategy.LINEAR:
            delay = self.config.base_delay_seconds * retry_count
        
        elif self.config.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.config.base_delay_seconds * (2 ** (retry_count - 1))
        
        else:
            delay = self.config.base_delay_seconds
        
        # 限制最大延迟
        delay = min(delay, self.config.max_delay_seconds)
        
        # 添加抖动（避免惊群效应）
        if self.config.jitter:
            import random
            jitter = random.uniform(0.8, 1.2)
            delay *= jitter
        
        return delay
    
    async def execute_with_retry(
        self,
        func: Callable,
        on_retry: Optional[Callable] = None,
        on_failure: Optional[Callable] = None
    ) -> Any:
        """带重试执行"""
        last_exception = None
        
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return await func()
            
            except Exception as e:
                last_exception = e
                
                if attempt < self.config.max_retries:
                    delay = self.calculate_delay(attempt)
                    
                    # 调用重试回调
                    if on_retry:
                        await on_retry(attempt, delay, e)
                    
                    await asyncio.sleep(delay)
                else:
                    # 调用失败回调
                    if on_failure:
                        await on_failure(attempt, e)
        
        raise last_exception
```

### 3.5 监控指标

#### 3.5.1 Prometheus 指标

```python
# src/monitoring/prometheus_exporter.py

from prometheus_client import Counter, Gauge, Histogram, start_http_server

class SchedulerMetrics:
    """调度器监控指标"""
    
    def __init__(self):
        # 任务数量
        self.tasks_total = Gauge(
            'scheduler_tasks_total',
            'Total number of scheduled tasks'
        )
        
        self.tasks_active = Gauge(
            'scheduler_tasks_active',
            'Number of active scheduled tasks'
        )
        
        self.tasks_paused = Gauge(
            'scheduler_tasks_paused',
            'Number of paused scheduled tasks'
        )
        
        # 任务执行
        self.task_executions_total = Counter(
            'scheduler_task_executions_total',
            'Total number of task executions',
            ['task_id', 'status']  # status: success/failed/timeout
        )
        
        self.task_execution_duration = Histogram(
            'scheduler_task_execution_duration_seconds',
            'Task execution duration in seconds',
            ['task_id'],
            buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 300, 600, 1800, 3600]
        )
        
        # 重试统计
        self.task_retries_total = Counter(
            'scheduler_task_retries_total',
            'Total number of task retries',
            ['task_id']
        )
        
        # 下次执行时间
        self.next_run_seconds = Gauge(
            'scheduler_next_run_seconds',
            'Seconds until next execution',
            ['task_id']
        )
        
        # 依赖等待
        self.dependency_wait_seconds = Gauge(
            'scheduler_dependency_wait_seconds',
            'Seconds waiting for dependencies',
            ['task_id', 'depends_on']
        )
        
        # 告警统计
        self.alerts_total = Counter(
            'scheduler_alerts_total',
            'Total number of alerts sent',
            ['task_id', 'channel', 'type']
        )
    
    def update_task_count(self, total: int, active: int, paused: int):
        """更新任务数量"""
        self.tasks_total.set(total)
        self.tasks_active.set(active)
        self.tasks_paused.set(paused)
    
    def record_execution(self, task_id: str, status: str, duration: float):
        """记录执行"""
        self.task_executions_total.labels(
            task_id=task_id,
            status=status
        ).inc()
        
        self.task_execution_duration.labels(
            task_id=task_id
        ).observe(duration)
    
    def record_retry(self, task_id: str):
        """记录重试"""
        self.task_retries_total.labels(task_id=task_id).inc()
    
    def update_next_run(self, task_id: str, seconds: float):
        """更新下次执行时间"""
        self.next_run_seconds.labels(task_id=task_id).set(seconds)
    
    def record_dependency_wait(self, task_id: str, depends_on: str, seconds: float):
        """记录依赖等待"""
        self.dependency_wait_seconds.labels(
            task_id=task_id,
            depends_on=depends_on
        ).set(seconds)
    
    def record_alert(self, task_id: str, channel: str, alert_type: str):
        """记录告警"""
        self.alerts_total.labels(
            task_id=task_id,
            channel=channel,
            type=alert_type
        ).inc()

# 启动指标服务器
def start_metrics_server(port: int = 9090):
    """启动 Prometheus 指标服务器"""
    start_http_server(port)
```

#### 3.5.2 Grafana 仪表板

```json
{
  "dashboard": {
    "title": "DFEcrab 定时任务监控",
    "panels": [
      {
        "title": "任务总数",
        "targets": [{
          "expr": "scheduler_tasks_total"
        }]
      },
      {
        "title": "任务执行成功率",
        "targets": [{
          "expr": "rate(scheduler_task_executions_total{status=\"success\"}[5m]) / rate(scheduler_task_executions_total[5m]) * 100"
        }]
      },
      {
        "title": "任务执行耗时 P99",
        "targets": [{
          "expr": "histogram_quantile(0.99, rate(scheduler_task_execution_duration_seconds_bucket[5m]))"
        }]
      },
      {
        "title": "重试次数",
        "targets": [{
          "expr": "rate(scheduler_task_retries_total[5m])"
        }]
      }
    ]
  }
}
```

---

## 4. 实施计划

### 4.1 时间线

```
Week 1-3:  Web UI 管理 → v4.3.0-alpha
Week 4-5:  任务持久化 → v4.3.0-beta
Week 6-7:  任务依赖 → v4.3.0-rc
Week 8:    任务重试和告警 → v4.3.0
Week 9-10: 监控指标 → v4.3.0
```

### 4.2 里程碑

| 里程碑 | 版本 | 日期 | 交付物 |
|--------|------|------|--------|
| M1: Web UI | v4.3.0-alpha | Week 3 | 可运行的 Web 管理界面 |
| M2: 持久化 | v4.3.0-beta | Week 5 | SQLite 完整存储 |
| M3: 依赖 | v4.3.0-rc | Week 7 | 任务依赖正确执行 |
| M4: 重试告警 | v4.3.0 | Week 8 | 智能重试 + 告警 |
| M5: 监控 | v4.3.0 | Week 10 | Prometheus + Grafana |

### 4.3 成功指标

- [ ] ✅ Web UI 可正常管理任务
- [ ] ✅ SQLite 持久化稳定
- [ ] ✅ 任务依赖正确执行（无循环依赖）
- [ ] ✅ 失败自动重试（重试成功率>80%）
- [ ] ✅ 告警通知及时（告警延迟<1 分钟）
- [ ] ✅ 监控指标完整
- [ ] ✅ Grafana 仪表板可用
- [ ] ✅ 测试覆盖率>80%

---

## 5. 附录

### 5.1 文件变更清单

**新增文件**：
```
src/web/
├── app.py
├── api/
│   └── schedules.py
└── static/
    └── admin/

src/core/
├── scheduler_dependencies.py
└── scheduler_retry.py

src/storage/
└── schedule_db.py

src/monitoring/
├── prometheus_exporter.py
└── alerting/
    ├── __init__.py
    ├── email.py
    ├── dingtalk.py
    └── wechat.py

monitoring/
├── prometheus.yml
└── grafana/
    └── dashboard.json
```

### 5.2 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/schedules | 获取任务列表 |
| POST | /api/schedules | 创建任务 |
| GET | /api/schedules/{id} | 获取任务详情 |
| PUT | /api/schedules/{id} | 更新任务 |
| DELETE | /api/schedules/{id} | 删除任务 |
| POST | /api/schedules/{id}/run | 立即执行 |
| POST | /api/schedules/{id}/pause | 暂停任务 |
| POST | /api/schedules/{id}/resume | 恢复任务 |
| GET | /api/schedules/{id}/logs | 获取执行日志 |
| GET | /api/schedules/{id}/metrics | 获取监控指标 |
| GET | /api/metrics/overview | 获取概览统计 |

---

**文档版本**：1.0  
**创建时间**：2026-03-30  
**审阅状态**：待审阅
