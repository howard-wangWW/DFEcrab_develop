# 单节点 Gateway 架构设计

## 一、架构概览

### 1.1 单节点部署

```
┌─────────────────────────────────────────────────────────────────────┐
│                        单台服务器                                    │
│                    (192.168.1.10 或 localhost)                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    DFEcrab Gateway                            │ │
│  │                                                               │ │
│  │   HTTP Server :8080     WebSocket Server :8080/ws            │ │
│  │         │                      │                              │ │
│  │         ▼                      ▼                              │ │
│  │   ┌─────────┐            ┌───────────┐                       │ │
│  │   │ REST API│            │  WS Handler│                       │ │
│  │   └────┬────┘            └─────┬─────┘                       │ │
│  │        │                       │                              │ │
│  │        └───────────┬───────────┘                              │ │
│  │                    │                                          │ │
│  │   ┌────────────────┴────────────────┐                        │ │
│  │   │         Gateway Core             │                        │ │
│  │   │  ┌──────────┐  ┌──────────────┐ │                        │ │
│  │   │  │Scheduler │  │   Registry   │ │                        │ │
│  │   │  └──────────┘  └──────────────┘ │                        │ │
│  │   │  ┌──────────┐  ┌──────────────┐ │                        │ │
│  │   │  │  Router  │  │   Executor   │ │                        │ │
│  │   │  └──────────┘  └──────────────┘ │                        │ │
│  │   └─────────────────────────────────┘                        │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                │                                    │
│                                │ 进程内调用                          │
│                                ▼                                    │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    CLI Processes (子进程)                      │ │
│  │                                                               │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐            │ │
│  │  │CLI-     │ │CLI-     │ │CLI-     │ │CLI-     │            │ │
│  │  │session  │ │monitor  │ │fault    │ │risk     │            │ │
│  │  │_manager │ │         │ │_main    │ │_main    │            │ │
│  │  │         │ │         │ │         │ │         │            │ │
│  │  │(常驻)   │ │(定时)   │ │(触发)   │ │(触发)   │            │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘            │ │
│  │                                                               │ │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐            │ │
│  │  │CLI-     │ │CLI-     │ │CLI-     │ │CLI-     │            │ │
│  │  │fault    │ │fault    │ │risk_    │ │risk_    │            │ │
│  │  │_trans   │ │_dist    │ │_trans   │ │_dist    │            │ │
│  │  │         │ │         │ │         │ │         │            │ │
│  │  │(触发)   │ │(触发)   │ │(触发)   │ │(触发)   │            │ │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘            │ │
│  │                                                               │ │
│  │  ┌─────────┐                                                 │ │
│  │  │CLI-     │                                                 │ │
│  │  │query    │                                                 │ │
│  │  │         │                                                 │ │
│  │  │(后台)   │                                                 │ │
│  │  └─────────┘                                                 │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                      共享存储                                  │ │
│  │  ~/.dfecrab/                                                   │ │
│  │  ├── memory/           # 四层记忆                              │ │
│  │  ├── sessions/         # Session状态                           │ │
│  │  ├── logs/             # 日志                                  │ │
│  │  └── config/           # 配置                                  │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 进程模型

```
┌─────────────────────────────────────────────────────────────────┐
│                      进程架构                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  dfecrab-gateway (主进程)                                       │
│  ├── HTTP Server (FastAPI)                                      │
│  ├── WebSocket Server                                           │
│  ├── Scheduler (调度器)                                         │
│  ├── CLI Manager (CLI生命周期管理)                              │
│  └── 共享状态管理                                                │
│                                                                 │
│  dfecrab-cli (子进程，可启动多个)                               │
│  ├── 每个 CLI 是独立进程                                        │
│  ├── 通过 stdin/stdout 或 Unix Socket 与 Gateway 通信          │
│  └── 也可以通过 WebSocket 连接                                  │
│                                                                 │
│  启动方式:                                                       │
│  dfecrab start --config config.yaml                             │
│  (同时启动 Gateway + 所有 CLI)                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 二、Session 规划

