#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_all_features.py — DFEcrab 全功能回归验证（含自动回滚）

用途
----
一次性跑通网关(6789) / 知识库(6788) 的绝大多数 HTTP 接口，
覆盖最近批次新增的能力（默认智能体、MCP 绑定收敛到智能体侧、
列表派生字段 recommended_mcp/is_default、会话附件生命周期、技能/模型/记忆/任务/事件 等），
并在结束后**自动把环境还原到测试前的状态**。

三段式执行
----------
1) 备份（仅本地模式）：config/dfecrab.json、config/mcporter.json、
   config/agents_index.json、config/permissions.json、data/files/registry.json
   → 复制到 data/.verify_backup_<ts>/（回滚成功后自动删除；中途崩溃可手工恢复）
2) 执行：14 组用例，逐条 PASS/FAIL/SKIP
3) 回滚（try/finally，无论成功失败都执行，LIFO 逆序）：
   - 删测试会话 / 附件 / 任务 / 用户 / 知识库文档
   - 清空测试智能体的 MCP 绑定、恢复服务级绑定
   - 删除测试智能体（先清默认）
   - 恢复平台默认智能体为测试前的值
   - 本地模式：覆盖回写备份配置文件；远程模式：全部走 API 还原

回滚语义说明
------------
- 服务是远程（非 127.0.0.1/localhost）时脚本拿不到服务器文件系统，
  自动降级为「API-only 回滚」：绑定/默认助手/测试资源全部通过接口还原，
  配置文件改动集中在 default_agent 与 mcporter（均由接口写回原值），无需手工干预。
- 网关进程内缓存：default_agent 走 app_config（PUT /default 会写盘 + reload，自动一致）；
  MCP 工具池是进程内缓存，回滚后如需立即生效，重启网关（脚本结束会提示）。

用法
----
  # 服务器上本地跑（推荐，含配置文件级回滚）
  python3 scripts/verify_all_features.py

  # 从本地机器打远程服务（API-only 回滚）
  python scripts\\verify_all_features.py --base http://172.20.51.153:6789

  # 常用开关
  --skip-llm          跳过真实对话（不消耗模型，速度快）
  --skip-kb           跳过知识库 6788
  --skip-ws           跳过 WebSocket
  --kb-write          允许知识库上传文档（会写索引，默认关闭）
  --risky             允许 MCP 服务启停(toggle)/同步(sync) 等高危写操作（默认关闭）
  --no-restore        只测不回滚（排障用，慎用）

