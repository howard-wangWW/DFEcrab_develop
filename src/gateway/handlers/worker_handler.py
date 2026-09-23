"""Worker / 系统状态处理器

从 `GatewayV2GRPC` 抽出：

    GET /api/v2/workers   通过 ZK 发现的 Worker Agent 列表（按 agent_id 分组）
    GET /api/services     服务注册健康状态（当前为空占位，保持原契约）
    GET /api/invariants   系统不变量检查

ZK 服务发现实例由网关启动时经 `lifecycle.zookeeper.set_discovery()` 注入，
因此本模块无需持有网关实例（路由可声明为 mod: 引用）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from src.gateway.lifecycle.zookeeper import get_discovery, zk_instance_agent_id

logger = logging.getLogger(__name__)


def pick_latest_instances(instances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一 agent_id 有多个 ZK 实例时，只保留 registered_at 最新的一个。

    历史遗留进程（如 default_localhost.localdomain_* 之类的孤儿）与当前批次进程
    会同时注册，若不去重可能返回死进程地址。
    """
    latest: Dict[str, Dict[str, Any]] = {}
    for inst in instances or []:
        if not isinstance(inst, dict):
            continue
        key = zk_instance_agent_id(inst) or inst.get("service_id") or ""
        prev = latest.get(key)
        if prev is None:
            latest[key] = inst
            continue
        cur_ts = str(inst.get("registered_at") or inst.get("timestamp") or "")
        prev_ts = str(prev.get("registered_at") or prev.get("timestamp") or "")
        if cur_ts >= prev_ts:
            latest[key] = inst
    return list(latest.values())


class WorkerHandler:
    """Worker / 服务状态接口（HTTP 适配层）"""

    @staticmethod
    async def list_workers(request: Any) -> Dict[str, Any]:
        """列出所有通过 Zookeeper 注册的 Agent（附带 grouped 分组便于前端按智能体渲染）

        ★ 合并深圳现场修复：worker / manager / default 三类注册合并发现，
          并按 agent_id 去重只保留最新实例，避免返回死进程地址。
        """
        try:
            discovery = get_discovery()
            if not discovery:
                return {"success": False, "error": "Zookeeper 服务发现未初始化"}

            instances: List[Dict[str, Any]] = []
            for service_name in ("worker_agent", "manager_agent", "default_agent"):
                try:
                    instances.extend(discovery.discover_service(service_name) or [])
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[WorkerHandler] 发现 {service_name} 失败: {e}")
            instances = pick_latest_instances(instances)

            workers = []
            for inst in instances:
                workers.append({
                    "agent_id": zk_instance_agent_id(inst),
                    "host": inst["host"],
                    "port": inst["port"],
                    "version": inst.get("metadata", {}).get("version", ""),
                    "service_id": inst.get("service_id", ""),
                })

            grouped: Dict[str, list] = {}
            for w in workers:
                grouped.setdefault(w["agent_id"], []).append(w)

            return {
                "success": True,
                "total": len(workers),
                "unique_agents": len(grouped),
                "workers": workers,
                "grouped": grouped,
            }
        except Exception as e:
            logger.error(f"[WorkerHandler] 列出 Worker 失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def list_services(request: Any) -> Dict[str, Any]:
        """列出服务（保持原契约：返回 services 数组）"""
        try:
            return {"services": []}
        except Exception as e:
            logger.error(f"[WorkerHandler] 列出服务失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def check_invariants(request: Any) -> Dict[str, Any]:
        """系统不变量检查"""
        try:
            from src.monitoring.invariants import check_all_invariants
            return {"invariants": check_all_invariants()}
        except ImportError:
            return {"invariants": "检查模块未安装"}
        except Exception as e:
            logger.error(f"[WorkerHandler] 不变量检查失败: {e}")
            return {"success": False, "error": str(e)}
