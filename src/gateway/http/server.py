# src/core/gateway/protocol/http_server.py
"""
HTTP 服务器 - 简化的 HTTP 协议实现
"""

import asyncio
import json
import logging
import re
from typing import Dict, List, Callable, Any, Optional, Tuple
from enum import Enum

# 说明：任务路由（/api/v2/tasks*、/api/tasks*）统一由 GatewayServer._register_task_routes()
# 从 src/task/api_routes.py 注册，本模块不再重复注册（避免出现两套同名路由、先注册者胜出）。
logger = logging.getLogger(__name__)

# ===== 统一 URL 前缀（可选兼容）=====
# 请求带 /dfecrab 前缀（如 /dfecrab/api/v2/chat）时自动剥离后再匹配路由表，
# 使带前缀与不带前缀（/api/v2/chat）两种地址均可访问，兼容旧调用方。
DFECRAB_URL_PREFIX = "/dfecrab"


def _normalize_api_path(path: str) -> str:
    """剥离可选的 /dfecrab 服务前缀，返回可匹配路由表的规范路径。"""
    if path == DFECRAB_URL_PREFIX or path.startswith(DFECRAB_URL_PREFIX + "/"):
        return path[len(DFECRAB_URL_PREFIX):] or "/"
    return path


# 权限判定服务（延迟导入，避免循环依赖）
try:
    from src.gateway.permission import PermissionService
except ImportError:
    PermissionService = None


