"""
event_types.py — 统一事件协议定义

集中定义所有 ReAct 事件类型、字段规范和构造方法。

使用示例：
    from src.core.event_types import ReactEventType, make_event, LEGACY_EVENT_NAME_MAP

    e = make_event(ReactEventType.TOOL_CALL, tool_name="dm_query", tool_args={"date": "2026-08"})
    assert e["type"] == "tool_call"
    assert e["data"]["tool_name"] == "dm_query"
    assert LEGACY_EVENT_NAME_MAP["reasoning"] == "think"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# 事件类型枚举
# ══════════════════════════════════════════════════════════════════════════════

class ReactEventType(str, Enum):
    """ReAct 协议事件类型（与前端约定对齐）"""

    # ★ v4.0: THINKING 拆分为三段式流式思考
    THINK_START   = "think_start"     # 思考开始
    THINK         = "think"           # 思考增量（多个）
    THINK_END     = "think_end"       # 思考结束
    TOOL_CALL     = "tool_call"       # 工具调用开始
    TOOL_RESULT   = "tool_result"     # 工具执行结果
    TOOL_START    = "tool_start"      # 工具执行开始（含时间戳）
    TOOL_PROGRESS = "tool_progress"   # 工具执行进度（耗时长的工具）
    PLAN_CREATED  = "plan_created"    # 计划已创建（阶段3 接通 Planner）
    PLAN_STEP     = "plan_step"       # 计划步骤状态变更（阶段3）
    MESSAGE_START = "message_start"   # ★ v4.0: 正文开始
    MESSAGE       = "message"         # ★ v4.1: 流式正文 chunk（ReAct 正文 token 实时转发）
    MESSAGE_END   = "message_end"     # ★ v4.0: 唯一终止标记（替代 FINAL）
    META          = "meta"            # 会话元信息
    MANAGER_DECISION = "manager_decision"  # Manager 路由决策
    SKILL_MATCH   = "skill_match"     # 技能匹配结果
    ERROR         = "error"           # 错误
    CONFIRMATION  = "confirmation"    # 需要用户确认（替代旧 "clarification_needed"")


# ══════════════════════════════════════════════════════════════════════════════
# 旧事件名 → 新事件名 映射表（过渡期兼容）
# ══════════════════════════════════════════════════════════════════════════════

LEGACY_EVENT_NAME_MAP: Dict[str, str] = {
    "reasoning":              ReactEventType.THINK.value,
    "thinking":               ReactEventType.THINK.value,        # 旧 thinking → 新 think
    "clarification_needed":   ReactEventType.CONFIRMATION.value,
    "tool_call":              ReactEventType.TOOL_CALL.value,
    "tool_result":            ReactEventType.TOOL_RESULT.value,
    "plan_created":           ReactEventType.PLAN_CREATED.value,
    "plan_step":              ReactEventType.PLAN_STEP.value,
    "final":                  ReactEventType.MESSAGE_END.value,  # ★ 旧 final → 新 message_end
    "error":                  ReactEventType.ERROR.value,
    "warning":                "warning",
    "skill_match":            "skill_match",
}


# ══════════════════════════════════════════════════════════════════════════════
# 各事件类型的字段规范（dataclass）
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ThinkStartEvent:
    """think_start 事件 — 思考阶段开始"""
    phase: str = "worker"      # manager | worker
    iteration: int = 0


@dataclass
class ThinkEvent:
    """think 事件 — 思考增量（流式）"""
    chunk: str                 # 增量文本
    phase: str = "worker"
    iteration: int = 0


@dataclass
class ThinkEndEvent:
    """think_end 事件 — 思考阶段结束"""
    full_reasoning: str        # 完整推理内容
    phase: str = "worker"
    iteration: int = 0


@dataclass
class ToolCallEvent:
    """tool_call 事件 — 工具调用开始"""
    tool_name: str
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""
    iteration: int = 0


@dataclass
class ToolResultEvent:
    """tool_result 事件 — 工具执行结果"""
    tool_name: str
    result: Any = None
    success: bool = True
    tool_call_id: str = ""
    elapsed_ms: int = 0
    iteration: int = 0


@dataclass
class PlanCreatedEvent:
    """plan_created 事件 — 计划已创建（阶段3 用）"""
    plan_id: str
    steps: List[str] = field(default_factory=list)
    total_steps: int = 0


@dataclass
class PlanStepEvent:
    """plan_step 事件 — 步骤状态变更（阶段3 用）"""
    step_index: int
    step_desc: str
    status: str  # pending | running | completed | failed | skipped
    result: Any = None


@dataclass
class MessageStartEvent:
    """message_start 事件 — 正文开始"""
    pass


@dataclass
class MessageEvent:
    """message 事件 — 流式正文 chunk（★ v4.1）"""
    chunk: str
    iteration: int = 0


@dataclass
class MessageEndEvent:       # ← 替代 FinalEvent
    """message_end 事件 — 唯一终止标记"""
    full_response: str = ""
    iterations: int = 0
    tools_used: List[str] = field(default_factory=list)
    elapsed_ms: int = 0


@dataclass
class ErrorEvent:
    """error 事件 — 错误"""
    message: str
    iteration: int = 0
    recoverable: bool = False


@dataclass
class ConfirmationEvent:
    """confirmation 事件 — 需要用户确认"""
    message: str
    options: List[str] = field(default_factory=list)
    timeout_sec: int = 0


@dataclass
class ToolStartEvent:
    """tool_start 事件 — 工具执行开始（含时间戳）"""
    tool_name: str
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""
    iteration: int = 0
    start_time: float = 0.0


@dataclass
class ToolProgressEvent:
    """tool_progress 事件 — 工具执行进度（耗时长的工具）"""
    tool_name: str
    tool_call_id: str = ""
    iteration: int = 0
    progress: str = ""


@dataclass
class MetaEvent:
    """meta 事件 — 会话元信息"""
    session_id: str = ""
    session_summary: str = ""
    is_new_session: bool = False
    agent_id: str = ""


@dataclass
class ManagerDecisionEvent:
    """manager_decision 事件 — Manager 路由决策"""
    intent: str = "task"
    target_agent: str = "dfecrab"
    parameters: Dict[str, Any] = field(default_factory=dict)
    missing_params: List[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class SkillMatchEvent:
    """skill_match 事件 — 技能匹配结果"""
    skills: List[Dict[str, Any]] = field(default_factory=list)
    agent_id: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# 统一构造函数
# ══════════════════════════════════════════════════════════════════════════════

def make_event(
    event_type: ReactEventType,
    /,
    **fields: Any,
) -> Dict[str, Any]:
    """构造符合协议的事件字典

    用法:
        >>> make_event(ReactEventType.THINK, chunk="我在思考...", iteration=1)
        {"type": "think", "data": {"chunk": "...", "iteration": 1}, "timestamp": 1.23}

        >>> make_event(ReactEventType.TOOL_CALL, tool_name="dm_query", tool_args={"date":"2026-08"})
        {"type": "tool_call", "data": {"tool_name": "dm_query", "tool_args": {...}}, "timestamp": 1.23}

    Args:
        event_type: ReactEventType 枚举值
        **fields: 事件字段（按各 dataclass 的字段名传入）

    Returns:
        事件字典: {"type": str, "data": dict, "timestamp": float}
    """
    # 把 snake_case 的字段名转为 dataclass 构造函数需要的参数
    # 过滤掉不属于该事件的字段，保留到 data 中
    return {
        "type": event_type.value,
        "data": dict(fields),
        "timestamp": time.time(),
    }


def normalize_legacy_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """将旧事件名转换为新协议事件名

    保留所有原有字段，只修改 type 值。

    Args:
        event: 旧格式事件字典，如 {"type": "reasoning", "content": "..."}

    Returns:
        新格式事件字典，如 {"type": "think", "content": "..."}
    """
    old_type = event.get("type", "")
    new_type = LEGACY_EVENT_NAME_MAP.get(old_type, old_type)

    if new_type != old_type:
        # 兼容：保留旧 content 字段在 data 中（前端老代码可能还在读）
        data = dict(event)
        data.pop("type", None)
        return {
            "type": new_type,
            "data": data,
            "timestamp": time.time(),
        }

    return event


# ══════════════════════════════════════════════════════════════════════════════
# ★ S4: 统一事件信封 — 所有 HTTP/WS 接口共用
# ══════════════════════════════════════════════════════════════════════════════

def make_event_envelope(
    event: Dict[str, Any],
    session_id: str = "",
    correlation_id: str = "",
) -> Dict[str, Any]:
    """将内部事件包装为统一的外层信封格式

    输入: {"type": "think", "data": {"chunk": "..."}}
    输出: {"type": "event", "id": "...", "data": {"event_type": "think", "data": {...}, ...}, ...}

    HTTP SSE 和 WebSocket 非流式接口都使用此函数统一事件格式。
    WebSocket 流式接口通过 WSMessage 包裹，不需要额外信封。
    """
    import uuid as _uuid
    from datetime import datetime as _datetime

    event_type = event.get("type", "unknown")
    inner_data = event.get("data", {})

    return {
        "type": "event",
        "id": str(_uuid.uuid4()),
        "data": {
            "event_type": event_type,
            "data": inner_data,
            "session_id": session_id or inner_data.get("session_id", ""),
            "correlation_id": correlation_id,
        },
        "timestamp": _datetime.now().isoformat(),
        "correlation_id": correlation_id,
    }
