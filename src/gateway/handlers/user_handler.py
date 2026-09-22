"""用户管理处理器（User Handler）

从 `GatewayV2GRPC` 抽出，业务逻辑仍在 `src/gateway/user_service.py`
（权限校验在 UserService 内，handler 只做协议适配 + 身份解析）。

路由（均为 admin_only，见 src/gateway/routes.py）：
    GET    /api/users
    POST   /api/users                 {user_id, role}
    PUT    /api/users/{user_id}       {role}
    DELETE /api/users/{user_id}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.gateway.identity import resolve_user_id

logger = logging.getLogger(__name__)


class UserHandler:
    """账号管理接口（HTTP 适配层）"""

    @staticmethod
    async def list_users(request: Any) -> Dict[str, Any]:
        """列出所有账号 → 角色映射"""
        try:
            from src.gateway.user_service import UserService
            return UserService.list_users()
        except Exception as e:
            logger.error(f"[UserHandler] 列出用户失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def create_user(request: Any) -> Dict[str, Any]:
        """新增账号（body: {user_id, role}；role 缺省 guest）"""
        try:
            from src.gateway.user_service import UserService
            body = await request.json()
            return UserService.create_user(
                user_id=body.get("user_id"),
                role=body.get("role", "guest"),
            )
        except Exception as e:
            logger.error(f"[UserHandler] 新增用户失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def update_user(request: Any, user_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """修改账号角色（body: {role}）"""
        try:
            from src.gateway.user_service import UserService
            user_id = user_id or kwargs.get("user_id") or request.path_params.get("user_id")
            body = await request.json()
            return UserService.update_user(
                user_id=user_id,
                role=body.get("role"),
                current_user=resolve_user_id(request),
            )
        except Exception as e:
            logger.error(f"[UserHandler] 修改用户失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def delete_user(request: Any, user_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """删除账号"""
        try:
            from src.gateway.user_service import UserService
            user_id = user_id or kwargs.get("user_id") or request.path_params.get("user_id")
            return UserService.delete_user(
                user_id=user_id,
                current_user=resolve_user_id(request),
            )
        except Exception as e:
            logger.error(f"[UserHandler] 删除用户失败: {e}")
            return {"success": False, "error": str(e)}
