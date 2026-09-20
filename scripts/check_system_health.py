"""
DFEcrab 系统健康检查脚本（完整版）

覆盖范围：
1. 环境与配置：config/gateway.yaml、关键目录、入口脚本、依赖缺失
2. 核心系统：grpc、gateway_import、memory、task、reflection、skill、plugin、multi_agent
3. 启动就绪：Gateway 初始化链路、/health 端点、端口占用、日志路径
4. 运维友好：遇到缺依赖给安装建议，失败输出 JSON 可对接 CI

用法：
    python scripts/check_system_health.py
    python scripts/check_system_health.py --json
    python scripts/check_system_health.py --deep
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import subprocess
import sys
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


@dataclass
class CheckResult:
    name: str
    ok: bool
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _python_snippet(body: str) -> str:
    prefix = textwrap.dedent(
        f"""
import json
import sys
from pathlib import Path

project_root = Path(r"{PROJECT_ROOT}")
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))
"""
    ).strip()
    return prefix + "\n\n" + textwrap.dedent(body).strip() + "\n"


def _run_snippet(name: str, body: str) -> CheckResult:
    proc = subprocess.run(
        [PYTHON, "-c", _python_snippet(body)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        combined = (proc.stderr or "") + "\n" + (proc.stdout or "")
        combined = combined.strip()
        summary, error = _classify_failure(combined)
        return CheckResult(
            name=name,
            ok=False,
            summary=summary,
            error=error,
        )

    output = (proc.stdout or "").strip()
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError:
        return CheckResult(
            name=name,
            ok=False,
            summary="检查输出无法解析",
            error=output,
        )

    return CheckResult(
        name=name,
        ok=bool(payload.get("ok", True)),
        summary=payload.get("summary", "ok"),
        details=payload.get("details", {}),
        error=payload.get("error"),
    )


def _classify_failure(stderr_and_stdout: str):
    import re

    missing = re.search(r"ModuleNotFoundError: No module named '([^']+)'", stderr_and_stdout)
    if missing:
        name = missing.group(1)
        install_hints = {
            "kazoo": "pip install kazoo==2.11.0",
            "yaml": "pip install pyyaml",
            "click": "pip install click",
            "grpc": "pip install grpcio protobuf",
            "flask": "pip install flask flask-cors",
            "httpx": "pip install httpx",
            "numpy": "pip install numpy",
            "pandas": "pip install pandas",
            "openpyxl": "pip install openpyxl",
        }
        if "." in name:
            base = name.split(".")[0]
        else:
            base = name
        hint = install_hints.get(base) or install_hints.get(name) or f"pip install {base}"
        return (
            f"缺少依赖 '{name}'",
            f"运行环境缺少模块 {name}，建议执行：{hint}",
        )

    head = stderr_and_stdout.splitlines()
    summary = head[-1].strip() or "检查失败"
    if len(summary) > 120:
        summary = summary[:117] + "..."
    return summary, stderr_and_stdout or None


# ============== 基础层：环境 / 配置 / 目录 / 入口 ==============


def check_project_layout() -> CheckResult:
    required_dirs = ["src", "skills", "plugins", "config", "scripts"]
    optional_dirs = ["agents", "logs", "data", "tui"]
    required_files = [
        "config/gateway.yaml",
        "scripts/start_gateway_grpc.py",
        "src/__main__.py",
    ]

    missing_dirs = [p for p in required_dirs if not (PROJECT_ROOT / p).is_dir()]
    missing_files = [p for p in required_files if not (PROJECT_ROOT / p).is_file()]
    present_optional = [p for p in optional_dirs if (PROJECT_ROOT / p).is_dir()]

    return CheckResult(
        name="project_layout",
        ok=not missing_dirs and not missing_files,
        summary="项目目录与关键文件完整" if not missing_dirs and not missing_files else "项目目录/入口缺失",
        details={
            "project_root": str(PROJECT_ROOT),
            "missing_required_dirs": missing_dirs,
            "missing_required_files": missing_files,
            "optional_dirs_present": present_optional,
        },
        error=None if not missing_dirs and not missing_files else
        f"缺少目录 {missing_dirs} 或缺少文件 {missing_files}",
    )


def check_config() -> CheckResult:
    return _run_snippet(
        "config",
        """
