"""
usage_store.py - 天级用量事件流（MCP 调用 / LLM token / 图片生成）

设计目标
--------
为「按天统计 MCP 调用次数」「按天统计 Token 消耗」提供一个与会话文件解耦的
轻量事件底座，取代"每次请求全量扫描 data/sessions/*_messages.json"的做法。

约定
----
1. 存储：``data/usage/YYYY-MM-DD.jsonl``，**按天分片**、append-only、一行一条事件。
   查询"某一天"只需读一个文件，成本与历史总量无关。
2. 可观测：一行一个 JSON 对象，字段固定带 ``ts`` / ``date`` / ``type``，
   并按需带 ``user_id`` / ``session_id`` / ``agent_id``（来自上下文，见 4）。
3. 事件类型：
   - ``mcp_call``    : server_name / tool_name / ok / elapsed_ms / error
   - ``llm_call``    : model / prompt_tokens / completion_tokens / total_tokens / source
   - ``image_gen``   : provider / model / size / n / ok / elapsed_ms / image_id
4. 上下文自动注入：MCP / 技能执行发生在 ReAct 循环内部，拿不到 HTTP 请求对象，
   因此用 ``ContextVar`` 携带当前 ``user_id / session_id / agent_id``，
   由对话入口（``_run_chat_pipeline``）设置一次，下游埋点自动补齐。
5. 零风险：所有写入/读取异常均被吞掉并降为 debug 日志——
   埋点属于旁路能力，绝不允许影响主业务流程。

线程安全
--------
MCP 调用在线程池（``asyncio.to_thread``）中同步执行，故文件追加用
``threading.Lock`` 保护；``ContextVar`` 在 ``to_thread`` 时会随上下文复制。
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

logger = logging.getLogger(__name__)

# 项目根：src/monitoring/usage_store.py -> src/monitoring -> src -> <root>
_ROOT = Path(__file__).resolve().parent.parent.parent
_USAGE_DIR = _ROOT / "data" / "usage"

# 单条文本字段落盘上限（防超长 error / prompt 撑爆事件文件）
_MAX_TEXT_CHARS = 500

# 事件类型常量
EVENT_MCP_CALL = "mcp_call"
EVENT_LLM_CALL = "llm_call"
EVENT_IMAGE_GEN = "image_gen"

DayLike = Union[str, date, datetime, None]


# ──────────────────────────────────────────────────────────────
# 上下文（user_id / session_id / agent_id）
# ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UsageContext:
    """埋点上下文（一次对话请求的身份信息）"""

    user_id: str = ""
    session_id: str = ""
    agent_id: str = ""


_EMPTY_CONTEXT = UsageContext()
_CTX: ContextVar[UsageContext] = ContextVar("dfecrab_usage_ctx", default=_EMPTY_CONTEXT)


def set_usage_context(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> None:
    """设置当前上下文的身份字段（None 表示保留原值）。"""
    cur = _CTX.get()
    _CTX.set(UsageContext(
        user_id=user_id if user_id is not None else cur.user_id,
        session_id=session_id if session_id is not None else cur.session_id,
        agent_id=agent_id if agent_id is not None else cur.agent_id,
    ))


def reset_usage_context() -> None:
    """清空当前上下文。"""
    _CTX.set(_EMPTY_CONTEXT)


@contextmanager
def usage_context(
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Iterator[UsageContext]:
    """以 with 方式临时设置上下文，退出后自动还原（供 chat 流水线使用）。"""
    cur = _CTX.get()
    ctx = UsageContext(
        user_id=user_id if user_id is not None else cur.user_id,
        session_id=session_id if session_id is not None else cur.session_id,
        agent_id=agent_id if agent_id is not None else cur.agent_id,
    )
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def current_usage_context() -> UsageContext:
    """读取当前上下文（始终返回对象，不会为 None）。"""
    return _CTX.get()


# ──────────────────────────────────────────────────────────────
# 路径 / 工具函数
# ──────────────────────────────────────────────────────────────


def usage_dir() -> Path:
    """事件流根目录。"""
    return _USAGE_DIR


def day_str(day: DayLike = None) -> str:
    """把 date / datetime / str / None 统一成 ``YYYY-MM-DD``（空串回落今天）。"""
    today = date.today().strftime("%Y-%m-%d")
    if isinstance(day, str):
        return day.strip() or today
    if isinstance(day, datetime):
        return day.strftime("%Y-%m-%d")
    if isinstance(day, date):
        return day.strftime("%Y-%m-%d")
    return today


def _clip(value: Any, limit: int = _MAX_TEXT_CHARS) -> Any:
    """截断过长文本字段；非字符串原样返回。"""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    return value[:limit] + "...(truncated)"


def _event_file(day: DayLike) -> Path:
    return _USAGE_DIR / f"{day_str(day)}.jsonl"


# ──────────────────────────────────────────────────────────────
# 写入
# ──────────────────────────────────────────────────────────────

_WRITE_LOCK = threading.Lock()


def record_event(event: Dict[str, Any], day: DayLike = None) -> bool:
    """追加一条事件到当天事件文件。

    Args:
        event: 事件字典，函数会自动补齐 ``ts`` / ``date`` / ``type`` 及上下文字段。
        day: 指定落盘日期（默认今天，主要用于测试）。

    Returns:
        bool: 是否写入成功（失败不抛异常）。
    """
    try:
        if not isinstance(event, dict) or not event.get("type"):
            return False

        ctx = current_usage_context()
        now = datetime.now()
        payload: Dict[str, Any] = {
            "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": day_str(day),
            "user_id": ctx.user_id,
            "session_id": ctx.session_id,
            "agent_id": ctx.agent_id,
        }
        for key, value in event.items():
            payload[key] = _clip(value) if isinstance(value, str) else value

        line = json.dumps(payload, ensure_ascii=False, default=str)

        target = _event_file(day)
        with _WRITE_LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return True
    except Exception as exc:  # noqa: BLE001 - 埋点失败必须降级
        logger.debug(f"[usage_store] 记录事件失败: {exc}")
        return False


def record_mcp_call(
    server_name: str,
    tool_name: str,
    ok: bool,
    elapsed_ms: int = 0,
    error: Optional[str] = None,
) -> bool:
    """记录一次 MCP 工具调用（成功/失败都记）。"""
    event: Dict[str, Any] = {
        "type": EVENT_MCP_CALL,
        "server_name": server_name or "unknown",
        "tool_name": tool_name or "unknown",
        "ok": bool(ok),
        "elapsed_ms": int(elapsed_ms or 0),
    }
    if error:
        event["error"] = error
    return record_event(event)


def record_llm_call(
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    source: str = "llm_usage",
    session_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> bool:
    """记录一次 LLM 调用（token 用量）。

    Args:
        source: ``llm_usage``=模型真实返回的 usage；``local_estimate``=本地估算兜底。
    """
    prompt = int(prompt_tokens or 0)
    completion = int(completion_tokens or 0)
    if prompt <= 0 and completion <= 0:
        return False
    event: Dict[str, Any] = {
        "type": EVENT_LLM_CALL,
        "model": model or "unknown",
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "source": source or "llm_usage",
    }
    if session_id:
        event["session_id"] = session_id
    if extra:
        event.update(extra)
    return record_event(event)


def record_image_gen(
    provider: str = "",
    model: str = "",
    size: str = "",
    n: int = 1,
    ok: bool = True,
    elapsed_ms: int = 0,
    image_id: str = "",
    error: Optional[str] = None,
) -> bool:
    """记录一次图片生成。"""
    event: Dict[str, Any] = {
        "type": EVENT_IMAGE_GEN,
        "provider": provider or "unknown",
        "model": model or "unknown",
        "size": size or "",
        "n": int(n or 1),
        "ok": bool(ok),
        "elapsed_ms": int(elapsed_ms or 0),
    }
    if image_id:
        event["image_id"] = image_id
    if error:
        event["error"] = error
    return record_event(event)


# ──────────────────────────────────────────────────────────────
# 读取
# ──────────────────────────────────────────────────────────────


def read_events(day: DayLike = None) -> List[Dict[str, Any]]:
    """读取某一天的全部事件（按写入顺序）；文件不存在/损坏时返回已解析部分。"""
    path = _event_file(day)
    events: List[Dict[str, Any]] = []
    try:
        if not path.exists():
            return events
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    events.append(obj)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"[usage_store] 读取事件失败 {path}: {exc}")
    return events


def read_events_range(start: DayLike, end: DayLike) -> List[Dict[str, Any]]:
    """读取 [start, end] 闭区间内每天的事件（按天拼接）。"""
    from datetime import timedelta

    s = _to_date(start)
    e = _to_date(end)
    if s is None or e is None:
        return []
    out: List[Dict[str, Any]] = []
    cur = s
    while cur <= e:
        out.extend(read_events(cur))
        cur += timedelta(days=1)
    return out


def _to_date(day: DayLike) -> Optional[date]:
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