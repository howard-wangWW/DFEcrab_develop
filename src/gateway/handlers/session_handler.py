"""会话管理处理器（HTTP 适配层）

统一委托给 `src.gateway.session_handler.SessionService`（协议无关业务层）：
- 权限检查/数据范围收敛在 SessionService，handler 不重复实现、不绕过；
- 身份解析走统一入口 `src.gateway.identity.resolve_user_id`；
- 该适配层同时供 HTTP（本模块）与 WebSocket 复用同一份业务逻辑。

覆盖路由：
    GET    /api/v2/sessions
    POST   /api/v2/sessions
    GET    /api/v2/sessions/{session_id}
    GET    /api/v2/sessions/{session_id}/messages
    DELETE /api/v2/sessions/deleteSession/{session_id}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.gateway.identity import resolve_user_id

logger = logging.getLogger(__name__)

#: 身份缺省值：与网关历史行为一致（普通用户只看自己数据）
DEFAULT_FALLBACK = "default"


def _truthy(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes")


def _path_session_id(request: Any, session_id: Optional[str]) -> Optional[str]:
    if session_id:
        return session_id
    try:
        return request.path_params.get("session_id")
    except Exception:
        return None


class SessionHandler:
    """会话管理处理器（HTTP 适配层）"""

    @staticmethod
    async def list_sessions(request: Any) -> Dict[str, Any]:
        """列出会话（?limit=50&include_empty=false；数据范围 all 看全部，own 只看自己的）"""
        try:
            from src.gateway.session_handler import SessionService

            params = getattr(request, "query_params", {}) or {}
            return SessionService.list_sessions(
                user_id=resolve_user_id(request, DEFAULT_FALLBACK),
                limit=int(params.get("limit", 50)),
                include_empty=_truthy(params.get("include_empty", "false")),
            )
        except Exception as e:
            logger.error(f"[SessionHandler] 列出会话失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def create_session(request: Any) -> Dict[str, Any]:
        """创建新会话（归属当前用户；body: {topic}）"""
        try:
            from src.gateway.session_handler import SessionService

            body = await request.json()
            return SessionService.create_session(
                user_id=resolve_user_id(request, DEFAULT_FALLBACK),
                topic=body.get("topic"),
            )
        except Exception as e:
            logger.error(f"[SessionHandler] 创建会话失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_session(request: Any, session_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """获取会话详情（带权限检查）"""
        try:
            from src.gateway.session_handler import SessionService

            session_id = _path_session_id(request, session_id or kwargs.get("session_id"))
            return SessionService.get_session(
                session_id=session_id,
                current_user=resolve_user_id(request, DEFAULT_FALLBACK),
            )
        except Exception as e:
            logger.error(f"[SessionHandler] 获取会话失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_messages(request: Any, session_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """获取会话消息历史（?limit=20，带权限检查与每轮上下文占用）"""
        try:
            from src.gateway.session_handler import SessionService

            session_id = _path_session_id(request, session_id or kwargs.get("session_id"))
            params = getattr(request, "query_params", {}) or {}
            return SessionService.get_session_messages(
                session_id=session_id,
                current_user=resolve_user_id(request, DEFAULT_FALLBACK),
                limit=int(params.get("limit", 20)),
            )
        except Exception as e:
            logger.error(f"[SessionHandler] 获取会话消息失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def close_session(request: Any, session_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """删除会话（带权限检查 + 附件联动清理）"""
        try:
            from src.gateway.session_handler import SessionService

            session_id = _path_session_id(request, session_id or kwargs.get("session_id"))
            return SessionService.delete_session(
                session_id=session_id,
                current_user=resolve_user_id(request, DEFAULT_FALLBACK),
            )
        except Exception as e:
            logger.error(f"[SessionHandler] 删除会话失败: {e}")
            return {"success": False, "error": str(e)}