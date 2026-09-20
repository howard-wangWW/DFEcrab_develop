"""
Event Bus - 事件总线（扩展版）

新增 ReAct 事件类型（S2.4），支持事件历史记录和订阅者查询。
"""

import asyncio
import logging
import time
from typing import Dict, List, Callable, Any, Optional, Tuple
from enum import Enum
import uuid

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 事件类型枚举
# ══════════════════════════════════════════════════════════════════════════════

class EventType(Enum):
    """基础设施事件类型"""
    SERVICE_REGISTERED   = "service.registered"
    SERVICE_UNREGISTERED = "service.unregistered"
    SERVICE_STARTED      = "service.started"
    SERVICE_STOPPED      = "service.stopped"
    MESSAGE_RECEIVED     = "message.received"
    MESSAGE_SENT         = "message.sent"
    ERROR                = "error"


class ReactEventType(str, Enum):
    """★ S2.4: ReAct 协议事件类型（与 src/core/event_types.py 对齐）"""
    THINKING      = "thinking"
    TOOL_CALL     = "tool_call"
    TOOL_RESULT   = "tool_result"
    PLAN_CREATED  = "plan_created"
    PLAN_STEP     = "plan_step"
    FINAL         = "final"
    ERROR         = "error"
    CONFIRMATION  = "confirmation"


# ══════════════════════════════════════════════════════════════════════════════
# Event 数据类
# ══════════════════════════════════════════════════════════════════════════════

class Event:
    """事件对象"""

    def __init__(
        self,
        event_type: EventType,
        data: Any = None,
        source: str = "",
        timestamp: Optional[float] = None,
    ):
        self.event_type = event_type
        self.data = data
        self.source = source
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
        }


# ══════════════════════════════════════════════════════════════════════════════
# EventBus
# ══════════════════════════════════════════════════════════════════════════════

