"""
WebSocket Protocol - WebSocket协议处理
提供WebSocket连接管理、消息处理和认证上下文功能
"""

import asyncio
import json
from typing import Dict, Any, Callable, Optional, List, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import uuid
import hashlib
import hmac

from src.utils.logger import get_logger

logger = get_logger(__name__)


class WSMessageType(Enum):
    """WebSocket消息类型"""
    # 客户端 -> 服务器
    PING = "ping"
    AUTH_REQUEST = "auth_request"
    MESSAGE = "message"
    COMMAND = "command"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    CHAT = "chat"                          # 聊天请求（一次性返回）
    CHAT_STREAM = "chat_stream"            # 流式聊天请求
    CHAT_CANCEL = "chat_cancel"            # 中止流式聊天

    # 会话管理（客户端 -> 服务器）
    LIST_SESSIONS = "list_sessions"        # 列出会话
    GET_SESSION = "get_session"            # 获取会话详情
    CREATE_SESSION = "create_session"      # 创建会话
    DELETE_SESSION = "delete_session"      # 删除会话
    GET_SESSION_MESSAGES = "get_session_messages"  # 获取会话消息历史

    # 用户管理（客户端 -> 服务器）
    USER_LOGIN = "user_login"              # 用户登录
    USER_LOGOUT = "user_logout"            # 用户登出

    # 服务器 -> 客户端
    PONG = "pong"
    AUTH_RESPONSE = "auth_response"
    MESSAGE_ACK = "message_ack"
    ERROR = "error"
    EVENT = "event"
    BROADCAST = "broadcast"
    
    # 任务管理 V2
    TASK_PROGRESS = "task_progress"        # 任务进度更新
    TASK_AUDIT = "task_audit"              # 任务审计日志
    TASK_STATUS = "task_status"            # 任务状态变更
    TASK_COMPLETE = "task_complete"        # 任务完成


@dataclass
class WSMessage:
    """WebSocket消息"""
    type: WSMessageType
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    
    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps({
            'type': self.type.value,
            'id': self.id,
            'data': self.data,
            'timestamp': self.timestamp.isoformat(),
            'correlation_id': self.correlation_id
        }, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'WSMessage':
        """从JSON字符串创建
        
        支持两种格式:
        旧格式: {"type":"chat_stream","data":{"message":"...","session_id":"..."}}
        新格式: {"type":"chat_stream","message":"...","session_id":"...","user_id":"...","agent_id":"..."}
        """
        raw = json.loads(json_str)
        data = raw.get('data')
        # 新格式: 顶层字段直接当参数（向后兼容旧格式）
        if data is None:
            data = {k: v for k, v in raw.items()
                    if k not in ('type', 'id', 'timestamp', 'correlation_id')}
        return cls(
            type=WSMessageType(raw['type']),
            id=raw.get('id', str(uuid.uuid4())),
            data=data,
            timestamp=datetime.fromisoformat(raw['timestamp']) if 'timestamp' in raw else datetime.now(),
            correlation_id=raw.get('correlation_id')
        )


@dataclass
class AuthContext:
    """认证上下文"""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    token: Optional[str] = None
    authenticated: bool = False
    auth_method: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)


