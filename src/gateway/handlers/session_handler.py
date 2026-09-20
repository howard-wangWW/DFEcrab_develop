"""
会话管理处理器（协议适配层）

统一委托给 src.gateway.session_handler.SessionService：
- 消除 admin 硬编码重复
- 复用 SessionService 内置的权限检查，避免绕过
"""

from typing import Dict, Any, Optional
from src.gateway.session_handler import SessionService


def _user_id(request: Optional[Any], fallback: str = "guest") -> str:
    """从请求头/查询参数解析 user_id（headers 已小写化存储）"""
    if request is None:
        return fallback
    return request.headers.get("x-user-id") or fallback


class SessionHandler:
    """会话管理处理器"""

    @staticmethod
    async def list_sessions(request: Optional[Any] = None) -> Dict[str, Any]:
        """列出会话（数据范围 all 看全部，own 只看自己的）"""
        try:
            params = getattr(request, 'query_params', {}) if request else {}
            user_id = _user_id(request)
            limit = int(params.get("limit", 50))
            return SessionService.list_sessions(user_id=user_id, limit=limit)
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_session(request: Any, session_id: Optional[str] = None) -> Dict[str, Any]:
        """获取会话详情（带权限检查）"""
        try:
            if session_id is None:
                session_id = getattr(request, 'path_params', {}).get('session_id')
            return SessionService.get_session(session_id, current_user=_user_id(request))
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_messages(request: Any, session_id: Optional[str] = None) -> Dict[str, Any]:
        """获取会话消息（带权限检查）"""
        try:
            if session_id is None:
                session_id = getattr(request, 'path_params', {}).get('session_id')
            params = getattr(request, 'query_params', {}) if request else {}
            limit = int(params.get("limit", 20))
            return SessionService.get_session_messages(
                session_id, current_user=_user_id(request), limit=limit
            )
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def close_session(request: Any, session_id: Optional[str] = None) -> Dict[str, Any]:
        """关闭会话（带权限检查）"""
        try:
            if session_id is None:
                session_id = getattr(request, 'path_params', {}).get('session_id')
            return SessionService.delete_session(session_id, current_user=_user_id(request))
        except Exception as e:
            return {"success": False, "error": str(e)}
