# Session-Agent-Group 三层架构

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        Group 层（组层）                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Group: "运维监控组"                                      │   │
│  │  - 协调多个Agent协作                                       │   │
│  │  - 管理共享资源和通信                                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         ▼                    ▼                    ▼             │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐      │
│  │   Agent 1   │      │   Agent 2   │      │   Agent 3   │      │
│  │ 用户交互    │      │ 故障分析    │      │ 风险分析    │      │
│  │             │      │             │      │             │      │
│  │ Session层   │      │ Session层   │      │ Session层   │      │
│  │ ┌─────────┐ │      │ ┌─────────┐ │      │ ┌─────────┐ │      │
│  │ │Session-1│ │      │ │Session-2│ │      │ │Session-3│ │      │
│  │ │会话状态  │ │      │ │会话状态  │ │      │ │会话状态  │ │      │
│  │ │工作记忆  │ │      │ │工作记忆  │ │      │ │工作记忆  │ │      │
│  │ │技能状态  │ │      │ │技能状态  │ │      │ │技能状态  │ │      │
│  │ └─────────┘ │      │ └─────────┘ │      │ └─────────┘ │      │
│  └─────────────┘      └─────────────┘      └─────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三层定义

### 1. Session 层（会话层）

**定义**: 单次CLI运行的上下文环境

**职责**:
- 管理单次运行的状态
- 存储工作记忆和技能状态
- 处理用户对话历史

**生命周期**: CLI启动 → 运行 → 退出/崩溃

```python
# Session 包含
class Session:
    session_id: str           # 会话ID
    cli_id: str              # CLI标识
    working_memory: Dict     # 工作记忆（独立）
    skill_state: Dict        # 技能状态（独立）
    conversation: List       # 对话历史
    status: str              # active/crashed/recovered
```

### 2. Agent 层（智能体层）

**定义**: 具有特定角色和能力的智能体实例

**职责**:
- 定义智能体的角色和能力
- 管理该Agent的专用技能
- 处理特定领域的任务

**生命周期**: Group创建 → 加入Group → Group解散

```python
# Agent 包含
class Agent:
    agent_id: str            # Agent ID
    role: str                # 角色：user-interaction/fault-analyzer/risk-analyzer
    capabilities: List       # 能力列表
    skills: List             # 专用技能
    sessions: List[Session]  # 关联的Session列表
```

### 3. Group 层（组层）

**定义**: 多个Agent协作的组织单元

**职责**:
- 协调多个Agent之间的协作
- 管理共享的项目记忆
- 处理Agent间的消息路由

**生命周期**: 用户启动 → 运行 → 用户关闭

```python
# Group 包含
class Group:
    group_id: str            # 组ID
    name: str                # 组名称
    agents: List[Agent]      # 组内Agent列表
    shared_memory: Memory    # 共享的项目记忆
    communication: Queue     # Agent间通信
    coordinator: Coordinator # 协调器
```

---

## 启动流程

```
                    用户启动 dfecrab
                          │
                          ▼
              ┌───────────────────────┐
              │   1. 创建 Group       │
              │   - 初始化共享记忆     │
              │   - 创建协调器        │
              └───────────┬───────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │2.创建Agent1│  │2.创建Agent2│  │2.创建Agent3│
   │用户交互    │  │故障分析    │  │风险分析    │
   │- 加载技能  │  │- 加载技能  │  │- 加载技能  │
   └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
         │               │               │
         ▼               ▼               ▼
   ┌────────────┐  ┌────────────┐  ┌────────────┐
   │3.创建Session│  │3.创建Session│  │3.创建Session│
   │- 工作记忆  │  │- 工作记忆  │  │- 工作记忆  │
   │- 技能状态  │  │- 技能状态  │  │- 技能状态  │
   └────────────┘  └────────────┘  └────────────┘
         │               │               │
         └───────────────┼───────────────┘
                         │
                         ▼
              ┌───────────────────────┐
              │   4. 启动 CLI 进程    │
              │   - 启动心跳监控      │
              │   - 开始消息循环      │
              └───────────────────────┘
```

---

## 详细启动代码

### 1. Group 启动

```python
class GroupManager:
    """组管理器"""
    
    async def create_group(
        self,
        group_name: str,
        project_dir: Path,
        agent_configs: List[Dict]
    ) -> Group:
        """创建一个Group"""
        
        # 1. 创建Group实例
        group = Group(
            group_id=str(uuid.uuid4()),
            name=group_name,
            project_dir=project_dir
        )
        
        # 2. 初始化共享记忆
        group.shared_memory = FourLayerMemoryManager(
            base_dir=project_dir,
            runtime_dir=Path.home() / ".dfecrab"
        )
        
        # 3. 创建协调器
        group.coordinator = Coordinator(project_dir, runtime_dir)
        await group.coordinator.initialize()
        
        # 4. 创建Agent
        for agent_config in agent_configs:
            agent = await self._create_agent(group, agent_config)
            group.agents.append(agent)
        
        # 5. 注册到全局
        self._groups[group.group_id] = group
        
        return group
```

### 2. Agent 启动

```python
class AgentManager:
    """Agent管理器"""
    
    async def create_agent(
        self,
        group: Group,
        role: str,
        capabilities: List[str],
        skills: List[str]
    ) -> Agent:
        """创建一个Agent"""
        
        # 1. 创建Agent实例
        agent = Agent(
            agent_id=f"{role}_{uuid.uuid4().hex[:8]}",
            role=role,
            capabilities=capabilities,
            group_id=group.group_id
        )
        
        # 2. 加载专用技能
        for skill_name in skills:
            skill = await self._load_skill(skill_name)
            agent.skills.append(skill)
        
        # 3. 注册到Group的协调器
        await group.coordinator.register_agent(agent.agent_id, agent)
        
        return agent
```