### 2.1 Session 清单

| Session ID | Agent | 类型 | 触发条件 | 说明 |
|-----------|-------|------|---------|------|
| `session_manager` | session_manager | 常驻 | 自动启动 | Session生命周期管理 |
| `monitor_health` | grid_monitor | 定时 | 每小时 | 健康检查 |
| `monitor_collect` | grid_monitor | 定时 | 每15分钟 | 数据采集 |
| `monitor_report` | grid_monitor | 定时 | 每日6点 | 日报生成 |
| `fault_main` | fault_analyzer | 触发 | 告警事件 | 故障分析主入口 |
| `fault_trans` | fault_trans | 触发 | 主网故障 | 主网故障分析 |
| `fault_dist` | fault_dist | 触发 | 配网故障 | 配网故障分析 |
| `fault_low` | fault_low | 触发 | 低压故障 | 低压故障分析 |
| `risk_main` | risk_analyzer | 触发 | 风险评估 | 风险分析主入口 |
| `risk_trans` | risk_trans | 触发 | 主网风险 | 主网风险分析 |
| `risk_dist` | risk_dist | 触发 | 配网风险 | 配网风险分析 |
| `risk_low` | risk_low | 触发 | 低压风险 | 低压风险分析 |
| `query` | info_query | 常驻 | 自动启动 | 信息查询服务 |

### 2.2 Session 协作流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    故障分析协作流程                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 告警发生                                                     │
│     │                                                           │
│     ▼                                                           │
│  ┌─────────────────┐                                            │
│  │ monitor_health  │ ──► 发现异常                               │
│  └─────────────────┘                                            │
│     │                                                           │
│     │ 触发事件: alert                                           │
│     ▼                                                           │
│  ┌─────────────────┐                                            │
│  │   fault_main    │ ──► 故障分析入口                           │
│  └─────────────────┘                                            │
│     │                                                           │
│     │ 判断故障类型                                              │
│     ├─────────────────────────────────────────┐                 │
│     │                   │                     │                 │
│     ▼                   ▼                     ▼                 │
│  ┌─────────┐      ┌─────────┐          ┌─────────┐             │
│  │fault_   │      │fault_   │          │fault_   │             │
│  │trans    │      │dist     │          │low      │             │
│  │(主网)   │      │(配网)   │          │(低压)   │             │
│  └────┬────┘      └────┬────┘          └────┬────┘             │
│       │                │                    │                   │
│       └────────────────┴────────────────────┘                   │
│                        │                                        │
│                        ▼                                        │
│               ┌─────────────────┐                               │
│               │  fault_main     │ ──► 汇总报告                  │
│               │  (汇总结果)     │                               │
│               └─────────────────┘                               │
│                        │                                        │
│                        │ 触发事件: fault_completed              │
│                        ▼                                        │
│               ┌─────────────────┐                               │
│               │   risk_main     │ ──► 风险评估                  │
│               └─────────────────┘                               │
│                        │                                        │
│                        ├─────────────────────────────────┐      │
│                        │               │                 │      │
│                        ▼               ▼                 ▼      │
│                   ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│                   │risk_    │  │risk_    │  │risk_    │        │
│                   │trans    │  │dist     │  │low      │        │
│                   └────┬────┘  └────┬────┘  └────┬────┘        │
│                        │               │            │           │
│                        └───────────────┴────────────┘           │
│                                        │                        │
│                                        ▼                        │
│                               ┌─────────────────┐               │
│                               │    query        │ ──► 发布结果  │
│                               └─────────────────┘               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 三、简化实现

### 3.1 项目结构

