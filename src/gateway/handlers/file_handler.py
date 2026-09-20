# -*- coding: utf-8 -*-
"""
FileHandler - 会话附件接口（批次12：文件实体化生命周期）

接口：
  POST   /api/files                      multipart 上传（field: session_id / file）
  GET    /api/files?session_id=          列某会话 active 附件
  DELETE /api/files/{file_id}            删除（owner 或 admin）
  GET    /api/files/{file_id}/download   下载原文件（owner 或 admin）

权限模型（对齐记忆接口）：X-User-Id 头为身份；普通用户只能操作自己的附件，
admin 可跨用户操作（?user_id= 查他人、删他人）。数据按会话隔离。

删除语义：叉掉 chip → DELETE → 删落盘原文件 + 注册表 status=deleted
（保留记录防复活/审计）；后续对话不再注入该附件。
"""
from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 上传配置（真实值以 dfecrab.json file_upload 段为准，含兜底）
_CFG_DEFAULTS = {
    "max_file_size_mb": 10,
    "max_files_per_session": 5,
    "allowed_extensions": [".txt", ".md", ".log", ".csv", ".xlsx"],
}

# MIME 显式覆盖（不依赖系统注册表：Windows 会把 .csv 识别为 application/vnd.ms-excel）
_MIME_OVERRIDES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
}


def _cfg() -> Dict[str, Any]:
    try:
        from src.config.app_config import section
        c = section("file_upload") or {}
        return dict(_CFG_DEFAULTS, **{k: v for k, v in c.items()})
    except Exception:
        return dict(_CFG_DEFAULTS)