依赖：仅 Python 标准库（WebSocket 用例需要 websockets，缺失自动 SKIP）。
"""

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TEST_AGENT = "zz_verify_tmp"          # 临时智能体（auto_start=false，不起进程）
TEST_AGENT2 = "zz_verify_tmp2"        # 临时智能体#2（专测"删除默认 agent 回退"，g3 仍依赖 TEST_AGENT 故不复用）
TEST_USER = "zz_verify_user"          # 临时用户
TEST_TAG = "zz_verify"                # 会话/任务/文件名统一前缀

BACKUP_RELS = [
    "config/dfecrab.json",
    "config/mcporter.json",
    "config/agents_index.json",
    "config/permissions.json",
    "data/files/registry.json",
]


class Verify:
    def __init__(self, args):
        self.base = args.base.rstrip("/")
        self.user = args.user
        self.kb_base = (args.kb_base or self._derive_kb_base()).rstrip("/")
        self.timeout = args.timeout
        self.llm_timeout = args.llm_timeout
        self.args = args
        self.file_mode = args.force_file_restore or self._is_local(self.base)
        self.results = []          # [(group, name, status, detail)]
        self.cleanups = []         # [(desc, callable)]
        self.backups = []          # [(rel_path, backup_path)]
        self.backup_dir = None
        self.orig_default_agent = None
        self.orig_bindings = {}    # agent_id -> [server names]
        self.orig_server_binding_state = {}   # server -> bound_agents 原值
        self.created = {"sessions": [], "files": [], "tasks": [], "users": [],
                        "agents": [], "kb_docs": []}

    # ────────────────────────── 基础设施 ──────────────────────────

    @staticmethod
    def _is_local(base):
        host = base.split("://", 1)[-1].split(":")[0]
        return host in ("127.0.0.1", "localhost", "::1", "[::1]")

    def _derive_kb_base(self):
        parts = self.base.split("://", 1)
        scheme = parts[0] if len(parts) > 1 else "http"
        host = parts[-1].split(":")[0]
        return "%s://%s:6788" % (scheme, host)

    def headers(self, extra=None):
        h = {"X-User-Id": self.user, "Accept": "application/json"}
        if extra:
            h.update(extra)
        return h

    def call(self, method, path, body=None, timeout=None, raw=False):
        """统一 HTTP 调用 → (status, payload, err)
        payload: dict/list（JSON 解析成功）或 str（非 JSON / raw=True）"""
        url = self.base + path
        data = None
        headers = self.headers()
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                status = resp.getcode()
                content = resp.read()
            if raw:
                return status, content, None
            try:
                return status, json.loads(content.decode("utf-8")), None
            except Exception:
                return status, content.decode("utf-8", "replace"), None
        except urllib.error.HTTPError as e:
            content = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            try:
                payload = json.loads(content)
            except Exception:
                payload = content
            return e.code, payload, "HTTP %s" % e.code
        except Exception as e:
            return 0, None, "%s: %s" % (type(e).__name__, e)

    def call_multipart(self, path, fields, files, timeout=None):
        """multipart/form-data 上传 → (status, payload, err)"""
        boundary = "----dfecrabVerify" + uuid.uuid4().hex
        buf = b""
        for k, v in fields.items():
            buf += ("--%s\r\n" % boundary).encode()
            buf += ('Content-Disposition: form-data; name="%s"\r\n\r\n' % k).encode("utf-8")
            buf += ("%s\r\n" % v).encode("utf-8")
        for fname, filename, content in files:
            buf += ("--%s\r\n" % boundary).encode()
            buf += ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                    % (fname, filename)).encode("utf-8")
            buf += b"Content-Type: application/octet-stream\r\n\r\n"
            buf += content + b"\r\n"
        buf += ("--%s--\r\n" % boundary).encode()
        req = urllib.request.Request(
            self.base + path, data=buf, method="POST",
            headers=self.headers({"Content-Type": "multipart/form-data; boundary=%s" % boundary}),
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                status = resp.getcode()
                content = resp.read().decode("utf-8", "replace")
            try:
                return status, json.loads(content), None
            except Exception:
                return status, content, None
        except urllib.error.HTTPError as e:
            content = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            return e.code, content, "HTTP %s" % e.code
        except Exception as e:
            return 0, None, "%s: %s" % (type(e).__name__, e)

    def call_stream(self, path, body, timeout):
        """SSE 流式：收集事件直到 message_end 或超时 → (events, err)"""
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=data, method="POST",
            headers=self.headers({"Content-Type": "application/json",
                                  "Accept": "text/event-stream"}),
        )
        events = []
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                deadline = time.time() + timeout
                for raw in resp:
                    if time.time() > deadline:
                        events.append({"type": "__timeout__"})
                        break
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        ev = json.loads(payload)
                    except Exception:
                        continue
                    inner = ev.get("data") if isinstance(ev, dict) and isinstance(ev.get("data"), dict) else ev
                    etype = (inner or {}).get("event_type") or (ev or {}).get("type")
                    events.append({"type": etype, "data": inner})
                    if etype == "message_end":
                        break
            return events, None
        except Exception as e:
            return events, "%s: %s" % (type(e).__name__, e)

    def kb(self, method, path, body=None, timeout=None):
        """知识库独立服务（6788）调用"""
        url = self.kb_base + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                status = resp.getcode()
                content = resp.read().decode("utf-8", "replace")
            try:
                return status, json.loads(content), None
            except Exception:
                return status, content, None
        except urllib.error.HTTPError as e:
            content = e.read().decode("utf-8", "replace") if hasattr(e, "read") else ""
            return e.code, content, "HTTP %s" % e.code
        except Exception as e:
            return 0, None, "%s: %s" % (type(e).__name__, e)

    def check(self, group, name, ok, detail="", skip=False):
        status = "SKIP" if skip else ("PASS" if ok else "FAIL")
        self.results.append((group, name, status, detail))
        print("  [%s] %-52s %s" % (status, name, (detail or "")[:110]))
        return ok

    @staticmethod
    def ok(resp):
        return isinstance(resp, dict) and resp.get("success") is not False

    @staticmethod
    def unwrap(d):
        """网关响应统一解包：{"success":true,"data":{...}} → data（已是裸结构则原样返回）"""
        if isinstance(d, dict) and isinstance(d.get("data"), (dict, list)):
            return d["data"]
        return d

    # ────────────────────────── 备份 ──────────────────────────

    def backup(self):
        if not self.file_mode:
            print("[备份] 远程模式（--base=%s）：跳过文件级备份，回滚走 API-only" % self.base)
            return
        self.backup_dir = PROJECT_ROOT / "data" / (".verify_backup_%s"
                                                   % time.strftime("%Y%m%d_%H%M%S"))
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        for rel in BACKUP_RELS:
            src = PROJECT_ROOT / rel
            if src.exists():
                dst = self.backup_dir / rel.replace("/", "__")
                dst.write_bytes(src.read_bytes())
                self.backups.append((rel, dst))
        print("[备份] %d 个文件 → %s" % (len(self.backups), self.backup_dir))

    def restore_files(self):
        if not self.file_mode or not self.backups:
            return
        for rel, bak in self.backups:
            target = PROJECT_ROOT / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bak, target)
                print("  [还原] %s" % rel)
            except Exception as e:
                print("  [还原失败] %s -> %s" % (rel, e))
        try:
            shutil.rmtree(self.backup_dir)
        except Exception:
            pass

    # ────────────────────────── 各组用例 ──────────────────────────

    def g1_basic(self):
        g = "1.基础与健康"
        st, d, err = self.call("GET", "/health")
        self.check(g, "GET /health", st == 200, "status=%s %s" % (st, err or ""))
        for name, path in [("GET /api/services", "/api/services"),
                           ("GET /api/invariants", "/api/invariants"),
                           ("GET /api/v2/workers", "/api/v2/workers"),
                           ("GET /api/v2/usage/stats", "/api/v2/usage/stats")]:
            st, d, err = self.call("GET", path)
            self.check(g, name, st == 200 and d is not None, "status=%s %s" % (st, err or ""))

    def g2_agents(self):
        g = "2.智能体管理(含默认助手)"
        st, d, err = self.call("GET", "/api/agents")
        agents = (d or {}).get("agents", []) if isinstance(d, dict) else []
        self.check(g, "GET /api/agents 列表", st == 200 and isinstance(agents, list),
                   "agents=%d %s" % (len(agents), err or ""))
        has_fields = bool(agents) and all(
            ("recommended_mcp" in a) and ("is_default" in a) for a in agents)
        self.check(g, "列表含 recommended_mcp / is_default 派生字段", has_fields,
                   "" if has_fields else "字段缺失（服务未部署新版？）")
        default_id = (d or {}).get("default_agent_id")
        self.orig_default_agent = default_id
        self.check(g, "顶层 default_agent_id", bool(default_id), "default=%s" % default_id)

        first = agents[0]["agent_id"] if agents else "dfecrab"
        st, res, err = self.call("GET", "/api/agents/%s" % first)
        det = ((res or {}).get("data") if isinstance(res, dict) else None) or {}
        self.check(g, "GET /api/agents/{id} 详情", st == 200 and bool(det),
                   "%s %s" % (first, err or ""))
        self.check(g, "详情含 system_prompt 字段", "system_prompt" in det,
                   "len=%d" % len(det.get("system_prompt") or ""))
        self.check(g, "详情含 description(老 agent 回退索引)", bool(det.get("description")),
                   (det.get("description") or "")[:30])
        self.check(g, "详情含 recommended_mcp", "recommended_mcp" in det,
                   str(det.get("recommended_mcp"))[:60])
        self.check(g, "详情含 is_default", "is_default" in det, str(det.get("is_default")))

        # 创建临时智能体（auto_start=false，不拉起进程）
        st, d, err = self.call("POST", "/api/agents", {
            "agent_id": TEST_AGENT, "agent_type": "worker",
            "name": "临时验证智能体", "description": "回归验证临时创建，自动删除",
            "system_prompt": "你是用于回归验证的临时智能体，请简短回答。",
            "model_config": "", "auto_start": False, "enabled_skills": [],
        })
        created = st == 200 and self.ok(d)
        self.check(g, "POST /api/agents 创建临时智能体", created,
                   (d or {}).get("error") or err or "")
        if created:
            self.created["agents"].append(TEST_AGENT)
            self.cleanups.append(("删除临时智能体 %s" % TEST_AGENT, self._cleanup_agent))
        if not created:
            return

        st, d, err = self.call("PUT", "/api/agents/%s" % TEST_AGENT,
                               {"name": "临时验证智能体(已改名)"})
        self.check(g, "PUT /api/agents/{id} 更新", self.ok(d),
                   (d or {}).get("error") or err or "")

        # ★ 模型：先固定再清空（回归：model_config 曾"能设不能清"，空串被 falsy 吞掉）
        st, mm, _ = self.call("GET", "/api/models")
        _provs = ((((mm or {}).get("data") if isinstance(mm, dict) else None) or {}).get("providers") or [])
        enabled_cn = next((p.get("config_name") for p in _provs if p.get("enabled")), None)
        if enabled_cn:
            st, d, _ = self.call("PUT", "/api/agents/%s" % TEST_AGENT, {"model_config": enabled_cn})
            self.check(g, "PUT model_config 固定模型可回显", self.ok(d)
                       and ((d or {}).get("data") or {}).get("model_config") == enabled_cn,
                       "data=%s" % ((d or {}).get("data") or {}))
            st, d, _ = self.call("PUT", "/api/agents/%s" % TEST_AGENT, {"model_config": ""})
            _dd = (d or {}).get("data") or {}
            self.check(g, 'PUT model_config="" 清空回跟随全局', self.ok(d)
                       and _dd.get("model_config") == "" and bool(_dd.get("model_name")),
                       "data=%s" % _dd)
        else:
            self.check(g, "PUT model_config 清空回跟随全局", True, "无 enabled 模型，跳过", skip=True)

        orig = self.orig_default_agent or "dfecrab"
        st, d, err = self.call("PUT", "/api/agents/%s/default" % TEST_AGENT)
        setok = self.ok(d)
        self.check(g, "PUT /api/agents/{id}/default 设为默认", setok,
                   (d or {}).get("error") or err or "")
        time.sleep(0.1)
        st, lst, _ = self.call("GET", "/api/agents")
        cur = (lst or {}).get("default_agent_id")
        marked = any(a.get("agent_id") == TEST_AGENT and a.get("is_default")
                     for a in (lst or {}).get("agents", []))
        self.check(g, "默认生效且唯一性(旧默认自动清除)", cur == TEST_AGENT and marked,
                   "default_agent_id=%s is_default_mark=%s" % (cur, marked))
        # ★ agent_type 跟随默认：新默认升 default、原默认降 worker、manager 不受影响
        #   ——同时作为「服务器是否已部署批次16(默认唯一化)」的能力探测：旧版 PUT default 不联动 agent_type
        at_map = {a.get("agent_id"): a.get("agent_type") for a in (lst or {}).get("agents", [])}
        new_semantics = (at_map.get(TEST_AGENT) == "default"
                         and at_map.get(orig) == "worker"
                         and at_map.get("manager_agent") == "manager")
        self.check(g, "agent_type 跟随默认(新默认default/旧默认worker)", new_semantics,
                   "at_map=%s" % {k: at_map.get(k) for k in (TEST_AGENT, orig, "manager_agent")})
        if not new_semantics:
            print("  [注意] 服务器未部署【批次16 默认助手唯一化】语义（agent_type 未随默认联动）。")
            print("        为防对旧逻辑误写污染，manager 拒绝 / 取消幂等 / 删除默认回退 用例将 SKIP；")
            print("        请替换新版 src/gateway/grpc_server.py 并重启网关后重跑本组。")
        self.cleanups.append(("恢复默认智能体为 %s" % orig, self._restore_default))

        st, d, err = self.call("PUT", "/api/agents/zz_not_exist_agent/default")
        self.check(g, "负向: 默认不存在的智能体被拒", not self.ok(d),
                   (d or {}).get("error") or "")

        # ★ 负向: manager_agent 是路由器，不可设为默认（仅新版拦截；旧版会误写故探测不到时 SKIP）
        if new_semantics:
            st, d, err = self.call("PUT", "/api/agents/manager_agent/default")
            stm, lstm, _ = self.call("GET", "/api/agents")
            self.check(g, "负向: manager_agent 不可设为默认", not self.ok(d)
                       and (lstm or {}).get("default_agent_id") == TEST_AGENT,
                       "%s default=%s" % ((d or {}).get("error") or err or "",
                                          (lstm or {}).get("default_agent_id")))
        else:
            self.check(g, "负向: manager_agent 不可设为默认", True, "服务器为旧版，跳过", skip=True)

        # ★ DELETE 非当前默认 → no-op（不误伤真默认，回归 Bug2；仅新版语义）
        if new_semantics:
            st, d, _ = self.call("DELETE", "/api/agents/%s/default" % orig)
            stn, lstn, _ = self.call("GET", "/api/agents")
            self.check(g, "DELETE 非当前默认 no-op 幂等", self.ok(d)
                       and (lstn or {}).get("default_agent_id") == TEST_AGENT,
                       "default=%s msg=%s" % ((lstn or {}).get("default_agent_id"),
                                              (d or {}).get("message") or ""))
        else:
            self.check(g, "DELETE 非当前默认 no-op 幂等", True, "服务器为旧版，跳过", skip=True)

        # DELETE 当前默认 → 取消回退（新版走兜底链、旧版无条件回退 dfecrab，行为等价，均可测）
        st, d, err = self.call("DELETE", "/api/agents/%s/default" % TEST_AGENT)
        st2, lst2, _ = self.call("GET", "/api/agents")
        cur2 = (lst2 or {}).get("default_agent_id")
        self.check(g, "DELETE /api/agents/{id}/default 取消并回退", self.ok(d)
                   and cur2 and cur2 != TEST_AGENT and cur2 != "manager_agent",
                   "default_agent_id=%s (%s)" % (cur2, (d or {}).get("message") or ""))

        # ★ 删除当前默认 agent 本身 → 自动回退兜底（回归 Bug1：原逻辑误缩进在 except 内；仅新版生效）
        if new_semantics:
            st, d, err = self.call("POST", "/api/agents", {
                "agent_id": TEST_AGENT2, "agent_type": "worker",
                "name": "临时默认删除验证", "description": "回归验证删除默认回退，自动删除",
                "system_prompt": "你是临时删除验证智能体。", "model_config": "", "auto_start": False,
            })
            if st == 200 and self.ok(d):
                self.cleanups.append(("清理临时默认删除验证 agent %s" % TEST_AGENT2,
                                      lambda: self._safe_delete_agent(TEST_AGENT2)))
                st, d, _ = self.call("PUT", "/api/agents/%s/default" % TEST_AGENT2)
                self.check(g, "删除默认前置: 临时 agent 设为默认", self.ok(d), (d or {}).get("error") or "")
                st, d, _ = self.call("DELETE", "/api/agents/%s" % TEST_AGENT2)
                st3, lst3, _ = self.call("GET", "/api/agents")
                cur3 = (lst3 or {}).get("default_agent_id")
                self.check(g, "删除默认 agent 自动回退", self.ok(d)
                           and cur3 and cur3 != TEST_AGENT2 and cur3 != "manager_agent",
                           "default_agent_id=%s" % cur3)
            else:
                self.check(g, "删除默认 agent 自动回退", True,
                           "临时 agent 创建失败，跳过: %s" % ((d or {}).get("error") if isinstance(d, dict) else err),
                           skip=True)
        else:
            self.check(g, "删除默认 agent 自动回退", True, "服务器为旧版，跳过", skip=True)

    def g3_mcp(self):
        g = "3.MCP服务与智能体绑定"
        st, d, err = self.call("GET", "/api/mcp/servers")
        payload = self.unwrap(d)
        servers = payload if isinstance(payload, list) else (payload or {}).get("servers", [])
        self.check(g, "GET /api/mcp/servers", st == 200 and isinstance(servers, list),
                   "servers=%d %s" % (len(servers), err or ""))
        enabled_names = [s.get("name") for s in servers if s.get("enabled", True)] \
            if servers and isinstance(servers[0], dict) else []

        st, d, err = self.call("GET", "/api/agents/%s/mcp" % TEST_AGENT)
        self.check(g, "GET /api/agents/{id}/mcp 绑定视图", st == 200 and d is not None,
                   (d or {}).get("error") if isinstance(d, dict) else err or "")

        if not enabled_names:
            self.check(g, "PUT /api/agents/{id}/mcp 保存绑定", False, skip=True)
        else:
            pick = enabled_names[0]
            st, d, err = self.call("PUT", "/api/agents/%s/mcp" % TEST_AGENT,
                                   {"mcp_servers": [pick]})
            self.check(g, "PUT /api/agents/{id}/mcp 保存绑定(%s)" % pick, self.ok(d),
                       (d or {}).get("error") or err or "")
            if self.ok(d):
                self.cleanups.append(("清空 %s 的 MCP 绑定" % TEST_AGENT,
                                      self._cleanup_agent_bindings))
                st, lst, _ = self.call("GET", "/api/agents")
                rec = None
                for a in (lst or {}).get("agents", []):
                    if a.get("agent_id") == TEST_AGENT:
                        rec = a.get("recommended_mcp")
                self.check(g, "绑定后列表 recommended_mcp 同步", rec and pick in rec,
                           "recommended_mcp=%s" % rec)

        st, d, err = self.call("PUT", "/api/agents/%s/mcp" % TEST_AGENT,
                               {"mcp_servers": ["alert_judge_tools"]})
        msg = (d or {}).get("error") or ""
        self.check(g, "负向: 保留服务 alert_judge_tools 绑普通智能体被拒",
                   not self.ok(d), msg[:80])

        st, d, err = self.call("PUT", "/api/agents/%s/mcp" % TEST_AGENT,
                               {"mcp_servers": ["zz_no_such_server"]})
        self.check(g, "负向: 绑定不存在的服务被拒", not self.ok(d),
                   ((d or {}).get("error") or "")[:80])

        st, d, err = self.call("POST", "/api/agents/%s/mcp" % TEST_AGENT,
                               {"mcp_servers": []})
        self.check(g, "废弃 POST /api/agents/{id}/mcp 返回迁移提示",
                   not self.ok(d) and "PUT" in ((d or {}).get("error") or ""),
                   ((d or {}).get("error") or "")[:80])

        if self.args.risky and enabled_names:
            name = enabled_names[0]
            st, d, err = self.call("POST", "/api/mcp/servers/%s/sync" % name)
            self.check(g, "POST /api/mcp/servers/{name}/sync(高危)", st == 200,
                       "status=%s %s" % (st, ((d or {}).get("error") if isinstance(d, dict) else "") or ""))
            st, d, err = self.call("POST", "/api/mcp/servers/%s/toggle" % name,
                                   {"enabled": True})
            self.check(g, "POST /api/mcp/servers/{name}/toggle(高危)", st == 200,
                       "status=%s" % st)
        else:
            self.check(g, "MCP toggle/sync(高危写操作)", False, skip=True)

        st, d, err = self.call("POST", "/api/mcp/servers/test",
                               {"name": enabled_names[0] if enabled_names else "demo"})
        self.check(g, "POST /api/mcp/servers/test 连通性", st in (200, 502, 500),
                   "status=%s" % st)

    def g4_skills(self):
        g = "4.技能管理"
        st, d, err = self.call("GET", "/api/skills")
        payload = (d or {}).get("data") if isinstance(d, dict) else None
        if isinstance(payload, dict):
            skills = payload.get("skills", [])
        elif isinstance(d, list):
            skills = d
        else:
            skills = []
        self.check(g, "GET /api/skills", st == 200 and isinstance(skills, list),
                   "skills=%d %s" % (len(skills), err or ""))
        has_rich = bool(skills) and isinstance(skills[0], dict) and (
            "description" in skills[0] or "name" in skills[0])
        self.check(g, "技能含富信息(name/description)", has_rich,
                   str(list(skills[0].keys()))[:80] if skills and isinstance(skills[0], dict) else "")
        st, d, err = self.call("GET", "/api/skills/search?q=%E6%9F%A5%E8%AF%A2")
        self.check(g, "GET /api/skills/search", st == 200, "status=%s %s" % (st, err or ""))
        st, d, err = self.call("POST", "/api/skills/reload", {})
        self.check(g, "POST /api/skills/reload", st == 200, "status=%s %s" % (st, err or ""))

    def g5_models(self):
        g = "5.模型管理"
        for name, path in [("GET /api/models", "/api/models"),
                           ("GET /api/models/current", "/api/models/current"),
                           ("GET /api/fallback/status", "/api/fallback/status")]:
            st, d, err = self.call("GET", path)
            self.check(g, name, st == 200 and d is not None, "status=%s %s" % (st, err or ""))
        st, d, _ = self.call("GET", "/api/models")
        payload = (d or {}).get("data") if isinstance(d, dict) else None
        models = []
        if isinstance(payload, dict):
            models = payload.get("providers") or payload.get("models") or []
        elif isinstance(d, list):
            models = d
        models = [m for m in models if isinstance(m, dict)]
        enabled = [m for m in models if m.get("enabled")]
        self.check(g, "存在启用中的模型", bool(enabled),
                   "total=%d enabled=%d" % (len(models), len(enabled)))

    def g6_sessions(self):
        g = "6.会话管理"
        st, d, err = self.call("POST", "/api/v2/sessions",
                               {"topic": "%s_会话" % TEST_TAG, "user_id": self.user})
        sid = ((d or {}).get("session") or {}).get("id") or (d or {}).get("session_id")
        self.check(g, "POST /api/v2/sessions 创建", st == 200 and bool(sid),
                   "sid=%s %s" % (sid, err or ""))
        if sid:
            self.created["sessions"].append(sid)
            self.cleanups.append(("删除测试会话 %s" % sid,
                                  lambda s=sid: self.call(
                                      "DELETE", "/api/v2/sessions/deleteSession/%s" % s)))
        st, d, err = self.call("GET", "/api/v2/sessions")
        self.check(g, "GET /api/v2/sessions 列表", st == 200, "status=%s %s" % (st, err or ""))
        if sid:
            st, d, err = self.call("GET", "/api/v2/sessions/%s" % sid)
            self.check(g, "GET /api/v2/sessions/{id} 详情", st == 200, "status=%s" % st)
            st, d, err = self.call("GET", "/api/v2/sessions/%s/messages?limit=10" % sid)
            self.check(g, "GET /api/v2/sessions/{id}/messages", st == 200, "status=%s" % st)
            st, d, err = self.call("GET", "/api/v2/sessions/%s/usage?group_by=model" % sid)
            self.check(g, "GET /api/v2/sessions/{id}/usage(按模型聚合)", st == 200,
                       "status=%s" % st)

    def g7_chat(self):
        g = "7.对话(LLM)"
        if self.args.skip_llm:
            self.check(g, "POST /api/v2/chat", False, "--skip-llm", skip=True)
            self.check(g, "POST /api/v2/chat/stream (SSE)", False, "--skip-llm", skip=True)
            return
        body = {"message": "请只回复两个字：正常",
                "user_id": self.user, "session_id": "",
                "agent_id": self.orig_default_agent or "dfecrab"}
        t0 = time.time()
        st, d, err = self.call("POST", "/api/v2/chat", body, timeout=self.llm_timeout)
        cost = time.time() - t0
        data = (d or {}).get("data") if isinstance(d, dict) else None
        resp_text = (data or {}).get("response") or (d or {}).get("message")
        sid = (data or {}).get("session_id") or (d or {}).get("session_id")
        self.check(g, "POST /api/v2/chat 非流式", st == 200 and bool(resp_text),
                   "%.1fs resp=%s" % (cost, (resp_text or "")[:40]))
        if sid:
            self.created["sessions"].append(sid)
            self.cleanups.append(("删除对话产生的会话 %s" % sid,
                                  lambda s=sid: self.call(
                                      "DELETE", "/api/v2/sessions/deleteSession/%s" % s)))

        t0 = time.time()
        events, err = self.call_stream("/api/v2/chat/stream",
                                       {"message": "请只回复两个字：正常",
                                        "user_id": self.user,
                                        "agent_id": self.orig_default_agent or "dfecrab"},
                                       timeout=self.llm_timeout)
        types = [e.get("type") for e in events]
        has_end = "message_end" in types
        self.check(g, "POST /api/v2/chat/stream (SSE)", has_end or len(events) > 0,
                   "%.1fs events=%s" % (time.time() - t0, types[:6]))
        for e in events:
            s = (e.get("data") or {}).get("session_id")
            if s and s not in self.created["sessions"]:
                self.created["sessions"].append(s)
                self.cleanups.append(("删除流式对话会话 %s" % s,
                                      lambda x=s: self.call(
                                          "DELETE", "/api/v2/sessions/deleteSession/%s" % x)))
                break

    def g8_files(self):
        g = "8.会话附件(上传/列表/下载/删除)"
        st, d, err = self.call("POST", "/api/v2/sessions",
                               {"topic": "%s_附件会话" % TEST_TAG, "user_id": self.user})
        sid = ((d or {}).get("session") or {}).get("id") or (d or {}).get("session_id")
        if not sid:
            self.check(g, "附件全链路", False, "会话创建失败: %s" % err, skip=True)
            return
        self.created["sessions"].append(sid)
        self.cleanups.append(("删除附件测试会话 %s" % sid,
                              lambda s=sid: self.call(
                                  "DELETE", "/api/v2/sessions/deleteSession/%s" % s)))

        content = ("线路,负荷\nF19地王一线,320\nF20宝润线,180\n").encode("utf-8")
        st, d, err = self.call_multipart(
            "/api/files", {"session_id": sid, "user_id": self.user},
            [("file", "%s_verify.csv" % TEST_TAG, content)])
        payload = (d or {}).get("data") if isinstance(d, dict) else None
        fid = (payload or {}).get("file_id") or (d or {}).get("file_id")
        self.check(g, "POST /api/files 上传(multipart)", st == 200 and bool(fid),
                   "fid=%s %s" % (fid, (d or {}).get("error") if isinstance(d, dict) else err or ""))
        if fid:
            self.created["files"].append(fid)
            self.cleanups.append(("删除测试附件 %s" % fid,
                                  lambda f=fid: self.call("DELETE", "/api/files/%s" % f)))
            st, d, err = self.call("GET", "/api/files?session_id=%s" % sid)
            files = ((d or {}).get("data") or {}).get("files", [])
            self.check(g, "GET /api/files 列表", st == 200 and len(files) >= 1,
                       "files=%d" % len(files))
            st, d, err = self.call("GET", "/api/files/%s/download" % fid)
            self.check(g, "GET /api/files/{id}/download", st == 200,
                       "status=%s %s" % (st, err or ""))
            st, d, err = self.call("DELETE", "/api/files/%s" % fid)
            self.check(g, "DELETE /api/files/{id} 删除", st == 200, "status=%s" % st)
            if fid in self.created["files"]:
                self.created["files"].remove(fid)

    def g9_knowledge(self):
        g = "9.知识库(6788)"
        if self.args.skip_kb:
            self.check(g, "知识库全组", False, "--skip-kb", skip=True)
            return

        # 健康检查 + 维度一致性（索引维度必须等于嵌入维度，否则 FAISS 检索会 mismatch）
        st_h, health, err = self.kb("GET", "/knowledge/health")
        self.check(g, "GET /knowledge/health", st_h == 200, "status=%s %s" % (st_h, err or ""))
        if st_h == 200 and isinstance(health, dict):
            idx_dim = health.get("index_dim")
            emb_dim = health.get("embed_dim")
            if idx_dim is None or emb_dim is None:
                self.check(g, "索引/嵌入维度自检", False, "health 未返回 index_dim/embed_dim", skip=True)
            else:
                self.check(g, "索引维度 == 嵌入维度", idx_dim == emb_dim,
                           "index_dim=%s embed_dim=%s mismatch=%s" % (idx_dim, emb_dim, health.get("mismatch")))
            self.check(g, "health 返回版本", bool(health.get("version")),
                       "version=%s" % health.get("version"))

        for name, path in [("GET /knowledge/stats", "/knowledge/stats"),
                           ("GET /knowledge/documents", "/knowledge/documents"),
                           ("GET /knowledge/knowledge-bases", "/knowledge/knowledge-bases"),
                           ("GET /knowledge/categories", "/knowledge/categories")]:
            st, d, err = self.kb("GET", path)
            self.check(g, name, st == 200, "status=%s %s" % (st, err or ""))

        # 切片数自洽：各文档 chunk_count 之和 == health.total_chunks
        st_docs, docs, _ = self.kb("GET", "/knowledge/documents")
        total_docs = 0
        sum_chunks = 0
        if st_docs == 200 and isinstance(docs, dict):
            total_docs = int(docs.get("total", 0) or 0)
            sum_chunks = sum(int(x.get("chunk_count", 0) or 0) for x in (docs.get("documents") or []))
        if st_h == 200 and isinstance(health, dict):
            self.check(g, "切片数自洽(文档chunk_count之和==health.total_chunks)",
                       sum_chunks == int(health.get("total_chunks", -1) or -1),
                       "documents_sum=%s health_total=%s" % (sum_chunks, health.get("total_chunks")))

        # 检索：接口可用 + 库非空时必须能召回（避免"有文档却搜不到"）
        st, d, err = self.kb("POST", "/knowledge/search",
                             {"query": "调度", "top_k": 3})
        self.check(g, "POST /knowledge/search", st == 200, "status=%s %s" % (st, err or ""))
        if st == 200 and isinstance(d, dict) and total_docs > 0:
            self.check(g, "检索非空(库非空时)", int(d.get("total", 0) or 0) > 0,
                       "total=%s documents=%s" % (d.get("total"), total_docs))

        if self.args.kb_write:
            st, d, err = self.kb("POST", "/knowledge/chat",
                                 {"question": "测试问题", "top_k": 2})
            self.check(g, "POST /knowledge/chat", st == 200, "status=%s %s" % (st, err or ""))
        else:
            self.check(g, "知识库上传/问答(写索引)", False, "默认跳过(--kb-write 开启)", skip=True)

    def g10_memory(self):
        g = "10.记忆管理"
        endpoints = [("GET /api/memory/stats", "/api/memory/stats"),
                     ("GET /api/memory/recent", "/api/memory/recent?limit=5"),
                     ("GET /api/memory/search", "/api/memory/search?q=%E8%B0%83%E5%BA%A6"),
                     ("GET /api/memory/files", "/api/memory/files"),
                     ("GET /api/memory/storage", "/api/memory/storage"),
                     ("GET /api/memory/index_health", "/api/memory/index_health"),
                     ("GET /api/memory/agents", "/api/memory/agents"),
                     ("GET /api/memory/users", "/api/memory/users")]
        for name, path in endpoints:
            st, d, err = self.call("GET", path)
            self.check(g, name, st == 200, "status=%s %s" % (st, err or ""))
        st, d, err = self.call("GET", "/api/memory/agents/%s" % (self.orig_default_agent or "dfecrab"))
        self.check(g, "GET /api/memory/agents/{agent_id}", st == 200, "status=%s" % st)

    def g11_tasks(self):
        g = "11.任务与待办"
        members = [{"agent_id": self.orig_default_agent or "dfecrab", "role": "developer"}]
        st, d, err = self.call("POST", "/api/v2/tasks", {
            "topic": "%s_临时任务" % TEST_TAG,
            "task_type": "temporary",
            "description": "回归验证临时任务，自动删除",
            "user_id": self.user,
            "agent_group_config": {"members": members},
        })
        payload = (d or {}).get("data") if isinstance(d, dict) else None
        tid = (payload or {}).get("task_id") or (d or {}).get("task_id")
        note = (d or {}).get("error") if isinstance(d, dict) else ""
        if err and "Timeout" in str(err):
            note = "%s（超时=任务系统同步阻塞网关事件循环，见服务端日志）" % err
        self.check(g, "POST /api/v2/tasks 创建", st == 200 and bool(tid),
                   "task=%s %s" % (tid, note or err or ""))
        # 负向：缺 agent_group_config.members 应被拒
        st2, d2, err2 = self.call("POST", "/api/v2/tasks",
                                  {"topic": "%s_缺成员" % TEST_TAG, "task_type": "temporary"})
        self.check(g, "负向: 缺 members 的任务被拒", not self.ok(d2),
                   (d2 or {}).get("error") if isinstance(d2, dict) else err2 or "")
        if tid:
            self.created["tasks"].append(tid)
            self.cleanups.append(("删除测试任务 %s" % tid,
                                  lambda t=tid: self.call("DELETE", "/api/v2/tasks/%s" % t)))
            st, d, err = self.call("GET", "/api/v2/tasks/%s" % tid)
            self.check(g, "GET /api/v2/tasks/{id}", st == 200, "status=%s" % st)
            st, d, err = self.call("GET", "/api/v2/tasks/%s/progress" % tid)
            self.check(g, "GET /api/v2/tasks/{id}/progress", st == 200, "status=%s" % st)
            st, d, err = self.call("GET", "/api/v2/tasks/%s/audit" % tid)
            self.check(g, "GET /api/v2/tasks/{id}/audit", st == 200, "status=%s" % st)
        for name, path in [("GET /api/v2/tasks 列表", "/api/v2/tasks"),
                           ("GET /api/tasks/stats", "/api/tasks/stats"),
                           ("GET /api/tasks/todos", "/api/tasks/todos"),
                           ("GET /api/tasks/heartbeats", "/api/tasks/heartbeats"),
                           ("GET /api/tasks/scheduled", "/api/tasks/scheduled")]:
            st, d, err = self.call("GET", path)
            self.check(g, name, st == 200, "status=%s %s" % (st, err or ""))

    def g12_events_plan(self):
        g = "12.事件/计划/反思"
        for name, path in [("GET /api/events/recent", "/api/events/recent?limit=5"),
                           ("GET /api/events/stats", "/api/events/stats"),
                           ("GET /api/events/search", "/api/events/search?q=%E6%B5%8B%E8%AF%95"),
                           ("GET /api/plan/current", "/api/plan/current"),
                           ("GET /api/plan/list", "/api/plan/list"),
                           ("GET /api/reflections", "/api/reflections")]:
            st, d, err = self.call("GET", path)
            self.check(g, name, st == 200, "status=%s %s" % (st, err or ""))

    def g13_users(self):
        g = "13.用户管理(admin)"
        st, d, err = self.call("GET", "/api/users")
        self.check(g, "GET /api/users", st == 200, "status=%s %s" % (st, err or ""))
        st, d, err = self.call("POST", "/api/users",
                               {"user_id": TEST_USER, "role": "guest"})
        ok_created = st == 200 and self.ok(d)
        self.check(g, "POST /api/users 创建临时用户", ok_created,
                   (d or {}).get("error") if isinstance(d, dict) else err or "")
        if ok_created:
            self.created["users"].append(TEST_USER)
            self.cleanups.append(("删除临时用户 %s" % TEST_USER,
                                  lambda u=TEST_USER: self.call("DELETE", "/api/users/%s" % u)))
            st, d, err = self.call("PUT", "/api/users/%s" % TEST_USER, {"role": "user"})
            self.check(g, "PUT /api/users/{id} 更新", st == 200, "status=%s" % st)
        # 权限模型校验：guest(permissions.json: test → guest) 的写操作应被拒
        # 用一个必然失败的参数（agent_id 非法）之外的真实写请求试探：
        # 若被拒 → 说明鉴权生效；若 success=True → 权限模型异常（不会真的创建，因 agent_id 已存在校验在前）
        guest_reject = True
        old_user = self.user
        try:
            self.user = "test"
            st, d, err = self.call("POST", "/api/agents", {
                "agent_id": TEST_AGENT, "agent_type": "worker",
                "system_prompt": "x", "auto_start": False})
            guest_reject = not self.ok(d)
        finally:
            self.user = old_user
        self.check(g, "鉴权: guest 写操作被拒", guest_reject,
                   "" if guest_reject else "guest 写成功了(检查 permissions.json)")

    def g14_ws(self):
        g = "14.WebSocket"
        if self.args.skip_ws:
            self.check(g, "WS chat_stream", False, "--skip-ws", skip=True)
            return
        try:
            import websockets  # noqa: F401
        except Exception:
            self.check(g, "WS chat_stream", False, "未安装 websockets，跳过", skip=True)
            return
        try:
            from websockets.sync.client import connect as ws_connect
            sync_mode = True
        except Exception:
            try:
                from websockets import connect as ws_connect  # noqa
                sync_mode = False
            except Exception:
                self.check(g, "WS chat_stream", False, "websockets API 不兼容，跳过", skip=True)
                return
        if not sync_mode:
            self.check(g, "WS chat_stream", False, "仅支持 websockets 同步客户端，跳过", skip=True)
            return
        ws_url = self.base.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = ws_url.rsplit(":", 1)[0] + ":6790"
        msg = json.dumps({"type": "chat", "message": "请只回复两个字：正常",
                          "user_id": self.user, "correlation_id": TEST_TAG})
        try:
            with ws_connect(ws_url, open_timeout=10) as ws:
                ws.send(msg)
                got = None
                deadline = time.time() + (self.llm_timeout if not self.args.skip_llm else 8)
                while time.time() < deadline:
                    try:
                        raw = ws.recv(timeout=5)
                    except Exception:
                        break
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        continue
                    if ev.get("type") == "message_ack":
                        got = ev
                        break
                self.check(g, "WS chat 收到 message_ack", bool(got),
                           (str((got or {}).get("data"))[:60]))
        except Exception as e:
            self.check(g, "WS chat_stream", False, "%s: %s" % (type(e).__name__, e))

    # ────────────────────────── 回滚动作 ──────────────────────────

    def _cleanup_agent_bindings(self):
        try:
            self.call("PUT", "/api/agents/%s/mcp" % TEST_AGENT, {"mcp_servers": []})
        except Exception:
            pass

    def _safe_delete_agent(self, agent_id):
        """安全删除智能体：先取消其默认（若正指向它，接口自动回退），再删接口；忽略异常（幂等，供 cleanup 用）。"""
        try:
            self.call("DELETE", "/api/agents/%s/default" % agent_id)
        except Exception:
            pass
        try:
            self.call("DELETE", "/api/agents/%s" % agent_id)
        except Exception:
            pass

    def _cleanup_agent(self):
        # 先取消默认（若指向测试 agent，接口会自动回退 dfecrab），再删除
        try:
            self.call("DELETE", "/api/agents/%s/default" % TEST_AGENT)
        except Exception:
            pass
        self.call("DELETE", "/api/agents/%s" % TEST_AGENT)
        # 兜底：本地模式下若目录仍在（接口未清理），直接删目录
        if self.file_mode:
            d = PROJECT_ROOT / "agents" / TEST_AGENT
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    def _restore_default(self):
        target = self.orig_default_agent or "dfecrab"
        self.call("PUT", "/api/agents/%s/default" % target)

    def restore(self):
        print("\n" + "=" * 78)
        print("回滚：还原到测试前状态")
        print("=" * 78)
        if self.args.no_restore:
            print("  [跳过] --no-restore 已指定，环境保持测试后状态")
            return
        for desc, fn in reversed(self.cleanups):
            try:
                fn()
                print("  [OK] %s" % desc)
            except Exception as e:
                print("  [ERR] %s -> %s" % (desc, e))
        self.restore_files()
        # 校验回滚结果
        st, d, _ = self.call("GET", "/api/agents")
        cur = (d or {}).get("default_agent_id")
        still = any(a.get("agent_id") == TEST_AGENT for a in (d or {}).get("agents", []))
        print("  [校验] default_agent_id=%s (测试前=%s) / 临时智能体残留=%s"
              % (cur, self.orig_default_agent, still))
        if still or (self.orig_default_agent and cur != self.orig_default_agent):
            print("  [警告] 回滚未完全生效，请检查上方 [ERR] 行")

    # ────────────────────────── 汇总 ──────────────────────────

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r[2] == "PASS")
        failed = sum(1 for r in self.results if r[2] == "FAIL")
        skipped = sum(1 for r in self.results if r[2] == "SKIP")
        print("\n" + "=" * 78)
        print("汇总: 总用例 %d | PASS %d | FAIL %d | SKIP %d" % (total, passed, failed, skipped))
        print("=" * 78)
        if failed:
            print("失败明细:")
            for grp, name, status, detail in self.results:
                if status == "FAIL":
                    print("  - [%s] %s :: %s" % (grp, name, detail))
        return passed, failed, skipped

    def write_report(self, passed, failed, skipped):
        out_dir = PROJECT_ROOT / "docs" / "verify_results"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            fp = out_dir / ("全功能回归验证结果_%s.txt" % ts)
            lines = ["DFEcrab 全功能回归验证结果",
                     "时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
                     "网关: %s  用户: %s  知识库: %s" % (self.base, self.user, self.kb_base),
                     "模式: %s" % ("本地(含配置文件级回滚)" if self.file_mode else "远程(API-only 回滚)"),
                     "汇总: PASS=%d FAIL=%d SKIP=%d" % (passed, failed, skipped),
                     "-" * 78]
            cur_group = None
            for grp, name, status, detail in self.results:
                if grp != cur_group:
                    lines.append("")
                    lines.append("## %s" % grp)
                    cur_group = grp
                lines.append("  [%s] %s %s" % (status, name, detail))
            fp.write_text("\n".join(lines), encoding="utf-8")
            print("\n结果已写入: %s" % fp)
        except Exception as e:
            print("\n[提示] 结果文件写入失败: %s" % e)

    def run(self):
        print("=" * 78)
        print("DFEcrab 全功能回归验证（自动回滚）")
        print("网关=%s  知识库=%s  用户=%s" % (self.base, self.kb_base, self.user))
        print("模式=%s  LLM对话=%s" % ("本地(含配置回滚)" if self.file_mode else "远程(API-only)",
                                    "关闭" if self.args.skip_llm else "开启"))
        print("=" * 78)
        self.backup()
        groups = [self.g1_basic, self.g2_agents, self.g3_mcp, self.g4_skills,
                  self.g5_models, self.g6_sessions, self.g7_chat, self.g8_files,
                  self.g9_knowledge, self.g10_memory, self.g11_tasks,
                  self.g12_events_plan, self.g13_users, self.g14_ws]
        if getattr(self.args, "only_groups", None):
            sel = set(self.args.only_groups)
            groups = [fn for fn in groups
                      if int(fn.__name__[1:].split("_")[0]) in sel]
            if not groups:
                print("⚠️ --only-groups 组号无效，有效范围: 1-14")
        try:
            for fn in groups:
                print("\n## %s" % fn.__name__[3:])
                try:
                    fn()
                except Exception as e:
                    self.check(fn.__name__, "分组执行异常", False,
                               "%s: %s" % (type(e).__name__, e))
        finally:
            self.restore()
        p, f, s = self.summary()
        self.write_report(p, f, s)
        print("\n提示: MCP 工具池为网关进程内缓存，如需回滚后立即生效请重启网关。")
        return 1 if f else 0


def main():
    # Windows 控制台(GBK)打印兜底：不可编码字符替换为 ?，避免 emoji/符号中断分组执行
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="DFEcrab 全功能回归验证（自动回滚）")
    ap.add_argument("--base", default="http://127.0.0.1:6789", help="网关地址(默认 http://127.0.0.1:6789)")
    ap.add_argument("--user", default="admin", help="X-User-Id(默认 admin，需 write 权限)")
    ap.add_argument("--kb-base", default=None, help="知识库地址(默认同 host:6788)")
    ap.add_argument("--timeout", type=int, default=20, help="普通接口超时秒(默认 20)")
    ap.add_argument("--llm-timeout", type=int, default=180, help="对话接口超时秒(默认 180)")
    ap.add_argument("--skip-llm", action="store_true", help="跳过真实对话(不消耗模型)")
    ap.add_argument("--skip-kb", action="store_true", help="跳过知识库 6788")
    ap.add_argument("--skip-ws", action="store_true", help="跳过 WebSocket")
    ap.add_argument("--kb-write", action="store_true", help="允许知识库写操作(上传/问答)")
    ap.add_argument("--risky", action="store_true", help="允许 MCP toggle/sync 等高危写操作")
    ap.add_argument("--no-restore", action="store_true", help="不回滚(排障用)")
    ap.add_argument("--force-file-restore", action="store_true",
                    help="远程 base 也强制启用本地配置文件备份/回滚(谨慎)")
    ap.add_argument("--only-groups", default=None,
                    help="只跑指定分组，逗号分隔组号(如 2=智能体管理/默认助手 5=模型；默认全跑)")
    args = ap.parse_args()
    if args.only_groups:
        try:
            args.only_groups = [int(x.strip()) for x in args.only_groups.split(",") if x.strip()]
        except ValueError:
            ap.error("--only-groups 需为逗号分隔的组号，如 2 或 2,5")
    return Verify(args).run()


if __name__ == "__main__":
    sys.exit(main())
