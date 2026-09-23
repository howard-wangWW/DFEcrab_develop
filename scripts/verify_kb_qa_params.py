#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""知识库 r4 合并验收 —— 问答参数（同事那批）与入库/带图（我方那批）是否**并存**。

背景（2026-09-14）：
    同事的 src.zip 与我的知识库更新包都改过这两个文件，且改法互相冲突——
        src/config/port_loader.py
        src/knowledge/knowledge_service.py
    他加了 qa_enable_thinking / qa_temperature / qa_top_k / qa_max_per_doc /
    qa_max_context_chunks 与 .llm.config_loader 装配，同时删掉了我的
    knowledge_ocr() / image_neighbor_radius / _attach_images / _store_images。
    谁单方面覆盖谁，都会砸掉对方。r4 把两边合并进同一份文件。

    本脚本只回答一个问题：**这两份文件里，两边的符号是不是都在？**

用法：
    cd <项目根>
    ./venv/bin/python3 scripts/verify_kb_qa_params.py            # 源码 + 配置 + 装配 + 在线问答
    ./venv/bin/python3 scripts/verify_kb_qa_params.py --offline  # 不连知识库服务，只查代码与配置

期望：FAIL=0 且退出码 0。
    WARN 不算失败（例如现场没配 LLM、或库里还没有图片切片）。

★ 本脚本**只读**，不改任何文件、不写库。
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

try:  # 控制台不是 UTF-8 时别让打印把脚本弄崩
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ★ 与 scripts/knowledge_api.py 对齐（那里也是同时塞「项目根」和「项目根/src」）。
#   不塞 src 的话，config_loader 内部的 `from config.port_loader import ...` 会失败、
#   静默退回内置默认值 —— 而默认值与常见现场配置恰好相同，本脚本就会把
#   「读不到 gateway.yaml」误判成通过。加上这一行才是服务进程的真实条件。
_SRC = ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

N_PASS = 0
N_FAIL = 0
N_WARN = 0


def ok(msg):    _bump("PASS"); print("  ✔ %s" % msg)
def bad(msg):   _bump("FAIL"); print("  ✗ %s" % msg)
def warn(msg):  _bump("WARN"); print("  ⚠️ %s" % msg)


def _bump(kind):
    global N_PASS, N_FAIL, N_WARN
    if kind == "PASS":
        N_PASS += 1
    elif kind == "FAIL":
        N_FAIL += 1
    else:
        N_WARN += 1


def read(rel):
    p = ROOT / rel
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        warn("读 %s 失败: %s" % (rel, e))
        return None


# ─────────────────────────── A. 源码级：两边符号必须共存 ───────────────────────────
def check_source_coexist():
    print("\n【A】两处「两边都改过」的文件 —— 两边符号必须同时在")

    both = [
        ("src/config/port_loader.py",
         "knowledge_ocr", "qa_max_context_chunks", "OCR/带图半径 与 问答参数"),
        ("src/knowledge/knowledge_service.py",
         "_attach_images", "_fetch_k", "邻近带图 与 超采/分类过滤"),
    ]
    for rel, mine, his, what in both:
        s = read(rel)
        if s is None:
            bad("%s 不存在" % rel)
            continue
        has_m, has_h = mine in s, his in s
        if has_m and has_h:
            ok("%s：%s **并存**（%s / %s）" % (rel, what, mine, his))
        elif has_m:
            bad("%s 只有我方的 %s，缺他的 %s —— 他的改动被覆盖了" % (rel, mine, his))
        elif has_h:
            bad("%s 只有他的 %s，缺我方的 %s —— 我的改动被覆盖了" % (rel, his, mine))
        else:
            bad("%s 两边的符号都没有，文件可能被换成了别的版本" % rel)

    # 同事那边**不在本包清单里**的文件：只提示状态，不判死
    print("\n  · 同事侧文件现状（本包不装它们，仅确认没被本包压坏）：")
    for rel, kw, label in [
        ("src/knowledge/llm/openai_client.py", "enable_thinking", "他的思考开关/温度下发"),
        ("src/knowledge/skills/knowledge_qa.py", "max_context_chunks", "他的 max_context_chunks 接线"),
        ("src/knowledge/skills/knowledge_search.py", None, "他的检索技能"),
    ]:
        s = read(rel)
        if s is None:
            warn("%s 不在（现场可能还没同步他那批）" % rel)
        elif kw is None:
            ok("%s 在" % rel)
        elif kw in s:
            ok("%s 在，且含 %s（%s）" % (rel, kw, label))
        else:
            warn("%s 在，但没有 %s（%s）—— 他那批可能只同步了一部分"
                 % (rel, kw, label))