```
DFEcrab--/
├── src/
│   ├── gateway/                    # Gateway核心
│   │   ├── __init__.py
│   │   ├── server.py               # HTTP + WebSocket 服务
│   │   ├── scheduler.py            # 调度器
│   │   ├── registry.py             # CLI注册
│   │   ├── router.py               # 消息路由
│   │   └── executor.py             # CLI执行器
│   │
│   ├── cli/                        # CLI核心
│   │   ├── __init__.py
│   │   ├── runner.py               # CLI运行器
│   │   └── session_base.py         # Session基类
│   │
│   ├── agents/                     # Agent实现
│   │   ├── __init__.py
│   │   ├── session_manager.py      # Session管理
│   │   ├── grid_monitor.py         # 电网监视
│   │   ├── fault_analyzer.py       # 故障分析(主)
│   │   ├── fault_trans.py          # 主网故障
│   │   ├── fault_dist.py           # 配网故障
│   │   ├── fault_low.py            # 低压故障
│   │   ├── risk_analyzer.py        # 风险分析(主)
│   │   ├── risk_trans.py           # 主网风险
│   │   ├── risk_dist.py            # 配网风险
│   │   ├── risk_low.py             # 低压风险
│   │   └── info_query.py           # 信息查询
│   │
│   └── core/                       # 核心模块(已有)
│       ├── memory/                 # 记忆系统
│       ├── plugins/                # 插件系统
│       └── tools/                  # 工具系统
│
├── config/
│   ├── gateway.yaml                # Gateway配置
│   └── sessions.yaml               # Session配置
│
├── dfecrab                         # 主入口脚本
└── pyproject.toml
```

### 3.2 主入口脚本

```python
#!/usr/bin/env python3
# dfecrab

"""
DFEcrab 主入口

用法:
    dfecrab start --config config.yaml        # 启动Gateway和所有CLI
    dfecrab stop                              # 停止所有
    dfecrab status                            # 查看状态
    dfecrab trigger <event> <data>            # 触发事件
"""

import asyncio
import click
import yaml
from pathlib import Path

from src.gateway import DFEcrabGateway
from src.cli import CLIManager


@click.group()
def cli():
    """DFEcrab - 电网运维智能助手"""
    pass


@cli.command()
@click.option('--config', '-c', default='config/gateway.yaml', help='配置文件路径')
def start(config: str):
    """启动DFEcrab"""
    # 加载配置
    with open(config, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    
    # 创建Gateway
    gateway = DFEcrabGateway(cfg)
    
    # 创建CLI管理器
    cli_manager = CLIManager(gateway)
    
    async def run():
        # 启动Gateway
        await gateway.start()
        
        # 启动所有CLI
        await cli_manager.start_all(cfg['sessions'])
        
        # 等待
        try:
            while gateway.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        
        # 停止
        await cli_manager.stop_all()
        await gateway.stop()
    
    asyncio.run(run())


@cli.command()
def stop():
    """停止DFEcrab"""
    # 发送停止信号
    import requests
    requests.post("http://localhost:8080/api/v1/shutdown")


@cli.command()
def status():
    """查看状态"""
    import requests
    resp = requests.get("http://localhost:8080/api/v1/status")
    print(resp.json())


@cli.command()
@click.argument('event')
@click.argument('data', required=False, default='{}')
def trigger(event: str, data: str):
    """触发事件"""
    import requests
    import json
    
    resp = requests.post(
        f"http://localhost:8080/api/v1/trigger/{event}",
        json=json.loads(data)
    )
    print(resp.json())


if __name__ == '__main__':
    cli()
```

### 3.3 Gateway 简化实现

