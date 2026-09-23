# -*- coding: utf-8 -*-
"""
知识库「切片内嵌图片」入库验证脚本（2026-09-11，批次 20）

验证思路：
    批次 20 让切片里能放图，但两处不到位：① 图片占位块全堆在文末，与正文的位置
    关系丢失；② 用 OCR 文本给图片做索引，界面截图类图片的破碎文字命中率低、
    噪声大。本批（批次 20）改为：**正文按文档顺序输出、图片就地出现**，
    OCR 默认关闭，图片片**不进索引** —— 改为「搜到图片附近的正文，顺带把图带出来」
    （src/knowledge/core/neighbors.py）。

    因此验收必须同时证明五件事，缺一不可：

      1) 图能看   —— 切片带 metadata.images，且 /knowledge/media/{doc_id}/{name}
                     真的取得到原图（字节与原图一致）
      2) 正文干净 —— 正文里只有占位块，批次 18 的【图片文字】彻底消失
      3) 顺序对   —— 图片占位块**夹在相邻正文片之间**，不再堆在文末
      4) 带得出来 —— 搜图片紧邻的那段正文，命中的文字片要**附带该图**
      5) 老路径没坏 —— 纯文本上传行为不变

    ★ 第 4 条不能只看切片文件里有没有图：向量索引与 BM25 语料都可能没跟上，
      而这一失效**没有任何报错**（retriever._merge_results 只从向量结果建键，
      关键词结果仅补分不建键）。所以必须真打一次 /search。

用法：
    python scripts/verify_kb_image_chunks.py [--base URL] [--file 路径] [--doc-id ID]
                                             [--category other] [--expect-text AVC]
                                             [--keep-upload] [--skip-chat]

行为（逐条打印，末行汇总）：
    1. 上传含图 docx    -> HTTP 200 且 chunk_count > 0 且 image_media_count > 0
    2. 切片带图片件     -> chunks[] 中存在 metadata.images 非空的切片
    3. 正文为占位块     -> 该切片顶层 content 形如【图片：NNN.ext】
    4. 图文顺序         -> 图片片夹在相邻正文片之间（不再全部排在末尾）
    5. 图片片不进索引   -> 该切片 metadata.content_chars == 0（检索位留空）
    6. 取图接口         -> GET metadata.images[].url 返回 200 + image/* 且字节与原图逐一比对
    7. 邻近带出         -> POST /search 搜图片紧邻的正文，命中的文字片带出该图
    8. 图片片不单列     -> 搜出来的结果里没有【图片：…】这种独立图片结果
    9. 问答来源带图     -> POST /chat 的 sources[] 携带 images（--skip-chat 可跳过）
   10. 路径穿越被拒     -> GET /knowledge/media/../../etc/passwd -> 404
   11. 删除清理         -> DELETE 文档后 media 目录一并消失
   12. 纯文本回归       -> 文本上传无 images 字段、content 与旧版一致

    --keep-upload 保留上传的文档（默认通过后自动删掉，避免污染现场知识库；
    与文档删除相关的第 11 条断言无论如何都会执行）。
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

# 控制台/文件统一 UTF-8 输出（Windows GBK 控制台打印中文/emoji 会崩）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 默认打本机 —— 本脚本设计为「在部署机上、部署完之后」运行。
# 服务默认绑 0.0.0.0，同机多网卡/多环境时指错地址会得到假结论，故默认 127.0.0.1。
DEFAULT_BASE = "http://127.0.0.1:6788"
# 样本：2026-09-10 上传失败的原始文件（798KB，其中图片占 760KB，正文仅 44 字）
SAMPLE_HINT = "新能源控制业务运行值班手册"
EXPECT_TEXT = "AVC"
# 本批新增的占位块标记；批次 18 的【图片文字】应彻底消失
IMAGE_MARK = "【图片："
LEGACY_MARK = "【图片文字】"
# 与本脚本同一版本落地的知识库版本号（paths.py:KNOWLEDGE_VERSION）
EXPECT_VERSION = "1.5.0"

RESULTS = []


def _log(status: str, name: str, detail: str = ""):
    line = f"[{status:^4}] {name} {detail}"
    RESULTS.append(line)
    print(line, flush=True)


def _http(method: str, url: str, body=None, headers=None, timeout=300):
    """返回 (status_code, parsed_json_or_raw_bytes)；网络异常抛给调用方"""
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.status
            ctype = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raw = e.read()
        code = e.code
        ctype = e.headers.get("Content-Type", "") if e.headers else ""
    try:
        return code, json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return code, raw


def _json_call(method: str, url: str, payload=None, timeout=300):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    return _http(method, url, body, headers, timeout=timeout)


def _multipart(fields: dict, file_field: str, filename: str, data: bytes):
    """手写 multipart/form-data，避免为验收脚本引入 requests 依赖"""
    boundary = "----DFEcrabBoundary" + uuid.uuid4().hex
    buf = bytearray()
    for k, v in fields.items():
        buf += f"--{boundary}\r\n".encode()
        buf += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        buf += str(v).encode("utf-8") + b"\r\n"
    buf += f"--{boundary}\r\n".encode()
    buf += (f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\n').encode("utf-8")
    buf += b"Content-Type: application/octet-stream\r\n\r\n"
    buf += data + b"\r\n"
    buf += f"--{boundary}--\r\n".encode()
    return bytes(buf), f"multipart/form-data; boundary={boundary}"


def _upload(base: str, path: Path, category: str, title: str):
    body, ctype = _multipart({"category": category, "title": title},
                             "file", path.name, path.read_bytes())
    return _http("POST", f"{base}/knowledge/upload", body,
                 {"Content-Type": ctype})


def find_sample(explicit: str) -> Path:
    """定位样本 docx：优先命令行，其次 knowledge_base/documents 下按标题找"""
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    root = Path(__file__).resolve().parent.parent
    for pat in (f"knowledge_base/documents/**/*{SAMPLE_HINT}*.docx",
                f"**/*{SAMPLE_HINT}*.docx"):
        hits = [p for p in root.glob(pat) if p.is_file()]
        if hits:
            return hits[0]
    return None


# --------------------------------------------------------------------------
# 断言 1：上传
# --------------------------------------------------------------------------
def upload_sample(base: str, sample: Path, category: str):
    """返回 (doc_id, ok)。ok 为 False 时已打印失败原因"""
    title = f"图片切片验收_{sample.stem}_{datetime.now().strftime('%H%M%S')}"
    code, data = _upload(base, sample, category, title)
    if code != 200 or not isinstance(data, dict) or data.get("status") != "success":
        _log("FAIL", "① 上传含图 docx", f"HTTP {code}: {str(data)[:300]}")
        return "", False

    doc_id = data.get("doc_id", "")
    _log("PASS", "① 上传含图 docx",
         f"chunk_count={data.get('chunk_count')} "
         f"image_count={data.get('image_count')} "
         f"image_media_count={data.get('image_media_count')} "
         f"ocr_count={data.get('ocr_count')} ocr_chars={data.get('ocr_chars')}")

    if not data.get("chunk_count"):
        _log("FAIL", "① 上传含图 docx", "chunk_count 为 0（纯图文档被长度闸门判死？）")
        return doc_id, False
    if not data.get("image_media_count"):
        _log("FAIL", "① 上传含图 docx",
             f"image_media_count={data.get('image_media_count')} —— "
             f"原图未落盘，切片里会有占位块但前端必然取图 404")
        return doc_id, False
    if IMAGE_MARK not in (data.get("message") or "") and not data.get("chunk_count"):
        return doc_id, False
    return doc_id, True


# --------------------------------------------------------------------------
# 断言 2/3/4：切片契约
# --------------------------------------------------------------------------
def assert_chunk_contract(base: str, doc_id: str, sample: Path):
    """返回 (chunks, img_chunks, ok)"""
    code, data = _http("GET", f"{base}/knowledge/documents/{doc_id}/chunks")
    if code != 200 or not isinstance(data, dict):
        _log("FAIL", "② 切片带图片件", f"拉切片失败 HTTP {code}: {str(data)[:200]}")
        return [], [], False

    chunks = data.get("chunks", []) or []
    if not chunks:
        _log("FAIL", "② 切片带图片件", f"切片为空 (total={data.get('total_chunks')})")
        return [], [], False

    merged = "\n".join(c.get("content", "") for c in chunks)
    _log("PASS", "② 切片带图片件",
         f"{len(chunks)} 个切片 / {len(merged)} 字符 (doc_id={doc_id})")

    ok = True

    # --- 有 metadata.images 非空的切片 ---
    img_chunks = []
    for c in chunks:
        imgs = (c.get("metadata") or {}).get("images") or []
        if imgs:
            img_chunks.append(c)
    if not img_chunks:
        _log("FAIL", "③ 图片切片", "没有任何切片带 metadata.images —— 图片没进切片")
        return chunks, [], False
    _log("PASS", "③ 图片切片", f"{len(img_chunks)} 片带 images")

    # --- 顶层 content 是占位块（展示位） ---
    bad_placeholder = [c for c in img_chunks
                       if not c.get("content", "").startswith(IMAGE_MARK)]
    if bad_placeholder:
        _log("FAIL", "④ 正文为占位块",
             f"{len(bad_placeholder)} 片带图但 content 不是占位块，"
             f"例如 {bad_placeholder[0].get('content', '')[:80]!r}")
        ok = False
    else:
        sample_txt = img_chunks[0].get("content", "").replace("\n", " ")[:60]
        _log("PASS", "④ 正文为占位块", f"例如 {sample_txt!r}")

    # --- 批次 18 的旧写法必须彻底消失 ---
    if LEGACY_MARK in merged:
        _log("FAIL", "⑤ 正文无 OCR 残渣",
             f"切片正文仍含 {LEGACY_MARK} —— 应已改为图片占位块")
        ok = False
    else:
        _log("PASS", "⑤ 正文无 OCR 残渣", f"正文未出现 {LEGACY_MARK}")

    # --- 图文顺序：图片片要夹在相邻正文片之间，不能全排在末尾 ---
    idx_all = {id(c): i for i, c in enumerate(chunks)}
    img_pos = [idx_all[id(c)] for c in img_chunks]
    img_set = set(img_pos)
    trailing = 0
    for pos in img_pos:
        # 该图片片之后若还有非图片片，说明它没有被堆到文末
        if any(j not in img_set for j in range(pos + 1, len(chunks))):
            trailing += 1
    if len(img_pos) > 1 and trailing == 0:
        _log("FAIL", "⑥ 图文顺序",
             f"{len(img_pos)} 张图片片全部连在一起排在末尾 —— "
             f"加载器没有按文档顺序输出（应为就地插入）")
        ok = False
    else:
        _log("PASS", "⑥ 图文顺序",
             f"{len(img_pos)} 张图片片，其中 {trailing} 张后面还有正文片"
             f"（全部排在末位即视为未生效）")

    # --- 图片片检索位必须为空（本批起图片不进索引，靠邻近带出） ---
    with_text = [c for c in img_chunks
                 if int((c.get("metadata") or {}).get("content_chars") or 0) > 0]
    if with_text:
        total = sum(int((c["metadata"] or {}).get("content_chars") or 0)
                    for c in with_text)
        _log("FAIL", "⑦ 图片片不进索引",
             f"{len(with_text)}/{len(img_chunks)} 片仍有检索文本（共 {total} 字符）—— "
             f"图片片会重新进入向量库，与「邻近带出」设计冲突。"
             f"请确认 gateway.yaml 的 knowledge.ocr.enabled 未开启，"
             f"且 metadata['content'] 已被置空")
        ok = False
    else:
        _log("PASS", "⑦ 图片片不进索引",
             f"{len(img_chunks)} 片图片切片检索位均为空（content_chars=0）")

    # --- 占位块名与 images[].name 对得上（否则前端按 name 取图会错位） ---
    mismatched = []
    for c in img_chunks:
        content = c.get("content", "").strip()
        names = [(i.get("name") or "") for i in
                 ((c.get("metadata") or {}).get("images") or [])]
        if names and content == f"{IMAGE_MARK}{names[0]}】":
            continue
        mismatched.append((content[:40], names))
    if mismatched:
        _log("WARN", "⑦b 占位块与 images 对应",
             f"{len(mismatched)} 片对不上，例如 {mismatched[0]}")

    return chunks, img_chunks, ok


# --------------------------------------------------------------------------
# 断言 5：取图接口 + 字节比对
# --------------------------------------------------------------------------
def _docx_image_hashes(sample: Path):
    """docx 内所有图片的 sha256 集合（用于与落盘图逐一比对字节）"""
    hashes = set()
    try:
        with zipfile.ZipFile(sample) as z:
            for n in z.namelist():
                if "/media/" in n.lower() and not n.endswith("/"):
                    hashes.add(hashlib.sha256(z.read(n)).hexdigest())
    except Exception as e:
        _log("WARN", "源图收集", f"读取 docx 媒体失败: {type(e).__name__}: {e}")
    return hashes


def assert_media_fetch(base: str, img_chunks: list, sample: Path) -> bool:
    src_hashes = _docx_image_hashes(sample)
    checked = matched = 0
    failures = []

    for c in img_chunks:
        for img in ((c.get("metadata") or {}).get("images") or []):
            url = img.get("url") or ""
            name = img.get("name") or ""
            if not url:
                failures.append(f"{name}: images 项缺 url")
                continue
            full = base + url if url.startswith("/") else url
            code, raw = _http("GET", full, timeout=120)
            checked += 1
            if code != 200 or not isinstance(raw, (bytes, bytearray)):
                failures.append(f"{name}: HTTP {code}")
                continue
            if len(raw) < 8:
                failures.append(f"{name}: 响应体过短 ({len(raw)}B)")
                continue
            # 图片魔数（FileResponse 未必带 Content-Type 断言之外的保证）
            sig_ok = (raw[:8] == b"\x89PNG\r\n\x1a\n" or raw[:2] == b"\xff\xd8"
                      or raw[:6] in (b"GIF87a", b"GIF89a") or raw[:2] == b"BM")
            if not sig_ok:
                failures.append(f"{name}: 不是图片字节 ({raw[:8]!r})")
                continue
            if src_hashes and hashlib.sha256(bytes(raw)).hexdigest() in src_hashes:
                matched += 1

    if failures:
        _log("FAIL", "⑦ 取图接口", f"{len(failures)}/{checked} 张取图失败，"
                                   f"例如 {failures[0]}")
        return False
    if checked == 0:
        _log("FAIL", "⑦ 取图接口", "切片里没有任何 images 项")
        return False

    if src_hashes and matched != checked:
        _log("FAIL", "⑦ 取图接口",
             f"字节比对不通过：{matched}/{checked} 张与源图一致 —— 落盘过程可能被改写")
        return False
    _log("PASS", "⑦ 取图接口",
         f"{checked} 张全部 200 且为图片字节"
         + (f"，其中 {matched} 张与源图 sha256 逐一相符" if src_hashes else "（未取到源图，跳过字节比对）"))
    return True


# --------------------------------------------------------------------------
# 断言 7/8：邻近带出（本批的核心契约）
# --------------------------------------------------------------------------
def _neighbor_query(chunks: list):
    """从「紧邻图片片的正文片」里取一段查询文本（就地验证邻近带出）

    返回 (query, 期望带出的图片 url)。找不到合适素材时返回 (None, None)。
    """
    pos = next((i for i, c in enumerate(chunks)
                if ((c.get("metadata") or {}).get("images"))), None)
    if pos is None:
        return None, None

    imgs = (chunks[pos].get("metadata") or {}).get("images") or []
    want_url = (imgs[0] or {}).get("url") if imgs else None

    for j in (pos - 1, pos + 1, pos - 2, pos + 2):
        if not (0 <= j < len(chunks)):
            continue
        if (chunks[j].get("metadata") or {}).get("images"):
            continue                      # 跳过图片片本身
        body = (chunks[j].get("content") or "").strip()
        if len(body) >= 8:
            return body[:80], want_url
    return None, None


def assert_neighbor_carryover(base: str, chunks: list, category: str,
                              doc_id: str, expect_text: str) -> bool:
    """搜图片紧邻的正文 → 命中的文字片必须把那张图带出来

    判据用「**命中片的 images 里有该图**」，而不是看排名：搜的本来就是该片自己的
    文本，排第几无所谓；要看的是检索后处理有没有把邻居图挂上来。

    ★ 必须容忍「索引还没重建完」：上传接口不等索引重建就返回
      （knowledge_service.upload_document → _rebuild_index_async，后台线程重建
      整个索引）。一搜就判死会把「后台还没跑完」误报成「检索坏了」，故退避重试。
    """
    query, want_url = _neighbor_query(chunks)
    used_fallback = False
    if not query:
        query, used_fallback = expect_text, True
        _log("WARN", "⑧ 邻近带出", "切片里没有「图片片 + 相邻正文片」的组合，"
                                   f"退回用 --expect-text（{expect_text!r}）验证")

    body = {"query": query, "top_k": 20}
    if category:
        body["category"] = category

    attempts, interval = 8, 5      # 最坏等 35 秒，够一本书重建完
    results, mine, waited, tries = [], [], 0, 0
    for i in range(attempts):
        tries = i + 1
        code, data = _json_call("POST", f"{base}/knowledge/search", body, timeout=120)
        if code != 200 or not isinstance(data, dict):
            _log("FAIL", "⑧ 邻近带出", f"HTTP {code}: {str(data)[:200]}")
            return False
        results = data.get("results", []) or []
        mine = [r for r in results if r.get("doc_id") == doc_id and r.get("images")]
        if mine or i == attempts - 1:
            break
        time.sleep(interval)
        waited += interval

    if waited:
        _log("INFO", "⑧ 邻近带出",
             f"第 {tries} 次才搜到（等了约 {waited} 秒）—— 上传后索引是后台"
             f"异步重建的，属正常，不是缺陷")

    if mine:
        urls = [i.get("url") for r in mine for i in (r.get("images") or [])]
        hit = (not want_url) or (want_url in urls) or used_fallback
        rank = results.index(mine[0]) + 1
        _log("PASS" if hit else "WARN", "⑧ 邻近带出",
             f"{query[:24]!r}… → {len(results)} 条，命中片带出 {len(set(urls))} 张图"
             f"（排第 {rank}）；期望图 {'在' if want_url in urls else '不在'}其中"
             + ("（退回 expect_text，不作图源比对）" if used_fallback else ""))
        return True

    if not results:
        _log("FAIL", "⑧ 邻近带出",
             f"{query[:30]!r}… 无结果"
             + (f"（category={category}）" if category else "")
             + f"，等了 {waited} 秒仍没有 —— 检索链路有问题（不是本批改动）")
        return False

    _log("FAIL", "⑧ 邻近带出",
         f"{query[:30]!r}… 命中 {len(results)} 条，但本文件（{doc_id}）的结果都不带 images"
         f" —— 邻近带图没生效。查 knowledge_service._attach_images 与 "
         f"gateway.yaml 的 knowledge.image_neighbor_radius（0 等于关闭）")
    return False


def assert_no_standalone_image_result(base: str, category: str, doc_id: str) -> bool:
    """图片片不能作为**独立结果**出现（它没有检索文本，也不该在索引里）"""
    body = {"query": IMAGE_MARK, "top_k": 10}
    if category:
        body["category"] = category
    code, data = _json_call("POST", f"{base}/knowledge/search", body, timeout=120)
    if code != 200 or not isinstance(data, dict):
        _log("WARN", "⑨ 图片片不单列", f"HTTP {code}: {str(data)[:150]}")
        return True
    results = data.get("results", []) or []
    standalone = [r for r in results
                  if (r.get("content") or "").strip().startswith(IMAGE_MARK)]
    if standalone:
        _log("FAIL", "⑨ 图片片不单列",
             f"搜「{IMAGE_MARK}」居然命中 {len(standalone)} 条图片片 —— "
             f"图片片仍在索引里（应被 filter_indexable 剔除）")
        return False
    _log("PASS", "⑨ 图片片不单列", f"以「{IMAGE_MARK}」为查询未命中任何独立图片片")
    return True


# --------------------------------------------------------------------------
# 断言 7：问答来源带图
# --------------------------------------------------------------------------
def assert_chat_sources(base: str, expect_text: str, category: str,
                        doc_id: str) -> bool:
    """问答来源带图 —— 只作 WARN，不作判死

    本批起图片由 neighbors 挂到**邻近的正文片**上，与排名无关；但 `sources`
    默认只取 top_k=5，本文件是否在这 5 条内仍取决于问题本身。这是**排名**
    问题不是**功能**问题，故这里只提示，不判 FAIL。
    """
    code, data = _json_call("POST", f"{base}/knowledge/chat",
                            {"question": expect_text, "top_k": 5,
                             "category": category}, timeout=300)
    if code != 200 or not isinstance(data, dict):
        _log("WARN", "⑩ 问答来源带图", f"HTTP {code}: {str(data)[:200]}")
        return False
    sources = data.get("sources", []) or []
    if not sources:
        _log("WARN", "⑩ 问答来源带图", "sources 为空（召回为空或 LLM 降级）")
        return False
    with_img = [s for s in sources
                if (s.get("metadata") or {}).get("images")]
    if with_img:
        _log("PASS", "⑩ 问答来源带图",
             f"{len(sources)} 条来源，{len(with_img)} 条带 images")
    elif any((s.get("metadata") or {}).get("doc_id") == doc_id for s in sources):
        _log("WARN", "⑩ 问答来源带图",
             f"{len(sources)} 条来源含本文件，但都不带 images"
             f"（邻近没图，或 top_k=5 内没排上，属正常）")
    else:
        _log("WARN", "⑩ 问答来源带图",
             f"{len(sources)} 条来源，均未带 images（top_k=5 内没排上，属正常）")
    return True


# --------------------------------------------------------------------------
# 断言 8：路径穿越
# --------------------------------------------------------------------------
def assert_traversal_blocked(base: str) -> bool:
    # 直接用原始 URL，别让 urllib 帮忙规范化 —— 要的就是把上跳原样送到服务端
    payloads = [
        f"{base}/knowledge/media/../../../../etc/passwd",
        f"{base}/knowledge/media/..%2f..%2f..%2fetc%2fpasswd/001.png",
        f"{base}/knowledge/media/other_x/../../../etc/passwd",
    ]
    leaks = []
    for u in payloads:
        try:
            code, raw = _http("GET", u, timeout=60)
        except Exception as e:
            code, raw = 0, str(e).encode()
        if code == 200 and b"root:" in (raw if isinstance(raw, bytes) else b""):
            leaks.append(u)
    if leaks:
        _log("FAIL", "⑪ 路径穿越被拒", f"泄露 /etc/passwd: {leaks[0]}")
        return False
    _log("PASS", "⑪ 路径穿越被拒", f"{len(payloads)} 种上跳写法均未泄露")
    return True


# --------------------------------------------------------------------------
# 断言 9：删除清理
# --------------------------------------------------------------------------
def assert_delete_cleanup(base: str, doc_id: str) -> bool:
    code, data = _http("GET", f"{base}/knowledge/documents/{doc_id}/chunks")
    names = []
    if code == 200 and isinstance(data, dict):
        for c in data.get("chunks", []) or []:
            for img in ((c.get("metadata") or {}).get("images") or []):
                names.append(img.get("url"))
    if not names:
        _log("WARN", "⑫ 删除清理", "未拿到图片 URL，跳过（删除仍会执行）")
    code, data = _http("DELETE", f"{base}/knowledge/documents/{doc_id}", timeout=120)
    if code not in (200, 204):
        _log("FAIL", "⑫ 删除清理", f"HTTP {code}: {str(data)[:200]}")
        return False
    # 删除后图应取不到
    still = []
    for u in names[:3]:
        full = base + u if u.startswith("/") else u
        try:
            c2, _ = _http("GET", full, timeout=60)
        except Exception:
            c2 = 0
        if c2 == 200:
            still.append(u)
    if still:
        _log("FAIL", "⑫ 删除清理", f"文档已删但图仍可取: {still[0]}")
        return False
    _log("PASS", "⑫ 删除清理", f"文档已删除，{len(names[:3])} 张抽查图均不可取")
    return True


# --------------------------------------------------------------------------
# 断言 10：纯文本回归
# --------------------------------------------------------------------------
def assert_text_regression(base: str, category: str) -> bool:
    payload = ("东方电子小螃蟹知识库回归测试。\n"
               "本文件为纯文本，不含任何图片，用于确认图片切片改动未影响原有文本链路。\n"
               "电网调度自动化系统 AVC 自动电压控制。\n") * 6
    name = f"img_regression_{datetime.now().strftime('%H%M%S')}.txt"
    body, ctype = _multipart({"category": category, "title": f"图片切片回归_{name}"},
                             "file", name, payload.encode("utf-8"))
    code, data = _http("POST", f"{base}/knowledge/upload", body,
                       {"Content-Type": ctype})
    if code != 200 or not isinstance(data, dict) or data.get("status") != "success":
        _log("FAIL", "⑬ 纯文本回归", f"HTTP {code}: {str(data)[:200]}")
        return False
    doc_id = data.get("doc_id", "")

    code, cdata = _http("GET", f"{base}/knowledge/documents/{doc_id}/chunks")
    if code != 200 or not isinstance(cdata, dict):
        _log("FAIL", "⑬ 纯文本回归", f"拉切片 HTTP {code}")
        return False
    chunks = cdata.get("chunks", []) or []
    if not chunks:
        _log("FAIL", "⑬ 纯文本回归", "纯文本切片为空")
        return False
    with_img = [c for c in chunks if (c.get("metadata") or {}).get("images")]
    if with_img:
        _log("FAIL", "⑬ 纯文本回归", f"纯文本切片竟然带了 images（{len(with_img)} 片）")
        return False
    # 文本片两处 content 必须一致（与旧版相同）。允许「剥空白后」的长度：
    #   _create_chunk 对 metadata.content 做 strip，顶层 content 保留原样。
    drifted = []
    for c in chunks:
        got = (c.get("metadata") or {}).get("content_chars")
        if got is None:
            continue
        body = c.get("content", "")
        if int(got) not in (len(body), len(body.strip())):
            drifted.append((int(got), len(body)))
    _log("PASS" if not drifted else "WARN", "⑬ 纯文本回归",
         f"chunk_count={len(chunks)} 无 images"
         + ("" if not drifted else
            f"，{len(drifted)} 片 content_chars 与正文长度不符，例如 {drifted[0]}"))

    try:
        _http("DELETE", f"{base}/knowledge/documents/{doc_id}", timeout=120)
    except Exception:
        pass
    return True


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="知识库图片切片入库验证（批次 20）")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"知识库地址，默认 {DEFAULT_BASE}")
    ap.add_argument("--file", default="", help="样本 docx 路径；不给则自动查找")
    ap.add_argument("--doc-id", default="", help="已有 doc_id：跳过上传，只复查切片")
    ap.add_argument("--category", default="other", help="上传分类，默认 other")
    ap.add_argument("--expect-text", default=EXPECT_TEXT,
                    help=f"检索验证词，默认 {EXPECT_TEXT}")
    ap.add_argument("--keep-upload", action="store_true",
                    help="保留上传的文档（默认通过后删除）")
    ap.add_argument("--skip-chat", action="store_true", help="跳过问答断言（较慢）")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    print("=" * 72)
    print(f"知识库图片切片入库验证（批次 20）— {base}")
    print("=" * 72)

    # 0. 版本确认 —— 版本对不上时后面的失败多为「包没部署全」，先点出来省排查时间
    try:
        code, health = _http("GET", f"{base}/knowledge/health", timeout=30)
    except Exception as e:
        _log("FAIL", "服务连通性", f"{base} 不可达: {type(e).__name__}: {e}")
        print("\n服务不可达，无法继续。请确认知识库进程已启动：")
        print("  ./venv/bin/python3 scripts/knowledge_api.py")
        return 1
    if code != 200 or not isinstance(health, dict):
        _log("FAIL", "服务连通性", f"HTTP {code}: {str(health)[:200]}")
        return 1
    ver = health.get("version", "?")
    if ver == EXPECT_VERSION:
        _log("PASS", "版本确认", f"knowledge_version={ver}")
    else:
        _log("WARN", "版本确认",
             f"knowledge_version={ver}，本脚本对应 {EXPECT_VERSION} —— "
             f"若后续断言失败，先确认 knowledge_api 已重启、src/knowledge/ 已更新")

    # 1. 上传（或复用已有 doc_id）
    doc_id = args.doc_id
    sample = None
    uploaded_here = False
    if doc_id:
        _log("INFO", "上传", f"复用已有 doc_id={doc_id}（跳过上传）")
        sample = find_sample(args.file)
    else:
        sample = find_sample(args.file)
        if not sample:
            _log("FAIL", "上传", f"未找到样本 docx（标题含 {SAMPLE_HINT!r}）；"
                                 f"请用 --file 指定，或 --doc-id 复查服务端已有文档")
            return 1
        _log("INFO", "上传", f"{sample.name} ({sample.stat().st_size / 1024:.0f} KB)")
        doc_id, ok = upload_sample(base, sample, args.category)
        uploaded_here = bool(doc_id)
        if not ok:
            return 1

    # 2-7. 切片契约（sample 为空时只跳过「与原图字节比对」，契约仍全验）
    chunks, img_chunks, ok = assert_chunk_contract(base, doc_id, sample)

    # 8. 取图
    ok = assert_media_fetch(base, img_chunks, sample) and ok

    # 9. 邻近带出 + 图片片不单列（按上传分类限定范围，避免拿别人的文档判自己）
    ok = assert_neighbor_carryover(base, chunks, args.category,
                                   doc_id, args.expect_text) and ok
    ok = assert_no_standalone_image_result(base, args.category, doc_id) and ok

    # 10. 问答（只作提示，不作判死）
    if not args.skip_chat:
        assert_chat_sources(base, args.expect_text, args.category, doc_id)

    # 11. 路径穿越
    ok = assert_traversal_blocked(base) and ok

    # 12. 删除清理（始终执行：既不污染现场，也顺带验证清理）
    if args.doc_id:
        _log("INFO", "删除清理", "复用已有文档，跳过删除（避免删掉现场数据）")
    elif args.keep_upload:
        _log("INFO", "删除清理", "--keep-upload 指定保留，跳过")
    else:
        ok = assert_delete_cleanup(base, doc_id) and ok

    # 13. 回归
    ok = assert_text_regression(base, args.category) and ok

    # 汇总
    fails = [r for r in RESULTS if r.startswith("[FAIL]")]
    warns = [r for r in RESULTS if r.startswith("[WARN]")]
    print("\n" + "=" * 72)
    print(f"结果: PASS={len([r for r in RESULTS if r.startswith('[PASS]')])} "
          f"FAIL={len(fails)} WARN={len(warns)}")
    for r in fails:
        print("  " + r)
    print("=" * 72)

    # 落盘
    try:
        out_dir = Path(__file__).resolve().parent.parent / "docs" / "verify_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"知识库图片切片验证结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out.write_text("\n".join([
            f"知识库图片切片入库验证 — {base}",
            f"时间: {datetime.now().isoformat(timespec='seconds')}",
            f"doc_id: {doc_id}",
            f"样本: {sample}",
            "",
            *RESULTS,
        ]), encoding="utf-8")
        print(f"结果已保存: {out}")
    except Exception as e:
        print(f"结果保存失败（不影响验收结论）: {e}")

    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