# ─────────────────────────── B. 配置级：qa_* 与 OCR 都能读出来 ───────────────────────────
def load_port_loader():
    """两种导入路径都试：`config.port_loader`（现场脚本的用法）与
    `src.config.port_loader`（把项目根塞进 sys.path 的用法）。
    与 src/knowledge/storage/document_loader.py 里读 OCR 配置的范式一致。"""
    for name in ("config.port_loader", "src.config.port_loader"):
        try:
            mod = __import__(name, fromlist=["knowledge_chunk_config", "knowledge_ocr"])
            return mod, name
        except Exception:
            continue
    return None, None


def check_config():
    print("\n【B】配置读取：知识库运行参数（两边的键都要在）")
    mod, mod_name = load_port_loader()
    if mod is None:
        bad("config.port_loader 与 src.config.port_loader 都导入不了"
            "（请确认在项目根目录下运行本脚本）")
        return None, None
    if mod_name != "config.port_loader":
        print("     （经 %s 导入 —— 现场脚本走的是 config.port_loader，此处等价）" % mod_name)

    knowledge_chunk_config = mod.knowledge_chunk_config
    knowledge_ocr = mod.knowledge_ocr
    cc = knowledge_chunk_config() or {}

    his_keys = ["qa_enable_thinking", "qa_temperature", "qa_top_k",
                "qa_max_per_doc", "qa_max_context_chunks"]
    miss = [k for k in his_keys if k not in cc]
    if miss:
        bad("缺同事的问答参数: %s" % ", ".join(miss))
    else:
        ok("问答参数齐: qa_top_k=%s qa_max_per_doc=%s qa_max_context_chunks=%s "
           "qa_temperature=%s qa_enable_thinking=%s"
           % (cc["qa_top_k"], cc["qa_max_per_doc"], cc["qa_max_context_chunks"],
              cc["qa_temperature"], cc["qa_enable_thinking"]))

    if "image_neighbor_radius" not in cc:
        bad("缺我方的 image_neighbor_radius（邻近带图半径）")
    else:
        ok("邻近带图半径 image_neighbor_radius=%s" % cc["image_neighbor_radius"])

    # qa_enable_thinking 允许 None（= 不下发该字段），但类型不能是字符串
    v = cc.get("qa_enable_thinking", "缺")
    if v == "缺":
        pass
    elif v is None or isinstance(v, bool):
        ok("qa_enable_thinking 类型正确（%r；None=不下发该字段）" % (v,))
    else:
        bad("qa_enable_thinking 应是 None 或 bool，实际是 %r" % (v,))

    for k in ("qa_top_k", "qa_max_per_doc", "qa_max_context_chunks", "qa_temperature"):
        if k in cc and not isinstance(cc[k], (int, float)):
            bad("%s 应是数字，实际是 %r" % (k, cc[k]))

    try:
        ocr = knowledge_ocr() or {}
        if not isinstance(ocr, dict) or "enabled" not in ocr:
            bad("knowledge_ocr() 没返回带 enabled 的 dict（实际 %r）—— 注意它返回的是**整段配置**不是 bool" % (ocr,))
        else:
            print("     （OCR 总开关当前：%s —— 批次20 起默认关闭）"
                  % ("开启" if ocr["enabled"] else "关闭"))
    except Exception as e:
        bad("knowledge_ocr() 调用失败: %s: %s" % (type(e).__name__, e))

    return cc, None


