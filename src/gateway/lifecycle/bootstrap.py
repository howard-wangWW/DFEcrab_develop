"""网关引导与运行时（Bootstrap Domain）

从 `grpc_server.GatewayV2GRPC` 按域拆出的 Mixin，承载"进程级"能力：

    initialize()             组合根：配置装配、ZK 服务发现、HTTP/WS 服务器、事件总线、
                             任务管理器与调度器、子进程自动拉起、路由注册
    _register_routes()       消费 `src/gateway/routes.py` 声明表 + 域提供方（plan_router / task）
    _register_task_routes()  任务域路由注册（带同 method+path 去重）
    start() / stop()         生命周期：启动/优雅停止全部子组件
    _get_manager_stub()      Manager gRPC 通道复用（含 ZK 发现与重建）
    _handle_health()         健康检查（含组件状态）

依赖单向：不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import uuid
from typing import Any, Dict, Optional

from src.core.errors import (
    UserError,
    error_response,
    setup_asyncio_exception_handler,
    setup_global_exception_handlers,
)
from src.gateway.event_bus import get_event_bus
from src.gateway.http.server import HTTPMethod, HTTPServer, RouteRule
from src.gateway.lifecycle.zookeeper import set_discovery
from src.gateway.websocket.connection import AuthContext, WSMessage, WSMessageType
from src.gateway.websocket.server import WebSocketServer
from src.task.periodic_scheduler import get_periodic_scheduler
from src.task.task_manager import get_task_manager

try:  # 离线环境可能缺 grpc
    import grpc
    from src.gateway.grpc import dfecrab_pb2, dfecrab_pb2_grpc
except Exception:  # pragma: no cover
    grpc = None  # type: ignore
    dfecrab_pb2 = None  # type: ignore
    dfecrab_pb2_grpc = None  # type: ignore

logger = logging.getLogger(__name__)


class BootstrapMixin:
    """网关引导与运行时（方法实现逐字自 grpc_server 迁出）"""

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
            set_discovery(self._zk_discovery)
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
            
            # 创建 WebSocket 服务器（心跳参数可在 config/gateway.yaml 的 ws 段配置，缺省 30s/90s）
            # 修复：原代码引用未定义的 _cfg，异常被吞后恒用默认值（配置项静默失效）
            try:
                from src.config.config_loader import config as _cfg_loader
                _ws_cfg = (_cfg_loader.raw_config.get("ws") or {})
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
        """注册全部 HTTP 路由（声明表见 src/gateway/routes.py）。

        拆分后此处不再堆 400 行 if/append：
        1) 内置路由 → `ROUTES` 声明表（顺序即匹配优先级：静态路径在前、参数化在后）；
        2) 域路由   → `PROVIDERS`（plan_router），按原语义做同 method+path 去重、写方法按 write 保护；
        3) 任务路由 → `_register_task_routes()`（src/task/api_routes.py，含自带去重与日志）。
        """
        from src.gateway.routes import PROVIDERS, ROUTES, iter_provider_routes, resolve_handler

        registered = 0
        for method_str, path, ref, level, admin_only in ROUTES:
            method = getattr(HTTPMethod, method_str, None)
            if method is None:
                logger.warning(f"[Router] 跳过非法方法声明: {method_str} {path}")
                continue
            self._http_server._routes.append(
                RouteRule(method, path, resolve_handler(ref, self),
                          required_level=level, admin_only=admin_only)
            )
            registered += 1
        logger.info(f"[Router] 内置路由已注册: {registered} 条")

        for provider in PROVIDERS:
            count = 0
            try:
                for spec, handler in iter_provider_routes(provider).items():
                    method_str, path = spec.split(" ", 1)
                    method = getattr(HTTPMethod, method_str, HTTPMethod.GET)
                    # 去重：跳过已注册的同 method+path 路由（避免与内置 handler 重复注册死路由）
                    if any(r.method == method and r.path_pattern == path
                           for r in self._http_server._routes):
                        logger.debug(f"[Router] 跳过重复 {provider} 路由: {method_str} {path}")
                        continue
                    level = "write" if method in (
                        HTTPMethod.POST, HTTPMethod.DELETE, HTTPMethod.PUT, HTTPMethod.PATCH
                    ) else "read"
                    self._http_server._routes.append(
                        RouteRule(method, path, handler, required_level=level)
                    )
                    count += 1
            except Exception as e:
                logger.warning(f"[Router] 提供方 {provider} 路由注册失败: {e}")
            logger.info(f"[Router] {provider} 路由已注册: {count} 条")

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