from src.config.config_loader import config

raw = config.raw_config
gateway = raw.get("gateway", {})
zookeeper = raw.get("zookeeper", {})

print(json.dumps({
    "ok": True,
    "summary": "配置文件可加载",
    "details": {
        "project_root": str(config.project_root),
        "gateway_host": gateway.get("host"),
        "gateway_port": gateway.get("port"),
        "ws_port": gateway.get("ws_port"),
        "zk_hosts": zookeeper.get("hosts"),
        "zk_namespace": zookeeper.get("namespace"),
        "raw_keys": sorted(list(raw.keys())),
    }
}, ensure_ascii=False))
        """,
    )


def check_ports() -> CheckResult:
    return _run_snippet(
        "ports",
        """
import socket
import json
import urllib.request
import urllib.error

try:
    from src.config.config_loader import config
    http_port = int(config.gateway_port)
    ws_port = int(config.websocket_port)
    zk_hosts = config.zk_hosts or "localhost:2181"
except Exception as e:
    print(json.dumps({
        "ok": False,
        "summary": "无法读取端口配置",
        "error": f"读取 gateway.yaml 失败: {e}",
    }, ensure_ascii=False))
    raise SystemExit(0)

def taken(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()

def looks_like_dfecrab_http(port: int):
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            payload = json.loads(body)
            status = str(payload.get("status", ""))
            version = str(payload.get("version", ""))
            gateway = str(payload.get("gateway", ""))
            if status == "healthy":
                return True, "dfecrab_healthy"
            if "grpc" in version or "dfecrab" in (gateway + status).lower():
                return True, "dfecrab_matched"
            return False, "foreign_http"
    except Exception as e:
        return False, f"unknown_{type(e).__name__}"

http_taken = taken(http_port)
ws_taken = taken(ws_port)
zk_reachable = False
try:
    host, _, port_str = zk_hosts.partition(":")
    if not host:
        host = "127.0.0.1"
    zk_port = int(port_str or "2181")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.8)
    zk_reachable = sock.connect_ex((host, zk_port)) == 0
    sock.close()
except Exception:
    zk_reachable = False

http_owner = "free"
if http_taken:
    matched, reason = looks_like_dfecrab_http(http_port)
    http_owner = "dfecrab" if matched else f"unknown({reason})"

ws_owner = "free" if not ws_taken else "unknown"

# 判定规则：
# - HTTP 空闲 -> OK（允许启动）
# - HTTP 被 DFEcrab 自己占 -> OK（服务正在运行，端口正确）
# - 其他占用 -> FAIL（外部冲突）
ok = (not http_taken) or (http_owner == "dfecrab")
summary = "启动所需端口可用"
if http_taken and http_owner == "dfecrab":
    summary = "端口已被 DFEcrab 占用（正在运行，正常）"
elif not ok:
    summary = "端口已被外部进程占用"

print(json.dumps({
    "ok": bool(ok),
    "summary": summary,
    "details": {
        "gateway_http": f"127.0.0.1:{http_port}",
        "gateway_http_in_use": http_taken,
        "gateway_http_owner": http_owner,
        "gateway_ws": f"127.0.0.1:{ws_port}",
        "gateway_ws_in_use": ws_taken,
        "gateway_ws_owner": ws_owner,
        "zk_hosts": zk_hosts,
        "zk_socket_reachable": zk_reachable,
    },
    "error": None if ok else f"端口冲突: HTTP={http_port} 被非 DFEcrab 进程占用, WS={ws_port} {'占用' if ws_taken else '空闲'}",
}, ensure_ascii=False))
        """,
    )


def check_runtime_dependencies() -> CheckResult:
    return _run_snippet(
        "dependencies",
        """
