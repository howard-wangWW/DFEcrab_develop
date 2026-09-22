"""
DFEcrab Gateway - gRPC版本

对外: HTTP API (6789端口，用户访问) + WebSocket (6790端口，实时通信)
对内: gRPC + Zookeeper (调用Manager和Workers)

架构:
用户 -> HTTP(6789) / WebSocket(6790) -> Gateway -> gRPC -> Manager(随机端口)
                                                           ↓
                                                      Zookeeper(2181)
                                                           ↓
                                                      Workers(随机端口)
"""

import sys
import asyncio
import json
import logging
import subprocess
import time
import re
import types
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
from datetime import datetime
from pathlib import Path

import httpx
import grpc

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.gateway.http.server import HTTPServer, HTTPMethod, RouteRule, HTTPResponse
from src.gateway.websocket.server import WebSocketServer
from src.session.history import HistoryFilter
from src.gateway.websocket.connection import WSMessageType, WSMessage, AuthContext
from src.gateway.event_bus import EventBus, get_event_bus
from src.task.task_manager import TaskManager, get_task_manager
from src.task.periodic_scheduler import PeriodicScheduler, get_periodic_scheduler
from src.gateway.grpc import dfecrab_pb2
from src.gateway.grpc import dfecrab_pb2_grpc
from src.utils.context_usage import DEFAULT_CONTEXT_LENGTH
from src.utils.api_base import normalize_api_base
from src.services.model_manager import model_manager
from src.memory.global_manager import get_global_memory_manager
from src.memory.long_term import MemoryManager
from src.utils.time_parser import parse_time, get_time_context
from src.core.errors import error_response, setup_global_exception_handlers, setup_asyncio_exception_handler, UserError
from src.gateway.chat.intent import (
    ALERT_JSON_FIELDS,
    extract_json_fragment,
    extract_json_object,
    is_alert_signal_json,
    looks_like_alert_json,
    truncate_system_prompt,
)
from src.gateway.identity import resolve_user_id
from src.gateway.lifecycle.zookeeper import set_discovery, zk_instance_agent_id
from src.gateway.agent_domain import AgentDomainMixin
from src.gateway.lifecycle.processes import ProcessLifecycleMixin
from src.gateway.lifecycle.bootstrap import BootstrapMixin
from src.gateway.sse import SSEStreamingResponse
from src.gateway.chat.display_think import DisplayThinkMixin
from src.gateway.chat.alert import AlertDomainMixin
from src.gateway.chat.session_context import SessionContextMixin
from src.gateway.chat.intent import IntentMixin
from src.gateway.chat.pipeline import ChatPipelineMixin
from src.gateway.chat.orchestration import ChatOrchestrationMixin
from src.gateway.chat.react import ReactDomainMixin
from src.gateway.llm_config import (
    context_engine_conf,
    gateway_context_length,
    gateway_llm_model,
    get_gateway_llm_config,
    resolve_agent_llm_config,
)

logger = logging.getLogger(__name__)
# Manager 独立日志（进程内执行，日志单独写 manager_agent.log）
manager_logger = logging.getLogger("dfecrab.manager")
# ReAct 独立日志（进程内执行，日志单独写 worker_agents.log）
react_logger = logging.getLogger("dfecrab.react")

# ★ 模块级常量：ReAct 事件类型映射（避免 Plan 模式引用未定义变量）
# EVENT_TYPE_MAP 已迁移至 src/gateway/chat/react.py



# 说明：`_strip_think_tags` 已随 normalize_structured_response 迁至
# src/gateway/chat/pipeline.py（唯一实现）。此处保留同名再导出，兼容历史调用方。
from src.gateway.chat.pipeline import _strip_think_tags  # noqa: E402,F401