class EventBus:
    """事件总线（扩展版）"""

    # 历史记录上限
    MAX_HISTORY: int = 1000

    def __init__(self):
        self._handlers: Dict[EventType, List[Tuple[str, Callable]]] = {}
        self._react_handlers: Dict[str, List[Tuple[str, Callable]]] = {}
        self._running = False
        # ★ S2.4: 事件历史记录
        self._event_history: List[Event] = []
        logger.info("事件总线初始化完成")

    # ── 订阅/取消订阅（基础设施事件） ──

    def subscribe(self, event_type: EventType, handler: Callable) -> str:
        """订阅基础设施事件"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []

        handler_id = str(uuid.uuid4())
        self._handlers[event_type].append((handler_id, handler))
        logger.debug(f"事件处理器已订阅：{event_type.value}")
        return handler_id

    def unsubscribe(self, handler_id: str) -> bool:
        """取消订阅"""
        for event_type, handlers in self._handlers.items():
            for i, (hid, _) in enumerate(handlers):
                if hid == handler_id:
                    del handlers[i]
                    logger.debug(f"事件处理器已取消订阅：{event_type.value}")
                    return True

        for event_type, handlers in self._react_handlers.items():
            for i, (hid, _) in enumerate(handlers):
                if hid == handler_id:
                    del handlers[i]
                    logger.debug(f"ReAct 事件处理器已取消订阅：{event_type}")
                    return True

        return False

    async def publish(self, event_type: EventType, data: Any = None) -> None:
        """发布基础设施事件"""
        if event_type not in self._handlers:
            return

        for _, handler in self._handlers[event_type]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error(f"事件处理失败 [{event_type.value}]: {e}")

    # ── ★ S2.4: ReAct 事件订阅/发布 ──

    def subscribe_react(self, event_type: str, handler: Callable) -> str:
        """订阅 ReAct 事件（按字符串类型订阅，如 \"thinking\", \"tool_call\"）

        Args:
            event_type: 事件类型字符串（ReactEventType 的值）
            handler: 处理函数，签名 handler(data: dict) 或 async handler(data: dict)

        Returns:
            str: handler_id，用于取消订阅
        """
        if event_type not in self._react_handlers:
            self._react_handlers[event_type] = []

        handler_id = str(uuid.uuid4())
        self._react_handlers[event_type].append((handler_id, handler))
        logger.debug(f"ReAct 事件处理器已订阅：{event_type}")
        return handler_id

    def subscribe_all_react(self, handler: Callable) -> str:
        """订阅所有 ReAct 事件（通配符 *）

        Args:
            handler: 处理函数

        Returns:
            str: handler_id
        """
        return self.subscribe_react("*", handler)

    async def publish_react(
        self,
        event_type: str,
        data: Dict[str, Any],
        session_id: str = "",
        user_id: str = "",
    ) -> None:
        """发布 ReAct 事件

        同时触发：
          1. 精确匹配的处理器（如 subscribe_react("thinking", ...)）
          2. 通配符处理器（subscribe_react("*", ...)）

        Args:
            event_type: 事件类型字符串
            data: 事件数据
            session_id: 会话 ID
            user_id: 用户 ID
        """
        # 构建事件对象
        event_obj = Event(
            event_type=EventType.MESSAGE_SENT,
            data={
                "react_type": event_type,
                "data": data,
                "session_id": session_id,
                "user_id": user_id,
                "timestamp": time.time(),
            },
            source="react_loop",
        )
        self._add_to_history(event_obj)

        # 构建 ReAct 事件负载
        payload = {
            "type": event_type,
            "data": data,
            "session_id": session_id,
            "user_id": user_id,
            "timestamp": time.time(),
        }

        # 派发给精确匹配的处理器
        handlers = self._react_handlers.get(event_type, [])
        for _, handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception as e:
                logger.error(f"ReAct 事件处理失败 [{event_type}]: {e}")

        # 派发给通配符处理器
        wildcard_handlers = self._react_handlers.get("*", [])
        for _, handler in wildcard_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)
            except Exception as e:
                logger.error(f"ReAct 通配符事件处理失败 [{event_type}]: {e}")

    # ── ★ S2.4: 事件历史 + 订阅者查询 ──

    def _add_to_history(self, event: Event) -> None:
        """添加事件到历史记录（自动裁剪）"""
        self._event_history.append(event)
        if len(self._event_history) > self.MAX_HISTORY:
            self._event_history = self._event_history[-self.MAX_HISTORY:]

    def get_event_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的事件历史

        Args:
            limit: 返回数量上限

        Returns:
            list[dict]: 事件列表
        """
        return [
            e.to_dict()
            for e in self._event_history[-limit:]
        ]

    def get_subscribers(self, event_type: EventType) -> List[str]:
        """获取指定事件类型的订阅者 ID 列表

        Args:
            event_type: EventType 枚举值

        Returns:
            list[str]: handler_id 列表
        """
        handlers = self._handlers.get(event_type, [])
        return [hid for hid, _ in handlers]

    # ── 生命周期 ──

    async def start(self) -> None:
        """启动事件总线"""
        self._running = True
        logger.info("事件总线已启动")

    async def stop(self) -> None:
        """停止事件总线"""
        self._running = False
        self._handlers.clear()
        self._react_handlers.clear()
        self._event_history.clear()
        logger.info("事件总线已停止")


# ══════════════════════════════════════════════════════════════════════════════
# 便捷函数
# ══════════════════════════════════════════════════════════════════════════════

async def publish_event(
    event_bus: EventBus,
    event_type: EventType,
    data: Any = None,
    source: str = "",
) -> None:
    """发布基础设施事件（保留兼容性）"""
    await event_bus.publish(event_type, data)


# ══════════════════════════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════════════════════════

_event_bus_instance: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """获取全局事件总线实例"""
    global _event_bus_instance
    if _event_bus_instance is None:
        _event_bus_instance = EventBus()
    return _event_bus_instance


def reset_event_bus() -> None:
    """重置全局事件总线实例"""
    global _event_bus_instance
    _event_bus_instance = None
