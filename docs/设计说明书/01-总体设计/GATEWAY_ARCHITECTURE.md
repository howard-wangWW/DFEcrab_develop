# Gateway 架构设计

## 一、场景分析

### 1.1 业务场景

```
电网运维监控系统
├── Session管理和调度（后台常驻）
│   └── 负责所有Session的生命周期管理
│
├── 电网运行信息监视（定时启动）
│   ├── 每小时健康检查
│   ├── 每15分钟数据采集
│   └── 每日报告生成
│
├── 故障分析（触发启动）
│   ├── 主网故障分析
│   ├── 配网故障分析
│   ├── 低压故障分析
│   └── 生成故障报告
│
├── 风险分析（触发启动）
│   ├── 主网风险分析 - 输电网络风险评估
│   ├── 配网风险分析 - 配电网络风险评估
│   ├── 低压风险分析 - 低压电网风险评估
│   └── 综合风险评估 - 汇总各层风险
│
└── 信息查询和发布（后台/触发）
    ├── 接收用户查询请求
    ├── 发布分析结果
    └── 推送告警信息
```

### 1.2 部署架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                          服务器集群                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  节点A (192.168.1.10)          节点B (192.168.1.11)                │
│  ┌─────────────────┐          ┌─────────────────┐                  │
│  │ dfecrab-cli     │          │ dfecrab-cli     │                  │
│  │ ┌─────────────┐ │          │ ┌─────────────┐ │                  │
│  │ │ session_mgr │ │          │ │ fault_analyze│ │                  │
│  │ │ (常驻)      │ │          │ │ (触发)      │ │                  │
│  │ └─────────────┘ │          │ └─────────────┘ │                  │
│  │ ┌─────────────┐ │          │ ┌─────────────┐ │                  │
│  │ │ monitor     │ │          │ │ risk_analyze │ │                  │
│  │ │ (定时)      │ │          │ │ (触发)      │ │                  │
│  │ └─────────────┘ │          │ └─────────────┘ │                  │
│  └─────────────────┘          └─────────────────┘                  │
│                                                                     │
│  节点C (192.168.1.12)          节点D (192.168.1.13)                │
│  ┌─────────────────┐          ┌─────────────────┐                  │
│  │ dfecrab-cli     │          │ dfecrab-cli     │                  │
│  │ ┌─────────────┐ │          │ ┌─────────────┐ │                  │
│  │ │ info_query  │ │          │ │ monitor_standby│ │                │
│  │ │ (后台/触发) │ │          │ │ (定时-备)   │ │                  │
│  │ └─────────────┘ │          │ └─────────────┘ │                  │
│  │ ┌─────────────┐ │          │ ┌─────────────┐ │                  │
│  │ │ fault_standby│ │          │ │ risk_standby │ │                 │
│  │ │ (触发-备)   │ │          │ │ (触发-备)   │ │                  │
│  │ └─────────────┘ │          │ └─────────────┘ │                  │
│  └─────────────────┘          └─────────────────┘                  │
│                                                                     │
│                         ┌─────────────┐                            │
│                         │   Gateway   │  ← 统一入口                 │
│                         │  (主备部署) │                            │
│                         └──────┬──────┘                            │
│                                │                                    │
└────────────────────────────────┼────────────────────────────────────┘
                                 │
                                 ▼
                          用户/外部系统