import importlib.util

modules = {
    "yaml": "pyyaml",
    "click": "click",
    "grpc": "grpcio",
    "google.protobuf": "protobuf",
    "httpx": "httpx",
    "kazoo": "kazoo",
    "requests": "requests",
}
missing = {}
present = {}
for mod, pip_name in modules.items():
    found = importlib.util.find_spec(mod) is not None
    present[mod] = found
    if not found:
        missing[mod] = pip_name

ok = not missing
print(json.dumps({
    "ok": bool(ok),
    "summary": "运行关键依赖齐全" if ok else f"缺失 {len(missing)} 个关键依赖",
    "details": {
        "modules": present,
        "missing_pip_install": [f"pip install {pkg}" for pkg in missing.values()],
    },
    "error": None if ok else "缺失依赖: " + ", ".join(f"{mod}({pkg})" for mod, pkg in missing.items()),
}, ensure_ascii=False))
        """,
    )


def check_entrypoints() -> CheckResult:
    return _run_snippet(
        "entrypoints",
        """
import sys
from pathlib import Path

checks = {}
warnings = []

# 1) python -m src.__main__ 可解析
try:
    from src.__main__ import main as _main
    checks["src.__main__.main"] = True
except Exception as e:
    checks["src.__main__.main"] = False
    warnings.append(f"src.__main__.main 导入失败: {e}")

# 2) dfecrab wrapper 存在且可被 python 编译（不执行，避免启动服务）
wrapper = Path(project_root) / "dfecrab"
if wrapper.exists():
    checks["dfecrab_wrapper_file_exists"] = True
    import py_compile
    try:
        py_compile.compile(str(wrapper), doraise=True)
        checks["dfecrab_wrapper_compiles"] = True
    except Exception as e:
        checks["dfecrab_wrapper_compiles"] = False
        warnings.append(f"dfecrab wrapper 语法/编译检查失败: {e}")
else:
    checks["dfecrab_wrapper_file_exists"] = False
    warnings.append("根目录缺少 dfecrab 启动包装脚本")

print(json.dumps({
    "ok": all(checks.values()),
    "summary": "入口命令就绪" if all(checks.values()) else "部分入口异常",
    "details": {"checks": checks, "warnings": warnings},
    "error": "；".join(warnings) if warnings else None,
}, ensure_ascii=False))
        """,
    )


# ============== 系统层：各子系统 ==============


def check_grpc() -> CheckResult:
    return _run_snippet(
        "grpc",
        """
from src.gateway.grpc import dfecrab_pb2, dfecrab_pb2_grpc
print(json.dumps({
    "ok": True,
    "summary": "gRPC protobuf 模块可导入",
    "details": {
        "pb2_file": getattr(dfecrab_pb2, "__file__", None),
        "pb2_grpc_file": getattr(dfecrab_pb2_grpc, "__file__", None),
    }
}, ensure_ascii=False))
        """,
    )


def check_gateway_import() -> CheckResult:
    return _run_snippet(
        "gateway_import",
        """
try:
    from src.gateway.grpc_server import GatewayV2GRPC
except ModuleNotFoundError as e:
    name = getattr(e, "name", "") or str(e)
    install_hints = {
        "kazoo": "pip install kazoo==2.11.0",
        "grpc": "pip install grpcio protobuf",
        "httpx": "pip install httpx",
        "flask": "pip install flask flask-cors",
        "yaml": "pip install pyyaml",
    }
    if "." in name:
        base = name.split(".")[0]
    else:
        base = name
    hint = install_hints.get(base) or install_hints.get(name) or f"pip install {base}"
    print(json.dumps({
        "ok": False,
        "summary": f"Gateway 导入失败：缺少依赖 '{name}'",
        "details": {"missing_module": name},
        "error": f"运行环境缺少依赖 {name}，建议执行：{hint}"
    }, ensure_ascii=False))
