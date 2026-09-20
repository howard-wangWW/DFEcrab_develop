# -*- coding: utf-8 -*-
"""
FileService - 会话附件解析与注入（批次12：文件实体化生命周期）

对齐 LibreChat「先上传原文件，再本地解析，解析文本才进上下文」：
  - 上传即落盘 + 解析一次，摘要缓存进注册表（registry.py）
  - 对话按会话自动注入 active 附件摘要（summary_cache 直取，不重解析）
  - 二进制不进上下文；原文件保留供下载/追溯
  - × 删除 / 删会话 → 由 file_handler / session 联动清 registry + 落盘

阶段2刻意不再支持请求体内联 base64（阶段1 兼容已移除）。
txt/md/log/csv 用标准库；xlsx 需 openpyxl（缺失友好降级）。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _decode_text(raw: bytes) -> str:
    """编码探测：utf-8 → gbk → utf-16 → 兜底 replace（中文现场常见 GBK/UTF-8 混用）。"""
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


# ────────────────────────────── 解析器（上传时执行一次）──────────────────────────────

def _parse_text_file(raw: bytes, max_chars: int) -> Dict[str, Any]:
    """txt/md/log：编码探测 + 受控截断（头尾保留）。"""
    text = _decode_text(raw)
    if len(text) <= max_chars:
        return {"type": "text", "chars": len(text), "content": text}
    head = text[: int(max_chars * 0.7)]
    tail = text[-int(max_chars * 0.25):]
    return {
        "type": "text",
        "chars": len(text),
        "content": f"{head}\n\n…[内容过长已截断，原 {len(text)} 字符，省略中部]…\n\n{tail}",
    }


def _parse_csv_file(raw: bytes, summary_rows: int) -> Dict[str, Any]:
    """csv：列名 + 类型 + 总行数 + 前 N 行（标准库，无 pandas）。"""
    import csv
    import io

    text = _decode_text(raw)
    reader = csv.reader(io.StringIO(text))
    try:
        rows = list(reader)
    except Exception as e:
        return {"type": "csv", "error": f"csv 解析失败: {e}", "total_rows": 0, "columns": []}
    if not rows:
        return {"type": "csv", "error": "空文件", "total_rows": 0, "columns": []}
    header = [c.strip() for c in (rows[0] or [])]
    data_rows = rows[1:]
    total_rows = len(data_rows)
    preview = data_rows[:summary_rows]
    col_types: List[str] = []
    if header:
        for ci in range(len(header)):
            _sample = ""
            for r in preview:
                if ci < len(r) and r[ci].strip():
                    _sample = r[ci].strip()
                    break
            if not _sample:
                col_types.append("?")
            elif re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", _sample):
                col_types.append("number")
            else:
                col_types.append("text")
    return {
        "type": "csv",
        "columns": list(zip(header, col_types)),
        "total_rows": total_rows,
        "preview": preview,
        "truncated": total_rows > len(preview),
    }


def _parse_xlsx_file(path: Path, summary_rows: int, max_sheets: int) -> Dict[str, Any]:
    """xlsx：逐 sheet 摘要（openpyxl；缺失时友好降级）。"""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return {"type": "xlsx", "error": "缺少 openpyxl 依赖，无法解析 xlsx（请 pip install openpyxl）"}
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        return {"type": "xlsx", "error": f"xlsx 打开失败: {e}"}
    sheets = []
    for sheet in wb.sheetnames[:max_sheets]:
        ws = wb[sheet]
        sheet_rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i > summary_rows:
                break
            sheet_rows.append(["" if c is None else str(c) for c in row])
        sheets.append({"name": sheet, "preview": sheet_rows})
    return {"type": "xlsx", "sheets": sheets, "sheet_count": len(wb.sheetnames)}


def parse_file_by_ext(filename: str, raw: bytes, path: Optional[Path] = None,
                      max_text_chars: int = 12000, summary_rows: int = 10,
                      max_xlsx_sheets: int = 10) -> Dict[str, Any]:
    """按扩展名解析原始字节 → 解析结果 dict（供生成 summary_cache）。"""
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md", ".log"):
        return _parse_text_file(raw, max_text_chars)
    if ext == ".csv":
        return _parse_csv_file(raw, summary_rows)
    if ext == ".xlsx":
        return _parse_xlsx_file(path or Path(filename), summary_rows, max_xlsx_sheets)
    # 兜底：按文本尝试
    return {"type": "text", "chars": len(raw), "content": _decode_text(raw)[:8000]}


def render_summary(filename: str, parsed: Dict[str, Any], summary_rows: int = 10) -> str:
    """解析结果 → 注入用的单文件摘要文本（存 summary_cache）。"""
    lines = [f"[附件] {filename}"]
    if parsed.get("error"):
        lines.append(f"（{parsed['error']}）")
        return "\n".join(lines)
    t = parsed.get("type")
    if t == "text":
        lines.append(f"（文本 · {parsed['chars']} 字符）")
        lines.append(parsed["content"])
    elif t == "csv":
        lines.append(f"（CSV · {parsed['total_rows']} 数据行 × {len(parsed['columns'])} 列）")
        cols = " | ".join(f"{c}({ct})" for c, ct in parsed["columns"])
        lines.append(f"列: {cols}")
        lines.append(f"前 {len(parsed['preview'])} 行:")
        for r in parsed["preview"]:
            lines.append(" | ".join(r))
        if parsed.get("truncated"):
            lines.append(f"…（共 {parsed['total_rows']} 行，仅展示前 {len(parsed['preview'])} 行）")
    elif t == "xlsx":
        lines.append(f"（Excel · {parsed['sheet_count']} 个 sheet，仅展示前 {len(parsed['sheets'])} 个）")
        for sh in parsed["sheets"]:
            lines.append(f"## Sheet: {sh['name']}")
            for r in sh["preview"]:
                lines.append(" | ".join(r))
    return "\n".join(lines)


# ────────────────────────────── FileService（上传 / 注入）──────────────────────────────

class FileService:
    """会话附件：上传入库 + 按会话注入上下文。"""

    @staticmethod
    def store_upload(session_id: str, user_id: str, filename: str,
                     raw: bytes, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """上传：校验 → 落盘 → 解析 → 摘要缓存 → 注册。

        Returns:
            registry 记录（含 file_id / summary_cache）
        """
        from .registry import session_storage_dir, register
        cfg = cfg or FileService._cfg()
        safe_name = "".join(c for c in Path(filename).name if c.isalnum() or c in "._- ")[:120].strip()
        if not safe_name:
            safe_name = "file"
        sess_dir = session_storage_dir(session_id)
        sess_dir.mkdir(parents=True, exist_ok=True)
        from .registry import new_file_id
        fid = new_file_id()
        storage = str(sess_dir / f"{fid}_{safe_name}")
        Path(storage).write_bytes(raw)

        parsed = parse_file_by_ext(
            safe_name, raw, Path(storage),
            max_text_chars=cfg.get("max_text_chars", 12000),
            summary_rows=int(cfg.get("summary_rows", 10)),
            max_xlsx_sheets=int(cfg.get("max_xlsx_sheets", 10)),
        )
        summary = render_summary(safe_name, parsed, int(cfg.get("summary_rows", 10)))
        return register({
            "session_id": session_id,
            "user_id": user_id,
            "filename": safe_name,
            "size": len(raw),
            "storage": storage,
            "summary_cache": summary,
        })

    @staticmethod
    def purge_session(session_id: str) -> Dict[str, Any]:
        """删会话联动清理（批次12步骤3）：该会话附件全量下线。

        幂等操作，用于会话被删除/过期时回收附件资源：
          1) 注册表：物理移除该会话全部记录（remove_by_session）
          2) 落盘：rmtree 会话专属目录 data/files/{session_id}/
          3) 注入侧无需额外动作——build_session_context 只查注册表，
             记录没了自然不再注入（叉掉即失效语义的最终形态）

        Returns:
            {"removed_records": int, "removed_path": str|None, "error": str|None}
        """
        import shutil
        from .registry import remove_by_session, session_storage_dir

        try:
            n = remove_by_session(session_id)
        except Exception as e:
            return {"removed_records": 0, "removed_path": None, "error": f"注册表清理失败: {e}"}

        removed_path = None
        try:
            d = session_storage_dir(session_id)
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                removed_path = str(d)
        except Exception as e:
            return {
                "removed_records": n,
                "removed_path": None,
                "error": f"物理目录清理失败: {e}",
            }
        return {"removed_records": n, "removed_path": removed_path, "error": None}

    @staticmethod
    def _cfg() -> Dict[str, Any]:
        try:
            from src.config.app_config import section
            return section("file_upload") or {}
        except Exception:
            return {}

    @staticmethod
    def build_session_context(session_id: str, context_length: int = 32768) -> str:
        """按会话查 active 附件，组合注入块（预算 = 窗口×budget_ratio）。

        Returns:
            str 注入块；无附件返回 ""
        """
        from .registry import list_by_session
        cfg = FileService._cfg()
        files = list_by_session(session_id)
        if not files:
            return ""
        budget_ratio = float(cfg.get("budget_ratio", 0.5) or 0.5)
        budget = max(4000, int(context_length * budget_ratio))
        blocks = [r.get("summary_cache") or f"[附件] {r.get('filename', '')}（无摘要）"
                  for r in files if r.get("summary_cache")]
        block = "\n\n".join(blocks)
        if len(block) > budget:
            block = block[:budget] + "\n\n…[附件内容超预算已截断]…"
        return block
