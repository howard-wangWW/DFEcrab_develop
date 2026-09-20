# Group 配置和运行模型

## 一、配置层次结构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Group 配置                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  name: "运维监控组"                                       │   │
│  │  runtime_model: "active_standby"  # 主备/多活/分片       │   │
│  │  shared_memory: ./DFECRAB.md                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         ▼                    ▼                    ▼             │
│  ┌─────────────┐      ┌─────────────┐      ┌─────────────┐      │
│  │   Agent 1   │      │   Agent 2   │      │   Agent 3   │      │
│  │ role: user  │      │ role: fault │      │ role: risk  │      │
│  │             │      │             │      │             │      │
│  │ prompt:     │      │ prompt:     │      │ prompt:     │      │
│  │  "你是用户  │      │  "你是故障  │      │  "你是风险  │      │
│  │   交互专家" │      │   分析专家" │      │   分析专家" │      │
│  │             │      │             │      │             │      │
│  │ skills:     │      │ skills:     │      │ skills:     │      │
│  │  - query    │      │  - log_analyzer │   │  - security │      │
│  │  - context  │      │  - system_monitor │  │  - compliance│     │
│  │             │      │             │      │             │      │
│  │ sessions:   │      │ sessions:   │      │ sessions:   │      │
│  │  ┌───────┐  │      │  ┌───────┐  │      │  ┌───────┐  │      │
│  │  │Sess-1 │  │      │  │Sess-1 │  │      │  │Sess-1 │  │      │
│  │  │primary│  │      │  │primary│  │      │  │primary│  │      │
│  │  └───────┘  │      │  └───────┘  │      │  └───────┘  │      │
│  │  ┌───────┐  │      │  ┌───────┐  │      │             │      │
│  │  │Sess-2 │  │      │  │Sess-2 │  │      │             │      │
│  │  │standby│  │      │  │standby│  │      │             │      │
│  │  └───────┘  │      │  └───────┘  │      │             │      │
│  └─────────────┘      └─────────────┘      └─────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、运行模型

### 2.1 主备模式 (Active-Standby)

```
┌─────────────────────────────────────────┐
│           Active-Standby 模式           │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────┐      ┌─────────┐          │
│  │ Primary │ ──── │ Standby │          │
│  │ (活跃)  │ 同步 │ (备用)  │          │
│  └────┬────┘      └─────────┘          │
│       │                                 │
│       │ 故障                            │
│       ▼                                 │
│  ┌─────────┐      ┌─────────┐          │
│  │ Crashed │      │ Primary │          │
│  │ (故障)  │ ───> │ (接管)  │          │
│  └─────────┘      └─────────┘          │
│                                         │
└─────────────────────────────────────────┘

配置示例:
{
  "runtime_model": "active_standby",
  "failover": {
    "auto_failover": true,
    "heartbeat_interval": 10,
    "failover_timeout": 30
  }
}
```

### 2.2 多活模式 (Active-Active)

```
┌─────────────────────────────────────────┐
│          Active-Active 模式             │
├─────────────────────────────────────────┤
│                                         │
│       ┌──────────────────┐             │
│       │   Load Balancer  │             │
│       └────────┬─────────┘             │
│                │                        │
│    ┌───────────┼───────────┐           │
│    ▼           ▼           ▼           │
│ ┌──────┐   ┌──────┐   ┌──────┐        │
│ │Active│   │Active│   │Active│        │
│ │  1   │   │  2   │   │  3   │        │
│ └──────┘   └──────┘   └──────┘        │
│                                         │
│ 所有Session同时活跃，负载均衡           │
└─────────────────────────────────────────┘

配置示例:
{
  "runtime_model": "active_active",
  "load_balance": {
    "strategy": "round_robin",  # round_robin/least_connections/weighted
    "weights": [1, 1, 1]
  }
}
```

### 2.3 分片模式 (Sharding)

```
┌─────────────────────────────────────────┐
│            Sharding 模式                │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐   │
│  │        Shard Router             │   │
│  │  key % 3 -> shard_0/1/2        │   │
│  └─────────────────────────────────┘   │
│                │                        │
│    ┌───────────┼───────────┐           │
│    ▼           ▼           ▼           │
│ ┌──────┐   ┌──────┐   ┌──────┐        │
│ │Shard │   │Shard │   │Shard │        │
│ │  0   │   │  1   │   │  2   │        │
│ │      │   │      │   │      │        │
│ │用户A │   │用户B │   │用户C │        │
│ │用户D │   │用户E │   │用户F │        │
│ └──────┘   └──────┘   └──────┘        │
│                                         │
│ 按分片键分配，每个Session负责一部分数据  │
└─────────────────────────────────────────┘

配置示例:
{
  "runtime_model": "sharding",
  "sharding": {
    "shard_key": "user_id",
    "shard_count": 3,
    "hash_function": "modulo"
  }
}
```

