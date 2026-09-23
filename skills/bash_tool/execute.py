# -*- coding: utf-8 -*-
"""bash_tool —— 会话工作区内执行 shell / Python（B 类：代码执行）。

契约对齐 LibreChat 的运行时真源（容器内 npm 包 @librechat/agents 的
BashExecutionToolDefinition，上线前由 contract_check.sh 现场取回核对）：

  工具名    bash_tool
  参数      command（必填）、args（可选）
  description / 参数描述：见文末 SKILL_METADATA，与 npm 原文逐字对齐
  产物口径  /mnt/data 下的标准扩展名文件自动交付；执行失败不登记新文件

刻意差异（形态适配，不是遗漏）：
  1) 描述中的"Referencing previous tool outputs"（{{tool<idx>turn<turn>}} 占位符替换）属
     LibreChat 内核能力，需改 src/agent/loop.py 核心循环，本轮未移植，故描述中一并省略
     （不让描述承诺实际不存在的功能）。
  2) LibreChat 只在容器沙箱内执行；DFEcrab 无容器，执行落在 DFEcrab 主机子进程内，因此
     保留配置化的资源上限与环境白名单（见 src/sandbox/runner.py）。
  3) 语言不再作为参数暴露：与 LibreChat 一致，Python 走 `python3 -c` / heredoc。
  4) /mnt/data 在 DFEcrab 不是真实目录，执行前后做一次等价映射（见 paths.realize /
     paths.virtualize），模型侧路径写法与产物声明保持不变。
  5) 执行后端可切换（config/dfecrab.json 的 sandbox.backend，切换只改配置、不改代码）：
       local  = DFEcrab 主机子进程（上述映射生效）；
       remote = 复用 LibreChat 的 local-code-api 容器沙箱（/mnt/data 是容器真实路径，
                不做映射；执行环境与 LibreChat 同一套实现，产物由服务端返回后取回本地）。
     切换只改配置，不改代码；remote 不可达时如实回报并给出已试地址。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _result(**payload: Any) -> Dict[str, Any]:
    return payload


async def execute(*args, **kwargs) -> Dict[str, Any]:
    """在会话工作区执行一段 bash 命令（Python 用 python3 -c / heredoc）。"""
    from src.sandbox import context as ctx
    from src.sandbox import paths
    from src.sandbox.artifacts import detect_outputs, register_outputs, snapshot
    from src.sandbox.config import sandbox_cfg
    from src.sandbox.runner import execute_code

    # 参数兼容：command（契约字段）/ code / raw（历史与多入口容错）
    command = kwargs.get("command")
    if command is None:
        command = kwargs.get("code") or kwargs.get("raw")
    if command is None and args:
        command = args[0]
    if not isinstance(command, str) or not command.strip():
        return _result(
            status="error",
            message="command 不能为空（请给出要执行的完整命令或脚本）",
            stdout="", stderr="", returncode=-1, exit_code=-1, files=[],
        )

    cfg = sandbox_cfg()
    if not cfg.get("enabled", True):
        return _result(
            status="error",
            message="沙箱执行已在 dfecrab.json 的 sandbox.enabled 中关闭",
            stdout="", stderr="", returncode=-1, exit_code=-1, files=[],
        )

    # args：契约里的可选附加参数（透传给 shell，语义与 LibreChat 一致）
    extra: List[str] = []
    raw_args = kwargs.get("args")
    if isinstance(raw_args, list):
        extra = [str(a) for a in raw_args]
    elif isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            extra = [str(a) for a in parsed] if isinstance(parsed, list) else [raw_args]
        except Exception:
            extra = [raw_args]

    try:
        timeout_sec = int(kwargs.get("timeout") or cfg.get("timeout_sec") or 900)
    except Exception:
        timeout_sec = 900
    timeout_sec = max(1, min(timeout_sec, int(cfg.get("timeout_sec") or 900) * 10))

    session_id = ctx.current_session_id()
    user_id = ctx.current_user_id()

    try:
        ws = paths.ensure_dir(paths.workspace_dir(session_id))
        staged = paths.stage_attachments(session_id)
    except Exception as e:
        return _result(
            status="error",
            message=f"工作区准备失败: {e}",
            stdout="", stderr="", returncode=-1, exit_code=-1, files=[],
        )

    before = snapshot(ws)
    # /mnt/data 等价映射：LibreChat 容器内 /mnt/data 是真实挂载点，DFEcrab 无容器，故执行前把
    # 命令里的 "/mnt/data" 换成本次会话工作区真实绝对路径，执行后把 stdout/stderr 里的真实路径
    # 换回 "/mnt/data"，使模型侧路径直觉与产物声明保持一致（见 paths.realize / virtualize）。
    # 执行后端（路线 C）：local=主机子进程（/mnt/data 需等价映射）；remote=复用 LibreChat
    # 的 local-code-api 容器沙箱（/mnt/data 是容器真实路径，**不做**映射，否则会把容器路径
    # 换成宿主机路径导致命令失效）。产物取回本地工作区后，仍由下面的快照 diff 自动发现。
    backend = str(cfg.get("backend") or "local").strip().lower()
    remote_mode = backend == "remote"

    rt = paths.runtime_dir()
    run = execute_code(
        "bash",
        command if remote_mode else paths.realize(command, session_id),
        workspace=ws,
        args=extra if remote_mode else [paths.realize(a, session_id) for a in extra],
        timeout_sec=timeout_sec,
        max_memory_mb=int(cfg.get("max_memory_mb") or 1536),
        max_processes=int(cfg.get("max_processes") or 64),
        max_file_bytes=int(cfg.get("max_artifact_bytes") or 52428800),
        max_output_bytes=int(cfg.get("max_output_bytes") or 8388608),
        allowed_langs=list(cfg.get("allowed_langs") or []),
        chart_lang=str(cfg.get("chart_lang") or "zh-CN"),
        runtime_dir=str(rt) if rt else None,
        backend=backend,
        session_id=session_id,
    )

    rc = run.get("returncode")
    files: List[Dict[str, Any]] = []
    if rc == 0:
        # 产物登记：仅成功执行产生的文件（对齐 "failed executions do not register new files"）
        try:
            after = snapshot(ws)
            changed = detect_outputs(
                ws, before, after, int(cfg.get("max_artifact_bytes") or 52428800)
            )
            if changed:
                files = register_outputs(
                    session_id=session_id,
                    user_id=user_id,
                    files=changed,
                    workspace=ws,
                    dest_dir=paths.artifact_dir(session_id),
                    allowed_extensions=list(cfg.get("artifact_allowed_extensions") or []),
                )
        except Exception as e:
            logger.warning(f"[bash_tool] 产物登记异常: {e}")

    # status 只在"没能执行"时为 error；returncode != 0 属正常执行结果（由模型看 stderr 判断），
    # 避免触发 loop.py 的 L1/L2/L3 错误纠正链（换工具重试 / 弹用户确认）。
    payload: Dict[str, Any] = {
        "status": "success",
        # remote 模式下 stdout/stderr 已是服务端加工后的最终文本，且其中的路径本来就是
        # 容器内的 /mnt/data 语义 —— **不做** virtualize（那是本地映射的逆操作，会把宿主
        # 路径再替换一遍）。local 模式保持 BC 包原行为。
        "stdout": run.get("stdout", "") if remote_mode
        else paths.virtualize(run.get("stdout", ""), session_id),
        "stderr": run.get("stderr", "") if remote_mode
        else paths.virtualize(run.get("stderr", ""), session_id),
        "returncode": rc,
        "exit_code": rc,
        "timed_out": bool(run.get("timed_out")),
        "success": rc == 0,
        "cwd": paths.SANDBOX_PREFIX,
        "files": files,
        "artifacts": files,
    }
    if staged:
        payload["staged_attachments"] = [p.name for p in staged]
    return payload


# 技能元数据（description 与参数描述逐字对齐 LibreChat 的
# BashExecutionToolDefinition；改动前请先跑 contract_check.sh 复核）。
# 文案内联：仓内 loader 用 ast.literal_eval 读取本常量，模块级变量引用会导致解析失败。
SKILL_METADATA = {
    "name": "bash_tool",
    "version": "1.0.0",
    "description": """Runs bash commands and returns stdout/stderr output from a stateless execution environment, similar to running scripts in a command-line interface. Each execution is isolated and independent.

