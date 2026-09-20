"""
usage_aggregator.py - 跨会话 token 用量聚合（纯 token 维度，本地模型无费用）

供 /api/v2/usage/stats 使用：从所有会话消息落库的 tokens 聚合：
- 时间窗口（今日 / 本周 / 本月 / 自定义）
- 按模型拆分（by_model）
- 每日趋势（by_day，供热力图 / 柱状图）
- 较上期对比

数据源：data/sessions/*_messages.json 中 assistant 消息的 tokens + model + timestamp。
纯只读聚合，无 LLM 调用。
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SESSION_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sessions"


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_msg_date(ts: Optional[str]) -> Optional[date]:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).date()
        except ValueError:
            continue
    return None


def resolve_period(period: str = "month", start: Optional[str] = None, end: Optional[str] = None) -> Tuple[date, date]:
    """把 period / start / end 解析为 (start_date, end_date)。"""
    today = date.today()
    if start and end:
        s, e = _parse_date(start), _parse_date(end)
        if s and e:
            return (s, e)
    if period == "day":
        return today, today
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    # month（默认）
    return today.replace(day=1), today


def _session_user_id(session_dir: Path, session_id: str) -> str:
    """读取会话元数据文件 {session_id}.json 中的 user_id。"""
    meta = session_dir / f"{session_id}.json"
    try:
        d = json.loads(meta.read_text(encoding="utf-8"))
        return str(d.get("user_id") or "")
    except Exception:
        return ""


def _iter_messages(session_dir: Path):
    """遍历所有会话消息文件，产出 (user_id, 消息 dict)。"""
    if not session_dir.exists():
        return
    for f in sorted(session_dir.glob("*_messages.json")):
        session_id = f.name[: -len("_messages.json")]
        uid = _session_user_id(session_dir, session_id)
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            msgs = data.get("messages", data) if isinstance(data, dict) else data
            if isinstance(msgs, list):
                for m in msgs:
                    if isinstance(m, dict):
                        yield uid, m
        except Exception as e:
            logger.debug(f"读取消息文件失败 {f}: {e}")


def aggregate_usage(start: date, end: date, user_id: Optional[str] = None,
                    session_dir: Optional[Path] = None) -> Dict[str, Any]:
    """聚合 [start, end] 窗口内的 token 用量。

    Args:
        start / end: 时间窗口。
        user_id: 用户隔离。None=统计全部用户（admin）；指定则只统计该用户的会话（普通用户）。
        session_dir: 会话存储目录（测试用）。

    Returns:
        {
            "totals": {"prompt_tokens", "completion_tokens", "total_tokens", "api_calls"},
            "by_model": {model: {"prompt_tokens", "completion_tokens", "total_tokens", "api_calls"}},
            "by_day": [{date, prompt_tokens, completion_tokens, total_tokens, api_calls}, ...],
        }
    """
    dirp = session_dir or _SESSION_DIR
    day_index: Dict[str, Dict] = {}
    model_index: Dict[str, Dict] = {}
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "api_calls": 0}

    for _uid, m in _iter_messages(dirp):
        if user_id and _uid != user_id:
            continue
        if m.get("role") != "assistant":
            continue
        tk = m.get("tokens") or {}
        prompt = int(tk.get("prompt") or 0)
        completion = int(tk.get("completion") or 0)
        total = int(tk.get("total") or 0)
        if total <= 0:
            continue
        d = _parse_msg_date(m.get("timestamp"))
        if not d or d < start or d > end:
            continue

        totals["prompt_tokens"] += prompt
        totals["completion_tokens"] += completion
        totals["total_tokens"] += total
        totals["api_calls"] += 1

        model = m.get("model") or "unknown"
        bm = model_index.setdefault(model, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "api_calls": 0})
        bm["prompt_tokens"] += prompt
        bm["completion_tokens"] += completion
        bm["total_tokens"] += total
        bm["api_calls"] += 1

        key = d.isoformat()
        bd = day_index.setdefault(key, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "api_calls": 0})
        bd["prompt_tokens"] += prompt
        bd["completion_tokens"] += completion
        bd["total_tokens"] += total
        bd["api_calls"] += 1

    # 窗口内每天补 0（趋势图连续）
    by_day = []
    cur = start
    while cur <= end:
        rec = day_index.get(cur.isoformat(), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "api_calls": 0})
        by_day.append({"date": cur.isoformat(), **rec})
        cur += timedelta(days=1)

    return {"totals": totals, "by_model": model_index, "by_day": by_day}