except Exception as e:
    import traceback
    print(json.dumps({
        "ok": False,
        "summary": "Gateway gRPC 主模块导入失败",
        "details": {"exception_type": type(e).__name__},
        "error": traceback.format_exc().strip()
    }, ensure_ascii=False))
else:
    print(json.dumps({
        "ok": True,
        "summary": "Gateway gRPC 主模块可导入",
        "details": {"gateway_class": GatewayV2GRPC.__name__}
    }, ensure_ascii=False))
        """,
    )


def check_memory() -> CheckResult:
    return _run_snippet(
        "memory",
        """
from src.memory.global_manager import get_global_memory_manager
from src.memory.long_term import MemoryManager

global_mgr = get_global_memory_manager()
stats = global_mgr.get_stats()
mm = MemoryManager(agent_id="healthcheck_agent")
mm.add_to_short_term("healthcheck_session", {"role": "user", "content": "ping"})

print(json.dumps({
    "ok": True,
    "summary": "记忆系统可用",
    "details": {
        "global_stats": stats,
        "short_term_entries": len(mm.get_short_term("healthcheck_session")),
        "shared_knowledge_loaded": bool(mm.get_shared_knowledge()),
    }
}, ensure_ascii=False))
        """,
    )


def check_task() -> CheckResult:
    return _run_snippet(
        "task",
        """
from src.task.scheduler import get_task_scheduler, TodoTask
from src.task.task_manager import TaskManager

scheduler = get_task_scheduler()
before_stats = scheduler.get_stats()
scheduler.add_todo(TodoTask(task_id="healthcheck_todo", title="healthcheck"))
scheduler.complete_todo("healthcheck_todo", {"status": "ok"})

manager = TaskManager(storage_dir="data/tasks")
details = {
    "scheduler_before": before_stats,
    "scheduler_after": scheduler.get_stats(),
    "loaded_tasks": len(getattr(manager, "_tasks", {})),
    "storage_dir": str(getattr(manager, "storage_dir", "")),
}

print(json.dumps({
    "ok": True,
    "summary": "任务系统可用",
    "details": details
}, ensure_ascii=False))
        """,
    )


def check_reflection() -> CheckResult:
    return _run_snippet(
        "reflection",
        """
from src.reflection import get_self_reflector, ConversationSample

reflector = get_self_reflector()
sample = ConversationSample(
    user_message="你好",
    assistant_response="你好，这是健康检查",
    session_id="healthcheck_session",
)

print(json.dumps({
    "ok": True,
    "summary": "反思系统可用",
    "details": {
        "reflector_type": type(reflector).__name__,
        "history_count": len(reflector.get_reflection_history(limit=1)),
        "sample_type": type(sample).__name__,
    }
}, ensure_ascii=False))
        """,
    )


def check_skill() -> CheckResult:
    return _run_snippet(
        "skill",
        """
from src.skill.loader import get_skill_loader
from src.skill.registry import get_tool_registry

loader = get_skill_loader()
registry = get_tool_registry()
skills_dir = project_root / "skills"
skill_dirs = [p.name for p in skills_dir.iterdir() if p.is_dir()] if skills_dir.exists() else []
tools = registry.list_tools()

print(json.dumps({
    "ok": True,
    "summary": "技能系统可用",
    "details": {
        "loader_type": type(loader).__name__,
        "skill_dir_count": len(skill_dirs),
        "tool_count": len(tools),
        "sample_tools": [item["function"]["name"] for item in tools[:10]],
    }
}, ensure_ascii=False))
        """,
    )


def check_multi_agent() -> CheckResult:
    return _run_snippet(
        "multi_agent",
        """
import asyncio
from src.agent.multi import get_self_assessor

assessor = get_self_assessor()
assessment = asyncio.run(assessor.assess(task="healthcheck", context={"source": "system_health"}))

