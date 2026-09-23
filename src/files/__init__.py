"""会话附件子系统（批次12：文件实体化生命周期）。

组成：
  - service.py   ：上传解析（落盘 + 摘要缓存）与按会话注入
  - registry.py  ：附件注册表（file_id / 会话归属 / 删除 / 孤儿清理）
  - multipart.py ：multipart/form-data 解析（零依赖）

生命周期对齐 LibreChat：上传即挂会话、对话自动注入、叉掉即删、删会话联动清理。
"""
from .service import FileService
from .registry import (
    register, get, list_by_session, list_by_user, list_unclaimed, attach_to_message,
    mark_deleted, delete_record, remove_by_session, cleanup_orphans,
)

__all__ = [
    "FileService",
    "register", "get", "list_by_session", "list_by_user", "list_unclaimed", "attach_to_message",
    "mark_deleted", "delete_record", "remove_by_session", "cleanup_orphans",
]
