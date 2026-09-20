"""
ConfirmationManager — 高风险工具调用前的人工确认

负责 add / get / remove 确认请求，支持超时和 resume 机制。
在 loop.py 中，CONFIRMATION 事件 yield 后暂停循环，等待用户回复。

使用流程：
  1. loop.py 遇到需要确认的操作 → yield CONFIRMATION 事件
  2. _react_chat_generator 透传 confirmation 事件给前端
  3. 前端显示确认对话框，用户点击"允许/拒绝"
  4. 前端发 POST /api/confirm/response
  5. ConfirmationManager.resume() 唤醒等待的 asyncio.Event
  6. loop.py 收到用户决定后继续执行或跳过

与旧版 legacy.py 的区别：
  - 旧版：仅用于 multi-agent 求助确认
  - 新版：通用确认，用于工具调用前确认（如删除文件、批量操作）
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 确认状态枚举
# ──────────────────────────────────────────────────────────────

class ConfirmStatus(str, Enum):
    PENDING   = "pending"    # 等待用户确认
    APPROVED  = "approved"   # 用户允许
    REJECTED  = "rejected"   # 用户拒绝
    TIMEOUT   = "timeout"    # 超时未响应
    CANCELLED = "cancelled"  # 已取消


# ──────────────────────────────────────────────────────────────
# 确认请求
# ──────────────────────────────────────────────────────────────

@dataclass
class ConfirmationRequest:
    """单次确认请求"""

    confirm_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # ── 上下文 ──
    session_id: str = ""
    user_id: str = ""
    tool_name: str = ""      # 触发确认的工具名
    tool_args: Dict[str, Any] = field(default_factory=dict)

    # ── 提示 ──
    message: str = ""        # 给用户看的提示文字
    options: List[str] = field(default_factory=list)  # 可选项

    # ── 状态 ──
    status: ConfirmStatus = ConfirmStatus.PENDING
    user_choice: str = ""    # 用户选择的选项
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None

    # ── 控制 ──
    timeout_sec: int = 30    # 超时秒数（0=不超时）
    _event: Optional[asyncio.Event] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirm_id": self.confirm_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "message": self.message,
            "options": self.options,
            "status": self.status.value,
            "user_choice": self.user_choice,
            "timeout_sec": self.timeout_sec,
            "created_at": self.created_at,
        }


# ──────────────────────────────────────────────────────────────
# ConfirmationManager
# ──────────────────────────────────────────────────────────────

class ConfirmationManager:
    """确认管理器（单例）

    存储所有待确认请求，支持按 session_id 查找、超时检查、resume 唤醒。
    """

    def __init__(self):
        # session_id → ConfirmationRequest（同一会话只保留一个待确认）
        self._pending: Dict[str, ConfirmationRequest] = {}
        # confirm_id → ConfirmationRequest（全局索引）
        self._by_id: Dict[str, ConfirmationRequest] = {}
        # 已处理的历史记录（最多保留 100 条）
        self._history: List[ConfirmationRequest] = []
        self._max_history: int = 100

    # ── 增删改查 ──

    def add(
        self,
        session_id: str,
        message: str,
        tool_name: str = "",
        tool_args: Optional[Dict[str, Any]] = None,
        options: Optional[List[str]] = None,
        timeout_sec: int = 30,
        user_id: str = "",
    ) -> ConfirmationRequest:
        """添加一个待确认请求

        Args:
            session_id: 会话 ID
            message: 确认提示文字
            tool_name: 触发确认的工具名
            tool_args: 工具参数
            options: 可选项列表（如 ["允许", "拒绝"]）
            timeout_sec: 超时秒数（0=不超时）
            user_id: 用户 ID

        Returns:
            ConfirmationRequest
        """
        req = ConfirmationRequest(
            session_id=session_id,
            user_id=user_id,
            tool_name=tool_name,
            tool_args=tool_args or {},
            message=message,
            options=options or ["允许", "拒绝"],
            timeout_sec=timeout_sec,
            status=ConfirmStatus.PENDING,
            _event=asyncio.Event(),
        )

        self._pending[session_id] = req
        self._by_id[req.confirm_id] = req

        logger.info(
            f"[Confirmation] 新增: session={session_id}, "
            f"tool={tool_name}, timeout={timeout_sec}s, "
            f"confirm_id={req.confirm_id}"
        )
        return req

    def get(self, session_id: str) -> Optional[ConfirmationRequest]:
        """获取指定会话的待确认请求"""
        return self._pending.get(session_id)

    def get_by_id(self, confirm_id: str) -> Optional[ConfirmationRequest]:
        """按 confirm_id 获取确认请求"""
        return self._by_id.get(confirm_id)

    def list_pending(self) -> List[ConfirmationRequest]:
        """列出所有待确认请求"""
        return list(self._pending.values())

    def remove(self, session_id: str) -> Optional[ConfirmationRequest]:
        """移除指定会话的待确认请求（返回被移除的请求）"""
        req = self._pending.pop(session_id, None)
        if req:
            req.status = ConfirmStatus.CANCELLED
            req.resolved_at = time.time()
            if req._event:
                req._event.set()  # 唤醒等待者
            self._add_to_history(req)
            logger.debug(f"[Confirmation] 已移除: session={session_id}")
        return req

    # ── 用户响应 ──

    async def resume(
        self,
        session_id: str,
        approved: bool,
        user_choice: str = "",
    ) -> Optional[ConfirmationRequest]:
        """用户做出响应后，唤醒等待的 asyncio.Event

        Args:
            session_id: 会话 ID
            approved: 是否允许
            user_choice: 用户选择的选项文本

        Returns:
            ConfirmationRequest 或 None（如不存在）
        """
        req = self._pending.get(session_id)
        if not req:
            logger.warning(f"[Confirmation] resume 失败: session={session_id} 无待确认请求")
            return None

        req.status = ConfirmStatus.APPROVED if approved else ConfirmStatus.REJECTED
        req.user_choice = user_choice
        req.resolved_at = time.time()

        # 唤醒等待的 asyncio.Event
        if req._event:
            req._event.set()
            logger.info(
                f"[Confirmation] 已唤醒: session={session_id}, "
                f"approved={approved}, choice={user_choice}"
            )

        # 移入历史
        self._pending.pop(session_id, None)
        self._add_to_history(req)
        return req

    # ── 超时处理 ──

    async def check_timeouts(self) -> List[ConfirmationRequest]:
        """检查并处理所有超时的确认请求

        Returns:
            list[ConfirmationRequest]: 已超时的请求列表
        """
        now = time.time()
        timed_out = []

        for session_id, req in list(self._pending.items()):
            if req.timeout_sec <= 0:
                continue
            if now - req.created_at > req.timeout_sec:
                req.status = ConfirmStatus.TIMEOUT
                req.resolved_at = now
                if req._event:
                    req._event.set()  # 唤醒等待者
                self._pending.pop(session_id, None)
                self._add_to_history(req)
                timed_out.append(req)
                logger.warning(
                    f"[Confirmation] 超时: session={session_id}, "
                    f"tool={req.tool_name}, elapsed={now - req.created_at:.1f}s"
                )

        return timed_out

    # ── 等待方法 ──

    async def wait_for_response(
        self,
        session_id: str,
        timeout_sec: int = 0,
    ) -> ConfirmStatus:
        """等待用户确认响应

        Args:
            session_id: 会话 ID
            timeout_sec: 等待超时秒数（0=使用请求自带的超时）

        Returns:
            ConfirmStatus: 最终状态
        """
        req = self._pending.get(session_id)
        if not req:
            return ConfirmStatus.CANCELLED

        effective_timeout = timeout_sec or req.timeout_sec
        event = req._event

        try:
            if effective_timeout > 0:
                await asyncio.wait_for(event.wait(), timeout=effective_timeout)
            else:
                await event.wait()
        except asyncio.TimeoutError:
            req.status = ConfirmStatus.TIMEOUT
            req.resolved_at = time.time()
            self._pending.pop(session_id, None)
            self._add_to_history(req)
            logger.warning(f"[Confirmation] wait 超时: session={session_id}")
            return ConfirmStatus.TIMEOUT

        return req.status

    # ── 历史 ──

    def _add_to_history(self, req: ConfirmationRequest) -> None:
        """添加到历史记录"""
        self._history.append(req)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的确认历史"""
        return [r.to_dict() for r in self._history[-limit:]]


# ──────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────

_instance: Optional[ConfirmationManager] = None


def get_confirmation_manager() -> ConfirmationManager:
    """获取全局 ConfirmationManager 单例"""
    global _instance
    if _instance is None:
        _instance = ConfirmationManager()
    return _instance


def reset_confirmation_manager() -> None:
    """重置全局单例"""
    global _instance
    _instance = None
