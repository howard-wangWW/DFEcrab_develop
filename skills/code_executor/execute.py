"""
安全沙箱执行器Skill - DFEcrab
自动提取markdown ```python代码块，子进程隔离执行，CPU/内存/文件大小限制
"""
import subprocess
import tempfile
import os
import signal
import resource
import logging
import re
import asyncio
from typing import Dict, Any

logger = logging.getLogger(__name__)

MAX_OUTPUT_LENGTH = 10000
DEFAULT_TIMEOUT = 5
# 高危模块黑名单：简单静态检查，仅第一层import拦截，不是完整沙箱防御
FORBIDDEN_MODULES = {"os", "subprocess", "sys", "socket", "importlib", "__import__", "pty"}


def _set_limits(timeout_sec: int):
    """子进程内设置资源限制，必须在preexec_fn调用"""
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (timeout_sec, timeout_sec + 1))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
    except Exception:
        pass


def _sync_execute(code: str, timeout: int) -> Dict[str, Any]:
    """同步真实执行逻辑，放到线程池运行，不阻塞asyncio事件循环"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp_path = f.name
    try:
        proc = subprocess.Popen(
            ["python3", tmp_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=lambda: _set_limits(timeout) if hasattr(os, "setsid") else None,
            start_new_session=hasattr(os, "setsid"),
            text=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            # 杀死整个进程组
            if hasattr(os, "setsid"):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
            else:
                proc.kill()
            stdout, stderr = proc.communicate()
            returncode = -9
            timed_out = True
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    # 输出截断
    if len(stdout) > MAX_OUTPUT_LENGTH:
        stdout = stdout[:MAX_OUTPUT_LENGTH] + "\n...[输出截断]"
    if len(stderr) > MAX_OUTPUT_LENGTH:
        stderr = stderr[:MAX_OUTPUT_LENGTH] + "\n...[输出截断]"

    return {
        "success": returncode == 0,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "timed_out": timed_out,
    }


async def execute(*args, **kwargs) -> Dict[str, Any]:
    """
    Skill入口，异步函数，DFEcrab Skill框架调用本函数
    参数：code:str，待运行python代码；timeout:int 超时秒数
    """
    logger.info(f"🔍 [code_executor] args: {args}, kwargs: {kwargs}")
    code: str | None = None
    timeout = kwargs.get("timeout", DEFAULT_TIMEOUT)

    # 1. 直接code参数
    if "code" in kwargs:
        code = kwargs["code"]
    # 2. input_data嵌套
    if code is None and "input_data" in kwargs:
        input_data = kwargs["input_data"]
        if isinstance(input_data, dict):
            code = input_data.get("code")
            raw_msg = input_data.get("message", "")
            if code is None and raw_msg and "```" in raw_msg:
                match = re.search(r"```python\s*(.*?)\s*```", raw_msg, re.DOTALL)
                if match:
                    code = match.group(1)
    # 3. args传入
    if code is None and len(args) > 0:
        code = args[0]
    # 4. instruction / message
    if code is None and "instruction" in kwargs:
        code = kwargs["instruction"]
    if code is None and "message" in kwargs:
        code = kwargs["message"]

    # 5. 提取markdown代码块
    if code and isinstance(code, str) and "```" in code:
        m = re.search(r"```python\s*(.*?)\s*```", code, re.DOTALL)
        if m:
            code = m.group(1)
        else:
            m = re.search(r"```\s*(.*?)\s*```", code, re.DOTALL)
            if m:
                code = m.group(1)

    logger.info(f"   提取的 code 长度: {len(code) if code else 0}")
    if not code or not isinstance(code, str):
        return {
            "success": False,
            "error": "无法提取Python代码，请传入code参数或使用```python```代码块",
            "stdout": "",
            "stderr": "错误: 未获取有效代码",
            "returncode": -1,
            "timed_out": False
        }

    # 简单静态黑名单检测（仅基础防护，不能当作真正安全沙箱）
    code_lower = code.lower()
    for mod in FORBIDDEN_MODULES:
        if f"import {mod}" in code_lower or f"from {mod}" in code_lower:
            return {
                "success": False,
                "error": f"安全策略禁止导入模块 '{mod}'",
                "stdout": "",
                "stderr": f"禁止导入模块: {mod}",
                "returncode": -1,
                "timed_out": False,
            }

    # 使用线程池跑同步subprocess，不阻塞事件循环
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _sync_execute, code, timeout)
    return result


SKILL_METADATA = {
    "name": "code_executor",
    "description": "在隔离沙箱子进程中执行Python代码。可以传入原始代码字符串，也可以自动解析```python ```markdown代码块。执行完成返回stdout、stderr、返回码、是否超时。适合数据分析、计算、数据处理。禁止使用os/subprocess/socket等高危模块。",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python源代码字符串，可以包含```python代码块标记，工具会自动剥离markdown标记"
            },
            "timeout": {
                "type": "integer",
                "description": "最大执行超时秒数",
                "default": 5
            }
        },
        "required": ["code"]
    }
}
