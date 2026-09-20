#!/usr/bin/env python3
"""
启动知识库API服务 (后台运行) - 端口6788
"""
import sys
import os
import subprocess
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
pid_file = Path("/tmp/knowledge_api.pid")


def start_knowledge_api():
    """启动知识库API服务"""
    
    # 检查是否已运行
    if pid_file.exists():
        try:
            with open(pid_file, 'r') as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"⚠️ 知识库API已在运行 (PID: {old_pid})")
            return False
        except (OSError, ValueError):
            pid_file.unlink()
    
    # 获取Python路径
    venv_python = project_root / "venv" / "bin" / "python3"
    if not venv_python.exists():
        venv_python = project_root / "venv" / "bin" / "python"
    
    # 启动服务
    api_script = project_root / "scripts" / "knowledge_api.py"
    
    # 创建日志目录
    log_dir = project_root / "logs" / "knowledge"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "knowledge_api.log"

    # 端口从 gateway.yaml local_ports.knowledge_api 读取（单一事实源）
    # config 是真正的 Python 包（src/config），需把 src 也加入 sys.path
    # 注意用 append 而非 insert(0)：src/ 下有与 pip 同名的模块（如 src/mcp/），
    # 若放最前会遮蔽 pip 的 mcp 包，导致 `import mcp.types` 失败。
    sys.path.append(str(project_root / "src"))
    sys.path.append(str(project_root))
    from config.port_loader import knowledge_api_port
    kb_port = knowledge_api_port(6788)
    
    # 启动进程（日志用追加模式，保留失败记录便于排查）
    from src.utils.logging_setup import write_startup_banner
    write_startup_banner(log_file, service_name="knowledge_api")
    log_fp = open(log_file, 'a', encoding='utf-8')
    # 子进程不继承 PYTHONPATH，避免 src/ 遮蔽 venv 的 mcp 包
    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)
    proc = subprocess.Popen(
        [str(venv_python), str(api_script), "--host", "0.0.0.0", "--port", str(kb_port)],
        cwd=str(project_root),
        env=child_env,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    
    # 保存PID
    with open(pid_file, 'w') as f:
        f.write(str(proc.pid))
    
    # 等待服务初始化（加载嵌入模型等耗时操作）
    init_wait = 3
    print(f"⏳ 等待知识库初始化 ({init_wait}秒)...")
    time.sleep(init_wait)
    
    # 轮询检查服务健康（最多等待10秒，每1秒重试一次）
    import urllib.request
    import json
    max_retries = 10
    for attempt in range(max_retries):
        time.sleep(1)
        try:
            req = urllib.request.Request(f"http://localhost:{kb_port}/knowledge/health")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    body = resp.read().decode('utf-8')
                    try:
                        data = json.loads(body)
                        status = data.get("status", "unknown")
                        docs = data.get("total_documents", 0)
                        chunks = data.get("total_chunks", 0)
                        print(f"✅ 知识库API已启动 (PID: {proc.pid})")
                        print(f"   状态: {status} | 文档: {docs} | 切片: {chunks}")
                    except json.JSONDecodeError:
                        print(f"✅ 知识库API已启动 (PID: {proc.pid})")
                    print(f"   http://localhost:{kb_port}/knowledge/health")
                    print(f"   http://localhost:{kb_port}/docs")
                    return True
        except Exception:
            if attempt == 0:
                print(f"   ⏳ 服务正在初始化... (第{attempt+1}次检测)")
            continue
    
    print("⚠️ 知识库API启动失败，请检查日志")
    print(f"   tail -f {log_file}")
    return False


def stop_knowledge_api():
    """停止知识库API服务"""
    if not pid_file.exists():
        print("ℹ️ 知识库API未运行")
        return True
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        os.kill(pid, 15)
        pid_file.unlink()
        print(f"✅ 知识库API已停止 (PID: {pid})")
        return True
    except Exception as e:
        print(f"⚠️ 停止失败: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop_knowledge_api()
    else:
        start_knowledge_api()