### 3. Session 启动

```python
class SessionManager:
    """Session管理器"""
    
    async def create_session(
        self,
        agent: Agent,
        cli_id: str
    ) -> Session:
        """创建一个Session"""
        
        # 1. 检查是否有可恢复的session
        crashed_sessions = self.persistence.list_crashed_sessions()
        for cs in crashed_sessions:
            if cs.cli_id == cli_id:
                # 恢复已有session
                return await self._recover_session(cli_id)
        
        # 2. 创建新Session
        session = Session(
            session_id=str(uuid.uuid4()),
            cli_id=cli_id,
            agent_id=agent.agent_id,
            created_at=datetime.now()
        )
        
        # 3. 初始化工作记忆
        session.working_memory = WorkMemory(cli_id=cli_id)
        
        # 4. 初始化技能状态
        for skill in agent.skills:
            session.skill_state[skill.name] = skill.get_initial_state()
        
        # 5. 持久化
        self.persistence.create_session(
            cli_id=cli_id,
            session_id=session.session_id,
            role=agent.role
        )
        
        # 6. 注册心跳
        self.monitor.register_cli(cli_id)
        
        return session
```

---

## 管理机制

### 1. Group 管理

```python
# 启动Group
group = await group_manager.create_group(
    group_name="运维监控组",
    project_dir=Path("/path/to/project"),
    agent_configs=[
        {"role": "user-interaction", "skills": ["user_handler"]},
        {"role": "fault-analyzer", "skills": ["log_analyzer", "system_monitor"]},
        {"role": "risk-analyzer", "skills": ["security_scanner"]}
    ]
)

# 获取Group状态
status = await group.get_status()

# 关闭Group
await group_manager.shutdown_group(group.group_id)
```

### 2. Agent 管理

```python
# 动态添加Agent
new_agent = await agent_manager.create_agent(
    group=group,
    role="performance-analyzer",
    capabilities=["performance_analysis"],
    skills=["profiler", "metrics_collector"]
)

# Agent崩溃恢复
await agent_manager.recover_agent(agent_id)

# 移除Agent
await agent_manager.remove_agent(agent_id)
```

### 3. Session 管理

```python
# Session生命周期
session = await session_manager.create_session(agent, cli_id="cli_001")

# 心跳更新
session_manager.monitor.heartbeat("cli_001")

# 状态保存
await session_manager.save_session(session)

# Session恢复
recovered = await session_manager.recover_session("cli_001")

# Session关闭
await session_manager.close_session(session.session_id)
```

---

## 崩溃恢复流程

```
CLI崩溃检测
     │
     ▼
┌─────────────────────────────────────┐
│ 1. Monitor检测到心跳超时            │
│    - 标记Session为crashed          │
│    - 通知Group协调器               │
└────────────────┬────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 2. 确认Agent状态                    │
│    - Agent仍存在：可以恢复         │
│    - Agent已销毁：需要重建         │
└────────────────┬────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 3. 恢复Session                      │
│    - 加载持久化的工作记忆          │
│    - 加载持久化的技能状态          │
│    - 恢复对话历史                  │
└────────────────┬────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 4. 重新启动CLI进程                  │
│    - 创建新进程                    │
│    - 注入恢复的Session             │
│    - 开始心跳监控                  │
└────────────────┬────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│ 5. 通知其他Agent                    │
│    - 广播恢复消息                  │
│    - 同步共享状态                  │
└─────────────────────────────────────┘
```

---

## 配置示例

```json
{
  "group": {
    "name": "运维监控组",
    "project_dir": "/path/to/project",
    "runtime_dir": "~/.dfecrab",
    "auto_recovery": true,
    "heartbeat_timeout": 60
  },
  
  "agents": [
    {
      "role": "user-interaction",
      "description": "负责与用户交互",
      "capabilities": ["user_interaction", "query_handler"],
      "skills": ["user_handler", "query_parser"],
      "model": "deepseek-v3.1"
    },
    {
      "role": "fault-analyzer",
      "description": "负责分析故障",
      "capabilities": ["fault_detection", "log_analysis"],
      "skills": ["log_analyzer", "system_monitor", "alert_handler"],
      "model": "deepseek-v3.1"
    },
    {
      "role": "risk-analyzer",
      "description": "负责分析风险",
      "capabilities": ["risk_assessment", "security_scan"],
      "skills": ["security_scanner", "compliance_checker"],
      "model": "deepseek-v3.1"
    }
  ],
  
  "shared_memory": {
    "project_memory": "./DFECRAB.md",
    "auto_sync": true,
    "sync_interval": 60
  }
}
```

---

## 目录结构

```
~/.dfecrab/
├── groups/
│   └── group_xxx/
│       ├── group.json           # Group配置
│       ├── agents.json          # Agent列表
│       └── shared/
│           └── project_memory.md
├── sessions/
│   ├── user-interaction_xxx/
│   │   ├── session.json
│   │   ├── working_memory.json
│   │   └── skill_state.json
│   ├── fault-analyzer_xxx/
│   │   └── ...
│   └── risk-analyzer_xxx/
│       └── ...
└── agents/
    ├── user-interaction/
    │   ├── config.json
    │   └── skills/
    ├── fault-analyzer/
    │   └── ...
    └── risk-analyzer/
        └── ...
```
