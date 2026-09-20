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

logger = logging.getLogger(__name__)
# Manager 独立日志（进程内执行，日志单独写 manager_agent.log）
manager_logger = logging.getLogger("dfecrab.manager")
# ReAct 独立日志（进程内执行，日志单独写 worker_agents.log）
react_logger = logging.getLogger("dfecrab.react")

# ★ 模块级常量：ReAct 事件类型映射（避免 Plan 模式引用未定义变量）
EVENT_TYPE_MAP = {
    "think_start": "think_start",
    "think": "think",
    "think_end": "think_end",
    "skill_match": "skill_match",
    "tool_call": "tool_call",
    "tool_result": "tool_result",
    "tool_start": "tool_start",
    "tool_progress": "tool_progress",
    "message_end": "message_end",
    "message_start": "message_start",
    "message": "message",           # ★ v4.1: 流式正文 chunk（ReAct 正文 token 实时转发）
    "error": "error",
    "confirmation": "confirmation",
    "plan_created": "plan_created",
    "plan_step": "plan_step",
}

# ★ JSON 告警字段（用于快速路由判断）
_ALERT_JSON_FIELDS = ("station_inside_outer", "throbNum", "alert_content", "signal_package")


def _strip_think_tags(text) -> str:
    """剥离模型输出中的思考标签（<think>...</think> 及孤立的思考前缀）。

    与 manager_agent 侧的逻辑保持一致，避免历史 content 混入思考过程。
    """
    if not text:
        return text
    import re as _re
    # 成对 <think>...</think>（含自定义标签如 <reasoning>、<thought>）
    s = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL | _re.IGNORECASE)
    s = _re.sub(r"<reasoning>.*?</reasoning>", "", s, flags=_re.DOTALL | _re.IGNORECASE)
    s = _re.sub(r"<thought>.*?</thought>", "", s, flags=_re.DOTALL | _re.IGNORECASE)
    # 孤立标签
    s = _re.sub(r"</?think>", "", s, flags=_re.IGNORECASE)
    s = _re.sub(r"</?reasoning>", "", s, flags=_re.IGNORECASE)
    s = _re.sub(r"</?thought>", "", s, flags=_re.IGNORECASE)
    return s.strip()


def normalize_structured_response(raw) -> Dict[str, Any]:
    """把 worker 可能返回的 JSON 字符串拆成结构化字段。

    背景：kunming 等智能体返回 `answer_final + other` 结构时，
    manager_agent 会把它们序列化成 JSON 字符串塞进 gRPC message，
    导致 Gateway 的 full_response 可能是纯文本也可能是 JSON 字符串，
    进而污染 session 历史的 content 字段。

    输入：raw 可以是纯文本，或形如
        '{"answer_final": "...", "other": {"recommendQuestions": "...", ...}}'
    输出：{
        "content": str,           # 最终展示纯文本（answer_final 剥离思考标签）
        "structured": dict|None,  # other 结构化字段；非结构化时为 None
        "raw": str,               # 原文，供前端调试
    }
    """
    if raw is None:
        return {"content": "", "structured": None, "raw": ""}
    raw = str(raw).strip()
    if not raw:
        return {"content": "", "structured": None, "raw": ""}

    s = raw
    if "<think>" in s or "<reasoning>" in s or "<thought>" in s:
        s = _strip_think_tags(s).strip()

    parsed = None
    if s.startswith("{") and s.endswith("}"):
        try:
            parsed = json.loads(s)
        except Exception:
            parsed = None

    if isinstance(parsed, dict) and "answer_final" in parsed:
        return {
            "content": _strip_think_tags(parsed.get("answer_final", "")),
            "structured": parsed.get("other") or {},
            "raw": raw,
        }

    return {
        "content": _strip_think_tags(raw),
        "structured": None,
        "raw": raw,
    }


def _build_execution_flow(flow_parts: List[Dict[str, Any]],
                          manager_reasoning: str = "") -> List[Dict[str, Any]]:
    """按真实时间顺序构建完整执行时间线（思考 + 工具调用与结果）。

    flow_parts 由调用方按事件接收顺序组装（think_end / tool_call / tool_result 依次追加），
    保证 execution_flow 与流式展示的顺序完全一致。供 message_end 与 session 持久化复用。

    Args:
        flow_parts: 已按时间轴排好的执行片段
        manager_reasoning: Manager 推理（如有则前置，用于解释路由/跳过原因）
    """
    flow: List[Dict[str, Any]] = list(flow_parts)
    if manager_reasoning:
        flow.insert(0, {"type": "manager_reasoning", "content": manager_reasoning})
    return flow


