# DFEcrab 任务管理与多 Agent 协作系统设计

> 版本：v1.0  
> 日期：2026-04-04  
> 状态：设计阶段

---

## 一、需求概述

### 1.1 任务类型

系统支持两种任务类型：

| 类型 | 特点 | 生命周期 | 示例 |
|------|------|---------|------|
| **临时任务** | 指令性、多次交互、可放弃/转化 | 短期（小时/天） | "帮我分析这个 bug" |
| **周期任务** | 自动执行、定期运行、持续积累 | 长期（周/月） | "每周生成运维报告" |

### 1.2 核心需求

1. **任务主题**：每个任务有一个明确的主题（Topic）
2. **监管 Agent**：每个任务有一个监管 Agent 负责协调和追踪
3. **专业 Agent 团队**：一组专业 Agent 共同完成任务
4. **工作流进度**：任务执行过程有明确的进度追踪
5. **行为审计**：每个 Agent 的操作都有审计日志
6. **界面展示**：监管 Agent 通过界面展示整体情况

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户界面层                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │  TUI     │  │  Web UI  │  │  API     │  │  CLI     │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        任务管理层                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    TaskManager                               │   │
│  │  - 任务创建/销毁/查询                                        │   │
│  │  - 临时任务 ↔ 周期任务转化                                   │   │
│  │  - 任务主题管理                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        任务执行层                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    TaskInstance                              │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │  SupervisorSession (监管会话)                         │   │   │
│  │  │  - 任务协调者                                         │   │   │
│  │  │  - 进度追踪                                           │   │   │
│  │  │  - 审计日志                                           │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  │  ┌──────────────────────────────────────────────────────┐   │   │
│  │  │  AgentGroup (Agent 编组)                              │   │   │
│  │  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │   │   │
│  │  │  │ TaskMember │  │ TaskMember │  │ TaskMember │     │   │   │
│  │  │  │ AgentRef A │  │ AgentRef B │  │ AgentRef C │     │   │   │
│  │  │  │ Session A1 │  │ Session B2 │  │ Session C3 │     │   │   │
│  │  │  └────────────┘  └────────────┘  └────────────┘     │   │   │
│  │  └──────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent 实体层                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Agent A  │  │ Agent B  │  │ Agent C  │  │ Agent D  │           │
│  │ (设计)   │  │ (开发)   │  │ (审查)   │  │ (测试)   │           │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心模块设计

### 3.1 TaskManager（任务管理器）

**职责**：统一管理系统中的所有任务

```python
class TaskManager:
    """任务管理器"""
    
    # 任务类型
    TEMPORARY = "temporary"    # 临时任务
    PERIODIC = "periodic"      # 周期任务
    
    # 任务状态
    PENDING = "pending"        # 待执行
    RUNNING = "running"        # 执行中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败
    CANCELLED = "cancelled"    # 已取消
    CONVERTED = "converted"    # 已转化（临时→周期）
    
    def create_task(
        self,
        topic: str,                    # 任务主题
        task_type: str,                # temporary/periodic
        description: str,              # 任务描述
        supervisor_agent_id: str,      # 监管 Agent ID
        agent_group_config: dict,      # AgentGroup 配置
        schedule: dict = None,         # 周期任务调度配置
    ) -> TaskInstance:
        """创建任务"""
        pass
    
    def convert_task(self, task_id: str, target_type: str) -> TaskInstance:
        """转化任务类型（临时↔周期）"""
        pass
    
    def get_task_progress(self, task_id: str) -> TaskProgress:
        """获取任务进度"""
        pass
    
    def get_task_audit_log(self, task_id: str) -> List[AuditLog]:
        """获取任务审计日志"""
        pass
```

### 3.2 TaskInstance（任务实例）

**职责**：表示一个具体的任务执行实例

```python
@dataclass
class TaskInstance:
    """任务实例"""
    task_id: str
    topic: str                          # 任务主题
    task_type: str                      # temporary/periodic
    status: str                         # pending/running/completed/failed
    description: str                    # 任务描述
    
    # 监管
    supervisor_session_id: str          # 监管会话 ID
    supervisor_agent_id: str            # 监管 Agent ID
    
    # AgentGroup
    agent_group: AgentGroup             # Agent 编组
    
    # 进度
    progress: TaskProgress              # 进度追踪
    
    # 审计
    audit_log: AuditLogger              # 审计日志
    
    # 时间
    created_at: datetime
    started_at: datetime = None
    completed_at: datetime = None
    
    # 周期任务专属
    schedule: dict = None               # cron 表达式
    last_run: datetime = None
    next_run: datetime = None
    run_count: int = 0
```

