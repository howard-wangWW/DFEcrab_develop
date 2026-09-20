"""
MCP HTTP 协议客户端。

实现基于 JSON-RPC 2.0 的 MCP 协议客户端，支持：
1. initialize 握手
2. tools/list 工具列表获取
3. tools/call 工具调用
4. 缓存工具列表到本地配置

支持 transport: streamable_http, http, sse

使用 requests 库实现同步 HTTP 调用，兼容 Windows 环境。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-06-18"
JSONRPC_VERSION = "2.0"

_request_id = 0


def _next_id() -> int:
    global _request_id
    _request_id += 1
    return _request_id


class MCPHTTPError(Exception):
    """MCP HTTP 协议错误"""

    def __init__(self, message: str, code: int = -1, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class MCPHTTPClient:
    """MCP HTTP/Streamable HTTP 传输客户端（基于 requests 同步实现）"""

    def __init__(
        self,
        base_url: str,
        transport: str = "streamable_http",
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        server_name: str = "",
    ):
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._headers = headers or {}
        self._timeout = timeout
        # ★ 用量统计：MCP 服务名（埋点用，未传时回落 base_url）
        self._server_name = server_name or self._base_url
        self._initialized = False
        self._server_capabilities: Dict[str, Any] = {}
        # ★ 服务端 instructions（initialize 握手返回，LibreChat serverInstructions 同款机制）
        self._instructions: str = ""
        self._session_id: Optional[str] = None
        self._http = requests.Session()

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        hdrs = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            hdrs["Mcp-Session-Id"] = self._session_id
        hdrs.update(self._headers)
        if extra:
            hdrs.update(extra)
        return hdrs

    def _build_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        req = {
            "jsonrpc": JSONRPC_VERSION,
            "method": method,
            "id": _next_id(),
        }
        if params is not None:
            req["params"] = params
        return req

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self._base_url
        try:
            response = self._http.post(
                url,
                json=payload,
                headers=self._build_headers(),
                timeout=self._timeout,
            )
        except requests.Timeout as e:
            raise MCPHTTPError(f"请求超时: {e}") from e
        except requests.ConnectionError as e:
            raise MCPHTTPError(f"连接失败: {e}") from e
        except requests.RequestException as e:
            raise MCPHTTPError(f"请求错误: {e}") from e

        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

        # ★ BUG-4 修复：MCP 协议规定 404 表示 session 失效（服务器重启/过期），
        # 丢弃旧 session 并重新 initialize 一次后重试，避免死 session 永久失败。
        if response.status_code == 404 and self._session_id:
            logger.info(f"MCP session 失效，重新 initialize: {self._base_url}")
            self._session_id = None
            self._initialized = False
            try:
                self.initialize()
            except MCPHTTPError:
                # 重新握手失败则保持原错误，交由调用方处理
                raise
            response = self._http.post(
                url,
                json=payload,
                headers=self._build_headers(),
                timeout=self._timeout,
            )
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id

        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                return self._parse_sse(response.text)
            try:
                return response.json()
            except json.JSONDecodeError:
                return {"result": response.text}
        elif response.status_code == 202:
            return {"accepted": True}
        elif response.status_code == 401 or response.status_code == 403:
            raise MCPHTTPError(
                f"认证失败 (HTTP {response.status_code}): {response.text[:300]}",
                code=response.status_code,
            )
        else:
            raise MCPHTTPError(
                f"HTTP {response.status_code}: {response.text[:500]}",
                code=response.status_code,
            )

    def _parse_sse(self, raw: str) -> Dict[str, Any]:
        """解析 SSE 响应"""
        result = {"sse_events": []}
        current_event = None
        current_data = ""

        for line in raw.split("\n"):
            line = line.rstrip("\r")
            if not line:
                if current_event is not None or current_data:
                    event_data = {}
                    if current_data:
                        try:
                            event_data = json.loads(current_data.strip())
                        except json.JSONDecodeError:
                            event_data = {"raw": current_data.strip()}
                    result["sse_events"].append({
                        "event": current_event or "message",
                        "data": event_data,
                    })
                    if isinstance(event_data, dict) and "result" in event_data:
                        result["result"] = event_data["result"]
                    elif "result" not in result:
                        result["result"] = event_data
                current_event = None
                current_data = ""
            elif line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                current_data += line[5:].strip() + "\n"

        if current_data:
            try:
                data = json.loads(current_data.strip())
                if isinstance(data, dict) and "result" in data:
                    result["result"] = data["result"]
                elif "result" not in result:
                    result["result"] = data
            except json.JSONDecodeError:
                if "result" not in result:
                    result["result"] = current_data.strip()

        return result

    def initialize(self) -> Dict[str, Any]:
        """MCP initialize 握手"""
        if self._initialized:
            return self._server_capabilities

        payload = self._build_request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "DFEcrab",
                    "version": "4.0.0",
                },
            },
        )

        resp = self._post(payload)

        if "error" in resp:
            err = resp["error"]
            raise MCPHTTPError(
                f"初始化失败: {err.get('message', str(err))}",
                code=err.get("code", -1),
                data=err.get("data"),
            )

        result = resp.get("result", resp)
        self._initialized = True
        self._server_capabilities = result
        self._instructions = (result.get("instructions") or "") if isinstance(result, dict) else ""
        # ★ 降为 debug：MCPHTTPClient 实例在 MCPClient 单例内复用，避免重复握手刷屏
        logger.debug(f"MCP 服务器已初始化: {self._base_url}")
        return result

    def get_instructions(self) -> str:
        """返回服务端在 initialize 时声明的 instructions（SOP / 工具调用须知）。

        对齐 LibreChat serverInstructions：客户端将该文本注入 agent 系统提示后，
        模型会遵守服务端定义的工具调用规范（如"先 search_feeders 定位再取拓扑"）。
        """
        return self._instructions

    def list_tools(self) -> List[Dict[str, Any]]:
        """获取 MCP 服务器提供的工具列表"""
        if not self._initialized:
            self.initialize()

        payload = self._build_request("tools/list")
        resp = self._post(payload)

        if "error" in resp:
            err = resp["error"]
            raise MCPHTTPError(
                f"获取工具列表失败: {err.get('message', str(err))}",
                code=err.get("code", -1),
                data=err.get("data"),
            )

        result = resp.get("result", {})
        tools = result.get("tools", [])
        logger.info(f"从 {self._base_url} 获取到 {len(tools)} 个工具")
        return tools

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调用 MCP 工具

        ★ 用量统计：本方法是所有 MCP 工具调用的唯一出口（含 test/sync 场景），
        在此单点埋点即可覆盖"这一天 MCP 的调用次数"；成功与失败都会记录。
        """
        import time as _time
        from src.monitoring.usage_store import record_mcp_call

        _t0 = _time.time()
        try:
            if not self._initialized:
                self.initialize()

            payload = self._build_request(
                "tools/call",
                {
                    "name": tool_name,
                    "arguments": arguments or {},
                },
            )

            logger.info(f"[MCP] 调用 {self._base_url} 工具 {tool_name} args={arguments or {}}")
            resp = self._post(payload)

            if "error" in resp:
                err = resp["error"]
                raise MCPHTTPError(
                    f"工具调用失败: {err.get('message', str(err))}",
                    code=err.get("code", -1),
                    data=err.get("data"),
                )

            result = resp.get("result", resp)
            _dt = _time.time() - _t0
            logger.info(f"[MCP] {tool_name} 返回 长度={len(str(result))} 耗时={_dt:.2f}s")
            logger.debug(f"[MCP] {tool_name} 原始响应={str(result)[:500]!r}")
            record_mcp_call(self._server_name, tool_name, True, int(_dt * 1000))
            return result
        except Exception as e:
            _dt = _time.time() - _t0
            logger.error(f"[MCP] {tool_name} 调用失败: {e} 耗时={_dt:.2f}s")
            record_mcp_call(self._server_name, tool_name, False, int(_dt * 1000), str(e))
            raise

    def ping(self) -> bool:
        """检测 MCP 服务器是否可用。

        ★ BUG-6 修复：先完成 initialize 握手再发 ping，
        兼容严格要求先握手才接受请求的 MCP 网关（否则会误判"不通"）。
        """
        try:
            if not self._initialized:
                self.initialize()
            payload = self._build_request("ping")
            resp = self._post(payload)
            return "error" not in resp
        except MCPHTTPError:
            return False
        except Exception:
            return False

    def close(self):
        """关闭连接"""
        self._initialized = False
        self._session_id = None
        self._http.close()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def server_capabilities(self) -> Dict[str, Any]:
        return self._server_capabilities