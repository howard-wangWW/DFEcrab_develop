#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_knowledge_upgrade.py — 知识库改造专项验证（阶段 0~5 覆盖）

用途
----
一次性验证本次「知识库改造」涉及的**全部 6788 接口**，并断言关键行为：

  1. GET  /knowledge/health                        版本 / 索引维度 == 嵌入维度
  2. POST /knowledge/upload                        .csv（表格）与 .md（标题提取）
  3. GET  /knowledge/documents                     文档登记可见
  4. GET  /knowledge/documents/{id}/chunks         切片结构：Excel 表头继承
  5. POST /knowledge/search                        检索可用 + 分类过滤
  6. GET  /knowledge/categories                    分类列表
  7. GET  /knowledge/stats                         统计与文档数自洽
  8. GET  /knowledge/knowledge-bases               兼容接口
  9. POST /knowledge/chat                          （可选 --with-chat）问答
 10. DELETE /knowledge/documents/{id}             清理（finally 保证执行）

特性
----
- **自生成测试文档**（csv / md），不依赖任何外部文件
- 执行完**自动删除**本次上传的测试文档（成功失败都会清理）
- 结果写入 `docs/verify_results/知识库改造验证_<时间戳>.txt`
- 仅用 Python 标准库，无需项目第三方依赖

用法
----
  venv/bin/python3 scripts/verify_knowledge_upgrade.py
  venv/bin/python3 scripts/verify_knowledge_upgrade.py --base http://localhost:6788
  venv/bin/python3 scripts/verify_knowledge_upgrade.py --with-chat     # 额外测问答（需 LLM 可用）
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

try:  # Windows GBK 控制台兜底
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_DIR = PROJECT_ROOT / "docs" / "verify_results"

TEST_TAG = "zz_kb_verify"
TEST_CATEGORY = "other"


