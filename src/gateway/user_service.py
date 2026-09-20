"""
用户管理服务

读取 / 修改 config/permissions.json 中的 users 映射（账号 -> 角色）。
仅管理员（admin）可通过网关调用；每次变更后重载 PermissionService 使配置立即生效。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.gateway.permission import PermissionService

logger = logging.getLogger(__name__)

# user_service.py 位于 src/gateway/ 下，3 级 parent 定位到 DFEcrab 根目录
CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "permissions.json"

VALID_ROLES = ("admin", "user", "guest")


class UserService:
    """用户 CRUD 服务（账号 -> 角色）"""

    @staticmethod
    def _read_config() -> Dict[str, Any]:
        if not CONFIG_PATH.exists():
            return {"users": {}, "roles": {}}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_config(config: Dict[str, Any]):
        """原子写回 permissions.json（写前备份 + 临时文件替换），并热重载权限。"""
        try:
            CONFIG_PATH.with_suffix('.json.bak').write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            logger.warning(f"用户配置备份失败: {e}")
        tmp = CONFIG_PATH.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(CONFIG_PATH)
        # 变更后重载，使判定立即生效
        PermissionService().reload()

    @staticmethod
    def list_users() -> Dict[str, Any]:
        """列出所有账号及角色"""
        try:
            config = UserService._read_config()
            users = config.get("users", {})
            return {"success": True, "count": len(users), "users": users}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def create_user(user_id: str, role: str = "guest") -> Dict[str, Any]:
        """新增账号"""
        try:
            user_id = (user_id or "").strip()
            if not user_id:
                return {"success": False, "error": "账号不能为空"}
            if role not in VALID_ROLES:
                return {"success": False, "error": f"角色必须是 {VALID_ROLES} 之一"}
            config = UserService._read_config()
            users = config.setdefault("users", {})
            if user_id in users:
                return {"success": False, "error": f"账号已存在: {user_id}"}
            users[user_id] = role
            UserService._write_config(config)
            return {"success": True, "message": f"账号已创建: {user_id} ({role})"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def update_user(user_id: str, role: str = None, current_user: str = None) -> Dict[str, Any]:
        """修改账号角色（不能把当前登录账号降级，避免误操作锁死自己）"""
        try:
            if role is not None and role not in VALID_ROLES:
                return {"success": False, "error": f"角色必须是 {VALID_ROLES} 之一"}
            if user_id and current_user and user_id == current_user and role != "admin":
                return {"success": False, "error": "不能把当前登录账号降级为普通角色"}
            config = UserService._read_config()
            users = config.get("users", {})
            if user_id not in users:
                return {"success": False, "error": f"账号不存在: {user_id}"}
            if role is None:
                return {"success": False, "error": "缺少 role 参数"}
            users[user_id] = role
            UserService._write_config(config)
            return {"success": True, "message": f"账号已更新: {user_id} ({role})"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def delete_user(user_id: str, current_user: str = None) -> Dict[str, Any]:
        """删除账号（不能删除当前登录账号）"""
        try:
            if user_id and current_user and user_id == current_user:
                return {"success": False, "error": "不能删除当前登录账号"}
            config = UserService._read_config()
            users = config.get("users", {})
            if user_id not in users:
                return {"success": False, "error": f"账号不存在: {user_id}"}
            del users[user_id]
            UserService._write_config(config)
            return {"success": True, "message": f"账号已删除: {user_id}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
