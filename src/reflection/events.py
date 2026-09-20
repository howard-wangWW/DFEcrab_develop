"""
反思域事件模型与索引。
"""

import logging
import inspect
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class Event:
    def __init__(self, event_type: str, data: Any = None, source: str = None):
        self.event_type = event_type
        self.data = data
        self.source = source
        self.timestamp = time.time()
        self.event_id = str(uuid.uuid4())


class EventBus:
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
        self._middlewares: List[Callable] = []
        self._running = False

    def subscribe(self, event_type: str, handler: Callable) -> str:
        self._handlers.setdefault(event_type, [])
        handler_id = str(uuid.uuid4())
        self._handlers[event_type].append((handler_id, handler))
        return handler_id

    def unsubscribe(self, handler_id: str) -> bool:
        for handlers in self._handlers.values():
            for index, (hid, _) in enumerate(handlers):
                if hid == handler_id:
                    del handlers[index]
                    return True
        return False

    def add_middleware(self, middleware: Callable):
        self._middlewares.append(middleware)

    async def publish(self, event_type: str, data: Any = None, source: str = None) -> Event:
        event = Event(event_type, data, source)
        for handlers in self._handlers.values():
            for _, handler in handlers:
                try:
                    if inspect.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        result = handler(event)
                        if inspect.isawaitable(result):
                            await result
                except Exception as exc:
                    logger.error("事件处理失败 [%s]: %s", event_type, exc)
        return event

    async def start(self):
        self._running = True

    async def stop(self):
        self._running = False
        self._handlers.clear()
        self._middlewares.clear()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "event_types": list(self._handlers.keys()),
            "total_handlers": sum(len(handlers) for handlers in self._handlers.values()),
            "middleware_count": len(self._middlewares),
        }


class EventsIndex:
    pass


class EventsHandler:
    @staticmethod
    async def search(req):
        return {"results": []}

    @staticmethod
    async def recent(req):
        return {"results": []}

    @staticmethod
    async def stats(req):
        return {"stats": {}}

    @staticmethod
    async def add(req):
        return {"success": True}


_events_index_instance = EventsIndex()
_event_bus_instance: Optional[EventBus] = None


def get_events_index() -> EventsIndex:
    return _events_index_instance


def get_event_bus() -> EventBus:
    global _event_bus_instance
    if _event_bus_instance is None:
        _event_bus_instance = EventBus()
    return _event_bus_instance


def reset_event_bus() -> None:
    global _event_bus_instance
    _event_bus_instance = None
