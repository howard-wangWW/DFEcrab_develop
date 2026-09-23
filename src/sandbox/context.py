# -*- coding: utf-8 -*-
"""请求级会话上下文（沙箱工具定位会话附件与工作区的唯一来源）。

背景：ToolRegistry.execute_tool(name, **kwargs) 只透传模型给的参数，工具函数拿不到
session_id。而会话上传的附件按 session_id 分桶（src/files/registry.py）。
故在网关入口登记 ContextVar，工具执行时读取。

传播保证：
  - 同一 async 任务内的 await 链可见（ContextVar 随 task context 传递）
  - registry.execute_tool 对同步技能走 asyncio.to_thread，其内部基于
    contextvars.copy_context()，同样可见

登记方式（两档，按稳健性递进）：
  1) set_request_context(session_id=..., user_id=..., agent_id=...)  —— 直接给值
  2) set_request_context_from_locals(locals())                       —— 网关侧推荐
     为什么要第 2 档：DFEcrab 的 grpc_server.py 在不同部署版本里，承载这些标识的
     局部变量名并不一致（例如 agent_id 只在部分分支赋值、有的版本用
     effective_agent_id）。若在注入的代码里直接写 `agent_id`，一旦该版本没有这个名字
     就会抛 NameError，整段登记被 except 吞掉而**静默失效**——工具侧只表现为
     "拿不到会话"，排查成本很高。用 locals() 取值则"取到什么登记什么，取不到留空
     由工具侧兜底"，注入代码本身就与版本无关。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, Iterable, Optional

_REQUEST_CTX: ContextVar[Dict[str, Any]] = ContextVar(
    "dfecrab_sandbox_request", default={}
)

# 候选变量名（按优先级排列）：不同部署版本的网关可能用不同命名
_SESSION_KEYS = ("session_id", "sessionId", "conversation_id", "sid")
_USER_KEYS = ("user_id", "userId", "uid")
_AGENT_KEYS = ("agent_id", "agentId", "effective_agent_id", "target_agent_id", "current_agent_id")


def _pick(namespace: Dict[str, Any], keys: Iterable[str]) -> str:
    """从命名空间里按优先级取第一个非空值（取不到返回空串，绝不抛异常）。"""
    if not isinstance(namespace, dict):
        return ""
    for k in keys:
        if k in namespace:
            v = namespace.get(k)
            if v is None or isinstance(v, (dict, list, tuple, set)):
                continue
            s = str(v).strip()
            if s and s.lower() not in ("none", "null", "undefined"):
                return s
    return ""


def set_request_context(session_id: str = "", user_id: str = "", agent_id: str = "") -> None:
    """登记当前请求的会话标识（网关入口调用；同一任务内覆盖式写入）。"""
    _REQUEST_CTX.set({
        "session_id": str(session_id or ""),
        "user_id": str(user_id or ""),
        "agent_id": str(agent_id or ""),
    })


def set_request_context_from_locals(namespace: Optional[Dict[str, Any]] = None, **overrides: Any) -> Dict[str, Any]:
    """从调用方 locals() 里挑出会话标识并登记；返回实际登记的值（便于断言与排障）。

    用法（注入到网关的代码）：``set_request_context_from_locals(locals())``
    显式值优先于 locals 中的同名键（overrides）。
    """
    ns: Dict[str, Any] = dict(namespace) if isinstance(namespace, dict) else {}
    ns.update(overrides)
    vals = {
        "session_id": _pick(ns, _SESSION_KEYS),
        "user_id": _pick(ns, _USER_KEYS),
        "agent_id": _pick(ns, _AGENT_KEYS),
    }
    set_request_context(**vals)
    return vals


def get_request_context() -> Dict[str, Any]:
    """读取当前请求上下文；未登记时返回空字段字典（调用方各自兜底）。"""
    return dict(_REQUEST_CTX.get() or {})


def current_session_id(fallback: str = "") -> str:
    """当前会话标识；缺省回退到 fallback，最终兜底 "no_session"。"""
    ctx = get_request_context()
    sid = str(ctx.get("session_id") or "").strip()
    if sid:
        return sid
    fb = str(fallback or "").strip()
    return fb or "no_session"


def current_user_id(fallback: str = "default") -> str:
    ctx = get_request_context()
    uid = str(ctx.get("user_id") or "").strip()
    return uid or str(fallback or "default")