def _pick_latest_instances(instances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一 agent_id 有多个 ZK 实例时，只保留 registered_at 最新的一个

    历史遗留进程（如 default_localhost.localdomain_* 之类的孤儿）与当前批次进程
    会同时注册，若不去重可能返回死进程地址。
    """
    latest: Dict[str, Dict[str, Any]] = {}
    for inst in instances:
        metadata = inst.get("metadata", {})
        agent_id = (metadata.get("agent_id") if metadata else None) or inst.get("service_id", "").split("_")[0]
        cur = latest.get(agent_id)
        if not cur or inst.get("registered_at", 0) > cur.get("registered_at", 0):
            latest[agent_id] = inst
    return list(latest.values())


class SSEStreamingResponse:
    """SSE 流式响应类 — 通用版本
    
    支持传入一个 async generator，由 http_server 的 _handle_sse_streaming 迭代输出。
    也兼容旧版 agent_plugin 模式（通过 chat_stream）。
    """
    
    def __init__(self, stream_generator=None, agent_plugin=None, agent_id=None,
                 message=None, session=None, session_manager=None,
                 session_id: str = "", correlation_id: str = ""):
        """
        Args:
            stream_generator: async generator，yield dict 格式的 SSE 事件，如:
                {"type": "meta", "data": {"session_id": "xxx"}}
                {"type": "message", "data": {"content": "你好"}}
                {"type": "message_end", "data": {"full_response": "完整内容"}}
            agent_plugin: 旧版兼容，Agent 插件实例
            agent_id: 旧版兼容
            message: 旧版兼容
            session: 旧版兼容
            session_manager: 旧版兼容
            session_id: 会话ID，用于事件信封
            correlation_id: 请求关联ID，用于事件信封和流追踪
        """
        self.stream_generator = stream_generator
        self.agent_plugin = agent_plugin
        self.agent_id = agent_id
        self.message = message
        self.session = session
        self.session_manager = session_manager
        self.is_sse_response = True
        self.session_id = session_id
        self.correlation_id = correlation_id


class GatewayV2GRPC:
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
        """★ 判断消息是否是 JSON 格式的告警信号（快速路由，不依赖 Manager LLM）
        
        判断规则：
        1. 消息以 '{' 开头（是 JSON 对象）
        2. 且包含 station_inside_outer / throbNum / alert_content / signal_package 中任意字段
        """
        if not message:
            return False
        msg_stripped = message.strip()
        if not msg_stripped.startswith("{"):
            return False
        # 快速字符串匹配检查字段（比解析 JSON 更快，用于路由预检）
        return any(f in msg_stripped for f in _ALERT_JSON_FIELDS)

    async def initialize(self) -> bool:
        """初始化网关"""
        try:
            logger.info("🚀 正在初始化 DFEcrab V2 Gateway (gRPC)...")

            # 初始化Zookeeper服务发现（懒加载：缺kazoo时只在初始化阶段报错，不拖垮模块导入）
            try:
                from src.gateway.grpc.zk_registry import ZKServiceDiscovery
            except ModuleNotFoundError as e:
                if "kazoo" in str(e):
                    logger.error("❌ 缺少 kazoo 依赖，无法启用 Zookeeper 服务发现。请运行: pip install kazoo==2.11.0")
                raise
            self._zk_discovery = ZKServiceDiscovery(zk_hosts=self.zk_hosts)
            if not self._zk_discovery.connect():
                logger.error("❌ Zookeeper连接失败")
                return False
            logger.info(f"✅ Zookeeper服务发现已初始化: {self.zk_hosts}")

            # 初始化事件总线
            self._event_bus = get_event_bus()
            logger.info("✅ 事件总线已初始化")

            # 初始化任务管理器（全局单例：任务 API 与网关共享同一份内存态）
            self._task_manager = get_task_manager()
            logger.info("✅ 任务管理器已初始化")

            # 初始化定时任务调度器（全局单例，支持 cron/间隔 + 重启恢复）
            self._periodic_scheduler = get_periodic_scheduler()
            logger.info("✅ 定时任务调度器已初始化")

            # 创建 HTTP 服务器
            self._http_server = HTTPServer(
                host=self.host,
                port=self.port,
                service_locator=None,
                event_bus=self._event_bus
            )
            logger.info(f"✅ HTTP 服务器已创建: {self.host}:{self.port}")
            
            # 创建 WebSocket 服务器（心跳参数可在 config 的 ws 段配置，缺省 30s/90s）
            try:
                _ws_cfg = (_cfg or {}).get("ws", {}) or {}
            except Exception:
                _ws_cfg = {}
            self._websocket_server = WebSocketServer(
                host=self.host,
                port=self.ws_port,
                event_bus=self._event_bus,
                heartbeat_interval=int(_ws_cfg.get("heartbeat_interval", 30)),
                idle_timeout=int(_ws_cfg.get("idle_timeout", 90))
            )
            logger.info(f"✅ WebSocket 服务器已创建: {self.host}:{self.ws_port}")

            # 注册路由
            self._register_routes()

            # 注册WebSocket消息处理器
            async def handle_chat(connection, message):
                """★ G7 重构: WS 非流式聊天入口 - 协议壳

                流程：解析 WS message → 调用共享 _run_chat_pipeline → 收集 events → 返回 JSON
                
                WS 消息格式（简化）:
                  {"type":"chat", "data":{"message":"...", "session_id":"...", "user_id":"...", "agent_id":"..."}}
                  其中 session_id, user_id, agent_id 均可选；id 和 correlation_id 自动生成
                """
                try:
                    data = message.data or {}
                    user_message = data.get("message", "")
                    session_id = data.get("session_id")
                    # ★ B-2：user_id 收敛（请求体 > WS 认证上下文 > 配置默认，缺失限频告警）
                    user_id = self._resolve_user_id(
                        data.get("user_id"),
                        auth=getattr(getattr(connection, "auth_context", None), "user_id", None),
                        source="ws/chat",
                    )
                    agent_id = data.get("agent_id")
                    knowledge_base = data.get("knowledge_base")
                    kb_category = data.get("kb_category")
                    kb_top_k = data.get("kb_top_k", 5)
                    mcp = data.get("mcp")

                    # ★ 兼容 dict 格式的 message（如告警JSON），自动转为 JSON 字符串
                    if isinstance(user_message, dict):
                        user_message = json.dumps(user_message, ensure_ascii=False)

                    if not user_message:
                        return WSMessage(
                            type=WSMessageType.ERROR,
                            data=error_response(UserError(
                                message="message is required",
                                status_code=400,
                            )),
                            correlation_id=message.correlation_id
                        )

                    # ★ 复用共享核心: 收集所有 events（非流式模式）
                    events = []
                    full_response = ""
                    session_id_final = session_id
                    session_summary = ""
                    is_new_session = False

                    async for event in self._run_chat_pipeline(
                        message=user_message,
                        session_id=session_id,
                        user_id=user_id,
                        agent_id=agent_id,
                        knowledge_base=knowledge_base,
                        kb_category=kb_category,
                        kb_top_k=kb_top_k,
                        mcp=mcp,
                        streaming=False,
                    ):
                        events.append(event)
                        et = event.get("type")
                        ed = event.get("data", {})
                        if et == "message_end":
                            full_response = ed.get("full_response", ed.get("content", ""))
                        elif et == "meta":
                            session_id_final = ed.get("session_id", session_id)
                            session_summary = ed.get("session_summary", "")
                            is_new_session = ed.get("is_new_session", False)

                    return WSMessage(
                        type=WSMessageType.MESSAGE_ACK,
                        data={
                            'received': True,
                            'type': 'chat',
                            'success': True,
                            'message': full_response,
                            'session_id': session_id_final,
                            'session_summary': session_summary,
                            'is_new_session': is_new_session,
                            'events': events,
                        },
                        correlation_id=message.correlation_id
                    )
                except Exception as e:
                    logger.error(f"WebSocket chat 处理失败: {e}")
                    return WSMessage(
                        type=WSMessageType.ERROR,
                        data={
                            'success': False,
                            'error': str(e),
                            'message': str(e)
                        },
                        correlation_id=message.correlation_id
                    )
            
            async def handle_chat_stream(connection, message):
                """★ G7 重构: WS 流式聊天入口 - 协议壳

                流程：解析 WS message → 调用共享 _run_chat_pipeline → 逐事件 ws.send()
                
                WS 消息格式（简化）:
                  {"type":"chat_stream", "data":{"message":"...", "session_id":"...", "user_id":"...", "agent_id":"..."}}
                  其中 session_id, user_id, agent_id 均可选；id 和 correlation_id 自动生成
                """
                correlation_id = message.correlation_id or str(uuid.uuid4())
                # ★ 立即注册取消事件（在异步操作前），确保取消请求能第一时间被响应
                stream_cancel_event = asyncio.Event()
                if correlation_id:
                    self._active_streams[correlation_id] = stream_cancel_event
                try:
                    # 提取消息数据（协议适配）
                    data = message.data or {}
                    user_message = data.get("message", "")
                    session_id = data.get("session_id")
                    # ★ B-2：user_id 收敛（请求体 > WS 认证上下文 > 配置默认，缺失限频告警）
                    user_id = self._resolve_user_id(
                        data.get("user_id"),
                        auth=getattr(getattr(connection, "auth_context", None), "user_id", None),
                        source="ws/chat_stream",
                    )
                    agent_id = data.get("agent_id")
                    knowledge_base = data.get("knowledge_base")
                    kb_category = data.get("kb_category")
                    kb_top_k = data.get("kb_top_k", 5)
                    mcp = data.get("mcp")

                    # ★ 兼容 dict 格式的 message（如告警JSON），自动转为 JSON 字符串
                    if isinstance(user_message, dict):
                        user_message = json.dumps(user_message, ensure_ascii=False)

                    if not user_message:
                        return WSMessage(
                            type=WSMessageType.ERROR,
                            data=error_response(UserError(
                                message="message is required",
                                status_code=400,
                            )),
                            correlation_id=message.correlation_id
                        )

                    # ★ 协议壳: 调用共享生成器，逐事件 ws.send
                    final_result = None
                    async for event in self._run_chat_pipeline(
                        message=user_message,
                        session_id=session_id,
                        user_id=user_id,
                        agent_id=agent_id,
                        knowledge_base=knowledge_base,
                        kb_category=kb_category,
                        kb_top_k=kb_top_k,
                        mcp=mcp,
                    ):
                        # 安全检查：确保event是字典
                        if not isinstance(event, dict):
                            logger.warning(f"⚠️ _run_chat_pipeline 返回了非字典对象: {type(event)}，跳过")
                            continue

                        # 检查取消
                        if stream_cancel_event.is_set():
                            logger.info(f"[WS] 流被用户取消: {correlation_id}")
                            await connection.send(WSMessage(
                                type=WSMessageType.EVENT,
                                data={
                                    'event_type': 'cancelled',
                                    'data': {'message': '对话已中止'},
                                    'correlation_id': message.correlation_id
                                },
                                correlation_id=message.correlation_id
                            ))
                            break

                        event_type = event.get("type")
                        event_data = event.get("data", {})

                        # 将 SSE 事件转换为 WebSocket 事件消息
                        ws_event = WSMessage(
                            type=WSMessageType.EVENT,
                            data={
                                'event_type': event_type,
                                'data': event_data,
                                'session_id': event_data.get("session_id", session_id),
                                'correlation_id': message.correlation_id
                            },
                            correlation_id=message.correlation_id
                        )
                        await connection.send(ws_event)

                        # 记录最终结果（如果是 message_end 事件）
                        if event_type == "message_end":
                            final_result = event_data

                    # 如果流式生成器没有返回 message_end（例如出错），则发送一个错误事件
                    if not final_result:
                        await connection.send(WSMessage(
                            type=WSMessageType.ERROR,
                            data={
                                'success': False,
                                'error': '流式生成器未返回最终结果',
                                'message': '流式生成器未返回最终结果'
                            },
                            correlation_id=message.correlation_id
                        ))
                        # ★ 清理活跃流映射
                        if correlation_id:
                            self._active_streams.pop(correlation_id, None)
                        return None

                    # ★ 清理活跃流映射
                    if correlation_id:
                        self._active_streams.pop(correlation_id, None)

                    # 发送最终的 MESSAGE_ACK，包含完整结果（保持向后兼容）
                    # ★ 修复: session/session_summary/is_new_session/manager_summary_text
                    #   是 _run_chat_pipeline 的局部变量，在此作用域不可用
                    #   改为从 final_result 或已知局部变量取值
                    return WSMessage(
                        type=WSMessageType.MESSAGE_ACK,
                        data={
                            'received': True,
                            'type': 'chat_stream',
                            'success': final_result.get('success', True),
                            'message': final_result.get('full_response', ''),
                            'session_id': final_result.get('session_id', session_id or ''),
                            'user_id': user_id,
                            'session_summary': final_result.get('session_summary', ''),
                            'task_type': final_result.get('task_type', ''),
                            'agents_used': final_result.get('agents_used', []),
                            'execution_flow': final_result.get('execution_flow', []),
                            'audit_log_id': final_result.get('audit_log_id', ''),
                            'gateway_elapsed_ms': final_result.get('gateway_elapsed_ms', 0),
                            'is_new_session': final_result.get('is_new_session', False),
                            'stream_complete': True,
                            'manager_summary': final_result.get('manager_summary', ''),
                        },
                        correlation_id=message.correlation_id
                    )

                except Exception as e:
                    # ★ 清理活跃流映射
                    if correlation_id:
                        self._active_streams.pop(correlation_id, None)
                    logger.error(f"WebSocket chat_stream 处理失败: {e}")
                    return WSMessage(
                        type=WSMessageType.ERROR,
                        data={
                            'success': False,
                            'error': str(e),
                            'message': str(e)
                        },
                        correlation_id=message.correlation_id
                    )

            # ===== 添加认证处理器 =====
            async def simple_auth_handler(auth_data):
                # 测试阶段：任何 token 都通过，同时保存 user_id
                # ★ B-2：认证缺省 user_id 也收敛到同一 helper（source=ws/auth，限频告警）
                user_id = self._resolve_user_id(
                    auth_data.get("user_id"),
                    source="ws/auth",
                )
                return True, AuthContext(
                    authenticated=True,
                    user_id=user_id
                )
            
            self._websocket_server.register_auth_handler('token', simple_auth_handler)
            # ====================================

            self._websocket_server.register_message_handler(WSMessageType.CHAT, handle_chat)
            self._websocket_server.register_message_handler(WSMessageType.CHAT_STREAM, handle_chat_stream)

            # ===== 会话管理 WS 处理器（与 HTTP 共用 SessionService）=====
            from src.gateway.session_handler import SessionService

            def _ws_current_user(connection):
                """获取连接当前用户"""
                try:
                    return self._resolve_user_id(
                        None,
                        auth=connection.auth_context.user_id,
                        source="ws/current_user",
                    )
                except Exception:
                    return self._resolve_user_id(None, source="ws/current_user")

            async def handle_ws_list_sessions(connection, message):
                data = message.data or {}
                result = SessionService.list_sessions(
                    user_id=_ws_current_user(connection),
                    limit=int(data.get("limit", 50)),
                    include_empty=bool(data.get("include_empty", False))
                )
                return WSMessage(type=WSMessageType.MESSAGE_ACK, data=result,
                                 correlation_id=message.correlation_id)

            async def handle_ws_get_session(connection, message):
                data = message.data or {}
                session_id = data.get("session_id")
                if not session_id:
                    return WSMessage(type=WSMessageType.ERROR,
                                     data={'success': False, 'message': '缺少 session_id'},
                                     correlation_id=message.correlation_id)
                result = SessionService.get_session(
                    session_id=session_id,
                    current_user=_ws_current_user(connection)
                )
                return WSMessage(type=WSMessageType.MESSAGE_ACK, data=result,
                                 correlation_id=message.correlation_id)

            async def handle_ws_create_session(connection, message):
                data = message.data or {}
                result = SessionService.create_session(
                    user_id=_ws_current_user(connection),
                    topic=data.get("topic")
                )
                return WSMessage(type=WSMessageType.MESSAGE_ACK, data=result,
                                 correlation_id=message.correlation_id)

            async def handle_ws_delete_session(connection, message):
                data = message.data or {}
                session_id = data.get("session_id")
                if not session_id:
                    return WSMessage(type=WSMessageType.ERROR,
                                     data={'success': False, 'message': '缺少 session_id'},
                                     correlation_id=message.correlation_id)
                result = SessionService.delete_session(
                    session_id=session_id,
                    current_user=_ws_current_user(connection)
                )
                return WSMessage(type=WSMessageType.MESSAGE_ACK, data=result,
                                 correlation_id=message.correlation_id)

            async def handle_ws_get_session_messages(connection, message):
                data = message.data or {}
                session_id = data.get("session_id")
                if not session_id:
                    return WSMessage(type=WSMessageType.ERROR,
                                     data={'success': False, 'message': '缺少 session_id'},
                                     correlation_id=message.correlation_id)
                result = SessionService.get_session_messages(
                    session_id=session_id,
                    current_user=_ws_current_user(connection),
                    limit=int(data.get("limit", 20))
                )
                return WSMessage(type=WSMessageType.MESSAGE_ACK, data=result,
                                 correlation_id=message.correlation_id)

            self._websocket_server.register_message_handler(WSMessageType.LIST_SESSIONS, handle_ws_list_sessions)
            self._websocket_server.register_message_handler(WSMessageType.GET_SESSION, handle_ws_get_session)
            self._websocket_server.register_message_handler(WSMessageType.CREATE_SESSION, handle_ws_create_session)
            self._websocket_server.register_message_handler(WSMessageType.DELETE_SESSION, handle_ws_delete_session)
            self._websocket_server.register_message_handler(WSMessageType.GET_SESSION_MESSAGES, handle_ws_get_session_messages)
            # =====================================================

            # ===== 注册中止流式聊天处理器 =====
            async def handle_chat_cancel(connection, message):
                """处理中止流式聊天请求"""
                cancel_id = (message.data or {}).get("correlation_id") or message.correlation_id
                if not cancel_id:
                    return WSMessage(
                        type=WSMessageType.ERROR,
                        data={'success': False, 'message': '缺少 correlation_id'},
                        correlation_id=message.correlation_id
                    )
                
                cancel_event = self._active_streams.get(cancel_id)
                if cancel_event:
                    cancel_event.set()
                    logger.info(f"⏹️ [CANCEL] 已发送中止信号: correlation_id={cancel_id}")
                    return WSMessage(
                        type=WSMessageType.MESSAGE_ACK,
                        data={'success': True, 'message': '已发送中止信号'},
                        correlation_id=message.correlation_id
                    )
                else:
                    logger.info(f"⏹️ [CANCEL] 流已结束或不存在，无需取消: correlation_id={cancel_id}")
                    return WSMessage(
                        type=WSMessageType.MESSAGE_ACK,
                        data={'success': True, 'message': '流已结束，无需取消'},
                        correlation_id=message.correlation_id
                    )

            self._websocket_server.register_message_handler(WSMessageType.CHAT_CANCEL, handle_chat_cancel)
            # ====================================

            # 默认助手类型对账（agent_type=default 跟随 default_agent.agent_id，启动时对齐历史脏数据）
            self._reconcile_default_agent_type()

            # 自动启动所有 worker 类型的智能体
            await self._auto_start_worker_agents()
            # 启动 Worker 进程守护（每 30 秒检查一次，宕机自动重启）
            asyncio.ensure_future(self._worker_health_check_loop())

            # 扫描 ZK 孤儿注册（本地 agents/ 目录不存在的 Agent），便于排查残留进程
            asyncio.ensure_future(self._scan_orphan_zk_agents())

            # 孤儿附件周期清理（批次12步骤3：deleted/超TTL/无记录 落盘文件回收）
            asyncio.ensure_future(self._files_orphan_cleanup_loop())

            # 自动启动 Manager Agent
            await self._auto_start_manager_agent()

            logger.info("✅ V2 Gateway (gRPC) 初始化完成")
            return True

        except Exception as e:
            logger.error(f"❌ V2 Gateway (gRPC) 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _register_routes(self) -> None:
        """注册路由 — V2 核心路由 + Classic 全部路由"""
        if not self._http_server:
            return

        # ========================================
        # V2 核心路由（gRPC Gateway 专属）
        # ========================================

        # 健康检查
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/health", self._handle_health)
        )

        # 统一聊天接口 - 通过gRPC调用Manager
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/v2/chat", self._handle_chat,
                      required_level="write")
        )

        # 流式聊天接口 - SSE 输出
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/v2/chat/stream", self._handle_chat_stream,
                      required_level="write")
        )

        # Worker Agent 管理（新增：通过 Zookeeper 发现）
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/v2/workers", self._handle_list_workers)
        )

        # Session 管理接口
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/v2/sessions", self._handle_list_sessions)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/v2/sessions", self._handle_create_session,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/v2/sessions/{session_id}", self._handle_get_session)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/v2/sessions/{session_id}/messages", self._handle_get_session_messages)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/v2/sessions/{session_id}/usage", self._handle_get_session_usage)
        )
        # 全局 token 用量统计（纯 token 维度）
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/v2/usage/stats", self._handle_usage_stats)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/v2/sessions/deleteSession/{session_id}", self._handle_close_session,
                      required_level="write")
        )

        # 用户管理接口（仅 admin）
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/users", self._handle_list_users,
                      required_level="read", admin_only=True)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/users", self._handle_create_user,
                      required_level="write", admin_only=True)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.PUT, "/api/users/{user_id}", self._handle_update_user,
                      required_level="write", admin_only=True)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/users/{user_id}", self._handle_delete_user,
                      required_level="write", admin_only=True)
        )

        # 任务管理接口（全部收口在 src/task/api_routes.py，见 _register_task_routes）


        # ========================================
        # Classic Gateway 全部路由（移植）
        # ========================================

        # --- Agent 管理 ---
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/agents", self._handle_list_agents)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/agents", self._handle_create_agent,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/agents/{agent_id}", self._handle_get_agent)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.PUT, "/api/agents/{agent_id}", self._handle_update_agent,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/agents/{agent_id}", self._handle_delete_agent,
                      required_level="write")
        )
        # --- Agent 默认助手（全局唯一，见 config/dfecrab.json → default_agent） ---
        self._http_server._routes.append(
            RouteRule(HTTPMethod.PUT, "/api/agents/{agent_id}/default", self._handle_set_default_agent,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/agents/{agent_id}/default", self._handle_clear_default_agent,
                      required_level="write")
        )

        # --- 服务 & 不变量 ---
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/services", self._handle_list_services)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/invariants", self._handle_check_invariants)
        )

        # --- 技能管理 ---
        from src.gateway.handlers.skill_handler import SkillHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/skills", SkillHandler.list_skills)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/skills/reload", SkillHandler.reload,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/skills/search", SkillHandler.search)
        )

        # --- MCP 服务管理 ---
        # ★ 权限粒度对齐（批次13）：按 config/permissions.json 三角色模型（admin/user=write、
        #   guest=read）统一鉴权，不再 admin_only 特判；用户管理 4 接口仍保持 admin_only。
        from src.gateway.handlers.mcp_handler import MCPHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/mcp/servers", MCPHandler.list_servers,
                      required_level="read")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/mcp/servers/{name}/toggle", MCPHandler.toggle_server,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/mcp/servers/{name}/sync", MCPHandler.sync_server,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/mcp/servers/{name}/binding", MCPHandler.bind_server,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/agents/{agent_id}/mcp", MCPHandler.get_agent_mcp)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/agents/{agent_id}/mcp", MCPHandler.set_agent_mcp,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.PUT, "/api/agents/{agent_id}/mcp", self._handle_save_agent_mcp,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/mcp-admin", MCPHandler.admin_page)
        )
        # MCP 服务新增/删除/测试
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/mcp/servers", MCPHandler.add_server,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/mcp/servers/{name}", MCPHandler.delete_server,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/mcp/servers/test", MCPHandler.test_server,
                      required_level="write")
        )

        # --- 模型管理 ---
        from src.gateway.handlers.model_handler import ModelHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/models", ModelHandler.list_models)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/models/current", ModelHandler.get_current)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/models/switch", ModelHandler.switch,
                      required_level="write")
        )
        # ★ 模型 CRUD（新增/编辑/删除/启停，持久化 + 热生效）
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/models", ModelHandler.create, required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.PUT, "/api/models/{config_name}", ModelHandler.update, required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/models/{config_name}", ModelHandler.delete, required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/models/{config_name}/toggle", ModelHandler.toggle, required_level="write")
        )
        # ★ 阶段A：上下文窗口自动发现（手动触发）
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/models/{config_name}/discover", ModelHandler.discover, required_level="write")
        )

        # --- 模型回退链 ---
        from src.gateway.handlers.fallback_handler import FallbackHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/fallback/status", FallbackHandler.status)
        )

        # --- 记忆管理 ---
        from src.gateway.handlers.memory_handler import MemoryHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/stats", MemoryHandler.stats)
        )

        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/recent", MemoryHandler.recent)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/search", MemoryHandler.search)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/files", MemoryHandler.files)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/storage", MemoryHandler.storage)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/index_health", MemoryHandler.index_health)
        )
        
        # --- Agent私有记忆查询 ---
        # 必须放在 /api/agents/ 前缀之外，否则会被 GET /api/agents/{agent_id} 通配路由劫持
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/agents/{agent_id}", MemoryHandler.agent_memory)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/agents", MemoryHandler.agent_memory_summary)
        )

        # --- 用户级记忆 CRUD（先按用户分，再按三层） ---
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/memory/users", MemoryHandler.user_memories)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/memory/users/{user_id}", MemoryHandler.user_memories_create,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.PUT, "/api/memory/users/{user_id}/{mem_id}", MemoryHandler.user_memories_update,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/memory/users/{user_id}/{mem_id}", MemoryHandler.user_memories_delete,
                      required_level="write")
        )

        # --- 会话附件（批次12：文件实体化生命周期）---
        from src.gateway.handlers.file_handler import FileHandler
        # download 必须先于 /{file_id} 之外的精确路径匹配无冲突（都是全路径正则，顺序无关）
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/files/{file_id}/download", FileHandler.download)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/files", FileHandler.list_files)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/files", FileHandler.upload,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/files/{file_id}", FileHandler.delete,
                      required_level="write")
        )

        # --- 用量统计（MCP 调用次数 / Token 消耗 / 图片生成）---
        # ★ 数据源：data/usage/YYYY-MM-DD.jsonl 事件流（埋点见 src/monitoring/usage_store.py），
        #   token 当天无事件时自动回落到会话扫描（兼容埋点上线前的历史数据）。
        # ★ 注意：全部为精确路径，无通配段，注册顺序不影响匹配。
        from src.gateway.handlers.stats_handler import StatsHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/stats/daily", StatsHandler.daily)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/stats/mcp", StatsHandler.mcp)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/stats/tokens", StatsHandler.tokens)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/stats/trend", StatsHandler.trend)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/stats/overview", StatsHandler.overview)
        )

        # --- 图片生成 ---
        # ★ 顺序要求：/api/images/providers 必须在 /api/images/{image_id} 之前注册，
        #   否则会被通配路径抢先匹配（HTTP 服务器取首个命中规则）。
        from src.gateway.handlers.image_handler import ImageHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/images/generate", ImageHandler.generate,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/images/providers", ImageHandler.list_providers)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/images", ImageHandler.list_images)
        )
        # ★ 画廊页面必须注册在通配的 /api/images/{image_id} 之前，
        #   否则 "/gallery" 会被当成 image_id 命中 get_image 而返回错误。
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/images/gallery", ImageHandler.gallery)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/images/{image_id}", ImageHandler.get_image)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.DELETE, "/api/images/{image_id}", ImageHandler.delete_image,
                      required_level="write")
        )

        # --- 事件系统 ---
        from src.gateway.handlers.events_handler import EventsHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/events/search", EventsHandler.search)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/events/recent", EventsHandler.recent)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/events/stats", EventsHandler.stats)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/events/add", EventsHandler.add,
                      required_level="write")
        )

        # --- 规划系统（旧版 PlanHandler，保留兼容）---
        from src.gateway.handlers.plan_handler import PlanHandler
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/plan/current", PlanHandler.get_current)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/plan/list", PlanHandler.get_list)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/plan/next", PlanHandler.next_step,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/plan/skip", PlanHandler.skip,
                      required_level="write")
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/plan/cancel", PlanHandler.cancel,
                      required_level="write")
        )

        # ★ S3.2: 新增 plan_router 独立路由（与 PlanHandler 互补）
        from src.gateway.plan_router import get_plan_routes
        plan_routes = get_plan_routes()
        registered_plan = 0
        for route_pattern, handler in plan_routes.items():
            method_str, path = route_pattern.split(" ", 1)
            method = getattr(HTTPMethod, method_str, HTTPMethod.GET)
            # 去重：跳过已注册的同 method+path 路由（避免与 PlanHandler 等重复注册死路由）
            if any(r.method == method and r.path_pattern == path for r in self._http_server._routes):
                logger.debug(f"[Router] 跳过重复 plan 路由: {method_str} {path}")
                continue
            # 写方法（POST/DELETE/PUT/PATCH）按 plan 资源域保护
            required_level = "write" if method in (HTTPMethod.POST, HTTPMethod.DELETE, HTTPMethod.PUT, HTTPMethod.PATCH) else "read"
            self._http_server._routes.append(
                RouteRule(method, path, handler, required_level=required_level)
            )
            registered_plan += 1
        logger.info(f"[Router] Plan 路由已注册: {registered_plan} 条")

        # --- 任务调度 / 待办 / 统计（路由由任务模块统一提供，见 _register_task_routes）---

        # --- 自反思系统 ---
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/reflections", self._handle_list_reflections)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.GET, "/api/reflections/{reflection_id}", self._handle_get_reflection)
        )
        self._http_server._routes.append(
            RouteRule(HTTPMethod.POST, "/api/reflections/{reflection_id}/implement", self._handle_implement_improvements,
                      required_level="write")
        )


        # --- 任务域路由（独立模块：src/task/api_routes.py）---
        self._register_task_routes()

        logger.info(f"✅ 已注册 {len(self._http_server._routes)} 个路由")

    def _register_task_routes(self) -> None:
        """注册任务域全部 HTTP 路由（实现见 src/task/api_routes.py）。

        只做"注册"这一件事：handler 全部由任务模块提供，网关不再持有任务业务逻辑。
        写方法（POST/DELETE/PUT/PATCH）按 write 保护，其余按 read。
        """
        from src.task.api_routes import get_task_routes

        registered = 0
        skipped = 0
        for spec, handler in get_task_routes().items():
            try:
                method_str, path = spec.split(" ", 1)
                method = getattr(HTTPMethod, method_str, HTTPMethod.GET)
            except (AttributeError, ValueError):
                logger.warning(f"[Router] 非法任务路由定义: {spec}")
                continue
            # 去重：避免与其它模块重复注册同一 method+path
            if any(r.method == method and r.path_pattern == path for r in self._http_server._routes):
                skipped += 1
                continue
            required_level = "write" if method in (
                HTTPMethod.POST, HTTPMethod.DELETE, HTTPMethod.PUT, HTTPMethod.PATCH
            ) else "read"
            self._http_server._routes.append(
                RouteRule(method, path, handler, required_level=required_level)
            )
            registered += 1
        logger.info(f"[Router] 任务路由已注册: {registered} 条（跳过重复 {skipped} 条）")

    async def start(self) -> bool:
        """启动网关"""
        try:
            if self._running:
                logger.warning("⚠️ Gateway 已在运行")
                return True

            # 设置全局异常处理器
            setup_global_exception_handlers()
            setup_asyncio_exception_handler()

            self._running = True
            
            # 获取 Manager Stub（用于定时任务调度器）
            manager_stub = self._get_manager_stub()
            if manager_stub and self._periodic_scheduler:
                self._periodic_scheduler.set_manager_stub(manager_stub)
                logger.info("✅ 定时任务调度器已连接 Manager Agent")

            # 启动定时任务调度器
            if self._periodic_scheduler:
                await self._periodic_scheduler.start()
                logger.info("✅ 定时任务调度器已启动")

            await self._http_server.start()
            logger.info("✅ HTTP 服务器已启动")
            
            # 启动 WebSocket 服务器
            if self._websocket_server:
                await self._websocket_server.start()
                logger.info("✅ WebSocket 服务器已启动")
            
            logger.info("✅ V2 Gateway (gRPC) 启动成功!")
            logger.info(f"🌐 对外服务地址: {self.host}:{self.port} (HTTP)")
            logger.info(f"🌐 WebSocket 地址: {self.host}:{self.ws_port} (WebSocket)")
            logger.info(f"🔄 内部通信: gRPC via Zookeeper({self.zk_hosts})")
            return True

        except Exception as e:
            logger.error(f"❌ V2 Gateway (gRPC) 启动失败: {e}")
            self._running = False
            return False

    async def stop(self) -> None:
        """停止网关"""
        self._running = False

        # 停止定时任务调度器
        if self._periodic_scheduler:
            await self._periodic_scheduler.stop()
            logger.info("✅ 定时任务调度器已停止")

        if self._http_server:
            await self._http_server.stop()
        if self._websocket_server:
            await self._websocket_server.stop()
        if self._manager_channel:
            self._manager_channel.close()
        if self._zk_discovery:
            self._zk_discovery.close()

        # 停止所有已启动的 Agent 进程
        if self._agent_processes:
            logger.info(f"🛑 正在停止 {len(self._agent_processes)} 个 Agent 进程...")
            for agent_id, proc in list(self._agent_processes.items()):
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=2)
                        logger.info(f"   ✅ Agent [{agent_id}] 进程已停止 (PID: {proc.pid})")
                    except Exception as e:
                        logger.warning(f"   ⚠️ Agent [{agent_id}] 进程停止异常: {e}")
                del self._agent_processes[agent_id]

        logger.info("👋 V2 Gateway (gRPC) 已停止")

    def _get_manager_stub(self, force_refresh: bool = False) -> Optional[dfecrab_pb2_grpc.ManagerServiceStub]:
        """获取Manager的gRPC Stub（带服务发现+自动重连）

        Args:
            force_refresh: 是否强制刷新连接（关闭旧连接，重新发现）
        """
        # 强制刷新：关闭旧连接，清除缓存
        if force_refresh:
            if self._manager_channel:
                try:
                    self._manager_channel.close()
                except Exception:
                    pass
            self._manager_stub = None
            self._manager_channel = None

        # 如果已有连接，直接返回
        if self._manager_stub:
            return self._manager_stub
        
        # 通过Zookeeper发现Manager服务
        if not self._zk_discovery:
            logger.error("❌ Zookeeper服务发现未初始化")
            return None
        
        instances = self._zk_discovery.discover_service("manager_agent")
        
        if not instances:
            logger.error("❌ 未找到Manager Agent服务")
            return None
        
        # 选择第一个实例
        instance = instances[0]
        host = instance["host"]
        port = instance["port"]
        
        logger.info(f"🔍 发现Manager Agent: {host}:{port}")
        
        # 创建gRPC连接
        self._manager_channel = grpc.insecure_channel(f"{host}:{port}")
        self._manager_stub = dfecrab_pb2_grpc.ManagerServiceStub(self._manager_channel)
        
        return self._manager_stub

    # ========== 路由处理器 ==========

    async def _handle_health(self, request) -> Dict[str, Any]:
        """健康检查"""
        # 检查Manager Agent是否可达
        manager_healthy = False
        worker_count = 0
        try:
            stub = self._get_manager_stub()
            if stub:
                resp = await asyncio.to_thread(lambda: stub.ManagerHealth(dfecrab_pb2.HealthCheckRequest(), timeout=5.0))
                manager_healthy = resp.healthy
                worker_count = resp.worker_count
        except Exception as e:
            logger.warning(f"Manager健康检查失败: {e}")
        
        return {
            "status": "healthy",
            "gateway": "running",
            "version": "2.0.0-grpc",
            "manager_agent": "healthy" if manager_healthy else "unhealthy",
            "worker_agents": worker_count,
            "architecture": "Gateway(6789/HTTP) -> Manager(gRPC) -> Workers(gRPC) via Zookeeper",
            "zookeeper": self.zk_hosts
        }

    async def _handle_chat(self, request) -> Dict[str, Any]:
        """
        HTTP 非流式聊天接口 - ★ G5 重构: 协议壳

        流程：解析 HTTP body → 调用共享 _run_chat_pipeline → 收集所有 events → 返回 JSON
        业务逻辑全部在 _run_chat_pipeline 中，HTTP/WS 4 个入口共用。
        """
        try:
            # 1. 解析请求体（协议适配）
            body = await request.json()
            message = body.get("message", "")
            session_id = body.get("session_id")
            # ★ B-2：user_id 收敛（请求体 > X-User-Id 头 > 配置默认，缺失限频告警）
            user_id = self._resolve_user_id(
                body.get("user_id"),
                auth=request.headers.get("x-user-id"),
                source="http/chat",
            )
            agent_id = body.get("agent_id")
            knowledge_base = body.get("knowledge_base")
            kb_category = body.get("kb_category")
            kb_top_k = body.get("kb_top_k", 5)
            mcp = body.get("mcp")
            use_plan = body.get("use_plan")   # ★ 预留：plan_mode=explicit 时前端可显式开启 Plan 分步

            # ★ 兼容 dict 格式的 message（如告警JSON），自动转为 JSON 字符串
            if isinstance(message, dict):
                message = json.dumps(message, ensure_ascii=False)

            if not message:
                raise UserError(
                    message="message is required",
                    details={"field": "message", "value": ""},
                    build_hint="请提供非空的 message 参数",
                    status_code=400,
                )

            logger.info(f"📨 收到非流式聊天请求: {message[:50]}...")

            # 2. ★ 复用共享核心: 收集所有 events（非流式模式）
            events = []
            full_response = ""
            tool_calls_made = []
            matched_skills = []
            intent = "task"
            session_id_final = session_id
            session_summary = ""
            is_new_session = False

            async for event in self._run_chat_pipeline(
                message=message,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                knowledge_base=knowledge_base,
                kb_category=kb_category,
                kb_top_k=kb_top_k,
                mcp=mcp,
                streaming=False,  # ★ 非流式：跳过 think chunk，只保留 think_end
                use_plan=use_plan,
            ):
                events.append(event)
                et = event.get("type")
                ed = event.get("data", {})

                if et == "message_end":
                    full_response = ed.get("full_response", ed.get("content", ""))
                elif et == "tool_call":
                    tool_calls_made.append({
                        "tool_name": ed.get("tool_name", ""),
                        "arguments": ed.get("tool_args", ed.get("arguments", {}))
                    })
                elif et == "skill_match":
                    matched_skills = ed.get("skills", [])
                elif et == "meta":
                    session_id_final = ed.get("session_id", session_id)
                    session_summary = ed.get("session_summary", "")
                    is_new_session = ed.get("is_new_session", False)
                    intent = ed.get("intent", intent)

            # 3. 协议壳：返回 JSON
            return HTTPResponse(200).json({
                "success": True,
                "message": "ReAct 循环执行完成",
                "data": {
                    "response": full_response,
                    "session_id": session_id_final,
                    "session_summary": session_summary,
                    "is_new_session": is_new_session,
                    "intent": intent,
                    "events": events,
                    "tool_calls": tool_calls_made,
                    "matched_skills": matched_skills,
                }
            })

        except Exception as e:
            logger.error(f"[Chat] 请求处理失败: {e}")
            import traceback
            traceback.print_exc()
            err = error_response(e)
            return HTTPResponse(err.get("status_code", 500)).json(err)

    async def _handle_chat_stream(self, request):
        """
        HTTP 流式聊天接口 - SSE 输出 - G6 重构: 协议壳

        流程：解析 HTTP body -> 包装 _run_chat_pipeline 为 SSE 响应
        业务逻辑全部在 _run_chat_pipeline 中，HTTP/WS 4 个入口共用。
        """
        try:
            body = await request.json()
            message = body.get("message", "")
            session_id = body.get("session_id")
            # ★ B-2：user_id 收敛（请求体 > X-User-Id 头 > 配置默认，缺失限频告警）
            user_id = self._resolve_user_id(
                body.get("user_id"),
                auth=request.headers.get("x-user-id"),
                source="http/chat_stream",
            )
            agent_id = body.get("agent_id")
            knowledge_base = body.get("knowledge_base")
            kb_category = body.get("kb_category")
            kb_top_k = body.get("kb_top_k", 5)
            mcp = body.get("mcp")
            use_plan = body.get("use_plan")   # ★ 预留：plan_mode=explicit 时前端可显式开启 Plan 分步
            request_type = body.get("type", "chat")

            # ★ 兼容 dict 格式的 message（如告警JSON），自动转为 JSON 字符串
            if isinstance(message, dict):
                message = json.dumps(message, ensure_ascii=False)

            if not message:
                raise UserError(
                    message="message is required",
                    details={"field": "message", "value": ""},
                    build_hint="请提供非空的 message 参数",
                    status_code=400,
                )

            # ★ 允许客户端传入 correlation_id，未传则自动生成
            correlation_id = body.get("correlation_id") or str(uuid.uuid4())

            logger.info(f"SSE stream: type={request_type} {message[:50]}...")

            # ★ type=alert：短期会话，跳过 session_mgr 全套（不创建会话、不写历史），
            #   强制走 alert_judge 专属研判链路；SSE 事件流照常透传，但不进入左侧会话列表
            if request_type == "alert":
                return SSEStreamingResponse(
                    stream_generator=self._alert_ephemeral_stream(
                        alert_json=message,
                        user_id=user_id,
                        correlation_id=correlation_id,
                    ),
                    session_id="",
                    correlation_id=correlation_id,
                )

            return SSEStreamingResponse(
                stream_generator=self._run_chat_pipeline(
                    message=message,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    knowledge_base=knowledge_base,
                    kb_category=kb_category,
                    kb_top_k=kb_top_k,
                    mcp=mcp,
                    correlation_id=correlation_id,
                    use_plan=use_plan,
                ),
                session_id=session_id or "",
                correlation_id=correlation_id,
            )

        except Exception as e:
            logger.error(f"SSE parse fail: {e}")
            err = error_response(e)
            return HTTPResponse(err.get("status_code", 500)).json(err)

    # ========== 流式聊天统一准备逻辑（HTTP/WS 共用）==========

    async def _apply_asr_correction(self, text: str) -> str:
        """ASR 纠错：在所有处理之前纠正 ASR 识别错误"""
        if not text:
            return text
        try:
            import sys
            from pathlib import Path
            _skills_dir = Path(__file__).resolve().parent.parent.parent.parent / "skills" / "asr_corrector"
            if str(_skills_dir) not in sys.path:
                sys.path.insert(0, str(_skills_dir))
            import importlib
            _spec = importlib.util.spec_from_file_location(
                "asr_corrector",
                _skills_dir / "execute.py"
            )
            if _spec and _spec.loader:
                _module = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_module)
                _result = _module.execute(text=text, use_model=True)
                if _result.get("has_correction"):
                    text = _result["corrected_text"]
                    logger.info(f"✅ ASR纠错: {_result.get('correction_count')}处修正 → '{text}'")
        except Exception as e:
            logger.warning(f"⚠️ ASR纠错失败: {e}，使用原文继续处理")
        return text

    async def _prepare_stream_context(self, message: str, session_id: Optional[str],
                                      user_id: str, agent_id: Optional[str] = None
                                      ) -> Dict[str, Any]:
        """
        流式聊天的统一准备逻辑（HTTP/WS 共用）

        包含：ASR纠错 → 会话管理 → 摘要 → 历史过滤 → 增强消息 → gRPC Stub → ReAct 检查
        返回统一的上下文 dict，供 HTTP/WS 各自的协议适配层使用。
        注意：Manager 编排不在本函数中执行，由 _run_chat_pipeline 统一调用一次。
        """
        from src.session.manager import get_session_manager, ClientType

        # 1. ASR 纠错
        message = await self._apply_asr_correction(message)

        # ★ P0 快速路由预检：JSON 告警 → 直接锁定 alert_judge（不经过 Manager LLM，避免路由错误）
        if not agent_id and self._is_alert_json_message(message):
            agent_id = "alert_judge"
            react_logger.info(f"[Route] 检测到JSON告警信号，快速路由 → alert_judge")

        # 2. 会话管理
        session_mgr = get_session_manager()
        existing_session = session_mgr.get_session(session_id) if session_id else None
        
        # ★ P0-1: 反转守卫逻辑 — 优先从 session / 显式参数取 agent_id，未指定时用 "auto"
        effective_agent_id = agent_id or (
            existing_session.agent_id if existing_session else None
        ) or "auto"
        # ★ 兼容旧 ID（default → dfecrab），统一在下游解析为当前智能体
        try:
            from src.agent.agent_config import normalize_agent_id
            effective_agent_id = normalize_agent_id(effective_agent_id) or effective_agent_id
        except Exception:
            pass
        
        session = session_mgr.get_or_create_session(
            session_id=session_id,
            user_id=user_id,
            agent_id=effective_agent_id,
            client_type=ClientType.API
        )
        is_new_session = (
            (not session_id) or
            (existing_session is None) or
            (session.message_count == 0)
        )
        logger.info(f"📋 流式聊天会话: {session.id} (新会话: {is_new_session})")
        # ★ 请求参数日志：明确展示是否显式指定 agent_id（用于判断是否跳过 Manager 路由）
        logger.info(
            "[ChatRequest] session=%s user=%s agent_id=%s effective=%s explicit=%s "
            "message_len=%s new=%s",
            session.id, user_id, agent_id, effective_agent_id,
            bool(agent_id), len(message), is_new_session
        )
        session_mgr.add_message(session.id, "user", message)

        # 3. 摘要生成/更新
        session_summary = session.summary
        if is_new_session or not session.summary_generated:
            try:
                session_summary = await self._generate_session_summary(message)
                session_mgr.set_summary(session.id, session_summary)
            except Exception as e:
                logger.warning(f"⚠️ 摘要生成失败: {e}")
                session_summary = message[:50]
                session_mgr.set_summary(session.id, session_summary)
        elif not session_summary:
            # ★ 阶段C: 不再每轮用 message[:50] 覆盖已有摘要（避免摘要每轮漂移），
            #   长对话滚动摘要由 SessionSummarizer 异步更新（见 _run_chat_pipeline 沉淀处）
            session_summary = message[:50]
            session_mgr.set_summary(session.id, session_summary)

        # 4. 历史过滤
        session_history = session_mgr.get_messages_as_dicts(session.id, limit=10)
        relevant_history = self._history_filter.filter_history(
            current_msg=message,
            history=session_history
        )
        if relevant_history != session_history:
            session_history = relevant_history

        # 4.5 ★ P0 上下文自动压缩：上一轮上下文占用 ≥ 阈值（默认 85%）时同步压缩历史。
        #   做法（无损）：LLM 将「旧摘要 + 老历史」合并为新摘要（SessionSummarizer.compact_session），
        #   会话消息不删除，仅减少本次注入的原始历史条数（老上下文由摘要承担）。
        compacted = False
        ce_conf = self._context_engine_conf()
        try:
            _msgs = session_mgr.get_messages_as_dicts(session.id, limit=20)
            last_prompt = 0
            for _m in reversed(_msgs):
                if _m.get("role") == "assistant":
                    last_prompt = int((_m.get("tokens") or {}).get("prompt", 0) or 0)
                    break
            if last_prompt > 0:
                # ★ 按 agent 模型解析（若该 agent 配置了 model_config 用其窗口，否则全局）
                _llm_config = self._resolve_agent_llm_config(effective_agent_id)
                _context_length = int(_llm_config.get("context_length", DEFAULT_CONTEXT_LENGTH) or DEFAULT_CONTEXT_LENGTH)
                from src.utils.context_usage import should_compact
                if should_compact(last_prompt, _context_length, ce_conf["auto_compact_threshold"]):
                    from src.agent.llm.adapter import LLMAdapter
                    from src.memory.summarizer import SessionSummarizer
                    compacted = await SessionSummarizer().compact_session(
                        LLMAdapter(_llm_config), session.id, user_id,
                        keep_recent=ce_conf["compact_keep_recent"],
                    )
                    if compacted:
                        # 压缩成功后：摘要已更新，本次注入的历史减到最近 keep 条
                        session_summary = session.summary
                        session_history = session_history[-ce_conf["compact_keep_recent"]:]
                        react_logger.info(
                            f"[Compaction] 上下文已自动压缩: session={session.id}, "
                            f"last_prompt={last_prompt}/{_context_length} "
                            f"(threshold={ce_conf['auto_compact_threshold']})"
                        )
        except Exception as e:
            react_logger.warning(f"[Compaction] 自动压缩触发失败（降级为不压缩）: {e}")
            compacted = False

        # 5. 增强消息
        enhanced_message = self._build_enhanced_message(
            message=message,
            session_id=session.id,
            session_summary=session_summary,
            session_history=session_history
        )

        # 6. gRPC Stub
        stub = self._get_manager_stub()

        # 7. System prompt
        manager_system_prompt = self._get_agent_system_prompt("manager_agent")

        # 8. ReAct 检查（HTTP/WS 对齐）
        # ★ P0-1: 默认走 ReAct 链路 — 用 effective_agent_id 替代显式 agent_id
        react_decision = None
        agent_skills = self._get_agent_skills(effective_agent_id)
        # ★ 方案1-L2: 预检补齐 MCP 维度（本地技能 或 已激活的 MCP 工具，都算"有工具"）
        has_active_mcp = False
        try:
            from src.skill.registry import get_tool_registry
            has_active_mcp = get_tool_registry().has_mcp_tools_for_agent(effective_agent_id)
        except Exception:
            pass
        if agent_skills or has_active_mcp:
            react_decision = {"agent_id": effective_agent_id, "skills": agent_skills}
            react_logger.info(
                f"[ReAct] 自动选择 Agent [{effective_agent_id}]，技能: {agent_skills} | "
                f"MCP激活: {has_active_mcp}"
            )
        else:
            react_logger.info(f"[ReAct] Agent [{effective_agent_id}] 无技能且无激活MCP，降级到标准 gRPC 链路")

        return {
            "session": session,
            "session_summary": session_summary,
            "is_new_session": is_new_session,
            "session_history": session_history,
            "enhanced_message": enhanced_message,
            "grpc_request": dfecrab_pb2.ChatRequest(
                message=enhanced_message,
                session_id=session.id,
                user_id=user_id
            ),
            "manager_system_prompt": manager_system_prompt,
            "stub": stub,
            "react_decision": react_decision,
            "raw_message": message,  # ★ 保存原始消息（alert_judge 需要未增强的原始JSON）
            "compacted": compacted,  # ★ P0 上下文压缩标记（message_end.usage 透传给前端）
            "explicit_agent_id": agent_id,  # ★ 显式指定的agent_id（含P0告警快速路由锁定），供pipeline跳过Manager
        }

    async def _run_chat_pipeline(
        self,
        message: str,
        session_id: Optional[str],
        user_id: str = "default",
        agent_id: Optional[str] = None,
        knowledge_base: Optional[str] = None,
        kb_category: Optional[str] = None,
        kb_top_k: int = 5,
        mcp: Optional[Dict[str, Any]] = None,
        streaming: bool = True,
        correlation_id: str = "",
        use_plan: Optional[bool] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ G1 共享核心: 4 个接口共用的对话流水线

        流程：
            1. 准备阶段（ASR、会话、摘要、历史）
            2. Manager 编排（think_start → think 流式 → think_end → manager_decision）
            3. 路由执行（chat 直调 LLM / task/complex 走 ReAct）
            4. 唯一 message_end 终止

        Args:
            streaming: True=流式（yield 每个 think chunk），False=非流式（跳过 think chunk，只保留 think_end）

        HTTP/WS 4 个入口共用此生成器，只在协议层（HTTP-JSON / SSE / WS）做适配：
            - HTTP /api/v2/chat (非流式)         : streaming=False → 收集 events → return JSON
            - HTTP /api/v2/chat/stream (流式)    : streaming=True → SSEStreamingResponse(gen())
            - WS /ws/chat/stream (流式)          : streaming=True → for event in gen(): ws.send()
            - WS /ws/chat/sync (非流式)          : streaming=False → 收集 events → ws.send() 一次
        """
        from src.session.manager import get_session_manager

        # ★ 请求追踪日志
        react_logger.info(
            f"[Pipeline] 请求开始 | session={session_id} | user={user_id} | "
            f"agent_id={agent_id} | message={message[:100]}"
        )

        # 1. 准备阶段
        ctx = await self._prepare_stream_context(
            message=message, session_id=session_id,
            user_id=user_id, agent_id=agent_id,
        )

        session = ctx["session"]
        session_summary = ctx["session_summary"]
        is_new_session = ctx["is_new_session"]
        session_history = ctx["session_history"]
        raw_message = ctx.get("raw_message", message)  # ★ 获取原始消息（alert_judge 需要）
        session_mgr = get_session_manager()
        # 初始化默认值（从 react_decision 获取初始 agent_id）
        # ★ 未传 agent_id 时显示 "auto" 表示自动路由，传了才显示实际值
        effective_agent_id = agent_id or "auto"
        # ★ 兼容旧 ID（default → dfecrab），统一在下游解析为当前智能体
        try:
            from src.agent.agent_config import normalize_agent_id
            effective_agent_id = normalize_agent_id(effective_agent_id) or effective_agent_id
        except Exception:
            pass
        react_decision = ctx.get("react_decision")
        if react_decision:
            effective_agent_id = react_decision.get("agent_id", effective_agent_id)

        # ★ 用量统计：注入本次请求上下文（user/session/agent），
        #   供下游 MCP 调用埋点与 token 事件自动补齐身份字段，实现按用户隔离统计。
        #   ContextVar 在 asyncio Task 之间隔离，不会串请求。
        try:
            from src.monitoring.usage_store import set_usage_context
            set_usage_context(
                user_id=user_id,
                session_id=session.id,
                agent_id="" if effective_agent_id == "auto" else effective_agent_id,
            )
        except Exception:
            pass

        # 2. meta 事件（所有接口统一）
        yield {
            "type": "meta",
            "data": {
                "session_id": session.id,
                "session_summary": session_summary,
                "is_new_session": is_new_session,
                "agent_id": effective_agent_id,
            }
        }

        # ★ 短路分支参数校验
        # knowledge_base 与 agent_id/mcp 互斥；agent_id 和 mcp 可共存
        if knowledge_base and (agent_id or mcp):
            err_msg = "knowledge_base 与 agent_id/mcp 参数互斥"
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        # agent_id 只能是单个字符串
        if agent_id and not isinstance(agent_id, str):
            err_msg = "agent_id 必须是单个字符串"
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        # ★ 知识库直答分支：直接调用 6788 /knowledge/chat，跳过 Manager/ReAct
        if knowledge_base:
            async for event in self._run_knowledge_base_branch(
                message=message,
                kb_category=kb_category,
                kb_top_k=kb_top_k,
                streaming=streaming,
                ctx=ctx,
            ):
                yield event
            return

        # ★ 解析 mcp 参数：MCP 服务名字符串或字符串数组，运行时临时覆盖该 agent 的 MCP 服务
        mcp_servers = None
        if mcp:
            if isinstance(mcp, str):
                mcp_servers = [mcp]
            elif isinstance(mcp, list):
                mcp_servers = [s for s in mcp if isinstance(s, str) and s]
            else:
                mcp_servers = []
            if not mcp_servers:
                err_msg = "mcp 参数必须是非空的 MCP 服务名字符串或字符串数组"
                yield {
                    "type": "message_end",
                    "data": {
                        "full_response": err_msg,
                        "content": err_msg,
                        "success": False,
                    }
                }
                return

        # 3. ★ G1 优化: Manager 编排（仅调用一次，同时输出 think 流 + 获取决策）
        full_response = ""
        tool_calls_made = []
        matched_skills = []
        message_end_seen = False
        manager_decision = None
        intent = "task"
        parameters = {}
        manager_reasoning = ""  # ★ S3: 捕获 Manager 推理过程
        worker_reasoning = ""   # ★ 捕获 Worker 推理过程
        full_tool_calls = []    # ★ 完整工具调用（含 result/elapsed_ms）
        execution_flow_parts = []  # ★ 按时间轴收集执行片段（think_end/tool_call/tool_result）
        pipeline_usage = None   # ★ 上下文统计：记录本次对话的 usage（供 message_end 与落库）

        # ★ 显式指定 agent_id（用户传参 / P0告警快速路由）时跳过 Manager LLM 思考，
        #    直接从 manager_decision 的下一步（路由执行）开始
        # ★ 指定 mcp 时同样跳过 Manager：agent_id 缺省用默认智能体 dfecrab。
        #   特殊地，mcp 中若包含 alert_judge_tools，说明想走 alert_judge 专属研判链路，
        #   此时在 agent_id 为空或 default 的情况下，自动路由到 alert_judge。
        if mcp_servers:
            # alert_judge_tools 是专属研判链路开关：只要 mcp 参数里带它，
            # 不论 agent_id 是什么，都路由到 alert_judge 走自己的流程。
            if "alert_judge_tools" in mcp_servers:
                routed_agent_id = "alert_judge"
            else:
                routed_agent_id = agent_id or "dfecrab"
        else:
            routed_agent_id = agent_id or ctx.get("explicit_agent_id")
        # ★ 路由决策日志：判断是否因绑定 agent 而跳过 Manager 编排
        logger.info(
            "[Pipeline] 路由决策 | agent_id=%s routed=%s skip_manager=%s",
            agent_id, routed_agent_id, bool(routed_agent_id)
        )
        if routed_agent_id:
            # ★ S3: 记录跳过 Manager 路由的原因，供历史接口解释"为什么没走 Manager"
            manager_reasoning = f"指定 agent_id={routed_agent_id}，跳过 Manager 路由直接执行"
            manager_decision = {
                "intent": "task",
                "target_agent": routed_agent_id,
                "parameters": {},
                "missing_params": [],
                "reasoning": manager_reasoning,
            }
            intent = "task"
            effective_agent_id = routed_agent_id
            react_decision = {
                "agent_id": routed_agent_id,
                "skills": self._get_agent_skills(routed_agent_id),
            }
            react_logger.info(
                f"[Pipeline] 指定 agent_id={routed_agent_id}，跳过 Manager 编排直接执行"
            )
            yield {"type": "manager_decision", "data": manager_decision}

        try:
            llm_config = self._get_gateway_llm_config()
            if llm_config and not routed_agent_id:
                async for event in self._manager_orchestrate(
                    message=message,
                    session_id=session.id,
                    user_id=user_id,
                    session_history=session_history,
                ):
                    et = event.get("type")
                    # ★ S3: 捕获 Manager 推理过程
                    if et == "think_end":
                        manager_reasoning = event.get("data", {}).get("full_reasoning", "")
                    # ★ 非流式模式：跳过 think chunk，只保留 think_end
                    if not streaming and et == "think":
                        continue
                    # ★ 流式模式：透传所有 think 事件
                    if streaming and et in ("think_start", "think", "think_end"):
                        yield event
                        continue
                    # 非流式模式：跳过 think_start，yield think_end
                    if not streaming and et == "think_start":
                        continue
                    if not streaming and et == "think_end":
                        yield event
                        continue

                    # clarification 事件
                    if et == "clarification":
                        yield event
                        return

                    # manager_decision 捕获
                    # （显式指定 agent_id 时已在上方短路合成决策，不会走到这里）
                    if et == "manager_decision":
                        manager_decision = event["data"]
                        intent = manager_decision.get("intent", "task")
                        target_agent = manager_decision.get("target_agent", "")
                        if target_agent:
                            effective_agent_id = target_agent
                            new_skills = self._get_agent_skills(target_agent)
                            react_decision = {"agent_id": target_agent, "skills": new_skills}
                        parameters = manager_decision.get("parameters", {})
                        logger.info(
                            f"[Intent] Manager 决策: intent={intent}, "
                            f"target_agent={effective_agent_id}"
                        )
                    yield event
            else:
                if routed_agent_id:
                    # 显式指定 agent_id（或 mcp）：跳过 Manager 编排属正常路径，非错误
                    logger.debug(f"[Intent] 指定 agent_id={routed_agent_id}，跳过 Manager 编排")
                else:
                    # LLM 配置不可用，降级到 task 模式
                    logger.warning("[Intent] LLM 配置不可用，降级为 task")
                manager_decision = {"intent": "task", "target_agent": effective_agent_id}

            # 4. 路由执行（chat 意图保持 chat：MCP 绑定不再强制改判，agent_id 权威，auto 决策）
            if intent == "chat":
                # chat 模式：直调 LLM（按 agent 模型解析，配置过 model_config 的用其模型）
                llm_config = self._resolve_agent_llm_config(effective_agent_id)
                if not llm_config:
                    yield {"type": "error", "data": {"message": "LLM 配置不可用"}}
                    return

                from src.agent.llm.adapter import LLMAdapter
                llm_adapter = LLMAdapter(llm_config)
                system_prompt = self._get_agent_system_prompt(effective_agent_id)
                _direct_usage: Dict = {}
                try:
                    direct_response, _direct_usage = await llm_adapter.call(
                        prompt=message,
                        system_prompt=system_prompt,
                        with_usage=True
                    )
                except Exception as e:
                    react_logger.error(f"[Pipeline] chat LLM 调用失败: {e}")
                    direct_response = "抱歉，处理您的请求时出错。"

                full_response = direct_response
                # ★ 上下文统计：chat 直答的上下文 = system_prompt + 当前消息
                from src.utils.context_usage import build_context_usage
                pipeline_usage = build_context_usage(
                    llm_usage=_direct_usage or None,
                    system_prompt=system_prompt,
                    current=message,
                    context_length=getattr(llm_adapter, "context_length", DEFAULT_CONTEXT_LENGTH),
                    model=getattr(llm_adapter, "model_name", ""),
                )
                pipeline_usage["compacted"] = ctx.get("compacted", False)  # ★ P0 压缩标记
                # ★ 统一 message_end 结构：拆 JSON + 补全字段
                _norm = normalize_structured_response(direct_response)
                if streaming:
                    # 流式模式：先 message_start，再 message 分块，最后 message_end
                    yield {"type": "message_start", "data": {"agent_id": effective_agent_id}}
                    yield {"type": "message", "data": {"chunk": _norm["content"], "agent_id": effective_agent_id}}
                yield {
                    "type": "message_end",
                    "data": {
                        "full_response": _norm["content"],
                        "structured": _norm["structured"],
                        "matched_skills": [],
                        "tool_calls": [],
                        "execution_flow": [{"type": "manager_reasoning", "content": manager_reasoning}] if manager_reasoning else [],
                        "iterations": 0,
                        "tools_used": [],
                        "elapsed_ms": 0,
                        "agent_id": effective_agent_id,
                        "usage": pipeline_usage,
                    }
                }
                message_end_seen = True
            else:
                # ★ 批次10：complex intent 已退役。无论 Manager 输出何种 intent
                #   （含旧模型残留 complex/未知值），一律归一为 task 直跑；
                #   Plan 分步仅当 plan_mode=explicit 且请求显式 use_plan=true 才启用。
                if intent != "task":
                    react_logger.info(f"[Pipeline] intent={intent} 归一化为 task（complex 已退役，批次10）")
                    intent = "task"
                _effective_use_plan = self._resolve_plan_use(use_plan)
                # ★ alert_judge 特殊：传原始 raw_message（纯JSON告警，不含时间/会话上下文）
                worker_message = raw_message if effective_agent_id == "alert_judge" else message
                async for event in self._react_chat_generator(
                    agent_id=effective_agent_id,
                    message=worker_message,
                    session_messages=session_history,
                    session_id=session.id,
                    user_id=user_id,
                    session_summary=session_summary,
                    use_plan=_effective_use_plan,
                    intent=intent,
                    manager_parameters=parameters,
                    correlation_id=correlation_id,
                    mcp_servers=mcp_servers,
                    compact_context=ctx.get("compacted", False),
                ):
                    et = event.get("type")
                    ed = event.get("data", {})
                    # ★ 非流式模式：跳过 think / 正文 chunk 增量，只保留 think_end 与 message_end
                    #   message_start/message 为流式正文转发，非流式下仅由 message_end 携带完整内容
                    if not streaming and et in ("think_start", "think", "message_start", "message"):
                        continue
                    # ★ 统一 message_end：拆 JSON + 收集 reasoning/tool_calls
                    if et == "message_end":
                        if message_end_seen:
                            react_logger.warning("[Pipeline] 检测到重复 message_end，跳过")
                            continue
                        message_end_seen = True
                        raw_full = ed.get("full_response", ed.get("content", ""))
                        full_response = raw_full
                        # ★ 上下文统计：记录 usage 供落库；透传给前端展示 token 占比
                        pipeline_usage = ed.get("usage") or pipeline_usage
                        if isinstance(pipeline_usage, dict):
                            pipeline_usage["compacted"] = ctx.get("compacted", False)  # ★ P0 压缩标记
                        _norm = normalize_structured_response(raw_full)
                        yield {
                            "type": "message_end",
                            "data": {
                                "full_response": _norm["content"],
                                "structured": _norm["structured"],
                                "matched_skills": matched_skills,
                                "tool_calls": full_tool_calls,
                                "execution_flow": _build_execution_flow(
                                    execution_flow_parts, manager_reasoning
                                ),
                                "iterations": ed.get("iterations", 0),
                                "tools_used": ed.get("tools_used", [t["tool_name"] for t in full_tool_calls]),
                                "elapsed_ms": ed.get("elapsed_ms", 0),
                                "agent_id": effective_agent_id,
                                "usage": pipeline_usage,
                            }
                        }
                        continue
                    elif et == "think_end":
                        worker_reasoning = (worker_reasoning + "\n" if worker_reasoning else "") + ed.get("full_reasoning", "")
                        # ★ 按时间轴就地插入 think_end（保持与流式顺序一致）
                        execution_flow_parts.append({
                            "type": "think_end",
                            "phase": "worker",
                            "iteration": ed.get("iteration", 0),
                            "full_reasoning": ed.get("full_reasoning", ""),
                        })
                    elif et == "tool_call":
                        _tc = {
                            "tool_name": ed.get("tool_name", ""),
                            "arguments": ed.get("tool_args", ed.get("arguments", {})),
                            "tool_call_id": ed.get("tool_call_id", ""),
                            "iteration": ed.get("iteration", 0),
                            "result": None,
                            "success": None,
                            "elapsed_ms": 0,
                            "agent_id": effective_agent_id,
                        }
                        full_tool_calls.append(_tc)
                        tool_calls_made.append({
                            "tool_name": _tc["tool_name"],
                            "arguments": _tc["arguments"],
                            "tool_call_id": _tc["tool_call_id"],
                            "iteration": _tc["iteration"],
                            "success": None,
                        })
                        # ★ 按时间轴就地插入 tool_call
                        execution_flow_parts.append({
                            "type": "tool_call",
                            "tool_name": _tc["tool_name"],
                            "arguments": _tc["arguments"],
                            "tool_call_id": _tc["tool_call_id"],
                            "iteration": _tc["iteration"],
                            "agent_id": effective_agent_id,
                        })
                    elif et == "tool_result":
                        # 按 tool_call_id 关联结果；无 id 时挂到最近一次调用
                        _tid = ed.get("tool_call_id", "")
                        _target = None
                        if _tid:
                            for _tc in reversed(full_tool_calls):
                                if _tc.get("tool_call_id") == _tid:
                                    _target = _tc
                                    break
                        if _target is None and full_tool_calls:
                            _target = full_tool_calls[-1]
                        if _target is not None:
                            _target["result"] = ed.get("result")
                            _target["success"] = ed.get("success", True)
                            _target["elapsed_ms"] = ed.get("elapsed_ms", 0)
                            # 同步回填轻量摘要 tool_calls_made 的成功态（工具结果只保留在 execution_flow）
                            if _tid:
                                for _mc in tool_calls_made:
                                    if _mc.get("tool_call_id") == _tid:
                                        _mc["success"] = ed.get("success", True)
                                        break
                            elif tool_calls_made:
                                tool_calls_made[-1]["success"] = ed.get("success", True)
                            # ★ 按时间轴就地插入 tool_result
                            execution_flow_parts.append({
                                "type": "tool_result",
                                "tool_name": _target.get("tool_name", ""),
                                "result": ed.get("result"),
                                "success": ed.get("success", True),
                                "tool_call_id": ed.get("tool_call_id", ""),
                                "iteration": ed.get("iteration", 0),
                                "elapsed_ms": ed.get("elapsed_ms", 0),
                                "agent_id": effective_agent_id,
                            })
                    elif et == "skill_match":
                        matched_skills = ed.get("skills", [])
                    yield event

        except Exception as e:
            react_logger.error(f"[Pipeline] 流水线异常: {e}", exc_info=True)
            yield {"type": "error", "data": {"message": str(e)}}

        # 5. 兜底：如果 ReAct 路径没 yield message_end（异常退出），补一个
        # ★ alert_judge 走专属 pipeline，以 task_complete 终止，不补 message_end
        if not message_end_seen and effective_agent_id != "alert_judge":
            react_logger.warning(f"[Pipeline] 未收到 message_end，强制补一个")
            yield {
                "type": "message_end",
                "data": {
                    "full_response": full_response or "对话未产生有效响应",
                    "structured": None,
                    "matched_skills": matched_skills,
                    "tool_calls": full_tool_calls,
                    "execution_flow": _build_execution_flow(
                        execution_flow_parts, manager_reasoning
                    ),
                    "iterations": 0,
                    "tools_used": [t["tool_name"] for t in tool_calls_made],
                    "elapsed_ms": 0,
                    "agent_id": effective_agent_id,
                }
            }

        # 6. 保存会话（含丰富元数据：思考过程、工具调用、技能匹配）
        if full_response:
            try:
                # 统一结构：content 存纯文本，structured 存 other 字段
                _norm = normalize_structured_response(full_response)
                _reasoning = manager_reasoning + ("\n" + worker_reasoning if worker_reasoning else "")
                # 构建执行流摘要（按时间轴顺序，含完整 reasoning + 工具调用详情）
                execution_flow = _build_execution_flow(
                    execution_flow_parts, manager_reasoning
                )
                if not execution_flow and _norm["structured"]:
                    execution_flow.append({
                        "type": "manager_reasoning",
                        "content": _reasoning,
                    })

                from src.utils.context_usage import usage_to_tokens
                _msg_tokens = usage_to_tokens(pipeline_usage)  # ★ 上下文统计：token 用量落库（累计到 Session.total_tokens）
                session_mgr.add_message(
                    session.id, "assistant", _norm["content"],
                    structured=_norm["structured"],
                    reasoning=_reasoning,
                    tool_calls=tool_calls_made,
                    agent_id=effective_agent_id,
                    task_type=intent,
                    model=(pipeline_usage or {}).get("model") or None,  # ★ P3：实际使用模型（多模型对话按模型统计）
                    tokens=_msg_tokens,
                    execution_flow=execution_flow,
                    status="completed",
                    metadata={
                        "matched_skills": matched_skills,
                        "tools_used": [t["tool_name"] for t in full_tool_calls],
                        "intent": intent,
                        "has_manager_reasoning": bool(manager_reasoning),
                        "manager_reasoning_length": len(manager_reasoning) if manager_reasoning else 0,
                        "tool_call_count": len(full_tool_calls),
                        "context_length": (pipeline_usage or {}).get("context_length"),  # ★ P3：该模型窗口（按模型聚合水位）
                    }
                )
                # ★ 用量统计：LLM token 事件落盘（与 MCP 事件同一事件流，供"按天统计 token 消耗"）
                try:
                    from src.monitoring.usage_store import record_llm_call
                    record_llm_call(
                        model=(pipeline_usage or {}).get("model") or "",
                        prompt_tokens=_msg_tokens.get("prompt", 0),
                        completion_tokens=_msg_tokens.get("completion", 0),
                        source=(pipeline_usage or {}).get("source") or "llm_usage",
                        session_id=session.id,
                    )
                except Exception:
                    pass
                session_mgr.save_session(session.id)
                react_logger.info(
                    f"[Pipeline] Session 已持久化: {session.id}, "
                    f"intent={intent}, tools={len(full_tool_calls)}, "
                    f"reasoning_len={len(_reasoning)}"
                )
            except Exception as e:
                react_logger.warning(f"[Pipeline] save_session 失败: {e}")

    # ========== ReAct 循环集成 ==========

    def _get_agent_skills(self, agent_id: str) -> List[str]:
        """获取指定 agent 启用的技能列表"""
        tools_path = PROJECT_ROOT / "agents" / agent_id / "tools.json"
        if tools_path.exists():
            try:
                with open(tools_path, 'r', encoding='utf-8') as f:
                    tools = json.load(f)
                return tools.get("enabled_skills", [])
            except Exception as e:
                logger.warning(f"⚠️ 读取 agent [{agent_id}] tools.json 失败: {e}")
        return []

    def _get_agent_system_prompt(self, agent_id: str) -> str:
        """获取指定 agent 的 system_prompt"""
        config_path = PROJECT_ROOT / "agents" / agent_id / "config.json"
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                return config.get("system_prompt", "")
            except Exception as e:
                logger.warning(f"⚠️ 读取 agent [{agent_id}] config.json 失败: {e}")
        return ""

    def _resolve_agent_tool_choice(
        self,
        agent_id: str,
        intent: str = "task",
        enabled_skills: Optional[List[str]] = None,
    ) -> str:
        """解析 tool_choice：agent config.json 显式配置 > 全局默认策略

        策略背景（对齐成熟平台的确定性工具编排，缓解 qwen3_a3b 等小参数量模型
        在 auto 模式下"不调技能直接编造数据"的问题）：
          - agent config.json 显式配置 tool_choice(auto/required/none) 最高优先
          - intent == "chat"            → "none"     （闲聊不装配工具）
          - task（含原 complex，批次10 退役归一）+ 启用了技能 → "required"（首轮强制调工具）
          - 其它（MCP 直调等无本地技能） → "auto"

        注意：required 在 ReActLoop 中只约束第 1 轮，工具返回后自动回到 auto，
        避免"拿到结果后仍被强制重复调工具"无法收尾。
        """
        try:
            from src.agent.agent_config import AgentConfig
            cfg = AgentConfig.from_id(agent_id)
            cfg_tc = (cfg.tool_choice or "").strip().lower()
            if cfg_tc in ("required", "auto", "none"):
                react_logger.info(
                    f"[ReAct] Agent[{agent_id}] tool_choice 命中 agent 配置: {cfg_tc}"
                )
                return cfg_tc
        except Exception as e:
            react_logger.warning(
                f"[ReAct] 读取 agent tool_choice 配置失败，走默认策略: {e}"
            )
        if intent == "chat":
            return "none"
        if enabled_skills:
            return "required"
        return "auto"

    # ──────────────────────────────────────────────────────────
    # ★ 短路分支: 知识库直答 / MCP 直调
    # ──────────────────────────────────────────────────────────

    async def _run_knowledge_base_branch(
        self,
        message: str,
        kb_category: Optional[str],
        kb_top_k: int,
        streaming: bool,
        ctx: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """知识库直答分支：调用 6788 /knowledge/chat，输出兼容现有事件流"""
        import httpx
        try:
            from config.port_loader import knowledge_api_port
            kb_port = knowledge_api_port()
        except Exception:
            kb_port = 6788
        kb_url = f"http://localhost:{kb_port}/knowledge/chat"

        payload = {
            "question": message,
            "category": kb_category,
            "top_k": kb_top_k,
        }
        logger.info(f"[KB-Branch] 调用知识库直答: {kb_url} payload={payload}")

        # 会话 ID（保存历史用）
        try:
            _session_id = ctx["session"].id if ctx.get("session") else None
        except Exception:
            _session_id = None
        from src.session.manager import get_session_manager
        session_mgr = get_session_manager()

        # 成功/失败都先发 manager_decision，便于前端识别走了 KB 分支
        yield {
            "type": "manager_decision",
            "data": {
                "intent": "knowledge_base",
                "target_agent": "knowledge_base",
                "parameters": {"category": kb_category, "top_k": kb_top_k},
                "reasoning": "指定 knowledge_base 参数，直接走知识库直答",
            }
        }

        # 注：用户消息由标准流程（_prepare_stream_context）统一保存，此处不再重复保存

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(kb_url, json=payload)
                resp.raise_for_status()
                kb_result = resp.json()
        except Exception as e:
            logger.error(f"[KB-Branch] 调用知识库服务失败: {e}")
            err_msg = f"知识库服务调用失败: {str(e)}"
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        if kb_result.get("status") != "success":
            err_msg = kb_result.get("message", "知识库问答失败")
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        answer = kb_result.get("answer", "")
        sources = kb_result.get("sources", [])

        # ★ 上下文统计：知识库直答本地估算 usage（KB 服务在独立进程 6788，拿不到真实 usage）
        from src.utils.context_usage import build_context_usage, usage_to_tokens
        kb_usage = build_context_usage(
            system_prompt="你是知识库问答助手，根据检索内容回答用户问题。",
            current=message,
            tool_results=[{"content": json.dumps(sources, ensure_ascii=False, default=str)}] if sources else [],
            context_length=self._gateway_context_length(),
            model=self._gateway_llm_model(),
        )
        kb_usage["source"] = "local_estimate"

        # ★ 用量统计：KB 直答 token 事件落盘（本地估算，source=local_estimate）
        try:
            from src.monitoring.usage_store import record_llm_call
            _kb_tokens = usage_to_tokens(kb_usage)
            record_llm_call(
                model=kb_usage.get("model") or "",
                prompt_tokens=_kb_tokens.get("prompt", 0),
                completion_tokens=_kb_tokens.get("completion", 0),
                source=kb_usage.get("source") or "local_estimate",
                session_id=_session_id or "",
            )
        except Exception:
            pass

        # 保存助手回答（含来源摘要），供会话回看
        if _session_id:
            try:
                source_titles = [
                    s.get("metadata", {}).get("title") or s.get("metadata", {}).get("source", "")
                    for s in sources
                    if s.get("metadata")
                ]
                session_mgr.add_message(
                    _session_id, "assistant", answer,
                    status="completed",
                    model=kb_usage.get("model") or None,  # ★ P3：实际使用模型
                    tokens=usage_to_tokens(kb_usage),  # ★ 上下文统计：token 落库
                    metadata={
                        "intent": "knowledge_base",
                        "kb_category": kb_category,
                        "sources": sources,
                        "source_titles": source_titles,
                        "matched_skills": ["knowledge_base"],
                        "context_length": kb_usage.get("context_length"),  # ★ P3：该模型窗口
                    },
                    task_type="knowledge_base",
                    agents_used=["knowledge_base"],
                    execution_flow=[
                        {"type": "knowledge_base", "content": f"调用知识库直答 (category={kb_category})"}
                    ],
                )
            except Exception as e:
                logger.warning(f"[KB-Branch] 保存助手历史失败: {e}")

        if streaming:
            yield {"type": "message_start", "data": {"agent_id": "knowledge_base"}}
            chunk_size = 80
            for i in range(0, len(answer), chunk_size):
                yield {
                    "type": "message",
                    "data": {
                        "chunk": answer[i:i + chunk_size],
                        "agent_id": "knowledge_base"
                    }
                }

        yield {
            "type": "message_end",
            "data": {
                "full_response": answer,
                "content": answer,
                "success": True,
                "kb_category": kb_category,
                "sources": sources,
                "matched_skills": ["knowledge_base"],
                "tool_calls": [],
                "execution_flow": [
                    {"type": "knowledge_base", "content": f"调用知识库直答 (category={kb_category})"}
                ],
                "iterations": 0,
                "tools_used": [],
                # ★ 上下文统计：知识库直答 usage（本地估算）
                "usage": kb_usage,
            }
        }

    # ──────────────────────────────────────────────────────────
    # ★ v4.0: Manager 编排层
    # ──────────────────────────────────────────────────────────

    async def _manager_orchestrate(
        self,
        message: str,
        session_id: str,
        user_id: str = "default",
        session_history: List[Dict] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ v4.0 Manager 编排层 — 统一入口

        所有对话路径（HTTP/WS）都先走此方法：
        1. 加载 Manager system_prompt
        2. 注入用户画像和 Agent 列表
        3. 流式调用 Manager LLM（输出 think 事件）
        4. 解析 JSON 决策
        5. yield manager_decision 事件
        6. 缺参时 yield clarification

        Yields:
            事件字典:
            - think_start(think, think_end) — Manager 思考流式输出
            - manager_decision — 路由决策
            - clarification — 缺参澄清（需要外部处理）
        """
        import time as _time
        from src.agent.llm.adapter import LLMAdapter
        from src.memory.unified_manager import get_unified_manager

        manager_logger.info(
            f"[Manager] 请求入口 | session={session_id} | user={user_id} | "
            f"message={message[:100]}"
        )

        # 1. 加载 Manager system_prompt
        manager_prompt = self._get_agent_system_prompt("manager_agent")
        if not manager_prompt:
            manager_logger.warning("[Manager] manager_agent config.json 无 system_prompt，降级")
            yield {
                "type": "manager_decision",
                "data": {
                    "intent": "task",
                    "target_agent": "dfecrab",
                    "parameters": {},
                    "missing_params": [],
                    "reasoning": "Manager 降级（无配置）",
                }
            }
            return

        # 2. 注入 {{USER_PROFILE}}
        try:
            memory_mgr = get_unified_manager()
            user_profile = await memory_mgr.get_user_profile(user_id)
        except Exception as e:
            manager_logger.warning(f"[Manager] 获取用户画像失败: {e}")
            user_profile = "（暂无用户画像）"
        manager_prompt = manager_prompt.replace("{{USER_PROFILE}}", user_profile)

        # 3. 注入 {{AGENT_LIST}}（含完整描述 + 技能列表）
        try:
            agent_descs = self._scan_agent_descriptions()

            # 读取 agents_index.json 获取 skills
            index_skills = {}
            index_file = PROJECT_ROOT / "config" / "agents_index.json"
            if index_file.exists():
                try:
                    with open(index_file, 'r', encoding='utf-8') as f:
                        index_data = json.load(f)
                    for aid, info in index_data.get("agents", {}).items():
                        index_skills[aid] = info.get("skills", [])
                except Exception:
                    pass

            # 构建含描述 + 技能的 Agent 列表
            agent_list_parts = []
            for aid, desc in agent_descs.items():
                name = desc.get("name", aid)
                description = desc.get("description", "")

                # 获取该 agent 的技能列表（合并 agents_index + tools.json）
                skills = list(index_skills.get(aid, []))
                try:
                    tools = self._get_agent_skills(aid)
                    for t in tools:
                        if t not in skills:
                            skills.append(t)
                except Exception:
                    pass

                skills_str = ", ".join(skills) if skills else "无"
                agent_list_parts.append(
                    f"- {aid}（{name}）: {description}\n  技能: {skills_str}"
                )

            agent_list_text = "\n".join(agent_list_parts)
        except Exception as e:
            manager_logger.warning(f"[Manager] 构建 Agent 列表失败: {e}")
            agent_list_text = "- default（默认助手）: 通用智能助手\n  技能: weather, file_read, excel-read, web-fetch\n- kunming（昆明配网数据专家）: 配网业务数据查询\n  技能: kunming_classifier, kunming_api"
        manager_prompt = manager_prompt.replace("{{AGENT_LIST}}", agent_list_text)

        # 4. 获取 LLM 配置
        llm_config = self._get_gateway_llm_config()
        if not llm_config:
            manager_logger.error("[Manager] LLM 配置不可用")
            yield {
                "type": "manager_decision",
                "data": {
                    "intent": "task",
                    "target_agent": "dfecrab",
                    "parameters": {},
                    "missing_params": [],
                    "reasoning": "LLM 不可用降级",
                }
            }
            return

        # 5. 构建消息（含历史上下文，合并为 prompt 字符串）
        prompt_parts = []
        if session_history:
            for msg in session_history[-6:]:  # 最近6条历史
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    prompt_parts.append(f"用户: {content}")
                elif role == "assistant":
                    prompt_parts.append(f"系统: {content}")
        prompt_parts.append(f"用户: {message}\n/no_think")
        merged_prompt = "\n".join(prompt_parts)

        # 6. 流式调用 Manager LLM
        llm_adapter = LLMAdapter(llm_config)

        yield {
            "type": "think_start",
            "data": {"phase": "manager", "iteration": 0}
        }

        full_reasoning = ""
        full_response = ""

        try:
            async for event in llm_adapter.call_stream(
                prompt=merged_prompt,
                system_prompt=manager_prompt,
                max_tokens=1024,
                response_format={"type": "json_object"},
            ):
                if event["type"] == "reasoning":
                    full_reasoning += event["content"]
                elif event["type"] == "token":
                    full_response += event["content"]
                    # Manager 的决策 JSON 落在 content；reasoning 兜底累积（/no_think 后通常为空）
                    full_reasoning += event["content"]
                elif event["type"] == "done":
                    break
        except Exception as e:
            manager_logger.error(f"[Manager] LLM 流式调用失败: {e}")
            yield {
                "type": "think_end",
                "data": {"phase": "manager", "full_reasoning": f"Manager 调用失败: {e}"}
            }
            # 降级：用 IntentClassifier
            intent = await self._fallback_classify(message, llm_config)
            yield {
                "type": "manager_decision",
                "data": {
                    "intent": intent,
                    "target_agent": "dfecrab",
                    "parameters": {},
                    "missing_params": [],
                    "reasoning": f"Manager 降级（LLM 失败）→ IntentClassifier={intent}",
                }
            }
            return

        manager_logger.info(
            f"[Manager] 思考完成 | reasoning_len={len(full_reasoning)} | "
            f"reasoning={full_reasoning[:200]}"
        )

        # 7. 解析 JSON 决策（同时尝试 full_response 和 full_reasoning）
        decision = self._parse_manager_decision(full_response, full_reasoning)
        if decision is None:
            # JSON 解析失败，降级（单行结构化日志，避免多行输出难排查）
            _resp_head = (full_response or "").replace("\n", " ").strip()[:120]
            manager_logger.warning(
                f"[Manager] 决策解析失败 | response_len={len(full_response or '')} | "
                f"head={_resp_head or '(空)'} | 降级待分类"
            )
            intent = await self._fallback_classify(message, llm_config)
            decision = {
                "intent": intent,
                "target_agent": "dfecrab",
                "parameters": {},
                "missing_params": [],
                "reasoning": f"Manager JSON 解析失败，降级 IntentClassifier={intent}",
            }

        manager_logger.info(
            f"[Manager] 路由决策 | intent={decision['intent']} | "
            f"target_agent={decision['target_agent']} | "
            f"missing_params={decision['missing_params']} | "
            f"reasoning={decision.get('reasoning', '')[:100]}"
        )

        # 8. 只推一句话路由理由（决策 JSON 不再逐 chunk 外泄）
        _reason_text = str(decision.get("reasoning", "")).strip()
        if _reason_text:
            yield {
                "type": "think",
                "data": {
                    "chunk": _reason_text,
                    "phase": "manager",
                    "iteration": 0,
                }
            }
        yield {
            "type": "think_end",
            "data": {"phase": "manager", "full_reasoning": _reason_text}
        }

        # 9. yield manager_decision 事件
        yield {
            "type": "manager_decision",
            "data": decision
        }

        # 10. 如果缺参，yield clarification
        if decision.get("missing_params"):
            yield {
                "type": "clarification",
                "data": {
                    "message": f"请补充以下信息: {', '.join(decision['missing_params'])}",
                    "missing_params": decision["missing_params"],
                    "options": [],
                }
            }

    def _parse_manager_decision(self, full_response: str, full_reasoning: str = "") -> Optional[Dict]:
        """解析 Manager LLM 输出的 JSON 决策

        优先解析 full_response（content 字段），
        失败则尝试 full_reasoning（reasoning_content 字段）。
        使用括号平衡匹配支持嵌套 JSON。

        Returns:
            dict: {intent, target_agent, parameters, missing_params, reasoning}
            None: 解析失败
        """
        import json

        def _extract_json_objects(text: str) -> list:
            """使用括号平衡匹配提取所有 JSON 对象"""
            objects = []
            depth = 0
            start = -1
            for i, ch in enumerate(text):
                if ch == '{':
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start >= 0:
                        json_str = text[start:i + 1]
                        objects.append(json_str)
                        start = -1
            return objects

        # 按优先级尝试解析：full_response → full_reasoning → 合并
        sources = []
        if full_response:
            sources.append(("response", full_response))
        if full_reasoning:
            sources.append(("reasoning", full_reasoning))
        if full_response and full_reasoning:
            sources.append(("combined", full_response + "\n" + full_reasoning))

        for source_name, raw_text in sources:
            json_objects = _extract_json_objects(raw_text)
            for json_str in reversed(json_objects):
                try:
                    decision = json.loads(json_str)
                    if "intent" in decision or "target_agent" in decision:
                        decision.setdefault("intent", "task")
                        decision.setdefault("target_agent", "dfecrab")
                        decision.setdefault("parameters", {})
                        decision.setdefault("missing_params", [])
                        decision.setdefault("reasoning", "")
                        manager_logger.info(f"[Manager] JSON 解析成功（来源: {source_name}）")
                        return decision
                except json.JSONDecodeError:
                    continue

        manager_logger.warning(f"[Manager] JSON 解析失败。response={full_response[:100]}, reasoning={full_reasoning[:100]}")
        return None

    async def _fallback_classify(self, message: str, llm_config: Dict) -> str:
        """Manager 降级时的意图分类（使用 IntentClassifier）"""
        try:
            from src.agent.intent_classifier import IntentClassifier
            classifier = IntentClassifier(llm_config=llm_config, use_llm=True)
            return await classifier.classify(message, has_skills=True)
        except Exception as e:
            manager_logger.warning(f"[Manager] IntentClassifier 降级也失败: {e}")
            return "task"

    async def _handle_clarification(
        self,
        original_message: str,
        user_reply: str,
        missing_params: List[str],
        session_id: str,
        user_id: str = "default",
        session_history: List[Dict] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ v4.0 Clarification 完整流程

        当 Manager 标记 missing_params 后：
        1. 前端展示 clarification 事件
        2. 用户回复补充信息
        3. 合并用户回复到原消息
        4. 重新走 _manager_orchestrate

        Args:
            original_message: 原始用户消息
            user_reply: 用户补充的回复
            missing_params: 缺失的参数列表
            session_id: 会话 ID
            user_id: 用户 ID
            session_history: 会话历史
        """
        # 合并用户回复到原消息
        merged_message = f"{original_message} {user_reply}"
        logger.info(
            f"[Clarification] 合并消息: '{original_message[:30]}' + '{user_reply[:30]}'"
        )

        # 重新走 Manager 编排
        async for event in self._manager_orchestrate(
            message=merged_message,
            session_id=session_id,
            user_id=user_id,
            session_history=session_history,
        ):
            yield event

    def _resolve_plan_use(self, request_use_plan: Optional[bool] = None) -> bool:
        """Plan 执行器开关（react.plan_mode，批次10：complex intent 已退役）。

        - off（默认）：恒不启用 Plan 分步——多步骤复杂度由 task 工具循环消化（日志实证更优）
        - explicit：仅请求体显式 use_plan=true 时启用（预留"计划确认模式/多智能体编排"底座）
        判定纯配置驱动，无关键词。
        """
        try:
            from src.config.app_config import section as _cfg_section
            mode = (_cfg_section("react") or {}).get("plan_mode", "off")
        except Exception:
            mode = "off"
        return bool(request_use_plan) if mode == "explicit" else False

    # ══════════════════════════════════════════════════════════
    # user_id 收敛（批次 10-B-2）
    # ══════════════════════════════════════════════════════════

    # 按来源（ws/chat、http/chat 等）记录最近一次"缺失 user_id"告警时间，限频防刷屏
    _missing_user_warn_at: Dict[str, float] = {}

    def _resolve_user_id(self, declared: Any = None, auth: Any = None,
                         source: str = "chat") -> str:
        """user_id 解析收敛（B-2）：declared(请求体) > auth(HTTP 头/WS 认证) > 配置默认。

        仅在两个候选都真实缺失（空串/None）时回落 config.identity.default_user_id，
        并按 source 限频打 WARNING，提示前端必传 user_id（多用户现场避免会话/记忆
        落到同一默认用户）。判定纯配置驱动，无关键词表、无硬编码名单。
        """
        for cand in (declared, auth):
            if isinstance(cand, str) and cand.strip():
                return cand.strip()
        try:
            from src.config.app_config import section as _cfg_section
            _idn = _cfg_section("identity") or {}
        except Exception:
            _idn = {}
        _default = str(_idn.get("default_user_id") or "default").strip() or "default"
        if _idn.get("warn_missing_user_id", True):
            _now = time.time()
            _gap = float(_idn.get("warn_missing_interval_s", 300) or 300)
            _last = type(self)._missing_user_warn_at.get(source, 0.0)
            if _now - _last >= _gap:
                type(self)._missing_user_warn_at[source] = _now
                logger.warning(
                    f"[Identity] {source} 请求未携带 user_id（请求体/认证均缺失），"
                    f"回落默认用户 '{_default}'。多用户现场请前端必传 user_id，"
                    f"否则会话与记忆按默认用户隔离。"
                )
        return _default

    async def _react_chat_generator(
        self,
        agent_id: str,
        message: str,
        session_messages: List[Dict],
        session_id: str,
        user_id: str = "default",
        session_summary: str = "",
        use_plan: bool = False,
        intent: str = "task",
        manager_parameters: Optional[Dict] = None,
        correlation_id: str = "",
        mcp_servers: Optional[List[str]] = None,
        compact_context: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """带 ReAct 循环的流式对话生成器

        当 agent 启用了技能时，使用此方法进行带工具调用的对话。
        ★ P0-4: 集成链路A的4个成熟能力（历史过滤、时间上下文、摘要、记忆沉淀）
        ★ P1-7: use_plan=True 时先调 Planner 拆步骤，再逐步骤跑 ReAct
        ★ 阶段3 Step6: Manager 参数注入 Worker system_prompt
        """
        # ★ tool_choice 决策已下沉到 _resolve_agent_tool_choice（需先归一化 agent_id、
        #   拿到 enabled_skills 才能判定，见下方调用）

        from src.agent.llm.adapter import LLMAdapter
        from src.agent.loop import ReActLoop
        from src.skill.registry import get_tool_registry

        start_time = time.time()

        # ★ 提前归一化 agent_id（default → dfecrab 等）。
        #   必须在此处（预判断之前）归一化，否则下面 _get_agent_skills / has_mcp 用
        #   原始 "default" 查不到配置，ReActLoop 内部虽会 normalize 但根本到不了那里。
        from src.agent.agent_config import normalize_agent_id
        agent_id = normalize_agent_id(agent_id) or "dfecrab"

        # 1. 获取 agent 配置
        enabled_skills = self._get_agent_skills(agent_id)
        system_prompt = self._get_agent_system_prompt(agent_id)

        # ★ tool_choice 决策（多级）：agent config.json 显式配置 > 全局默认策略
        #   背景：qwen3_a3b 等小参数量模型在 auto 下常"不调技能直接编数据"，
        #   task + 启用技能默认 required（ReActLoop 内仅约束第 1 轮，后续轮回 auto）
        tool_choice = self._resolve_agent_tool_choice(
            agent_id=agent_id,
            intent=intent,
            enabled_skills=enabled_skills,
        )

        # ★ 阶段3 Step6: 注入 Manager 参数到 system_prompt
        if manager_parameters:
            params_str = json.dumps(manager_parameters, ensure_ascii=False, indent=2)
            system_prompt += f"\n\n【Manager 提取的参数】\n{params_str}"
            react_logger.info(f"[ReAct] 注入 Manager 参数到 [{agent_id}]: {list(manager_parameters.keys())}")

        # ★ MCP instructions 注入（对齐 LibreChat serverInstructions：服务端声明的
        #   工具调用 SOP 进入 system_prompt，弱模型也能遵守"先 search_feeders 定位唯一
        #   file、再 get_feeder_topology 取拓扑"等规范）
        if mcp_servers:
            try:
                from src.mcp import get_mcp_client
                _ins_parts = []
                for _sn in mcp_servers:
                    _ins = get_mcp_client().get_server_instructions(_sn)
                    if _ins and _ins.strip():
                        _ins_parts.append(f"【{_sn} MCP 使用须知】\n{_ins.strip()}")
                if _ins_parts:
                    system_prompt += "\n\n" + "\n\n".join(_ins_parts)
                    react_logger.info(f"[ReAct] 注入 MCP instructions: {mcp_servers}")
            except Exception as e:
                react_logger.warning(f"[ReAct] MCP instructions 注入失败: {e}")
        
        # ★ MCP 绑定决定是否进 ReAct（工具池确有该 agent 绑定的 MCP 工具）
        has_mcp = False
        try:
            has_mcp = get_tool_registry().has_mcp_tools_for_agent(agent_id)
        except Exception:
            has_mcp = False

        # ★ alert_judge 为空壳智能体：走专属微调模型文本 ReAct 旁路，
        #   不依赖本地技能/MCP 绑定/传参的通用装配判断（主路径靠传 alert_judge_tools 触发，
        #   P0 快速路由为自动兜底）
        if agent_id != "alert_judge" and not enabled_skills and not has_mcp and not mcp_servers:
            # 无本地技能、未绑定 MCP 工具、且未通过请求体 mcp 参数临时指定 → 使用普通对话模式
            react_logger.info(f"[ReAct] Agent [{agent_id}] 无启用的技能、无绑定 MCP、未传 mcp 参数")
            yield {
                "type": "message",
                "data": {
                    "content": "该Agent未配置技能，使用普通对话模式",
                    "agent_id": agent_id
                }
            }
            return

        react_logger.info(
            f"[ReAct] Agent [{agent_id}] 启用技能: {enabled_skills} | "
            f"绑定MCP激活: {has_mcp}"
        )

        # 2. 获取 LLM 配置（★ 按 agent 模型解析：model_config 优先，否则跟随全局）
        llm_config = self._resolve_agent_llm_config(agent_id)
        if not llm_config:
            yield {
                "type": "error",
                "data": {"content": "LLM 配置不可用"}
            }
            return

        # ★ P0-4 能力1: 语义历史过滤（复用链路A的 HistoryFilter）
        filtered_history = session_messages
        try:
            filtered_history = self._history_filter.filter_history(
                current_msg=message,
                history=session_messages
            )
        except Exception as e:
            react_logger.warning(f"[ReAct] 历史过滤失败，使用原始历史: {e}")

        # ★ 时间上下文注入 system_prompt（不混入用户消息，避免模型把系统时间当用户问题）
        # alert_judge 的消息是 JSON 告警信号，不需要时间上下文
        enhanced_message = message
        if agent_id != "alert_judge":
            try:
                from src.utils.time_parser import get_time_context
                system_prompt = f"{get_time_context()}\n\n{system_prompt}"
            except Exception as e:
                react_logger.warning(f"[ReAct] 时间上下文生成失败: {e}")

            # ★ 批次12-C2：会话附件自动注入（本会话 active 附件摘要进上下文）。
            #   生命周期对齐 LibreChat：上传即挂会话 → 每轮自动带上 → 叉掉/删除后不再注入
            #   （build_session_context 只取 status=active；删会话由 delete_session 联动清理）。
            #   仅注入"发给模型的当前轮"，不污染历史/摘要（历史已按原始 message 落库）。
            try:
                from src.files.service import FileService
                _ctx_len = int((llm_config or {}).get("context_length") or 0) or 32768
                _attach_block = FileService.build_session_context(session_id or "", _ctx_len)
                if _attach_block:
                    enhanced_message = _attach_block + "\n\n" + enhanced_message
                    react_logger.info(
                        f"[Pipeline] 会话附件注入 {len(_attach_block)} 字符 (session={session_id})"
                    )
            except Exception as e:
                react_logger.warning(f"[Pipeline] 会话附件注入失败（忽略继续）: {e}")

        # ★ alert_judge 特殊处理：走标准三件套适配链路（src/alert_judge/ 对应现场标准文件），
        #   跳过通用 LLM 层。agent_caller2 按 Thought:/Action: 文本 ReAct 输出，
        #   工具由标准 tools.py 直连后端服务执行，产出完整 thought/tool_call/task 事件流。
        if agent_id == "alert_judge":
            react_logger.info(f"[ReAct] alert_judge 专用链路：标准三件套（src/alert_judge）")
            async for event in self._alert_judge_direct_react(
                alert_json=enhanced_message,
                session_id=session_id,
                user_id=user_id,
                correlation_id=correlation_id,
            ):
                yield event
            return

        # 3. 构建消息列表
        messages = []
        # 添加历史消息（已过滤）——HistoryFilter 现按"持续上下文"默认带回最近 6 条完整轮。
        # ★ P0：本次触发过自动压缩时保留最近 4 条（老上下文已由摘要承担）；普通场景取 6 条
        _hist_num = 4 if compact_context else 6
        recent_history = filtered_history[-_hist_num:] if len(filtered_history) > _hist_num else filtered_history
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            messages.append({"role": role, "content": content})
        
        # 添加当前用户消息（增强版）
        messages.append({"role": "user", "content": enhanced_message})

        # 4. 初始化 ReAct 循环
        llm_adapter = LLMAdapter(llm_config)
        tool_registry = get_tool_registry()
        # ★ ReAct 最大轮数：读 dfecrab.json agent_defaults.max_iterations（AgentConfig.from_id 已合并全局默认），兜底 3
        _max_iter = 3
        try:
            from src.agent.agent_config import AgentConfig
            _max_iter = int(AgentConfig.from_id(agent_id).max_iterations or 3)
        except Exception:
            pass
        react_logger.info(f"[ReAct] Agent[{agent_id}] 最大轮数={_max_iter}")
        react_loop = ReActLoop(
            llm_adapter=llm_adapter,
            tool_registry=tool_registry,
            max_iterations=_max_iter
        )

        # ★ 统一初始化（批次10 修复：此前 tool_calls_made 仅在非 Plan 分支初始化，
        #   Plan 分支收尾使用 → complex 任务必崩 UnboundLocalError）
        tool_calls_made = []
        matched_skills = []

        # ★ S3.1: Plan 模式（执行器保留：供 plan_mode=explicit / 未来多智能体编排复用）
        plan = None
        if use_plan:
            from src.agent.planner import get_task_planner
            planner = get_task_planner()
            plan = await planner.plan(
                user_message=message,
                llm_adapter=llm_adapter,
                enabled_skills=enabled_skills,
            )
            if plan.steps:
                yield {
                    "type": "plan_created",
                    "data": {
                        "plan_id": plan.id,
                        "steps": [s.to_dict() for s in plan.steps],
                        "total": plan.total,
                        "agent_id": agent_id,
                    }
                }
                logger.info(
                    f"[ReAct+Plan] 开始执行 {plan.total} 步计划 (plan_id={plan.id})"
                )

        # ★ S3.1: 如果有 plan 且有 steps，逐步骤执行
        if plan and plan.steps:
            full_response_parts = []

            for step in plan.steps:
                planner.start_step(step.index)
                step_event = yield {
                    "type": "plan_step",
                    "data": {
                        "step_index": step.index,
                        "step_desc": step.description,
                        "status": "running",
                        "agent_id": agent_id,
                    }
                }

                # 构建该步骤的提示消息
                step_message = (
                    f"【步骤 {step.index}/{plan.total}】{step.description}\n"
                    + (f"建议工具: {step.suggested_tool}" if step.suggested_tool else "")
                )
                step_messages = list(messages)  # 复制原始消息
                step_messages.append({"role": "user", "content": step_message})

                # 为该步骤运行 ReAct 循环
                step_response = ""
                step_tool_calls = []

                async for event in react_loop.run(
                    messages=step_messages,
                    agent_id=agent_id,
                    enabled_skills=enabled_skills,
                    system_prompt=system_prompt,
                    # temperature / max_tokens 不传 → 由 LLMAdapter 从 dfecrab.json provider 读取
                    tool_choice=tool_choice,
                    mcp_servers=mcp_servers,
                    user_id=user_id,
                ):
                    event_type = event.get("type")
                    event_data = event.get("data", {})

                    if event_type == "tool_call":
                        step_tool_calls.append({
                            "tool_name": event_data.get("tool_name", ""),
                            "arguments": event_data.get("tool_args", event_data.get("arguments", {})),
                        })

                    elif event_type == "message_end":  # ★ final → message_end
                        step_response = event_data.get("full_response", event_data.get("content", ""))

                    # 透传事件给前端（加上步骤上下文）
                    mapped_type = EVENT_TYPE_MAP.get(event_type, event_type)
                    yield {
                        "type": mapped_type,
                        "data": {
                            **event_data,
                            "step_index": step.index,
                            "step_desc": step.description,
                            "agent_id": agent_id,
                        }
                    }

                    # EventBus 派发
                    if self._event_bus:
                        try:
                            await self._event_bus.publish_react(
                                event_type=event_type,
                                data=event_data,
                                session_id=session_id,
                                user_id=user_id,
                            )
                        except Exception:
                            pass

                # 保存步骤结果
                if step_response:
                    full_response_parts.append(f"步骤{step.index}: {step_response}")
                    planner.set_step_result(step.index, step_response)
                    planner.complete_step(step.index)
                    tool_calls_made.extend(step_tool_calls)

                    yield {
                        "type": "plan_step",
                        "data": {
                            "step_index": step.index,
                            "step_desc": step.description,
                            "status": "completed",
                            "result": step_response,
                            "agent_id": agent_id,
                        }
                    }
                    logger.info(f"[ReAct+Plan] 步骤 {step.index} 完成")
                else:
                    planner.fail_step(step.index)
                    yield {
                        "type": "plan_step",
                        "data": {
                            "step_index": step.index,
                            "step_desc": step.description,
                            "status": "failed",
                            "result": "步骤未返回有效结果",
                            "agent_id": agent_id,
                        }
                    }
                    logger.warning(f"[ReAct+Plan] 步骤 {step.index} 失败")

            full_response = "\n\n".join(full_response_parts)
            planner.current_plan.status = "completed"
            logger.info(f"[ReAct+Plan] 计划完成 (plan_id={plan.id})")

        # ★ 非 Plan 模式：直接跑 ReAct 循环
        else:
            # 5. 运行 ReAct 循环（内联，S3.1 保留原有逻辑）
            #   tool_calls_made / matched_skills 已在函数顶部统一初始化（批次10，Plan/非 Plan 共用）
            full_response = ""

            async for event in react_loop.run(
                messages=messages,
                agent_id=agent_id,
                enabled_skills=enabled_skills,
                system_prompt=system_prompt,
                # temperature / max_tokens 不传 → 由 LLMAdapter 从 dfecrab.json provider 读取
                tool_choice=tool_choice,
                mcp_servers=mcp_servers,
                user_id=user_id,
            ):
                event_type = event.get("type")
                event_data = event.get("data", {})
                mapped_type = EVENT_TYPE_MAP.get(event_type, event_type)

                # ★ S2.2: 协议事件透传（格式已对齐 event_types.py）
                # ★ v4.0: thinking 拆为三段式 think_start / think / think_end
                if event_type == "think_start":
                    yield {
                        "type": "think_start",
                        "data": {
                            "phase": event_data.get("phase", "worker"),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "think":
                    yield {
                        "type": "think",
                        "data": {
                            "chunk": event_data.get("chunk", ""),  # ★ content → chunk
                            "phase": event_data.get("phase", "worker"),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "think_end":
                    yield {
                        "type": "think_end",
                        "data": {
                            "full_reasoning": event_data.get("full_reasoning", ""),
                            "phase": event_data.get("phase", "worker"),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "skill_match":  # ★ 独立事件
                    matched_skills = event_data.get("skills", [])
                    yield {
                        "type": "skill_match",
                        "data": {
                            "skills": event_data.get("skills", []),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "tool_call":
                    # ★ S2.2: 使用 event_data（make_event 格式）
                    tool_name = event_data.get("tool_name", "")
                    arguments = event_data.get("tool_args", event_data.get("arguments", {}))
                    tool_calls_made.append({
                        "tool_name": tool_name,
                        "arguments": arguments
                    })

                    yield {
                        "type": mapped_type,
                        "data": {
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "content": f"调用技能: {tool_name}({json.dumps(arguments, ensure_ascii=False)})",
                            "agent_id": agent_id
                        }
                    }

                elif event_type == "tool_result":
                    result = event_data.get("result", {})
                    # ★ 展示工具执行的实质内容（stdout/stderr），替代机械的"技能执行完成: success"
                    _status = "done"
                    _summary = ""
                    if isinstance(result, dict):
                        _status = result.get("status", "unknown")
                        _inner = result.get("content", {})
                        if isinstance(_inner, dict):
                            _summary = _inner.get("stdout", "") or _inner.get("stderr", "")
                        if not _summary:
                            _summary = result.get("error", "") or ""
                    _summary = str(_summary).strip()[:200]
                    _content = f"技能执行完成: {_status}"
                    if _summary:
                        _content += f" | {_summary}"
                    yield {
                        "type": mapped_type,
                        "data": {
                            "tool_name": event_data.get("tool_name", ""),
                            "result": result,
                            "success": event_data.get("success", True),
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "elapsed_ms": event_data.get("elapsed_ms", 0),
                            "corrected": event_data.get("corrected", False),
                            "content": _content,
                            "agent_id": agent_id
                        }
                    }

                elif event_type == "tool_start":
                    yield {
                        "type": "tool_start",
                        "data": {
                            "tool_name": event_data.get("tool_name", ""),
                            "tool_args": event_data.get("tool_args", {}),
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "start_time": event_data.get("start_time", 0.0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "tool_progress":
                    yield {
                        "type": "tool_progress",
                        "data": {
                            "tool_name": event_data.get("tool_name", ""),
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "progress": event_data.get("progress", ""),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "message_start":  # ★ v4.0: 正文开始（透传给前端）
                    yield {
                        "type": "message_start",
                        "data": {
                            "agent_id": agent_id
                        }
                    }

                elif event_type == "message":  # ★ v4.1: 流式正文 chunk（loop.py 实时 token 转发）
                    yield {
                        "type": "message",
                        "data": {
                            "chunk": event_data.get("chunk", ""),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "message_end":  # ★ final → message_end
                    full_response = event_data.get("full_response", event_data.get("content", ""))
                    yield {
                        "type": "message_end",
                        "data": {
                            "full_response": full_response,
                            "iterations": event_data.get("iterations", 0),
                            "tools_used": event_data.get("tools_used", []),
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                            "agent_id": agent_id,
                            # ★ 上下文统计：透传 ReActLoop 计算的 usage（token 占比）
                            "usage": event_data.get("usage"),
                        }
                    }

                elif event_type == "error":
                    yield {
                        "type": mapped_type,
                        "data": {
                            "message": event_data.get("message", event_data.get("content", "Unknown error")),
                            "iteration": event_data.get("iteration", 0),
                            "recoverable": event_data.get("recoverable", False),
                            "agent_id": agent_id
                        }
                    }
                    # 只有不可恢复的错误才 return
                    if not event_data.get("recoverable", False):
                        return

                elif event_type == "confirmation":
                    yield {
                        "type": mapped_type,
                        "data": {
                            "message": event_data.get("message", ""),
                            "options": event_data.get("options", []),
                            "timeout_sec": event_data.get("timeout_sec", 0),
                            "tool_name": event_data.get("tool_name", ""),
                            "error": event_data.get("error", ""),
                            "agent_id": agent_id,
                        }
                    }

                # ★ S2.3: EventBus 派发 ReAct 事件（所有事件类型透传）
                if self._event_bus:
                    try:
                        await self._event_bus.publish_react(
                            event_type=event_type,
                            data=event_data,
                            session_id=session_id,
                            user_id=user_id,
                        )
                    except Exception:
                        pass  # EventBus 派发失败不中断主流程

        # ★ P0-4 能力3+4: 会话摘要 + 记忆沉淀（复用链路A的 save_daily_memory + add_to_long_term）
        elapsed = time.time() - start_time
        try:
            # 3. 更新会话摘要
            if session_summary:
                try:
                    from src.session.manager import get_session_manager
                    sm = get_session_manager()
                    sm.set_summary(session_id, session_summary)
                except Exception:
                    pass
            
            # 4. 沉淀每日记忆 + 长期记忆
            from src.memory.global_manager import get_global_memory_manager
            from src.memory.long_term import MemoryManager
            global_memory_mgr = get_global_memory_manager()
            
            memory_content = f"""
会话ID: {session_id}
用户: {user_id}
用户消息: {message[:200]}
AI响应: {full_response[:500] if full_response else '(无文本响应)'}
使用的工具: {[t['tool_name'] for t in tool_calls_made] if tool_calls_made else '无'}
"""
            mem_category = "conversation" if full_response else "error_log"
            global_memory_mgr.save_daily_memory(memory_content, category=mem_category, user_id=user_id)
            
            # ★ S3.5: Plan 模式 Memory 持久化（按 plan_id 维度存取）
            if plan and plan.steps:
                plan_memory_content = (
                    f"[计划 {plan.id}]\n"
                    f"用户消息: {message[:200]}\n"
                    f"总步骤: {plan.total} / 完成: {plan.completed}\n"
                    f"步骤详情:\n" +
                    "\n".join(
                        f"  [{s.status}] 步骤{s.index}: {s.description}"
                        for s in plan.steps
                    ) +
                    f"\n最终结果: {full_response[:500] if full_response else '(无)'}"
                )
                try:
                    global_memory_mgr.save_daily_memory(
                        plan_memory_content,
                        category="plan_execution",
                        user_id=user_id,
                    )
                except Exception:
                    pass

                # 长期记忆：plan 级别的经验沉淀
                try:
                    mm = MemoryManager(agent_id=agent_id, user_id=user_id)
                    plan_tags = ["react", "plan", agent_id, plan.status]
                    mm.add_to_long_term(
                        "plan_executions",
                        f"计划 {plan.id}: {plan.total} 步, 完成 {plan.completed}, 状态 {plan.status}",
                        tags=plan_tags,
                    )
                except Exception:
                    pass

                logger.info(
                    f"[ReAct+Plan] Plan 记忆已持久化 (plan_id={plan.id}, "
                    f"steps={plan.total}/{plan.completed})"
                )
            
            # 长期记忆（按 agent + user 写入）
            try:
                mm = MemoryManager(agent_id=agent_id, user_id=user_id)
                mm.add_to_long_term(
                    "successful_patterns" if full_response else "lessons_learned",
                    f"会话 {session_id}: {message[:100]} -> {full_response[:200] if full_response else '无响应'}",
                    tags=["react", agent_id]
                )
            except Exception:
                pass
            
            react_logger.info(f"[ReAct] 记忆已沉淀 (session={session_id}, elapsed={elapsed:.2f}s)")

            # ★ 阶段B: 自动提取用户事实（LLM，fire-and-forget，不阻塞主流程）
            if full_response and (message or "").strip():
                try:
                    from src.memory.extractor import UserFactExtractor
                    asyncio.create_task(
                        UserFactExtractor().extract_and_store(
                            llm_adapter, message, full_response, user_id
                        )
                    )
                except Exception:
                    pass

            # ★ 阶段C: 长对话滚动摘要（LLM，fire-and-forget，每 N 轮合并一次）
            if session_id:
                try:
                    from src.memory.summarizer import SessionSummarizer
                    asyncio.create_task(
                        SessionSummarizer().maybe_rolling_summary(
                            llm_adapter, session_id, user_id
                        )
                    )
                except Exception:
                    pass

            # ★ 持久化会话由主链路 _run_chat_pipeline 统一负责（含 reasoning/工具/技能元数据），
            #   此处不再重复保存，避免历史出现无思考内容的裸 assistant 消息
        except Exception as e:
            react_logger.warning(f"[ReAct] 记忆沉淀失败（降级继续）: {e}")

        # ★ G2 修复: 不再 yield 重复的 message_end
        # ReActLoop.run() 内部已 yield 过 message_end（L3749-3760 转发逻辑）
        # 此处再 yield 会产生双 message_end 事件
        react_logger.debug(f"[ReAct] 流生成器结束，message_end 由 ReActLoop 统一 yield")

        # ★ S5.4: 反思已由 ReActLoop 后台执行（_reflect_in_background），
        #   网关侧不再重复触发，避免一次对话反思两次、重复写记忆。

    # ★ S1.2: 旧版 _classify_intent + _CHAT_PATTERNS / _COMPLEX_PATTERNS 已迁移至
    #   src/agent/intent_classifier.py → IntentClassifier 类
    #   此处不再保留重复定义。

    async def _alert_ephemeral_stream(
        self,
        alert_json: str,
        user_id: str,
        correlation_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """alert 短期会话（type=alert）：不创建/不落库 session_mgr，强制走 alert_judge。

        与 `_alert_judge_direct_react` 的区别：跳过通用 _run_chat_pipeline 的
        会话管理与上下文注入，避免每次告警在左侧"今日"列表里塞一条无意义记录。
        事件流格式与正常 alert_judge 链路一致：meta → thought → … → task_complete → task_finish。
        """
        yield {
            "type": "meta",
            "id": str(uuid.uuid4()),
            "data": {
                "session_id": "",
                "is_new_session": False,
                "agent_id": "alert_judge",
                "session_summary": "",
                "ephemeral": True,  # ★ 前端可据此识别"一次性研判，不建会话"
            },
            "timestamp": datetime.now().isoformat(),
            "correlation_id": correlation_id,
        }
        try:
            async for event in self._alert_judge_direct_react(
                alert_json=alert_json,
                session_id="",
                user_id=user_id,
                correlation_id=correlation_id,
            ):
                yield event
        except Exception as e:
            react_logger.error(f"[alert_ephemeral] 异常: {e}", exc_info=True)
            yield {
                "type": "error",
                "id": str(uuid.uuid4()),
                "data": {"content": f"alert 处理异常: {str(e)}"},
                "timestamp": datetime.now().isoformat(),
                "correlation_id": correlation_id,
            }

    async def _alert_judge_direct_react(
        self,
        alert_json: str,
        session_id: str,
        user_id: str,
        correlation_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ alert_judge 专用链路：透传标准三件套适配事件流

        alert_judge 走 src/alert_judge/ 三件套（tools.py / config.py / agent_caller2.py，
        与现场标准文件一一对应）成熟逻辑，产出自己的事件标准
        （thought / chat_stream / tool_start / tool_end / task_complete / error / task_finish），
        不走 DFEcrab 通用事件标准（think_start / think / think_end / tool_call / tool_result / message_end）。

        grpc_server 不做事件类型转换，直接透传给 SSE。
        """
        from mcp_servers.mcp_alert_judge import run as alert_react_run

        correlation_id = correlation_id or str(uuid.uuid4())
        react_logger.info(
            f"[alert_judge] 走专属 pipeline 链路 | "
            f"correlation_id={correlation_id} | alert_json={alert_json[:300]}"
        )

        try:
            async for event in alert_react_run(alert_json, correlation_id=correlation_id):
                # ★ 上下文统计：alert_judge 以 task_complete 终止，本地估算 usage 附加到该事件
                #   （微调模型走文本 ReAct，无 LLM usage；且研判为单轮场景，估算精度要求低）
                if isinstance(event, dict) and event.get("type") == "task_complete" \
                        and isinstance(event.get("data"), dict):
                    try:
                        from src.utils.context_usage import build_context_usage
                        _usage = build_context_usage(
                            system_prompt="你是告警研判助手，基于告警信号与运行数据给出研判结论。",
                            current=alert_json,
                            context_length=self._gateway_context_length(),
                            model=self._gateway_llm_model(),
                        )
                        _usage["source"] = "local_estimate"
                        event = dict(event)
                        event["data"] = dict(event["data"])
                        event["data"]["usage"] = _usage
                    except Exception as _e:
                        react_logger.debug(f"[alert_judge] usage 附加失败（忽略）: {_e}")
                yield event
        except Exception as e:
            react_logger.error(f"[alert_judge] pipeline 异常: {e}", exc_info=True)
            yield {
                "type": "error",
                "id": str(uuid.uuid4()),
                "data": {"content": f"研判流程异常: {str(e)}"},
                "timestamp": datetime.now().isoformat(),
                "correlation_id": correlation_id,
            }

    def _get_gateway_llm_config(self) -> Dict:
        """获取全局默认 LLM 配置（timeout 同 Manager 为 600s）。

        ★ 修复：此前硬编码 provider "qwen3"，导致 /api/models/switch 切换后若 "qwen3"
        仍 enabled 则切换不生效。现改用 current_provider（全局模型），切换即真正生效。
        """
        try:
            provider_cfg = model_manager.get_provider_config()  # 用 current_provider
            if provider_cfg and provider_cfg.get("enabled", False):
                if model_manager._check_alive(provider_cfg, verify_content=True):
                    return {
                        "api_base": provider_cfg.get("api_base", ""),
                        "model_name": provider_cfg.get("model_name", ""),
                        "timeout": provider_cfg.get("timeout", 600),
                        "temperature": provider_cfg.get("temperature", 0.7),
                        "max_tokens": provider_cfg.get("max_tokens", 1024),
                        "api_key": provider_cfg.get("api_key", "not-needed"),
                        "context_length": provider_cfg.get("context_length", DEFAULT_CONTEXT_LENGTH),  # ★ 供上下文占比
                        "think_config": provider_cfg.get("think_config") or None,
                        # ★ 思考开关/模板参数透传（否则白名单会丢掉，现场表现为"配了不生效"）
                        "enable_thinking": provider_cfg.get("enable_thinking"),
                        "chat_template_kwargs": provider_cfg.get("chat_template_kwargs") or None,
                        "provider_name": provider_cfg.get("config_name", ""),
                    }
        except Exception as e:
            logger.warning(f"⚠️ 主模型配置读取失败: {e}")
        # fallback
        try:
            alive = model_manager.get_all_alive_configs()
            if alive:
                return {
                    "api_base": alive[0].get("api_base", ""),
                    "model_name": alive[0].get("model_name", ""),
                    "timeout": alive[0].get("timeout", 600),
                    "temperature": alive[0].get("temperature", 0.7),
                    "max_tokens": alive[0].get("max_tokens", 1024),
                    "api_key": alive[0].get("api_key", "not-needed"),
                    "context_length": alive[0].get("context_length", DEFAULT_CONTEXT_LENGTH),  # ★ 供上下文占比
                    "think_config": alive[0].get("think_config") or None,
                    "enable_thinking": alive[0].get("enable_thinking"),
                    "chat_template_kwargs": alive[0].get("chat_template_kwargs") or None,
                    "provider_name": alive[0].get("config_name", ""),
                }
        except Exception as e:
            logger.warning(f"⚠️ Fallback 模型读取失败: {e}")
        return {}

    def _resolve_agent_llm_config(self, agent_id: str) -> Dict:
        """按优先级解析 Agent 执行用的 LLM 配置（模型选择体系）：

        1. Agent 配置的 model_config（**最高优先级**，固定该模型，不受全局切换影响）
        2. 全局默认模型（current_provider，/api/models/switch 切换即生效）

        返回与 _get_gateway_llm_config 同结构的配置 dict（含 context_length / think_config / provider_name）。
        """
        try:
            cfg_path = PROJECT_ROOT / "agents" / agent_id / "config.json"
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                mc = (data.get("model_config") or "").strip()
                if mc:
                    pc = model_manager.get_provider_config(mc)
                    if pc and pc.get("enabled", False):
                        return {
                            "api_base": pc.get("api_base", ""),
                            "model_name": pc.get("model_name", ""),
                            "timeout": pc.get("timeout", 600),
                            "temperature": pc.get("temperature", 0.7),
                            "max_tokens": pc.get("max_tokens", 2048),
                            "api_key": pc.get("api_key", "not-needed"),
                            "context_length": pc.get("context_length", DEFAULT_CONTEXT_LENGTH),
                            "think_config": pc.get("think_config") or None,
                            "enable_thinking": pc.get("enable_thinking"),
                            "chat_template_kwargs": pc.get("chat_template_kwargs") or None,
                            "provider_name": mc,
                        }
        except Exception as e:
            logger.warning(f"⚠️ Agent 模型解析失败（走全局）: {agent_id}: {e}")
        # 未配置 model_config（或不可用）→ 跟随全局
        cfg = self._get_gateway_llm_config()
        cfg["provider_name"] = cfg.get("provider_name", "")
        return cfg

    def _gateway_context_length(self) -> int:
        """当前网关 LLM 模型的上下文窗口大小（供上下文占比计算）"""
        try:
            return int(self._get_gateway_llm_config().get("context_length", DEFAULT_CONTEXT_LENGTH) or DEFAULT_CONTEXT_LENGTH)
        except Exception:
            return DEFAULT_CONTEXT_LENGTH

    def _gateway_llm_model(self) -> str:
        """当前网关 LLM 模型名（用于上下文占比按模型统计 / 标注占比口径）"""
        try:
            return self._get_gateway_llm_config().get("model_name", "") or ""
        except Exception:
            return ""

    def _context_engine_conf(self) -> Dict:
        """读取上下文引擎配置（dfecrab.json 的 react 段），带默认值。

        段合并兼容：先读 react 段，回落旧 context_engine 段（下个大版本移除回落）。

        - auto_compact_threshold: 上下文占用达到该比例时触发自动压缩（默认 0.85）
        - compact_keep_recent: 压缩后保留的最近消息轮数（默认 2）
        """
        try:
            cfg_path = PROJECT_ROOT / "config" / "dfecrab.json"
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                ce = data.get("react") or data.get("context_engine") or {}
                return {
                    "auto_compact_threshold": float(ce.get("auto_compact_threshold", 0.85)),
                    "compact_keep_recent": int(ce.get("compact_keep_recent", 2)),
                }
        except Exception as e:
            logger.warning(f"⚠️ react/context_engine 配置读取失败: {e}")
        return {"auto_compact_threshold": 0.85, "compact_keep_recent": 2}

    def _scan_agent_descriptions(self) -> Dict[str, Dict]:
        """扫描 agents 目录，优先从 agents_index.json 读取描述（带缓存）"""
        agents_dir = PROJECT_ROOT / "agents"
        if not agents_dir.exists():
            return {}

        # 检查目录修改时间
        current_mtime = agents_dir.stat().st_mtime
        current_snapshot = {}
        for f in agents_dir.iterdir():
            if f.is_dir() and (f / "config.json").exists():
                try:
                    current_snapshot[f.name] = (f / "config.json").stat().st_mtime
                except:
                    pass

        # 未变更，直接返回缓存
        if current_mtime == self._agents_dir_mtime and self._agents_dir_snapshot == current_snapshot:
            return self._agent_descriptions

        # 优先从 agents_index.json 读取描述
        index_file = PROJECT_ROOT / "config" / "agents_index.json"
        index_info = {}
        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                    index_info = index_data.get("agents", {})
            except Exception as e:
                logger.warning(f"⚠️ 读取 {index_file} 失败: {e}")

        # 有变更，重新扫描
        descriptions = {}
        for d in sorted(agents_dir.iterdir()):
            if not d.is_dir():
                continue
            cfg_file = d / "config.json"
            if not cfg_file.exists():
                continue
            try:
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                agent_id = d.name
                if agent_id == "manager_agent":
                    continue
                
                # 优先从 index 获取描述，没有则从 config.json 获取
                index_entry = index_info.get(agent_id, {})
                descriptions[agent_id] = {
                    "name": index_entry.get("name", cfg.get("name", agent_id)),
                    "description": index_entry.get("description", cfg.get("description", "")),
                    "keywords": cfg.get("keywords", []),
                }
            except:
                pass

        self._agent_descriptions = descriptions
        self._agents_dir_mtime = current_mtime
        self._agents_dir_snapshot = current_snapshot
        logger.info(f"🔄 Gateway Agent列表已刷新，共 {len(descriptions)} 个可用Agent")
        return descriptions

    def _build_gateway_agent_list(self) -> tuple:
        """构建 Gateway 可用 Agent 列表 + 动态路由规则（带缓存）

        Returns:
            (agent_list_str, route_rules_str)
        """
        descriptions = self._scan_agent_descriptions()

        agent_lines = []
        route_lines = []

        for agent_id, info in descriptions.items():
            name = info["name"]
            desc = info["description"]
            keywords = info["keywords"]

            # Agent 列表行
            kw_str = "、".join(keywords[:5]) if keywords else ""
            desc_str = f"（关键词：{kw_str}）" if kw_str else ""
            # alert_judge 特殊标注
            if agent_id == "alert_judge":
                desc_str = "（仅处理JSON格式告警信号，不处理自然语言查询）"
            agent_lines.append(f"- {agent_id}（{name}）: {desc}{desc_str}")

            # 动态路由规则行
            if agent_id == "alert_judge":
                # alert_judge 不生成关键词路由，仅在输入为JSON告警格式时匹配
                continue
            if keywords:
                route_lines.append(f"- {'/'.join(keywords[:3])}等 → {agent_id}")
            elif desc:
                route_lines.append(f"- {desc} → {agent_id}")

        agent_list = "\n".join(agent_lines) if agent_lines else "无可调用 Agent"
        route_rules = "\n".join(route_lines) if route_lines else ""
        return agent_list, route_rules

    def _parse_intent_from_json(self, text: str) -> Optional[Dict]:
        """从 LLM 输出的文本中解析意图 JSON

        兼容多种格式：
        - 标准完整 JSON
        - 被 max_tokens 截断的 JSON（缺前或后）
        - JSON 在思考文本中被包裹
        - 无 JSON 时尝试从 thinking 提取 agent
        """
        if not text:
            return None
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.DOTALL)
        text = re.sub(r'<thinking>[\s\S]*?</thinking>', '', text, flags=re.DOTALL)
        # ★ 尝试多种策略提取 JSON
        strategies = [
            # 策略1：找最后一个完整的 {...} 对象
            self._try_extract_json(text),
            # 策略2：如果被截断缺了 {，补上 { 再试
            self._try_extract_json('{' + text) if not text.strip().startswith('{') else None,
            # 策略3：只保留从 { 到 } 的部分（兼容多余文字）
            self._try_extract_json_loose(text),
        ]
        for result in strategies:
            if result is not None:
                return result
        return None

    def _try_extract_json(self, text: str) -> Optional[Dict]:
        """尝试从文本中提取完整 JSON"""
        if not text:
            return None
        last_brace_start = text.rfind('{')
        last_brace_end = text.rfind('}')
        if last_brace_start == -1 or last_brace_end == -1 or last_brace_end <= last_brace_start:
            return None
        json_str = text[last_brace_start:last_brace_end+1]
        attempts = [
            json_str,
            json_str.replace("'", '"'),
            re.sub(r',(\s*[}\]])', r'\1', json_str),
            json_str.replace("，", ",").replace("：", ":").replace("“", '"').replace("”", '"'),
            re.sub(r'(\w+)\s*:', r'"\1":', json_str),
        ]
        for attempt in attempts:
            try:
                parsed = json.loads(attempt)
                if isinstance(parsed, dict):
                    if "target_agent" not in parsed:
                        for alias in ["target", "agent", "agent_id"]:
                            if alias in parsed:
                                parsed["target_agent"] = parsed[alias]
                                break
                    return parsed
            except:
                continue
        return None

    def _try_extract_json_loose(self, text: str) -> Optional[Dict]:
        """宽松模式：从文本中尝试找任何类似 JSON 对象的片段"""
        if not text:
            return None
        # 找所有可能的 { ... } 片段
        brace_starts = [m.start() for m in re.finditer('{', text)]
        brace_ends = [m.start() for m in re.finditer('}', text)]
        for s in reversed(brace_starts):
            for e in brace_ends:
                if e > s:
                    fragment = text[s:e+1]
                    try:
                        parsed = json.loads(fragment)
                        if isinstance(parsed, dict) and ('type' in parsed or 'target_agent' in parsed or 'agent' in parsed):
                            if "target_agent" not in parsed:
                                for alias in ["target", "agent", "agent_id"]:
                                    if alias in parsed:
                                        parsed["target_agent"] = parsed[alias]
                                        break
                            return parsed
                    except:
                        continue
        return None

    def _truncate_system_prompt(self, prompt: str, max_chars: int = 2000) -> str:
        """截断系统提示词中的 Agent 列表（同 Manager 的 _truncate_agent_list）"""
        if not prompt or len(prompt) <= max_chars:
            return prompt
        head_len = int(max_chars * 0.7)
        tail_len = max_chars - head_len
        truncated = prompt[:head_len] + "\n...(Agent列表中间省略，共省略" + str(len(prompt) - max_chars) + "字符)...\n" + prompt[-tail_len:]
        return truncated

    def _is_alert_signal_json(self, message: str) -> bool:
        """判断输入是否是电力告警JSON信号格式。

        匹配字段: station_inside_outer, throbNum, alert_content, signal_package
        4 个中满足至少 2 个，或 message 是可解析 JSON 包含 alert_content
        """
        if not message or not isinstance(message, str):
            return False
        msg = message.strip()
        if not msg.startswith("{"):
            return False
        try:
            obj = json.loads(msg)
        except Exception:
            return False
        if not isinstance(obj, dict):
            return False
        alert_fields = ("station_inside_outer", "throbNum", "alert_content", "signal_package")
        hits = sum(1 for f in alert_fields if f in obj)
        if hits >= 2:
            return True
        # 兼容：数组形式的多条告警
        for f, v in obj.items():
            if isinstance(v, list) and v:
                first = v[0]
                if isinstance(first, dict) and sum(1 for ff in alert_fields if ff in first) >= 2:
                    return True
        return False

    def _match_gateway_rule_based_intent(self, message: str) -> Optional[Dict]:
        """基于 Agent 配置关键词做动态短路路由。

        这里只处理高置信度 simple/query 场景。关键词来自各 Agent 的
        `config.json`，因此是配置驱动而不是写死在代码里。
        """
        clean_message = (message or "").strip()
        if not clean_message:
            return None

        candidates = []
        for agent_id, info in self._scan_agent_descriptions().items():
            for keyword in info.get("keywords", []) or []:
                kw = str(keyword).strip()
                if not kw or len(kw) < 2:
                    continue
                pos = clean_message.find(kw)
                if pos >= 0:
                    candidates.append((len(kw), -pos, agent_id, kw))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        _, _, agent_id, keyword = candidates[0]
        return {
            "type": "simple",
            "category": "query",
            "target_agent": agent_id,
            "reason": f"命中Agent关键词规则: {keyword}"
        }

    def _build_gateway_display_think_skeleton(self, intent: Dict, raw_query: str) -> str:
        """根据稳定 intent 构造展示思考的骨架文本。"""
        query = (raw_query or "").strip() or "当前请求"
        intent_type = intent.get("type", "simple")
        category = intent.get("category", "chat")
        target_agent = intent.get("target_agent", "")
        reason = intent.get("reason", "")
        descriptions = self._scan_agent_descriptions()
        target_name = descriptions.get(target_agent, {}).get("name", target_agent)

        if intent_type == "complex":
            steps = (((intent.get("workflow") or {}).get("steps")) or [])
            step_agents = []
            for step in steps[:2]:
                agent_id = step.get("agent", "")
                display_name = descriptions.get(agent_id, {}).get("name", agent_id or "未知智能体")
                if display_name:
                    step_agents.append(display_name)
            lines = [
                f"用户询问的是{query}，这类请求需要拆成多个步骤协同处理。",
                "当前判断这不是普通对话，而是需要按流程分发的复合型任务。"
            ]
            if step_agents:
                lines.append(f"后续将按{' -> '.join(step_agents)}的顺序继续执行，并汇总处理结果。")
            else:
                lines.append("后续将进入多智能体协作流程，并逐步完成处理。")
            return " ".join(lines)

        if category == "chat" or not target_agent:
            return " ".join([
                f"用户询问的是{query}，当前看更像普通对话或通用问答场景。",
                "这类请求不需要进入专项数据查询链路。",
                "后续将由Manager直接生成回复。"
            ])

        domain_background, next_action = self._build_gateway_display_domain_context(
            query,
            target_name or target_agent or "对应智能体",
            reason
        )
        lines = [
            f"用户询问的是{query}，{domain_background}",
            f"根据路由规则，此类请求更适合交由{target_name or target_agent}处理。"
        ]
        if next_action:
            lines.append(next_action)
        else:
            lines.append("后续将由对应智能体继续完成检索并返回结果。")
        return " ".join(lines)



    def _extract_gateway_display_think_lines(self, text: str, incremental: bool = False) -> List[str]:
        """从模型展示流中抽取<think>标签内的思考句子。
        
        提取<think>和</think>标签之间的完整思考内容。
        """
        if not text:
            return []

        think_start = text.find("<think>")
        think_end = text.find("</think>")
        
        if think_start == -1 or think_end == -1 or think_end <= think_start:
            return []
        
        think_content = text[think_start + len("<think>"):think_end]
        think_content = think_content.replace("\r", "\n").strip()
        
        if not think_content:
            return []

        parts: List[str] = []
        for line in think_content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for seg in re.split(r'(?<=[。！？])', stripped):
                seg = seg.strip()
                if seg:
                    parts.append(seg)
        return parts

    def _chunk_gateway_think_text(self, text: str) -> List[str]:
        """将思考文本切成 2-4 个字的小块，模拟更细粒度的流式输出。"""
        compact = re.sub(r"\s+", "", text or "")
        if not compact:
            return []

        chunks: List[str] = []
        idx = 0
        total = len(compact)
        while idx < total:
            remain = total - idx
            if remain <= 4:
                step = remain
            elif remain == 5:
                step = 2
            else:
                step = 3
            chunks.append(compact[idx:idx + step])
            idx += step

        if len(chunks) >= 2 and len(chunks[-1]) == 1:
            chunks[-2] += chunks[-1]
            chunks.pop()
        return [chunk for chunk in chunks if chunk]

    async def _emit_gateway_think_chunks(self, text: str, delay: float = 0.05):
        """把一段 think 文本按小块连续发给前端。"""
        for chunk in self._chunk_gateway_think_text(text):
            yield {"type": "think", "data": {"content": chunk}}
            await asyncio.sleep(delay)

    def _build_gateway_display_system_prompt(self, agent_list: str) -> str:
        """构建展示用的 Manager 风格提示词，保留中文分析风格，去掉 JSON 输出要求。"""
        manager_prompt = (self._get_agent_system_prompt("manager_agent") or "").strip()
        if manager_prompt:
            manager_prompt = manager_prompt.replace("{{AGENT_LIST}}", agent_list or "无可调用Agent")
            if "【输出格式】" in manager_prompt:
                manager_prompt = manager_prompt.split("【输出格式】", 1)[0].rstrip()
            manager_prompt += (
                "\n\n【输出格式】\n"
                "- 只输出2-3句简短自然的中文分析\n"
                "- 不要JSON，不要Markdown，不要额外说明\n"
                "- 禁止输出英文、步骤编号、检查约束、Draft、Here's a thinking process 等模板内容"
            )
            return self._truncate_system_prompt(manager_prompt, max_chars=2200)

        fallback_prompt = (
            "你是DFEcrab的总调度员(Manager)，负责分析用户意图并将任务分派给合适的Agent。\n\n"
            "【约束】\n"
            "- 只分析最匹配的1个Agent\n"
            "- 禁止输出英文、步骤编号、检查约束、Draft 等模板内容\n"
            "- 只输出2到3句简短自然的中文分析\n"
            "- 不要JSON，不要Markdown，不要额外说明\n\n"
            f"【可调用Agent】\n{agent_list or '无可调用Agent'}"
        )
        return self._truncate_system_prompt(fallback_prompt, max_chars=2200)

    def _build_gateway_display_domain_context(self, query: str, target_name: str, reason: str) -> tuple[str, str]:
        """为展示层生成更自然的业务背景与后续动作。"""
        text = f"{query} {reason}"

        if "受令资格" in text:
            return (
                "这是电网人员资质核验场景，通常需要先识别人员姓名，再确认是否具备受令资格。",
                f"下一步会交给{target_name}继续做人员识别和资格核验。"
            )
        if "异常信号" in text:
            return (
                "这是配网运行监测相关查询，通常需要先明确时间范围，再查看异常信号明细或统计情况。",
                f"下一步会交给{target_name}继续检索异常信号数据。"
            )
        if "跳闸" in text:
            return (
                "这是配网跳闸事件查询场景，通常需要先确定查询时间范围，再查看对应跳闸记录。",
                f"下一步会交给{target_name}继续检索跳闸事件数据。"
            )
        if "早会材料" in text or "早会" in text:
            return (
                "这是电网业务材料汇总场景，通常需要先明确时间范围和主题，再整理对应数据内容。",
                f"下一步会交给{target_name}继续整理相关业务材料。"
            )
        if "保供电" in text:
            return (
                "这是保供电相关业务查询，通常需要结合时间和对象范围整理相关信息。",
                f"下一步会交给{target_name}继续检索保供电相关数据。"
            )
        if "svg" in text.lower():
            return (
                "这是配网设备或线路分组查询场景，通常需要先明确对象范围，再查询对应设备数据。",
                f"下一步会交给{target_name}继续检索对应设备信息。"
            )
        if target_name and target_name != "Manager":
            return (
                f"这属于{target_name}更擅长处理的业务查询场景，需要结合当前问题继续做针对性检索。",
                f"下一步会交给{target_name}继续完成分析和处理。"
            )
        return (
            "这是一个需要结合当前语义继续判断处理方式的请求。",
            "下一步会根据当前预判继续完成后续处理。"
        )

    def _build_gateway_display_user_prompt(
        self,
        intent: Dict,
        raw_query: str,
        target_name: str,
        reason: str,
        step_names: List[str],
    ) -> str:
        """构建展示层的用户提示，尽量贴近 Manager 风格，不直接暴露机器规则术语。"""
        query = (raw_query or "").strip() or "当前请求"

        if intent.get("type") == "complex":
            workflow_line = ""
            if step_names:
                workflow_line = f"\n协作流程：{' -> '.join(step_names)}。"
            return (
                f"用户问题：{query}\n"
                "请像总调度员一样，先判断这不是普通闲聊，而是需要多步骤协作处理的任务。"
                f"{workflow_line}\n"
                "请只输出2到3句自然中文分析。"
            )

        if intent.get("category") == "chat" or not intent.get("target_agent"):
            return (
                f"用户问题：{query}\n"
                "请像总调度员一样，判断这是普通对话或通用问答，给出2到3句自然中文分析。"
            )

        domain_background, next_action = self._build_gateway_display_domain_context(query, target_name, reason)
        return (
            f"用户问题：{query}\n"
            f"业务背景：{domain_background}\n"
            f"当前判断：这个问题更适合交给{target_name}处理。\n"
            f"后续动作：{next_action}\n"
            "请像总调度员一样，只输出2到3句自然中文分析。"
        )

    async def _gateway_model_display_think_stream(self, intent: Dict, raw_query: str):
        """用独立模型流生成前端展示的 think 内容；失败时回退模板骨架。"""
        skeleton = self._build_gateway_display_think_skeleton(intent, raw_query)
        skeleton_lines = [part.strip() for part in skeleton.splitlines() if part.strip()]
        llm_config = self._get_gateway_llm_config()
        # ★ 统一清洗：即使配置误填完整接口地址，也剥成根地址再拼
        api_base = normalize_api_base(llm_config.get("api_base", ""))
        model_name = llm_config.get("model_name")
        api_key = llm_config.get("api_key", "not-needed")

        descriptions = self._scan_agent_descriptions()
        target_agent = intent.get("target_agent", "")
        target_name = descriptions.get(target_agent, {}).get("name", target_agent or "Manager")
        reason = intent.get("reason", "")
        query = (raw_query or "").strip() or "当前请求"
        workflow = intent.get("workflow") or {}
        steps = workflow.get("steps") or []
        step_names = []
        for step in steps[:3]:
            agent_id = step.get("agent", "")
            if agent_id:
                step_names.append(descriptions.get(agent_id, {}).get("name", agent_id))
        agent_list, _ = self._build_gateway_agent_list()

        if not api_base or not model_name:
            async for line in self._stream_gateway_display_think(skeleton):
                async for event in self._emit_gateway_think_chunks(line, delay=0.04):
                    yield event
            yield {"type": "think_end", "data": {"content": skeleton}}
            return

        system_prompt = self._build_gateway_display_system_prompt(agent_list)
        user_prompt = self._build_gateway_display_user_prompt(
            intent=intent,
            raw_query=query,
            target_name=target_name,
            reason=reason,
            step_names=step_names,
        )

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": True,
            "temperature": 0.25,
            "max_tokens": 1024,
        }
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"

        raw_text = ""
        emitted_lines: List[str] = []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                async with client.stream(
                    "POST",
                    f"{api_base}/chat/completions",
                    json=payload,
                    headers=headers
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except Exception:
                            continue

                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        delta_text = delta.get("content") or delta.get("reasoning_content") or ""
                        if not delta_text:
                            continue
                        raw_text += delta_text

                        candidate_lines = self._extract_gateway_display_think_lines(raw_text, incremental=True)
                        if len(candidate_lines) < 1:
                            continue

                        while len(emitted_lines) < len(candidate_lines):
                            current_line = candidate_lines[len(emitted_lines)]
                            emitted_lines.append(current_line)
                            async for event in self._emit_gateway_think_chunks(current_line, delay=0.03):
                                yield event
        except Exception as e:
            logger.warning(f"⚠️ Gateway 展示思考流生成失败，回退模板: {e}")
            raw_text = ""
            emitted_lines = []

        final_lines = self._extract_gateway_display_think_lines(raw_text)
        logger.info(f"🧠 [Gateway] 展示流原文预览: {(raw_text or '')[:200]}")
        logger.info(f"🧠 [Gateway] 展示流抽取句数: {len(final_lines)}")
        if len(final_lines) < 1:
            final_text = skeleton
            for line in skeleton_lines[len(emitted_lines):]:
                async for event in self._emit_gateway_think_chunks(line, delay=0.04):
                    yield event
        else:
            if len(final_lines) > 4:
                final_lines = final_lines[:4]
            if len(final_lines) < 3:
                for skeleton_line in skeleton_lines:
                    if skeleton_line not in final_lines:
                        final_lines.append(skeleton_line)
                    if len(final_lines) >= 3:
                        break
            for line in final_lines[len(emitted_lines):]:
                async for event in self._emit_gateway_think_chunks(line, delay=0.04):
                    yield event
            final_text = "\n".join(final_lines)
            logger.info("🧠 [Gateway] 展示思考已使用模型流输出")

        yield {"type": "think_end", "data": {"content": final_text}}

    async def _stream_gateway_display_think(self, think_text: str):
        """按句流式发送伪思考文本，保持 WS 对话体验。"""
        for line in [part.strip() for part in (think_text or "").splitlines() if part.strip()]:
            yield line
            await asyncio.sleep(0.12)

    async def _gateway_llm_think_stream(self, message: str, session_id: str):
        """Gateway 轻量意图识别。

        先走基于 Agent 配置关键词的动态规则短路；未命中时，再用非流式
        `json_object` 方式做结构化意图识别，避免 WS 首层继续依赖思维链。
        """
        clean_message = (message or "").strip()

        rule_intent = self._match_gateway_rule_based_intent(clean_message)
        if rule_intent:
            logger.info(f"🧠 [Gateway] 意图识别: {rule_intent.get('type')}/{rule_intent.get('category')}")
            if rule_intent.get("target_agent"):
                logger.info(f"   └─ 目标 Agent: {rule_intent['target_agent']}")
            yield {"type": "think_end", "data": {"content": clean_message, "intent": rule_intent, "replace": True}}
            return

        llm_config = self._get_gateway_llm_config()
        if not llm_config.get("api_base"):
            logger.error("❌ Gateway LLM 配置不可用，降级")
            fallback_intent = {"type": "simple", "category": "chat", "reason": "LLM不可用"}
            yield {"type": "think_end", "data": {"content": clean_message, "intent": fallback_intent, "replace": True}}
            return

        agent_list, route_rules = self._build_gateway_agent_list()
        system_prompt = f"""你是意图识别助手，将用户问题路由到正确的智能体。

【路由规则】
{route_rules}
- 其他 → default

【输出要求】
- 只输出一个 JSON 对象
- 禁止解释、分析、Markdown、<think>、额外文字
- simple/chat:
{{"type":"simple","category":"chat","reason":"理由"}}
- simple/query:
{{"type":"simple","category":"query","target_agent":"agent_id","reason":"理由"}}
- complex:
{{"type":"complex","category":"xxx","reason":"理由","workflow":{{"steps":[{{"agent":"xxx","action":"xxx","description":"xxx"}}]}}}}
- simple 非 chat 时，target_agent 和 category 必须同时出现
- 字段名必须是 target_agent，禁止用 target、agent、agent_id 等别名"""
        system_prompt = self._truncate_system_prompt(system_prompt, max_chars=2000)

        user_prompt = f"""用户消息：{clean_message}

可用Agent：
{agent_list}

请返回一个 JSON 对象。"""

        api_base = llm_config["api_base"]
        model_name = llm_config.get("model_name", "default")
        timeout = llm_config.get("timeout", 600)
        api_key = llm_config.get("api_key", "not-needed")
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": min(llm_config.get("max_tokens", 256), 256),
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{api_base}/chat/completions",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
        except Exception as e:
            logger.error(f"❌ Gateway 轻量意图识别失败: {e}")
            fallback_intent = {"type": "simple", "category": "chat", "reason": "Gateway意图识别失败"}
            yield {
                "type": "think_end",
                "data": {
                    "content": clean_message,
                    "intent": fallback_intent,
                    "replace": True
                }
            }
            return

        choice = (result.get("choices") or [{}])[0]
        message_obj = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")
        content = (
            message_obj.get("content")
            or message_obj.get("reasoning_content")
            or ""
        )
        if finish_reason == "length":
            logger.warning("⚠️ Gateway 轻量意图识别仍被截断，准备降级")

        intent = self._parse_intent_from_json(content)
        if not intent:
            logger.warning("⚠️ Gateway 轻量意图识别 JSON 解析失败，降级为 chat")
            intent = {"type": "simple", "category": "chat", "reason": "Gateway意图识别JSON解析失败"}

        logger.info(f"🧠 [Gateway] 意图识别: {intent.get('type')}/{intent.get('category')}")
        if intent.get("target_agent"):
            logger.info(f"   └─ 目标 Agent: {intent['target_agent']}")

        yield {"type": "think_end", "data": {"content": content, "intent": intent, "replace": True}}

    @staticmethod
    def _zk_instance_agent_id(inst: Dict[str, Any]) -> str:
        """从 ZK 实例记录解析 agent_id（收敛：网关所有解析点共用，杜绝散落式 split）。

        命名约定（★ 步骤4 统一）：worker/manager 均以 metadata.agent_id 为准；
        旧 `default_agent` 服务节点自部署以来恒代表 dfecrab（default→dfecrab 更名），
        兼容期无 metadata 时直接归为 dfecrab，避免再产出 'default' 触发迁移告警刷屏。
        """
        try:
            metadata = inst.get("metadata") or {}
            if metadata.get("agent_id"):
                return str(metadata["agent_id"])
            service_name = str(inst.get("service_name", "") or "")
            sid = str(inst.get("service_id", "") or "")
            if service_name == "default_agent":
                return "dfecrab"  # 兼容旧注册：default_agent 节点 ⇔ dfecrab
            if "_agent_" in sid:
                return sid.split("_agent_")[0]
            parts = sid.split("_")
            return parts[0] if parts else "unknown"
        except Exception:
            return "unknown"

    def _discover_worker_service(self, agent_id: str) -> Optional[Dict]:
        """通过 ZK 发现 Worker Agent"""
        if not self._zk_discovery:
            logger.error("❌ ZK 服务发现未初始化")
            return None
        instances = self._zk_discovery.discover_service("worker_agent")
        if not instances:
            instances = self._zk_discovery.discover_service("default_agent")
        if not instances:
            logger.warning(f"⚠️ 未找到任何 Worker 实例")
            return None
        for inst in instances:
            if inst.get("metadata", {}).get("agent_id") == agent_id:
                logger.info(f"🔍 发现 Worker [{agent_id}]: {inst['host']}:{inst['port']}")
                return inst
        logger.error(f"❌ 未找到 Worker: {agent_id}")
        return None

    def _call_worker_grpc(self, host: str, port: int, session_id: str, message: str,
                          user_id: str = "") -> Dict:
        """调用 Worker 的 gRPC Execute"""
        channel = None
        try:
            channel = grpc.insecure_channel(
                f"{host}:{port}",
                options=[
                    ('grpc.max_send_message_length', 50 * 1024 * 1024),
                    ('grpc.max_receive_message_length', 50 * 1024 * 1024),
                ]
            )
            stub = dfecrab_pb2_grpc.AgentServiceStub(channel)
            request = dfecrab_pb2.ExecuteRequest(
                session_id=session_id,
                input_data={"message": message},
                skills=[],
                instruction=message,
                timeout=600,
                user_id=user_id,
            )
            response = stub.Execute(request, timeout=600.0)
            result = {
                "success": response.success,
                "agent_id": response.agent_id,
                "result": response.result,
                "error": response.error,
            }
            return result
        except Exception as e:
            logger.error(f"❌ Worker gRPC 调用失败: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if channel:
                try:
                    channel.close()
                except Exception:
                    pass

    # 任务相关 HTTP handler 已全部迁移至 src/task/api_routes.py

    async def _generate_session_summary(self, message: str) -> str:
        """生成会话摘要：调用 LLM 生成 <=30 字摘要，失败时降级为截取前30字"""
        from src.agent.llm.think import remove_think_tags, get_default_think_config
        
        # 先尝试 LLM 生成真实摘要
        try:
            llm_config = self._get_gateway_llm_config()
            if llm_config:
                from src.agent.llm.adapter import LLMAdapter
                llm = LLMAdapter(llm_config)
                prompt = f"请为以下对话生成一个不超过30字的简短摘要：\n\n用户: {message}"
                summary = await llm.call(
                    prompt=prompt,
                    system_prompt="你是会话摘要助手，只输出不超过30字的摘要，不要输出其他内容。",
                    max_tokens=50
                )
                summary = summary.strip()
                if summary and len(summary) <= 50:
                    logger.info(f"LLM 生成会话摘要: {summary}")
                    return summary[:30] + "..." if len(summary) > 30 else summary
        except Exception as e:
            logger.debug(f"LLM 摘要生成失败，降级为截取: {e}")
        
        # 降级：直接截取用户消息前30字符
        think_config = get_default_think_config()
        clean = remove_think_tags(message, think_config)
        clean = re.sub(r'\n+', ' ', clean).strip()
        return clean[:30] + "..." if len(clean) > 30 else clean
    
    def _build_enhanced_message(
        self,
        message: str,
        session_id: str,
        session_summary: str,
        session_history: List[Dict]
    ) -> str:
        """
        构建增强的消息，包含 session 上下文和当前时间信息
        
        这样 Manager Agent 可以了解：
        1. 当前会话的主题
        2. 之前的对话历史
        3. 用户消息在上下文中的位置
        4. 当前时间（用户消息中的相对时间已被 Gateway 解析为具体日期）
        """
        # 获取时间上下文
        time_context = get_time_context()
        
        # 如果有历史消息，添加到消息前面作为上下文
        if session_history:
            history_text = "\n\n".join([
                f"[{'用户' if m['role'] == 'user' else '助手'}]: {m['content']}"
                for m in session_history[-5:]  # 最近 5 条
            ])
            
            enhanced = f"""{time_context}

[会话上下文]
主题: {session_summary}
Session ID: {session_id}

历史对话:
{history_text}

---
当前消息: {message}"""
        else:
            enhanced = f"""{time_context}

[新会话]
主题: {session_summary}
Session ID: {session_id}

消息: {message}"""
        
        return enhanced

    # ==================== Session 管理接口 ====================

    def _identity(self, request, fallback: str = "default") -> str:
        """从请求头解析当前用户（唯一身份来源）"""
        return request.headers.get("x-user-id", fallback)

    async def _handle_list_sessions(self, request) -> Dict[str, Any]:
        """列出会话（数据范围 all 看全部，own 只看自己的）"""
        from src.gateway.session_handler import SessionService
        params = request.query_params
        include_empty = str(params.get("include_empty", "false")).lower() in ("1", "true", "yes")
        return SessionService.list_sessions(
            user_id=self._identity(request),
            limit=int(params.get("limit", 50)),
            include_empty=include_empty,
        )

    async def _handle_create_session(self, request) -> Dict[str, Any]:
        """创建新会话（归属当前用户）"""
        from src.gateway.session_handler import SessionService
        body = await request.json()
        return SessionService.create_session(
            user_id=self._identity(request),
            topic=body.get("topic")
        )

    async def _handle_get_session(self, request, **kwargs) -> Dict[str, Any]:
        """获取会话详情（带权限检查）"""
        from src.gateway.session_handler import SessionService
        session_id = kwargs.get('session_id') or request.path_params.get('session_id')
        return SessionService.get_session(
            session_id=session_id,
            current_user=self._identity(request)
        )

    async def _handle_get_session_messages(self, request, **kwargs) -> Dict[str, Any]:
        """获取会话消息历史（带权限检查）"""
        from src.gateway.session_handler import SessionService
        session_id = kwargs.get('session_id') or request.path_params.get('session_id')
        params = request.query_params
        return SessionService.get_session_messages(
            session_id=session_id,
            current_user=self._identity(request),
            limit=int(params.get("limit", 20))
        )

    async def _handle_get_session_usage(self, request, **kwargs) -> Dict[str, Any]:
        """获取会话上下文占用统计（P1 + P3：累计 token 用量 + 每轮明细 + 按模型聚合，带权限检查）。

        数据全部来自已落库的 Message.tokens / model / metadata.context_length，纯只读聚合，无 LLM 调用。

        查询参数：
          group_by=model  按模型分组返回累计用量（多模型对话时查看各模型 token 消耗，对齐 CodeBuddy /cost）
        """
        from src.gateway.session_handler import SessionService
        session_id = kwargs.get('session_id') or request.path_params.get('session_id')
        params = request.query_params
        group_by = str(params.get("group_by", ""))
        res = SessionService.get_session_messages(
            session_id=session_id,
            current_user=self._identity(request),
            limit=100,
        )
        if not res.get("success"):
            return res

        msgs = res.get("messages", [])
        total_prompt = total_completion = total_total = 0
        rounds = []
        # ★ P3：按模型聚合 {model: {prompt, completion, total, context_length, last_prompt}}
        by_model: Dict[str, Dict] = {}
        for m in msgs:
            tk = m.get("tokens") or {}
            p = int(tk.get("prompt") or 0)
            c = int(tk.get("completion") or 0)
            t = int(tk.get("total") or 0)
            total_prompt += p
            total_completion += c
            total_total += t
            if m.get("role") == "assistant" and t > 0:
                rounds.append({
                    "message_id": m.get("id"),
                    "timestamp": m.get("timestamp"),
                    "prompt": p, "completion": c, "total": t,
                    "model": m.get("model"),
                })
                model = m.get("model") or "unknown"
                bm = by_model.setdefault(
                    model, {"prompt": 0, "completion": 0, "total": 0, "context_length": None, "last_prompt": 0}
                )
                bm["prompt"] += p
                bm["completion"] += c
                bm["total"] += t
                bm["last_prompt"] = p
                if bm["context_length"] is None:
                    bm["context_length"] = (m.get("metadata") or {}).get("context_length")

        # 当前模型上下文窗口
        context_length = DEFAULT_CONTEXT_LENGTH
        try:
            context_length = int(self._get_gateway_llm_config().get("context_length", DEFAULT_CONTEXT_LENGTH) or DEFAULT_CONTEXT_LENGTH)
        except Exception:
            pass

        last_prompt = rounds[-1]["prompt"] if rounds else 0
        last_used_percent = round(last_prompt / context_length * 100, 1) if context_length and last_prompt else 0.0
        peak = max((r["prompt"] for r in rounds), default=0)
        peak_used_percent = round(peak / context_length * 100, 1) if context_length and peak else 0.0
        for r in rounds:
            r["used_percent"] = round(r["prompt"] / context_length * 100, 1) if context_length else 0.0

        result = {
            "success": True,
            "session_id": session_id,
            "summary": {
                "turns": len(rounds),
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_total,
                "context_length": context_length,
                "last_prompt_tokens": last_prompt,
                "last_used_percent": last_used_percent,
                "peak_used_percent": peak_used_percent,
            },
            "rounds": rounds,
        }
        # ★ P3：按模型聚合（多模型对话成本统计）
        if group_by == "model":
            by_model_out: Dict[str, Dict] = {}
            for model, bm in by_model.items():
                clen = int(bm["context_length"] or context_length or DEFAULT_CONTEXT_LENGTH)
                last_pct = round(bm["last_prompt"] / clen * 100, 1) if clen and bm["last_prompt"] else 0.0
                by_model_out[model] = {
                    "total_prompt_tokens": bm["prompt"],
                    "total_completion_tokens": bm["completion"],
                    "total_tokens": bm["total"],
                    "context_length": clen,
                    "last_used_percent": last_pct,
                }
            result["by_model"] = by_model_out
        return result

    async def _handle_usage_stats(self, request) -> Dict[str, Any]:
        """token 用量统计（纯 token 维度，本地模型无费用）。

        GET /api/v2/usage/stats?period=day|week|month&start=YYYY-MM-DD&end=YYYY-MM-DD
        权限：admin 看全部用户用量；普通用户只看自己的用量（与历史/记忆接口一致）。
        """
        from src.utils.usage_aggregator import resolve_period, aggregate_usage
        from src.gateway.permission import PermissionService
        from datetime import timedelta
        params = request.query_params
        period = str(params.get("period", "month"))
        start, end = resolve_period(period, params.get("start"), params.get("end"))
        # 权限隔离：admin 看全部；普通 user 只统计自己的会话
        current_user = self._identity(request)
        user_filter = None
        try:
            if not PermissionService().is_admin(current_user):
                user_filter = current_user
        except Exception:
            user_filter = current_user
        current = aggregate_usage(start, end, user_id=user_filter)
        # 较上期：同等长度窗口向前推
        span = (end - start).days + 1
        prev_start = start - timedelta(days=span)
        prev_end = start - timedelta(days=1)
        prev = aggregate_usage(prev_start, prev_end, user_id=user_filter)
        vs_last = None
        if prev["totals"]["total_tokens"] > 0:
            vs_last = round(
                (current["totals"]["total_tokens"] - prev["totals"]["total_tokens"])
                / prev["totals"]["total_tokens"] * 100, 1
            )
        return {
            "success": True,
            "period": period,
            "user_id": user_filter or "*",  # 统计范围（* = 全部用户 / admin）
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "totals": current["totals"],
            "comparison": {"vs_last_period_percent": vs_last},
            "by_model": current["by_model"],
            "by_day": current["by_day"],
        }

    async def _handle_close_session(self, request, **kwargs) -> Dict[str, Any]:
        """删除会话（带权限检查）"""
        from src.gateway.session_handler import SessionService
        session_id = kwargs.get('session_id') or request.path_params.get('session_id')
        return SessionService.delete_session(
            session_id=session_id,
            current_user=self._identity(request)
        )

    async def _handle_list_users(self, request) -> Dict[str, Any]:
        """列出所有账号（仅 admin）"""
        from src.gateway.user_service import UserService
        return UserService.list_users()

    async def _handle_create_user(self, request) -> Dict[str, Any]:
        """新增账号（仅 admin）"""
        from src.gateway.user_service import UserService
        body = await request.json()
        return UserService.create_user(
            user_id=body.get("user_id"),
            role=body.get("role", "guest")
        )

    async def _handle_update_user(self, request, **kwargs) -> Dict[str, Any]:
        """修改账号角色（仅 admin）"""
        from src.gateway.user_service import UserService
        user_id = kwargs.get('user_id') or request.path_params.get('user_id')
        body = await request.json()
        return UserService.update_user(
            user_id=user_id, role=body.get("role"), current_user=self._identity(request))

    async def _handle_delete_user(self, request, **kwargs) -> Dict[str, Any]:
        """删除账号（仅 admin）"""
        from src.gateway.user_service import UserService
        user_id = kwargs.get('user_id') or request.path_params.get('user_id')
        return UserService.delete_user(user_id=user_id, current_user=self._identity(request))

    # ================================================================
    # Classic Gateway 全部路由处理器（移植）
    # ================================================================

    # --- Worker Agent 管理（新增） ---

    async def _handle_list_workers(self, request) -> Dict[str, Any]:
        """列出所有通过 Zookeeper 注册的 Worker Agent"""
        try:
            if not self._zk_discovery:
                return {"success": False, "error": "Zookeeper 服务发现未初始化"}

            instances = self._zk_discovery.discover_service("worker_agent")

            workers = []
            for inst in instances:
                # ★ 收敛：统一走 _zk_instance_agent_id 解析（步骤4）
                service_id = inst.get("service_id", "")
                agent_id = self._zk_instance_agent_id(inst)

                workers.append({
                    "agent_id": agent_id,
                    "host": inst["host"],
                    "port": inst["port"],
                    "version": inst.get("metadata", {}).get("version", ""),
                    "service_id": service_id,
                })

            # 按 agent_id 分组
            grouped = {}
            for w in workers:
                aid = w["agent_id"]
                if aid not in grouped:
                    grouped[aid] = []
                grouped[aid].append(w)

            return {
                "success": True,
                "total": len(workers),
                "unique_agents": len(grouped),
                "workers": workers,
                "grouped": grouped
            }
        except Exception as e:
            logger.error(f"列出 Worker Agents 失败: {e}")
            return {"success": False, "error": str(e)}

    # --- Agent 管理 ---

    def _resolve_agent_model(self, model_config: str) -> Dict[str, Any]:
        """解析 agent 的模型三元组（配置值 / 展示名 / 上下文窗口），一次 provider 查找。

        model_config（= GET /api/models 的 config_name）有值 → 取该 provider；
        为空（跟随全局）→ 取当前全局模型。取不到时 model_name 回退空串、窗口回退 None（前端自行兜底）。
        """
        mc = (model_config or "").strip()
        try:
            from src.services.model_manager import model_manager as _mm
            cfg = _mm.get_provider_config(mc) if mc else None
            if not cfg:
                cur = _mm.get_current_provider_name() or ""
                cfg = _mm.get_provider_config(cur) if cur else None
            if not cfg:
                alive = _mm.get_all_alive_configs()
                cfg = alive[0] if alive else None
        except Exception:
            cfg = None
        cfg = cfg or {}
        return {
            "model_config": mc,
            "model_name": cfg.get("model_name", ""),
            "context_length": cfg.get("context_length"),
        }

    def _sync_agents_index(self, agent_id: str, config: Dict[str, Any]) -> None:
        """将 Agent 信息同步到 config/agents_index.json（描述索引）"""
        try:
            index_file = PROJECT_ROOT / "config" / "agents_index.json"
            index_data = {"version": "1.0", "agents": {}}
            if index_file.exists():
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
            agents_map = index_data.setdefault("agents", {})
            skills = config.get("enabled_skills") or []
            if not skills:
                tools_path = PROJECT_ROOT / "agents" / agent_id / "tools.json"
                if tools_path.exists():
                    with open(tools_path, 'r', encoding='utf-8') as f:
                        skills = json.load(f).get("enabled_skills", []) or []
            agents_map[agent_id] = {
                "icon": config.get("icon", ""),
                "name": config.get("name", agent_id),
                "description": config.get("description", ""),
                "skills": skills,
            }
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Index] agents_index.json 已同步: {agent_id}")
        except Exception as e:
            logger.warning(f"⚠️ 同步 agents_index.json 失败: {e}")

    def _load_agent_meta(self, agent_id: str) -> Dict[str, Any]:
        """从 agents 目录读取智能体的元信息（图标、配色、技能）
        
        agent_id 可能是 'dm' 或 'dm_agent'，尝试多种路径匹配
        PROJECT_ROOT 指向项目根目录，agents 在项目根目录下
        """
        meta = {}
        try:
            agents_base = PROJECT_ROOT / "agents"
            logger.info(f"🔍 [META] agent_id={agent_id}, agents_base={agents_base}, exists={agents_base.exists()}")
            
            # 尝试多种目录名: agent_id, agent_id_agent, agent_id+agent
            candidates = [agent_id]
            if not agent_id.endswith("_agent"):
                candidates.append(f"{agent_id}_agent")
            
            agents_dir = None
            for candidate in candidates:
                d = agents_base / candidate
                logger.info(f"🔍 [META] 尝试路径: {d}, exists={d.exists()}")
                if d.exists():
                    agents_dir = d
                    break
            
            if not agents_dir:
                logger.warning(f"⚠️ [META] agent [{agent_id}] 未找到对应目录, candidates={candidates}, agents_base={agents_base}")
                return meta
                
            # 读取 config.json 获取图标配色
            config_path = agents_dir / "config.json"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                meta["icon"] = cfg.get("icon", "")
                meta["iconColor"] = cfg.get("iconColor", "")
                meta["bgColor"] = cfg.get("bgColor", "")
                meta["name"] = cfg.get("name", "")
                meta["agent_type"] = cfg.get("agent_type", "")
                meta["description"] = cfg.get("description", "")
                meta["system_prompt"] = cfg.get("system_prompt", "")
                meta["model_config"] = cfg.get("model_config", "")
                meta["parent_agent"] = cfg.get("parent_agent")
                logger.info(f"✅ [META] agent [{agent_id}] 读取 config.json 成功: icon={meta.get('icon')}, iconColor={meta.get('iconColor')}, bgColor={meta.get('bgColor')}, agent_type={meta.get('agent_type')}")
            else:
                logger.warning(f"⚠️ [META] agent [{agent_id}] config.json 不存在: {config_path}")
            # 读取 tools.json 获取技能列表
            tools_path = agents_dir / "tools.json"
            if tools_path.exists():
                with open(tools_path, 'r', encoding='utf-8') as f:
                    tools = json.load(f)
                meta["skills"] = tools.get("enabled_skills", [])
                logger.info(f"✅ [META] agent [{agent_id}] 读取 tools.json 成功: skills={meta.get('skills')}")
            else:
                logger.info(f"ℹ️ [META] agent [{agent_id}] tools.json 不存在: {tools_path}")
        except Exception as e:
            logger.warning(f"⚠️ 读取 agent [{agent_id}] 元信息失败: {e}")
        return meta

    def _agents_list_ttl(self) -> float:
        """/api/agents 结果缓存 TTL（读 cache.agents_list_ttl_s，缺省 1.5s）"""
        try:
            from src.config.app_config import section as _cfg_section
            _ttl = (_cfg_section("cache") or {}).get("agents_list_ttl_s", 1.5)
            return float(_ttl)
        except Exception:
            return 1.5

    async def _handle_list_agents(self, request) -> Dict[str, Any]:
        """列出所有智能体（扫描 agents/ 目录 + Zookeeper 状态补充）

        C-2：TTL 缓存——TTL 内重复调用直接返回进程内缓存（二次访问 <10ms），
        避免每次前端轮询都重扫 agents/ 目录与 ZK；TTL 到期后自动重建，状态保持新鲜。
        """
        try:
            # ★ C-2：TTL 缓存命中
            _ttl = self._agents_list_ttl()
            _now = time.time()
            if self._agents_list_cache is not None and (_now - self._agents_list_cache_at) < _ttl:
                logger.debug(f"[API] /api/agents 命中 TTL 缓存（{( _now - self._agents_list_cache_at):.2f}s < {_ttl}s）")
                return self._agents_list_cache

            all_agents = []
            logger.info(f"📋 [API] _handle_list_agents 被调用, PROJECT_ROOT={PROJECT_ROOT}")

            # 0. 加载 agents_index.json 作为描述回退源（config.json 未写 description 的老 Agent 用）
            index_descs = {}
            index_file = PROJECT_ROOT / "config" / "agents_index.json"
            if index_file.exists():
                try:
                    with open(index_file, 'r', encoding='utf-8') as f:
                        index_descs = json.load(f).get("agents", {})
                except Exception:
                    pass

            # 1. 扫描 agents/ 目录获取所有智能体配置
            agents_base = PROJECT_ROOT / "agents"
            if agents_base.exists():
                for agent_dir in sorted(agents_base.iterdir()):
                    if agent_dir.is_dir():
                        config_path = agent_dir / "config.json"
                        if config_path.exists():
                            agent_id = agent_dir.name
                            meta = self._load_agent_meta(agent_id)
                            idx_meta = index_descs.get(agent_id, {})
                            agent_data = {
                                "agent_id": agent_id,
                                "agent_type": meta.get("agent_type", ""),
                                "icon": meta.get("icon", ""),
                                "iconColor": meta.get("iconColor", ""),
                                "bgColor": meta.get("bgColor", ""),
                                "name": meta.get("name", ""),
                                "description": meta.get("description") or idx_meta.get("description", ""),
                                "model_config": meta.get("model_config", ""),
                                "model_name": "",
                                "skills": meta.get("skills", []),
                            }
                            all_agents.append(agent_data)
            
            # 2. 获取 Zookeeper 中的 Worker Agents、Default Agent 和 Manager Agent
            try:
                if self._zk_discovery:
                    worker_instances = self._zk_discovery.discover_service("worker_agent") or []
                    manager_instances = self._zk_discovery.discover_service("manager_agent") or []
                    default_instances = self._zk_discovery.discover_service("default_agent") or []
                    all_instances = worker_instances + manager_instances + default_instances
                    # 同一 agent 多实例时只保留最新注册，避免返回死进程地址
                    all_instances = _pick_latest_instances(all_instances)
                    
                    if all_instances:
                        for inst in all_instances:
                            service_id = inst.get('service_id', '')
                            
                            # ★ 收敛：统一走 _zk_instance_agent_id 解析（不再产出 'default' 触发迁移告警）
                            agent_id = self._zk_instance_agent_id(inst)

                            # 根据 ZK 注册的服务类型判断 agent_type（manager 特判；default/worker 由末段按默认助手归一，
                            # 不再硬编码 dfecrab=default —— agent_type=default 跟随默认助手，切换默认后旧的自动变 worker）
                            service_name = inst.get('service_name', '')
                            if service_name == "manager_agent" or agent_id in ("manager", "manager_agent"):
                                agent_type = "manager"
                            else:
                                agent_type = "worker"
                            
                            if agent_id not in [a.get('agent_id') for a in all_agents]:
                                meta = self._load_agent_meta(agent_id)
                                # 本地 agents/ 目录无此 Agent（无 config.json）的 ZK 注册视为孤儿，
                                # 如 default_localhost.localdomain_* 之类的残留进程，跳过不展示
                                if not meta and agent_id != "manager_agent":
                                    logger.warning(
                                        f"⚠️ [API] 跳过 ZK 孤儿注册: agent_id={agent_id}, "
                                        f"service_id={service_id}（本地 agents/ 目录无此 Agent）"
                                    )
                                    continue
                                logger.info(f"📋 [API] ZK agent [{agent_id}] meta={meta}")
                                agent_data = {
                                    "agent_id": agent_id,
                                    "agent_type": agent_type,
                                    "status": "active",
                                    "address": f"{inst.get('host')}:{inst.get('port')}",
                                    "service_id": service_id
                                }
                                agent_data.update(meta)
                                all_agents.append(agent_data)
                            else:
                                # ZK 中发现的 agent 已在本地存在，补充 ZK 信息
                                for existing in all_agents:
                                    if existing.get('agent_id') == agent_id:
                                        existing["status"] = "active"
                                        existing["address"] = f"{inst.get('host')}:{inst.get('port')}"
                                        existing["service_id"] = service_id
                                        if not existing.get("agent_type"):
                                            existing["agent_type"] = agent_type
                                        break
            except Exception as e:
                logger.warning(f"⚠️ 获取 Agents 失败: {e}")
            
            # 根据 agent_type 统一颜色（同类 agent 使用相同配色）
            type_colors = {
                "manager": {"iconColor": "#FFB800", "bgColor": "#FFF8E1"},
                "worker":  {"iconColor": "#2196F3", "bgColor": "#E3F2FD"},
                "default": {"iconColor": "#FF6B6B", "bgColor": "#FFE5E5"},
            }

            # 收集 ZK 中活跃的 agent_id 集合，用于判断 status
            zk_active_ids = set()
            try:
                if self._zk_discovery:
                    for service_type in ["worker_agent", "manager_agent", "default_agent"]:
                        for inst in (self._zk_discovery.discover_service(service_type) or []):
                            # ★ 收敛：统一解析（不再产出 'default'）
                            zk_active_ids.add(self._zk_instance_agent_id(inst))
            except Exception:
                pass

            for agent in all_agents:
                # ★ agent_type 动态归一：default 全局唯一且跟随默认助手，manager 保持，其余 worker
                #（读侧修正，兼容历史 config.json 里 dfecrab 恒 default 等脏数据）
                aid = agent.get("agent_id", "")
                at = self._normalize_agent_type(aid, agent.get("agent_type", ""))
                agent["agent_type"] = at
                colors = type_colors.get(at, type_colors["default"])
                if not agent.get("iconColor"):
                    agent["iconColor"] = colors["iconColor"]
                if not agent.get("bgColor"):
                    agent["bgColor"] = colors["bgColor"]

                # 设置 status: 纯粹根据 ZK 注册记录判断
                # active: ZK 中有注册（正在运行）
                # inactive: ZK 中无注册（未运行）
                if not agent.get("status"):
                    aid = agent.get("agent_id", "")
                    if aid in zk_active_ids:
                        agent["status"] = "active"
                    else:
                        agent["status"] = "inactive"

            # 统一输出格式：确保字段顺序一致
            default_agent_id = self._default_agent_id()
            formatted_agents = []
            for agent in all_agents:
                aid = agent.get("agent_id", "")
                # ★ 模型字段一次解析（model_config 为空=跟随全局，model_name/context_length 已按全局解析好）
                am = self._resolve_agent_model(agent.get("model_config", ""))
                formatted = {
                    "agent_id": aid,
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", "inactive"),
                    "icon": agent.get("icon", ""),
                    "iconColor": agent.get("iconColor", ""),
                    "bgColor": agent.get("bgColor", ""),
                    "name": agent.get("name", ""),
                    "description": agent.get("description", ""),
                    "model_config": am["model_config"],
                    "model_name": am["model_name"],
                    "context_length": am["context_length"],
                    "skills": agent.get("skills", []),
                    # ★ 派生字段：推荐 MCP（服务级绑定反向聚合）+ 默认助手标记
                    "recommended_mcp": self._recommended_mcp_servers(aid),
                    "is_default": aid == default_agent_id,
                }
                # 可选字段（ZK 发现的 agent 才有）
                if agent.get("address"):
                    formatted["address"] = agent["address"]
                if agent.get("service_id"):
                    formatted["service_id"] = agent["service_id"]
                formatted_agents.append(formatted)

            # ★ C-2：重建后写入 TTL 缓存（含默认助手 ID，供前端预选/高亮）
            self._agents_list_cache = {"default_agent_id": default_agent_id, "agents": formatted_agents}
            self._agents_list_cache_at = time.time()
            return self._agents_list_cache
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _generate_agent_description(self, agent_id: str, system_prompt: str) -> str:
        """用LLM生成智能体功能描述（≤20字），失败时返回 agent_id"""
        try:
            from src.services.model_manager import model_manager
            provider_cfg = model_manager.get_provider_config("qwen3")
            if not provider_cfg or not provider_cfg.get("enabled", False):
                alive_configs = model_manager.get_all_alive_configs()
                if alive_configs:
                    provider_cfg = alive_configs[0]
            if not provider_cfg:
                return agent_id

            api_base = provider_cfg.get("api_base", "")
            model_name = provider_cfg.get("model_name", "")
            api_key = provider_cfg.get("api_key", "not-needed")

            prompt = f"""根据以下智能体描述，用10个字以内概括它的核心功能：
{system_prompt[:500]}
直接输出简短概括，不要任何前缀后缀、不要引号、不要解释。"""

            messages = [
                {"role": "system", "content": "你是一个精准的文本概括助手。只输出概括结果，不要任何额外内容。"},
                {"role": "user", "content": prompt}
            ]

            req_headers = {"Content-Type": "application/json"}
            if api_key and api_key != "not-needed":
                req_headers["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    json={"model": model_name, "messages": messages, "temperature": 0.1, "max_tokens": 50},
                    headers=req_headers
                )
                resp.raise_for_status()
                data = resp.json()
                if "choices" in data and data["choices"]:
                    desc = data["choices"][0]["message"]["content"].strip()
                    desc = re.sub(r'^[\'"]+|[\'"]+$', '', desc).strip()
                    if desc:
                        return desc[:20]
        except Exception as e:
            logger.warning(f"⚠️ 自动生成description失败: {e}")
        return agent_id

    async def _notify_manager_reload_agents(self) -> None:
        """通知 Manager 重新加载 Agent 描述（最佳努力，不抛异常）"""
        try:
            stub = self._get_manager_stub()
            if not stub:
                logger.warning("⚠️ Manager 不可用，跳过通知")
                return
            internal_msg = "__INTERNAL__:RELOAD_AGENTS"
            await asyncio.to_thread(
                lambda: stub.Chat(dfecrab_pb2.ChatRequest(
                    message=internal_msg,
                    session_id="__internal__",
                    user_id="__system__"
                ), timeout=10.0)
            )
            logger.info("📨 已通知 Manager 重新加载 Agent 描述")
        except Exception as e:
            logger.warning(f"⚠️ 通知 Manager 重新加载失败（不影响创建）: {e}")

    async def _handle_create_agent(self, request) -> Dict[str, Any]:
        """
        创建智能体

        在 agents/{agent_id}/ 目录下创建：
          - config.json   : 核心配置（agent_type / name / icon / system_prompt 等）
          - tools.json    : 技能清单（空列表）
          - memory.json   : 记忆文件（默认空结构，供 MemoryManager 加载）

        Body 参数：
          agent_id     (必填) - 唯一标识，仅允许小写字母/数字/下划线/连字符
          agent_type   (必填) - 三选一：worker / manager / default
          system_prompt(必填) - 系统提示词，决定 agent 行为
          description  (选填) - 功能描述（≤20字），不传则由LLM自动生成
          name         (选填) - 展示名，默认 = agent_id
          icon         (选填) - 图标 emoji，默认 "🤖"
          iconColor    (选填) - 标题颜色，默认按 agent_type 映射
          bgColor      (选填) - 背景颜色，默认按 agent_type 映射
          model_config (选填) - 模型配置名，不传则使用全局默认模型
          parent_agent (选填) - 父 agent ID，默认 null
          enabled_skills(选填)- 启用的技能列表
          builtin_tools (选填)- 内置工具列表
          custom_tools  (选填)- 自定义工具列表
          auto_start    (选填)- 是否自动启动进程（默认 true，manager 类型除外）

        注意：
          - worker/default 类型创建后会自动启动 gRPC 服务进程（通过 subprocess.Popen）
          - manager 类型由 gateway 自动管理
          - 启动的进程由 Gateway 管理，网关停止时自动清理
          - 可通过 auto_start: false 跳过自动启动
        """
        try:
            body = await request.json()
            agent_id = body.get("agent_id", "").strip()

            # ── agent_id 校验 ──
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}
            if not re.match(r'^[a-z0-9_-]+$', agent_id):
                return {"success": False, "error": "agent_id 仅允许小写字母、数字、下划线、连字符"}

            # ── agent_type 校验 ──
            valid_types = {"worker", "manager", "default"}
            agent_type = body.get("agent_type", "")
            if agent_type not in valid_types:
                return {"success": False, "error": f"agent_type 必须是 {', '.join(sorted(valid_types))} 之一"}

            # ── system_prompt 校验 ──
            system_prompt = body.get("system_prompt", "").strip()
            if not system_prompt:
                return {"success": False, "error": "system_prompt 不能为空，请提供智能体的核心行为定义"}

            # ── description 处理：用户提供或LLM自动生成 ──
            description = body.get("description", "").strip()
            if not description:
                description = await self._generate_agent_description(agent_id, system_prompt)
                logger.info(f"   🤖 自动生成 description: {description}")

            # ── 目录准备 ──
            agents_base = PROJECT_ROOT / "agents"
            agent_dir = agents_base / agent_id
            if agent_dir.exists():
                return {"success": False, "error": f"Agent [{agent_id}] 已存在"}

            agent_dir.mkdir(parents=True, exist_ok=True)

            # ── 按 agent_type 映射默认颜色 ──
            type_colors = {
                "manager": {"iconColor": "#FFB800", "bgColor": "#FFF8E1"},
                "worker":  {"iconColor": "#2196F3", "bgColor": "#E3F2FD"},
                "default": {"iconColor": "#FF6B6B", "bgColor": "#FFE5E5"},
            }
            colors = type_colors.get(agent_type, type_colors["worker"])

            # ── model_config 处理：校验必须是已启用的 provider；缺省存空 = 跟随全局模型 ──
            model_config = body.get("model_config", "").strip()
            if model_config:
                _pc = model_manager.get_provider_config(model_config)
                if not _pc or not _pc.get("enabled", False):
                    return {"success": False, "error": f"模型配置不存在或已禁用: {model_config}"}

            # ── 1. 创建 config.json ──
            now = datetime.now().isoformat()
            config = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "name": body.get("name", agent_id),
                "icon": body.get("icon", "🤖"),
                "iconColor": body.get("iconColor", colors["iconColor"]),
                "bgColor": body.get("bgColor", colors["bgColor"]),
                "system_prompt": system_prompt,
                "description": description,
                "model_config": model_config,
                "parent_agent": body.get("parent_agent"),
                "created_at": now,
                "updated_at": now,
                "welcome_message": body.get("welcome_message"),
                "auto_start": body.get("auto_start", True),
            }
            # 去除值为 None 的字段（保持 config.json 整洁）
            config = {k: v for k, v in config.items() if v is not None}

            config_path = agent_dir / "config.json"
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Create] config.json 写入: {config_path}")

            # ── 2. 创建 tools.json ──
            tools = {
                "enabled_skills": body.get("enabled_skills", []),
                "builtin_tools": body.get("builtin_tools", []),
                "custom_tools": body.get("custom_tools", []),
            }
            tools_path = agent_dir / "tools.json"
            with open(tools_path, 'w', encoding='utf-8') as f:
                json.dump(tools, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Create] tools.json 写入: {tools_path}")

            # ── 2.5 同步 agents_index.json（描述索引） ──
            self._sync_agents_index(agent_id, config)

            # ── 3. 创建 memory.json（默认空结构，MemoryManager 格式） ──
            now = datetime.now().isoformat()
            memory = {
                "short_term_memory": [],
                "long_term_memory": {
                    "professional_knowledge": [],
                    "experience": {
                        "successful_patterns": [],
                        "lessons_learned": []
                    },
                    "user_preferences": {},
                    "metadata": {
                        "created_at": now,
                        "last_updated": now,
                        "version": "2.0"
                    }
                }
            }
            memory_path = agent_dir / "memory.json"
            with open(memory_path, 'w', encoding='utf-8') as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Create] memory.json 写入: {memory_path}")

            # ── 通知 Manager 重新加载 Agent 描述 ──
            await self._notify_manager_reload_agents()
            # ★ C-2：agents 列表已变更，主动失效 TTL 缓存（避免列表页 1.5s 内返回旧数据）
            self._agents_list_cache = None
            auto_start = body.get("auto_start", True)
            started = False
            process_pid = None
            if auto_start and agent_type != "manager":
                proc = await self._start_agent_process(agent_id)
                if proc:
                    started = True
                    process_pid = proc.pid

            # ── 返回创建结果 ──
            am = self._resolve_agent_model(model_config)
            result = {
                "success": True,
                "agent_id": agent_id,
                "agent": {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "status": "running" if started else "inactive",
                    "process_pid": process_pid,
                    "process_started": started,
                    "name": config.get("name", agent_id),
                    "description": description,
                    "model_config": am["model_config"],
                    "model_name": am["model_name"],
                    "icon": config.get("icon", "🤖"),
                    "iconColor": config.get("iconColor", colors["iconColor"]),
                    "bgColor": config.get("bgColor", colors["bgColor"]),
                    "skills": tools.get("enabled_skills", []),
                }
            }
            logger.info(f"✅ Agent [{agent_id}] 创建成功 (description: {description}, process_started: {started})")
            return result

        except Exception as e:
            logger.error(f"❌ Agent 创建失败: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_agent(self, request, **kwargs) -> Dict[str, Any]:
        """获取单个智能体的完整配置（详情）"""
        try:
            agent_id = kwargs.get("agent_id") or (request.path_params.get("agent_id") if hasattr(request, "path_params") else None)
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}

            agent_dir = PROJECT_ROOT / "agents" / agent_id
            if not agent_dir.exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}

            meta = self._load_agent_meta(agent_id)
            # description 回退：config.json 未写时用 agents_index.json 描述索引（与列表口径一致，
            # 老 agent 如 alert_judge 的 config.json 无 description，详情页否则为空）
            if not meta.get("description"):
                try:
                    _idx_file = PROJECT_ROOT / "config" / "agents_index.json"
                    if _idx_file.exists():
                        with open(_idx_file, 'r', encoding='utf-8') as f:
                            meta["description"] = (((json.load(f).get("agents", {}) or {})
                                                    .get(agent_id) or {}).get("description", ""))
                except Exception:
                    pass
            # ★ 模型字段一次解析 + agent_type 归一（default 跟随默认助手，兼容历史脏数据）
            am = self._resolve_agent_model(meta.get("model_config", ""))
            detail = {
                "agent_id": agent_id,
                "agent_type": self._normalize_agent_type(agent_id, meta.get("agent_type", "")),
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "system_prompt": meta.get("system_prompt", ""),
                "model_config": am["model_config"],
                "model_name": am["model_name"],
                "context_length": am["context_length"],
                "icon": meta.get("icon", ""),
                "iconColor": meta.get("iconColor", ""),
                "bgColor": meta.get("bgColor", ""),
                "parent_agent": meta.get("parent_agent"),
                "skills": meta.get("skills", []),
            }

            # 时间戳 / 开场白 / 自动启动（config.json 补充字段）
            try:
                with open(agent_dir / "config.json", 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                detail["created_at"] = cfg.get("created_at", "")
                detail["updated_at"] = cfg.get("updated_at", "")
                detail["welcome_message"] = cfg.get("welcome_message", "")
                # auto_start：老 agent 的 config.json 可能没有（手建文件），缺省 True
                #（进程由网关 auto_start 扫描拉起；仅写 True 展示语义，不据此强制重启）
                detail["auto_start"] = cfg.get("auto_start", True)
                # 老 agent 无时间戳：兜底 config.json 文件 mtime（新 agent 创建即带，仅手建老文件缺失）
                if not detail["created_at"] or not detail["updated_at"]:
                    _mtime = datetime.fromtimestamp(
                        (agent_dir / "config.json").stat().st_mtime).isoformat()
                    if not detail["created_at"]:
                        detail["created_at"] = _mtime
                    if not detail["updated_at"]:
                        detail["updated_at"] = _mtime
            except Exception:
                pass

            # 运行状态（ZK 补充）
            detail["status"] = "inactive"
            try:
                if self._zk_discovery:
                    for service_type in ["worker_agent", "manager_agent", "default_agent"]:
                        for inst in (self._zk_discovery.discover_service(service_type) or []):
                            zk_aid = self._zk_instance_agent_id(inst)
                            if zk_aid == agent_id:
                                detail["status"] = "active"
                                detail["address"] = f"{inst.get('host')}:{inst.get('port')}"
                                detail["service_id"] = inst.get("service_id", "")
                                break
            except Exception:
                pass

            # ★ 派生字段（与列表一致，配置页一个请求拿全）：推荐 MCP + 默认助手标记
            detail["recommended_mcp"] = self._recommended_mcp_servers(agent_id)
            detail["is_default"] = agent_id == self._default_agent_id()

            return {"success": True, "data": detail}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_update_agent(self, request, **kwargs) -> Dict[str, Any]:
        """更新智能体配置（部分更新，支持热加载）

        Body 可包含任意可编辑字段；传 restart: true 时平滑重启该 agent 进程，
        使 system_prompt / model_config 等启动期缓存的配置真正生效。
        """
        try:
            agent_id = kwargs.get("agent_id") or (request.path_params.get("agent_id") if hasattr(request, "path_params") else None)
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}

            agent_dir = PROJECT_ROOT / "agents" / agent_id
            config_path = agent_dir / "config.json"
            if not config_path.exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            body = await request.json()
            if not isinstance(body, dict):
                return {"success": False, "error": "请求体必须是 JSON 对象"}

            # 可更新到 config.json 的字段
            editable = ["name", "description", "system_prompt", "icon", "iconColor", "bgColor",
                        "parent_agent", "welcome_message"]
            for key in editable:
                if key in body:
                    config[key] = body[key]

            # model_config：空串 = 清空（恢复跟随全局）；非空需校验为已启用的 provider
            #（修复：原 `and body.get("model_config")` 让空串被 falsy 吞掉，固定模型后无法改回跟随全局）
            if "model_config" in body:
                mc = str(body.get("model_config") or "").strip()
                if mc:
                    _pc = model_manager.get_provider_config(mc)
                    if not _pc or not _pc.get("enabled", False):
                        return {"success": False, "error": f"模型配置不存在或已禁用: {mc}"}
                config["model_config"] = mc

            # 技能/工具更新到 tools.json
            if any(k in body for k in ("enabled_skills", "builtin_tools", "custom_tools")):
                tools_path = agent_dir / "tools.json"
                tools = {}
                if tools_path.exists():
                    with open(tools_path, 'r', encoding='utf-8') as f:
                        tools = json.load(f)
                if "enabled_skills" in body:
                    tools["enabled_skills"] = body["enabled_skills"]
                if "builtin_tools" in body:
                    tools["builtin_tools"] = body["builtin_tools"]
                if "custom_tools" in body:
                    tools["custom_tools"] = body["custom_tools"]
                with open(tools_path, 'w', encoding='utf-8') as f:
                    json.dump(tools, f, ensure_ascii=False, indent=2)

            # 时间戳
            from datetime import datetime
            config["updated_at"] = datetime.now().isoformat()

            # 写回 config.json
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            # 同步 agents_index.json（描述索引）
            self._sync_agents_index(agent_id, config)

            # 通知 Manager 重新加载描述
            await self._notify_manager_reload_agents()
            # ★ C-2：agents 列表已变更，主动失效 TTL 缓存
            self._agents_list_cache = None

            # 热加载：如需对运行中的进程生效，平滑重启该 agent 进程
            restart = body.get("restart", False)
            if restart:
                await self._stop_agent_process(agent_id)
                await self._start_agent_process(agent_id)

            am = self._resolve_agent_model(config.get("model_config", ""))
            return {
                "success": True,
                "message": f"Agent [{agent_id}] 已更新",
                "data": {
                    "agent_id": agent_id,
                    "name": config.get("name", agent_id),
                    "description": config.get("description", ""),
                    "model_config": am["model_config"],
                    "model_name": am["model_name"],
                    "restarted": bool(restart),
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════
    # 平台默认助手（config/dfecrab.json → default_agent，全局唯一）
    # 语义：仅作为对话页"默认预选/高亮 + 初始传参"的配置源，
    #       不接管缺省路由（不带 agent_id 仍走 Manager 智能语义路由）。
    # ══════════════════════════════════════════════════════════

    def _fallback_default_agent(self, exclude: str = "") -> str:
        """默认助手回退目标：优先 dfecrab，其次任一仍存在且非 manager 的 agent。

        用于取消/删除默认助手时保持 default_agent 始终指向存在的 agent。
        """
        try:
            agents_base = PROJECT_ROOT / "agents"
            candidates = ["dfecrab"]
            if agents_base.exists():
                candidates += sorted(
                    d.name for d in agents_base.iterdir()
                    if d.is_dir() and (d / "config.json").exists()
                )
            for cid in candidates:
                if cid == exclude or cid == "manager_agent":
                    continue
                if (agents_base / cid / "config.json").exists():
                    return cid
        except Exception as e:
            logger.warning(f"[Agent] 计算默认助手回退目标失败，回退 dfecrab: {e}")
        return "dfecrab"

    def _default_agent_id(self) -> str:
        """读取平台默认助手 agent_id。

        缺省 / 配置为空 / 指向的 agent 目录不存在时回退可用兜底 agent（_fallback_default_agent）。
        通过 app_config.section() 读取（自动剔除 _note），随配置写盘热更新。
        """
        agent_id = "dfecrab"
        try:
            from src.config.app_config import section
            cfg = section("default_agent") or {}
            candidate = str(cfg.get("agent_id", "") or "").strip()
            if candidate and (PROJECT_ROOT / "agents" / candidate / "config.json").exists():
                agent_id = candidate
            elif candidate:
                logger.warning(f"[Agent] 默认助手 [{candidate}] 不存在，回退兜底 agent")
                agent_id = self._fallback_default_agent(exclude=candidate)
        except Exception as e:
            logger.warning(f"[Agent] 读取默认智能体配置失败，回退 dfecrab: {e}")
        return agent_id

    def _recommended_mcp_servers(self, agent_id: str) -> List[str]:
        """某 agent 的推荐 MCP 服务名（enabled 且服务级绑定含该 agent 或全局 *）。

        派生自 mcporter.json 的 bound_agents（MCP 侧单一事实源），只读、失败返回空。
        """
        try:
            from src.mcp import get_mcp_client
            return sorted(get_mcp_client().get_bound_server_names(agent_id))
        except Exception as e:
            logger.debug(f"[Agent] 读取 {agent_id} 推荐 MCP 失败: {e}")
            return []

    def _set_agent_type(self, agent_id: str, agent_type: str) -> None:
        """同步 agent 的 agent_type 到 config.json（默认助手唯一化的落盘动作，best-effort）。"""
        try:
            config_path = PROJECT_ROOT / "agents" / agent_id / "config.json"
            if not config_path.exists():
                return
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if cfg.get("agent_type") == agent_type:
                return
            cfg["agent_type"] = agent_type
            cfg["updated_at"] = datetime.now().isoformat()
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self._agents_list_cache = None
            logger.info(f"✅ [AgentType] {agent_id}.agent_type → {agent_type}")
        except Exception as e:
            logger.warning(f"⚠️ 同步 {agent_id} agent_type 失败: {e}")

    def _normalize_agent_type(self, agent_id: str, agent_type: str) -> str:
        """读侧修正 agent_type（防历史脏数据）：默认助手⇔default，manager 保持，其余 worker。"""
        if agent_type == "manager":
            return "manager"
        return "default" if agent_id == self._default_agent_id() else "worker"

    def _reconcile_default_agent_type(self) -> None:
        """启动对账：default_agent.agent_id 与各 agent config.json 的 agent_type 对齐（幂等）。

        修复历史脏数据（如老部署 dfecrab 恒 default、或默认指向 worker 类型 agent），
        保证"agent_type=default 全局唯一且跟随默认助手"这一不变量。
        """
        try:
            cur = self._default_agent_id()
            agents_base = PROJECT_ROOT / "agents"
            if not agents_base.exists():
                return
            for d in agents_base.iterdir():
                if not (d.is_dir() and (d / "config.json").exists()):
                    continue
                with open(d / "config.json", 'r', encoding='utf-8') as f:
                    at = json.load(f).get("agent_type", "")
                if d.name == cur and at != "manager":
                    self._set_agent_type(d.name, "default")
                elif at == "default" and d.name != cur:
                    self._set_agent_type(d.name, "worker")
        except Exception as e:
            logger.warning(f"⚠️ 默认助手类型对账失败（不影响启动）: {e}")

    def _persist_default_agent(self, agent_id: str) -> bool:
        """把某 agent 写为平台默认（单值覆盖 → 全局唯一），并同步 agent_type：

        - 旧默认自动降级 worker、新默认升级 default（agent_type 跟随默认，全局唯一）
        - manager 不可作为默认（调用方已拦截，此处兜底）
        - 保留 dfecrab.json 中 default_agent._note 维护说明（首次写入用默认文案）
        - 失效列表缓存
        """
        try:
            if agent_id == "manager_agent":
                logger.error("❌ manager_agent 不可设为默认助手")
                return False
            if not (PROJECT_ROOT / "agents" / agent_id / "config.json").exists():
                logger.error(f"❌ 默认助手目标 [{agent_id}] 不存在")
                return False

            from src.config.app_config import update_section, get_dfecrab_raw
            prev_raw = (get_dfecrab_raw() or {}).get("default_agent") or {}
            prev = str(prev_raw.get("agent_id", "") or "")
            note = prev_raw.get("_note") or (
                "平台默认助手（全局唯一，多现场随部署文件差异化）：agent_type=default 跟随本字段，"
                "切换时旧默认自动降级 worker；PUT /api/agents/{id}/default 设置；"
                "取消/删除默认 agent 自动回退兜底 agent（优先 dfecrab）"
            )
            update_section("default_agent", {"agent_id": agent_id, "_note": note})

            # agent_type 同步：旧的降 worker、新的升 default（prev == agent_id 时幂等跳过）
            if prev and prev != agent_id and prev != "manager_agent":
                self._set_agent_type(prev, "worker")
            self._set_agent_type(agent_id, "default")

            self._agents_list_cache = None
            logger.info(f"✅ 平台默认助手: {prev or '(无)'} → {agent_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 设置默认智能体失败: {e}")
            return False

    async def _handle_set_default_agent(self, request, **kwargs) -> Dict[str, Any]:
        """PUT /api/agents/{agent_id}/default — 设为平台默认助手（旧默认自动清除并降级 worker）"""
        try:
            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}
            if not (PROJECT_ROOT / "agents" / agent_id / "config.json").exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}
            if agent_id == "manager_agent":
                return {"success": False, "error": "manager_agent 是任务路由器，不可设为默认助手"}
            if not self._persist_default_agent(agent_id):
                return {"success": False, "error": "设置默认智能体失败（配置写入异常）"}
            return {
                "success": True,
                "message": f"已将 [{agent_id}] 设为平台默认助手",
                "data": {"agent_id": agent_id, "default_agent_id": agent_id, "is_default": True},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_clear_default_agent(self, request, **kwargs) -> Dict[str, Any]:
        """DELETE /api/agents/{agent_id}/default — 取消默认（回退兜底 agent，幂等）

        仅当该 agent 确为当前默认时才回退；对非默认 agent 调用是 no-op（不误伤真默认）。
        """
        try:
            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}
            if not (PROJECT_ROOT / "agents" / agent_id / "config.json").exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}
            current = self._default_agent_id()
            if agent_id != current:
                return {
                    "success": True,
                    "message": f"[{agent_id}] 非平台默认助手，无需变更",
                    "data": {"agent_id": agent_id, "default_agent_id": current, "is_default": False},
                }
            fallback = self._fallback_default_agent(exclude=agent_id)
            if not self._persist_default_agent(fallback):
                return {"success": False, "error": "取消默认智能体失败（配置写入异常）"}
            return {
                "success": True,
                "message": f"已取消默认助手，平台默认回退 {fallback}",
                "data": {"agent_id": agent_id, "default_agent_id": fallback, "is_default": False},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_save_agent_mcp(self, request, **kwargs) -> Dict[str, Any]:
        """PUT /api/agents/{agent_id}/mcp — 网关包装：调 MCPHandler 保存绑定后立即失效列表缓存。

        列表缓存内含 recommended_mcp 派生字段，绑定变更必须主动失效（TTL 仅 1.5s 兜底）。
        """
        from src.gateway.handlers.mcp_handler import MCPHandler
        result = await MCPHandler.save_agent_mcp(request, **kwargs)
        if result.get("success"):
            self._agents_list_cache = None
        return result

    async def _auto_start_worker_agents(self) -> None:
        """自动扫描启动 agents/ 目录下所有 worker 类型的智能体"""
        try:
            agents_base = PROJECT_ROOT / "agents"
            if not agents_base.exists():
                logger.warning(f"⚠️ agents 目录不存在: {agents_base}")
                return

            started_count = 0
            for agent_dir in agents_base.iterdir():
                if not agent_dir.is_dir():
                    continue
                # 跳过 manager_agent（由 dfecrab start 单独启动）
                if agent_dir.name == "manager_agent":
                    continue

                config_path = agent_dir / "config.json"
                if not config_path.exists():
                    logger.debug(f"   ℹ️ 跳过 {agent_dir.name}: 无 config.json")
                    continue

                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                except Exception as e:
                    logger.warning(f"   ⚠️ 读取 {agent_dir.name}/config.json 失败: {e}")
                    continue

                agent_id = config.get("agent_id") or agent_dir.name
                agent_type = config.get("agent_type", "worker")

                # 只跳过 manager 类型（由 dfecrab start 单独启动）
                if agent_type == "manager":
                    logger.info(f"   ℹ️ 跳过 {agent_id}: manager 类型")
                    continue

                # 检查是否已在运行
                if agent_id in self._agent_processes:
                    proc = self._agent_processes[agent_id]
                    if proc.poll() is None:
                        logger.info(f"   ℹ️ {agent_id} 已在运行 (PID: {proc.pid})，跳过")
                        continue
                    else:
                        logger.warning(f"   ⚠️ {agent_id} 旧进程已退出，重新启动")
                        del self._agent_processes[agent_id]

                logger.info(f"🤖 自动启动 worker 智能体: {agent_id}")
                proc = await self._start_agent_process(agent_id)
                if proc:
                    started_count += 1
                    logger.info(f"   ✅ {agent_id} 已启动 (PID: {proc.pid})")
                else:
                    logger.warning(f"   ⚠️ {agent_id} 启动失败")

            logger.info(f"✅ 自动启动 worker 智能体完成，共启动 {started_count} 个")
        except Exception as e:
            logger.error(f"❌ 自动启动 worker 智能体失败: {e}")

    async def _auto_start_manager_agent(self) -> None:
        """自动启动 Manager Agent 进程"""
        try:
            # 先检查是否已在运行（通过 ZK 检测）
            if self._zk_discovery:
                instances = self._zk_discovery.discover_service("manager_agent")
                if instances:
                    logger.info("✅ Manager Agent 已在 Zookeeper 中注册，跳过自动启动")
                    # 启动健康检查循环
                    asyncio.ensure_future(self._manager_health_check_loop())
                    return

            # 启动 Manager 进程
            logger.info("🚀 自动启动 Manager Agent...")
            proc = await self._start_agent_process("manager_agent")
            if proc:
                logger.info(f"✅ Manager Agent 已启动 (PID: {proc.pid})")
                # 等待 Manager 在 ZK 中注册
                await asyncio.sleep(5)
                # 启动健康检查循环
                asyncio.ensure_future(self._manager_health_check_loop())
            else:
                logger.error("❌ Manager Agent 启动失败")
        except Exception as e:
            logger.error(f"❌ 自动启动 Manager Agent 异常: {e}")

    async def _manager_health_check_loop(self):
        """定时检查 Manager Agent 是否存活，发现宕机自动重启"""
        while self._running:
            try:
                # 检查进程是否存活
                if "manager_agent" in self._agent_processes:
                    proc = self._agent_processes["manager_agent"]
                    if proc.poll() is not None:
                        logger.warning(f"⚠️ Manager Agent 进程已退出 (code: {proc.returncode})，尝试重启...")
                        del self._agent_processes["manager_agent"]
                        proc = await self._start_agent_process("manager_agent")
                        if proc:
                            logger.info(f"✅ Manager Agent 已自动重启 (PID: {proc.pid})")
                        else:
                            logger.error("❌ Manager Agent 重启失败")
                else:
                    # 进程记录不存在，尝试启动
                    logger.warning("⚠️ Manager Agent 进程不存在，尝试启动...")
                    proc = await self._start_agent_process("manager_agent")
                    if proc:
                        logger.info(f"✅ Manager Agent 已启动 (PID: {proc.pid})")
                
                # 通过 ZK 检查服务是否注册成功
                if self._zk_discovery:
                    instances = self._zk_discovery.discover_service("manager_agent")
                    if not instances:
                        logger.warning("⚠️ Manager Agent 未在 Zookeeper 中注册")
                    
            except Exception as e:
                logger.error(f"❌ Manager 健康检查异常: {e}")
            await asyncio.sleep(30)  # 每30秒检查一次

    async def _scan_orphan_zk_agents(self) -> None:
        """扫描 ZK 中本地 agents/ 目录不存在的 Agent 注册，打警告日志

        用于发现残留进程 / 僵尸 ZK 节点（如 agent_id=default 的孤儿注册），
        便于运维及时清理。
        """
        if not self._zk_discovery:
            return
        try:
            agents_base = PROJECT_ROOT / "agents"
            local_ids = set()
            if agents_base.exists():
                local_ids = {
                    d.name for d in agents_base.iterdir()
                    if d.is_dir() and (d / "config.json").exists()
                }

            for service_type in ("worker_agent", "manager_agent", "default_agent"):
                for inst in (self._zk_discovery.discover_service(service_type) or []):
                    agent_id = self._zk_instance_agent_id(inst)
                    if agent_id == "manager_agent" or agent_id in local_ids:
                        continue
                    logger.warning(
                        f"⚠️ [ZK] 孤儿注册: agent_id={agent_id}, "
                        f"service_id={inst.get('service_id')}, "
                        f"addr={inst.get('host')}:{inst.get('port')}, "
                        f"registered_at={inst.get('registered_at')}"
                    )
        except Exception as e:
            logger.error(f"❌ 扫描 ZK 孤儿注册失败: {e}")

    async def _worker_health_check_loop(self):
        """每隔 30 秒检查所有 worker 进程，发现宕机或 ZK 注册丢失就重启"""
        while self._running:
            try:
                agents_base = PROJECT_ROOT / "agents"
                if not agents_base.exists():
                    await asyncio.sleep(30)
                    continue

                for agent_dir in agents_base.iterdir():
                    if not agent_dir.is_dir():
                        continue
                    if agent_dir.name == "manager_agent":
                        continue

                    config_path = agent_dir / "config.json"
                    if not config_path.exists():
                        continue

                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                    except Exception:
                        continue

                    agent_id = config.get("agent_id") or agent_dir.name
                    agent_type = config.get("agent_type", "worker")

                    # 跳过 manager 类型（由 _manager_health_check_loop 负责）
                    if agent_type == "manager":
                        continue

                    # 检查 ZK 中是否有注册（★ 步骤4：注册端统一 worker_agent；default_agent 仅兼容旧节点）
                    registered = False
                    if self._zk_discovery:
                        for _st in ("worker_agent", "default_agent"):
                            for inst in (self._zk_discovery.discover_service(_st) or []):
                                if self._zk_instance_agent_id(inst) == agent_id:
                                    registered = True
                                    break
                            if registered:
                                break

                    need_restart = False

                    # 检查进程是否存活
                    proc = self._agent_processes.get(agent_id)
                    if proc:
                        if proc.poll() is not None:
                            logger.warning(
                                f"⚠️ Worker [{agent_id}] 进程已退出 (code: {proc.returncode})"
                            )
                            del self._agent_processes[agent_id]
                            need_restart = True
                    else:
                        # 进程记录不存在，若 ZK 也无注册 → 需要启动
                        if not registered:
                            need_restart = True

                    # ZK 注册丢失但进程活着 → 可能是 ZK session 过期，重启进程以重建 ZK session
                    if proc and proc.poll() is None and not registered:
                        logger.warning(
                            f"⚠️ Worker [{agent_id}] 进程存活但 ZK 注册丢失，重启以重建 ZK session"
                        )
                        await self._stop_agent_process(agent_id)
                        need_restart = True

                    if need_restart:
                        logger.info(f"🔄 自动重启 worker [{agent_id}]...")
                        await self._start_agent_process(agent_id)

            except Exception as e:
                logger.error(f"❌ Worker 健康检查异常: {e}")
                import traceback
                traceback.print_exc()

            await asyncio.sleep(30)

    async def _files_orphan_cleanup_loop(self) -> None:
        """孤儿附件周期清理（批次12步骤3）

        按 file_upload.cleanup_interval_s 周期调用 registry.cleanup_orphans，
        回收：status=deleted 记录、超 TTL 记录、注册表无记录的落盘文件。
        默认 1 小时扫一次、TTL 30 天；仅处理孤儿，不影响 active 附件。
        """
        try:
            from src.config.app_config import section as _cfg_section
            _fu = _cfg_section("file_upload") or {}
        except Exception:
            _fu = {}
        try:
            _interval = float(_fu.get("cleanup_interval_s", 3600) or 3600)
        except Exception:
            _interval = 3600.0
        while self._running:
            try:
                await asyncio.sleep(_interval)
                if not self._running:
                    break
                from src.files.registry import cleanup_orphans
                _ttl = int(_fu.get("cleanup_ttl_days", 30) or 30)
                _res = cleanup_orphans(ttl_days=_ttl)
                if _res.get("removed_records") or _res.get("removed_files"):
                    logger.info(
                        f"[Files] 孤儿附件清理: records={_res.get('removed_records', 0)}, "
                        f"files={_res.get('removed_files', 0)} (ttl={_ttl}d)"
                    )
                else:
                    logger.debug(
                        f"[Files] 孤儿附件清理: 无孤儿（ttl={_ttl}d）"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[Files] 孤儿附件清理异常（下轮重试）: {e}")

    async def _start_agent_process(self, agent_id: str) -> Optional[subprocess.Popen]:
        """启动 Agent 的 gRPC 服务进程

        Args:
            agent_id: 智能体ID
            
        Returns:
            subprocess.Popen 对象，启动失败返回 None
        """
        if agent_id in self._agent_processes:
            proc = self._agent_processes[agent_id]
            if proc.poll() is None:
                logger.info(f"   ℹ️ Agent [{agent_id}] 进程已在运行 (PID: {proc.pid})")
                return proc
            else:
                # 进程已退出，清理旧记录
                logger.warning(f"   ⚠️ Agent [{agent_id}] 旧进程已退出 (code: {proc.returncode}), 重新启动")
                del self._agent_processes[agent_id]

        if agent_id == "manager_agent":
            agent_service_script = PROJECT_ROOT / "services" / "manager_agent" / "manager_agent_grpc.py"
        else:
            agent_service_script = PROJECT_ROOT / "services" / "agent_service" / "agent_service_grpc.py"
        if not agent_service_script.exists():
            logger.error(f"   ❌ Agent 服务脚本不存在: {agent_service_script}")
            return None

        python_exec = sys.executable

        try:
            cmd = [
                python_exec,
                str(agent_service_script),
                "--zk-hosts", self.zk_hosts,
            ]
            if agent_id != "manager_agent":
                cmd.extend(["--agent-id", agent_id])

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._agent_processes[agent_id] = proc
            logger.info(f"   🚀 Agent [{agent_id}] 进程已启动 (PID: {proc.pid})")
            return proc
        except Exception as e:
            logger.error(f"   ❌ Agent [{agent_id}] 进程启动失败: {e}")
            return None

    async def _stop_agent_process(self, agent_id: str) -> bool:
        """停止 Agent 的 gRPC 服务进程"""
        if agent_id not in self._agent_processes:
            return False

        proc = self._agent_processes.pop(agent_id)
        if proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"   ⚠️ Agent [{agent_id}] 进程未响应终止信号，强制杀死")
                    proc.kill()
                    proc.wait(timeout=3)
                logger.info(f"   ✅ Agent [{agent_id}] 进程已停止 (PID: {proc.pid})")
            except Exception as e:
                logger.error(f"   ❌ Agent [{agent_id}] 进程停止失败: {e}")
                return False
        return True

    async def _handle_delete_agent(self, request, **kwargs) -> Dict[str, Any]:
        """删除智能体（删除 agents/ 目录 + 停止进程）"""
        try:
            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}

            # ── 先停止进程 ──
            process_stopped = await self._stop_agent_process(agent_id)
            if process_stopped:
                logger.info(f"   ✅ Agent [{agent_id}] 进程已停止")

            agents_base = PROJECT_ROOT / "agents"
            agent_dir = agents_base / agent_id

            if not agent_dir.exists():
                return {"success": False, "error": f"Agent {agent_id} 不存在"}

            import shutil
            shutil.rmtree(agent_dir)

            # 清理 agents_index.json 中对应项
            try:
                index_file = PROJECT_ROOT / "config" / "agents_index.json"
                if index_file.exists():
                    with open(index_file, 'r', encoding='utf-8') as f:
                        index_data = json.load(f)
                    if agent_id in index_data.get("agents", {}):
                        del index_data["agents"][agent_id]
                        with open(index_file, 'w', encoding='utf-8') as f:
                            json.dump(index_data, f, ensure_ascii=False, indent=2)
                        logger.info(f"✅ [Index] agents_index.json 已清理: {agent_id}")
            except Exception as e:
                logger.warning(f"⚠️ 清理 agents_index.json 失败: {e}")

            # ★ 删除的是平台默认助手时回退兜底 agent（修复：原逻辑误缩进在 except 内，正常路径永不执行）
            try:
                if agent_id == self._default_agent_id():
                    fallback = self._fallback_default_agent(exclude=agent_id)
                    self._persist_default_agent(fallback)
                    logger.info(f"✅ 默认助手 [{agent_id}] 已删除，平台默认回退 {fallback}")
            except Exception as e:
                logger.warning(f"⚠️ 清理平台默认助手失败: {e}")

            logger.info(f"✅ Agent {agent_id} 删除成功")
            # ★ C-2：agents 列表已变更，主动失效 TTL 缓存
            self._agents_list_cache = None
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- 服务 & 不变量 ---

    async def _handle_list_services(self, request) -> Dict[str, Any]:
        """列出服务"""
        try:
            return {"services": []}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_check_invariants(self, request) -> Dict[str, Any]:
        """处理不变量检查请求"""
        try:
            from src.monitoring.invariants import check_all_invariants
            result = check_all_invariants()
            return {"invariants": result}
        except ImportError:
            return {"invariants": "检查模块未安装"}
        except Exception as e:
            return {"success": False, "error": str(e)}



    # --- 任务调度 / 待办 / 统计：已迁移至 src/task/api_routes.py ---

    # --- 自反思系统 ---

    async def _handle_list_reflections(self, request) -> Dict[str, Any]:
        """列出反思历史"""
        try:
            from src.reflection import get_self_reflector
            reflector = get_self_reflector()
            limit = int(request.query_params.get("limit", 10))
            history = reflector.get_reflection_history(limit=limit)

            return {
                "success": True,
                "count": len(history),
                "reflections": [
                    {
                        "reflection_id": r.reflection_id,
                        "agent_id": r.agent_id,
                        "timestamp": r.timestamp.isoformat() if hasattr(r.timestamp, 'isoformat') else str(r.timestamp),
                        "satisfaction_score": r.satisfaction.score if hasattr(r, 'satisfaction') else 0,
                        "summary": r.summary
                    }
                    for r in history
                ]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_get_reflection(self, request, **kwargs) -> Dict[str, Any]:
        """获取反思报告详情"""
        try:
            reflection_id = kwargs.get("reflection_id") or request.path_params.get("reflection_id")

            from src.reflection import get_self_reflector
            reflector = get_self_reflector()

            reflection_dir = reflector._reflection_dir
            import json
            from pathlib import Path

            for agent_dir in reflection_dir.iterdir():
                if not agent_dir.is_dir():
                    continue

                for f in agent_dir.glob("*.json"):
                    if reflection_id in f.stem:
                        with open(f, 'r', encoding='utf-8') as fh:
                            report = json.load(fh)
                        return {"success": True, "reflection": report}

            return {"success": False, "error": f"反思报告不存在：{reflection_id}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_implement_improvements(self, request, **kwargs) -> Dict[str, Any]:
        """执行改进计划"""
        try:
            reflection_id = kwargs.get("reflection_id") or request.path_params.get("reflection_id")

            from src.reflection import get_self_reflector
            reflector = get_self_reflector()

            reflection_dir = reflector._reflection_dir
            import json
            from pathlib import Path

            for agent_dir in reflection_dir.iterdir():
                if not agent_dir.is_dir():
                    continue

                for f in agent_dir.glob("*.json"):
                    if reflection_id in f.stem:
                        with open(f, 'r', encoding='utf-8') as fh:
                            report = json.load(fh)

                        actions = report.get("improvement_actions", [])
                        if actions:
                            # 执行改进计划（当前为占位实现，仅回执改进行动数量）
                            return {
                                "success": True,
                                "message": f"改进计划已提交：{len(actions)} 项行动",
                                "actions_count": len(actions)
                            }

            return {"success": False, "error": f"反思报告不存在：{reflection_id}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- V2 任务管理 (完整 CRUD + 进度 + 审计 + 仪表盘)：已迁移至 src/task/api_routes.py ---