class GatewayV2GRPC(
    BootstrapMixin,
    AgentDomainMixin,
    ProcessLifecycleMixin,
    ChatPipelineMixin,
    ChatOrchestrationMixin,
    ReactDomainMixin,
    DisplayThinkMixin,
    AlertDomainMixin,
    SessionContextMixin,
    IntentMixin,
):
    """V2 网关 - gRPC版本"""

    def __init__(self, host: str = None, port: int = None, ws_port: int = 6790, zk_hosts: str = None):
        from src.config.config_loader import config as _cfg
        if host is None:
            host = _cfg.gateway_host
        if port is None:
            port = _cfg.gateway_port
        if zk_hosts is None:
            zk_hosts = _cfg.zk_hosts
        self.host = host
        self.port = port
        self.ws_port = ws_port
        self.zk_hosts = zk_hosts
        self._http_server: Optional[HTTPServer] = None
        self._websocket_server: Optional[WebSocketServer] = None
        self._event_bus: Optional[EventBus] = None
        self._task_manager: Optional[TaskManager] = None
        self._periodic_scheduler: Optional[PeriodicScheduler] = None  # 定时任务调度器
        self._running = False
        
        # gRPC相关
        self._zk_discovery: "Optional[ZKServiceDiscovery]" = None
        self._manager_channel: Optional[grpc.Channel] = None
        self._manager_stub: Optional[dfecrab_pb2_grpc.ManagerServiceStub] = None
        
        # 历史消息过滤器
        self._history_filter = HistoryFilter()

        # 流式响应中止管理: correlation_id -> asyncio.Event
        self._active_streams: Dict[str, asyncio.Event] = {}

        # Agent 进程管理
        self._agent_processes: Dict[str, subprocess.Popen] = {}  # agent_id -> Popen

        # Agent 描述缓存（同 Manager，用于 Gateway 意图识别）
        self._agent_descriptions: Dict[str, Dict] = {}  # agent_id -> {name, desc, keywords}
        self._agents_dir_mtime: float = 0
        self._agents_dir_snapshot: Dict[str, float] = {}

        # C-2: /api/agents 结果 TTL 缓存（读 cache.agents_list_ttl_s，命中直接返回，二次访问 <10ms）
        self._agents_list_cache: Optional[Dict] = None
        self._agents_list_cache_at: float = 0.0

    @staticmethod
    def _is_alert_json_message(message: str) -> bool:
        """★ 告警 JSON 快速预检（实现见 src/gateway/chat/intent.py:looks_like_alert_json）"""
        return looks_like_alert_json(message)

    # 告警直连链路（ephemeral / judge 直连 ReAct）已迁移至 src/gateway/chat/alert.py

    def _get_gateway_llm_config(self) -> Dict:
        """全局默认 LLM 配置（current_provider + 探活 + fallback）"""
        return get_gateway_llm_config()

    def _resolve_agent_llm_config(self, agent_id: str) -> Dict:
        """Agent 固定模型优先，回落全局默认模型"""
        return resolve_agent_llm_config(agent_id)

    def _gateway_context_length(self) -> int:
        """当前网关 LLM 模型的上下文窗口大小"""
        return gateway_context_length()

    def _gateway_llm_model(self) -> str:
        """当前网关 LLM 模型名"""
        return gateway_llm_model()

    def _context_engine_conf(self) -> Dict:
        """上下文引擎配置（dfecrab.json 的 react 段，回落旧 context_engine 段）"""
        return context_engine_conf()

    # Agent 描述扫描与网关 Agent 列表构建已迁移至 src/gateway/agent_domain.py

    # 意图 JSON 解析与规则短路匹配已迁移至 src/gateway/chat/intent.py（IntentMixin）

    # display 思考流（skeleton / 分片 / 提示词 / 模型直连流）已迁移至 src/gateway/chat/display_think.py

    @staticmethod
    def _zk_instance_agent_id(inst: Dict[str, Any]) -> str:
        """从 ZK 实例记录解析 agent_id（实现见 lifecycle/zookeeper.py）"""
        return zk_instance_agent_id(inst)

    # Worker 直连调用（discover_worker_service / call_worker_grpc）已迁移至
    # src/gateway/lifecycle/zookeeper.py（gateway 侧当前无调用点）

    # 任务相关 HTTP handler 已全部迁移至 src/task/api_routes.py

    # 会话摘要与消息增强已迁移至 src/gateway/chat/session_context.py

    def _identity(self, request, fallback: str = "default") -> str:
        """从请求头解析当前用户（实现见 src/gateway/identity.py:resolve_user_id）"""
        return resolve_user_id(request, fallback)

    # Session 管理接口（列表/创建/详情/消息/删除）已迁移至
    # src/gateway/handlers/session_handler.py（HTTP 适配层，与 WS 共用 SessionService）

    # 用户管理 / Worker 列表已迁移：
    #   - users CRUD                  → src/gateway/handlers/user_handler.py
    #   - workers / services / invariants → src/gateway/handlers/worker_handler.py

    # ================================================================
    # Classic Gateway 全部路由处理器（移植）
    # ================================================================

    # Agent 管理域（元信息/索引/缓存 + agents CRUD + 默认助手 + MCP 绑定）
    # 已迁移至 src/gateway/agent_domain.py（AgentDomainMixin）

    # 子进程拉起/停止与健康巡检循环
    # 已迁移至 src/gateway/lifecycle/processes.py（ProcessLifecycleMixin）

    # 服务 & 不变量：已迁移至 src/gateway/handlers/worker_handler.py

    # 自反思接口（list / get / implement）已迁移至
    # src/gateway/handlers/reflection_handler.py

    # --- V2 任务管理 (完整 CRUD + 进度 + 审计 + 仪表盘)：已迁移至 src/task/api_routes.py ---