"""
StatsHandler - 用量统计接口（MCP 调用次数 / Token 消耗 / 图片生成）

路由（注册见 grpc_server._register_routes）：
    GET /api/stats/daily?date=YYYY-MM-DD     某天总览（MCP + Token + 图片）
    GET /api/stats/mcp?date=&server=&tool=   某天 MCP 调用明细
    GET /api/stats/tokens?date=              某天 Token 用量
    GET /api/stats/trend?days=30             最近 N 天趋势
    GET /api/stats/overview                  今日看板（含昨日环比 + 近 7 日趋势）

权限口径（与 /api/v2/usage/stats 保持一致）：
    - admin：可查全部用户；可用 ?user_id= 指定单个用户
    - 普通用户：强制只看自己（忽略 ?user_id=）
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


class StatsHandler:
    """用量统计处理器（无状态，均为 staticmethod）"""

    # ──────────────────────────────────────────────────────
    # 内部：权限与参数解析
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _current_user(request) -> str:
        return request.headers.get("x-user-id", "default") or "default"

    @staticmethod
    def _resolve_scope(request) -> Tuple[Optional[str], str, bool]:
        """解析统计范围。

        Returns:
            (user_filter, current_user, is_admin)
            user_filter=None 表示统计全部用户（仅 admin 可能拿到 None）。
        """
        current_user = StatsHandler._current_user(request)
        try:
            from src.gateway.permission import PermissionService
            is_admin = PermissionService().is_admin(current_user)
        except Exception:
            is_admin = False

        requested = (request.query_params.get("user_id") or "").strip()
        if is_admin:
            return (requested or None), current_user, True
        return current_user, current_user, False

    @staticmethod
    def _query_day(request) -> Optional[str]:
        value = (request.query_params.get("date") or "").strip()
        return value or None

    @staticmethod
    def _identity_hint(current_user: str, is_admin: bool, summary: Dict[str, Any]) -> Optional[str]:
        """非管理员查到空数据时返回身份提示（只说身份口径，不泄露他人数据量）。

        最常见的困惑：用 admin 身份产生的对话，却用默认身份去查
        （未传 X-User-ID → 落 guest 角色 → data_scope=own），
        数据被"仅看自己"的规则过滤成 0，看起来像"统计坏了"。
        """
        if is_admin:
            return None
        if (summary.get("totals") or {}).get("events"):
            return None
        return (
            f"当前身份 '{current_user}' 为非管理员，仅能查看自己名下的数据；"
            f"{summary.get('date')} 没有属于该身份的记录。"
            "若该日数据由其他用户产生，请改用管理员身份查询"
            "（请求头 X-User-ID: admin；管理员还可用 ?user_id=xxx 指定用户）。"
        )

    # ──────────────────────────────────────────────────────
    # 接口
    # ──────────────────────────────────────────────────────

    @staticmethod
    async def daily(request) -> Dict[str, Any]:
        """某天总览：MCP 调用次数 + Token 消耗 + 图片生成（默认今天）。"""
        from src.monitoring.daily_stats import summarize_day

        user_filter, current_user, is_admin = StatsHandler._resolve_scope(request)
        summary = summarize_day(StatsHandler._query_day(request), user_id=user_filter)
        return {
            "success": True,
            "scope": {"current_user": current_user, "is_admin": is_admin},
            "hint": StatsHandler._identity_hint(current_user, is_admin, summary),
            **summary,
        }

    @staticmethod
    async def mcp(request) -> Dict[str, Any]:
        """某天 MCP 调用明细（总数/成功/失败/平均耗时 + 按 server / tool 分组）。

        可选 server / tool 过滤参数用于前端下钻。
        """
        from src.monitoring.daily_stats import summarize_day

        user_filter, current_user, is_admin = StatsHandler._resolve_scope(request)
        summary = summarize_day(StatsHandler._query_day(request), user_id=user_filter)
        mcp_stats = summary["mcp"]

        server = (request.query_params.get("server") or "").strip()
        tool = (request.query_params.get("tool") or "").strip()
        if server:
            mcp_stats = dict(mcp_stats)
            mcp_stats["by_tool"] = [t for t in mcp_stats["by_tool"] if t["server_name"] == server]
        if tool:
            mcp_stats = dict(mcp_stats)
            mcp_stats["by_tool"] = [t for t in mcp_stats["by_tool"] if t["tool_name"] == tool]

        return {
            "success": True,
            "date": summary["date"],
            "user_id": summary["user_id"],
            "scope": {"current_user": current_user, "is_admin": is_admin},
            "filter": {"server": server or None, "tool": tool or None},
            "mcp": mcp_stats,
        }

    @staticmethod
    async def tokens(request) -> Dict[str, Any]:
        """某天 Token 消耗（prompt / completion / total + 按模型、按来源）。"""
        from src.monitoring.daily_stats import summarize_day

        user_filter, current_user, is_admin = StatsHandler._resolve_scope(request)
        summary = summarize_day(StatsHandler._query_day(request), user_id=user_filter)
        return {
            "success": True,
            "date": summary["date"],
            "user_id": summary["user_id"],
            "scope": {"current_user": current_user, "is_admin": is_admin},
            "token_source": summary["token_source"],
            "tokens": summary["tokens"],
            "hint": StatsHandler._identity_hint(current_user, is_admin, summary),
        }

    @staticmethod
    async def trend(request) -> Dict[str, Any]:
        """最近 N 天用量趋势（默认 30 天，?end=YYYY-MM-DD 可指定终点）。"""
        from src.monitoring.daily_stats import trend as trend_stats

        user_filter, current_user, is_admin = StatsHandler._resolve_scope(request)
        try:
            days = int(request.query_params.get("days") or 30)
        except (TypeError, ValueError):
            days = 30
        data = trend_stats(days=days, end=StatsHandler._query_day(request), user_id=user_filter)
        return {
            "success": True,
            "scope": {"current_user": current_user, "is_admin": is_admin},
            **data,
        }

    @staticmethod
    async def overview(request) -> Dict[str, Any]:
        """今日看板：今日汇总 + 昨日环比 + 近 7 日趋势。"""
        from src.monitoring.daily_stats import summarize_day, trend as trend_stats
        from datetime import date, timedelta

        user_filter, current_user, is_admin = StatsHandler._resolve_scope(request)
        today = summarize_day(None, user_id=user_filter)
        yesterday = summarize_day(date.today() - timedelta(days=1), user_id=user_filter)

        def _delta(cur: int, prev: int) -> Optional[float]:
            if not prev:
                return None
            return round((cur - prev) / prev * 100, 1)

        return {
            "success": True,
            "scope": {"current_user": current_user, "is_admin": is_admin},
            "today": today,
            "yesterday": yesterday,
            "vs_yesterday": {
                "mcp_calls_percent": _delta(today["mcp"]["calls"], yesterday["mcp"]["calls"]),
                "total_tokens_percent": _delta(
                    today["tokens"]["total_tokens"], yesterday["tokens"]["total_tokens"]
                ),
                "images_percent": _delta(today["images"]["images"], yesterday["images"]["images"]),
            },
            "recent_7d": trend_stats(days=7, user_id=user_filter)["days"],
        }