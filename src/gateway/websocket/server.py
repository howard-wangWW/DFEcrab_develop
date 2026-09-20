"""
WebSocket Server - WebSocket服务器实现
提供WebSocket连接握手、帧解析和连接管理
"""

import asyncio
import json
import logging
import base64
import hashlib
import uuid
from datetime import timedelta
from typing import Dict, Any, Optional, Callable

from .connection import (
    WSConnectionManager,
    WSConnection,
    WSMessage,
    WSMessageType,
    AuthContext
)

logger = logging.getLogger(__name__)


class WebSocketServer:
    """WebSocket服务器"""
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 6790,
        connection_manager: Optional[WSConnectionManager] = None,
        event_bus: Any = None,
        heartbeat_interval: int = 30,
        idle_timeout: int = 90
    ):
        self._host = host
        self._port = port
        self._connection_manager = connection_manager or WSConnectionManager(event_bus)
        self._event_bus = event_bus
        self._server: Optional[asyncio.Server] = None
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        # 心跳参数：服务端每 heartbeat_interval 秒发一次协议 Ping 帧探测；
        # 超过 idle_timeout 秒无任何活动（含客户端 Pong 应答）即判定僵尸连接并断开
        self._heartbeat_interval = max(int(heartbeat_interval or 30), 5)
        self._idle_timeout = max(int(idle_timeout or 90), self._heartbeat_interval + 5)
        self._message_handlers: Dict[WSMessageType, Callable] = {}
        
    def get_connection_manager(self) -> WSConnectionManager:
        """获取连接管理器"""
        return self._connection_manager
    
    def register_message_handler(self, message_type: WSMessageType, handler: Callable):
        """注册消息处理器"""
        self._connection_manager.register_message_handler(message_type, handler)
        
    def register_auth_handler(self, method: str, handler: Callable):
        """注册认证处理器"""
        self._connection_manager.register_auth_handler(method, handler)
    
    async def start(self) -> bool:
        """启动WebSocket服务器"""
        try:
            self._server = await asyncio.start_server(
                self._handle_connection,
                self._host,
                self._port
            )
            self._running = True
            # 启动心跳监控后台任务
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info(f"WebSocket 服务器已启动：{self._host}:{self._port}"
                        f"（心跳 interval={self._heartbeat_interval}s, idle_timeout={self._idle_timeout}s）")
            return True
        except Exception as e:
            logger.error(f"WebSocket 服务器启动失败：{e}")
            return False
    
    async def stop(self) -> None:
        """停止WebSocket服务器"""
        if not self._running:
            return
        
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("WebSocket 服务器已停止")
    
    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """处理WebSocket连接"""
        connection_id = str(uuid.uuid4())[:8]
        logger.info(f"新的WebSocket连接: {connection_id}")
        
        try:
            # 1. 执行WebSocket握手
            if not await self._perform_handshake(reader, writer):
                logger.warning(f"WebSocket握手失败: {connection_id}")
                writer.close()
                await writer.wait_closed()
                return
            
            # 2. 创建连接对象
            connection = WSConnection(
                connection_id=connection_id,
                reader=reader,
                writer=writer,
                auth_context=None,
                frame_sender=self._send_frame
            )
            self._connection_manager.add_connection(connection)
            
            # 3. 处理消息循环
            await self._message_loop(connection)
            
        except Exception as e:
            logger.error(f"WebSocket连接处理异常 [{connection_id}]: {e}")
        finally:
            # 清理连接
            self._connection_manager.remove_connection(connection_id)
            writer.close()
            try:
                await writer.wait_closed()
            except:
                pass
            logger.info(f"WebSocket连接关闭: {connection_id}")
    
    async def _perform_handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
        """执行WebSocket握手"""
        try:
            # 读取握手请求头
            request_headers = await self._read_http_headers(reader)
            if not request_headers:
                return False
            
            # 检查是否为WebSocket升级请求
            if request_headers.get('upgrade', '').lower() != 'websocket':
                return False
            
            # 获取Sec-WebSocket-Key
            sec_key = request_headers.get('sec-websocket-key', '')
            if not sec_key:
                return False
            
            # 计算Sec-WebSocket-Accept
            accept_key = self._compute_accept_key(sec_key)
            
            # 发送握手响应
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept_key}\r\n"
                "\r\n"
            )
            writer.write(response.encode())
            await writer.drain()
            
            return True
            
        except Exception as e:
            logger.error(f"WebSocket握手异常: {e}")
            return False
    
    async def _read_http_headers(self, reader: asyncio.StreamReader) -> Dict[str, str]:
        """读取HTTP头"""
        headers = {}
        try:
            # 读取请求行
            request_line = await reader.readline()
            if not request_line:
                return {}
            
            # 读取头行
            while True:
                line = await reader.readline()
                if line == b'\r\n' or line == b'\n' or not line:
                    break
                
                line_str = line.decode().strip()
                if ':' in line_str:
                    key, value = line_str.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
                    
        except Exception as e:
            logger.error(f"读取HTTP头异常: {e}")
        
        return headers
    
    def _compute_accept_key(self, key: str) -> str:
        """计算WebSocket Accept Key"""
        GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept = base64.b64encode(
            hashlib.sha1((key + GUID).encode()).digest()
        ).decode()
        return accept
    
    async def _message_loop(self, connection: WSConnection):
        """消息循环"""
        try:
            while not connection._closing:
                # 读取WebSocket帧
                frame = await self._read_frame(connection.reader)
                if frame is None:
                    break
                
                opcode, payload = frame
                
                # 处理不同类型的帧
                if opcode == 0x1:  # 文本帧
                    try:
                        message_text = payload.decode('utf-8')
                        logger.debug(f"收到消息 [{connection.connection_id}]: {message_text[:100]}")
                        
                        # 解析为WSMessage
                        ws_message = WSMessage.from_json(message_text)
                        
                        # [修复] 流式聊天请求异步执行，不阻塞消息循环，确保 cancel 等消息能被及时处理
                        if ws_message.type == WSMessageType.CHAT_STREAM:
                            asyncio.create_task(self._run_stream_handler(
                                connection, ws_message
                            ))
                        else:
                            # 其他消息（包括 chat_cancel）同步处理，保证即时响应
                            response = await self._connection_manager.handle_message(
                                connection.connection_id,
                                ws_message
                            )
                            if response:
                                await connection.send(response)
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"消息JSON解析失败: {e}")
                        await connection.send_error(f"Invalid JSON: {str(e)}")
                    except Exception as e:
                        logger.error(f"消息处理异常: {e}")
                        await connection.send_error(f"Internal error: {str(e)}")
                        
                elif opcode == 0x8:  # 关闭帧
                    logger.info(f"收到关闭帧 [{connection.connection_id}]")
                    await connection.close(1000, "Normal closure")
                    break
                    
                elif opcode == 0x9:  # Ping帧
                    logger.debug(f"收到Ping帧 [{connection.connection_id}]")
                    await self._send_frame(connection.writer, 0xA, payload)  # Pong
                    
                elif opcode == 0xA:  # Pong帧（应答服务端心跳探测，证明连接存活）
                    logger.debug(f"收到Pong帧 [{connection.connection_id}]")
                    connection.update_activity()
                    
                else:
                    logger.warning(f"不支持的WebSocket操作码: {opcode}")
                    
        except Exception as e:
            logger.error(f"消息循环异常 [{connection.connection_id}]: {e}")
    
    async def _heartbeat_loop(self):
        """心跳监控循环：定期向所有连接发协议 Ping 帧探测活性，并清理僵尸连接。

        正常客户端（浏览器原生 WS API）收到 Ping 帧会自动回 Pong 帧，
        Pong 帧会刷新连接的 last_message_at；超过 idle_timeout 无任何活动的连接视为僵尸并断开。
        """
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)

                # 1. 向所有连接发送协议 Ping 帧（客户端标准实现会自动应答 Pong）
                for conn in self._connection_manager.get_all_connections():
                    try:
                        await self._send_frame(conn.writer, 0x9, b'')
                    except Exception as e:
                        logger.debug(f"发送 Ping 帧失败 [{conn.connection_id}]: {e}")

                # 2. 清理超过 idle_timeout 无任何活动（含 Pong 应答）的连接
                await self._connection_manager.cleanup_idle_connections(
                    timedelta(seconds=self._idle_timeout)
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"心跳监控任务异常: {e}")

    async def _run_stream_handler(self, connection: WSConnection, ws_message: WSMessage):
        """异步运行流式消息处理器，与消息循环并发执行"""
        try:
            response = await self._connection_manager.handle_message(
                connection.connection_id, ws_message
            )
            if response:
                await connection.send(response)
        except Exception as e:
            logger.error(f"流式消息处理异常 [{connection.connection_id}]: {e}")
    
    async def _read_frame(self, reader: asyncio.StreamReader):
        """读取WebSocket帧"""
        try:
            # 读取前两个字节
            header = await reader.read(2)
            if len(header) < 2:
                return None
            
            first_byte, second_byte = header[0], header[1]
            
            fin = (first_byte & 0x80) != 0
            opcode = first_byte & 0x0F
            masked = (second_byte & 0x80) != 0
            payload_len = second_byte & 0x7F
            
            # 读取扩展长度
            if payload_len == 126:
                len_bytes = await reader.read(2)
                if len(len_bytes) < 2:
                    return None
                payload_len = int.from_bytes(len_bytes, 'big')
            elif payload_len == 127:
                len_bytes = await reader.read(8)
                if len(len_bytes) < 8:
                    return None
                payload_len = int.from_bytes(len_bytes, 'big')
            
            # 读取掩码键（如果有）
            mask_key = None
            if masked:
                mask_key = await reader.read(4)
                if len(mask_key) < 4:
                    return None
            
            # 读取有效载荷
            payload = await reader.read(payload_len)
            if len(payload) < payload_len:
                return None
            
            # 解码掩码（如果有）
            if masked and mask_key:
                payload = bytes(payload[i] ^ mask_key[i % 4] for i in range(len(payload)))
            
            return opcode, payload
            
        except Exception as e:
            logger.error(f"读取WebSocket帧异常: {e}")
            return None
    
    async def _send_frame(self, writer: asyncio.StreamWriter, opcode: int, payload: bytes):
        """发送WebSocket帧"""
        try:
            if writer.is_closing():
                return

            # 构建帧头
            frame = bytearray()
            
            # FIN=1, 操作码
            frame.append(0x80 | opcode)
            
            # 负载长度
            payload_len = len(payload)
            if payload_len <= 125:
                frame.append(payload_len)
            elif payload_len <= 65535:
                frame.append(126)
                frame.extend(payload_len.to_bytes(2, 'big'))
            else:
                frame.append(127)
                frame.extend(payload_len.to_bytes(8, 'big'))
            
            # 添加负载
            frame.extend(payload)
            
            writer.write(frame)
            await writer.drain()
            
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        except Exception as e:
            logger.error(f"发送WebSocket帧异常: {e}")
            
    async def broadcast(self, message: WSMessage, authenticated_only: bool = True):
        """广播消息"""
        self._connection_manager.broadcast(message, authenticated_only)
        
    async def send_to_connection(self, connection_id: str, message: WSMessage) -> bool:
        """发送消息到指定连接"""
        connection = self._connection_manager.get_connection(connection_id)
        if not connection:
            return False
        return await connection.send(message)