```python
# src/gateway/server.py

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
import asyncio
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class DFEcrabGateway:
    """
    DFEcrab Gateway (单节点版)
    
    同一进程中运行:
    - HTTP Server
    - WebSocket Server  
    - Scheduler
    - CLI Manager
    """
    
    def __init__(self, config: dict):
        self.config = config
        
        # FastAPI应用
        self.app = FastAPI(title="DFEcrab Gateway")
        
        # 核心组件
        from .scheduler import SessionScheduler
        from .registry import CLIRegistry
        from .router import MessageRouter
        from .executor import CLIExecutor
        
        self.scheduler = SessionScheduler()
        self.registry = CLIRegistry()
        self.router = MessageRouter()
        self.executor = CLIExecutor(self)
        
        # Session配置
        self.sessions: Dict[str, dict] = {}
        
        # 状态
        self.running = False
        
        # 注册路由
        self._setup_routes()
    
    def _setup_routes(self):
        """注册HTTP和WebSocket路由"""
        
        @self.app.get("/api/v1/status")
        async def get_status():
            return {
                "gateway": "running",
                "sessions": len(self.sessions),
                "clis": self.registry.get_status()
            }
        
        @self.app.get("/api/v1/sessions")
        async def list_sessions():
            return {"sessions": list(self.sessions.values())}
        
        @self.app.post("/api/v1/trigger/{event_name}")
        async def trigger_event(event_name: str, data: dict):
            result = await self.scheduler.trigger_event(event_name, data)
            return {"triggered": result}
        
        @self.app.post("/api/v1/shutdown")
        async def shutdown():
            self.running = False
            return {"status": "shutting down"}
        
        @self.app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            
            # 等待注册消息
            msg = await websocket.receive_json()
            if msg.get("type") != "register":
                await websocket.close()
                return
            
            # 注册CLI
            cli_id = msg["cli_id"]
            self.registry.register({
                "cli_id": cli_id,
                "agent_id": msg["agent_id"],
                "capabilities": msg.get("capabilities", []),
                "websocket": websocket
            })
            
            try:
                while True:
                    msg = await websocket.receive_json()
                    await self._handle_cli_message(cli_id, msg)
            except:
                self.registry.unregister(cli_id)
    
    async def _handle_cli_message(self, cli_id: str, msg: dict):
        """处理CLI消息"""
        msg_type = msg.get("type")
        
        if msg_type == "heartbeat":
            self.registry.update_heartbeat(cli_id, msg)
            
        elif msg_type == "task_result":
            await self.executor.handle_result(
                cli_id,
                msg["session_id"],
                msg["success"],
                msg.get("result"),
                msg.get("error")
            )
    
    async def start(self):
        """启动Gateway"""
        import uvicorn
        
        self.running = True
        
        # 启动调度器
        await self.scheduler.start()
        
        # 加载Session配置
        await self._load_sessions()
        
        # 启动HTTP服务
        config = uvicorn.Config(
            self.app,
            host=self.config.get("host", "0.0.0.0"),
            port=self.config.get("port", 8080),
            log_level="info"
        )
        server = uvicorn.Server(config)
        
        # 异步运行
        asyncio.create_task(server.serve())
        
        logger.info(f"[Gateway] 启动成功: http://{config.host}:{config.port}")
    
    async def stop(self):
        """停止Gateway"""
        self.running = False
        await self.scheduler.stop()
        logger.info("[Gateway] 已停止")
    
    async def _load_sessions(self):
        """加载Session配置"""
        sessions_cfg = self.config.get("sessions", [])
        
        for session_cfg in sessions_cfg:
            session_id = session_cfg["id"]
            self.sessions[session_id] = session_cfg
            
            # 注册到调度器
            if session_cfg["type"] == "scheduled":
                for schedule in session_cfg.get("schedule", []):
                    await self.scheduler.register_session(
                        session_id=session_id,
                        agent_id=session_cfg["agent"],
                        session_type="scheduled",
                        schedule_config={
                            "cron": schedule["cron"],
                            "task": schedule["task"]
                        }
                    )
            
            elif session_cfg["type"] == "triggered":
                trigger_cfg = session_cfg.get("trigger", {})
                await self.scheduler.register_session(
                    session_id=session_id,
                    agent_id=session_cfg["agent"],
                    session_type="triggered",
                    trigger_config={
                        "events": trigger_cfg.get("events", []),
                        "cooldown": trigger_cfg.get("cooldown", 60)
                    }
                )
        
        logger.info(f"[Gateway] 加载了 {len(self.sessions)} 个Session配置")
```

### 3.4 CLI Manager

