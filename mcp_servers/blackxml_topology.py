"""blackxml_topology 本地 MCP 服务：包装 Node.js 实现的拓扑分析服务

由 DFEcrab 启动脚本自动拉起，保持存活直到 Node 子进程退出。

用法：
    cd /home/e8900/DFEcrab
    venv/bin/python mcp_servers/blackxml_topology.py

默认监听 127.0.0.1:8602，端点 = http://127.0.0.1:8602/mcp

默认数据目录：DFEcrab/mcp_servers/blackxml-topology-mcp/
（即本脚本同级的 blackxml-topology-mcp/ 目录）

环境变量（可覆盖默认值）：
    BLACKXML_MCP_DIR    blackxml-topology-mcp 根目录路径（覆盖默认位置）
    MCP_PORT            监听端口（默认 8602）
    MCP_HOST            监听地址（默认 127.0.0.1）
    MCP_REQUEST_TIMEOUT_MS  请求超时毫秒数（默认 600000 = 10分钟）
    MCP_ENABLE_UPDATES  是否启用数据更新（默认 true）
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# ── 配置（支持环境变量覆盖） ──
# 默认路径：blackxml-topology-mcp 放在 mcp_servers/ 下
# 也支持放在 DFEcrab 同级目录（通过 BLACKXML_MCP_DIR 环境变量覆盖）
_default_mcp_dir = Path(__file__).resolve().parent / "blackxml-topology-mcp"
MCP_DIR = Path(os.environ.get("BLACKXML_MCP_DIR", str(_default_mcp_dir)))
MCP_JS = MCP_DIR / "tools" / "http-mcp-server.js"
# 默认端口从 config/gateway.yaml 的 local_ports.mcp.blackxml_topology 读取，
# 支持 MCP_PORT 环境变量覆盖（dfecrab start 会显式传入）
if os.environ.get("MCP_PORT"):
    _default_mcp_port = int(os.environ["MCP_PORT"])
else:
    try:
        # config 是真正的 Python 包（src/config），需把 src 也加入 sys.path
        _root = Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(_root / "src"))
        sys.path.insert(0, str(_root))
        from config.port_loader import mcp_port
        _default_mcp_port = mcp_port("blackxml_topology", default=8602)
    except Exception:
        _default_mcp_port = 8602
MCP_PORT = _default_mcp_port
MCP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")

# ── 前置检查 ──
# Node.js 查找优先级（从高到低）：
# 1. 环境变量 NODE_BIN
# 2. 项目自带 runtime/bin/node（推荐：免系统安装）
#    - 如果是 musl 版（从 Alpine 容器提取），直接用 musl loader 调用 node.real
#    - 否则直接调用 node 二进制
# 3. PATH 中的 node
_project_root2 = Path(__file__).resolve().parent.parent
_runtime_dir = _project_root2 / "runtime"
_runtime_node = _runtime_dir / "bin" / "node"
_runtime_node_real = _runtime_dir / "bin" / "node.real"
_runtime_musl_ld = _runtime_dir / "lib" / "ld-musl-x86_64.so.1"
_runtime_lib = _runtime_dir / "lib"
_runtime_usr_lib = _runtime_dir / "usr" / "lib"

if os.environ.get("NODE_BIN"):
    _node_bin = os.environ["NODE_BIN"]
elif _runtime_musl_ld.exists() and _runtime_node_real.exists():
    # musl 版 Node：直接调用 musl loader，绕过 bash wrapper（避免 subprocess 挂起）
    _lib_path = "{}:{}".format(str(_runtime_lib), str(_runtime_usr_lib))
    _node_bin = [str(_runtime_musl_ld), "--library-path", _lib_path, str(_runtime_node_real)]
elif _runtime_node.exists():
    _node_bin = str(_runtime_node)
else:
    _node_bin = "node"

# 检查 Node.js
try:
    _ver_cmd = _node_bin + ["--version"] if isinstance(_node_bin, list) else [_node_bin, "--version"]
    _ver_proc = subprocess.run(
        _ver_cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=10
    )
    if _ver_proc.returncode != 0:
        raise FileNotFoundError("Node.js check failed")
    _node_version = _ver_proc.stdout.strip()
except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
    print("[blackxml_topology] ERROR: Node.js not found or not working.", file=sys.stderr)
    print("[blackxml_topology] Please install Node.js >= 22 and ensure it's in PATH.", file=sys.stderr)
    sys.exit(1)

# 检查 MCP JS 文件
if not MCP_JS.exists():
    print(f"[blackxml_topology] ERROR: MCP script not found: {MCP_JS}", file=sys.stderr)
    print(f"[blackxml_topology] MCP_DIR = {MCP_DIR}", file=sys.stderr)
    print(f"[blackxml_topology] CWD = {os.getcwd()}", file=sys.stderr)
    sys.exit(1)

# 检查数据目录
_blackxml_dir = MCP_DIR / "BLACKXML"
_status_dir = MCP_DIR / "开关状态"
_user_db_dir = MCP_DIR / "用户列表索引"
_warnings = []
if not _blackxml_dir.exists():
    _warnings.append(f"  - BLACKXML directory not found: {_blackxml_dir}")
if not _status_dir.exists():
    _warnings.append(f"  - 开关状态 directory not found: {_status_dir}")
if not _user_db_dir.exists():
    _warnings.append(f"  - 用户列表索引 directory not found: {_user_db_dir}")

print(f"[blackxml_topology] Node.js: {_node_version}")
print(f"[blackxml_topology] MCP dir: {MCP_DIR}")
print(f"[blackxml_topology] MCP script: {MCP_JS}")
print(f"[blackxml_topology] Listening: {MCP_HOST}:{MCP_PORT}")
if _warnings:
    print("[blackxml_topology] WARNING: Some data directories missing:")
    for w in _warnings:
        print(w)

# ── 拉起 Node.js MCP 进程 ──
_env = os.environ.copy()
_env["MCP_HOST"] = MCP_HOST
_env["MCP_PORT"] = str(MCP_PORT)
_env["MCP_REQUEST_TIMEOUT_MS"] = os.environ.get("MCP_REQUEST_TIMEOUT_MS", "600000")
_env["MCP_ENABLE_UPDATES"] = os.environ.get("MCP_ENABLE_UPDATES", "true")

# 如果使用 musl 版 Node，设置子进程启动所需的环境变量
if isinstance(_node_bin, list) and _runtime_musl_ld.exists():
    _env["MUSL_LD"] = str(_runtime_musl_ld)
    _env["MUSL_LIB_PATH"] = _lib_path
    _env["NODE_REAL"] = str(_runtime_node_real)

# 数据目录路径（如果环境变量中有自定义路径则使用）
if "BLACKXML_DIR" in os.environ:
    _env["BLACKXML_DIR"] = os.environ["BLACKXML_DIR"]
if "STATUS_DIR" in os.environ:
    _env["STATUS_DIR"] = os.environ["STATUS_DIR"]
if "CURRENT_DIR" in os.environ:
    _env["CURRENT_DIR"] = os.environ["CURRENT_DIR"]
if "USER_DB_DIR" in os.environ:
    _env["USER_DB_DIR"] = os.environ["USER_DB_DIR"]

# 构建启动命令（_node_bin 可能是 list 或 string）
_launch_cmd = (_node_bin if isinstance(_node_bin, list) else [_node_bin]) + [str(MCP_JS)]
proc = subprocess.Popen(
    _launch_cmd,
    cwd=str(MCP_DIR),
    env=_env,
    stdout=sys.stdout,
    stderr=sys.stderr,
    preexec_fn=os.setsid,  # 创建独立进程组，确保能杀掉所有子进程
)

# ── 等待端口就绪 ──
import socket
_ready = False
for _i in range(30):
    time.sleep(1)
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _s.settimeout(1)
        if _s.connect_ex((MCP_HOST, MCP_PORT)) == 0:
            _ready = True
            _s.close()
            break
        _s.close()
    except Exception:
        pass
    # 检查子进程是否已退出
    if proc.poll() is not None:
        print(f"[blackxml_topology] ERROR: Node.js process exited early (code={proc.returncode})", file=sys.stderr)
        sys.exit(1)

if not _ready:
    print(f"[blackxml_topology] WARNING: Port {MCP_PORT} not ready after 30s, but process is running", file=sys.stderr)
else:
    print(f"[blackxml_topology] Port {MCP_PORT} is ready ✓")

# ── 优雅关闭处理 ──
_shutdown_started = False

def _kill_process_group():
    """杀掉 Node.js 进程组中的所有进程。"""
    try:
        pgid = os.getpgid(proc.pid)
        # 先尝试优雅终止
        os.killpg(pgid, signal.SIGTERM)
        # 等待最多 3 秒
        for _ in range(30):
            if proc.poll() is not None:
                return
            time.sleep(0.1)
        # 还没死就强杀
        os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=2)
    except (ProcessLookupError, OSError):
        pass

def _handle_signal(signum, frame):
    global _shutdown_started
    if _shutdown_started:
        return  # 防止重入
    _shutdown_started = True
    print(f"\n[blackxml_topology] Received signal {signum}, shutting down...")
    _kill_process_group()
    print("[blackxml_topology] Shut down complete.")
    sys.exit(0)

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# ── 保活：轮询等待 Node 进程退出 ──
print(f"[blackxml_topology] Running (pid={proc.pid})... Press Ctrl+C to stop.")
while not _shutdown_started:
    try:
        proc.wait(timeout=0.5)
        # 子进程自己退出了
        break
    except subprocess.TimeoutExpired:
        continue
    except KeyboardInterrupt:
        # 被 signal handler 拦截了，它会设置 _shutdown_started
        pass

if _shutdown_started:
    # 信号已处理，直接退出
    sys.exit(0)

_exit_code = proc.returncode
print(f"[blackxml_topology] Node.js process exited (code={_exit_code})")
sys.exit(_exit_code or 0)
