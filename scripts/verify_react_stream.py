# -*- coding: utf-8 -*-
"""
v4.1 ReAct 正文流式输出 + 评估后台化 验证脚本

覆盖接口（与本次修改相关的系统）：
- POST /api/v2/chat                   非流式对话（检查 events 含 message_end、data.response 非空）
- POST /api/v2/chat/stream            SSE 流式对话（核心：验证事件顺序与 message 实时输出）
- GET  /api/v2/sessions/{id}/messages 会话历史（验证 assistant 消息落库）
- GET  /api/v2/sessions/{id}/usage    会话上下文占用统计
- DELETE /api/v2/sessions/deleteSession/{id}  清理测试会话

验证点（本次修改核心）：
1. 流式事件顺序：think_start → think → think_end → message_start → message(≥1) → message_end
2. think_end 在 message_start 之前（思考结束标记提前，不再等正文生成完）
3. message_start 在第一个 message 之前，且 message_start 仅出现一次
4. 正文 message 事件 ≥ 1（正文 token 实时流式转发，不再一次性 message_end）
5. message_end.assessment 为 None 或缺失（评估已后台化，不再阻塞响应）
6. message_end.usage 结构完整

用法：
    python scripts/verify_react_stream.py [--base URL] [--keep]

    --base 网关地址，默认 http://172.20.51.153:6789
    --keep 执行后保留脚本（默认验证成功后删除自身）

行为：
    1. 连通性检查（失败则报告并退出，保留脚本，等待部署后重跑）
    2. 执行全部用例，逐条记录 PASS / FAIL / WARN
    3. 结果保存为 docs/verify_results/ReAct流式验证结果_*.txt
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
_CREATED_SESSIONS = []  # 测试会话（最后统一清理）


def _log(status: str, name: str, detail: str = ""):
    line = f"[{status:^5}] {name} {detail}"
    RESULTS.append(line)
    print(line, flush=True)


def _req(method: str, path: str, body: dict = None, timeout: int = 180):
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


def _req_sse(path: str, body: dict, timeout: int = 180):
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
                            # 解信封：data.event_type + data.data
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


def _check_usage(u: dict, ctx: str) -> bool:
    """校验 usage 结构完整性。"""
    if not isinstance(u, dict) or not u:
        _log("FAIL", ctx, "usage 缺失或为空")
        return False
    ok = True
    for k in ("prompt_tokens", "completion_tokens", "context_length", "used_percent", "free_space",
              "categories", "source", "auto_compact_buffer", "compacted", "model"):
        if k not in u:
            _log("FAIL", ctx, f"usage 缺少字段: {k}")
            ok = False
    if ok:
        pct = u.get("used_percent", -1)
        total = u.get("context_length", 0)
        prompt = u.get("prompt_tokens", 0)
        if not (0 <= pct <= 100):
            _log("FAIL", ctx, f"used_percent 越界: {pct}")
            ok = False
        if not (0 < prompt <= total):
            _log("FAIL", ctx, f"prompt_tokens 不合理: {prompt} / context_length={total}")
            ok = False
    if ok:
        _log("PASS", ctx, f"used_percent={u.get('used_percent')}% "
                          f"({u.get('prompt_tokens')}/{u.get('context_length')} tokens, source={u.get('source')})")
    return ok


def case_connectivity() -> bool:
    code, data = _req("GET", "/api/v2/sessions", timeout=30)
    if code == 200 and data.get("success", False) is True:
        _log("PASS", "连通性", f"GET /api/v2/sessions -> {code}")
        return True
    _log("FAIL", "连通性", f"GET /api/v2/sessions -> {code} {json.dumps(data, ensure_ascii=False)[:200]}")
    return False


def case_chat_stream() -> bool:
    """核心用例：SSE 流式对话，验证 v4.1 事件顺序与 message 实时输出。"""
    sid = f"v41_stream_{datetime.now().strftime('%H%M%S')}"
    code, events = _req_sse("/api/v2/chat/stream", {
        "message": "写一个 python 脚本打印 hello world 并运行",
        "session_id": sid,
        "user_id": USER,
        "agent_id": "code_writer",
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not events:
        _log("FAIL", "流式对话", f"SSE 无事件或失败 code={code}")
        return False

    types = [e.get("type") for e in events]
    ok = True
    ctx = "流式事件顺序"

    # 1. 关键事件齐全
    for need in ("think_start", "think", "think_end", "message_start", "message", "message_end"):
        if need not in types:
            _log("FAIL", ctx, f"缺少事件: {need} | 实际序列={types}")
            ok = False
    if not ok:
        return False

    # 2. 顺序：think_end < message_start < message < message_end
    idx_think_end = types.index("think_end")
    idx_msg_start = types.index("message_start")
    idx_msg = types.index("message")
    idx_msg_end = types.index("message_end")
    if not (idx_think_end < idx_msg_start < idx_msg < idx_msg_end):
        _log("FAIL", ctx, f"顺序错误(think_end={idx_think_end} msg_start={idx_msg_start} msg={idx_msg} msg_end={idx_msg_end})")
        ok = False
    else:
        _log("PASS", ctx, f"think_end→message_start→message→message_end 顺序正确")

    # 3. message_start 仅 1 次
    n_start = types.count("message_start")
    if n_start != 1:
        _log("FAIL", ctx, f"message_start 出现 {n_start} 次（应为 1 次）")
        ok = False

    # 4. 正文 message 事件数（实时流式转发）
    n_msg = types.count("message")
    if n_msg < 1:
        _log("FAIL", ctx, f"message 正文增量事件数={n_msg}（应 ≥1，正文未实时流式）")
        ok = False
    else:
        _log("PASS", ctx, f"message 正文增量事件数={n_msg}（正文实时流式转发）")

    # 5. 拼接 message chunks 应与 message_end.full_response 一致
    chunks = "".join(e.get("data", {}).get("chunk", "") for e in events if e.get("type") == "message")
    full = ""
    for e in events:
        if e.get("type") == "message_end":
            full = e.get("data", {}).get("full_response", "")
    if chunks and full and chunks.strip() != full.strip():
        _log("WARN", "正文一致性", "message 拼接与 message_end.full_response 不完全一致（首尾空白差异可忽略）")

    # 6. message_end.assessment 为 None 或缺失（评估后台化）
    end_data = {}
    for e in events:
        if e.get("type") == "message_end":
            end_data = e.get("data", {})
    if "assessment" in end_data and end_data.get("assessment") is not None:
        _log("FAIL", "评估后台化", f"message_end.assessment 应为 None，实际={end_data.get('assessment')}")
        ok = False
    else:
        _log("PASS", "评估后台化", "message_end.assessment=None（评估不阻塞响应）")

    # 7. usage 结构
    _check_usage(end_data.get("usage"), "message_end.usage")

    _log("PASS" if ok else "FAIL", "流式对话", f"事件总数={len(events)}")
    return ok


def case_chat_non_stream() -> bool:
    """非流式对话：data.response 非空，events 含 message_end。"""
    sid = f"v41_ns_{datetime.now().strftime('%H%M%S')}"
    code, data = _req("POST", "/api/v2/chat", {
        "message": "你好",
        "session_id": sid,
        "user_id": USER,
        "agent_id": "dfecrab",
    })
    _CREATED_SESSIONS.append(sid)
    if code != 200 or not data.get("success", False):
        _log("FAIL", "非流式对话", f"code={code} {json.dumps(data, ensure_ascii=False)[:200]}")
        return False
    resp = data.get("data", {}).get("response", "")
    if not resp:
        _log("FAIL", "非流式对话", "data.response 为空")
        return False
    events = data.get("data", {}).get("events", [])
    etypes = [e.get("type") for e in events]
    if "message_end" not in etypes:
        _log("FAIL", "非流式对话", "events 中缺少 message_end")
        return False
    _log("PASS", "非流式对话", f"response_len={len(resp)}, events={len(events)}")
    return True


def case_session_history(sid: str) -> bool:
    """历史回看：assistant 消息已落库。"""
    code, data = _req("GET", f"/api/v2/sessions/{sid}/messages", timeout=30)
    if code != 200:
        _log("FAIL", "会话历史", f"GET messages code={code}")
        return False
    msgs = data.get("data", {}).get("messages", data.get("messages", []))
    assistants = [m for m in msgs if m.get("role") == "assistant"]
    if not assistants:
        _log("WARN", "会话历史", f"会话 {sid} 无 assistant 消息（模型可能未返回内容）")
        return True
    has_full = any(m.get("content") for m in assistants)
    _log("PASS" if has_full else "WARN", "会话历史",
         f"assistant 消息 {len(assistants)} 条, content 非空={has_full}")
    return has_full


def case_session_usage(sid: str) -> bool:
    """会话上下文占用统计接口。"""
    code, data = _req("GET", f"/api/v2/sessions/{sid}/usage", timeout=30)
    if code == 200:
        _log("PASS", "会话 usage", f"GET /sessions/{sid}/usage -> {code}")
        return True
    _log("WARN", "会话 usage", f"GET /sessions/{sid}/usage -> {code}（旧版本可能无此接口，可忽略）")
    return False


def cleanup():
    for sid in _CREATED_SESSIONS:
        _req("DELETE", f"/api/v2/sessions/deleteSession/{sid}", timeout=30)
    _log("INFO", "清理", f"已清理 {len(_CREATED_SESSIONS)} 个测试会话")


def save_result():
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "verify_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"ReAct流式验证结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    lines = [
        f"ReAct 正文流式 + 评估后台化 验证结果",
        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"网关: {BASE}",
        f"用户: {USER}",
        "=" * 60,
        *RESULTS,
        "=" * 60,
    ]
    fname.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n结果已保存: {fname}")
    return fname


def main():
    global BASE, KEEP
    ap = argparse.ArgumentParser(description="v4.1 ReAct 正文流式 + 评估后台化 验证")
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

    passed = 0
    failed = 0
    ok1 = case_chat_stream()
    ok2 = case_chat_non_stream()

    # 用流式用例创建的会话做历史/usage 回看
    if _CREATED_SESSIONS:
        sid = _CREATED_SESSIONS[-1]
        ok3 = case_session_history(sid)
        case_session_usage(sid)
    else:
        ok3 = False

    passed += int(ok1) + int(ok2) + int(ok3)
    failed = 3 - passed

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
