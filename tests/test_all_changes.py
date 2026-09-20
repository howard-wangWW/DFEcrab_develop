#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DFEcrab 全量修改冒烟测试（含自动清理）

覆盖：用户管理 / 权限拦截 / 会话与思考内容 / MCP 服务 / 知识库独立 API
运行：python tests/test_all_changes.py

环境要求：
  - 网关服务 (port 6789) 已启动
  - 知识库API (port 6788) 已启动（可选，跳过则知识库用例标记 SKIP）

地址配置（多现场 / 本机适配）：
  - 默认连接本机 localhost
  - 可用环境变量覆盖：
      DFECRAB_GATEWAY  (默认 http://localhost:6789)
      DFECRAB_KB_API   (默认 http://localhost:6788)

测试结束（无论通过与否）会自动清理产生的测试账号 / MCP / 会话 /
知识库文档，并删除临时文件 .qa_sid.txt、.qa_kb_docid.txt，
无需再单独运行 cleanup_test_data.py（已合并）。
"""
import json
import os
import sys
import urllib.error
import urllib.request

# ============ 配置（可用环境变量覆盖，默认本机） ============
GATEWAY = os.environ.get("DFECRAB_GATEWAY", "http://localhost:6789")
KB_API = os.environ.get("DFECRAB_KB_API", "http://localhost:6788")
ADMIN = "admin"
TEST_USER = "qa_test"           # 脚本创建/清理的测试账号
TEST_MCP = "qa_test_mcp"        # 脚本创建/清理的 MCP 服务
KB_DOC_TITLE = "qa_test_doc"    # 知识库测试文档标题


PASS = 0
FAIL = 0
SKIP = 0


def hdr(uid, ct="application/json"):
    return {"X-User-Id": uid, "Content-Type": ct}


def call(method, url, uid=ADMIN, body=None, ct="application/json"):
    if body is None:
        data = None
    elif isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    else:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers=hdr(uid, ct))
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, (r.read().decode("utf-8") or "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)


def call_json(method, path, base=GATEWAY, uid=ADMIN, body=None, ct="application/json"):
    url = base + path
    s, t = call(method, url, uid, body, ct)
    try:
        return s, (json.loads(t) if t else None)
    except Exception:
        return s, t


def check(cond, name):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name)
    else:
        FAIL += 1
        print("  [FAIL] " + name)


def skip(name, reason=""):
    global SKIP
    SKIP += 1
    print("  [SKIP] " + name + ("  (" + reason + ")" if reason else ""))


def section(t):
    print("\n==== " + t + " ====")


# ---------------------------------------------------------------------------
# 测试主体
# ---------------------------------------------------------------------------
def run_tests():
    sid = None
    doc_id = ""
    kb_ok = False

    # 1. 用户管理 + 权限模型
    section("1. 用户管理 & 权限")
    s, _ = call("GET", GATEWAY + "/api/users", uid="nobody_abc")
    check(s == 403, "陌生账号访问 /api/users 被拦截(403) -> default_role=guest 生效")
    s, users = call_json("GET", "/api/users", uid=ADMIN)
    check(s == 200, "admin 列出用户 (HTTP %s)" % s)
    s, _ = call_json("POST", "/api/users", uid=ADMIN, body={"user_id": TEST_USER, "role": "user"})
    check(s == 200, "admin 新增账号 %s(role=user)" % TEST_USER)
    s, users = call_json("GET", "/api/users", uid=ADMIN)
    user_map = users.get("users", {}) if isinstance(users, dict) else {}
    check(TEST_USER in user_map, "用户列表含 %s -> 角色=%s" % (TEST_USER, user_map.get(TEST_USER, "?")))

    # 2. guest 被拦截在鉴权层
    section("2. Q1+Q2 复现：guest 不能对话（根因 = 鉴权拦截）")
    s, _ = call("POST", GATEWAY + "/api/v2/chat", uid="nobody_abc", body={"message": "hi"})
    check(s == 403, "guest 调 /api/v2/chat -> 403")
    s, _ = call("POST", GATEWAY + "/api/v2/chat/stream", uid="nobody_abc", body={"message": "hi"})
    check(s == 403, "guest 调 /api/v2/chat/stream -> 403")

    # 3. 会话 + 对话（user 角色）
    section("3. 会话 & 对话（user 角色）")
    s, sess = call_json("POST", "/api/v2/sessions", uid=TEST_USER, body={"topic": "qa_test"})
    session = sess.get("session", {}) if isinstance(sess, dict) else {}
    sid = session.get("id")
    check(s == 200 and sid, "user 创建会话 (sid=%s)" % sid)

    s, _ = call_json("POST", GATEWAY + "/api/v2/chat", uid=TEST_USER,
                     body={"message": "你好", "session_id": sid, "agent_id": "dfecrab"})
    check(s == 200, "user 调 chat(dfecrab) 成功 -> 拿到了 message_end")
    s, _ = call_json("POST", GATEWAY + "/api/v2/chat", uid=TEST_USER,
                     body={"message": "写一段 python 打印 hello world",
                           "session_id": sid, "agent_id": "code_writer"})
    check(s == 200, "user 调 chat(code_writer) 成功")

    s, msgs = call_json("GET", "/api/v2/sessions/%s/messages?limit=50" % sid, uid=TEST_USER)
    msg_list = msgs.get("messages", []) if isinstance(msgs, dict) else []
    check(s == 200 and isinstance(msgs, dict), "读取会话历史 (%s 条)" % len(msg_list))

    assistant = [m for m in msg_list if m.get("role") == "assistant"]
    check(len(assistant) >= 1, "历史含 assistant 消息 (%d 条)" % len(assistant))

    has_any_think = any((m.get("reasoning") or m.get("execution_flow")) for m in assistant)
    check(has_any_think, "至少 1 条 assistant 含思考/执行链路 (reasoning/execution_flow)")

    tool_ok = [tc for m in assistant for tc in (m.get("tool_calls") or []) if tc.get("success") is True]
    check(bool(tool_ok), "至少 1 次工具调用成功 success=true (%d 次成功)" % len(tool_ok))

    bad_status = [m for m in assistant if m.get("status") != "completed"]
    check(not bad_status, "assistant 消息 status 均为 completed")

    contents = [m.get("content") for m in assistant if m.get("content")]
    check(len(contents) == len(set(contents)), "不存在重复 assistant 消息（冗余保存回归）")

    # 4. MCP 服务管理
    section("4. MCP 服务管理")
    s, _ = call("POST", GATEWAY + "/api/mcp/servers", uid=TEST_USER, body={"name": TEST_MCP})
    check(s == 403, "普通 user 不能新增 MCP (403) -> 仅 admin")
    s, _ = call_json("POST", GATEWAY + "/api/mcp/servers", uid=ADMIN, body={
        "name": TEST_MCP, "url": "http://127.0.0.1:9/fake",
        "transport": "streamable_http", "enabled": False,
        "bound_agents": ["*"], "auto_sync": False})
    check(s == 200, "admin 新增 MCP %s" % TEST_MCP)
    s, lst = call_json("GET", "/api/mcp/servers", uid=ADMIN)
    servers = lst.get("data", {}).get("servers", []) if isinstance(lst, dict) else []
    names = [x.get("name") for x in servers]
    check(TEST_MCP in names, "MCP 列表含 %s" % TEST_MCP)
    s, _ = call_json("POST", GATEWAY + "/api/mcp/servers/%s/binding" % TEST_MCP, uid=ADMIN,
                     body={"bound_agents": ["default"]})
    check(s == 200, "admin 设置 MCP 绑定")

    # 5. 知识库独立 API
    section("5. 知识库独立 API (port 6788)")
    s, _ = call_json("GET", "/knowledge/health", base=KB_API, uid="any")
    if s == 0:
        skip("知识库 API 未启动，跳过知识库用例", "port 6788 不可达")
    else:
        kb_ok = True
        check(s == 200, "知识库健康检查 (HTTP %s)" % s)
        s, _ = call_json("POST", "/knowledge/search", base=KB_API, uid="any",
                         body={"query": "调度操作", "top_k": 3})
        check(s == 200, "知识库检索 (HTTP %s)" % s)
        s, _ = call_json("POST", "/knowledge/chat", base=KB_API, uid="any",
                         body={"question": "安全措施有什么要求？", "top_k": 3})
        check(s == 200, "知识库问答 (HTTP %s)" % s)
        try:
            boundary = "----qa_test_boundary"
            body_parts = []
            body_parts.append("--%s\r\n" % boundary)
            body_parts.append('Content-Disposition: form-data; name="file"; filename="qa_test.txt"\r\n')
            body_parts.append("Content-Type: text/plain\r\n\r\n")
            body_parts.append("DFEcrab QA测试文档：电网调度操作基本要求。\r\n")
            body_parts.append("--%s\r\n" % boundary)
            body_parts.append('Content-Disposition: form-data; name="category"\r\n\r\n')
            body_parts.append("qa_test\r\n")
            body_parts.append("--%s\r\n" % boundary)
            body_parts.append('Content-Disposition: form-data; name="title"\r\n\r\n')
            body_parts.append(KB_DOC_TITLE + "\r\n")
            body_parts.append("--%s--\r\n" % boundary)
            body_data = "".join(body_parts).encode("utf-8")
            s, up = call("POST", KB_API + "/knowledge/upload", uid="any",
                         body=body_data, ct="multipart/form-data; boundary=%s" % boundary)
            up_json = json.loads(up) if up else {}
            doc_id = up_json.get("doc_id") or up_json.get("document_id") or ""
            check(s == 200, "上传知识库文档 (doc_id=%s)" % doc_id)
        except Exception as e:
            check(False, "上传知识库文档异常: %s" % e)
        s, docs = call_json("GET", "/knowledge/documents", base=KB_API, uid="any")
        doc_list = docs.get("documents", docs.get("data", {}).get("documents", [])) if isinstance(docs, dict) else []
        titles = [d.get("title") for d in doc_list]
        check(KB_DOC_TITLE in titles, "文档列表含 %s" % KB_DOC_TITLE)

    # 记录 ID 供清理（保留以便排查，结束时会自动删除）
    with open(".qa_sid.txt", "w", encoding="utf-8") as f:
        f.write(sid or "")
    if doc_id:
        with open(".qa_kb_docid.txt", "w", encoding="utf-8") as f:
            f.write(doc_id)

    return sid, doc_id, kb_ok


# ---------------------------------------------------------------------------
# 自动清理（原 cleanup_test_data.py 逻辑，已合并）
# ---------------------------------------------------------------------------
def cleanup(sid, doc_id):
    print("\n==== 自动清理测试数据 ====")

    def done(s, name):
        ok = s in (200, 204, 404)
        print(("  [OK]   " if ok else "  [WARN] ") + "%s -> HTTP %s" % (name, s))

    if sid:
        s, _ = call("DELETE", GATEWAY + "/api/v2/sessions/deleteSession/%s" % sid, uid=ADMIN)
        done(s, "删除会话 %s" % sid)
    else:
        print("  [SKIP] 无会话 ID，跳过会话清理")

    s, _ = call("DELETE", GATEWAY + "/api/mcp/servers/%s" % TEST_MCP, uid=ADMIN)
    done(s, "删除 MCP %s" % TEST_MCP)

    s, _ = call("DELETE", GATEWAY + "/api/users/%s" % TEST_USER, uid=ADMIN)
    done(s, "删除用户 %s" % TEST_USER)

    if doc_id:
        s, _ = call("DELETE", KB_API + "/knowledge/documents/%s" % doc_id, uid="any")
        done(s, "删除知识库文档 %s" % doc_id)
    else:
        print("  [SKIP] 无文档 ID，跳过知识库清理")

    for fn in (".qa_sid.txt", ".qa_kb_docid.txt"):
        try:
            os.remove(fn)
        except Exception:
            pass
    print("清理完成。")


def main():
    sid, doc_id, _kb_ok = run_tests()
    section("结果")
    print("PASS=%d  FAIL=%d  SKIP=%d" % (PASS, FAIL, SKIP))
    # 无论通过与否，均自动清理测试数据，避免污染
    cleanup(sid, doc_id)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