### 3.3 AgentGroup（Agent 编组）

**职责**：管理任务中的 Agent 团队

```python
class AgentGroup:
    """Agent 编组 - 混合方案实现"""
    
    def __init__(self, task_id: str, task_type: str, config: dict):
        self.task_id = task_id
        self.task_type = task_type
        self.members: List[TaskMember] = []
        
        # 根据任务类型选择模式
        if task_type == TaskManager.TEMPORARY:
            # 轻量模式：复用 Agent，创建 Session 团队
            self._init_session_team(config)
        else:
            # 独立模式：创建专用 Agent 实例
            self._init_dedicated_agents(config)
    
    def _init_session_team(self, config: dict):
        """初始化 Session 团队（临时任务）"""
        for member_config in config['members']:
            # 引用已有 Agent，创建独立 TaskSession
            member = TaskMember(
                agent_ref=member_config['agent_id'],  # 引用
                session_id=uuid4().hex,               # 新 Session
                role=member_config['role'],
                mode='session_team'                   # 轻量模式
            )
            self.members.append(member)
    
    def _init_dedicated_agents(self, config: dict):
        """初始化专用 Agent（周期任务）"""
        for member_config in config['members']:
            # 创建新 Agent 实例
            member = TaskMember(
                agent_id=f"{self.task_id}_{member_config['role']}",
                session_id=uuid4().hex,
                role=member_config['role'],
                mode='dedicated_agent'                # 独立模式
            )
            self.members.append(member)
```

### 3.4 TaskMember（任务成员）

**职责**：表示 AgentGroup 中的一个成员

```python
@dataclass
class TaskMember:
    """任务成员"""
    agent_ref: str                    # Agent 引用 ID
    session_id: str                   # 任务会话 ID
    role: str                         # 角色（designer/developer/reviewer）
    mode: str                         # session_team/dedicated_agent
    
    # 状态
    status: str = "idle"              # idle/running/completed/failed
    progress: float = 0.0             # 0-100
    
    # 审计
    action_count: int = 0             # 操作次数
    last_action: datetime = None      # 最后操作时间
    
    # 记忆隔离
    memory_scope: str = "session"     # session/agent
```

### 3.5 SupervisorSession（监管会话）

**职责**：任务的协调者和进度追踪者

```python
class SupervisorSession:
    """监管会话 - 任务协调者"""
    
    def __init__(self, task_id: str, agent_group: AgentGroup):
        self.task_id = task_id
        self.agent_group = agent_group
        self.session_id = uuid4().hex
        
        # 进度追踪
        self.progress_tracker = ProgressTracker()
        
        # 审计日志
        self.audit_logger = AuditLogger(task_id)
        
        # 工作流
        self.workflow = WorkflowEngine()
    
    async def coordinate_task(self, user_input: str):
        """协调任务执行"""
        # 1. 分解任务
        plan = await self.workflow.decompose_task(user_input)
        
        # 2. 分配给 AgentGroup
        for step in plan.steps:
            member = self.agent_group.select_member(step.required_role)
            await self.assign_step(member, step)
            
            # 3. 追踪进度
            self.progress_tracker.update_step(step.id, "running")
            
            # 4. 记录审计
            self.audit_logger.log_action(
                action="assign_step",
                agent=member.agent_ref,
                step=step.id,
                timestamp=datetime.now()
            )
        
        # 5. 执行并监控
        await self.monitor_execution()
    
    async def monitor_execution(self):
        """监控执行进度"""
        while not self.progress_tracker.is_complete():
            for member in self.agent_group.members:
                status = await self.check_member_status(member)
                self.progress_tracker.update_member(member, status)
                
                # 记录审计
                self.audit_logger.log_action(
                    action="check_status",
                    agent=member.agent_ref,
                    status=status,
                    timestamp=datetime.now()
                )
            
            await asyncio.sleep(5)  # 5 秒检查一次
    
    def get_dashboard_data(self) -> dict:
        """获取界面展示数据"""
        return {
            "task_id": self.task_id,
            "progress": self.progress_tracker.get_overall_progress(),
            "members": [
                {
                    "agent": m.agent_ref,
                    "role": m.role,
                    "status": m.status,
                    "progress": m.progress,
                }
                for m in self.agent_group.members
            ],
            "workflow": self.workflow.get_status(),
            "audit_summary": self.audit_logger.get_summary(),
        }
```