---

## 三、完整配置示例

### 3.1 Group 配置

```yaml
# group.yaml

group:
  id: "group_ops_001"
  name: "运维监控组"
  description: "负责系统运维监控的Agent组"
  
  # 运行模型
  runtime_model: "active_standby"  # active_standby / active_active / sharding
  
  # 共享记忆
  shared_memory:
    project_memory: "./DFECRAB.md"
    sync_interval: 60
  
  # 主备配置
  failover:
    auto_failover: true
    heartbeat_interval: 10      # 心跳间隔（秒）
    failover_timeout: 30        # 故障转移超时（秒）
    retry_attempts: 3
  
  # 多活配置（当 runtime_model = active_active 时生效）
  load_balance:
    strategy: "round_robin"
    health_check_interval: 30
  
  # 分片配置（当 runtime_model = sharding 时生效）
  sharding:
    shard_key: "user_id"
    shard_count: 3
    hash_function: "modulo"     # modulo / consistent_hash
  
  # 监控配置
  monitoring:
    enabled: true
    metrics_interval: 60
    alert_channels: ["log", "webhook"]
```

### 3.2 Agent 配置

```yaml
# agents.yaml

agents:
  - id: "agent_user"
    role: "user-interaction"
    description: "用户交互Agent"
    
    # Agent级别提示词
    system_prompt: |
      你是一个专业的用户交互专家。
      你的职责是：
      - 理解用户需求
      - 协调其他Agent完成任务
      - 向用户反馈结果
      
      你的工作原则：
      - 友好、专业、高效
      - 主动沟通，及时反馈
    
    # 能力定义
    capabilities:
      - user_interaction
      - query_handler
      - task_coordination
    
    # 技能配置
    skills:
      - name: "query_parser"
        enabled: true
        config:
          max_query_length: 500
      
      - name: "context_manager"
        enabled: true
        config:
          context_window: 4000
      
      - name: "response_generator"
        enabled: true
        config:
          style: "professional"
    
    # Session配置
    sessions:
      - id: "session_user_primary"
        role: "primary"        # primary / standby
        # Session级别提示词（覆盖Agent提示词）
        session_prompt: |
          你是主用户交互Session。
          当前状态：主服务运行中。
          如遇故障，将自动切换到备用Session。
        
        resources:
          memory_limit: "512M"
          cpu_limit: "0.5"
        
        health_check:
          enabled: true
          interval: 10
      
      - id: "session_user_standby"
        role: "standby"
        session_prompt: |
          你是备用用户交互Session。
          当前状态：待命。
          随时准备接管主服务。

  - id: "agent_fault"
    role: "fault-analyzer"
    description: "故障分析Agent"
    
    system_prompt: |
      你是一个专业的故障分析专家。
      你的职责是：
      - 检测系统故障
      - 分析日志和指标
      - 提供诊断建议
      
      你的工作原则：
      - 快速响应
      - 准确诊断
      - 提供可执行的建议
    
    capabilities:
      - fault_detection
      - log_analysis
      - system_monitoring
    
    skills:
      - name: "log_analyzer"
        enabled: true
        config:
          log_paths: ["/var/log/system.log", "/var/log/app.log"]
          max_lines: 10000
      
      - name: "system_monitor"
        enabled: true
        config:
          metrics: ["cpu", "memory", "disk", "network"]
          interval: 5
      
      - name: "alert_handler"
        enabled: true
        config:
          alert_levels: ["warning", "error", "critical"]
    
    sessions:
      - id: "session_fault_primary"
        role: "primary"
        session_prompt: |
          你是主故障分析Session。
          负责实时监控系统状态。
      
      - id: "session_fault_standby"
        role: "standby"
        session_prompt: |
          你是备用故障分析Session。
          待命中，同步主Session状态。

  - id: "agent_risk"
    role: "risk-analyzer"
    description: "风险分析Agent"
    
    system_prompt: |
      你是一个专业的风险评估专家。
      你的职责是：
      - 识别安全风险
      - 评估风险等级
      - 提供缓解建议
      
      你的工作原则：
      - 预防为主
      - 全面评估
      - 持续改进
    
    capabilities:
      - risk_assessment
      - security_scan
      - compliance_check
    
    skills:
      - name: "security_scanner"
        enabled: true
        config:
          scan_types: ["vulnerability", "misconfiguration"]
          schedule: "daily"
      
      - name: "compliance_checker"
        enabled: true
        config:
          standards: ["CIS", "ISO27001"]
    
    sessions:
      - id: "session_risk_primary"
        role: "primary"
        session_prompt: |
          你是主风险分析Session。
          负责持续风险评估。
```

---

## 四、实现代码
