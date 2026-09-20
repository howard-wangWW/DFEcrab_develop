"""
网关层 - gateway 域

管理 HTTP/WebSocket/gRPC 通信、事件总线、API 路由。
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.gateway.event_bus import EventBus
    from src.gateway.service_locator import ServiceLocator

__all__ = [
    'EventBus', 'get_event_bus',
    'ServiceLocator', 'get_service_locator',
]


def __getattr__(name: str):
    if name in {"EventBus", "get_event_bus"}:
        from src.gateway.event_bus import EventBus, get_event_bus

        return {"EventBus": EventBus, "get_event_bus": get_event_bus}[name]
    if name in {"ServiceLocator", "get_service_locator"}:
        from src.gateway.service_locator import ServiceLocator, get_service_locator

        return {"ServiceLocator": ServiceLocator, "get_service_locator": get_service_locator}[name]
    raise AttributeError(f"module 'src.gateway' has no attribute {name!r}")