### 3.6 ProgressTracker（进度追踪器）

**职责**：实时追踪任务进度

```python
class ProgressTracker:
    """进度追踪器"""
    
    def __init__(self):
        self.steps: Dict[str, StepProgress] = {}
        self.members: Dict[str, MemberProgress] = {}
        self.callbacks: List[Callable] = []  # 进度变更回调
    
    def update_step(self, step_id: str, status: str):
        """更新步骤进度"""
        self.steps[step_id] = StepProgress(
            step_id=step_id,
            status=status,
            updated_at=datetime.now()
        )
        self._notify_callbacks()
    
    def update_member(self, member: TaskMember, status: dict):
        """更新成员进度"""
        self.members[member.session_id] = MemberProgress(
            agent=member.agent_ref,
            role=member.role,
            status=status['status'],
            progress=status.get('progress', 0),
            updated_at=datetime.now()
        )
        self._notify_callbacks()
    
    def get_overall_progress(self) -> float:
        """获取总体进度"""
        if not self.steps:
            return 0.0
        completed = sum(1 for s in self.steps.values() if s.status == "completed")
        return (completed / len(self.steps)) * 100
    
    def is_complete(self) -> bool:
        """是否完成"""
        return self.get_overall_progress() >= 100.0
    
    def on_progress(self, callback: Callable):
        """注册进度回调（用于 WebSocket 推送）"""
        self.callbacks.append(callback)
    
    def _notify_callbacks(self):
        """通知所有回调"""
        data = {
            "overall": self.get_overall_progress(),
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "members": {k: v.to_dict() for k, v in self.members.items()},
        }
        for callback in self.callbacks:
            callback(data)
```

### 3.7 AuditLogger（审计日志器）

**职责**：记录所有 Agent 操作

```python
class AuditLogger:
    """审计日志器"""
    
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.logs: List[AuditLogEntry] = []
    
    def log_action(
        self,
        action: str,
        agent: str,
        details: dict = None,
        timestamp: datetime = None
    ):
        """记录操作"""
        entry = AuditLogEntry(
            task_id=self.task_id,
            action=action,
            agent=agent,
            details=details or {},
            timestamp=timestamp or datetime.now()
        )
        self.logs.append(entry)
    
    def get_logs(self, agent: str = None, action: str = None) -> List[AuditLogEntry]:
        """查询审计日志"""
        logs = self.logs
        if agent:
            logs = [l for l in logs if l.agent == agent]
        if action:
            logs = [l for l in logs if l.action == action]
        return logs
    
    def get_summary(self) -> dict:
        """获取审计摘要"""
        return {
            "total_actions": len(self.logs),
            "by_agent": self._count_by_field("agent"),
            "by_action": self._count_by_field("action"),
            "last_action": self.logs[-1] if self.logs else None,
        }
```

### 3.8 WorkflowEngine（工作流引擎）

**职责**：管理任务的工作流

```python
class WorkflowEngine:
    """工作流引擎"""
    
    def __init__(self):
        self.steps: List[WorkflowStep] = []
        self.current_step: int = 0
    
    async def decompose_task(self, user_input: str) -> TaskPlan:
        """使用 LLM 分解任务"""
        # 调用 LLM 将用户输入分解为步骤
        plan = await llm.decompose(user_input)
        self.steps = plan.steps
        return plan
    
    def get_status(self) -> dict:
        """获取工作流状态"""
        return {
            "total_steps": len(self.steps),
            "current_step": self.current_step,
            "completed_steps": sum(1 for s in self.steps[:self.current_step] if s.status == "completed"),
            "steps": [s.to_dict() for s in self.steps],
        }
```

---

## 四、任务生命周期

### 4.1 临时任务流程