```python
# src/cli/runner.py

import asyncio
import subprocess
import os
from typing import Dict, List
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class CLIManager:
    """
    CLI管理器
    
    负责启动和管理CLI子进程
    """
    
    def __init__(self, gateway):
        self.gateway = gateway
        self.processes: Dict[str, subprocess.Popen] = {}
        self.cli_configs: Dict[str, dict] = {}
    
    async def start_all(self, session_configs: List[dict]):
        """启动所有CLI"""
        
        # 按agent分组
        agents = {}
        for cfg in session_configs:
            agent_id = cfg["agent"]
            if agent_id not in agents:
                agents[agent_id] = {
                    "agent_id": agent_id,
                    "sessions": []
                }
            agents[agent_id]["sessions"].append(cfg["id"])
        
        # 启动每个agent的CLI
        for agent_id, agent_cfg in agents.items():
            await self.start_cli(agent_id, agent_cfg)
    
    async def start_cli(self, agent_id: str, config: dict):
        """启动单个CLI"""
        cli_id = f"cli_{agent_id}"
        
        # 保存配置
        self.cli_configs[cli_id] = config
        
        # 启动子进程
        # 使用 asyncio.create_subprocess_exec
        process = await asyncio.create_subprocess_exec(
            "python", "-m", "src.cli.runner",
            "--cli-id", cli_id,
            "--agent-id", agent_id,
            "--gateway-url", "ws://localhost:8080/ws",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        self.processes[cli_id] = process
        
        logger.info(f"[CLIManager] 启动CLI: {cli_id} (PID={process.pid})")
    
    async def stop_all(self):
        """停止所有CLI"""
        for cli_id, process in self.processes.items():
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
            
            logger.info(f"[CLIManager] 停止CLI: {cli_id}")
    
    def get_status(self) -> dict:
        """获取状态"""
        return {
            "total": len(self.processes),
            "running": sum(1 for p in self.processes.values() if p.returncode is None),
            "stopped": sum(1 for p in self.processes.values() if p.returncode is not None)
        }


# CLI主程序入口
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--gateway-url", default="ws://localhost:8080/ws")
    args = parser.parse_args()
    
    # 运行CLI
    from .runner import DFEcrabCLI
    
    cli = DFEcrabCLI(
        cli_id=args.cli_id,
        agent_id=args.agent_id,
        gateway_url=args.gateway_url
    )
    
    asyncio.run(cli.start())
```

### 3.5 Session 基类

```python
# src/cli/session_base.py

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


class SessionBase(ABC):
    """
    Session基类
    
    所有Agent Session继承此类
    """
    
    def __init__(self, session_id: str, agent_id: str, context: dict):
        self.session_id = session_id
        self.agent_id = agent_id
        self.context = context
        
        # 记忆
        self.memory = context.get("memory")
        
        # 工具
        self.tools = context.get("tools")
        
        # Gateway连接
        self.gateway = context.get("gateway")
    
    @abstractmethod
    async def execute(self, task: dict) -> dict:
        """
        执行任务
        
        Args:
            task: 任务数据
                - type: "scheduled" | "triggered" | "resident"
                - event: 触发事件(触发任务)
                - data: 任务数据
                
        Returns:
            执行结果
        """
        pass
    
    async def emit_event(self, event_name: str, data: dict):
        """发送事件到Gateway"""
        if self.gateway:
            await self.gateway.trigger_event(event_name, data)
    
    async def call_llm(self, prompt: str, system: str = None) -> str:
        """调用LLM"""
        # TODO: 实现LLM调用
        pass
    
    async def use_tool(self, tool_name: str, params: dict) -> dict:
        """使用工具"""
        if self.tools:
            return await self.tools.execute(tool_name, params, self.context)
        return {"error": "tools not available"}
```

### 3.6 Agent 实现示例

