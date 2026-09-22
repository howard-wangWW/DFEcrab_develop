"""网关生命周期 / 基础设施域

    zookeeper.py  服务发现（Manager/Worker 寻址、实例 agent_id 解析、直连调用）

约定：不得 import `src.gateway.grpc_server`（依赖单向）。
"""

from src.gateway.lifecycle.zookeeper import (  # noqa: F401
    call_worker_grpc,
    pick_latest_instances,
    discover_worker_service,
    get_discovery,
    set_discovery,
    zk_instance_agent_id,
)

__all__ = [
    "set_discovery",
    "get_discovery",
    "zk_instance_agent_id",
    "discover_worker_service",
    "call_worker_grpc",
    "pick_latest_instances",
]
