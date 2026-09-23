# -*- coding: utf-8 -*-
"""沙箱路径解析与安全检查。

三类目录（互不重叠）：
  1) 工作区   data/sandbox/{session_id}/        —— 代码执行的 cwd，可读写
  2) 会话附件 data/files/{session_id}/          —— 用户上传的原文件，只读基准
  3) 产物落盘 data/files/{产物归属会话}/         —— 归属由 artifact_session_scope 决定

产物落盘的会话归属由 sandbox.artifact_session_scope 决定（默认 session）：
  - session  ：产物登记回真实会话 → GET /api/files?session_id= 可列出 → 前端文件列表
              里直接可见、可下载；summary_cache 为空串，build_session_context 不会注入
              （该方法只拼装 summary_cache 非空的记录），token 面零影响。
              代价：占用 file_upload.max_files_per_session 配额。
  - isolated ：登记到 {sid}__artifacts → 不占配额、不进文件列表，仅能凭 file_id 下载
              （/api/files/{file_id}/download 只按 file_id 取记录与 storage，与会话无关）。
路径入参兼容：
  - "/mnt/data/xxx"      → 工作区相对路径（对齐 read_file / bash_tool 的路径习惯）
  - 绝对路径             → 必须落在工作区内，否则拒绝
  - 相对路径             → 相对工作区解析
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 代码执行工具对外暴露的路径前缀（对齐 LibreChat 的沙箱路径习惯，便于模型复用同一套路径直觉）
SANDBOX_PREFIX = "/mnt/data"

ARTIFACT_SESSION_SUFFIX = "__artifacts"


def project_root() -> Path:
    return _PROJECT_ROOT


def workspace_root() -> Path:
    from .config import sandbox_cfg
    raw = str(sandbox_cfg().get("workspace_root") or "data/sandbox")
    p = Path(raw)
    return p if p.is_absolute() else (_PROJECT_ROOT / p)


def runtime_dir() -> Optional[Path]:
    """沙箱子进程的运行时支撑目录（内含 matplotlibrc 与 sitecustomize.py）。

    等价于 LibreChat 沙箱镜像里的 /app：给子进程提供 MATPLOTLIBRC 与 PYTHONPATH，
    让中文图表字体族与标签中文化生效。目录由本移植包随盘安装，可被
    sandbox.runtime_dir 覆盖；配置为空或目录不存在时返回 None（调用方不注入这两个变量）。
    """
    from .config import sandbox_cfg
    raw = str(sandbox_cfg().get("runtime_dir") or "").strip()
    if not raw:
        return None
    p = Path(raw)
    p = p if p.is_absolute() else (_PROJECT_ROOT / p)
    return p if p.is_dir() else None


def _safe_seg(value: str, fallback: str = "no_session") -> str:
    """会话标识 → 目录安全段（与 src/files/registry.session_storage_dir 同规则）。"""
    s = "".join(c for c in str(value or "") if c.isalnum() or c in "-_")
    return s or fallback


def workspace_dir(session_id: str) -> Path:
    """会话工作区目录（代码执行 cwd）。"""
    return workspace_root() / _safe_seg(session_id)


def attachments_dir(session_id: str) -> Path:
    """会话上传附件目录（复用附件注册表的落盘规则，保证同源）。"""
    from src.files.registry import session_storage_dir
    return session_storage_dir(session_id)


def artifact_scope() -> str:
    """产物会话归属：session（默认）或 isolated。"""
    try:
        from .config import sandbox_cfg
        raw = str(sandbox_cfg().get("artifact_session_scope") or "session").strip().lower()
    except Exception:
        raw = "session"
    return raw if raw in ("session", "isolated") else "session"


def artifact_session_id(session_id: str) -> str:
    """产物的注册表 session 命名空间（由 sandbox.artifact_session_scope 决定）。

    session  ：回到真实会话命名空间 → GET /api/files?session_id= 能列出产物，
               前端文件列表可见、可下载；摘要缓存为空串故不会被注入上下文。
    isolated ：独立命名空间 {sid}__artifacts → 不占配额、不进文件列表，
               只能凭工具返回的 file_id 走 /api/files/{file_id}/download 下载。
    """
    sid = _safe_seg(session_id)
    return f"{sid}{ARTIFACT_SESSION_SUFFIX}" if artifact_scope() == "isolated" else sid


def artifact_dir(session_id: str) -> Path:
    """产物落盘目录（在 data/files 下，与附件同级，便于统一清理）。"""
    return attachments_dir(artifact_session_id(session_id))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def within(base: Path, target: Path) -> bool:
    """target 是否落在 base 内（真实路径比较，防符号链接逃逸）。"""
    try:
        b = base.resolve()
        t = target.resolve()
    except Exception:
        return False
    return t == b or b in t.parents


def resolve_workspace_path(session_id: str, raw_path: str) -> Path:
    """把模型给的路径解析到工作区内；越界抛 ValueError。"""
    ws = ensure_dir(workspace_dir(session_id))
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("path 不能为空")

    if raw.startswith(SANDBOX_PREFIX):
        rel = raw[len(SANDBOX_PREFIX):].lstrip("/\\")
        target = ws / rel
    else:
        p = Path(raw)
        target = p if p.is_absolute() else (ws / raw)

    if not within(ws, target):
        raise ValueError(f"路径超出本次会话的工作区: {raw_path}")
    return target


def to_sandbox_path(session_id: str, path: Path) -> str:
    """工作区内的绝对路径 → 模型侧路径（/mnt/data/...）。"""
    ws = workspace_dir(session_id)
    try:
        rel = path.resolve().relative_to(ws.resolve()).as_posix()
    except Exception:
        return str(path)
    return f"{SANDBOX_PREFIX}/{rel}" if rel and rel != "." else SANDBOX_PREFIX


# ── /mnt/data 等价映射 ──────────────────────────────────────────────────────
# LibreChat 在容器里 /mnt/data 是真实挂载点，模型写 `/mnt/data/x.csv` 天然成立。
# DFEcrab 无容器，工作区实际落在 data/sandbox/{sid}/，该绝对路径不存在 → 重定向失败、
# 产物拿不到。故在执行前后做一次双向文本映射（不改运行方式、不需特权、不跨会话共享）：
#   执行前：命令里的 "/mnt/data" → 本次会话工作区真实绝对路径
#   执行后：stdout/stderr 里的真实路径 → "/mnt/data"（模型看到的路径与契约一致）
# 替换发生在命令字符串层面，替换结果不参与任何求值。
def _real_path_forms(ws: Path) -> List[str]:
    """工作区绝对路径的等价书写形式（长串优先，避免前缀互相截断）。"""
    try:
        resolved = ws.resolve()
    except Exception:
        resolved = ws
    s = str(resolved)
    forms = {s, s.replace("\\", "/")}
    m = re.match(r"^([A-Za-z]):[/\\](.*)$", s)
    if m:  # Windows Git Bash 形式：C:/x/y → /c/x/y
        forms.add(f"/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}")
    forms.discard("")
    return sorted(forms, key=len, reverse=True)


def _command_path_form(ws: Path) -> str:
    """命令里使用的路径写法：一律正斜杠（Linux 原生即此形态；Windows 下 bash 同样接受）。"""
    try:
        s = str(ws.resolve())
    except Exception:
        s = str(ws)
    return s.replace("\\", "/")


def realize(text: str, session_id: str) -> str:
    """命令侧："/mnt/data" → 本次会话工作区真实绝对路径（正斜杠形态）。"""
    if not text or SANDBOX_PREFIX not in text:
        return text
    return text.replace(SANDBOX_PREFIX, _command_path_form(workspace_dir(session_id)))


def virtualize(text: str, session_id: str) -> str:
    """输出侧：工作区真实绝对路径 → "/mnt/data"（模型侧路径直觉保持一致）。"""
    if not text:
        return text
    for form in _real_path_forms(workspace_dir(session_id)):
        if form in text:
            text = text.replace(form, SANDBOX_PREFIX)
    return text


def find_attachment(session_id: str, name_or_id: str) -> Optional[Path]:
    """按 file_id 或文件名定位当前会话的 active 附件实体路径。

    只做精确匹配（文件名全等 → 大小写不敏感全等 → 尾部 _文件名 匹配），
    不做递归搜索（对齐 read_file 的"读已知路径、不做 ls/find"语义）。
    """
    from src.files.registry import get, list_by_session

    key = str(name_or_id or "").strip()
    if not key:
        return None

    # 1) 直接按 file_id
    rec = get(key)
    if rec and rec.get("status") == "active":
        p = Path(str(rec.get("storage") or ""))
        if p.is_file():
            return p

    base = attachments_dir(session_id)
    if not base.exists():
        return None

    try:
        files = list_by_session(session_id)
    except Exception:
        files = []

    # 2) 注册表内按文件名精确匹配
    for rec in files:
        fn = str(rec.get("filename") or "")
        if fn == key or fn.lower() == key.lower():
            p = Path(str(rec.get("storage") or ""))
            if p.is_file():
                return p

    # 3) 落盘名形如 "{file_id}_{原名}"，做尾部匹配
    key_l = key.lower()
    for p in base.glob("*"):
        if not p.is_file():
            continue
        n = p.name
        if n.lower() == key_l or n.lower().endswith("_" + key_l):
            return p

    # 4) 最后一层：工作区里同名的副本（可能已被前一次执行写入）
    ws_copy = workspace_dir(session_id) / key
    if ws_copy.is_file() and within(workspace_dir(session_id), ws_copy):
        return ws_copy
    return None


def stage_attachments(session_id: str) -> list:
    """把会话 active 附件同步进工作区（只新增/更新副本，不动原件）。

    对齐 LibreChat 的 files 引用 staging 语义：执行前让工作区能看到上传文件，
    执行后原件不受任何影响（回滚面为零）。
    """
    import shutil

    staged = []
    base = attachments_dir(session_id)
    if not base.exists():
        return staged
    ws = ensure_dir(workspace_dir(session_id))

    try:
        recs = list(list_by_session_safe(session_id))
    except Exception:
        recs = []

    for rec in recs:
        src = Path(str(rec.get("storage") or ""))
        if not src.is_file():
            continue
        name = Path(str(rec.get("filename") or src.name)).name
        if not name:
            continue
        dst = ws / name
        if not within(ws, dst):
            continue
        try:
            if dst.exists() and dst.stat().st_size == src.stat().st_size:
                continue
            shutil.copy2(src, dst)
            staged.append(dst)
        except Exception:
            continue
    return staged


def list_by_session_safe(session_id: str):
    from src.files.registry import list_by_session
    return list_by_session(session_id)
