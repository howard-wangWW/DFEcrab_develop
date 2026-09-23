# -*- coding: utf-8 -*-
"""代码执行器（B 类）。

口径对齐 LibreChat 代码沙箱 **实际部署值 + 实际结果加工**：

  常量（docker-compose.yml 的 local-code-api.environment 覆盖 server.py 代码默认值）：
    - 超时 900s（LOCAL_CODE_API_TIMEOUT），超时 kill 整个进程组，返回码 124
    - 输出上限 8388608（LOCAL_CODE_API_MAX_OUTPUT，即 8MB），stdout/stderr 各自独立计算
    - 内存 1536MB / 进程数 64 / 单文件 50MB / 并发 2
    - 语言 py/python/python3（脚本文件 + sys.executable）与 bash/sh（shell -lc）

  结果加工（local-code-api/server.py，模型能看到的最终文本由这里决定）：
    - 截断：`_bounded_text` —— 按 **UTF-8 字节** 计预算，后缀
      b"\\n[output truncated by sandbox]\\n" **计入预算之内**（先扣掉后缀长度再切片）
    - 超时：rc=124，stderr = bounded(f"{stderr}\\nExecution timed out after {N}s.\\n")
    - 非零退出且 stderr 非空：stderr = f"{stderr.rstrip()}\\nProcess exited with code {rc}.\\n"
      （该后缀在 bounded 之后追加，因此**不占**输出预算；超时路径同样会再补这一行）

  子进程环境白名单（server.py 的 _run_code env，一个不多一个不少）：
    HOME / PATH / LANG=C.UTF-8 / LC_ALL=C.UTF-8 / MPLCONFIGDIR /
    MATPLOTLIBRC=<runtime>/matplotlibrc / PYTHONPATH=<runtime> /
    SAL_USE_VCLPLUGIN=svp / SANDBOX_CHART_LANGUAGE=zh-CN / TMPDIR / XDG_CACHE_HOME /
    PYTHONUNBUFFERED=1
    —— 其中 MATPLOTLIBRC 给中文字体族、PYTHONPATH 让 sitecustomize.py 被自动导入做标签
    中文化，两者共同构成"中文图表"的生效链（LibreChat 侧指向镜像内 /app，我们指向
    sandbox.runtime_dir，即随包安装的 data/sandbox_runtime）。

与 local-code-api 的差异（无容器形态的必要适配，非照搬）：
  - 资源限制用 POSIX rlimit 等价实现（容器侧是 cgroup/外部限制）；非 POSIX 平台
    （开发自测）用独立进程组 + taskkill /T 回收进程树，跳过 rlimit。
  - 额外显式设置 MPLBACKEND=Agg 与 PYTHONIOENCODING=utf-8：宿主无显示、且默认 locale
    不保证是 UTF-8，避免无显示环境绘图报错与中文输出乱码（不改变模型可见文本）。

执行后端（路线 C）：
  - `backend="local"`（默认）：本模块直接执行，行为与上面完全一致。
  - `backend="remote"`：整体转发给 `src/sandbox/remote.py`，由 LibreChat 的
    `local-code-api` 容器执行。此时**结果加工已由服务端完成**（`_bounded_text` +
    `do_POST` 的退出码行），本地**不再二次加工**（否则会出现两个 `Process exited` 行）；
    且 `/mnt/data` 是容器真实路径，调用方不应再做 realize/virtualize 映射。
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_POSIX = os.name == "posix"
_IS_WIN = os.name == "nt"

# 输出截断后缀（与 local-code-api/server.py 的 _bounded_text 逐字一致；计入字节预算内）
OUTPUT_TRUNC_SUFFIX = b"\n[output truncated by sandbox]\n"


def _make_preexec(memory_mb: int, processes: int, max_file_bytes: int, timeout_sec: int):
    """POSIX 资源限制（在子进程 exec 前生效）。"""
    if not _POSIX:
        return None

    def _limit() -> None:  # pragma: no cover - 仅子进程内执行
        try:
            import resource

            os.setsid()  # 独立进程组，便于超时按组回收
            if timeout_sec > 0:
                resource.setrlimit(resource.RLIMIT_CPU, (timeout_sec + 1, timeout_sec + 2))
            if memory_mb > 0:
                _b = memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (_b, _b))
            if processes > 0:
                resource.setrlimit(resource.RLIMIT_NPROC, (processes, processes))
            if max_file_bytes > 0:
                resource.setrlimit(resource.RLIMIT_FSIZE, (max_file_bytes, max_file_bytes))
        except Exception:
            # 限制设置失败不阻断执行（对齐 local-code-api 的容错取向）
            pass

    return _limit


def _build_env(workspace: Path, tmp_dir: Path, chart_lang: str,
               runtime_dir: Optional[str] = None) -> Dict[str, str]:
    """子进程环境白名单：只给必需品，宿主密钥类变量一律不透传。

    键集合对齐 local-code-api/server.py 的 env（见模块 docstring）。runtime_dir 有值且
    目录存在时额外注入 MATPLOTLIBRC / PYTHONPATH（中文图表生效链）。
    """
    env = {
        "HOME": str(workspace),
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "TMPDIR": str(tmp_dir),
        "XDG_CACHE_HOME": str(tmp_dir / "cache"),
        "MPLCONFIGDIR": str(tmp_dir / "matplotlib"),
        "MPLBACKEND": "Agg",
        "SAL_USE_VCLPLUGIN": "svp",
        "SANDBOX_CHART_LANGUAGE": str(chart_lang or "zh-CN"),
    }
    if runtime_dir:
        rd = Path(runtime_dir)
        if rd.is_dir():
            env["PYTHONPATH"] = str(rd)
            env["MATPLOTLIBRC"] = str(rd / "matplotlibrc")
    return env


def _bounded_text(text: str, limit: int) -> str:
    """对齐 local-code-api/server.py 的 _bounded_text。

    按 UTF-8 字节计预算；超限时切片长度为 limit - len(后缀)，后缀计入预算之内。
    解码用 errors="replace"（截在字符中间时得到替换符，与 JS 侧行为一致）。
    """
    data = (text or "").encode("utf-8", errors="replace")
    if limit <= 0 or len(data) <= limit:
        return data.decode("utf-8", errors="replace")
    keep = max(0, limit - len(OUTPUT_TRUNC_SUFFIX))
    return (data[:keep] + OUTPUT_TRUNC_SUFFIX).decode("utf-8", errors="replace")


def _finalize(stdout_raw: str, stderr_raw: str, returncode: int,
              max_output_bytes: int) -> Dict[str, str]:
    """执行结果 → 模型可见文本（与 server.py 的加工顺序逐字一致）。"""
    stdout = _bounded_text(stdout_raw, max_output_bytes)
    stderr = _bounded_text(stderr_raw, max_output_bytes)
    if returncode != 0 and stderr:
        stderr = f"{stderr.rstrip()}\nProcess exited with code {returncode}.\n"
    return {"stdout": stdout, "stderr": stderr}


def _decode(raw: Optional[bytes]) -> str:
    """子进程输出解码；优先 UTF-8，其次 GBK/UTF-16，最后替换式解码（不丢内容）。"""
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


def execute_code(
    lang: str,
    code: str,
    *,
    workspace: Path,
    args: Optional[List[str]] = None,
    timeout_sec: int = 900,
    max_memory_mb: int = 1536,
    max_processes: int = 64,
    max_file_bytes: int = 52428800,
    max_output_bytes: int = 8388608,
    allowed_langs: Optional[List[str]] = None,
    chart_lang: str = "zh-CN",
    runtime_dir: Optional[str] = None,
    backend: str = "local",
    session_id: str = "",
) -> Dict[str, Any]:
    """执行代码片段，返回 {stdout, stderr, returncode, timed_out, lang, cwd}。

    backend="remote" 时返回的 stdout/stderr 是**远端服务端加工后的最终文本**
    （截断 + 退出码行 + 超时行），本地不再二次加工。
    """
    lang_norm = str(lang or "").strip().lower()
    langs = [str(x).lower() for x in (allowed_langs or ["py", "python", "python3", "bash", "sh"])]
    workspace = Path(workspace)

    if lang_norm not in langs:
        # 口径同 server.py：rc=2 + 英文错误行，随后同样补 "Process exited with code 2."
        raw_err = (
            f"Unsupported language: {lang}. "
            "This local executor supports py/python and bash/sh.\n"
        )
        out = _finalize("", raw_err, 2, max_output_bytes)
        return {
            "stdout": out["stdout"],
            "stderr": out["stderr"],
            "returncode": 2,
            "timed_out": False,
            "lang": lang_norm,
            "cwd": str(workspace),
        }

    # ── 执行后端分派（路线 C）──────────────────────────────────────────────
    # backend="remote" 时把执行整体交给 LibreChat 的 local-code-api 容器：
    # 执行语义、依赖库、中文图表环境、资源上限、并发闸门与 LibreChat 同一套实现，
    # 不需要在本地复刻。默认 "local" 保持 BC 包原行为完全不变。
    if str(backend or "local").strip().lower() == "remote":
        from . import remote as _remote  # 延迟导入：不用 remote 时不引入该依赖
        return _remote.execute(
            lang_norm,
            code,
            workspace=Path(workspace),
            args=args,
            timeout_sec=timeout_sec,
            max_output_bytes=max_output_bytes,
            session_id=str(session_id or ""),
        )

    workspace.mkdir(parents=True, exist_ok=True)
    args = [str(a) for a in (args or [])]
    tmp_dir = Path(tempfile.mkdtemp(prefix="dfecrab-sandbox-"))

    try:
        if lang_norm in ("py", "python", "python3"):
            script = tmp_dir / "script.py"
            script.write_text(code, encoding="utf-8")
            command = [sys.executable or "python3", str(script), *args]
        else:
            shell = shutil.which("bash") or shutil.which("sh")
            if shell:
                command = [shell, "-lc", code, *args]
            elif platform.system().lower().startswith("win"):
                command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", code]
            else:
                command = ["/bin/sh", "-lc", code, *args]

        preexec = _make_preexec(max_memory_mb, max_processes, max_file_bytes, timeout_sec)
        popen_kwargs: Dict[str, Any] = {}
        if _POSIX:
            # 独立会话：超时时可按进程组整体回收（对齐 local-code-api 的取向）
            popen_kwargs["preexec_fn"] = preexec
            popen_kwargs["start_new_session"] = True
        elif _IS_WIN:
            # Windows 开发自测用：独立进程组，避免子进程信号牵连调用方；
            # 超时时用 taskkill /T 杀整棵进程树（等价于 POSIX 的进程组回收）
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        proc = subprocess.Popen(
            command,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_build_env(workspace, tmp_dir, chart_lang, runtime_dir),
            **popen_kwargs,
        )

        timed_out = False
        try:
            out_b, err_b = proc.communicate(timeout=timeout_sec if timeout_sec > 0 else None)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            if _POSIX:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
            elif _IS_WIN:
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, timeout=10)
                except Exception:
                    pass
                try:
                    proc.kill()
                except Exception:
                    pass
            else:
                proc.kill()
            out_b, err_b = proc.communicate()
            returncode = 124

        stdout_raw = _decode(out_b)
        stderr_raw = _decode(err_b)
        if timed_out:
            # 与 server.py 一致：超时文案**并入** bounded 预算，随后再补 "Process exited"
            stderr_raw = f"{stderr_raw}\nExecution timed out after {timeout_sec}s.\n"

        out = _finalize(stdout_raw, stderr_raw, returncode, max_output_bytes)
        return {
            "stdout": out["stdout"],
            "stderr": out["stderr"],
            "returncode": returncode,
            "timed_out": timed_out,
            "lang": lang_norm,
            "cwd": str(workspace),
        }
    except Exception as e:  # 执行器自身异常也要变成工具可读的错误
        logger.warning(f"[Sandbox] 执行异常: {e}")
        return {
            "stdout": "",
            "stderr": f"执行器异常: {e}",
            "returncode": -1,
            "timed_out": False,
            "lang": lang_norm,
            "cwd": str(workspace),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