print(json.dumps({
    "ok": True,
    "summary": "多智能体系统可用",
    "details": {
        "assessor_type": type(assessor).__name__,
        "task_type": getattr(getattr(assessment, "task_type", None), "value", None),
        "needs_help": getattr(assessment, "needs_help", None),
        "collaboration_mode": getattr(assessment, "collaboration_mode", None),
    }
}, ensure_ascii=False))
        """,
    )


# ============== 启动层：Gateway 初始化 + /health ==============


def check_gateway_initialize() -> CheckResult:
    return _run_snippet(
        "gateway_initialize",
        """
import asyncio
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

warnings = []

try:
    from src.gateway.grpc_server import GatewayV2GRPC
    from src.config.config_loader import config
except Exception as e:
    import traceback
    print(json.dumps({
        "ok": False,
        "summary": "Gateway 模块无法导入，初始化体检跳过",
        "details": {"exception": type(e).__name__},
        "error": traceback.format_exc().strip(),
    }, ensure_ascii=False))
    raise SystemExit(0)

gw = GatewayV2GRPC(
    host="127.0.0.1",
    port=int(config.gateway_port),
    ws_port=int(config.websocket_port),
    zk_hosts=config.zk_hosts,
)

async def probe():
    init_steps = {}
    ok = True

    # Step 1: config load
    try:
        _ = gw._load_config()
        init_steps["load_config"] = True
    except Exception as e:
        init_steps["load_config"] = False
        warnings.append(f"load_config 失败: {e}")
        ok = False

    # Step 2: event bus
    try:
        from src.gateway import get_event_bus
        gw._event_bus = get_event_bus()
        init_steps["event_bus_ready"] = True
    except Exception as e:
        init_steps["event_bus_ready"] = False
        warnings.append(f"event_bus 初始化失败: {e}")
        ok = False

    # Step 3: route registration (不会真的监听端口)
    try:
        # 必须先创建 http server，否则 register routes 会报属性错
        from src.gateway.http.server import HTTPServer
        from src.gateway.websocket.server import WebSocketServer
        from src.task.task_manager import TaskManager
        from src.task.periodic_scheduler import PeriodicScheduler

        gw._task_manager = TaskManager()
        gw._periodic_scheduler = PeriodicScheduler(tasks_dir="data/tasks")
        gw._http_server = HTTPServer(host=gw.host, port=gw.port, service_locator=None, event_bus=gw._event_bus)
        gw._websocket_server = WebSocketServer(host=gw.host, port=gw.ws_port, event_bus=gw._event_bus)
        gw._register_routes()
        route_count = len(getattr(gw._http_server, "_routes", []))
        init_steps["routes_registered"] = True
        init_steps["http_route_count"] = route_count
    except Exception as e:
        init_steps["routes_registered"] = False
        warnings.append(f"路由注册失败: {e}")
        ok = False

    # Step 4: 直接调用 _handle_health，验证自检输出结构
    try:
        class _DummyRequest: pass
        health = await gw._handle_health(_DummyRequest())
        required = {"status", "gateway", "version", "manager_agent", "worker_agents", "architecture", "zookeeper"}
        init_steps["health_handler_works"] = required.issubset(set(health.keys()))
        init_steps["health_sample"] = {k: health.get(k) for k in ["status", "gateway", "version", "manager_agent", "worker_agents", "zookeeper"]}
        if not init_steps["health_handler_works"]:
            ok = False
            warnings.append("_handle_health 返回结构缺少字段")
    except Exception as e:
        init_steps["health_handler_works"] = False
        warnings.append(f"_handle_health 执行失败: {e}")
        ok = False

    return ok, init_steps

try:
    ok, steps = asyncio.run(probe())
except Exception as e:
    import traceback
    print(json.dumps({
        "ok": False,
        "summary": "Gateway 初始化链路异常",
        "details": {"exception": type(e).__name__},
        "error": traceback.format_exc().strip(),
    }, ensure_ascii=False))
    raise SystemExit(0)