class WSConnection:
    """WebSocket连接"""
    
    def __init__(
        self,
        connection_id: str,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        auth_context: Optional[AuthContext] = None,
        frame_sender: Optional[Callable[[asyncio.StreamWriter, int, bytes], Any]] = None
    ):
        self.connection_id = connection_id
        self.reader = reader
        self.writer = writer
        self.auth_context = auth_context or AuthContext()
        self._frame_sender = frame_sender
        self.subscriptions: Set[str] = set()
        self.metadata: Dict[str, Any] = {}
        self.created_at = datetime.now()
        self.last_message_at = datetime.now()
        self._closing = False
    
    @property
    def peer_address(self) -> str:
        """获取对端地址"""
        return f"{self.writer.get_extra_info('peername')}"
    
    async def send(self, message: WSMessage) -> bool:
        """发送消息"""
        try:
            if self._closing:
                return False

            if self.writer.is_closing():
                self._closing = True
                return False
            
            data = message.to_json()
            
            # 使用帧发送器（如果存在）
            if self._frame_sender:
                await self._frame_sender(self.writer, 0x1, data.encode())
            else:
                # 回退到直接发送（兼容旧代码）
                self.writer.write(data.encode() + b'\n')
                await self.writer.drain()
            
            self.last_message_at = datetime.now()
            return True
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._closing = True
            return False
        except Exception as e:
            logger.error(f"发送消息失败 [{self.connection_id}]: {e}")
            return False
    
    async def send_error(self, error_message: str, correlation_id: Optional[str] = None):
        """发送错误消息"""
        message = WSMessage(
            type=WSMessageType.ERROR,
            data={'message': error_message},
            correlation_id=correlation_id
        )
        await self.send(message)
    
    async def close(self, code: int = 1000, reason: str = ""):
        """关闭连接"""
        if self._closing:
            return
        
        self._closing = True
        
        try:
            close_message = WSMessage(
                type=WSMessageType.ERROR,
                data={'code': code, 'reason': reason}
            )
            await self.send(close_message)
            self.writer.close()
            await self.writer.wait_closed()
        except Exception as e:
            logger.error(f"关闭连接失败 [{self.connection_id}]: {e}")
    
    def update_activity(self):
        """更新最后活动时间"""
        self.last_message_at = datetime.now()
        self.auth_context.last_activity = datetime.now()


class WSConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self, event_bus: Optional[Any] = None):
        self._connections: Dict[str, WSConnection] = {}
        self._event_bus = event_bus
        self._message_handlers: Dict[WSMessageType, Callable] = {}
        self._auth_handlers: Dict[str, Callable] = {}
    
    def add_connection(self, connection: WSConnection):
        """添加连接"""
        self._connections[connection.connection_id] = connection
        logger.info(f"WebSocket连接已添加: {connection.connection_id}")
    
    def remove_connection(self, connection_id: str):
        """移除连接"""
        if connection_id in self._connections:
            del self._connections[connection_id]
            logger.info(f"WebSocket连接已移除: {connection_id}")
    
    def get_connection(self, connection_id: str) -> Optional[WSConnection]:
        """获取连接"""
        return self._connections.get(connection_id)
    
    def get_all_connections(self) -> List[WSConnection]:
        """获取所有连接"""
        return list(self._connections.values())
    
    def get_authenticated_connections(self) -> List[WSConnection]:
        """获取已认证的连接"""
        return [
            conn for conn in self._connections.values()
            if conn.auth_context.authenticated
        ]
    
    def broadcast(self, message: WSMessage, authenticated_only: bool = True):
        """广播消息"""
        connections = (
            self.get_authenticated_connections()
            if authenticated_only
            else self.get_all_connections()
        )
        
        for connection in connections:
            asyncio.create_task(connection.send(message))
    
    async def handle_message(
        self,
        connection_id: str,
        message: WSMessage
    ) -> Optional[WSMessage]:
        """处理消息"""
        if connection_id not in self._connections:
            logger.warning(f"连接不存在: {connection_id}")
            return None
        
        connection = self._connections[connection_id]
        connection.update_activity()
        logger.info(f"收到 WebSocket 消息: 连接={connection_id}, 类型={message.type.value}, 消息ID={message.id}, 关联ID={message.correlation_id}")

        # 心跳：PING 免认证直接应答 PONG（无需登录态，已刷新活动时间）
        if message.type == WSMessageType.PING:
            return WSMessage(
                type=WSMessageType.PONG,
                data={'pong': True},
                correlation_id=message.correlation_id
            )

        # 处理认证请求
        if message.type == WSMessageType.AUTH_REQUEST:
            return await self._handle_auth(connection, message)
        
        # 检查认证状态
        if not connection.auth_context.authenticated:
            return WSMessage(
                type=WSMessageType.ERROR,
                data={'message': 'Not authenticated'},
                correlation_id=message.correlation_id
            )
        
        # 处理订阅请求
        if message.type == WSMessageType.SUBSCRIBE:
            return await self._handle_subscribe(connection, message)
        
        if message.type == WSMessageType.UNSUBSCRIBE:
            return await self._handle_unsubscribe(connection, message)
        
        # 调用消息处理器
        handler = self._message_handlers.get(message.type)
        if handler:
            try:
                return await handler(connection, message)
            except Exception as e:
                logger.error(f"消息处理失败: {e}")
                return WSMessage(
                    type=WSMessageType.ERROR,
                    data={'message': str(e)},
                    correlation_id=message.correlation_id
                )
        
        return None
    
    async def _handle_auth(
        self,
        connection: WSConnection,
        message: WSMessage
    ) -> WSMessage:
        """处理认证请求"""
        auth_data = message.data
        auth_method = auth_data.get('method', 'token')
        
        handler = self._auth_handlers.get(auth_method)
        if not handler:
            return WSMessage(
                type=WSMessageType.AUTH_RESPONSE,
                data={'success': False, 'error': f'Unknown auth method: {auth_method}'},
                correlation_id=message.correlation_id
            )
        
        try:
            success, auth_context = await handler(auth_data)
            
            if success:
                connection.auth_context = auth_context
                connection.auth_context.authenticated = True
                
                return WSMessage(
                    type=WSMessageType.AUTH_RESPONSE,
                    data={'success': True, 'method': auth_method},
                    correlation_id=message.correlation_id
                )
            else:
                return WSMessage(
                    type=WSMessageType.AUTH_RESPONSE,
                    data={'success': False, 'error': 'Authentication failed'},
                    correlation_id=message.correlation_id
                )
        except Exception as e:
            logger.error(f"认证处理失败: {e}")
            return WSMessage(
                type=WSMessageType.AUTH_RESPONSE,
                data={'success': False, 'error': str(e)},
                correlation_id=message.correlation_id
            )
    
    async def _handle_subscribe(
        self,
        connection: WSConnection,
        message: WSMessage
    ) -> WSMessage:
        """处理订阅请求"""
        event_type = message.data.get('event_type')
        if not event_type:
            return WSMessage(
                type=WSMessageType.ERROR,
                data={'message': 'Missing event_type'},
                correlation_id=message.correlation_id
            )
        
        connection.subscriptions.add(event_type)
        
        return WSMessage(
            type=WSMessageType.EVENT,
            data={'subscribed': event_type},
            correlation_id=message.correlation_id
        )
    
    async def _handle_unsubscribe(
        self,
        connection: WSConnection,
        message: WSMessage
    ) -> WSMessage:
        """处理取消订阅请求"""
        event_type = message.data.get('event_type')
        if not event_type:
            return WSMessage(
                type=WSMessageType.ERROR,
                data={'message': 'Missing event_type'},
                correlation_id=message.correlation_id
            )
        
        connection.subscriptions.discard(event_type)
        
        return WSMessage(
            type=WSMessageType.EVENT,
            data={'unsubscribed': event_type},
            correlation_id=message.correlation_id
        )
    
    def register_message_handler(self, message_type: WSMessageType, handler: Callable):
        """注册消息处理器"""
        self._message_handlers[message_type] = handler
        logger.info(f"消息处理器已注册: {message_type.value}")

    def register_auth_handler(self, method: str, handler: Callable):
        """注册认证处理器"""
        self._auth_handlers[method] = handler
        logger.info(f"认证处理器已注册: {method}")
    
    async def send_to_subscribers(self, event_type: str, data: Dict[str, Any]):
        """向订阅了特定事件类型的连接发送消息"""
        message = WSMessage(
            type=WSMessageType.EVENT,
            data={'event_type': event_type, 'data': data},
        )
        
        sent_count = 0
        for connection in self.get_authenticated_connections():
            if event_type in connection.subscriptions:
                success = await connection.send(message)
                if success:
                    sent_count += 1
        
        if sent_count > 0:
            logger.debug(f"Event {event_type} sent to {sent_count} subscribers")
    
    async def send_task_progress(self, task_id: str, progress_data: Dict[str, Any]):
        """发送任务进度更新"""
        message = WSMessage(
            type=WSMessageType.TASK_PROGRESS,
            data={'task_id': task_id, 'progress': progress_data},
        )
        
        # 发送给订阅了该任务的连接
        for connection in self.get_authenticated_connections():
            if f"task:{task_id}" in connection.subscriptions or "task:*" in connection.subscriptions:
                await connection.send(message)
    
    async def send_task_complete(self, task_id: str, result_data: Dict[str, Any]):
        """发送任务完成通知"""
        message = WSMessage(
            type=WSMessageType.TASK_COMPLETE,
            data={'task_id': task_id, 'result': result_data},
        )
        
        for connection in self.get_authenticated_connections():
            if f"task:{task_id}" in connection.subscriptions or "task:*" in connection.subscriptions:
                await connection.send(message)
    
    async def cleanup_idle_connections(self, idle_timeout: timedelta):
        """清理空闲连接"""
        now = datetime.now()
        idle_connections = []
        
        for connection_id, connection in self._connections.items():
            if now - connection.last_message_at > idle_timeout:
                idle_connections.append(connection_id)
        
        for connection_id in idle_connections:
            connection = self._connections[connection_id]
            await connection.close(1001, "Idle timeout")
            self.remove_connection(connection_id)
        
        if idle_connections:
            logger.info(f"清理了 {len(idle_connections)} 个空闲连接")


