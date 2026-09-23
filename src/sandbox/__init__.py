# -*- coding: utf-8 -*-
"""沙箱子系统（B 类：代码执行 / C 类：文件读取）。

对齐来源（LibreChat 侧只读参照，不改动）：
  - 代码执行语义：local-code-api/server.py 的 POST /exec（lang/code/args/session_id/files
    → stdout/stderr/returncode/files）与 local-code-api 的资源限制口径
  - 文件读取语义：容器内 @librechat/agents 的 read_file 工具（已知路径直读、行号输出、
    大文件只回元信息、>256KB 文本 / >10MB 二进制不硬读）
  - 图片读取语义：branding/api-dist/image-ocr.cjs（本地 OCR 端点、行渲染格式、
    文字预算与 <ocr_image_text> 包装文案逐字对齐）

与 LibreChat 的差异（本实现为无容器形态的必要适配）：
  - 无独立沙箱容器，执行落在 DFEcrab 本机子进程（资源限制用 POSIX rlimit 等价实现）
  - 工作区由 /mnt/data 前缀映射到 data/sandbox/{session_id}/（对外路径直觉保持一致）
  - 产物不再经沙箱 /files 接口回拉，而是直接登记进 DFEcrab 附件注册表，复用已有下载路由
  - OCR 服务地址走候选列表探测（容器名在宿主机未必可解析），不再有容器内固定服务名
"""
from .config import file_read_cfg, ocr_cfg, sandbox_cfg
from .context import get_request_context, set_request_context
from .ocr import format_ocr_block, probe as ocr_probe, read_image_text
from .runner import execute_code

__all__ = [
    "sandbox_cfg",
    "file_read_cfg",
    "ocr_cfg",
    "set_request_context",
    "get_request_context",
    "execute_code",
    "read_image_text",
    "format_ocr_block",
    "ocr_probe",
]
