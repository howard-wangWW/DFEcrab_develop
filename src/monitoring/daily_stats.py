"""
daily_stats.py - 天级用量聚合（MCP 调用次数 / Token 消耗 / 图片生成）

数据源与优先级
--------------
1. **事件流**（主）：``data/usage/YYYY-MM-DD.jsonl``，由 ``usage_store`` 写入。
   精确（区分 success/failed、按 server/tool/model 细分），且读取成本只与当天数据量相关。
2. **会话兜底**（辅）：当天事件流里没有任何 ``llm_call`` 时，回落到
   ``usage_aggregator`` 扫 ``data/sessions/*_messages.json``。
   目的是让"埋点上线之前"的历史数据依旧可以统计到 token；
   一旦当天有事件流数据，就以事件流为准，避免重复计算。

性能
----
按天做 mtime 校验的内存缓存，事件文件未变化时直接复用解析结果，
避免同一请求内多次读盘（对比原 ``/api/v2/usage/stats`` 每次全量扫描两遍）。
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.monitoring.usage_store import day_str, read_events, usage_dir

logger = logging.getLogger(__name__)

# 明细返回条数上限（避免接口体过大）
_MAX_TOOL_GROUPS = 20
_MAX_ERRORS = 20

_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────────────────────


def _to_date(day: Any) -> Optional[date]:
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, date):
        return day
    if isinstance(day, str):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(day, fmt).date()
            except ValueError:
                continue
    return None


def _read_day(day: str) -> List[Dict[str, Any]]:
    """按天读取事件（带缓存），事件文件变化时自动失效。

    缓存键用 (mtime, size)：追加写入时文件大小必变，
    可避免低精度文件系统上"同秒追加但 mtime 未变"导致读到旧缓存。
    """
    path = usage_dir() / f"{day}.jsonl"
    try:
        st = path.stat() if path.exists() else None
        stamp: Tuple[float, int] = (st.st_mtime, st.st_size) if st else (0.0, 0)
    except OSError:
        stamp = (0.0, 0)

    with _cache_lock:
        hit = _cache.get(day)
        if hit is not None and hit[0] == stamp:
            return hit[1]

    events = read_events(day)

    with _cache_lock:
        _cache[day] = (stamp, events)
    return events


def _match_user(event: Dict[str, Any], user_id: Optional[str]) -> bool:
    """用户过滤：user_id=None 表示不过滤（admin 全量）。"""
    if not user_id:
        return True
    return str(event.get("user_id") or "") == user_id


def _avg(total: int, count: int) -> int:
    return int(total / count) if count else 0


# ──────────────────────────────────────────────────────────────
# 各维度聚合
# ──────────────────────────────────────────────────────────────


def _summarize_mcp(calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_server: Dict[str, Dict[str, int]] = {}
    by_tool: Dict[Tuple[str, str], Dict[str, Any]] = {}
    errors: List[Dict[str, Any]] = []
    success = 0
    total_ms = 0

    for e in calls:
        ok = bool(e.get("ok"))
        server = str(e.get("server_name") or "unknown")
        tool = str(e.get("tool_name") or "unknown")
        elapsed = int(e.get("elapsed_ms") or 0)
        success += 1 if ok else 0
        total_ms += elapsed

        srv = by_server.setdefault(server, {"calls": 0, "success": 0, "failed": 0})
        srv["calls"] += 1
        srv["success" if ok else "failed"] += 1

        key = (server, tool)
        item = by_tool.setdefault(
            key,
            {"server_name": server, "tool_name": tool, "calls": 0, "success": 0, "failed": 0, "elapsed_ms": 0},
        )
        item["calls"] += 1
        item["success" if ok else "failed"] += 1
        item["elapsed_ms"] += elapsed

        if not ok and e.get("error"):
            errors.append({
                "ts": e.get("ts", ""),
                "server_name": server,
                "tool_name": tool,
                "error": str(e.get("error"))[:300],
            })

    total = len(calls)
    tool_list = []
    for item in by_tool.values():
        tool_list.append({
            "server_name": item["server_name"],
            "tool_name": item["tool_name"],
            "calls": item["calls"],
            "success": item["success"],
            "failed": item["failed"],
            "avg_elapsed_ms": _avg(item["elapsed_ms"], item["calls"]),
        })
    tool_list.sort(key=lambda x: x["calls"], reverse=True)

    return {
        "calls": total,
        "success": success,
        "failed": total - success,
        "success_rate": round(success / total * 100, 1) if total else 0.0,
        "avg_elapsed_ms": _avg(total_ms, total),
        "by_server": by_server,
        "by_tool": tool_list[:_MAX_TOOL_GROUPS],
        "errors": errors[-_MAX_ERRORS:],
    }


def _summarize_tokens(llm_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    prompt_total = 0
    completion_total = 0
    by_model: Dict[str, Dict[str, int]] = {}
    by_source: Dict[str, Dict[str, int]] = {}

    for e in llm_calls:
        prompt = int(e.get("prompt_tokens") or 0)
        completion = int(e.get("completion_tokens") or 0)
        total = int(e.get("total_tokens") or (prompt + completion))
        prompt_total += prompt
        completion_total += completion

        model = str(e.get("model") or "unknown")
        bm = by_model.setdefault(
            model,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "llm_calls": 0},
        )
        bm["prompt_tokens"] += prompt
        bm["completion_tokens"] += completion
        bm["total_tokens"] += total
        bm["llm_calls"] += 1

        source = str(e.get("source") or "unknown")
        bs = by_source.setdefault(source, {"total_tokens": 0, "llm_calls": 0})
        bs["total_tokens"] += total
        bs["llm_calls"] += 1

    calls = len(llm_calls)
    total_tokens = prompt_total + completion_total
    return {
        "prompt_tokens": prompt_total,
        "completion_tokens": completion_total,
        "total_tokens": total_tokens,
        "llm_calls": calls,
        "avg_tokens_per_call": _avg(total_tokens, calls),
        "by_model": by_model,
        "by_source": by_source,
    }


def _summarize_images(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_provider: Dict[str, Dict[str, int]] = {}
    by_size: Dict[str, int] = {}
    success = 0
    gen_count = 0

    for e in events:
        ok = bool(e.get("ok"))
        success += 1 if ok else 0
        n = int(e.get("n") or 1)
        gen_count += n if ok else 0

        provider = str(e.get("provider") or "unknown")
        bp = by_provider.setdefault(provider, {"requests": 0, "success": 0, "failed": 0})
        bp["requests"] += 1
        bp["success" if ok else "failed"] += 1

        size = str(e.get("size") or "default")
        by_size[size] = by_size.get(size, 0) + (n if ok else 0)

    total = len(events)
    return {
        "requests": total,
        "images": gen_count,
        "success": success,
        "failed": total - success,
        "by_provider": by_provider,
        "by_size": by_size,
    }


def _legacy_tokens(day: str, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """会话兜底：埋点上线前的历史数据仍可通过扫会话统计到 token。"""
    d = _to_date(day)
    if d is None:
        return None
    try:
        from src.utils.usage_aggregator import aggregate_usage
        res = aggregate_usage(d, d, user_id=user_id or None)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[daily_stats] 会话兜底统计失败 {day}: {exc}")
        return None

    totals = res.get("totals") or {}
    total_tokens = int(totals.get("total_tokens") or 0)
    if total_tokens <= 0:
        return None

    by_model = {}
    for model, rec in (res.get("by_model") or {}).items():
        by_model[model] = {
            "prompt_tokens": int(rec.get("prompt_tokens") or 0),
            "completion_tokens": int(rec.get("completion_tokens") or 0),
            "total_tokens": int(rec.get("total_tokens") or 0),
            "llm_calls": int(rec.get("api_calls") or 0),
        }

    calls = int(totals.get("api_calls") or 0)
    return {
        "prompt_tokens": int(totals.get("prompt_tokens") or 0),
        "completion_tokens": int(totals.get("completion_tokens") or 0),
        "total_tokens": total_tokens,
        "llm_calls": calls,
        "avg_tokens_per_call": _avg(total_tokens, calls),
        "by_model": by_model,
        "by_source": {},
    }


def _summarize_activity(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """活跃度画像：事件总数、活跃会话/用户/智能体数、首末活动时间、按小时分布。

    回答"这一天整体上都发生了什么"，二十四小时全部补齐（便于前端画柱状图不断档）。
    """
    sessions: set = set()
    users: set = set()
    agents: set = set()
    by_hour: Dict[str, int] = {}
    first_ts = ""
    last_ts = ""

    for e in events:
        sid = str(e.get("session_id") or "")
        uid = str(e.get("user_id") or "")
        aid = str(e.get("agent_id") or "")
        if sid:
            sessions.add(sid)
        if uid:
            users.add(uid)
        if aid:
            agents.add(aid)

        ts = str(e.get("ts") or "")
        hour = ts[11:13] if len(ts) >= 13 else ""
        if hour.isdigit():
            by_hour[hour] = by_hour.get(hour, 0) + 1
        if ts:
            if not first_ts or ts < first_ts:
                first_ts = ts
            if not last_ts or ts > last_ts:
                last_ts = ts

    return {
        "events": len(events),
        "active_sessions": len(sessions),
        "active_users": len(users),
        "active_agents": len(agents),
        "first_event": first_ts,
        "last_event": last_ts,
        "by_hour": {f"{h:02d}": by_hour.get(f"{h:02d}", 0) for h in range(24)},
    }


# ──────────────────────────────────────────────────────────────
# 对外接口
# ──────────────────────────────────────────────────────────────


def summarize_day(day: Any = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    """聚合某一天（默认今天）的用量总览。

    Args:
        day: ``YYYY-MM-DD`` / date / datetime / None(今天)。
        user_id: 用户隔离；None=全部用户（admin）。

    Returns:
        {
            "date": "YYYY-MM-DD",
            "user_id": "*" | uid,
            "token_source": "event_stream" | "legacy_session_scan" | "empty",
            "totals": {...},     # 一眼看板：当天核心汇总数字
            "mcp": {...},        # MCP 调用：次数/成功/失败/耗时 + 按 server / tool
            "tokens": {...},     # Token：prompt/completion/total + 按模型 / 按来源
            "images": {...},     # 图片生成：请求数 / 张数 + 按 provider / size
            "activity": {...},   # 活跃度：会话数 / 用户数 / Agent 数 / 按小时分布
        }
    """
    d = day_str(day)
    events = [e for e in _read_day(d) if _match_user(e, user_id)]

    mcp_calls = [e for e in events if e.get("type") == "mcp_call"]
    llm_calls = [e for e in events if e.get("type") == "llm_call"]
    image_events = [e for e in events if e.get("type") == "image_gen"]

    tokens = _summarize_tokens(llm_calls)
    if llm_calls:
        token_source = "event_stream"
    else:
        # 事件流当天无 token 数据 → 回落扫会话（兼容埋点上线前的历史数据）
        legacy = _legacy_tokens(d, user_id)
        if legacy:
            tokens = legacy
            token_source = "legacy_session_scan"
        else:
            token_source = "empty"

    activity = _summarize_activity(events)
    mcp_summary = _summarize_mcp(mcp_calls)
    images_summary = _summarize_images(image_events)

    return {
        "date": d,
        "user_id": user_id or "*",
        "token_source": token_source,
        "totals": {
            "events": activity["events"],
            "mcp_calls": mcp_summary["calls"],
            "mcp_failed": mcp_summary["failed"],
            "llm_calls": tokens.get("llm_calls", 0),
            "prompt_tokens": tokens.get("prompt_tokens", 0),
            "completion_tokens": tokens.get("completion_tokens", 0),
            "total_tokens": tokens.get("total_tokens", 0),
            "images": images_summary["images"],
            "image_requests": images_summary["requests"],
            "active_sessions": activity["active_sessions"],
            "active_users": activity["active_users"],
        },
        "mcp": mcp_summary,
        "tokens": tokens,
        "images": images_summary,
        "activity": activity,
    }


def trend(days: int = 30, end: Any = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    """返回最近 N 天的用量趋势（默认以今天为终点）。"""
    try:
        days = max(1, min(int(days or 30), 365))
    except (TypeError, ValueError):
        days = 30

    end_date = _to_date(end) or date.today()
    start_date = end_date - timedelta(days=days - 1)

    items: List[Dict[str, Any]] = []
    totals = {
        "mcp_calls": 0,
        "mcp_failed": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
        "images": 0,
    }

    cur = start_date
    while cur <= end_date:
        summary = summarize_day(cur, user_id=user_id)
        mcp = summary["mcp"]
        tk = summary["tokens"]
        img = summary["images"]
        items.append({
            "date": summary["date"],
            "mcp_calls": mcp["calls"],
            "mcp_failed": mcp["failed"],
            "prompt_tokens": tk["prompt_tokens"],
            "completion_tokens": tk["completion_tokens"],
            "total_tokens": tk["total_tokens"],
            "llm_calls": tk["llm_calls"],
            "images": img["images"],
        })
        totals["mcp_calls"] += mcp["calls"]
        totals["mcp_failed"] += mcp["failed"]
        totals["prompt_tokens"] += tk["prompt_tokens"]
        totals["completion_tokens"] += tk["completion_tokens"]
        totals["total_tokens"] += tk["total_tokens"]
        totals["llm_calls"] += tk["llm_calls"]
        totals["images"] += img["images"]
        cur += timedelta(days=1)

    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": days},
        "user_id": user_id or "*",
        "totals": totals,
        "days": items,
    }


def clear_cache() -> None:
    """清空内存缓存（测试 / 配置热更新后调用）。"""
    with _cache_lock:
        _cache.clear()