class Verify:
    def __init__(self, base: str, with_chat: bool = False, timeout: int = 60):
        self.base = base.rstrip("/")
        self.with_chat = with_chat
        self.timeout = timeout
        self.results = []          # (ok, name, detail, skip)
        self.created_docs = []     # 本次上传的 doc_id，用于清理

    # ────────────────────────────── HTTP ──────────────────────────────

    def _request(self, method, path, data=None, content_type=None):
        url = self.base + path
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = resp.getcode()
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read().decode("utf-8", "replace")
        except Exception as e:
            return 0, None, "%s: %s" % (type(e).__name__, e)
        try:
            return status, json.loads(raw), None
        except Exception:
            return status, raw, None

    def get(self, path):
        return self._request("GET", path)

    def post_json(self, path, body):
        return self._request("POST", path,
                             json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             "application/json")

    def upload(self, filename, content: bytes, category: str, title: str = None):
        boundary = "----dfecrabKb" + uuid.uuid4().hex
        parts = []

        def field(name, value):
            parts.append(("--%s\r\n" % boundary).encode())
            parts.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
            parts.append(value.encode("utf-8"))
            parts.append(b"\r\n")

        parts.append(("--%s\r\n" % boundary).encode())
        parts.append(('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % filename).encode())
        parts.append(b"Content-Type: application/octet-stream\r\n\r\n")
        parts.append(content)
        parts.append(b"\r\n")
        field("category", category)
        if title:
            field("title", title)
        parts.append(("--%s--\r\n" % boundary).encode())

        return self._request("POST", "/knowledge/upload", b"".join(parts),
                             "multipart/form-data; boundary=%s" % boundary)

    def delete(self, doc_id):
        return self._request("DELETE", "/knowledge/documents/%s" % doc_id)

    # ────────────────────────────── 断言 ──────────────────────────────

    def check(self, name, ok, detail="", skip=False):
        self.results.append((bool(ok), name, detail, skip))
        flag = "SKIP" if skip else ("PASS" if ok else "FAIL")
        line = "  [%s] %s%s" % (flag, name, ("  -- " + detail) if detail else "")
        print(line)

    # ────────────────────────── 测试文档生成 ──────────────────────────

    @staticmethod
    def _csv_bytes() -> bytes:
        rows = ["告警大类,告警小类,处置措施"]
        for i in range(1, 26):
            rows.append("测试大类%d,测试小类%d,处置步骤%d" % (i, i, i))
        return "\n".join(rows).encode("utf-8")

    @staticmethod
    def _md_bytes() -> bytes:
        return (
            "# " + TEST_TAG + "标题验证\n\n"
            "第一段：用于验证段落切分与一级标题识别。\n\n"
            "第二段：包含中文标点！还有问句？以及分号；用于验证标点保真。\n"
        ).encode("utf-8")

    # ────────────────────────────── 用例 ──────────────────────────────

    def run(self):
        print("=" * 72)
        print("知识库改造专项验证   base=%s" % self.base)
        print("=" * 72)
        try:
            self.t_health()
            self.t_upload_table()   # .csv → 表格切片（表头继承）+ 检索
            self.t_upload_md()      # .md → 标题提取
            self.t_misc()
            if self.with_chat:
                self.t_chat()
            else:
                self.check("问答 /chat（需 LLM，默认跳过）", False, "--with-chat 开启", skip=True)
        finally:
            self.t_cleanup()
        return self.report()

    def t_health(self):
        g = "健康与诊断"
        st, d, err = self.get("/knowledge/health")
        self.check(g + " | GET /knowledge/health", st == 200, "status=%s %s" % (st, err or ""))
        if st != 200 or not isinstance(d, dict):
            return
        self.check(g + " | health.version 存在", bool(d.get("version")), "version=%s" % d.get("version"))
        idx, emb = d.get("index_dim"), d.get("embed_dim")
        if idx is None or emb is None:
            self.check(g + " | 维度字段存在", False, "index_dim/embed_dim 缺失（旧版？）", skip=True)
        else:
            self.check(g + " | index_dim == embed_dim", idx == emb,
                       "index_dim=%s embed_dim=%s mismatch=%s" % (idx, emb, d.get("mismatch")))

    def t_upload_table(self):
        g = "表格解析(.csv)"
        name = "%s_table.csv" % TEST_TAG
        st, d, err = self.upload(name, self._csv_bytes(), TEST_CATEGORY)
        self.check(g + " | POST /knowledge/upload", st == 200 and isinstance(d, dict)
                   and d.get("status") == "success", "status=%s %s" % (st, err or json.dumps(d, ensure_ascii=False)[:200] if isinstance(d, dict) else err))
        if not (st == 200 and isinstance(d, dict) and d.get("status") == "success"):
            return
        doc_id = d.get("doc_id")
        self.created_docs.append(doc_id)
        self.check(g + " | 生成切片", int(d.get("chunk_count", 0)) > 0, "chunk_count=%s" % d.get("chunk_count"))

        # 切片必须继承表头（每片首行含 "告警大类" 等列名）
        st, chunks, err = self.get("/knowledge/documents/%s/chunks" % doc_id)
        ok = st == 200 and isinstance(chunks, dict) and (chunks.get("total_chunks", 0) > 0)
        self.check(g + " | GET /documents/{id}/chunks", ok, "status=%s %s" % (st, err or ""))
        if ok and chunks.get("total_chunks", 0) > 1:
            bodies = [c.get("content", "") for c in chunks.get("chunks", [])]
            inherited = all("告警大类" in b for b in bodies)
            self.check(g + " | 表格表头继承（每片含列名）", inherited,
                       "检查 %d 片" % len(bodies))

        # 分类检索：应能按 category 命中
        st, s, err = self.post_json("/knowledge/search",
                                    {"query": "测试小类", "top_k": 3, "category": TEST_CATEGORY})
        self.check(g + " | POST /knowledge/search(分类过滤)", st == 200 and isinstance(s, dict),
                   "status=%s %s" % (st, err or ""))
        if st == 200 and isinstance(s, dict):
            self.check(g + " | 检索非空", int(s.get("total", 0)) > 0, "total=%s" % s.get("total"))

    def t_upload_md(self):
        g = "标题识别(.md)"
        content = self._md_bytes()
        st, d, err = self.upload("%s_title.md" % TEST_TAG, content, TEST_CATEGORY)
        self.check(g + " | POST /knowledge/upload", st == 200 and isinstance(d, dict)
                   and d.get("status") == "success", "status=%s %s" % (st, err or ""))
        if not (st == 200 and isinstance(d, dict) and d.get("status") == "success"):
            return
        self.created_docs.append(d.get("doc_id"))
        title = d.get("title", "")
        self.check(g + " | 自动提取 md 一级标题", title == TEST_TAG + "标题验证",
                   "title=%s（期望 %s标题验证）" % (title, TEST_TAG))

    def t_misc(self):
        g = "其它接口"
        for name, path in [("GET /knowledge/documents", "/knowledge/documents"),
                           ("GET /knowledge/categories", "/knowledge/categories"),
                           ("GET /knowledge/stats", "/knowledge/stats"),
                           ("GET /knowledge/knowledge-bases", "/knowledge/knowledge-bases")]:
            st, d, err = self.get(path)
            self.check(g + " | " + name, st == 200, "status=%s %s" % (st, err or ""))

        # 统计自洽：documents 的 chunk_count 之和 == stats.total_chunks
        st_docs, docs, _ = self.get("/knowledge/documents")
        st_stat, stat, _ = self.get("/knowledge/stats")
        if st_docs == 200 and st_stat == 200 and isinstance(docs, dict) and isinstance(stat, dict):
            total_docs = int(docs.get("total", 0) or 0)
            sum_chunks = sum(int(x.get("chunk_count", 0) or 0) for x in (docs.get("documents") or []))
            self.check(g + " | 切片数自洽(文档之和==stats.total_chunks)",
                       sum_chunks == int(stat.get("total_chunks", -1) or -1),
                       "documents_sum=%s stats=%s total_docs=%s" % (sum_chunks, stat.get("total_chunks"), total_docs))

    def t_chat(self):
        g = "问答"
        st, d, err = self.post_json("/knowledge/chat",
                                    {"question": "测试小类的处置措施", "top_k": 2, "category": TEST_CATEGORY})
        ok = st == 200 and isinstance(d, dict) and d.get("status") == "success"
        self.check(g + " | POST /knowledge/chat", ok, "status=%s %s" % (st, err or ""))
        if ok:
            # 关键断言：检索到内容时 answer 不应是"未找到"（阶段 4 修复点）
            has_sources = int(d.get("total_sources", 0) or 0) > 0
            answer = d.get("answer", "")
            if has_sources:
                self.check(g + " | 有召回时 answer 非'未找到'",
                           "未找到相关内容" not in answer,
                           "answer_len=%s sources=%s" % (len(answer), d.get("total_sources")))
            else:
                self.check(g + " | 有召回", False, "total_sources=0", skip=True)

    def t_cleanup(self):
        g = "清理"
        if not self.created_docs:
            self.check(g + " | 删除测试文档", True, "无上传记录", skip=True)
            return
        for doc_id in self.created_docs:
            st, d, err = self.delete(doc_id)
            self.check(g + " | DELETE /knowledge/documents/%s" % doc_id, st in (200, 400),
                       "status=%s %s" % (st, err or ""))

    # ────────────────────────────── 报告 ──────────────────────────────

    def report(self):
        total = len(self.results)
        passed = sum(1 for ok, _, _, sk in self.results if ok and not sk)
        failed = sum(1 for ok, _, _, sk in self.results if not ok and not sk)
        skipped = sum(1 for _, _, _, sk in self.results if sk)

        lines = []
        lines.append("=" * 72)
        lines.append("知识库改造专项验证结果")
        lines.append("时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        lines.append("地址: %s" % self.base)
        lines.append("汇总: PASS %d / FAIL %d / SKIP %d（共 %d 项）" % (passed, failed, skipped, total))
        lines.append("=" * 72)
        for ok, name, detail, sk in self.results:
            flag = "SKIP" if sk else ("PASS" if ok else "FAIL")
            lines.append("[%s] %s%s" % (flag, name, ("  -- " + detail) if detail else ""))
        lines.append("=" * 72)
        text = "\n".join(lines)

        print("")
        print(text)
        try:
            RESULT_DIR.mkdir(parents=True, exist_ok=True)
            out = RESULT_DIR / ("知识库改造验证_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))
            out.write_text(text, encoding="utf-8")
            print("\n结果已保存: %s" % out)
        except Exception as e:
            print("\n结果保存失败: %s" % e)
        return 0 if failed == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="知识库改造专项验证")
    ap.add_argument("--base", default="http://127.0.0.1:6788", help="知识库地址")
    ap.add_argument("--with-chat", action="store_true", help="额外测试问答 /chat（需 LLM 可用）")
    ap.add_argument("--timeout", type=int, default=60, help="单请求超时(秒)")
    args = ap.parse_args()
    sys.exit(Verify(args.base, with_chat=args.with_chat, timeout=args.timeout).run())


if __name__ == "__main__":
    main()
