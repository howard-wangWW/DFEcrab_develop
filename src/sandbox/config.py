# -*- coding: utf-8 -*-
"""沙箱与文件读取的配置读取（dfecrab.json 的 sandbox / file_read / ocr 三段）。

默认值口径对齐 LibreChat 侧**实际部署值**。注意取值优先级：
  1) docker-compose.yml 的 local-code-api.environment（这是部署时的真源，会覆盖代码默认值）
  2) local-code-api/server.py 顶部的常量（仅当 compose 未设置时生效）

按此口径的实际部署值（librechat-code-api 容器）：
  LOCAL_CODE_API_TIMEOUT=900        ← compose 显式设置（server.py 默认是 30，被覆盖）
  LOCAL_CODE_API_MAX_OUTPUT=8388608 ← compose 显式设置 8MB（server.py 默认 1MB，被覆盖）
  LOCAL_CODE_API_MAX_MEMORY=1610612736（=1536MB，与 server.py 默认一致）
  LOCAL_CODE_API_MAX_PROCESSES=64 / MAX_FILE=50MB / MAX_CONCURRENT=2
  SUPPORTED_LANGS={py,python,python3,bash,sh}

子进程环境白名单口径（server.py 的 _run_code env）：HOME / PATH / LANG=C.UTF-8 /
LC_ALL=C.UTF-8 / MPLCONFIGDIR / MATPLOTLIBRC=/app/matplotlibrc / PYTHONPATH=/app /
SAL_USE_VCLPLUGIN=svp / SANDBOX_CHART_LANGUAGE=zh-CN / TMPDIR / XDG_CACHE_HOME /
PYTHONUNBUFFERED=1。其中 MATPLOTLIBRC + PYTHONPATH 是中文图表的生效链
（matplotlibrc 给中文字体族，PYTHONPATH 让 sitecustomize.py 被自动导入做标签中文化）。
DFEcrab 侧用 sandbox.runtime_dir 指向自带的等价目录。
"""
from __future__ import annotations

from typing import Any, Dict, List

_DEFAULT_SANDBOX: Dict[str, Any] = {
    "enabled": True,
    # 执行后端（路线 C 的开关）：
    #   local  = DFEcrab 主机子进程执行（= BC 包行为，/mnt/data 走双向等价映射）
    #   remote = 复用 LibreChat 的 local-code-api 容器沙箱（/mnt/data 是容器真实路径，
    #            不做映射；执行环境/依赖库/中文图表/资源上限/并发闸门与 LibreChat
    #            完全同一套实现，因此这部分不会随 LibreChat 升级而漂移）
    # 切换只改这一个键；remote 不可达时工具会明确回报不可达并给出已试地址，
    # 需要降级就把该值改回 "local"。
    "backend": "local",
    # remote 后端的配置。**默认值的唯一真源是 src/sandbox/remote.py 的 _REMOTE_DEFAULTS**，
    # 这里给空 dict 表示"全用默认"；需要覆盖时在 dfecrab.json 的 sandbox.remote 里写同名键：
    #   base_urls            候选地址列表，按序探测 GET {base}/health（期望 200 + {"ok":true}）
    #   discover_container   是否用 docker inspect 自动补容器 IP（默认补）
    #   container            容器名，默认 librechat-code-api
    #   http_timeout_pad_sec HTTP 读超时相对执行超时的余量秒数（远端 900s，读超时须更大）
    #   probe_cache_sec      健康探测结果缓存秒数
    #   busy_retry           服务繁忙（429，服务端 MAX_CONCURRENT=2）的退避重试次数
    #   busy_retry_wait_sec  退避基准等待秒数
    "remote": {},
    "workspace_root": "data/sandbox",
    # 沙箱运行时支撑目录（相对 DFEcrab 根或绝对路径）：内含 matplotlibrc 与
    # sitecustomize.py，等价于 LibreChat 沙箱镜像里的 /app。置空则不注入
    # MATPLOTLIBRC / PYTHONPATH（中文图表不会生效）
    "runtime_dir": "data/sandbox_runtime",
    "timeout_sec": 900,
    "max_memory_mb": 1536,
    "max_processes": 64,
    "max_output_bytes": 8388608,
    "max_artifact_bytes": 52428800,
    "allowed_langs": ["py", "python", "python3", "bash", "sh"],
    "artifact_allowed_extensions": [
        ".xlsx", ".xls", ".docx", ".pptx", ".pdf", ".csv", ".txt", ".md",
        ".json", ".png", ".jpg", ".jpeg", ".svg", ".zip", ".log",
    ],
    "chart_lang": "zh-CN",
    # 产物登记的会话归属：session=进会话文件列表（前端文件列表可见、可按 file_id 下载，
    # 占用 file_upload.max_files_per_session 配额）；isolated=独立命名空间（不占配额，
    # 不进文件列表，仅能凭返回的 file_id 下载）
    "artifact_session_scope": "session",
}

_DEFAULT_FILE_READ: Dict[str, Any] = {
    "enabled": True,
    "max_read_bytes": 262144,
    "allow_attachments": True,
    "allow_workspace": True,
}

_DEFAULT_OCR: Dict[str, Any] = {
    "enabled": True,
    # 候选地址按序探测（健康检查 GET {base}/health），命中即用并缓存
    "base_urls": ["http://blackxml-ocr:8090", "http://127.0.0.1:8090"],
    "timeout_sec": 120,
    "max_lines_chars": 40000,
    "probe_cache_sec": 300,
    # 调 /ocr 前先 GET 一次 /health 预热（对齐 ocr-warmup-hook.cjs 的做法），
    # 消除"后端空闲回收后首次请求未就绪"导致的偶发失败
    "warmup": True,
    "warmup_timeout_sec": 5,
    "retry": 1,
}


def _section(name: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from src.config.app_config import section
        cfg = section(name) or {}
        merged = dict(defaults)
        merged.update({k: v for k, v in cfg.items() if not str(k).startswith("_")})
        return merged
    except Exception:
        return dict(defaults)


def sandbox_cfg() -> Dict[str, Any]:
    """沙箱执行配置（含兜底）。"""
    return _section("sandbox", _DEFAULT_SANDBOX)


def file_read_cfg() -> Dict[str, Any]:
    """文件读取配置（含兜底）。"""
    return _section("file_read", _DEFAULT_FILE_READ)


def ocr_cfg() -> Dict[str, Any]:
    """OCR 配置（含兜底）。"""
    return _section("ocr", _DEFAULT_OCR)


def allowed_langs() -> List[str]:
    return [str(x).lower() for x in (sandbox_cfg().get("allowed_langs") or [])]
