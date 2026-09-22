"""用量统计处理器（Usage Handler）

从 `grpc_server.GatewayV2GRPC` 抽出，返回结构保持**完全不变**（前端零改动）：

    GET /api/v2/sessions/{session_id}/usage   单会话上下文占用（累计 + 每轮明细 + 按模型）
    GET /api/v2/usage/stats                   跨会话 token 用量（窗口 / 环比 / 按模型 / 逐日）

两接口均为纯只读聚合：
- 单会话：读已落库 `Message.tokens / model / metadata.context_length`，无 LLM 调用；
- 跨会话：走 `src.utils.usage_aggregator`，不触发任何模型请求。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.gateway.identity import resolve_user_id
from src.gateway.llm_config import gateway_context_length
from src.utils.context_usage import DEFAULT_CONTEXT_LENGTH

logger = logging.getLogger(__name__)


class UsageHandler:
    """用量统计接口（HTTP 适配层）"""

    @staticmethod
    async def session_usage(request: Any, session_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """GET /api/v2/sessions/{session_id}/usage — 单会话上下文占用统计。

        数据来自已落库的 Message.tokens / model / metadata.context_length，纯只读聚合，无 LLM 调用。

        查询参数：
          group_by=model  额外返回按模型分组的累计用量（多模型会话成本，对齐 CodeBuddy /cost）
        """
        from src.gateway.session_handler import SessionService

        session_id = session_id or kwargs.get("session_id") or request.path_params.get("session_id")
        params = getattr(request, "query_params", {}) or {}
        group_by = str(params.get("group_by", ""))

        res = SessionService.get_session_messages(
            session_id=session_id,
            current_user=resolve_user_id(request),
            limit=100,
        )
        if not res.get("success"):
            return res

        msgs = res.get("messages", [])
        total_prompt = total_completion = total_total = 0
        rounds = []
        # 按模型聚合 {model: {prompt, completion, total, context_length, last_prompt}}
        by_model: Dict[str, Dict] = {}
        for m in msgs:
            tk = m.get("tokens") or {}
            p = int(tk.get("prompt") or 0)
            c = int(tk.get("completion") or 0)
            t = int(tk.get("total") or 0)
            total_prompt += p
            total_completion += c
            total_total += t
            if m.get("role") == "assistant" and t > 0:
                rounds.append({
                    "message_id": m.get("id"),
                    "timestamp": m.get("timestamp"),
                    "prompt": p, "completion": c, "total": t,
                    "model": m.get("model"),
                })
                model = m.get("model") or "unknown"
                bm = by_model.setdefault(
                    model,
                    {"prompt": 0, "completion": 0, "total": 0, "context_length": None, "last_prompt": 0},
                )
                bm["prompt"] += p
                bm["completion"] += c
                bm["total"] += t
                bm["last_prompt"] = p
                if bm["context_length"] is None:
                    bm["context_length"] = (m.get("metadata") or {}).get("context_length")

        # 当前模型上下文窗口
        try:
            context_length = int(gateway_context_length() or DEFAULT_CONTEXT_LENGTH)
        except Exception:
            context_length = DEFAULT_CONTEXT_LENGTH

        last_prompt = rounds[-1]["prompt"] if rounds else 0
        last_used_percent = round(last_prompt / context_length * 100, 1) if context_length and last_prompt else 0.0
        peak = max((r["prompt"] for r in rounds), default=0)
        peak_used_percent = round(peak / context_length * 100, 1) if context_length and peak else 0.0
        for r in rounds:
            r["used_percent"] = round(r["prompt"] / context_length * 100, 1) if context_length else 0.0

        result = {
            "success": True,
            "session_id": session_id,
            "summary": {
                "turns": len(rounds),
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_total,
                "context_length": context_length,
                "last_prompt_tokens": last_prompt,
                "last_used_percent": last_used_percent,
                "peak_used_percent": peak_used_percent,
            },
            "rounds": rounds,
        }
        # 按模型聚合（多模型对话成本统计）
        if group_by == "model":
            by_model_out: Dict[str, Dict] = {}
            for model, bm in by_model.items():
                clen = int(bm["context_length"] or context_length or DEFAULT_CONTEXT_LENGTH)
                last_pct = round(bm["last_prompt"] / clen * 100, 1) if clen and bm["last_prompt"] else 0.0
                by_model_out[model] = {
                    "total_prompt_tokens": bm["prompt"],
                    "total_completion_tokens": bm["completion"],
                    "total_tokens": bm["total"],
                    "context_length": clen,
                    "last_used_percent": last_pct,
                }
            result["by_model"] = by_model_out
        return result

    @staticmethod
    async def usage_stats(request: Any) -> Dict[str, Any]:
        """GET /api/v2/usage/stats — 跨会话 token 用量统计（纯 token 维度，本地模型无费用）。

        查询参数：period=day|week|month、start/end=YYYY-MM-DD（同时传时优先于 period）
        权限：admin 看全部用户；普通用户只看自己的用量（与历史/记忆接口一致）。
        """
        from src.utils.usage_aggregator import resolve_period, aggregate_usage
        from src.gateway.permission import PermissionService
        from datetime import timedelta

        params = getattr(request, "query_params", {}) or {}
        period = str(params.get("period", "month"))
        start, end = resolve_period(period, params.get("start"), params.get("end"))

        # 权限隔离：admin 看全部；普通 user 只统计自己的会话
        current_user = resolve_user_id(request)
        user_filter = None
        try:
            if not PermissionService().is_admin(current_user):
                user_filter = current_user
        except Exception:
            user_filter = current_user

        current = aggregate_usage(start, end, user_id=user_filter)
        # 较上期：同等长度窗口向前推
        span = (end - start).days + 1
        prev = aggregate_usage(start - timedelta(days=span), start - timedelta(days=1), user_id=user_filter)
        vs_last = None
        if prev["totals"]["total_tokens"] > 0:
            vs_last = round(
                (current["totals"]["total_tokens"] - prev["totals"]["total_tokens"])
                / prev["totals"]["total_tokens"] * 100, 1
            )
        return {
            "success": True,
            "period": period,
            "user_id": user_filter or "*",  # 统计范围（* = 全部用户 / admin）
            "range": {"start": start.isoformat(), "end": end.isoformat()},
            "totals": current["totals"],
            "comparison": {"vs_last_period_percent": vs_last},
            "by_model": current["by_model"],
            "by_day": current["by_day"],
        }
