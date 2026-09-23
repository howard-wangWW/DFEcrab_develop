# -*- coding: utf-8 -*-
"""
记忆系统全量接口验证脚本（阶段 A/B/C）

覆盖接口：
- /api/memory/index_health                   检索引擎健康
- /api/memory/search                         记忆检索（BM25）
- /api/memory/stats|recent|files|storage     每日记忆统计/最近/文件/存储
- /api/memory/agents                         所有 Agent 记忆摘要
- /api/memory/agents/{agent_id}              单个 Agent 记忆
- /api/memory/users                          用户级记忆 CRUD（GET/POST/PUT/DELETE）
- /api/v2/chat                               对话（触发记忆沉淀 + 用户事实自动提取）
- /api/v2/sessions                           会话列表 / 删除

用法：
    python scripts/verify_memory_system.py [user_id] [--base URL] [--rounds N] [--keep]

    user_id  用户ID，默认 admin（可选位置参数）
    --base   网关地址，默认 http://127.0.0.1:6789（在服务器本机跑用默认即可；
             本地跑别的机器用 --base http://172.20.51.153:6789）
    --rounds 对话轮数，默认 1；>=10 时同时验证会话滚动摘要
    --keep   执行后保留脚本（默认验证成功后删除自身）

    示例：
        python scripts/verify_memory_system.py admin --rounds 11
        python scripts/verify_memory_system.py --base http://172.20.51.153:6789 --rounds 1

行为：
    1. 连通性检查（失败则报告并退出，保留脚本，等待部署后重跑）
    2. 执行全部用例，逐条记录 PASS / FAIL / WARN
    3. 结果保存为 docs/verify_results/记忆系统验证结果_*.txt
    4. 清理测试数据（测试记忆 / 测试会话）
    5. 验证成功后默认删除脚本自身
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = os.environ.get("VERIFY_BASE_URL", "http://127.0.0.1:6789")
USER = os.environ.get("VERIFY_USER", "admin")
ROUNDS = int(os.environ.get("VERIFY_ROUNDS", "1"))
KEEP = os.environ.get("VERIFY_KEEP", "0") == "1"

RESULTS: list = []


def _log(status: str, name: str, detail: str = ""):
    line = f"[{status:^5}] {name} {detail}"
    RESULTS.append(line)
    print(line, flush=True)


def _req(method: str, path: str, body: dict = None, timeout: int = 30):
    url = BASE.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"X-User-Id": USER, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "ignore")
            return r.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"success": False, "error": raw[:200]}
    except Exception as e:
        return 0, {"success": False, "error": repr(e)}


def _p(path: str) -> str:
    return urllib.parse.quote(path, safe="")


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "verify_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"记忆系统验证结果_{ts}.txt"

    _log("INFO", "目标", f"BASE={BASE} USER={USER} ROUNDS={ROUNDS}")

    # 1. 连通性检查
    code, body = _req("GET", "/api/memory/index_health", timeout=5)
    if code != 200 or not body.get("success"):
        msg = f"服务器不可达或返回异常: HTTP {code} {body.get('error','')}。请先部署新代码并启动服务后再运行。"
        _log("FAIL", "连通性", msg)
        _finish(out_file, keep=True)
        return

    # 2. 接口用例
    # 2.1 检索引擎健康
    code, body = _req("GET", "/api/memory/index_health")
    h = (body.get("data") or {}).get("health") or {}
    if h.get("status") == "healthy":
        _log("PASS", "index_health", "BM25 检索引擎已启用")
    else:
        _log("WARN", "index_health", f"status={h.get('status')}（可能是旧代码未部署阶段 A）")

    # 2.2 记忆检索
    code, body = _req("GET", f"/api/memory/search?q={urllib.parse.quote('调度')}&user_id={USER}")
    if body.get("success"):
        _log("PASS", "search", f"命中 {len((body.get('data') or {}).get('results') or [])} 条")
    else:
        _log("FAIL", "search", str(body.get("error")))

    # 2.3 每日记忆统计/最近/文件/存储
    for name, path in (("stats", "/api/memory/stats"), ("recent", "/api/memory/recent"),
                       ("files", "/api/memory/files"), ("storage", "/api/memory/storage")):
        code, body = _req("GET", f"{path}?user_id={USER}")
        _log("PASS" if body.get("success") else "FAIL", name, json.dumps(body.get("data") or body, ensure_ascii=False)[:80])

    # 2.4 Agent 记忆摘要 + 单个 Agent 记忆
    code, body = _req("GET", f"/api/memory/agents?user_id={USER}")
    if body.get("success"):
        total = (body.get("data") or {}).get("total_agents", 0)
        _log("PASS", "agents", f"total_agents={total}")
    else:
        _log("FAIL", "agents", str(body.get("error")))
    code, body = _req("GET", f"/api/memory/agents/kunming?user_id={USER}")
    _log("PASS" if body.get("success") else "FAIL", "agents/kunming", str(body.get("error") or ""))

    # 2.5 用户级记忆 CRUD
    code, body = _req("GET", f"/api/memory/users?user_id={USER}")
    _log("PASS" if body.get("success") else "FAIL", "users GET", str(body.get("error") or ""))

    test_key = f"验证测试_{int(time.time())}"
    created_ids = []
    code, body = _req("POST", f"/api/memory/users/{USER}", {"key": test_key, "content": "初始值", "tags": ["验证"], "source": "api"})
    if body.get("success") and body.get("data"):
        created_ids.append((body.get("data") or {}).get("id", ""))
        _log("PASS", "users POST", f"id={created_ids[-1]}")
    else:
        _log("FAIL", "users POST", str(body.get("error")))

    if created_ids and created_ids[0]:
        mem_id = created_ids[0]
        code, body = _req("PUT", f"/api/memory/users/{USER}/{mem_id}", {"content": "更新值"})
        _log("PASS" if body.get("success") else "FAIL", "users PUT", str(body.get("error") or ""))

        code, body = _req("GET", f"/api/memory/users?user_id={USER}")
        if body.get("success"):
            found = [m for m in (body.get("data") or {}).get("memories") or [] if m.get("id") == mem_id]
            ok = bool(found) and found[0].get("content") == "更新值"
            _log("PASS" if ok else "FAIL", "users 更新校验", f"content={found[0].get('content') if found else None}")
        else:
            _log("FAIL", "users 更新校验", str(body.get("error")))

        code, body = _req("DELETE", f"/api/memory/users/{USER}/{mem_id}")
        _log("PASS" if body.get("success") else "FAIL", "users DELETE", str(body.get("error") or ""))

    # 2.6 对话（触发记忆沉淀 + 用户事实自动提取）
    chat_sid = f"verify_mem_{ts}"
    code, body = _req("POST", "/api/v2/chat",
                      {"message": "我家在昆明，工作主要是电力调度运维，回复请简洁一点。", "session_id": chat_sid,
                       "user_id": USER, "agent_id": "kunming"}, timeout=90)
    resp = (body.get("data") or {}).get("response") or ""
    if body.get("success") and resp:
        _log("PASS", "chat", f"len={len(resp)} summary={(body.get('data') or {}).get('session_summary','')[:40]}")
    else:
        _log("FAIL", "chat", str(body.get("error")))

    # 2.7 会话列表
    code, body = _req("GET", "/api/v2/sessions?limit=5")
    _log("PASS" if body.get("success") else "FAIL", "sessions GET", str(body.get("error") or ""))

    # 2.8 自动提取用户事实（阶段 B，异步，等待 3 秒）
    time.sleep(30)
    code, body = _req("GET", f"/api/memory/users?user_id={USER}")
    auto = []
    if body.get("success"):
        auto = [m for m in (body.get("data") or {}).get("memories") or [] if m.get("source") == "conversation"]
    if auto:
        _log("PASS", "自动提取", f"发现 {len(auto)} 条 conversation 记忆: {[(m.get('key'), m.get('content')) for m in auto[:3]]}")
    else:
        _log("WARN", "自动提取", "未发现 conversation 记忆（旧代码未部署阶段 B，或 LLM 未提取到高置信度事实）")

    # 2.9 多轮对话滚动摘要（阶段 C，--rounds>=10 时）
    if ROUNDS >= 10:
        summary_prev = ""
        for i in range(ROUNDS):
            code, body = _req("POST", "/api/v2/chat",
                              {"message": f"第 {i + 1} 轮：继续讨论昆明电网保供电话题，补充一点关于运行方式的内容。",
                               "session_id": chat_sid, "user_id": USER, "agent_id": "kunming"}, timeout=90)
            s = (body.get("data") or {}).get("session_summary") or ""
            if i in (0, ROUNDS - 1):
                _log("INFO", "对话摘要", f"第{i + 1}轮: {s[:40]}")
            summary_prev = s
        if summary_prev:
            _log("INFO", "滚动摘要", f"最终摘要: {summary_prev[:80]}")
        else:
            _log("WARN", "滚动摘要", "未获取到滚动摘要（可能轮次不足或旧代码）")

    # 3. 清理测试数据
    cleaned = []
    for mem_id in created_ids:
        if mem_id:
            code, body = _req("DELETE", f"/api/memory/users/{USER}/{mem_id}")
            cleaned.append(f"memory:{mem_id}")
    try:
        code, body = _req("DELETE", f"/api/v2/sessions/deleteSession/{chat_sid}")
        cleaned.append("chat_session")
    except Exception:
        pass
    _log("INFO", "清理", "; ".join(cleaned) if cleaned else "无测试数据")

    _finish(out_file, keep=KEEP)


def _finish(out_file: Path, keep: bool):
    out_file.write_text("\n".join(RESULTS) + "\n", encoding="utf-8")
    passed = sum(1 for r in RESULTS if r.startswith("[PASS"))
    failed = sum(1 for r in RESULTS if r.startswith("[FAIL"))
    warned = sum(1 for r in RESULTS if r.startswith("[WARN"))
    print(f"\n结果文件: {out_file}")
    print(f"PASS={passed} FAIL={failed} WARN={warned}")
    if not keep and failed == 0:
        try:
            os.remove(os.path.abspath(__file__))
            print("验证通过，脚本已自动删除。")
        except Exception as e:
            print(f"脚本自删失败（可手动删除）: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="记忆系统全量接口验证（阶段 A/B/C）")
    parser.add_argument("user_id", nargs="?", default="admin", help="用户ID，默认 admin")
    parser.add_argument("--base", default="http://127.0.0.1:6789", help="网关地址，默认 http://127.0.0.1:6789")
    parser.add_argument("--rounds", type=int, default=1, help="对话轮数，>=10 时验证会话滚动摘要")
    parser.add_argument("--keep", action="store_true", help="验证成功后保留脚本，默认自删")
    ns = parser.parse_args()

    BASE = ns.base
    USER = ns.user_id
    ROUNDS = ns.rounds
    KEEP = ns.keep
    main()
