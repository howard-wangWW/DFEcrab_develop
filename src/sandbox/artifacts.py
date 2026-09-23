# -*- coding: utf-8 -*-
"""执行产物识别与登记（B 类产物回传）。

对齐 LibreChat 只读参照 local-code-api/server.py 的产物口径：
  - 执行前后对工作区做快照 diff，只认"新增或内容变化"的普通文件
  - 跳过隐藏文件/隐藏目录（路径任一段以 "." 开头）
  - 超过单文件上限的跳过（对齐 LOCAL_CODE_API_MAX_FILE）
  - 产物对外名称用相对工作区的路径（对齐 display_name = relative_to(workspace)）

DFEcrab 侧落点差异（无容器形态的必要适配）：
  - LibreChat 把产物登记进沙箱自己的 state（file_id + /files 接口），再由内核转成会话文件；
    本实现直接写 DFEcrab 附件注册表（src/files/registry.register），复用已有的
    GET /api/files/{file_id}/download（前端拼 data URL 展示/下载），不新增下载通道。
  - 产物归属会话由 sandbox.artifact_session_scope 决定：默认 session，即**登记回真实会话**，
    于是 GET /api/files?session_id= 能列出产物（前端文件列表可见、可下载）；
    summary_cache 置空串，故不会被 build_session_context 注入上下文（该方法只拼装
    非空 summary_cache 的记录）。需要不占配额时改为 isolated。
"""
from __future__ import annotations

import logging
import mimetypes
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_MIME_OVERRIDES = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".cjs": "application/javascript",
    ".ts": "application/typescript",
    ".tsx": "application/typescript",
    ".jsx": "application/javascript",
    ".py": "text/x-python",
    ".sh": "application/x-sh",
    ".toml": "text/toml",
    ".ini": "text/ini",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".parquet": "application/vnd.apache.parquet",
}


def guess_mime(filename: str) -> str:
    """产物 MIME：先查显式表，再退回系统 mime 库。

    显式表存在的理由：mimetypes 依赖宿主注册表（同一 .csv 在 Windows 上是
    application/vnd.ms-excel），不显式指定会导致不同机器给出不同结果。
    """
    ext = Path(filename).suffix.lower()
    return _MIME_OVERRIDES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def snapshot(root: Path) -> Dict[str, Tuple[int, float]]:
    """工作区快照：{相对路径: (size, mtime)}。目录不存在返回空。"""
    out: Dict[str, Tuple[int, float]] = {}
    root = Path(root)
    if not root.exists():
        return out
    try:
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(root).as_posix()
            except Exception:
                continue
            if _is_hidden(rel):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            out[rel] = (st.st_size, round(st.st_mtime, 3))
    except Exception as e:
        logger.debug(f"[Sandbox] 快照失败 {root}: {e}")
    return out


def _is_hidden(rel_posix: str) -> bool:
    return any(part.startswith(".") for part in rel_posix.split("/") if part)


def detect_outputs(
    root: Path,
    before: Dict[str, Tuple[int, float]],
    after: Dict[str, Tuple[int, float]],
    max_bytes: int,
) -> List[Path]:
    """新增或变化的文件（按相对路径排序，保证结果稳定）。"""
    root = Path(root)
    changed: List[Path] = []
    for rel, sig in sorted(after.items()):
        if before.get(rel) == sig:
            continue
        p = root / rel
        try:
            if not p.is_file() or p.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        changed.append(p)
    return changed


def register_outputs(
    *,
    session_id: str,
    user_id: str,
    files: List[Path],
    workspace: Path,
    dest_dir: Path,
    allowed_extensions: List[str],
) -> List[Dict[str, Any]]:
    """把工作区产物登记为可下载附件，返回下载描述列表。

    Returns:
        [{"filename", "file_id", "size", "mime", "download_url", "sandbox_path", "session_id"}]
    """
    from src.files.registry import new_file_id, register

    workspace = Path(workspace)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    allowed = {str(e).lower() for e in (allowed_extensions or [])}

    registered: List[Dict[str, Any]] = []
    for src in files:
        try:
            rel = src.relative_to(workspace).as_posix()
        except Exception:
            rel = src.name
        if _is_hidden(rel):
            continue
        ext = Path(rel).suffix.lower()
        if allowed and ext not in allowed:
            logger.info(f"[Sandbox] 产物扩展名不在白名单，跳过登记: {rel}")
            continue

        fid = new_file_id()
        safe_name = Path(rel).name or "artifact"
        dest = dest_dir / f"{fid}_{safe_name}"
        try:
            shutil.copy2(src, dest)
        except Exception as e:
            logger.warning(f"[Sandbox] 产物落盘失败 {rel}: {e}")
            continue

        size = 0
        try:
            size = dest.stat().st_size
        except OSError:
            pass

        try:
            record = register({
                "file_id": fid,
                "session_id": _artifact_session(session_id),
                "user_id": user_id,
                "filename": safe_name,
                "size": size,
                # 与 FileService.store_upload 的写法保持一致（扩展名小写、含点），
                # 供前端文件列表与 _attachment_meta 直接取用，避免记录里出现空 type
                "type": Path(safe_name).suffix.lower(),
                "storage": str(dest),
                # 产物不进附件摘要注入：不绑 message_id（message 级注入取不到该记录），
                # 且摘要留空（session 级回退路径也不拼装该记录）
                "summary_cache": "",
            })
        except Exception as e:
            logger.warning(f"[Sandbox] 产物登记失败 {rel}: {e}")
            continue

        registered.append({
            "filename": str(record.get("filename") or safe_name),
            "file_id": str(record.get("file_id") or fid),
            "size": int(record.get("size") or size),
            "mime": guess_mime(safe_name),
            "download_url": f"/api/files/{record.get('file_id') or fid}/download",
            "sandbox_path": f"/mnt/data/{rel}",
            "session_id": str(record.get("session_id") or ""),
        })
    return registered


def _artifact_session(session_id: str) -> str:
    from .paths import artifact_session_id
    return artifact_session_id(session_id)