print(json.dumps({
    "ok": bool(ok),
    "summary": "Gateway 初始化链路通过" if ok else "Gateway 初始化链路存在断点",
    "details": {"init_steps": steps, "warnings": warnings},
    "error": ("；".join(warnings) if warnings else None),
}, ensure_ascii=False))
        """,
    )


def check_health_endpoint() -> CheckResult:
    """探测 /health 端点。

    根据端口实际状态自动选路径：
    - 端口被 DFEcrab 占用：直接打现有实例（最真实场景）
    - 端口空闲：在子进程里启动最小化 HTTP Server 再打 /health
    - 端口被非 DFEcrab 占用：判定为外部冲突，跳过
    """
    port_probe = check_ports()
    http_in_use = bool(port_probe.details.get("gateway_http_in_use"))
    http_owner = port_probe.details.get("gateway_http_owner") or "free"
    test_port = int(port_probe.details.get("gateway_http", "6789").split(":")[-1])

    if not port_probe.ok:
        return CheckResult(
            name="health_endpoint",
            ok=False,
            summary="端口被外部进程占用，跳过 /health 探测",
            details=port_probe.details,
            error=port_probe.error,
        )

    mode = "probe_live_instance" if (http_in_use and http_owner == "dfecrab") else "start_minimal_server"

    return _run_snippet(
        "health_endpoint",
        f"""
import asyncio
import json
import logging
import socket
import time
import urllib.request
import urllib.error

logging.basicConfig(level=logging.WARNING)
probe_port = {test_port}
probe_host = "127.0.0.1"
mode = {mode!r}

def probe_live(timeout: float = 5.0):
    url = f"http://{{probe_host}}:{{probe_port}}/health"
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body), None
        except Exception as e:
            last_error = str(e)
            time.sleep(0.1)
    return None, last_error or "probe_live failed with no exception"

if mode == "probe_live_instance":
    payload, probe_error = probe_live(timeout=5.0)
    details = {{
        "mode": "probe_live_instance",
        "endpoint": f"http://{{probe_host}}:{{probe_port}}/health",
    }}
    if payload:
        details["health_response"] = payload
    ok = bool(payload and payload.get("status") == "healthy")
    print(json.dumps({{
        "ok": bool(ok),
        "summary": "运行中的 Gateway 返回 healthy" if ok else "运行中的 Gateway 未返回 healthy",
        "details": details,
        "error": probe_error,
    }}, ensure_ascii=False))
    raise SystemExit(0)

# else: start_minimal_server
from src.gateway.grpc_server import GatewayV2GRPC
from src.gateway.http.server import HTTPServer
from src.config.config_loader import config
from src.gateway import get_event_bus

gw = GatewayV2GRPC(
    host=probe_host,
    port=probe_port,
    ws_port=int(config.websocket_port),
    zk_hosts=config.zk_hosts,
)
gw._event_bus = get_event_bus()
gw._http_server = HTTPServer(
    host=probe_host,
    port=probe_port,
    service_locator=None,
    event_bus=gw._event_bus,
)
gw._register_routes()

async def socket_ready(host: str, port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.2)
        try:
            if s.connect_ex((host, port)) == 0:
                return True
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
        await asyncio.sleep(0.1)
    return False

async def probe_http(host: str, port: int, timeout: float = 5.0):
    url = f"http://{{host}}:{{port}}/health"
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body), None
        except Exception as e:
            last_error = str(e)
            await asyncio.sleep(0.1)
    return None, last_error or "probe failed with no exception"