```python
# src/agents/fault_analyzer.py

from src.cli.session_base import SessionBase
import logging

logger = logging.getLogger(__name__)


class FaultAnalyzerSession(SessionBase):
    """
    故障分析 - 主入口
    
    职责:
    - 接收告警事件
    - 判断故障类型
    - 分发给对应的故障分析Session
    - 汇总分析结果
    """
    
    async def execute(self, task: dict) -> dict:
        """执行故障分析"""
        event = task.get("event")
        data = task.get("data", {})
        
        logger.info(f"[FaultAnalyzer] 收到事件: {event}")
        
        # 1. 分析告警，判断故障类型
        fault_type = await self._classify_fault(data)
        
        # 2. 触发对应的故障分析
        result = await self._dispatch_analysis(fault_type, data)
        
        # 3. 汇总结果
        report = await self._generate_report(result)
        
        # 4. 触发风险评估
        await self.emit_event("fault_completed", {
            "report_id": report["id"],
            "fault_type": fault_type,
            "severity": result.get("severity")
        })
        
        return report
    
    async def _classify_fault(self, data: dict) -> str:
        """判断故障类型"""
        # 使用LLM或规则判断
        source = data.get("source", "")
        voltage_level = data.get("voltage_level", "")
        
        if voltage_level >= 110:  # kV
            return "transmission"  # 主网
        elif voltage_level >= 10:
            return "distribution"  # 配网
        else:
            return "low_voltage"  # 低压
    
    async def _dispatch_analysis(self, fault_type: str, data: dict) -> dict:
        """分发到具体分析Session"""
        
        if fault_type == "transmission":
            await self.emit_event("fault_transmission", data)
            # 等待结果...
            return {"type": "transmission", "severity": "high"}
            
        elif fault_type == "distribution":
            await self.emit_event("fault_distribution", data)
            return {"type": "distribution", "severity": "medium"}
            
        else:
            await self.emit_event("fault_low_voltage", data)
            return {"type": "low_voltage", "severity": "low"}
    
    async def _generate_report(self, result: dict) -> dict:
        """生成报告"""
        import uuid
        
        return {
            "id": f"fault_report_{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now().isoformat(),
            "fault_type": result.get("type"),
            "severity": result.get("severity"),
            "status": "analyzed"
        }


# src/agents/fault_trans.py

class FaultTransSession(SessionBase):
    """
    主网故障分析
    
    专门处理输电网络(110kV+)故障
    """
    
    async def execute(self, task: dict) -> dict:
        data = task.get("data", {})
        
        # 1. 收集主网数据
        grid_data = await self._collect_transmission_data(data)
        
        # 2. 调用专业分析模型
        analysis = await self._analyze_transmission_fault(grid_data)
        
        # 3. 生成主网故障报告
        report = await self._generate_transmission_report(analysis)
        
        return report
    
    async def _collect_transmission_data(self, alert_data: dict) -> dict:
        """收集主网数据"""
        # 从SCADA、EMS等系统获取数据
        return {
            "voltage": alert_data.get("voltage"),
            "current": alert_data.get("current"),
            "frequency": alert_data.get("frequency"),
            "topology": await self._get_topology()
        }
    
    async def _analyze_transmission_fault(self, data: dict) -> dict:
        """分析主网故障"""
        # 使用LLM + 工具分析
        prompt = f"""
        作为主网故障分析专家，分析以下数据:
        {data}
        
        请提供:
        1. 故障类型判断
        2. 可能原因分析
        3. 影响范围评估
        4. 处理建议
        """
        
        analysis = await self.call_llm(prompt)
        
        return {
            "analysis": analysis,
            "confidence": 0.85
        }


# src/agents/risk_trans.py

class RiskTransSession(SessionBase):
    """
    主网风险分析
    
    专门评估输电网络风险
    """
    
    async def execute(self, task: dict) -> dict:
        data = task.get("data", {})
        
        # 1. 获取主网运行状态
        grid_status = await self._get_transmission_status()
        
        # 2. 获取最近的故障信息
        recent_faults = await self._get_recent_faults(data)
        
        # 3. 风险评估
        risk_assessment = await self._assess_risk(grid_status, recent_faults)
        
        # 4. 生成报告
        report = await self._generate_risk_report(risk_assessment)
        
        return report
```

## 四、配置文件

### 4.1 Gateway配置