class HTTPMethod(Enum):
    """HTTP 方法"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    OPTIONS = "OPTIONS"


class HTTPRequest:
    """HTTP 请求"""

    def __init__(self):
        self.method: Optional[HTTPMethod] = None
        self.path: str = ""
        self.path_params: Dict[str, str] = {}
        self.headers: Dict[str, str] = {}
        self.body: bytes = b""
        self.query_params: Dict[str, str] = {}

    async def json(self) -> Any:
        """解析 JSON body"""
        if not self.body:
            return {}

        try:
            body_text = self.body.decode('utf-8')
            return json.loads(body_text)
        except UnicodeDecodeError:
            try:
                body_text = self.body.decode('latin-1')
                return json.loads(body_text)
            except:
                return {}
        except json.JSONDecodeError:
            return {}
        except Exception:
            return {}


class HTTPResponse:
    """HTTP 响应"""

    def __init__(self, status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.headers = headers or {}
        self.body: bytes = b""
        self.is_sse_response = False
        self.stream_generator = None
        self._add_cors_headers()

    def _add_cors_headers(self):
        self.headers["Access-Control-Allow-Origin"] = "*"
        self.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
        self.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"

    def json(self, data: Any) -> 'HTTPResponse':
        self.headers["Content-Type"] = "application/json"
        self.body = json.dumps(data, ensure_ascii=False).encode()
        return self

    def text(self, content: str) -> 'HTTPResponse':
        self.headers["Content-Type"] = "text/plain; charset=utf-8"
        self.body = content.encode()
        return self

    def bytes(self, data: bytes, content_type: str = "application/octet-stream") -> 'HTTPResponse':
        """二进制直出（图片 / 文件下载）。

        ★ 图片等二进制资源走此方法，避免 base64 JSON 的体积膨胀与解析开销。
        """
        self.headers["Content-Type"] = content_type
        self.body = data if isinstance(data, bytes) else bytes(data)
        return self

    def sse(self, generator) -> 'HTTPResponse':
        self.is_sse_response = True
        self.stream_generator = generator
        return self


class RouteRule:
    """路由规则"""

    def __init__(self, method: HTTPMethod, path_pattern: str, handler: Callable,
                 required_level: str = "read", admin_only: bool = False):
        self.method = method
        self.path_pattern = path_pattern
        self.handler = handler
        self.required_level = required_level
        self.admin_only = admin_only

        regex_pattern = re.sub(r'\{([^}]+)\}', r'(?P<\1>[^/]+)', path_pattern)
        self._path_regex = re.compile(f'^' + regex_pattern + '$')

    def match(self, method: HTTPMethod, path: str) -> Optional[Dict[str, str]]:
        if self.method.value != method.value:
            return None

        match_result = self._path_regex.match(path)
        if match_result:
            return match_result.groupdict()

        return None


class HTTPServer:
    """HTTP 服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 6789, 
                 service_locator: Any = None, event_bus: Any = None):
        self._host = host
        self._port = port
        self._service_locator = service_locator
        self._event_bus = event_bus
        self._routes: List[RouteRule] = []
        self._server: Optional[asyncio.Server] = None
        self._running = False

    def _wrap_handler(self, endpoint):
        """包装FastAPI风格的端点函数"""
        async def wrapped_handler(request: HTTPRequest, **path_params):
            try:
                # 解析请求体
                body = await request.json() if request.body else {}

                import inspect
                args = {}

                try:
                    sig = inspect.signature(endpoint)
                except (ValueError, TypeError):
                    sig = None

                if sig:
                    for param_name, param in sig.parameters.items():
                        annotation = param.annotation

                        # ===== 修复1：优先检查参数类型是否是 HTTPRequest =====
                        if annotation != inspect.Parameter.empty:
                            if annotation is HTTPRequest:
                                args[param_name] = request
                                continue

                        # 路径参数
                        if param_name in path_params:
                            raw_value = path_params[param_name]
                            if annotation != inspect.Parameter.empty:
                                args[param_name] = self._coerce_query_value(raw_value, annotation)
                            else:
                                args[param_name] = raw_value
                        # 如果参数名是 'request' 且没有类型注解，注入 HTTPRequest
                        elif param_name == 'request' and annotation == inspect.Parameter.empty:
                            args[param_name] = request
                        # 如果参数名在 body 中
                        elif param_name in body:
                            args[param_name] = body[param_name]
                        # 如果参数在查询参数中
                        elif param_name in request.query_params:
                            raw_value = request.query_params[param_name]
                            # 根据类型注解转换查询参数值（HTTP查询参数始终是字符串）
                            if annotation != inspect.Parameter.empty:
                                args[param_name] = self._coerce_query_value(raw_value, annotation)
                            else:
                                args[param_name] = raw_value
                        # 如果参数是 Pydantic 模型，用 body 构建
                        elif param.default == inspect.Parameter.empty:
                            # 检查参数类型注解是否是 Pydantic BaseModel
                            is_pydantic_model = False
                            try:
                                from pydantic import BaseModel
                                if annotation != inspect.Parameter.empty and isinstance(annotation, type):
                                    if issubclass(annotation, BaseModel):
                                        is_pydantic_model = True
                                        try:
                                            args[param_name] = annotation(**body)
                                            logger.debug(f"✅ 构建 Pydantic 模型: {param_name}")
                                            continue
                                        except Exception as e:
                                            # 模型构建失败（如缺少必填字段）时，直接返回明确的参数校验错误，
                                            # 避免把原始 dict 兜底传给端点，导致 request.xxx 属性访问崩溃
                                            # （如 "'dict' object has no attribute 'task_type'"）
                                            logger.warning(f"⚠️ 构建 Pydantic 模型失败 {param_name}: {e}")
                                            return HTTPResponse(400).json({
                                                "success": False,
                                                "error": f"Invalid request body for '{param_name}': {e}"
                                            })
                            except ImportError:
                                pass

                            # 仅当参数不是 Pydantic 模型时，才把整个 body 作为该参数传入
                            if not is_pydantic_model and body and len(sig.parameters) == 1:
                                args[param_name] = body
                            else:
                                logger.warning(f"⚠️ 参数 '{param_name}' 无法解析，端点可能报错")

                        # 有默认值，跳过
                        elif param.default != inspect.Parameter.empty:
                            pass
                else:
                    # 如果无法获取签名，尝试用 body 作为第一个参数
                    if body:
                        args = body

                # ===== 修复2：调用前检查是否缺少必填参数 =====
                if sig:
                    for param_name, param in sig.parameters.items():
                        if param_name not in args and param.default == inspect.Parameter.empty:
                            if isinstance(body, dict) and param_name in body:
                                args[param_name] = body[param_name]
                            else:
                                logger.error(f"❌ 缺少必填参数: {param_name}")
                                return HTTPResponse(400).json({
                                    "success": False, 
                                    "error": f"Missing required parameter: {param_name}"
                                })

                # 调用端点
                if asyncio.iscoroutinefunction(endpoint):
                    result = await endpoint(**args)
                else:
                    result = endpoint(**args)

                # 处理返回值
                if isinstance(result, dict):
                    return HTTPResponse(200).json(result)
                elif isinstance(result, HTTPResponse):
                    return result
                elif hasattr(result, 'is_sse_response') and result.is_sse_response:
                    return result
                else:
                    return HTTPResponse(200).json({"success": True, "data": result})

            except Exception as e:
                logger.error(f"任务路由处理失败: {e}")
                import traceback
                traceback.print_exc()
                return HTTPResponse(500).json({"success": False, "error": str(e)})

        return wrapped_handler

    @staticmethod
    def _coerce_query_value(raw_value: str, annotation):
        """将HTTP查询参数的字符串值转换为目标类型"""
        # 处理 Union/Optional 类型（如 Optional[int] -> Union[int, None]）
        origin = getattr(annotation, '__origin__', None)
        if origin is not None:
            # 找到第一个非 None 的类型参数
            args = getattr(annotation, '__args__', ())
            for arg in args:
                if arg is not type(None):
                    annotation = arg
                    break

        if annotation is bool:
            return raw_value.lower() in ('true', '1', 'yes', 'on')
        elif annotation is str:
            return raw_value
        elif isinstance(annotation, type):
            try:
                return annotation(raw_value)
            except (ValueError, TypeError):
                return raw_value
        return raw_value

    def add_route(self, method: HTTPMethod, path: str, handler: Callable,
                  required_level: str = "read", admin_only: bool = False) -> None:
        self._routes.append(RouteRule(method, path, handler, required_level=required_level, admin_only=admin_only))

    async def start(self) -> bool:
        try:
            logger.info(f"HTTPServer.start() - 路由数：{len(self._routes)}")
            for i, route in enumerate(self._routes):
                logger.info(f"  {i}: {route.method.value} {route.path_pattern}")
            logger.info(f"✅ 已启用可选 URL 前缀：{DFECRAB_URL_PREFIX}/api/...（不带前缀的 /api/... 仍兼容）")

            self._server = await asyncio.start_server(
                self._handle_connection,
                self._host,
                self._port
            )
            self._running = True
            logger.info(f"HTTP 服务器已启动：{self._host}:{self._port}")
            return True
        except Exception as e:
            logger.error(f"HTTP 服务器启动失败：{e}")
            return False

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("HTTP 服务器已停止")

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return

            parts = request_line.decode().strip().split(' ')
            if len(parts) < 2:
                return

            method_str, path_str = parts[0], parts[1]

            request = HTTPRequest()
            request.method = HTTPMethod(method_str)

            if '?' in path_str:
                path_only, query_string = path_str.split('?', 1)
                request.path = path_only
                for param in query_string.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        request.query_params[key] = value
                    elif param:
                        request.query_params[param] = ""
            else:
                request.path = path_str

            while True:
                line = await reader.readline()
                if line == b'\r\n' or line == b'\n' or not line:
                    break
                if b':' in line:
                    key, value = line.decode().strip().split(':', 1)
                    request.headers[key.strip().lower()] = value.strip()

            if 'content-length' in request.headers:
                try:
                    length = int(request.headers['content-length'])
                    if length > 0:
                        request.body = await reader.readexactly(length)
                    else:
                        request.body = b""
                except Exception as e:
                    logger.warning(f"读取请求体失败: {e}")
                    request.body = b""

            response = await self._handle_request(request)

            if hasattr(response, 'is_sse_response') and response.is_sse_response:
                await self._handle_sse_streaming(response, writer)
            else:
                status_text = {
                    200: 'OK', 201: 'Created', 204: 'No Content',
                    400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
                    404: 'Not Found', 405: 'Method Not Allowed', 413: 'Payload Too Large',
                    500: 'Internal Server Error', 502: 'Bad Gateway', 503: 'Service Unavailable',
                }.get(response.status_code, 'Unknown')
                writer.write(f"HTTP/1.1 {response.status_code} {status_text}\r\n".encode())
                for key, value in response.headers.items():
                    writer.write(f"{key}: {value}\r\n".encode())
                writer.write(f"Content-Length: {len(response.body)}\r\n".encode())
                writer.write(b"\r\n")
                if response.body:
                    writer.write(response.body)
                await writer.drain()

        except Exception as e:
            err_msg = str(e).lower()
            if any(x in err_msg for x in ["connection lost", "connection reset", "broken pipe", "client disconnected"]):
                logger.debug(f"客户端断开连接: {e}")
            else:
                logger.error(f"处理连接失败：{e}")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except:
                pass

    async def _handle_sse_streaming(self, sse_response, writer: asyncio.StreamWriter) -> None:
        import json
        import time
        from src.core.event_types import make_event_envelope

        start_ts = time.time()
        last_event_type = "start"

        try:
            writer.write(b"HTTP/1.1 200 OK\r\n")
            writer.write(b"Content-Type: text/event-stream\r\n")
            writer.write(b"Cache-Control: no-cache\r\n")
            writer.write(b"Connection: keep-alive\r\n")
            writer.write(b"Access-Control-Allow-Origin: *\r\n")
            writer.write(b"Access-Control-Allow-Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS\r\n")
            writer.write(b"Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With\r\n")
            writer.write(b"\r\n")
            await writer.drain()

            full_response = ""
            session_id = getattr(sse_response, 'session_id', '')
            correlation_id = getattr(sse_response, 'correlation_id', '')

            if hasattr(sse_response, 'stream_generator') and sse_response.stream_generator:
                async for event in sse_response.stream_generator:
                    try:
                        if writer.is_closing():
                            logger.warning(
                                f"[SSE] 客户端连接已关闭，中止流式 "
                                f"(session={session_id}, elapsed={time.time()-start_ts:.1f}s, "
                                f"last_event={last_event_type})"
                            )
                            break

                        if isinstance(event, dict):
                            if "id" in event and "type" in event and "data" in event and "timestamp" in event and "correlation_id" in event:
                                event_data = json.dumps(event, ensure_ascii=False, default=str)
                            else:
                                envelope = make_event_envelope(event, session_id=session_id, correlation_id=correlation_id)
                                event_data = json.dumps(envelope, ensure_ascii=False, default=str)
                        else:
                            event_data = json.dumps(
                                make_event_envelope({"type": "message", "data": {"content": str(event)}},
                                                    session_id=session_id, correlation_id=correlation_id),
                                ensure_ascii=False, default=str
                            )

                        writer.write(f"data: {event_data}\n\n".encode('utf-8'))
                        await writer.drain()

                        if isinstance(event, dict):
                            last_event_type = event.get("type", last_event_type)
                            if event.get("type") == "message" and "data" in event:
                                full_response += event["data"].get("answer", event["data"].get("content", ""))
                            elif event.get("type") == "message_end" and "data" in event:
                                full_response = event["data"].get("full_response", full_response)
                    except (ConnectionResetError, BrokenPipeError, OSError) as e:
                        logger.warning(
                            f"[SSE] 连接异常断开: {e} "
                            f"(session={session_id}, elapsed={time.time()-start_ts:.1f}s, "
                            f"last_event={last_event_type})"
                        )
                        break
            else:
                logger.warning("SSE响应没有 stream_generator")
        except Exception as e:
            logger.error(f"SSE 流式响应失败: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_request(self, request: HTTPRequest) -> HTTPResponse:
        """处理 HTTP 请求：CORS 预检 + /dfecrab 前缀归一 + 路由分发"""
        if request.method == HTTPMethod.OPTIONS:
            response = HTTPResponse(200)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-User-Id"
            response.headers["Access-Control-Max-Age"] = "86400"
            return response

        # 兼容带 dfecrab 前缀的访问：/dfecrab/api/... 与 /api/... 均可命中同一路由
        request.path = _normalize_api_path(request.path)

        for rule in self._routes:
            path_params = rule.match(request.method, request.path)

            if path_params is not None:
                # ===== 权限拦截 =====
                if PermissionService is not None:
                    user_id = request.headers.get("x-user-id", "guest")
                    perm = PermissionService()
                    # 第一步：系统管理路由（admin_only）仅 admin 可访问
                    if rule.admin_only and not perm.is_admin(user_id):
                        return HTTPResponse(403).json({"success": False, "error": "无权限"})
                    # 第二步：功能权限（read / write）
                    if not perm.has_access(user_id, rule.required_level):
                        return HTTPResponse(403).json({"success": False, "error": "无权限"})
                # ==================
                request.path_params = path_params
                try:
                    if path_params:
                        result = await rule.handler(request, **path_params) if asyncio.iscoroutinefunction(rule.handler) else rule.handler(request, **path_params)
                    else:
                        result = await rule.handler(request) if asyncio.iscoroutinefunction(rule.handler) else rule.handler(request)

                    if isinstance(result, HTTPResponse):
                        return result
                    elif hasattr(result, 'is_sse_response') and result.is_sse_response:
                        return result
                    elif isinstance(result, dict):
                        return HTTPResponse(200).json(result)
                    else:
                        return HTTPResponse(200).text(str(result))
                except Exception as e:
                    logger.error(f"路由处理失败：{e}")
                    import traceback
                    traceback.print_exc()
                    return HTTPResponse(500).text(f"Internal Server Error: {e}")

        return HTTPResponse(404).text("Not Found")