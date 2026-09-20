# CLI 管理和通讯机制

## 一、管理入口

### 1. CLI 管理命令

```bash
# 列出所有CLI
dfecrab cli list

# 查看CLI状态
dfecrab cli status <cli_id>

# 启动新CLI
dfecrab cli start --role=<role> --group=<group_id>

# 停止CLI
dfecrab cli stop <cli_id>

# 恢复崩溃的CLI
dfecrab cli recover <cli_id>

# CLI间通信
dfecrab cli send <from_cli> <to_cli> "<message>"
dfecrab cli broadcast <from_cli> "<message>"
```

### 2. Group 管理命令

```bash
# 列出所有Group
dfecrab group list

# 创建Group
dfecrab group create --name="运维组" --config=group.json

# 查看Group详情
dfecrab group status <group_id>

# 关闭Group
dfecrab group shutdown <group_id>
```

---

## 二、Session 发现机制

### 2.1 自动发现流程

```
新CLI启动
    │
    ▼
┌─────────────────────────────┐
│ 1. 向 Coordinator 注册      │
│    - cli_id, role, agent_id │
│    - 能力列表               │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ 2. 获取其他CLI列表          │
│    - coordinator.list_clis()│
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ 3. 订阅感兴趣的主题         │
│    - subscribe(topic)       │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│ 4. 发送上线通知             │
│    - broadcast("cli_online")│
└─────────────────────────────┘
```

### 2.2 发现协议

```python
# CLI注册信息
{
    "cli_id": "cli_fault_001",
    "agent_id": "fault-analyzer_xxx",
    "group_id": "group_xxx",
    "role": "fault-analyzer",
    "capabilities": ["fault_detection", "log_analysis"],
    "status": "online",
    "endpoint": "ws://localhost:6789/cli/cli_fault_001",
    "metadata": {
        "version": "4.0.0",
        "started_at": "2026-04-02T19:00:00"
    }
}
```

---

## 三、通讯机制

### 3.1 通讯方式

```
┌─────────────────────────────────────────────────────────────┐
│                     Coordinator                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                 Message Router                       │   │
│  │  - 点对点消息                                        │   │
│  │  - 广播消息                                          │   │
│  │  - 订阅/发布                                         │   │
│  │  - 请求/响应                                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
   ┌──────────┐         ┌──────────┐         ┌──────────┐
   │ CLI-1    │         │ CLI-2    │         │ CLI-3    │
   │ 消息队列  │         │ 消息队列  │         │ 消息队列  │
   └──────────┘         └──────────┘         └──────────┘
```

### 3.2 消息类型

```python
# 1. 点对点消息
{
    "type": "direct",
    "from": "cli_user_001",
    "to": "cli_fault_001",
    "topic": "task_request",
    "payload": {
        "task": "analyze_error",
        "error_log": "..."
    },
    "timestamp": "2026-04-02T19:00:00",
    "message_id": "msg_xxx"
}

# 2. 广播消息
{
    "type": "broadcast",
    "from": "cli_fault_001",
    "topic": "alert",
    "payload": {
        "alert_level": "high",
        "message": "检测到严重故障"
    }
}

# 3. 订阅/发布
{
    "type": "publish",
    "from": "cli_risk_001",
    "topic": "security_alert",
    "payload": {
        "vulnerability": "CVE-2026-xxx"
    }
}

# 4. 请求/响应
{
    "type": "request",
    "from": "cli_user_001",
    "to": "cli_fault_001",
    "topic": "get_status",
    "request_id": "req_xxx",
    "payload": {}
}

# 响应
{
    "type": "response",
    "from": "cli_fault_001",
    "to": "cli_user_001",
    "request_id": "req_xxx",
    "payload": {
        "status": "analyzing",
        "progress": 60
    }
}
```

### 3.3 通讯模式

#### 模式1：任务委托

```
user-interaction CLI                fault-analyzer CLI
       │                                    │
       │  1. 请求分析任务                    │
       │ ─────────────────────────────────> │
       │                                    │
       │  2. 接受任务                        │
       │ <───────────────────────────────── │
       │                                    │
       │  3. 进度更新                        │
       │ <───────────────────────────────── │
       │                                    │
       │  4. 完成报告                        │
       │ <───────────────────────────────── │
       │                                    │
```

#### 模式2：协作讨论

```
user-interaction     fault-analyzer      risk-analyzer
       │                   │                   │
       │  广播: 发现异常    │                   │
       │ ─────────────────>│                   │
       │                   │                   │
       │                   │ 分析结果          │
       │ <─────────────────│                   │
       │                   │                   │
       │                   │  广播: 风险评估    │
       │                   │ ─────────────────>│
       │                   │                   │
       │                   │  风险报告          │
       │                   │ <─────────────────│
       │                   │                   │
       │ 综合报告           │                   │
       │ <─────────────────│                   │
       │                   │                   │
```

#### 模式3：共享状态

```
所有CLI共享:
├── 项目记忆 (DFECRAB.md)
├── 全局变量 (shared_state.json)
├── 事件流 (event_stream)
└── 知识库 (knowledge_base)
```

---

## 四、实现代码