```yaml
# config/gateway.yaml

gateway:
  id: gateway_001
  host: 0.0.0.0
  port: 8080
  
  # 心跳配置
  heartbeat:
    interval: 10
    timeout: 30
  
  # 调度配置
  scheduler:
    max_concurrent: 5

# Agent定义
agents:
  - id: session_manager
    name: "Session管理器"
    module: src.agents.session_manager
    
  - id: grid_monitor
    name: "电网监视"
    module: src.agents.grid_monitor
    
  - id: fault_analyzer
    name: "故障分析(主)"
    module: src.agents.fault_analyzer
    
  - id: fault_trans
    name: "主网故障分析"
    module: src.agents.fault_trans
    
  - id: fault_dist
    name: "配网故障分析"
    module: src.agents.fault_dist
    
  - id: fault_low
    name: "低压故障分析"
    module: src.agents.fault_low
    
  - id: risk_analyzer
    name: "风险分析(主)"
    module: src.agents.risk_analyzer
    
  - id: risk_trans
    name: "主网风险分析"
    module: src.agents.risk_trans
    
  - id: risk_dist
    name: "配网风险分析"
    module: src.agents.risk_dist
    
  - id: risk_low
    name: "低压风险分析"
    module: src.agents.risk_low
    
  - id: info_query
    name: "信息查询"
    module: src.agents.info_query

# Session配置
sessions:
  # 常驻Session
  - id: session_manager
    agent: session_manager
    type: resident
    
  - id: query
    agent: info_query
    type: resident
    
  # 定时Session
  - id: monitor_health
    agent: grid_monitor
    type: scheduled
    schedule:
      - cron: "0 * * * *"
        task: health_check
        
  - id: monitor_collect
    agent: grid_monitor
    type: scheduled
    schedule:
      - cron: "*/15 * * * *"
        task: data_collect
        
  - id: monitor_report
    agent: grid_monitor
    type: scheduled
    schedule:
      - cron: "0 6 * * *"
        task: daily_report
    
  # 触发Session - 故障分析
  - id: fault_main
    agent: fault_analyzer
    type: triggered
    trigger:
      events: ["alert", "anomaly_detected"]
      cooldown: 60
    
  - id: fault_trans
    agent: fault_trans
    type: triggered
    trigger:
      events: ["fault_transmission"]
      
  - id: fault_dist
    agent: fault_dist
    type: triggered
    trigger:
      events: ["fault_distribution"]
      
  - id: fault_low
    agent: fault_low
    type: triggered
    trigger:
      events: ["fault_low_voltage"]
    
  # 触发Session - 风险分析
  - id: risk_main
    agent: risk_analyzer
    type: triggered
    trigger:
      events: ["fault_completed", "risk_assessment"]
      cooldown: 300
    
  - id: risk_trans
    agent: risk_trans
    type: triggered
    trigger:
      events: ["risk_transmission"]
      
  - id: risk_dist
    agent: risk_dist
    type: triggered
    trigger:
      events: ["risk_distribution"]
      
  - id: risk_low
    agent: risk_low
    type: triggered
    trigger:
      events: ["risk_low_voltage"]
```

## 五、使用方式

### 5.1 启动

```bash
# 启动所有服务
dfecrab start --config config/gateway.yaml

# 查看状态
dfecrab status

# 输出:
# {
#   "gateway": "running",
#   "sessions": 13,
#   "clis": {"total": 11, "running": 11}
# }
```

### 5.2 触发事件

```bash
# 模拟告警
dfecrab trigger alert '{
  "source": "scada",
  "voltage_level": 110,
  "message": "110kV线路电压异常"
}'

# 手动触发风险评估
dfecrab trigger risk_assessment '{}'

# 查看Session状态
curl http://localhost:8080/api/v1/sessions
```

### 5.3 停止

```bash
dfecrab stop
```

## 六、后续扩展

当需要多节点部署时，只需：

1. **Gateway独立部署** - 运行在专用服务器
2. **CLI远程连接** - 通过网络WebSocket连接Gateway
3. **配置调整** - 修改`gateway_url`为远程地址

```yaml
# CLI配置（多节点版）
cli:
  gateway_url: ws://192.168.1.100:8080/ws  # 远程Gateway
  node_id: node_192.168.1.10
```

核心代码无需修改，只需配置变更。