# ─────────────────────────── C. 装配级：他的 config_loader 能跑 ───────────────────────────
def check_skill_config():
    print("\n【C】问答配置装配（.llm.config_loader）")
    try:
        from src.knowledge.llm.config_loader import load_skill_config
    except Exception as e:
        warn("导入 .llm.config_loader 失败: %s: %s" % (type(e).__name__, e))
        print("     知识库服务会回落到内置读取：问答照常跑，只是不下发 "
              "qa_temperature / enable_thinking。**入库与检索不受影响。**")
        return

    ok("src/knowledge/llm/config_loader.py 可导入")

    # ★ 先探「它自己能不能读到 gateway.yaml」。读不到时会用内置默认值，
    #   而默认值与常见现场配置恰好相同 —— 只看下面 cfg 的数字分辨不出来。
    try:
        from src.knowledge.llm import config_loader as _cl
        _probe = getattr(_cl, "_chunk_config", lambda: {})()
        if _probe:
            ok("装配模块能从 gateway.yaml 读到 knowledge 段（%d 个键）" % len(_probe))
        else:
            bad("装配模块读不到 gateway.yaml（退回内置默认值）—— "
                "现场在 gateway.yaml 里写的 qa_* / filter_overfetch / "
                "image_neighbor_radius 覆盖都不会生效")
    except Exception as e:
        warn("无法探测装配模块的配置读取: %s: %s" % (type(e).__name__, e))

    try:
        cfg = load_skill_config()
    except Exception as e:
        bad("load_skill_config() 调用失败: %s: %s" % (type(e).__name__, e))
        return

    _DEFAULTS = {"top_k": 5, "max_per_doc": 2,
                 "max_context_chunks": 5, "filter_overfetch": 6}
    _YAML_KEY = {"top_k": "qa_top_k", "max_per_doc": "qa_max_per_doc",
                 "max_context_chunks": "qa_max_context_chunks",
                 "filter_overfetch": "filter_overfetch"}
    _mod, _ = load_port_loader()
    try:
        _cc = _mod.knowledge_chunk_config() if _mod else {}
    except Exception:
        _cc = {}

    for k in _DEFAULTS:
        if k not in cfg:
            bad("装配结果缺 %s" % k)
            continue
        ok("装配结果含 %s=%s" % (k, cfg[k]))
        if not _cc:
            continue
        _want = _cc.get(_YAML_KEY[k], _DEFAULTS[k])
        if cfg[k] == _want:
            ok("  └ 与 gateway.yaml 一致（%s=%s）" % (_YAML_KEY[k], _want))
        else:
            bad("  └ %s=%s 但 gateway.yaml 里 %s=%s —— 装配没读到现场配置"
                % (k, cfg[k], _YAML_KEY[k], _want))

    llm = cfg.get("llm") or {}
    if llm.get("api_base") and llm.get("model_name"):
        ok("LLM 已接入: %s @ %s" % (llm["model_name"], llm["api_base"]))
        if "temperature" in llm:
            ok("qa_temperature 已下发: %s" % llm["temperature"])
        else:
            warn("llm 里没有 temperature —— 现场 openai_client.py 可能是旧版，"
                 "温度不会生效（不影响检索与入库）")
        if "enable_thinking" in llm:
            print("     enable_thinking=%r（None 表示不下发该字段）" % (llm["enable_thinking"],))
    else:
        warn("未接入 LLM（config/dfecrab.json 里没有 enabled 且 api_base 非空的 provider）"
             " —— chat 会走本地拼接回答，属正常降级")


