"""ZooKeeper 服务发现（网关 → Manager/Worker 寻址）

从 `GatewayV2GRPC` 抽出，统一实例解析与直连调用：

    set_discovery / get_discovery      网关启动时注入 ZKServiceDiscovery 实例（模块级注册表）
    zk_instance_agent_id(inst)         从 ZK 实例记录解析 agent_id（全网关唯一实现）
    discover_worker_service(agent_id)  按 agent_id 查找 Worker 实例
    call_worker_grpc(...)              直连 Worker 的 gRPC Execute

说明：`grpc` 与 pb2 模块在该文件里**惰性 import**，保证本模块可被静态分析/单测加载。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: 模块级服务发现注册表（由网关启动时注入）
_discovery: Optional[Any] = None


def set_discovery(discovery: Optional[Any]) -> None:
    """注入 ZK 服务发现实例（网关 initialize 时调用；传 None 表示不可用）。"""
    global _discovery
    _discovery = discovery
    logger.debug(f"[ZK] 服务发现注册表已更新: {'可用' if discovery else '不可用'}")


def get_discovery() -> Optional[Any]:
    """获取当前 ZK 服务发现实例（可能为 None）。"""
    return _discovery


def zk_instance_agent_id(inst: Dict[str, Any]) -> str:
    """从 ZK 实例记录解析 agent_id（网关所有解析点共用，杜绝散落式 split）。

    命名约定：worker/manager 均以 `metadata.agent_id` 为准；
    旧 `default_agent` 服务节点自部署以来恒代表 dfecrab（default→dfecrab 更名），
    兼容期无 metadata 时直接归为 dfecrab，避免再产出 'default' 触发迁移告警刷屏。
    """
    try:
        metadata = inst.get("metadata") or {}
        if metadata.get("agent_id"):
            return str(metadata["agent_id"])
        service_name = str(inst.get("service_name", "") or "")
        sid = str(inst.get("service_id", "") or "")
        if service_name == "default_agent":
            return "dfecrab"  # 兼容旧注册：default_agent 节点 ⇔ dfecrab
        if "_agent_" in sid:
            return sid.split("_agent_")[0]
        parts = sid.split("_")
        return parts[0] if parts else "unknown"
    except Exception:
        return "unknown"


def discover_worker_service(agent_id: str, discovery: Optional[Any] = None) -> Optional[Dict]:
    """通过 ZK 发现指定 Worker 实例；未命中返回 None。"""
    discovery = discovery or get_discovery()
    if not discovery:
        logger.error("❌ ZK 服务发现未初始化")
        return None
    instances = discovery.discover_service("worker_agent")
    if not instances:
        instances = discovery.discover_service("default_agent")
    if not instances:
        logger.warning("⚠️ 未找到任何 Worker 实例")
        return None
    for inst in instances:
        if inst.get("metadata", {}).get("agent_id") == agent_id:
            logger.info(f"🔍 发现 Worker [{agent_id}]: {inst['host']}:{inst['port']}")
            return inst
    logger.error(f"❌ 未找到 Worker: {agent_id}")
    return None


def call_worker_grpc(host: str, port: int, session_id: str, message: str,
                     user_id: str = "") -> Dict:
    """直连 Worker 的 gRPC Execute（阻塞调用，调用方自行决定是否 to_thread）。"""
    import grpc  # 惰性 import：保持模块可静态加载

    from src.gateway.grpc import dfecrab_pb2, dfecrab_pb2_grpc

    channel = None
    try:
        channel = grpc.insecure_channel(
            f"{host}:{port}",
            options=[
                ("grpc.max_send_message_length", 50 * 1024 * 1024),
                ("grpc.max_receive_message_length", 50 * 1024 * 1024),
            ],
        )
        stub = dfecrab_pb2_grpc.AgentServiceStub(channel)
        request = dfecrab_pb2.ExecuteRequest(
            session_id=session_id,
            input_data={"message": message},
            skills=[],
            instruction=message,
            timeout=600,
            user_id=user_id,
        )
        response = stub.Execute(request, timeout=600.0)
        return {
            "success": response.success,
            "agent_id": response.agent_id,
            "result": response.result,
            "error": response.error,
        }
    except Exception as e:
        logger.error(f"❌ Worker gRPC 调用失败: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if channel:
            try:
                channel.close()
            except Exception:
                pass


def pick_latest_instances(instances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一 agent_id 有多个 ZK 实例时，只保留 registered_at 最新的一个。

    历史遗留进程（如 default_localhost.localdomain_* 之类的孤儿）与当前批次进程
    会同时注册，若不去重可能返回死进程地址。
    """
    latest: Dict[str, Dict[str, Any]] = {}
    for inst in instances:
        metadata = inst.get("metadata", {})
        agent_id = (metadata.get("agent_id") if metadata else None) or inst.get("service_id", "").split("_")[0]
        cur = latest.get(agent_id)
        if not cur or inst.get("registered_at", 0) > cur.get("registered_at", 0):
            latest[agent_id] = inst
    return list(latest.values())