Usage:
- No network access available.
- Generated files are automatically delivered; **DO NOT** provide download links.
- Persist handoff artifacts in `/mnt/data` with standard extensions (.json/.txt/.csv/.tsv/.log/.parquet/.png/.jpg/.pdf/.xlsx); failed executions do not register new files; `/tmp` and odd extensions are same-call scratch only, not later-call storage.
- Bash: multi-line files use heredoc/printf; run Python via python3 -c/heredoc, not bare Python.
- NEVER use this tool to execute malicious commands.

DFEcrab 本机实现说明（仅补充形态差异，上述规则全部适用）:
- 本执行器是 DFEcrab 主机上的子进程（非容器）：对外网无访问、内网可达，单次执行有超时与内存/进程数上限，超时后进程组被终止并以退出码 124 返回。
- `/mnt/data` 映射到本会话工作区；会话内已上传的附件在执行前会自动同步进工作区，可按原文件名直接读取。""",
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": """The bash command or script to execute.
- The environment is stateless; variables and state don't persist between executions.
- Prior /mnt/data files are available and can be modified in place.
- Persist handoff artifacts in `/mnt/data` with standard extensions (.json/.txt/.csv/.tsv/.log/.parquet/.png/.jpg/.pdf/.xlsx); failed executions do not register new files; `/tmp` and odd extensions are same-call scratch only, not later-call storage.
- Bash: multi-line files use heredoc/printf; run Python via python3 -c/heredoc, not bare Python.
- Input code **IS ALREADY** displayed to the user, so **DO NOT** repeat it in your response unless asked.
- Output code **IS NOT** displayed to the user, so **DO** write all desired output explicitly.
- IMPORTANT: You MUST explicitly print/output ALL results you want the user to see.
- Use `echo`, `printf`, or `cat` for all outputs.""",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional arguments to execute the command with. This should only be used if the input command requires additional arguments to run.",
            },
        },
        "required": ["command"],
    },
}