# ─────────────────────────── D. 在线：问答与带图同一条链路 ───────────────────────────
def _post(url, payload, timeout=120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def check_live(cc):
    print("\n【D】在线：问答链路（同事的 qa_*）与带图字段（我方批次19）同一条路")
    mod, _ = load_port_loader()
    try:
        port = mod.knowledge_api_port()
    except Exception:
        port = 6788
    base = "http://127.0.0.1:%d/knowledge" % port

    # 先看服务在不在
    try:
        with urllib.request.urlopen(base + "/health", timeout=5) as r:
            json.loads(r.read().decode("utf-8"))
    except Exception as e:
        warn("知识库服务未响应（%s）—— 跳过在线检查。" % e)
        print("     启动后再跑： cd %s && ./dfecrab start-knowledge" % ROOT)
        return

    # 取一篇文档的标题当问句（比瞎编一个问题更容易命中）
    question = None
    try:
        with urllib.request.urlopen(base + "/documents", timeout=20) as r:
            docs = (json.loads(r.read().decode("utf-8")) or {}).get("documents", []) or []
        if docs:
            question = (docs[0].get("title") or "").strip() or None
    except Exception as e:
        warn("列文档失败: %s" % e)

    if not question:
        warn("库里还没有文档，跳过在线问答（先上传一份再跑本脚本）")
        return

    # D1 问答：top_k 生效（应 ≤ 传入值）
    want_k = int((cc or {}).get("qa_top_k", 5) or 5)
    try:
        st, res = _post(base + "/chat", {"question": question, "top_k": want_k})
        n = len(res.get("sources", []) or [])
        if st == 200 and res.get("status") == "success":
            ok("POST /chat 200，召回 %d 条（请求 top_k=%d）" % (n, want_k))
            if n <= want_k:
                ok("召回收敛在 top_k 之内 —— 超采/截断逻辑正常")
            else:
                bad("召回 %d 条 > top_k=%d，超采后没截断回 top_k" % (n, want_k))
            if res.get("answer"):
                ok("回答非空（%d 字）" % len(res["answer"]))
            else:
                warn("回答为空 —— 若未接 LLM 属正常降级，检查 config/dfecrab.json")
        else:
            bad("POST /chat 返回异常: HTTP %s status=%s msg=%s"
                % (st, res.get("status"), res.get("message")))
    except Exception as e:
        bad("POST /chat 失败: %s: %s" % (type(e).__name__, e))

    # D2 检索：results[] 必须仍有 images 键（我方的带图契约）
    try:
        st, res = _post(base + "/search", {"query": question, "top_k": want_k})
        rows = res.get("results", []) or []
        if st == 200 and res.get("status") == "success":
            ok("POST /search 200，命中 %d 条" % len(rows))
            if rows and all("images" in r for r in rows):
                ok("results[] 每条都有 images 字段（批次19 契约未丢）")
            elif rows:
                bad("results[] 缺 images 字段 —— 批次19 的契约被覆盖了")
            n_img = sum(len(r.get("images") or []) for r in rows)
            if n_img:
                ok("命中结果带出图片 %d 张 —— **问答与邻近带图在同一条链路上并存**" % n_img)
            else:
                warn("本次命中没有带出图片（库里可能还没有图片切片，或命中的片附近没图）"
                     "。上传一份含图 docx 后再跑本脚本即可看到。")
        else:
            bad("POST /search 返回异常: HTTP %s status=%s msg=%s"
                % (st, res.get("status"), res.get("message")))
    except Exception as e:
        bad("POST /search 失败: %s: %s" % (type(e).__name__, e))


def main():
    ap = argparse.ArgumentParser(description="知识库 r4 合并验收（问答参数 + 入库带图 并存）")
    ap.add_argument("--offline", action="store_true", help="不连知识库服务，只查代码与配置")
    args = ap.parse_args()

    print("=" * 66)
    print(" 知识库 r4 合并验收：两边功能是否并存")
    print(" 项目根: %s" % ROOT)
    print("=" * 66)

    check_source_coexist()
    cc, _ = check_config()
    check_skill_config()
    if args.offline:
        print("\n【D】在线检查：已按 --offline 跳过")
    else:
        check_live(cc)

    print("\n" + "=" * 66)
    print("PASS=%d FAIL=%d WARN=%d" % (N_PASS, N_FAIL, N_WARN))
    if N_FAIL:
        print("❌ 有 %d 项未通过 —— 说明有一边的改动被覆盖了（或被改成了别的版本）。" % N_FAIL)
        print("   回滚（把 <包目录> 换成实际解压路径）：")
        print("     bash /home/e8900/update/dfecrab-kb-full-20260911-r4/uninstall.sh %s" % ROOT)
        return 1
    print("✅ 全部通过：问答参数（同事那批）与图片入库/带图（我方批次19/20）**并存**。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