async def main_coro():
    started_ok = False
    errors = []
    socket_ok = False
    payload = None
    probe_error = None
    try:
        started_ok = await gw._http_server.start()
        if started_ok:
            socket_ok = await socket_ready(probe_host, probe_port, timeout=5.0)
            if socket_ok:
                payload, probe_error = await probe_http(probe_host, probe_port, timeout=5.0)
    except Exception as e:
        import traceback
        errors.append(traceback.format_exc().strip())
    finally:
        try:
            await gw._http_server.stop()
        except Exception as e:
            errors.append(f"stop http server error: {{e}}")

    ok = bool(payload and payload.get("status") == "healthy")
    details = {{
        "mode": "start_minimal_server",
        "endpoint": f"http://{{probe_host}}:{{probe_port}}/health",
        "gateway_started_flag": started_ok,
        "socket_ready": socket_ok,
        "thread_errors": errors,
    }}
    if payload:
        details["health_response"] = payload

    print(json.dumps({{
        "ok": bool(ok),
        "summary": "HTTP /health 可返回 healthy" if ok else "HTTP /health 未返回 healthy",
        "details": details,
        "error": probe_error or ("；".join(errors) if errors else None),
    }}, ensure_ascii=False))

asyncio.run(main_coro())
        """,
    )


# ============== 主流程 ==============


ALL_CHECK_ORDER: List[str] = [
    "project_layout",
    "dependencies",
    "config",
    "ports",
    "entrypoints",
    "grpc",
    "gateway_import",
    "memory",
    "task",
    "reflection",
    "skill",
    "multi_agent",
    "gateway_initialize",
    "health_endpoint",
]


def _run_checks(deep: bool, only: List[str] | None = None) -> List[CheckResult]:
    wanted = set(only) if only else set(ALL_CHECK_ORDER)

    ordered_checks = [
        ("project_layout", lambda: check_project_layout()),
        ("dependencies", lambda: check_runtime_dependencies()),
        ("config", lambda: check_config()),
        ("ports", lambda: check_ports()),
        ("entrypoints", lambda: check_entrypoints()),
        ("grpc", lambda: check_grpc()),
        ("gateway_import", lambda: check_gateway_import()),
        ("memory", lambda: check_memory()),
        ("task", lambda: check_task()),
        ("reflection", lambda: check_reflection()),
        ("skill", lambda: check_skill()),
        ("multi_agent", lambda: check_multi_agent()),
        ("gateway_initialize", lambda: check_gateway_initialize()),
        ("health_endpoint", lambda: check_health_endpoint()),
    ]

    results: List[CheckResult] = []
    for name, factory in ordered_checks:
        if name in wanted:
            results.append(factory())
    return results


def _print_human(results: List[CheckResult]):
    ok_count = sum(1 for r in results if r.ok)
    failed_count = len(results) - ok_count
    print("=" * 72)
    print("DFEcrab 完整启动体检")
    print("=" * 72)
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        print(f"[{status}] {r.name:<18} {r.summary}")
        if r.details:
            for key, value in r.details.items():
                print(f"       - {key}: {value}")
        if r.error:
            for line in str(r.error).splitlines()[:10]:
                print(f"       - error: {line}")
    print("-" * 72)
    print(f"总计: {len(results)}  通过: {ok_count}  失败: {failed_count}")
    if failed_count:
        failed_names = [r.name for r in results if not r.ok]
        print(f"失败项: {', '.join(failed_names)}")
        print("建议顺序：先修 project_layout / dependencies / config，再看 gateway_initialize / health_endpoint")


def main() -> int:
    parser = argparse.ArgumentParser(description="DFEcrab 完整启动体检脚本")
    parser.add_argument("--json", action="store_true", help="输出 JSON 结果")
    parser.add_argument("--deep", action="store_true", help="深度体检（含插件加载）")
    parser.add_argument("--only", nargs="+", choices=ALL_CHECK_ORDER,
                        help="只跑指定检查项，例如：--only gateway_import gateway_initialize")
    args = parser.parse_args()

    results = _run_checks(args.deep, args.only)

    ok_count = sum(1 for r in results if r.ok)
    failed_count = len(results) - ok_count
    payload = {
        "ok": failed_count == 0,
        "summary": {"total": len(results), "ok": ok_count, "failed": failed_count},
        "results": [asdict(r) for r in results],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(results)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
