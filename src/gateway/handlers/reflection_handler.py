"""自反思处理器（Reflection Handler）

从 `GatewayV2GRPC` 抽出。原实现里 `list/get/implement` 各自重复了一段
"遍历 agents 反思目录、按 reflection_id 匹配文件"的扫描逻辑，
现统一收敛为 `find_reflection_report()`（一份实现、三处复用）。

路由：
    GET  /api/reflections
    GET  /api/reflections/{reflection_id}
    POST /api/reflections/{reflection_id}/implement
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _reflection_dir(reflector) -> Optional[Path]:
    """取反思报告根目录（reflector 未提供时返回 None）。"""
    try:
        d = getattr(reflector, "_reflection_dir", None)
        return Path(d) if d else None
    except Exception:
        return None


def find_reflection_report(reflection_id: str) -> Optional[Dict]:
    """按 reflection_id 在 `<reflection_dir>/*/*.json` 中查找报告，未命中返回 None。

    原实现分散在 `_handle_get_reflection` / `_handle_implement_improvements` 两处，
    逻辑完全一致（仅后续处理不同），此处收敛为唯一实现。
    """
    try:
        from src.reflection import get_self_reflector

        reflection_dir = _reflection_dir(get_self_reflector())
        if not reflection_dir or not reflection_dir.exists():
            return None
        for agent_dir in reflection_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            for f in agent_dir.glob("*.json"):
                if reflection_id in f.stem:
                    with open(f, "r", encoding="utf-8") as fh:
                        return json.load(fh)
    except Exception as e:
        logger.error(f"[ReflectionHandler] 读取反思报告失败 {reflection_id}: {e}")
    return None


class ReflectionHandler:
    """自反思接口（HTTP 适配层）"""

    @staticmethod
    async def list_reflections(request: Any) -> Dict[str, Any]:
        """列出反思历史（?limit=，默认 10）"""
        try:
            from src.reflection import get_self_reflector

            reflector = get_self_reflector()
            params = getattr(request, "query_params", {}) or {}
            limit = int(params.get("limit", 10))
            history = reflector.get_reflection_history(limit=limit)

            return {
                "success": True,
                "count": len(history),
                "reflections": [
                    {
                        "reflection_id": r.reflection_id,
                        "agent_id": r.agent_id,
                        "timestamp": r.timestamp.isoformat() if hasattr(r.timestamp, "isoformat") else str(r.timestamp),
                        "satisfaction_score": r.satisfaction.score if hasattr(r, "satisfaction") else 0,
                        "summary": r.summary,
                    }
                    for r in history
                ],
            }
        except Exception as e:
            logger.error(f"[ReflectionHandler] 列出反思失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_reflection(request: Any, reflection_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """获取反思报告详情"""
        try:
            reflection_id = reflection_id or kwargs.get("reflection_id") \
                or request.path_params.get("reflection_id")
            report = find_reflection_report(reflection_id)
            if report is None:
                return {"success": False, "error": f"反思报告不存在：{reflection_id}"}
            return {"success": True, "reflection": report}
        except Exception as e:
            logger.error(f"[ReflectionHandler] 获取反思失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def implement_improvements(request: Any, reflection_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """执行改进计划（当前为占位实现，仅回执改进行动数量）"""
        try:
            reflection_id = reflection_id or kwargs.get("reflection_id") \
                or request.path_params.get("reflection_id")
            report = find_reflection_report(reflection_id)
            if report is None:
                return {"success": False, "error": f"反思报告不存在：{reflection_id}"}

            actions = report.get("improvement_actions", [])
            if actions:
                return {
                    "success": True,
                    "message": f"改进计划已提交：{len(actions)} 项行动",
                    "actions_count": len(actions),
                }
            return {"success": True, "message": "该反思报告无需执行的改进行动", "actions_count": 0}
        except Exception as e:
            logger.error(f"[ReflectionHandler] 执行改进计划失败: {e}")
            return {"success": False, "error": str(e)}
