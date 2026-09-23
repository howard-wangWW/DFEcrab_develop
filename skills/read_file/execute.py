# -*- coding: utf-8 -*-
"""read_file —— 读取已知路径的文件（C 类：会话附件 / 沙箱工作区读取）。

行为真源：LibreChat `branding/api-dist/index.cjs` 的 **`handleSandboxFileFallback`**
（这是 DFEcrab 唯一对应的形态：入参是 `/mnt/data/...` 或裸文件名，走沙箱读文件）。
工具名 / 参数名 / responseFormat 仍以容器内 npm 包 `@librechat/agents` 的
`ReadFileToolDefinition` 为准（上线前由 contract_check.sh 现场取回核对）。

逐字对齐的分支语义：
  1) 图片：扩展名 ∈ {.png .jpg .jpeg .webp .bmp .tif .tiff}
     —— **不含 .gif**（.gif 落入二进制黑名单，走 buildBinaryFileError 的图片提示文案）
     —— 该分支**没有自身大小上限**（大小由 OCR 侧限制），成功时直接返回 OCR 文本块，
        成功结果**不带** `File: ...` 头部
  2) 二进制黑名单 BINARY_EXTENSIONS_NEVER_READABLE（约 70 项）→ buildBinaryFileError：
     图片类扩展名（含 .gif/.ico/.heic/.heif/.avif）返回带 `[BLACKXML_OCR 2026.9.17]`
     前缀的中文提示（明令"不要在沙箱查找或安装 tesseract/pytesseract"）；
     其余返回英文通用提示
  3) 读取内容后 looksBinary 兜底：前 8192 个字符内有 NUL → 判二进制并给出提示
  4) 截断：按 **JS 字符串长度（UTF-16 码元数）** 与 MAX_READABLE_BYTES(262144) 比较；
     超限时 **先截断再编号**，然后在末尾追加
     `\\n\\n[truncated at 262144 bytes — use \\`bash_tool\\` (e.g. \\`head -c\\` / \\`tail\\`) to read the rest of "{path}"]`
     —— 注意是"截断 + 提示"，**不是**拒绝返回内容（旧实现写成了拒绝，已纠正）
  5) 行号：`${右对齐行号} | ${行内容}`，行号宽度 = 总行数位数（addLineNumbers）
  6) 成功返回**只有**行号化内容本身，没有任何头部

返回值形态：**始终返回字符串**（成功=内容文本，各种失败=可读的提示文本）。
为什么不用 `{"status": "error"}`：DFEcrab 的 loop.py 对 `status=="error"` 会启动
L1（补默认参数重试）/ L2（换工具）/ L3（弹用户确认）纠错链；而 LibreChat 只是把这段
文本交给模型，由模型自己改用 bash_tool。返回字符串即等价于 LibreChat 的模型可见效果，
且不会多出重试与用户弹窗。

刻意差异（形态适配，非遗漏）：
  - `{skillName}/{filePath}` 技能文件寻址与 `SKILL.md` 直返在 DFEcrab 无对应形态
    （技能即工具），描述中不做无实现的承诺。
  - PDF 在 LibreChat 里可作为 document content 返回；DFEcrab 无该通道，改为提示
    使用 PDF 技能或 bash_tool（描述中如实写明）。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 与 index.cjs 对齐的常量（handlers.ts 区段）─────────────────────────────
MAX_READABLE_BYTES = 262144            # = 256KB；比较与提示文案都用它
MAX_BINARY_BYTES = 5 * 1024 * 1024     # 技能文件路径用；此处仅记录口径，沙箱分支不用

# 走 OCR 的图片扩展名（与 handleSandboxFileFallback 的数组逐字一致，**不含 .gif**）
IMAGE_OCR_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

# 二进制黑名单：命中即不可能作为文本读取（逐字照抄 BINARY_EXTENSIONS_NEVER_READABLE）
BINARY_EXTENSIONS_NEVER_READABLE = frozenset([
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".ico",
    ".heic", ".heif", ".avif", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".lz4", ".zst",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma",
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v",
    ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".a", ".lib", ".bin",
    ".class", ".jar", ".parquet", ".bson", ".db", ".sqlite", ".sqlite3",
    ".pyc", ".pyo", ".wasm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
])

# 命中黑名单时，这些扩展名走"图片"专用中文提示（逐字照抄 IMAGE_EXTENSIONS_FOR_HINT）
IMAGE_EXTENSIONS_FOR_HINT = frozenset([
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif",
    ".ico", ".heic", ".heif", ".avif",
])

_PDF_EXTS = (".pdf",)

_OCR_UNAVAILABLE_HINT = (
    "DFEcrab 说明：可用位置为本会话已上传的附件（按原文件名，如 \"设备台账.csv\"）"
    "或工作区 /mnt/data/ 下的路径；本工具不做目录遍历，路径必须是已知的。"
)


# ── 与 index.cjs 逐字一致的小工具 ──────────────────────────────────────────

def add_line_numbers(content: str) -> str:
    """对齐 addLineNumbers：宽度 = 总行数位数，右对齐 + " | "。"""
    lines = content.split("\n")
    w = len(str(len(lines)))
    return "\n".join(f"{str(i + 1).rjust(w, ' ')} | {l}" for i, l in enumerate(lines))


def lowercase_extension(file_path: str) -> str:
    """对齐 lowercaseExtension：最后一个 "." 必须晚于最后一个路径分隔符。"""
    s = str(file_path or "")
    dot = s.rfind(".")
    slash = max(s.rfind("/"), s.rfind("\\"))
    if dot < 0 or dot < slash:
        return ""
    return s[dot:].lower()


def looks_binary(content: str) -> bool:
    """对齐 looksBinary：前 min(len, 8192) 个字符里存在 NUL 即判二进制。"""
    limit = min(len(content or ""), 8192)
    for i in range(limit):
        if ord(content[i]) == 0:
            return True
    return False


def build_binary_file_error(file_path: str, ext: str) -> str:
    """对齐 buildBinaryFileError（文案逐字一致）。"""
    if ext in IMAGE_EXTENSIONS_FOR_HINT:
        return (
            "[BLACKXML_OCR 2026.9.17] 图片不能作为可编辑文本读取。PNG/JPEG/WebP/BMP/TIFF "
            "请使用 read_file 获取本地OCR文字；其他图片格式请转为PNG重新上传。"
            "不要在沙箱查找或安装tesseract/pytesseract。"
            "视觉模型请直接读取原始图片；看不到图片时明确说明，不能猜测内容。"
        )
    return (
        f'"{file_path}" is a binary file ({ext}) and cannot be read as text by `read_file`. '
        f"Use `bash_tool` to process it (e.g. `file {file_path}` for metadata, "
        f"or a runtime-appropriate command for the format)."
    )


def _js_length(s: str) -> int:
    """JS 字符串长度（UTF-16 码元数）；BMP 字符与 Python len 相同，非 BMP 字符算 2。"""
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in s)


def truncate_like_js(payload: str, limit: int) -> Tuple[str, bool]:
    """对齐 `payload.slice(0, MAX_READABLE_BYTES)`（按 UTF-16 码元数切）。

    与 JS 的唯一差别：不会把代理对切一半（JS 那样会产生孤立代理项，JSON 往返后变成
    替换符）。对 BMP 文本（日志/CSV/中文）两者完全等价。
    """
    if limit <= 0 or len(payload) <= limit:
        # 码点数 ≤ 上限时，UTF-16 长度可能因非 BMP 字符超过上限，故仍需精确判断
        total = 0
        for i, ch in enumerate(payload):
            total += 2 if ord(ch) > 0xFFFF else 1
            if total > limit:
                return payload[:i], True
        return payload, False
    total = 0
    for i, ch in enumerate(payload):
        total += 2 if ord(ch) > 0xFFFF else 1
        if total > limit:
            return payload[:i], True
    return payload, False


def _decode(raw: bytes) -> Optional[str]:
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def _locate(path_arg: str) -> Dict[str, Any]:
    """定位文件：返回 {ok, path, origin} 或 {ok:False, error}。"""
    from src.sandbox import context as ctx
    from src.sandbox import paths

    session_id = ctx.current_session_id()
    raw = str(path_arg or "").strip()
    if not raw:
        return {"ok": False, "error": "path 不能为空"}

    # 1) 工作区路径（含 /mnt/data 前缀）
    if raw.startswith(paths.SANDBOX_PREFIX) or raw.startswith("/") or raw.startswith("./") \
            or ("/" in raw and not raw.startswith("f_")):
        try:
            cand = paths.resolve_workspace_path(session_id, raw)
            if cand.is_file():
                return {"ok": True, "path": cand, "origin": "workspace"}
        except ValueError:
            pass

    # 2) 会话附件（file_id 或文件名）
    att = paths.find_attachment(session_id, raw)
    if att and att.is_file():
        return {"ok": True, "path": att, "origin": "attachment"}

    # 3) 兜底：把入参当工作区内相对路径再试一次
    try:
        cand = paths.resolve_workspace_path(session_id, raw)
        if cand.is_file():
            return {"ok": True, "path": cand, "origin": "workspace"}
    except ValueError:
        pass

    return {"ok": False, "path_arg": raw}


async def _read_image_text(target: Path, display: str) -> str:
    """图片分支：本地 OCR 转写（成功结果**不带** File 头部，与 LibreChat 一致）。"""
    from src.sandbox import ocr as ocr_mod
    from src.sandbox.config import ocr_cfg

    cfg = ocr_cfg()
    if not cfg.get("enabled", True):
        return (
            f'"{display}" 是图片，但本地 OCR 已在 dfecrab.json 的 ocr.enabled 中关闭，'
            "未解析其内容。如需读取图片文字，请开启 OCR 或由视觉模型直接查看原始图片。"
        )
    ok, text = await asyncio.to_thread(ocr_mod.read_image_text, target, image_index=1)
    if ok:
        return text
    # 对齐 handleSandboxFileFallback 的 catch：OCR_SERVICE 兜底文案 + 已试地址
    return (
        "OCR_SERVICE: 本地图片读取或OCR失败，请检查沙箱会话与 blackxml-ocr 服务。"
        "不要在 bash_tool 中寻找或安装OCR程序，也不要声称已经识别图片。\n"
        f"（{text}）"
    )


async def execute(*args, **kwargs) -> str:
    """读取一个已知路径的文件；始终返回给模型看的文本（成功=内容，失败=可读提示）。"""
    from src.sandbox import context as ctx
    from src.sandbox import paths
    from src.sandbox.config import file_read_cfg

    path_arg = kwargs.get("path") or kwargs.get("file") or kwargs.get("filename")
    if path_arg is None and args:
        path_arg = args[0]
    if not isinstance(path_arg, str) or not path_arg.strip():
        return "path 不能为空（请给出要读取的文件名或 /mnt/data/ 下的路径）。"
    path_arg = path_arg.strip()

    cfg = file_read_cfg()
    if not cfg.get("enabled", True):
        return "文件读取已在 dfecrab.json 的 file_read.enabled 中关闭。"

    limit = int(cfg.get("max_read_bytes") or MAX_READABLE_BYTES)

    located = _locate(path_arg)
    if not located.get("ok"):
        # 文案对齐 handleSandboxFileFallback 的 "Failed to read ..."（DFEcrab 补寻址说明）
        return (
            f'Failed to read "{path_arg}" from the code-execution sandbox. '
            f"Try `bash_tool` (e.g. `cat {path_arg}`).\n\n{_OCR_UNAVAILABLE_HINT}"
        )

    target: Path = located["path"]
    origin = located.get("origin")
    session_id = ctx.current_session_id()
    display = paths.to_sandbox_path(session_id, target) if origin == "workspace" else target.name

    ext = lowercase_extension(display)

    # ── ① 图片：本地 OCR（不含 .gif；此分支无自身大小上限）──
    if ext in IMAGE_OCR_EXTS:
        return await _read_image_text(target, display)

    # ── ② 二进制黑名单：直接拒绝并给出正确的替代做法 ──
    if ext in BINARY_EXTENSIONS_NEVER_READABLE:
        return build_binary_file_error(display, ext)

    try:
        raw = target.read_bytes()
    except OSError as e:
        return f"读取失败: {e}（路径 {display}）"

    # ── ③ looksBinary 兜底（扩展名没命中黑名单时的安全网）──
    if b"\x00" in raw[:8192]:
        return (
            f'"{display}" appears to be a binary file and cannot be read as text. '
            f"Use `bash_tool` to process it (e.g. `file {display}` for metadata)."
        )

    text = _decode(raw)
    if text is None:
        return (
            f'"{display}" appears to be a binary file and cannot be read as text. '
            f"Use `bash_tool` to process it (e.g. `file {display}` for metadata)."
        )

    # ── ④ 截断（先截断再编号）+ ⑤ 行号 ──
    payload, truncated = truncate_like_js(text, limit)
    numbered = add_line_numbers(payload)
    if truncated:
        numbered += (
            f'\n\n[truncated at {limit} bytes — use `bash_tool` (e.g. `head -c` / `tail`) '
            f'to read the rest of "{display}"]'
        )
    return numbered


# 技能元数据（名称 / 参数 / responseFormat 对齐 npm 的 ReadFileToolDefinition；
# 行为描述按 DFEcrab 实际生效的沙箱分支改写，不承诺无实现的能力）。
# 文案内联：仓内 loader 用 ast.literal_eval 读取本常量，模块级变量引用会导致解析失败。
SKILL_METADATA = {
    "name": "read_file",
    "version": "1.1.0",
    "description": """Read the contents of a file. Returns text content with line numbers for easy reference.

BEHAVIOR:
- Text files: returned with numbered lines. Content beyond 256KB is truncated and the truncation is stated at the end, together with how to read the rest.
- Images (png, jpg, jpeg, webp, bmp, tif, tiff): text is extracted by the local OCR service and returned as an OCR transcription, clearly marked as OCR output rather than visual understanding. Other image formats are not readable this way.
- PDF/Office/archives and other binary formats: not readable as text; a note explains what to use instead.
- Other binary files: a note explains what to use instead.

CONSTRAINTS:
- Only files from the current session are accessible: files uploaded in this session (by original filename) or files created under the sandbox workspace (`/mnt/data/...`).
- Do not guess file paths. Use paths from the attachment list or tool output.""",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": 'Path to the file: the original filename of a file uploaded in this session (e.g. "设备台账.csv"), or a sandbox workspace path (e.g. "/mnt/data/result.csv").',
            },
        },
        "required": ["path"],
    },
    # 对齐 ReadFileToolDefinition.responseFormat（DFEcrab 无 artifact 通道，仅作契约记录）
    "responseFormat": "content_and_artifact",
}
