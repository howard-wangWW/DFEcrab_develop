# -*- coding: utf-8 -*-
"""
对话链路 Bug 修复验证脚本（批次一~三）

覆盖本次修改相关的接口：
- POST /api/v2/chat               非流式对话（chat 直答 → message_end）
- POST /api/v2/chat/stream        SSE 流式（★核心：验证 message 事件已恢复）
- 工具调用（天气）                验证工具按意图筛选注入（tool_call 精简）
- MCP（转电预案）                 验证 MCP 工具保留
- knowledge_base 直答             验证短路分支
- 无 agent_id（Manager 决策）     验证 Manager 决策不再是"JSON 解析失败"

用法：
    python scripts/verify_fix.py [--base URL] [--keep]

    --base 网关地址，默认 http://172.20.51.153:6789
    --keep 执行后保留脚本（默认验证成功后删除自身）

行为：
    1. 连通性检查
    2. 执行全部用例，逐条记录 PASS / FAIL / WARN
    3. 结果保存 docs/verify_results/对话修复验证结果_*.txt
    4. 清理测试会话
    5. 验证成功后默认删除脚本自身
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "http://172.20.51.153:6789"
USER = "admin"
KEEP = False

RESULTS = []
_CREATED_SESSIONS = []


def _log(status: str, name: str, detail: str = ""):
    line = f"[{status:^5}] {name} {detail}"
    RESULTS.append(line)
    print(line, flush=True)


def _req(method: str, path: str, body: dict = None, timeout: int = 240):
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
            return e.code, {"raw": raw}
    except Exception as e:
        return 0, {"error": str(e)}


def _req_sse(path: str, body: dict, timeout: int = 240):
    """SSE 流式请求：逐行解析 data: 事件，遇 message_end 停止。返回 (状态码, 事件列表)。"""
    url = BASE.rstrip("/") + path
    payload = json.dumps(body).encode("utf-8")
    headers = {"X-User-Id": USER, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    events = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            buf = ""
            while True:
                chunk = r.read(4096).decode("utf-8", "ignore")
                if not chunk:
                    break
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if not data_str:
                            continue
                        try:
                            ev = json.loads(data_str)
                            inner = ev.get("data", {})
                            if isinstance(inner, dict) and "event_type" in inner:
                                events.append({
                                    "type": inner["event_type"],
                                    "data": inner.get("data", {}),
                                })
                            else:
                                events.append(ev)
                            if events and events[-1].get("type") == "message_end":
                                return 200, events
                        except json.JSONDecodeError:
                            continue
        return 200, events
    except Exception as e:
        return 0, [{"type": "error", "data": {"message": str(e)}}]


def case_connectivity() -> bool:
    code, data = _req("GET", "/api/v2/sessions", timeout=30)
    if code == 200 and data.get("success", False) is True:
        _log("PASS", "连通性", f"GET /api/v2/sessions -> {code}")
        return True
    _log("FAIL", "连通性", f"GET /api/v2/sessions -> {code} {json.dumps(data, ensure_ascii=False)[:200]}")
    return False


def case_chat_non_stream() -> bool:
    """非流式 chat 直答：data.response 非空，events 含 message_end。"""
    sid = f"fix_ns_{datetime.now().strftime('%H%M%S')}"
    code, data = _req("POST", "/api/v2/chat", {
        "message": "你好", "session_id": sid, "user_id": USER, "agent_id": "dfecrab",
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not data.get("success", False):
        _log("FAIL", "非流式对话", f"code={code} {json.dumps(data, ensure_ascii=False)[:200]}")
        return False
    resp = data.get("data", {}).get("response", "")
    etypes = [e.get("type") for e in data.get("data", {}).get("events", [])]
    ok = bool(resp) and "message_end" in etypes
    _log("PASS" if ok else "FAIL", "非流式对话",
         f"response_len={len(resp)}, message_end={('message_end' in etypes)}")
    return ok


def case_chat_stream_message() -> bool:
    """★核心：流式对话必须出现 message 正文事件（Fix-1 验证）。"""
    sid = f"fix_msg_{datetime.now().strftime('%H%M%S')}"
    code, events = _req_sse("/api/v2/chat/stream", {
        "message": "烟台今天天气怎么样", "session_id": sid, "user_id": USER, "agent_id": "dfecrab",
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not events:
        _log("FAIL", "流式-message事件", f"SSE 无事件或失败 code={code}")
        return False
    types = [e.get("type") for e in events]
    n_msg = types.count("message")
    n_start = types.count("message_start")
    n_end = types.count("message_end")
    # 顺序：think_end < message_start < message < message_end
    ok_order = True
    for a, b in (("think_end", "message_start"), ("message_start", "message"), ("message", "message_end")):
        if a in types and b in types and types.index(a) > types.index(b):
            ok_order = False
    ok = n_msg >= 1 and n_start >= 1 and n_end >= 1 and ok_order
    _log("PASS" if ok else "FAIL", "流式-message事件",
         f"message={n_msg}, start={n_start}, end={n_end}, 顺序正确={ok_order}")
    return ok


def case_tool_filter() -> bool:
    """工具按意图筛选：天气请求 tool_call 应为 weather，且 tools 不应全量注入。"""
    sid = f"fix_tool_{datetime.now().strftime('%H%M%S')}"
    code, events = _req_sse("/api/v2/chat/stream", {
        "message": "烟台今天天气怎么样", "session_id": sid, "user_id": USER, "agent_id": "dfecrab",
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not events:
        _log("FAIL", "工具筛选", f"SSE 失败 code={code}")
        return False
    tool_calls = [e["data"].get("tool_name", "") for e in events if e.get("type") == "tool_call"]
    ok = bool(tool_calls) and all(t in ("weather", "weather-forecast") for t in tool_calls)
    _log("PASS" if ok else "FAIL", "工具筛选",
         f"tool_call={tool_calls}（期望 weather，非 31 工具全量）")
    return ok


def case_mcp() -> bool:
    """MCP 工具保留：转电预案应触发电网 MCP 工具（search_feeders/get_feeder_topology 等）。"""
    sid = f"fix_mcp_{datetime.now().strftime('%H%M%S')}"
    code, events = _req_sse("/api/v2/chat/stream", {
        "message": "请你制定F19地王一线的转电预案",
        "session_id": sid, "user_id": USER, "agent_id": "dfecrab",
        "mcp": ["blackxml_topology", "demo"],
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not events:
        _log("FAIL", "MCP工具", f"SSE 失败 code={code}")
        return False
    tool_calls = [e["data"].get("tool_name", "") for e in events if e.get("type") == "tool_call"]
    ok = bool(tool_calls)
    _log("PASS" if ok else "WARN", "MCP工具",
         f"tool_call={tool_calls[:6]}（MCP 工具应被保留并可调用）")
    return ok


def case_knowledge_base() -> bool:
    """knowledge_base 短路分支：message_end 带 content 与 sources。"""
    sid = f"fix_kb_{datetime.now().strftime('%H%M%S')}"
    code, data = _req("POST", "/api/v2/chat", {
        "message": "调度操作的基本要求是什么", "session_id": sid, "user_id": USER,
        "knowledge_base": True, "kb_top_k": 5,
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not data.get("success", False):
        _log("FAIL", "知识库直答", f"code={code} {json.dumps(data, ensure_ascii=False)[:200]}")
        return False
    resp = data.get("data", {}).get("response", "")
    ok = bool(resp)
    _log("PASS" if ok else "FAIL", "知识库直答", f"response_len={len(resp)}")
    return ok


def case_manager_decision() -> bool:
    """Manager 决策：无 agent_id 请求的 manager_decision 不应仍是"JSON 解析失败"降级。"""
    sid = f"fix_mgr_{datetime.now().strftime('%H%M%S')}"
    code, data = _req("POST", "/api/v2/chat", {
        "message": "你是谁", "session_id": sid, "user_id": USER,
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not data.get("success", False):
        _log("FAIL", "Manager决策", f"code={code} {json.dumps(data, ensure_ascii=False)[:200]}")
        return False
    md = next((e["data"] for e in data.get("data", {}).get("events", [])
               if e.get("type") == "manager_decision"), None)
    if not md:
        _log("WARN", "Manager决策", "未捕获 manager_decision 事件")
        return False
    reasoning = str(md.get("reasoning", ""))
    ok = "JSON 解析失败" not in reasoning and "降级" not in reasoning
    _log("PASS" if ok else "WARN", "Manager决策",
         f"intent={md.get('intent')}, target={md.get('target_agent')}, reasoning={reasoning[:60]}")
    return ok


def cleanup():
    for sid in _CREATED_SESSIONS:
        _req("DELETE", f"/api/v2/sessions/deleteSession/{sid}", timeout=30)
    _log("INFO", "清理", f"已清理 {len(_CREATED_SESSIONS)} 个测试会话")


def save_result():
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "verify_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"对话修复验证结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    lines = [
        "对话链路 Bug 修复（批次一~三）验证结果",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"网关: {BASE}",
        "=" * 60,
        *RESULTS,
        "=" * 60,
    ]
    fname.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n结果已保存: {fname}")
    return fname


def main():
    global BASE, KEEP
    ap = argparse.ArgumentParser(description="对话链路 Bug 修复验证")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--keep", action="store_true", help="保留脚本（默认验证成功后删除自身）")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    KEEP = args.keep

    _log("INFO", "开始", f"网关={BASE}")
    if not case_connectivity():
        _log("INFO", "结束", "连通性失败，保留脚本，部署后重跑")
        save_result()
        sys.exit(1)

    cases = [
        ("非流式对话", case_chat_non_stream),
        ("流式-message事件", case_chat_stream_message),
        ("工具筛选", case_tool_filter),
        ("MCP工具", case_mcp),
        ("知识库直答", case_knowledge_base),
        ("Manager决策", case_manager_decision),
    ]
    passed = 0
    for name, fn in cases:
        try:
            if fn():
                passed += 1
        except Exception as e:
            _log("FAIL", name, f"异常: {e}")

    failed = len(cases) - passed
    cleanup()
    save_result()

    if failed == 0 and not KEEP:
        try:
            os.remove(__file__)
            print(f"✅ 验证通过，脚本已自动删除: {os.path.basename(__file__)}")
        except OSError as e:
            print(f"⚠️ 脚本删除失败（可手动删）: {e}")
    sys.exit(0 if failed == 0 else 2)


if __name__ == "__main__":
    main()
