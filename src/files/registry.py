# -*- coding: utf-8 -*-
"""
registry.py - 会话附件注册表（批次12：文件实体化生命周期）

以会话为单位的附件注册表，单 JSON 文件落盘（原子写：临时文件 + 替换），
避免阶段1 的"无状态内联/孤儿文件无人清"问题。

数据模型（data/files/registry.json）：
  {"files": {file_id: {
      file_id, session_id, user_id, filename, size, storage,
      summary_cache, created_at, status("active"/"deleted")
  }}}

要点：
  - file_id: f_ + uuid4().hex[:8]
  - 会话级生命周期：删除会话 → 该会话文件整体清理（调用方 rmtree storage_dir 即可）
  - 归属校验：owner/admin 语义由调用方（FileHandler）基于 user_id 判定
  - 原子写：写临时文件后 replace，防崩溃写坏
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = None  # 延迟赋值，避免 import 时强依赖 logging 结构


def _log():
    global logger
    if logger is None:
        import logging
        logger = logging.getLogger("dfecrab.files.registry")
    return logger


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _default_storage_dir() -> Path:
    """附件实体根目录（会话分桶）。可被 _configure() 覆盖（测试/多现场）。"""
    return _PROJECT_ROOT / "data" / "files"


# 运行期可配置（测试用 / 多现场指向独立盘）
_STORAGE_DIR: Path = _default_storage_dir()
_REGISTRY_PATH: Path = _STORAGE_DIR / "registry.json"

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def _configure(storage_dir: Path, registry_path: Optional[Path] = None) -> None:
    """测试/部署覆盖存储根目录（生产不调用）。"""
    global _STORAGE_DIR, _REGISTRY_PATH, _cache
    _STORAGE_DIR = Path(storage_dir)
    _REGISTRY_PATH = registry_path or (_STORAGE_DIR / "registry.json")
    _cache = None


def _load() -> Dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        if _REGISTRY_PATH.exists():
            _cache = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        else:
            _cache = {"files": {}}
    except Exception as e:
        _log().warning(f"[Registry] 注册表读取失败，按空初始化: {e}")
        _cache = {"files": {}}
    return _cache


def _save() -> None:
    data = _load()
    _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _REGISTRY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_REGISTRY_PATH)  # 原子替换


# ────────────────────────────── 核心操作 ──────────────────────────────

def new_file_id() -> str:
    return f"f_{uuid.uuid4().hex[:8]}"


def session_storage_dir(session_id: str) -> Path:
    """某会话的附件落盘目录（data/files/{session_id}/）。"""
    safe = "".join(c for c in str(session_id or "no_session") if c.isalnum() or c in "-_") or "no_session"
    return _STORAGE_DIR / safe


def register(meta: Dict[str, Any]) -> Dict[str, Any]:
    """登记一个文件；返回含 file_id 的完整记录。"""
    with _lock:
        data = _load()
        fid = meta.get("file_id") or new_file_id()
        record = {
            "file_id": fid,
            "session_id": meta.get("session_id", ""),
            "user_id": meta.get("user_id", "default"),
            "filename": meta.get("filename", ""),
            "size": int(meta.get("size") or 0),
            "storage": meta.get("storage", ""),
            "summary_cache": meta.get("summary_cache", ""),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": meta.get("status", "active"),
        }
        data["files"][fid] = record
        _save()
        return record


def get(file_id: str) -> Optional[Dict[str, Any]]:
    return _load().get("files", {}).get(file_id)


def list_by_session(session_id: str, user_id: str = "", include_deleted: bool = False) -> List[Dict[str, Any]]:
    """列某会话的附件。

    Args:
        session_id: 目标会话
        user_id: 为空不过滤归属；否则仅返回该用户（供 owner 语义校验）
        include_deleted: 是否包含已删除记录（默认只返回 active）
    """
    out = []
    for rec in _load().get("files", {}).values():
        if rec.get("session_id") != session_id:
            continue
        if user_id and rec.get("user_id") != user_id:
            continue
        if not include_deleted and rec.get("status") != "active":
            continue
        out.append(rec)
    return out


def list_by_user(user_id: str) -> List[Dict[str, Any]]:
    return [r for r in _load().get("files", {}).values()
            if r.get("user_id") == user_id and r.get("status") == "active"]


def mark_deleted(file_id: str) -> Optional[Dict[str, Any]]:
    """软删除（保留记录供审计/防复活）；返回更新后的记录。"""
    with _lock:
        data = _load()
        rec = data.get("files", {}).get(file_id)
        if rec is None:
            return None
        rec["status"] = "deleted"
        _save()
        return rec


def delete_record(file_id: str) -> bool:
    """物理移除注册记录（删除会话联动 / 清理孤儿时用）。"""
    with _lock:
        data = _load()
        if file_id in data.get("files", {}):
            del data["files"][file_id]
            _save()
            return True
        return False


def remove_by_session(session_id: str) -> int:
    """删除会话联动：物理移除该会话全部注册记录，返回删除条数。"""
    with _lock:
        data = _load()
        files = data.get("files", {})
        removed = [k for k, r in files.items() if r.get("session_id") == session_id]
        for k in removed:
            del files[k]
        _save()
    return len(removed)


def cleanup_orphans(ttl_days: int = 30) -> Dict[str, Any]:
    """孤儿清理：status=deleted 的记录、超期记录、落盘存在但注册表无记录的文件。

    Returns:
        {"removed_records": int, "removed_files": int, "skipped_session_dirs": int}
    """
    with _lock:
        data = _load()
        files = data.get("files", {})
        now_ts = datetime.now(timezone.utc)
        removed_records = 0
        removed_files = 0

        def _expired(rec: Dict[str, Any]) -> bool:
            try:
                dt = datetime.fromisoformat(str(rec.get("created_at", "")))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (now_ts - dt).days > ttl_days
            except Exception:
                return False

        # 1) deleted 或超期记录：删记录 + 删落盘文件
        for fid, rec in list(files.items()):
            if rec.get("status") == "deleted" or _expired(rec):
                storage = rec.get("storage")
                if storage:
                    try:
                        p = Path(storage)
                        if p.exists():
                            p.unlink()
                            removed_files += 1
                    except Exception:
                        pass
                del files[fid]
                removed_records += 1

        # 2) 落盘会话目录里存在但注册表无记录/已删的文件（写注册表失败等孤儿）
        if _STORAGE_DIR.exists():
            for sess_dir in _STORAGE_DIR.iterdir():
                if not sess_dir.is_dir() or sess_dir.name == "registry.json" \
                        or sess_dir.name.startswith("."):
                    continue
                known_paths = {r.get("storage") for r in files.values()
                               if r.get("storage", "").startswith(str(sess_dir))}
                for f in sess_dir.glob("*"):
                    if f.is_file() and str(f) not in known_paths:
                        try:
                            f.unlink()
                            removed_files += 1
                        except Exception:
                            pass
        _save()
    return {"removed_records": removed_records, "removed_files": removed_files}