```
用户发起任务
    │
    ▼
TaskManager.create_task(topic, "temporary", ...)
    │
    ▼
创建 SupervisorSession（监管会话）
    │
    ▼
创建 AgentGroup（Session 团队模式）
    ├─ 引用 Agent A → 创建 TaskSession A1
    ├─ 引用 Agent B → 创建 TaskSession B2
    └─ 引用 Agent C → 创建 TaskSession C3
    │
    ▼
SupervisorSession.coordinate_task(user_input)
    │
    ├─ 分解任务 → WorkflowEngine
    ├─ 分配步骤 → AgentGroup
    ├─ 追踪进度 → ProgressTracker
    └─ 记录审计 → AuditLogger
    │
    ▼
任务完成 / 用户取消 / 用户转化
    │
    ├─ 完成 → 归档 TaskSession，保留审计日志
    ├─ 取消 → 清理 TaskSession，保留审计日志
    └─ 转化 → 创建周期任务，迁移必要状态
```

### 4.2 周期任务流程

```
TaskManager.create_task(topic, "periodic", schedule={...})
    │
    ▼
创建 SupervisorSession（监管会话）
    │
    ▼
创建 AgentGroup（专用 Agent 模式）
    ├─ 创建专用 Agent A1 → 创建 TaskSession
    ├─ 创建专用 Agent B2 → 创建 TaskSession
    └─ 创建专用 Agent C3 → 创建 TaskSession
    │
    ▼
按 schedule 自动执行
    │
    ├─ 每次执行 → SupervisorSession.coordinate_task()
    ├─ 追踪进度 → ProgressTracker
    └─ 记录审计 → AuditLogger
    │
    ▼
持续运行，知识积累到专用 Agent
```

### 4.3 任务转化流程

```
临时任务执行中/完成后
    │
    ▼
用户请求转化：TaskManager.convert_task(task_id, "periodic")
    │
    ▼
创建新的周期任务
    ├─ 复制主题、描述、AgentGroup 配置
    ├─ 添加 schedule 配置
    └─ 创建新的 SupervisorSession
    │
    ▼
迁移必要状态
    ├─ 复制审计日志
    ├─ 复制进度历史
    └─ 标记原任务为 "converted"
    │
    ▼
原临时任务归档，新周期任务开始运行
```

---

## 五、记忆管理策略

### 5.1 隔离策略

```
Agent 长期记忆（共享）
    │
    ├── TaskSession A1 短期记忆（任务 A）
    ├── TaskSession A2 短期记忆（任务 B）
    └── TaskSession A3 短期记忆（任务 C）

任务结束后：
    临时任务 → 短期记忆丢弃，或提取关键知识合并
    周期任务 → 短期记忆 → 合并到 Agent 长期记忆
```

### 5.2 合并策略

```python
class MemoryManager:
    """记忆管理器"""
    
    async def merge_task_memory(self, task_instance: TaskInstance):
        """合并任务记忆到 Agent 长期记忆"""
        for member in task_instance.agent_group.members:
            # 获取 TaskSession 短期记忆
            short_term = await self.get_session_memory(member.session_id)
            
            # 提取关键知识
            key_knowledge = await self.extract_key_knowledge(short_term)
            
            if task_instance.task_type == TaskManager.PERIODIC:
                # 周期任务：合并到长期记忆
                await self.merge_to_long_term(member.agent_ref, key_knowledge)
            else:
                # 临时任务：仅合并关键知识（可选）
                if task_instance.progress.get_overall_progress() > 80:
                    await self.merge_to_long_term(member.agent_ref, key_knowledge)
            
            # 清理短期记忆
            await self.clear_session_memory(member.session_id)
```

---

## 六、界面展示设计

### 6.1 任务看板