class TokenAuthHandler:
    """Token认证处理器"""
    
    def __init__(self, secret_key: str):
        self._secret_key = secret_key
    
    async def authenticate(self, auth_data: Dict[str, Any]) -> tuple[bool, AuthContext]:
        """
        验证Token
        
        Args:
            auth_data: 包含token的数据
            
        Returns:
            (是否成功, 认证上下文)
        """
        token = auth_data.get('token')
        if not token:
            return False, AuthContext()
        
        # 简单Token验证（实际应该用JWT或其他更安全的方式）
        # 这里只是示例
        try:
            # 验证token格式
            parts = token.split('.')
            if len(parts) != 3:
                return False, AuthContext()
            
            # 验证签名
            expected_sig = hmac.new(
                self._secret_key.encode(),
                f"{parts[0]}.{parts[1]}".encode(),
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(parts[2], expected_sig):
                return False, AuthContext()
            
            # 解析payload
            import base64
            import json
            
            payload = json.loads(base64.b64decode(parts[1]))
            
            auth_context = AuthContext(
                user_id=payload.get('user_id'),
                session_id=payload.get('session_id'),
                token=token,
                authenticated=True,
                auth_method='token',
                metadata=payload
            )
            
            return True, auth_context
        except Exception as e:
            logger.error(f"Token验证失败: {e}")
            return False, AuthContext()
    
    @staticmethod
    def generate_token(user_id: str, session_id: str, secret_key: str) -> str:
        """生成Token"""
        import base64
        import json
        import time
        
        header = base64.b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode()
        
        payload = base64.b64encode(json.dumps({
            "user_id": user_id,
            "session_id": session_id,
            "iat": int(time.time())
        }).encode()).decode()
        
        signature = hmac.new(
            secret_key.encode(),
            f"{header}.{payload}".encode(),
            hashlib.sha256
        ).hexdigest()
        
        return f"{header}.{payload}.{signature}"
