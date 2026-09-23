"""
记忆接口全量测试脚本

功能：
    1. 跑完所有记忆相关接口（全局 / Agent私有 / 用户级记忆 / 权限）
    2. 结果保存为 memory_api_test_report_<时间戳>.txt
    3. 测试写入的用户级记忆自动删除（清理测试数据）

用法：
    python scripts/test_memory_api.py [HOST] [USER] [OTHER_USER]

默认：
    HOST    = http://172.20.51.153:6789
    USER    = admin
    OTHER   = zhangsan（用于越权测试）

依赖：仅标准库（urllib / json），无需第三方包。
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from urllib.parse import quote

HOST = (sys.argv[1] if len(sys.argv) > 1 else "http://172.20.51.153:6789").rstrip("/")
USER = sys.argv[2] if len(sys.argv) > 2 else "admin"
OTHER = sys.argv[3] if len(sys.argv) > 3 else "zhangsan"

REPORT = f"memory_api_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
_lines: list = []


def log(*args) -> None:
    s = " ".join(str(a) for a in args)
    print(s)
    _lines.append(s)


def _call(method: str, path: str, headers: dict = None, body: dict = None):
    """发起 HTTP 请求，返回 (status, parsed_json 或错误文本)"""
    url = HOST + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw
    except Exception as e:
        return -1, str(e)


def _trunc(obj, length: int = 260) -> str:
    return json.dumps(obj, ensure_ascii=False)[:length]


def main() -> None:
    log("=" * 64)
    log(f"记忆接口全量测试  HOST={HOST}  USER={USER}  OTHER={OTHER}")
    log(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 64)

    created_mem_id = None
    created_key = None

    # ---------- 1. 全局记忆接口（按用户） ----------
    log("\n【1. 全局记忆接口】")
    global_cases = [
        ("stats",        f"/api/memory/stats?user_id={USER}"),
        ("recent",       f"/api/memory/recent?user_id={USER}"),
        ("files",        f"/api/memory/files?user_id={USER}"),
        ("storage",      f"/api/memory/storage?user_id={USER}"),
        ("search", f"/api/memory/search?q={quote('调度')}&user_id={USER}"),
        ("index_health", f"/api/memory/index_health"),
    ]
    for name, path in global_cases:
        status, body = _call("GET", path, {"X-User-Id": USER})
        log(f"[{status}] {name}  {path}")
        log(f"        -> {_trunc(body)}")

    # ---------- 2. Agent 私有记忆（按用户） ----------
    log("\n【2. Agent 私有记忆】")
    for agent in ["kunming", "dfecrab", "code_writer", "knowledge_agent", "manager_agent"]:
        status, body = _call("GET", f"/api/memory/agents/{agent}?user_id={USER}", {"X-User-Id": USER})
        log(f"[{status}] agent_memory[{agent}]")
        log(f"        -> {_trunc(body)}")

    status, body = _call("GET", f"/api/memory/agents?user_id={USER}", {"X-User-Id": USER})
    log(f"[{status}] agents_summary")
    log(f"        -> {_trunc(body)}")

    # ---------- 3. 用户级记忆 CRUD（含自动清理） ----------
    log("\n【3. 用户级记忆 CRUD】")
    status, body = _call("GET", f"/api/memory/users?user_id={USER}", {"X-User-Id": USER})
    log(f"[{status}] users_list")
    log(f"        -> {_trunc(body)}")

    created_key = f"__test_{datetime.now().strftime('%H%M%S')}"
    status, body = _call("POST", f"/api/memory/users/{USER}", {"X-User-Id": USER},
                         {"key": created_key, "content": "测试内容", "tags": ["test"]})
    log(f"[{status}] users_create key={created_key}")
    log(f"        -> {_trunc(body)}")

    if isinstance(body, dict) and body.get("success"):
        created_mem_id = (body.get("data") or {}).get("id")
        if created_mem_id:
            status2, body2 = _call("PUT", f"/api/memory/users/{USER}/{created_mem_id}",
                                   {"X-User-Id": USER}, {"content": "更新后的测试内容"})
            log(f"[{status2}] users_update id={created_mem_id}")
            log(f"        -> {_trunc(body2)}")

            status3, body3 = _call("DELETE", f"/api/memory/users/{USER}/{created_mem_id}", {"X-User-Id": USER})
            log(f"[{status3}] users_delete(清理) id={created_mem_id}")
            log(f"        -> {_trunc(body3)}")

    # ---------- 4. 权限验证 ----------
    log("\n【4. 权限验证】")
    for desc, path in [
        (f"{OTHER} 访问 {USER} 的 agent 记忆(应无权限)",
         f"/api/memory/agents/kunming?user_id={USER}"),
        (f"{OTHER} 访问 {USER} 的 stats(应无权限)",
         f"/api/memory/stats?user_id={USER}"),
        (f"{OTHER} 访问 {USER} 的用户级记忆(应无权限)",
         f"/api/memory/users?user_id={USER}"),
    ]:
        status, body = _call("GET", path, {"X-User-Id": OTHER})
        log(f"[{status}] {desc}")
        log(f"        -> {_trunc(body)}")

    # ---------- 5. 汇总 ----------
    log("\n" + "=" * 64)
    log("测试完成")
    log(f"测试写入的用户级记忆: key={created_key}, id={created_mem_id}")
    log(f"清理状态: {'已自动删除 ✅' if created_mem_id else '无测试数据（无需清理）'}")
    log(f"报告已保存: {REPORT}")
    log("=" * 64)

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(_lines) + "\n")


if __name__ == "__main__":
    main()