```

## 二、核心架构

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Gateway 层                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  DFEcrabGateway                                          │   │
│  │  ├── 调度器 (Scheduler)      - 定时/触发任务调度         │   │
│  │  ├── 注册中心 (Registry)     - CLI注册和发现             │   │
│  │  ├── 路由器 (Router)         - 消息路由和负载均衡         │   │
│  │  ├── 执行器 (Executor)       - Session生命周期管理        │   │
│  │  └── 监控器 (Monitor)        - 健康检查和告警             │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 │ WebSocket / HTTP
                                 │
┌─────────────────────────────────────────────────────────────────┐
│                         CLI 层                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  DFEcrabCLI (运行在各节点上)                             │   │
│  │  ├── 连接管理              - 连接Gateway，断线重连       │   │
│  │  ├── 任务执行              - 执行Gateway下发的任务       │   │
│  │  ├── 状态上报              - 心跳、负载、结果上报        │   │
│  │  └── 本地记忆              - 独立工作记忆 + 共享项目记忆 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 │ 文件系统 / 数据库
                                 │
┌─────────────────────────────────────────────────────────────────┐
│                        存储层                                    │
│  ├── 项目记忆 (共享)          ~/.dfecrab/memory/               │
│  ├── Session状态              ~/.dfecrab/sessions/              │
│  ├── 执行日志                 ~/.dfecrab/logs/                  │
│  └── 配置文件                 ~/.dfecrab/config/                │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 组件职责

| 组件 | 职责 | 关键接口 |
|------|------|----------|
| **Gateway** | 统一入口，集中管理 | `/api/*`, `/ws` |
| **Scheduler** | 定时/触发任务调度 | `schedule()`, `trigger()` |
| **Registry** | CLI注册和发现 | `register()`, `discover()` |
| **Router** | 消息路由 | `route()`, `broadcast()` |
| **Executor** | Session生命周期 | `start()`, `stop()`, `restart()` |
| **CLI** | 任务执行器 | `execute()`, `report()` |

## 三、Gateway 设计

### 3.1 核心类

```python
# src/core/gateway/__init__.py

class DFEcrabGateway:
    """
    DFEcrab Gateway
    
    统一入口，负责：
    - Session调度（定时、触发、常驻）
    - CLI注册和发现
    - 消息路由和广播
    - Session生命周期管理
    - 健康监控和故障转移
    """
    
    def __init__(self, config: GatewayConfig):
        self.config = config
        
        # 核心组件
        self.scheduler = SessionScheduler()
        self.registry = CLIRegistry()
        self.router = MessageRouter()
        self.executor = SessionExecutor()
        self.monitor = HealthMonitor()
        
        # 状态管理
        self.sessions: Dict[str, SessionInfo] = {}
        self.running = False
    
    async def start(self):
        """启动Gateway"""
        # 1. 加载配置
        await self._load_config()
        
        # 2. 启动调度器
        await self.scheduler.start()
        
        # 3. 启动健康监控
        await self.monitor.start()
        
        # 4. 启动HTTP/WebSocket服务
        await self._start_server()
        
        self.running = True
    
    async def stop(self):
        """停止Gateway"""
        self.running = False
        await self.scheduler.stop()
        await self.monitor.stop()
        # 通知所有CLI断开
    
    # ==================== 核心API ====================
    
    async def schedule_session(self, session_id: str, schedule: ScheduleConfig):
        """调度Session"""
        # 1. 选择CLI执行
        cli = await self._select_cli(session_id)
        
        # 2. 注册到调度器
        self.scheduler.register(session_id, schedule, cli)
    
    async def trigger_session(self, session_id: str, event: str, data: dict):
        """触发Session"""
        # 1. 查找目标Session
        session = self.sessions.get(session_id)
        
        # 2. 选择CLI
        cli = await self._select_cli(session_id)
        
        # 3. 下发任务
        await self._dispatch_task(cli, session_id, {
            "type": "triggered",
            "event": event,
            "data": data
        })
    
    async def _select_cli(self, session_id: str) -> str:
        """
        选择CLI执行Session
        
        策略：
        - 常驻Session：选择已注册的CLI
        - 定时Session：负载均衡选择可用CLI
        - 触发Session：选择空闲CLI或启动新CLI
        """
        session = self.sessions[session_id]
        
        if session.session_type == "resident":
            # 常驻Session，返回已分配的CLI
            return session.assigned_cli
        
        # 负载均衡选择
        return self.registry.select_available(
            agent_id=session.agent_id,
            capabilities=session.capabilities
        )
    
    async def _dispatch_task(self, cli_id: str, session_id: str, task: dict):
        """下发任务到CLI"""
        cli = self.registry.get(cli_id)
        
        if cli.status != "online":
            raise CLIOfflineError(f"CLI {cli_id} is offline")
        
        # 通过WebSocket发送任务
        await self.router.send(cli.websocket, {
            "type": "task",
            "session_id": session_id,
            "task": task
        })
```

### 3.2 CLI注册中心

```python
# src/core/gateway/registry.py

@dataclass
class CLIInfo:
    """CLI信息"""
    cli_id: str
    node_id: str                    # 节点标识
    agent_id: str                   # Agent类型
    capabilities: List[str]         # 能力列表
    sessions: List[str]             # 承载的Session
    
    status: str = "offline"         # offline, online, busy
    load: int = 0                   # 当前负载
    last_heartbeat: datetime = None
    websocket: WebSocket = None
    
    # 资源信息
    cpu_usage: float = 0.0
    memory_usage: float = 0.0


class CLIRegistry:
    """
    CLI注册中心
    
    职责：
    - CLI注册和注销
    - CLI发现和选择
    - 心跳监控
    """
    
    def __init__(self):
        self._clis: Dict[str, CLIInfo] = {}
        self._by_agent: Dict[str, List[str]] = {}  # agent_id -> [cli_ids]
        self._by_capability: Dict[str, List[str]] = {}  # capability -> [cli_ids]
    
    async def register(self, cli_info: CLIInfo) -> bool:
        """注册CLI"""
        cli_id = cli_info.cli_id
        
        # 存储CLI信息
        self._clis[cli_id] = cli_info
        cli_info.status = "online"
        cli_info.last_heartbeat = datetime.now()
        
        # 建立索引
        agent_id = cli_info.agent_id
        if agent_id not in self._by_agent:
            self._by_agent[agent_id] = []
        self._by_agent[agent_id].append(cli_id)
        
        for cap in cli_info.capabilities:
            if cap not in self._by_capability:
                self._by_capability[cap] = []
            self._by_capability[cap].append(cli_id)
        
        logger.info(f"[Registry] CLI注册成功: {cli_id} (agent={agent_id})")
        return True
    
    async def unregister(self, cli_id: str):
        """注销CLI"""
        if cli_id not in self._clis:
            return
        
        cli = self._clis.pop(cli_id)
        
        # 清理索引
        if cli.agent_id in self._by_agent:
            self._by_agent[cli.agent_id].remove(cli_id)
        
        for cap in cli.capabilities:
            if cap in self._by_capability:
                self._by_capability[cap].remove(cli_id)
        
        logger.info(f"[Registry] CLI注销: {cli_id}")
    
    def select_available(
        self, 
        agent_id: str = None,
        capabilities: List[str] = None,
        strategy: str = "least_load"
    ) -> Optional[str]:
        """
        选择可用的CLI
        
        Args:
            agent_id: Agent类型
            capabilities: 能力需求
            strategy: 选择策略 (least_load, round_robin, random)
            
        Returns:
            CLI ID
        """
        candidates = []
        
        # 按Agent筛选
        if agent_id:
            candidates = self._by_agent.get(agent_id, [])
        # 按能力筛选
        elif capabilities:
            for cap in capabilities:
                cap_clis = self._by_capability.get(cap, [])
                if not candidates:
                    candidates = cap_clis[:]
                else:
                    candidates = [c for c in candidates if c in cap_clis]
        else:
            candidates = list(self._clis.keys())
        
        # 过滤在线且空闲的
        candidates = [
            c for c in candidates 
            if self._clis[c].status in ["online", "busy"]
        ]
        
        if not candidates:
            return None
        
        # 选择策略
        if strategy == "least_load":
            return min(candidates, key=lambda c: self._clis[c].load)
        elif strategy == "round_robin":
            # TODO: 实现轮询
            return candidates[0]
        else:
            import random
            return random.choice(candidates)
    
    def get_by_agent(self, agent_id: str) -> List[CLIInfo]:
        """获取指定Agent的所有CLI"""
        cli_ids = self._by_agent.get(agent_id, [])
        return [self._clis[cid] for cid in cli_ids]
    
    def get_status(self) -> Dict:
        """获取注册中心状态"""
        return {
            "total_clis": len(self._clis),
            "online_clis": sum(1 for c in self._clis.values() if c.status == "online"),
            "by_agent": {
                agent: len(clis) 
                for agent, clis in self._by_agent.items()
            }
        }
```

### 3.3 消息路由器

```python
# src/core/gateway/router.py

class MessageRouter:
    """
    消息路由器
    
    职责：
    - 点对点消息
    - 广播消息
    - 主题订阅/发布
    """
    
    def __init__(self):
        self._subscriptions: Dict[str, List[str]] = {}  # topic -> [cli_ids]
    
    async def send(self, websocket: WebSocket, message: dict):
        """发送消息"""
        await websocket.send_json(message)
    
    async def send_to_cli(self, cli_id: str, message: dict, registry: CLIRegistry):
        """发送消息到指定CLI"""
        cli = registry.get(cli_id)
        if cli and cli.websocket:
            await self.send(cli.websocket, message)
    
    async def broadcast(
        self, 
        message: dict, 
        registry: CLIRegistry,
        exclude: List[str] = None
    ):
        """广播消息到所有CLI"""
        exclude = exclude or []
        
        for cli_id, cli in registry._clis.items():
            if cli_id in exclude:
                continue
            if cli.websocket:
                try:
                    await self.send(cli.websocket, message)
                except Exception as e:
                    logger.error(f"广播失败: {cli_id} - {e}")
    
    async def publish(
        self, 
        topic: str, 
        message: dict,
        registry: CLIRegistry
    ):
        """发布消息到主题"""
        subscribers = self._subscriptions.get(topic, [])
        
        for cli_id in subscribers:
            await self.send_to_cli(cli_id, message, registry)
    
    async def subscribe(self, cli_id: str, topic: str):
        """CLI订阅主题"""
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        
        if cli_id not in self._subscriptions[topic]:
            self._subscriptions[topic].append(cli_id)
    
    async def unsubscribe(self, cli_id: str, topic: str):
        """取消订阅"""
        if topic in self._subscriptions:
            if cli_id in self._subscriptions[topic]:
                self._subscriptions[topic].remove(cli_id)
```

## 四、CLI 设计

### 4.1 CLI核心类

```python
# src/core/cli/__init__.py

class DFEcrabCLI:
    """
    DFEcrab CLI
    
    运行在各节点上，负责：
    - 连接Gateway
    - 执行下发的任务
    - 上报状态和结果
    - 管理本地记忆
    """
    
    def __init__(self, config: CLIConfig):
        self.config = config
        
        # 身份信息
        self.cli_id = config.cli_id
        self.agent_id = config.agent_id
        self.node_id = config.node_id
        
        # 连接
        self.gateway_url = config.gateway_url
        self.websocket: WebSocket = None
        
        # 记忆
        self.memory_manager = FourLayerMemoryManager(
            base_dir=config.project_dir,
            runtime_dir=config.runtime_dir
        )
        
        # 工具和技能
        self.tool_executor = ToolExecutor()
        self.skill_manager = SkillManager()
        
        # 状态
        self.status = "offline"
        self.current_task = None
    
    async def start(self):
        """启动CLI"""
        # 1. 加载记忆
        await self.memory_manager.load_all()
        
        # 2. 连接Gateway
        await self._connect_gateway()
        
        # 3. 注册
        await self._register()
        
        # 4. 开始接收任务
        await self._listen_tasks()
    
    async def _connect_gateway(self):
        """连接Gateway"""
        import websockets
        
        retry_count = 0
        max_retry = self.config.max_retry
        
        while retry_count < max_retry:
            try:
                self.websocket = await websockets.connect(
                    f"{self.gateway_url}/ws",
                    extra_headers={
                        "X-CLI-ID": self.cli_id,
                        "X-Agent-ID": self.agent_id
                    }
                )
                logger.info(f"[CLI] 连接Gateway成功: {self.gateway_url}")
                return
                
            except Exception as e:
                retry_count += 1
                logger.warning(f"[CLI] 连接失败 ({retry_count}/{max_retry}): {e}")
                await asyncio.sleep(5 * retry_count)
        
        raise ConnectionError("无法连接Gateway")
    
    async def _register(self):
        """注册到Gateway"""
        await self.websocket.send_json({
            "type": "register",
            "cli_id": self.cli_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "capabilities": self.config.capabilities,
            "sessions": self.config.sessions
        })
        
        # 等待确认
        response = await self.websocket.receive_json()
        if response.get("type") != "register_ack":
            raise Exception("注册失败")
        
        self.status = "online"
        logger.info(f"[CLI] 注册成功: {self.cli_id}")
    
    async def _listen_tasks(self):
        """监听任务"""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        try:
            while True:
                message = await self.websocket.receive_json()
                
                if message["type"] == "task":
                    # 收到任务
                    asyncio.create_task(self._handle_task(message))
                    
                elif message["type"] == "broadcast":
                    # 收到广播
                    await self._handle_broadcast(message)
                    
                elif message["type"] == "subscribe":
                    # 订阅主题
                    pass
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("[CLI] 连接断开，尝试重连...")
            await self._reconnect()
    
    async def _handle_task(self, message: dict):
        """处理任务"""
        task = message["task"]
        session_id = message["session_id"]
        
        self.status = "busy"
        self.current_task = session_id
        
        try:
            # 执行任务
            result = await self._execute_task(session_id, task)
            
            # 上报结果
            await self.websocket.send_json({
                "type": "task_result",
                "cli_id": self.cli_id,
                "session_id": session_id,
                "success": True,
                "result": result
            })
            
        except Exception as e:
            # 上报错误
            await self.websocket.send_json({
                "type": "task_result",
                "cli_id": self.cli_id,
                "session_id": session_id,
                "success": False,
                "error": str(e)
            })
            
        finally:
            self.status = "online"
            self.current_task = None
    
    async def _execute_task(self, session_id: str, task: dict) -> dict:
        """
        执行任务
        
        这是CLI的核心执行逻辑
        """
        task_type = task.get("type")
        
        # 构建执行上下文
        context = {
            "session_id": session_id,
            "task": task,
            "memory": self.memory_manager,
            "tools": self.tool_executor,
            "skills": self.skill_manager
        }
        
        if task_type == "scheduled":
            # 定时任务执行
            return await self._run_scheduled_task(context)
            
        elif task_type == "triggered":
            # 触发任务执行
            return await self._run_triggered_task(context, task)
            
        elif task_type == "resident":
            # 常驻任务执行
            return await self._run_resident_task(context)
        
        return {"status": "unknown"}
    
    async def _heartbeat_loop(self):
        """心跳循环"""
        while True:
            await asyncio.sleep(self.config.heartbeat_interval)
            
            if self.websocket:
                try:
                    await self.websocket.send_json({
                        "type": "heartbeat",
                        "cli_id": self.cli_id,
                        "status": self.status,
                        "load": 1 if self.status == "busy" else 0,
                        "cpu_usage": 0,  # TODO: 实际获取
                        "memory_usage": 0
                    })
                except:
                    pass
```

## 五、Session 生命周期

### 5.1 Session状态流转

```
┌─────────────────────────────────────────────────────────────────┐
│                     Session生命周期                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────┐     启动成功      ┌─────────┐                     │
│  │ PENDING │ ───────────────► │ RUNNING │                     │
│  └─────────┘                  └────┬────┘                     │
│       │                            │                          │
│       │ 启动失败                   │                          │
│       ▼                            ▼                          │
│  ┌─────────┐              ┌─────────────────┐                │
│  │ FAILED  │              │     正常结束     │                │
│  └─────────┘              │  或             │                │
│                           │  超时/失败      │                │
│                           └────────┬────────┘                │
│                                    │                          │
│              ┌─────────────────────┼─────────────────────┐   │
│              ▼                     ▼                     ▼   │
│        ┌──────────┐         ┌──────────┐         ┌──────────┐│
│        │COMPLETED │         │ TIMEOUT  │         │ FAILED   ││
│        └──────────┘         └──────────┘         └──────────┘│
│              │                     │                     │    │
│              │                     │                     │    │
│              ▼                     ▼                     ▼    │
│        ┌──────────────────────────────────────────────────┐  │
│        │               根据配置决定：                       │  │
│        │  - 重新调度（定时任务）                           │  │
│        │  - 通知其他Session（触发任务）                    │  │
│        │  - 重试（失败任务）                               │  │
│        │  - 告警（持续失败）                               │  │
│        └──────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Session类型详解

#### 5.2.1 常驻Session

```python
# session_manager.py - 常驻后台运行

class SessionManagerSession:
    """
    Session管理器
    
    类型：常驻
    职责：
    - 监控所有Session状态
    - 处理Session启停请求
    - 协调Session间通信
    - 管理Session生命周期
    """
    
    async def run(self, context: dict):
        """持续运行"""
        while True:
            # 1. 检查所有Session状态
            status = await self._check_sessions()
            
            # 2. 处理异常Session
            for session_id, state in status.items():
                if state == "failed":
                    await self._handle_failure(session_id)
                elif state == "timeout":
                    await self._handle_timeout(session_id)
            
            # 3. 处理待处理的请求
            requests = await self._get_pending_requests()
            for req in requests:
                await self._process_request(req)
            
            # 4. 上报状态
            await self._report_status()
            
            await asyncio.sleep(10)  # 每10秒检查一次
```

#### 5.2.2 定时Session

```python
# monitor.py - 定时启动

class GridMonitorSession:
    """
    电网运行信息监视
    
    类型：定时
    调度：
    - 每小时健康检查
    - 每15分钟数据采集
    - 每日报告生成
    """
    
    async def run(self, context: dict, task: dict):
        """执行定时任务"""
        schedule_type = task.get("schedule_type")
        
        if schedule_type == "health_check":
            return await self._do_health_check(context)
        elif schedule_type == "data_collect":
            return await self._do_data_collect(context)
        elif schedule_type == "daily_report":
            return await self._do_daily_report(context)
    
    async def _do_health_check(self, context):
        """健康检查"""
        results = []
        
        # 检查各系统状态
        for system in ["scada", "ems", "gis"]:
            status = await self._check_system(system)
            results.append({"system": system, "status": status})
        
        # 如果发现异常，触发故障分析
        anomalies = [r for r in results if r["status"] != "normal"]
        if anomalies:
            await self._trigger_fault_analysis(anomalies)
        
        return {
            "check_time": datetime.now().isoformat(),
            "results": results,
            "anomalies": len(anomalies)
        }
```

#### 5.2.3 触发Session

```python
# fault_analyzer.py - 触发启动

class FaultAnalyzerSession:
    """
    故障分析
    
    类型：触发
    触发条件：
    - 收到告警
    - 监视发现异常
    - 手动触发
    """
    
    async def run(self, context: dict, task: dict):
        """执行故障分析"""
        event = task.get("event")
        data = task.get("data")
        
        # 1. 收集相关信息
        context_data = await self._collect_context(event, data)
        
        # 2. 分析故障原因
        analysis = await self._analyze_fault(context_data)
        
        # 3. 生成报告
        report = await self._generate_report(analysis)
        
        # 4. 通知相关Session
        await self._notify_sessions({
            "event": "fault_analysis_completed",
            "report_id": report["id"],
            "severity": analysis["severity"]
        })
        
        return report
    
    async def _notify_sessions(self, message):
        """通知其他Session"""
        # 通过Gateway发布事件
        await context["gateway"].publish("fault_events", message)
```

## 六、通讯协议

### 6.1 WebSocket消息格式

```python
# 客户端 -> Gateway

# 注册
{
    "type": "register",
    "cli_id": "cli_001",
    "node_id": "node_192.168.1.10",
    "agent_id": "fault_analyzer",
    "capabilities": ["fault_detection", "log_analysis"],
    "sessions": ["session_fault_001"]
}

# 心跳
{
    "type": "heartbeat",
    "cli_id": "cli_001",
    "status": "online",
    "load": 0,
    "cpu_usage": 25.5,
    "memory_usage": 40.2
}

# 任务结果
{
    "type": "task_result",
    "cli_id": "cli_001",
    "session_id": "session_fault_001",
    "success": true,
    "result": {...}
}

# Gateway -> 客户端

# 任务下发
{
    "type": "task",
    "session_id": "session_fault_001",
    "task": {
        "type": "triggered",
        "event": "alert",
        "data": {"severity": "high", "source": "scada"}
    }
}

# 广播
{
    "type": "broadcast",
    "from_cli": "cli_002",
    "topic": "fault_events",
    "message": {
        "event": "fault_analysis_completed",
        "report_id": "report_001"
    }
}
```

### 6.2 HTTP API

```
Gateway HTTP API
├── /api/v1/sessions
│   ├── GET    /                 # 列出所有Session
│   ├── POST   /                 # 创建Session
│   ├── GET    /{session_id}     # 获取Session详情
│   ├── PUT    /{session_id}     # 更新Session
│   └── DELETE /{session_id}     # 删除Session
│
├── /api/v1/clis
│   ├── GET    /                 # 列出所有CLI
│   ├── GET    /{cli_id}         # 获取CLI详情
│   └── POST   /{cli_id}/exec    # 让CLI执行任务
│
├── /api/v1/trigger
│   └── POST   /{event_name}     # 触发事件
│
└── /api/v1/status
    └── GET    /                 # 获取Gateway状态
```

## 七、配置示例

### 7.1 Gateway配置

```yaml
# ~/.dfecrab/config/gateway.yaml

gateway:
  id: gateway_001
  name: "DFEcrab Gateway"
  
  # 监听地址
  host: 0.0.0.0
  port: 8080
  
  # 主备配置
  ha:
    enabled: true
    role: primary  # primary, standby
    peer: gateway_002:8080
  
  # 心跳配置
  heartbeat:
    interval: 10
    timeout: 30
  
  # 调度配置
  scheduler:
    max_concurrent: 10
    retry_attempts: 3
    retry_delay: 60

# Session配置
sessions:
  # Session管理器 - 常驻
  - id: session_manager
    agent: session_manager
    type: resident
    node: node_192.168.1.10
    priority: high
    
  # 电网监视 - 定时
  - id: session_monitor
    agent: grid_monitor
    type: scheduled
    schedule:
      - cron: "0 * * * *"      # 每小时健康检查
        task: health_check
      - cron: "*/15 * * * *"   # 每15分钟数据采集
        task: data_collect
      - cron: "0 6 * * *"      # 每日6点报告
        task: daily_report
    node: node_192.168.1.10
    standby: node_192.168.1.13
    
  # 故障分析 - 触发
  - id: session_fault
    agent: fault_analyzer
    type: triggered
    trigger:
      events: ["alert", "anomaly_detected", "manual_trigger"]
      cooldown: 60
    node: node_192.168.1.11
    standby: node_192.168.1.12
    
  # 风险分析 - 触发
  - id: session_risk
    agent: risk_analyzer
    type: triggered
    trigger:
      events: ["risk_assessment", "fault_analysis_completed"]
      cooldown: 300
    node: node_192.168.1.11
    standby: node_192.168.1.13
    
  # 信息查询 - 后台/触发
  - id: session_query
    agent: info_query
    type: resident
    capabilities: ["query", "publish"]
    node: node_192.168.1.12

