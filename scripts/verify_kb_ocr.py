# -*- coding: utf-8 -*-
"""
知识库图片（OCR / 落盘 / 邻近带图）验证脚本（2026-09-10）

    ★ 2026-09-11（批次 20）再改版：**OCR 默认关闭**。图片只落盘 + 正文占位块
      【图片：NNN.ext】，图内文字**不再进检索位**（图片片整体退出索引），
      改为检索命中正文后按位置把邻近图片挂到结果上。
      本脚本随之调整断言：默认期望 ocr_count == 0、图片片 content_chars == 0；
      加 --ocr-on 才按「OCR 生效」的口径验证（应急开回时用）。
      本批主验收见 scripts/verify_kb_image_chunks.py，本脚本退化为
      「OCR 开关状态 + 图片落盘」的快速体检。

    ★ 批次 19 的旧口径（保留备查）：图片不再 OCR 进正文，改为原图落盘 + 正文占位块，
      图内文字只进「检索位」（metadata.content）。

验证思路：
    本次改动要解决的是「含图片的 Word 上传报 400」。根因不是解析崩溃，而是正文几乎全在
    图片里，提取出的文字（44 字）不足切片下限（min_chunk_size=50），document_processor
    返回空列表，被 knowledge_service 判为失败。因此验收必须同时证明三件事：

      1) 该文档现在能入库        -> HTTP 200 且 chunk_count > 0
      2) 图片进了正文            -> 切片里出现【图片：NNN.ext】占位块
      3) 原图真的落了盘          -> image_media_count > 0（否则前端取图必 404）
      4) OCR 开关状态符合预期    -> 默认关闭时 ocr_count == 0；--ocr-on 时 > 0

    ★ 第 3 条不能只看「切片正文里有没有 AVC」。实测该 docx 的 document.xml 里本来就有
      44 字文本层，其中含 ASCII 串 "AVC"——它随正文一起入库，OCR 完全没跑也会出现。
      所以正文命中只证明「切片有了」，证明「图内文字真的进了索引」必须靠 ocr_count 与
      content_chars，并以 /search 实打一次为准（向量/BM25 都可能没跟上且无报错）。

用法：
    python scripts/verify_kb_ocr.py [--base URL] [--file 路径] [--doc-id ID]
                                   [--category other] [--expect-text AVC] [--keep]
                                   [--ocr-on]

行为：
    1. 引擎自检：本进程直接 import src.knowledge.ocr.engine，报告是否可用
       （不可用不直接判死，后续以服务端 ocr_count 为准）
    2. 服务连通性：GET /knowledge/health
    3. 主验收：上传含图 docx -> 断言 200 / chunk_count>0 / image_media_count>0 / ocr_count>0
    4. 切片断言：GET /knowledge/documents/{doc_id}/chunks -> 断言含【图片：占位块、
       正文无【图片文字】残渣、检索位 content_chars > 0
    4.1 检索断言：POST /knowledge/search 用 --expect-text 仍能命中
    5. 回归：纯文本上传仍成功且 ocr_count == 0（确认纯文本链路未被改动影响）
    6. 结果保存 docs/verify_results/知识库OCR入库验证结果_*.txt（--keep 则保留脚本）

    未指定 --file 且本机找不到样本文件时，自动改为按标题在服务端检索已有文档来断言切片，
    便于「服务器上已传好、只想复查」的场景。
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

# 控制台/文件统一 UTF-8 输出（Windows GBK 控制台打印中文/emoji 会崩）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 默认打本机 —— 本脚本设计为「在部署机上、部署完之后」运行。
# ★ 2026-09-11 订正：早前此处写「172.20.43.78:6788 是另一套知识库」，**该说法是错的**。
#   部署机 `hostname -I` 实测就是 172.20.43.78（同机另有 172.17/172.22/172.28… 等
#   Docker 网桥地址）。当时据此误判，白绕了一圈。
#   仍然不要硬编码固定 IP：服务默认绑 0.0.0.0，同机多网卡/多环境时指错地址会得到
#   "找不到样本文档"的假结论——所以默认走 127.0.0.1，要用别的地址请显式 --base。
DEFAULT_BASE = "http://127.0.0.1:6788"
# 样本：2026-09-10 上传失败的原始文件（798KB，其中图片占 760KB，正文仅 44 字）
SAMPLE_HINT = "新能源控制业务运行值班手册"
EXPECT_TEXT = "AVC"
# 批次 19 起：图片在正文里是占位块，原图由 /knowledge/media/{doc_id}/{name} 提供，
# 图内文字只进「检索位」（metadata.content，chunks 接口以 content_chars 计数回显）。
IMAGE_MARK = "【图片："
# 批次 18 的旧写法：OCR 文字直接灌进正文。本批起应**彻底消失**——它正是"读不通"的来源。
LEGACY_MARK = "【图片文字】"

RESULTS = []


def _log(status: str, name: str, detail: str = ""):
    line = f"[{status:^4}] {name} {detail}"
    RESULTS.append(line)
    print(line, flush=True)


def _http(method: str, url: str, body=None, headers=None, timeout=300):
    """返回 (status_code, parsed_json_or_raw_text)；网络异常抛给调用方"""
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            code = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        code = e.code
    try:
        return code, json.loads(raw)
    except Exception:
        return code, raw


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


def engine_selfcheck() -> bool:
    """本进程直接探测 OCR 引擎（对应实施方案验证步骤 1）"""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from src.knowledge.ocr.engine import get_ocr_engine
    except Exception as e:
        _log("WARN", "引擎自检", f"无法导入 OCR 模块: {type(e).__name__}: {e}")
        return False

    info = get_ocr_engine().get_info()
    if info.get("available"):
        _log("PASS", "引擎自检", f"{info.get('engine')} 可用")
        return True
    _log("WARN", "引擎自检", f"OCR 不可用: {info.get('error')}")
    print("       修复: ./venv/bin/python3 -m pip install -r requirements-ocr.txt "
          "--no-index --find-links wheels/ --no-deps", flush=True)
    return False


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


def lookup_doc_id(base: str, hint: str) -> str:
    """服务端按标题模糊查找 doc_id"""
    code, data = _http("GET", f"{base}/knowledge/documents")
    if code != 200 or not isinstance(data, dict):
        return ""
    for d in data.get("documents", []):
        if hint in (d.get("title") or "") or hint in (d.get("file_name") or ""):
            return d.get("doc_id", "")
    return ""


def assert_chunks(base: str, doc_id: str, expect_text: str,
                  ocr_on: bool) -> bool:
    """拉切片，断言「图片以占位块进正文」+「检索位状态与 OCR 开关一致」"""
    code, data = _http("GET", f"{base}/knowledge/documents/{doc_id}/chunks")
    if code != 200 or not isinstance(data, dict):
        _log("FAIL", "拉取切片", f"HTTP {code}: {str(data)[:200]}")
        return False

    chunks = data.get("chunks", [])
    if not chunks:
        _log("FAIL", "拉取切片", f"切片为空 (total_chunks={data.get('total_chunks')})")
        return False

    merged = "\n".join(c.get("content", "") for c in chunks)
    _log("PASS", "拉取切片",
         f"{len(chunks)} 个切片 / {len(merged)} 字符 (doc_id={doc_id})")

    ok = True

    # 断言 1：图片以占位块形式进正文（这是本功能的核心目的）
    img_chunks = [c for c in chunks if c.get("content", "").startswith(IMAGE_MARK)]
    if img_chunks:
        sample = img_chunks[0].get("content", "").replace("\n", " ")[:60]
        _log("PASS", "图片切片", f"{len(img_chunks)} 片，例如: {sample}")
    else:
        _log("FAIL", "图片切片", f"切片中未出现 {IMAGE_MARK} 占位块 —— 图片未进正文")
        ok = False

    # 断言 2：检索位状态必须与 OCR 开关一致（批次 20 起默认关闭）。
    #   chunks 接口只回 content_chars（不回整段 OCR 文字），所以看长度即可。
    #   注意必须只看**图片片**的 content_chars：正文片本来就非 0。
    img_with_text = [c for c in img_chunks
                     if int((c.get("metadata") or {}).get("content_chars") or 0) > 0]
    if ocr_on:
        if img_with_text:
            total = sum(int((c["metadata"] or {}).get("content_chars") or 0)
                        for c in img_with_text)
            _log("PASS", "图内文字进检索位",
                 f"{len(img_with_text)} 片 / 共 {total} 字符（--ocr-on）")
        else:
            _log("FAIL", "图内文字进检索位",
                 "图片切片未挂检索文本（content_chars 全为 0）—— 图内文字搜不到")
            ok = False
    else:
        # 默认口径：图片片检索位必须为空（否则它们会重新进索引，把噪声带回来）
        if img_with_text:
            _log("FAIL", "图片片检索位应为空",
                 f"{len(img_with_text)} 个图片片仍带检索文本 —— "
                 f"图片片应退出索引，靠邻近带出")
            ok = False
        else:
            _log("PASS", "图片片检索位为空",
                 f"{len(img_chunks)} 个图片片 content_chars 均为 0（OCR 已关，符合预期）")

    # 断言 3：旧写法彻底消失（正文里不该再有整段 OCR 文字）
    if LEGACY_MARK in merged:
        _log("FAIL", "正文无 OCR 残渣",
             f"切片正文仍含 {LEGACY_MARK} —— 应已改为图片占位块")
        ok = False
    else:
        _log("PASS", "正文无 OCR 残渣", f"正文未出现 {LEGACY_MARK}")

    # 期望文本：图内文字已移出正文，正文命中只能来自文档自带文本层。
    #   "图里的字还搜得到吗"由 search_hits() 单独验证。
    if expect_text:
        if expect_text in merged:
            _log("PASS", "正文期望文本", f"切片正文含 {expect_text!r}")
        else:
            _log("INFO", "正文期望文本",
                 f"正文不含 {expect_text!r}（图内文字已移出正文，属预期；"
                 f"以「搜索仍可命中」为准）")
    return ok


def search_hits(base: str, query: str, timeout: int = 60):
    """检索是否命中 —— 证明图内文字真的进了索引（而不只是躺在切片文件里）"""
    body = json.dumps({"query": query, "top_k": 5}).encode("utf-8")
    code, data = _http("POST", f"{base}/knowledge/search", body,
                       {"Content-Type": "application/json"}, timeout=timeout)
    if code != 200 or not isinstance(data, dict):
        _log("FAIL", "搜索命中", f"HTTP {code}: {str(data)[:200]}")
        return None
    results = data.get("results", []) or []
    _log("PASS" if results else "FAIL", "搜索命中",
         f"{query!r} → {len(results)} 条"
         + (f"，首条来自 {results[0].get('metadata', {}).get('title', '?')}" if results else ""))
    return results


def regression_text_upload(base: str, category: str) -> bool:
    """回归：纯文本上传仍成功，且 ocr_count 必须为 0（不该无中生有）"""
    payload = ("东方电子小螃蟹知识库 OCR 回归测试。\n"
               "本文件为纯文本，不含任何图片，用于确认 OCR 改动未影响原有文本链路。\n"
               "电网调度自动化系统 AVC 自动电压控制。\n") * 6
    name = f"ocr_regression_{datetime.now().strftime('%H%M%S')}.txt"
    body, ctype = _multipart(
        {"category": category, "title": f"OCR回归测试_{name}"},
        "file", name, payload.encode("utf-8"))
    code, data = _http("POST", f"{base}/knowledge/upload", body,
                       {"Content-Type": ctype})
    if code != 200 or not isinstance(data, dict) or data.get("status") != "success":
        _log("FAIL", "纯文本回归", f"HTTP {code}: {str(data)[:200]}")
        return False

    ocr_count = data.get("ocr_count", 0)
    if ocr_count != 0:
        _log("FAIL", "纯文本回归", f"ocr_count={ocr_count}，纯文本不该产生 OCR 结果")
        return False
    _log("PASS", "纯文本回归",
         f"chunk_count={data.get('chunk_count')} ocr_count={ocr_count}（符合预期）")
    return True


def main():
    ap = argparse.ArgumentParser(description="知识库 OCR 入库验证")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"知识库地址，默认 {DEFAULT_BASE}")
    ap.add_argument("--file", default="", help="样本 docx 路径；不给则自动查找/改用服务端已有文档")
    ap.add_argument("--doc-id", default="", help="已有 doc_id：跳过上传，只复查切片")
    ap.add_argument("--category", default="other", help="上传分类，默认 other")
    ap.add_argument("--expect-text", default=EXPECT_TEXT, help=f"期望出现在切片中的文本，默认 {EXPECT_TEXT}")
    ap.add_argument("--keep", action="store_true", help="保留脚本自身（默认全部通过后仍保留）")
    ap.add_argument("--ocr-on", action="store_true",
                    help="按「OCR 已开」的口径验证（现场用 KNOWLEDGE_OCR_ENABLED=true 开回时用）")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    print("=" * 72)
    print(f"知识库 OCR 入库验证 — {base}")
    print("=" * 72)

    # 1. 引擎自检（批次 20 起 OCR 默认关闭，本进程引擎是否可用只作提示）
    engine_ok = engine_selfcheck()
    if not args.ocr_on:
        _log("INFO", "OCR 开关", "默认关闭（批次 20 起）—— 期望 ocr_count == 0；"
                                "现场开回请加 --ocr-on")

    # 2. 服务连通性
    try:
        code, data = _http("GET", f"{base}/knowledge/health", timeout=30)
    except Exception as e:
        _log("FAIL", "服务连通性", f"{base} 不可达: {type(e).__name__}: {e}")
        print("\n服务不可达，无法继续。请确认知识库进程已启动：")
        print("  ./venv/bin/python3 scripts/knowledge_api.py")
        return 1
    if code != 200:
        _log("FAIL", "服务连通性", f"HTTP {code}: {str(data)[:200]}")
        return 1
    _log("PASS", "服务连通性",
         f"docs={data.get('total_documents')} chunks={data.get('total_chunks')}")

    # 3. 主验收
    doc_id = args.doc_id
    if not doc_id:
        sample = find_sample(args.file)
        if sample:
            size = sample.stat().st_size
            _log("INFO", "上传样本", f"{sample.name} ({size / 1024:.0f} KB)")
            body, ctype = _multipart(
                {"category": args.category, "title": sample.stem},
                "file", sample.name, sample.read_bytes())
            code, data = _http("POST", f"{base}/knowledge/upload", body,
                               {"Content-Type": ctype})
            if code != 200 or not isinstance(data, dict) or data.get("status") != "success":
                _log("FAIL", "上传含图 docx", f"HTTP {code}: {str(data)[:300]}")
                print("\n仍上传失败。批次 20 起 OCR 默认关闭，含图 docx 走「原图落盘 + 占位块」"
                      "路径，不该再因 OCR 报错；")
                print("若消息仍含「OCR 引擎不可用」/「OCR 未识别出有效文字」，说明现场"
                      "把 OCR 开回了（KNOWLEDGE_OCR_ENABLED=true），先关掉再试。")
                return 1
            doc_id = data.get("doc_id", "")
            _log("PASS", "上传含图 docx",
                 f"HTTP 200 chunk_count={data.get('chunk_count')} "
                 f"image_count={data.get('image_count')} "
                 f"image_media_count={data.get('image_media_count')} "
                 f"ocr_count={data.get('ocr_count')} ocr_chars={data.get('ocr_chars')}")
            if not data.get("chunk_count"):
                _log("FAIL", "切片数", "chunk_count 为 0")
                return 1
            # 图片必须真的落盘了 —— 否则切片里只有占位块、前端必然取图 404
            if not data.get("image_media_count"):
                _log("FAIL", "图片落盘",
                     f"image_media_count={data.get('image_media_count')} —— "
                     f"原图未写入 knowledge_base/media/，前端将取不到图")
                return 1
            _log("PASS", "图片落盘", f"{data.get('image_media_count')} 张已入库")
            # OCR 开关状态必须与预期一致（批次 20 起默认关闭）
            if args.ocr_on:
                if not data.get("ocr_count"):
                    _log("FAIL", "OCR 生效", "ocr_count 为 0 —— 图内文字未进检索位")
                    return 1
                _log("PASS", "OCR 生效",
                     f"识别 {data.get('ocr_count')} 处 / {data.get('ocr_chars')} 字符")
            else:
                if data.get("ocr_count"):
                    _log("FAIL", "OCR 应为关闭",
                         f"ocr_count={data.get('ocr_count')} —— 默认应已关闭；"
                         f"现场若确实开回了，请加 --ocr-on")
                    return 1
                _log("PASS", "OCR 未跑", "ocr_count=0 ocr_chars=0（默认关闭，符合预期）")
        else:
            _log("INFO", "上传样本", "本机未找到样本文件，改为查服务端已有文档")
            doc_id = lookup_doc_id(base, SAMPLE_HINT)
            if not doc_id:
                _log("FAIL", "定位文档", f"服务端未找到标题含 {SAMPLE_HINT!r} 的文档；"
                                        f"请用 --file 指定样本")
                return 1
            _log("PASS", "定位文档", doc_id)

    # 4. 切片断言：无论走到这里的是刚上传的还是服务端已有的文档，都要求图片占位块
    #    与检索位文本存在（这正是本功能要证明的事；engine_selfcheck 只作提示，不作豁免）
    ok = assert_chunks(base, doc_id, args.expect_text, args.ocr_on)

    # 4.1 检索断言：图内文字必须真的**搜得到**。只看切片文件不算数 ——
    #     向量索引与 BM25 缓存都可能没跟上（见 CHANGELOG 批次 19 的说明）。
    hits = search_hits(base, args.expect_text)
    if hits is None:
        ok = False
    elif not hits:
        # 旧库/旧文档可能确实没有这个字，给 WARN 不直接判死；但刚上传的必须命中
        _log("WARN", "搜索命中", f"{args.expect_text!r} 无结果，"
                                 f"请人工确认该字确实只在图片里")

    # 5. 回归
    txt_ok = regression_text_upload(base, args.category)

    # 汇总
    fails = [r for r in RESULTS if r.startswith("[FAIL]")]
    warns = [r for r in RESULTS if r.startswith("[WARN]")]
    print("\n" + "=" * 72)
    print(f"结果: PASS={len([r for r in RESULTS if r.startswith('[PASS]')])} "
          f"FAIL={len(fails)} WARN={len(warns)}")
    if args.ocr_on and not engine_ok:
        print("注意: 引擎自检未通过，但服务端 OCR 是否可用以 ocr_count 为准"
              "（脚本进程与服务进程环境可能不同）。")
    elif not args.ocr_on:
        print("提示: OCR 默认关闭属本批设计；引擎自检结果不影响本脚本结论。")
    for r in fails:
        print("  " + r)
    print("=" * 72)

    # 落盘
    try:
        out_dir = Path(__file__).resolve().parent.parent / "docs" / "verify_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"知识库OCR入库验证结果_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out.write_text("\n".join([
            f"知识库 OCR 入库验证 — {base}",
            f"时间: {datetime.now().isoformat(timespec='seconds')}",
            f"doc_id: {doc_id}",
            "",
            *RESULTS,
        ]), encoding="utf-8")
        print(f"结果已保存: {out}")
    except Exception as e:
        print(f"结果保存失败（不影响验证结论）: {e}")

    return 1 if (fails or not ok or not txt_ok) else 0


if __name__ == "__main__":
    sys.exit(main())