```
┌─────────────────────────────────────────────────────────────────┐
│  任务看板                                                         │
├─────────────────────────────────────────────────────────────────┤
│  任务 ID: task_abc123                                            │
│  主    题: 分析电网故障                                          │
│  类    型: 临时任务                                              │
│  状    态: 执行中                                                │
│  进    度: ████████░░ 80%                                       │
├─────────────────────────────────────────────────────────────────┤
│  Agent 团队                                                       │
│  ┌────────────┬────────┬────────┬────────┐                      │
│  │ Agent      │ 角色   │ 状态   │ 进度   │                      │
│  ├────────────┼────────┼────────┼────────┤                      │
│  │ qwencode   │ 设计   │ 完成   │ 100%   │                      │
│  │ codebuddy  │ 开发   │ 执行中 │ 75%    │                      │
│  │ dfecrab    │ 审查   │ 等待   │ 0%     │                      │
│  └────────────┴────────┴────────┴────────┘                      │
├─────────────────────────────────────────────────────────────────┤
│  工作流                                                          │
│  1. 需求分析 ✅                                                  │
│  2. 方案设计 ✅                                                  │
│  3. 代码实现 🔄                                                  │
│  4. 测试验证 ⏳                                                  │
│  5. 部署上线 ⏳                                                  │
├─────────────────────────────────────────────────────────────────┤
│  审计日志（最近 5 条）                                            │
│  10:30:15 | codebuddy | 执行步骤 3 | 完成 75%                   │
│  10:29:45 | qwencode  | 完成步骤 2 | 100%                       │
│  10:28:30 | supervisor| 分配步骤 3 | codebuddy                  │
│  10:27:00 | qwencode  | 执行步骤 2 | 完成 100%                  │
│  10:25:00 | supervisor| 任务开始   | task_abc123                │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 实时推送

```python
# WebSocket 推送进度更新
async def on_progress_update(data: dict):
    await websocket.send_json({
        "type": "progress_update",
        "task_id": data["task_id"],
        "progress": data["overall"],
        "members": data["members"],
        "timestamp": datetime.now().isoformat(),
    })

# 注册回调
progress_tracker.on_progress(on_progress_update)
```

---

## 七、API 设计

### 7.1 任务管理 API

```
POST   /api/tasks                      # 创建任务
GET    /api/tasks                      # 列出任务
GET    /api/tasks/{task_id}            # 任务详情
POST   /api/tasks/{task_id}/convert    # 转化任务类型
DELETE /api/tasks/{task_id}            # 取消任务

GET    /api/tasks/{task_id}/progress   # 获取进度
GET    /api/tasks/{task_id}/audit      # 获取审计日志
WS     /api/tasks/{task_id}/ws         # 实时进度推送
```

### 7.2 请求/响应示例

**创建临时任务**：
```json
POST /api/tasks
{
  "topic": "分析电网故障",
  "task_type": "temporary",
  "description": "分析最近的电网故障原因",
  "supervisor_agent_id": "supervisor_01",
  "agent_group_config": {
    "members": [
      {"agent_id": "qwencode", "role": "designer"},
      {"agent_id": "codebuddy", "role": "developer"},
      {"agent_id": "dfecrab", "role": "reviewer"}
    ]
  }
}
```

**响应**：
```json
{
  "task_id": "task_abc123",
  "status": "pending",
  "supervisor_session_id": "sess_xyz789",
  "agent_group": {
    "mode": "session_team",
    "members": [
      {"agent_ref": "qwencode", "session_id": "sess_a1", "role": "designer"},
      {"agent_ref": "codebuddy", "session_id": "sess_b2", "role": "developer"},
      {"agent_ref": "dfecrab", "session_id": "sess_c3", "role": "reviewer"}
    ]
  }
}
```

---

## 八、实现计划

### 8.1 阶段一：核心模块（1-2 周）

- [ ] TaskManager 实现
- [ ] TaskInstance 数据模型
- [ ] AgentGroup 实现（混合方案）
- [ ] TaskMember 实现

### 8.2 阶段二：监管与进度（1 周）

- [ ] SupervisorSession 实现
- [ ] ProgressTracker 实现
- [ ] WebSocket 实时推送

### 8.3 阶段三：审计与工作流（1 周）

- [ ] AuditLogger 实现
- [ ] WorkflowEngine 实现
- [ ] 记忆管理策略

### 8.4 阶段四：API 与界面（1-2 周）

- [ ] REST API 实现
- [ ] TUI 任务看板
- [ ] 任务转化功能

---

## 九、关键设计决策

| 决策点 | 选择 | 原因 |
|--------|------|------|
| 临时任务模式 | Session 团队 | 轻量、快速、知识共享 |
| 周期任务模式 | 专用 Agent | 独立状态、可积累经验 |
| 记忆隔离 | Session 级别 | 避免任务间污染 |
| 进度推送 | WebSocket | 实时、低延迟 |
| 审计存储 | JSON 文件 | 简单、易查询 |
| 任务转化 | 新建 + 迁移 | 保持状态清晰 |

---

*设计完成时间: 2026-04-04*  
*下一步: 开始阶段一实现*