# Agent定义
agents:
  - id: session_manager
    name: "Session管理器"
    description: "负责所有Session的生命周期管理"
    capabilities: ["session_mgmt", "coordination"]
    
  - id: grid_monitor
    name: "电网监视"
    description: "定时监视电网运行状态"
    capabilities: ["monitoring", "data_collect", "alert"]
    
  - id: fault_analyzer
    name: "故障分析"
    description: "分析和诊断电网故障"
    capabilities: ["fault_detection", "log_analysis", "diagnosis"]
    
  - id: risk_analyzer
    name: "风险分析"
    description: "评估电网运行风险"
    capabilities: ["risk_assessment", "prediction", "warning"]
    
  - id: info_query
    name: "信息查询"
    description: "处理查询请求和发布信息"
    capabilities: ["query", "publish", "notification"]
```

### 7.2 CLI配置

```yaml
# ~/.dfecrab/config/cli.yaml (在节点A上)

cli:
  id: cli_node_a
  node_id: node_192.168.1.10
  gateway_url: ws://gateway:8080/ws
  
  # 心跳
  heartbeat_interval: 10
  
  # 重连
  max_retry: 10
  retry_delay: 5
  
  # 资源限制
  max_concurrent_tasks: 3

agent:
  id: session_manager
  capabilities:
    - session_mgmt
    - coordination
    - health_check

sessions:
  - session_manager    # 常驻
  - session_monitor    # 定时

# 本地配置
paths:
  project_dir: /opt/dfecrab/project
  runtime_dir: ~/.dfecrab
  logs: ~/.dfecrab/logs
```

## 八、部署架构

### 8.1 单Gateway部署

```
                    Gateway (主)
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    节点A             节点B             节点C
   (CLI-1)          (CLI-2)          (CLI-3)
```

### 8.2 高可用部署

```
         ┌─────────────────────────────────┐
         │         负载均衡器              │
         └───────────────┬─────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
    Gateway (主)                    Gateway (备)
    192.168.1.100                   192.168.1.101
         │                               │
         └───────────────┬───────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    节点A             节点B             节点C
```

### 8.3 启动命令

```bash
# 启动Gateway
dfecrab-gateway start --config gateway.yaml

# 启动CLI (在节点A)
dfecrab-cli start --config cli_node_a.yaml

# 启动CLI (在节点B)
dfecrab-cli start --config cli_node_b.yaml

# 触发故障分析
curl -X POST http://gateway:8080/api/v1/trigger/alert \
  -H "Content-Type: application/json" \
  -d '{"severity": "high", "source": "scada", "message": "电压异常"}'
```
