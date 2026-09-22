"""请求身份解析（唯一身份来源）

网关所有 handler 都通过 `resolve_user_id(request)` 取当前用户，
避免各处重复实现 `request.headers.get("x-user-id", ...)` 且 fallback 不一致。

约定：
- HTTP headers 已被 HTTPServer 统一小写化，因此取 `x-user-id`；
- 缺省值保持网关历史行为 `"default"`（注意：`handlers/session_handler.py` 的适配层用 `"guest"`，
  两者数据范围不同，迁移时需显式指定 fallback）。
"""

from __future__ import annotations

from typing import Any, Optional

#: 网关内部默认身份（历史行为）
DEFAULT_FALLBACK = "default"


def resolve_user_id(request: Optional[Any], fallback: str = DEFAULT_FALLBACK) -> str:
    """从请求头 `X-User-Id` 解析当前用户；缺失时返回 fallback。"""
    if request is None:
        return fallback
    try:
        headers = getattr(request, "headers", None) or {}
        return headers.get("x-user-id") or fallback
    except Exception:
        return fallback
