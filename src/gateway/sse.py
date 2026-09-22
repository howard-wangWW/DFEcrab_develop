"""SSE 流式响应载体（与 HTTP 服务器解耦）

`HTTPServer` 通过鸭子类型识别：`hasattr(result, "is_sse_response")` 为真即走 SSE 输出分支，
因此本类可以被网关、任务域、任何 handler 复用，无需依赖 http.server。

从 `grpc_server.py` 抽出，导入方请使用：
    from src.gateway.sse import SSEStreamingResponse
"""

from __future__ import annotations


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