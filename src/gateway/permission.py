"""
权限判定服务

基于 config/permissions.json 的简单权限（功能权限 × 数据范围）：
- 功能权限 level：read（只看）/ write（能改）
- 数据范围 data_scope：all（看全部数据）/ own（只看自己的）
- 系统管理（用户管理等）：仅 admin 角色
- 未注册用户落到 default_role（默认 guest）
"""

import json
from pathlib import Path
from typing import Any, Dict


class PermissionService:
    """权限判定服务（单例，启动时读取一次配置文件）"""

    _instance = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        # permission.py 位于 src/gateway/ 下，3 级 parent 定位到 DFEcrab 根目录
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "permissions.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self.__class__._config = json.load(f)

    def reload(self):
        """重新加载配置（用户管理接口变更后调用）"""
        self.__class__._config = {}
        self._load_config()

    def resolve_role(self, user_id: str) -> str:
        """解析用户所属角色，未注册用户落到 default_role"""
        users = self._config.get("users", {})
        return users.get(user_id, self._config.get("default_role", "guest"))

    def _get_role(self, user_id: str) -> Dict[str, Any]:
        """获取用户角色配置，未知角色返回空"""
        role_name = self.resolve_role(user_id)
        return self._config.get("roles", {}).get(role_name, {})

    def is_admin(self, user_id: str) -> bool:
        """是否管理员（系统管理专属）"""
        return self.resolve_role(user_id) == "admin"

    def has_access(self, user_id: str, required_level: str) -> bool:
        """功能权限：用户是否具备指定操作等级（read < write）"""
        role = self._get_role(user_id)
        if not role:
            return False
        if required_level == "read":
            return True
        if required_level == "write":
            return role.get("level") == "write"
        return False

    def data_scope_of(self, user_id: str) -> str:
        """数据范围：all（看全部）/ own（只看自己的）"""
        role = self._get_role(user_id)
        return role.get("data_scope", "own")

    def can_access_record(self, user_id: str, required_level: str,
                          owner_id: str = None) -> bool:
        """组合判定：功能权限 + 数据范围（针对单条记录）"""
        if not self.has_access(user_id, required_level):
            return False
        if self.data_scope_of(user_id) == "all":
            return True
        return owner_id == user_id