class FileHandler:
    """会话附件处理器"""

    @staticmethod
    def _req_user(request: Any) -> str:
        """当前请求身份（X-User-Id 头，缺省走 identity.default_user_id；对齐 B-2 收敛）"""
        headers = getattr(request, "headers", {}) or {}
        if str(headers.get("x-user-id") or "").strip():
            return str(headers.get("x-user-id")).strip()
        try:
            from src.config.app_config import section
            return str((section("identity") or {}).get("default_user_id") or "default")
        except Exception:
            return "default"

    @staticmethod
    def _is_admin(user_id: str) -> bool:
        try:
            from src.gateway.permission import PermissionService
            return bool(PermissionService().is_admin(user_id))
        except Exception:
            return False

    @staticmethod
    def _target_user(request: Any) -> Optional[str]:
        """返回可访问目标用户（admin 可按 query.user_id 指定，否则=自己）；无权限 None"""
        req_user = FileHandler._req_user(request)
        query = getattr(request, "query_params", {}) or {}
        target = str(query.get("user_id") or req_user)
        if target != req_user and not FileHandler._is_admin(req_user):
            return None
        return target

    # ────────────────────────────── 上传 ──────────────────────────────

    @staticmethod
    async def upload(request: Any) -> Dict[str, Any]:
        """POST /api/files — multipart/form-data 上传（field: session_id / file）

        也可用 JSON body（{session_id, filename, content_base64}）兼容便捷调用。
        """
        try:
            cfg = _cfg()
            user_id = FileHandler._req_user(request)
            session_id = ""
            filename = ""
            raw: bytes = b""

            content_type = (getattr(request, "headers", {}) or {}).get("content-type", "")
            if content_type.lower().startswith("multipart/form-data"):
                from src.files.multipart import parse_multipart_form
                parsed = parse_multipart_form(request.body or b"", content_type)
                session_id = str((parsed.get("fields") or {}).get("session_id") or "")
                if not parsed.get("files"):
                    return {"success": False, "error": "缺少文件字段 file"}
                fpart = parsed["files"][0]
                filename = fpart.filename
                raw = fpart.content
            else:
                body = await request.json()
                session_id = str(body.get("session_id") or "")
                filename = str(body.get("filename") or "")
                b64 = body.get("content_base64")
                if b64:
                    raw = base64.b64decode(b64, validate=False)
                elif body.get("content") is not None:
                    raw = str(body["content"]).encode("utf-8")
                else:
                    return {"success": False, "error": "缺少文件内容（content_base64 或 content）"}

            if not session_id:
                return {"success": False, "error": "缺少 session_id（附件与会话绑定）"}

            from src.files.registry import list_by_session
            existing = list_by_session(session_id, user_id=user_id)
            max_files = int(cfg.get("max_files_per_session", 5))
            if len(existing) >= max_files:
                return {"success": False, "error": f"会话附件已达上限（{max_files} 个），请先删除再上传"}

            max_mb = float(cfg.get("max_file_size_mb", 10))
            if len(raw) > max_mb * 1024 * 1024:
                return {"success": False, "error": f"文件超过大小上限 {max_mb:.0f}MB"}

            ext = Path(filename).suffix.lower()
            allowed = set(cfg.get("allowed_extensions", [".txt", ".md", ".log", ".csv", ".xlsx"]))
            if ext not in allowed:
                return {"success": False, "error": f"不支持的文件类型（允许 {sorted(allowed)}）"}

            from src.files.service import FileService
            record = FileService.store_upload(session_id, user_id, filename, raw, cfg)
            logger.info(f"[FileHandler] 上传成功: {record.get('file_id')} <- {record.get('filename')} ({record.get('size')}B)")
            return {
                "success": True,
                "data": {
                    "file_id": record["file_id"],
                    "filename": record["filename"],
                    "size": record["size"],
                    "type": ext,
                    "created_at": record.get("created_at", ""),
                },
            }
        except Exception as e:
            logger.warning(f"[FileHandler] 上传失败: {e}")
            return {"success": False, "error": f"上传失败: {e}"}

    # ────────────────────────────── 列表 ──────────────────────────────

    @staticmethod
    async def list_files(request: Any) -> Dict[str, Any]:
        """GET /api/files?session_id= — 列某会话的 active 附件（admin 可 ?user_id= 查他人）"""
        try:
            req_user = FileHandler._req_user(request)
            query = getattr(request, "query_params", {}) or {}
            session_id = str(query.get("session_id") or "")
            if not session_id:
                return {"success": False, "error": "缺少查询参数 session_id"}

            # admin 可按 user_id 指定他人；普通用户固定自己
            owner = req_user
            if str(query.get("user_id") or "") and FileHandler._is_admin(req_user):
                owner = str(query["user_id"])

            from src.files.registry import list_by_session
            files = list_by_session(session_id, user_id=owner)
            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "files": [{
                        "file_id": f["file_id"],
                        "filename": f["filename"],
                        "size": f["size"],
                        "type": Path(f.get("filename", "")).suffix.lower(),
                        "created_at": f.get("created_at", ""),
                    } for f in files],
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ────────────────────────────── 删除 ──────────────────────────────

    @staticmethod
    async def delete(request: Any, file_id: str = "") -> Dict[str, Any]:
        """DELETE /api/files/{file_id} — 彻底删除（owner 或 admin）

        删落盘原文件 + 注册表 status=deleted；之后对话引用不再注入。
        """
        try:
            if not file_id:
                return {"success": False, "error": "缺少 file_id"}
            req_user = FileHandler._req_user(request)

            from src.files.registry import get, mark_deleted
            rec = get(file_id)
            if rec is None:
                return {"success": False, "error": "文件不存在"}
            if rec.get("user_id") != req_user and not FileHandler._is_admin(req_user):
                return {"success": False, "error": "无权限删除他人的文件"}

            # 删落盘
            storage = rec.get("storage")
            if storage:
                try:
                    p = Path(storage)
                    if p.exists():
                        p.unlink()
                except Exception as e:
                    logger.warning(f"[FileHandler] 删除落盘失败 {storage}: {e}")
            mark_deleted(file_id)
            logger.info(f"[FileHandler] 删除附件: {file_id} ({rec.get('filename')})")
            return {"success": True, "message": f"文件已删除: {rec.get('filename')}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ────────────────────────────── 下载 ──────────────────────────────

    @staticmethod
    async def download(request: Any, file_id: str = "") -> Dict[str, Any]:
        """GET /api/files/{file_id}/download — 返回 base64 + 元信息（前端拼 data URL 展示/下载）"""
        try:
            if not file_id:
                return {"success": False, "error": "缺少 file_id"}
            req_user = FileHandler._req_user(request)

            from src.files.registry import get
            rec = get(file_id)
            if rec is None or rec.get("status") != "active":
                return {"success": False, "error": "文件不存在"}
            if rec.get("user_id") != req_user and not FileHandler._is_admin(req_user):
                return {"success": False, "error": "无权限查看他人的文件"}

            storage = rec.get("storage")
            if not storage or not Path(storage).exists():
                return {"success": False, "error": "文件已从磁盘移除"}

            raw = Path(storage).read_bytes()
            filename = rec.get("filename", "file")
            ext = Path(filename).suffix.lower()
            ctype = _MIME_OVERRIDES.get(ext) \
                or mimetypes.guess_type(filename)[0] \
                or "application/octet-stream"
            return {
                "success": True,
                "data": {
                    "file_id": file_id,
                    "filename": filename,
                    "content_type": ctype,
                    "size": len(raw),
                    "content_base64": base64.b64encode(raw).decode("ascii"),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
