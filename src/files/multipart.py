# -*- coding: utf-8 -*-
"""
multipart.py - multipart/form-data 解析（批次12 文件上传用，零第三方依赖）

自研 HTTP server（src/gateway/http/server.py）不依赖 aiohttp 等框架，
request.body 已是原始 bytes。此处用标准库手动按 boundary 切分表单，
产出 { fields: {表单字段}, files: [{ filename, content }] }。

对齐 LibreChat local-code-api（其用标准库 cgi.FieldStorage；Python 3.13 已
移除 cgi 模块，故自研轻量实现，行为等价：大小/文件名校验交由调用方）。
"""
from __future__ import annotations

import re
from typing import Dict, List


class MultipartPart:
    """一个文件 part"""
    __slots__ = ("field", "filename", "content")

    def __init__(self, field: str, filename: str, content: bytes):
        self.field = field
        self.filename = filename
        self.content = content


def parse_multipart_form(body: bytes, content_type: str) -> Dict:
    """解析 multipart/form-data body。

    Args:
        body: HTTP 请求原始 body（bytes）
        content_type: Content-Type 头（须含 boundary）

    Returns:
        {"fields": {name: str}, "files": [MultipartPart, ...]}

    Raises:
        ValueError: content_type 非 multipart 或缺 boundary / body 无法解析
    """
    if not content_type or not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Content-Type must be multipart/form-data")
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type)
    if not m:
        raise ValueError("missing boundary in Content-Type")
    boundary = (m.group(1) or m.group(2)).strip().encode("utf-8")

    if not body:
        return {"fields": {}, "files": []}

    fields: Dict[str, str] = {}
    files: List[MultipartPart] = []
    # 按 boundary 切块；首尾块为 "--boundary" 开闭标记
    raw_parts = body.split(b"--" + boundary)
    for raw in raw_parts:
        # 仅剥去 MIME 分隔产生的前/后各一处 CRLF，保留 payload 本体（含内部换行）
        if raw.startswith(b"\r\n"):
            raw = raw[2:]
        elif raw.startswith(b"\n"):
            raw = raw[1:]
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        if not raw or raw == b"--":
            continue
        header_end = raw.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        head = raw[:header_end].decode("utf-8", errors="replace")
        payload = raw[header_end + 4:]

        disp = re.search(
            r'Content-Disposition:\s*form-data;\s*name="([^"]*)"(?:;\s*filename="([^"]*)")?',
            head,
        )
        if not disp:
            continue
        name = disp.group(1) or ""
        filename = disp.group(2)
        if filename is None:
            # 普通表单字段
            fields[name] = payload.decode("utf-8", errors="replace")
        else:
            files.append(MultipartPart(field=name, filename=filename, content=payload))

    return {"fields": fields, "files": files}
