#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_delivery.py —— 挑出「可直接交付」的文件并打包（不做任何内容处理）

只做三件事：
    1. 扫描仓库，判定每个文件能不能直接交付
    2. 能直接交付的 → **原样**复制到暂存目录（逐字节，不改一个字符）
    3. 打成 zip，附文件清单与 SHA256

故意不做的事：
    - 不做任何脱敏 / 替换 / 改写。需要脱敏的文件本轮**直接跳过**，只登记清单
    - 不改动源仓库任何文件（全程只读）

判定口径（复用 scripts/review_scope_audit.py 的规则，避免两套规则漂移）：
    直接交付 ALLOW   → 进包
    需脱敏   MASK    → 本轮跳过，写进「待脱敏清单.txt」
    排除     BLOCK   → 甲方数据本体，不进包
    排除     SKIP    → 生成物 / 部署环境 / 与审核无关，不进包

用法
    python3 scripts/make_delivery.py
    python3 scripts/make_delivery.py --out dist/pkg.zip --keep-stage

退出码
    0 = 正常出包    2 = 入参问题
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# 复用判定脚本的规则，单一定义源（不再维护第二套规则）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_scope_audit import audit, load_rules  # noqa: E402

DEFAULT_STAGE = ".delivery_stage"


# ============================================================================
# 工具
# ============================================================================

def die(msg: str, code: int = 2) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(code)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_reasons(reasons: list[str]) -> list[str]:
    """去掉级别后缀并去重，便于阅读。"""
    out: list[str] = []
    for r in reasons:
        text = r.split(" [")[0].strip()
        if text and text not in out:
            out.append(text)
    return out


# ============================================================================
# 主体
# ============================================================================

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(
        description="挑出可直接交付的文件并原样打包（不脱敏、不改源仓库）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--root", default=None, help="仓库根（默认脚本上一级）")
    parser.add_argument("--out", default=None, help="输出 zip（默认 dist/DFEcrab_delivery_<时间>.zip）")
    parser.add_argument("--stage", default=DEFAULT_STAGE, help=f"暂存目录（默认 {DEFAULT_STAGE}）")
    parser.add_argument("--keep-stage", action="store_true", help="保留暂存目录（默认打包后删除）")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not root.is_dir():
        die(f"仓库根不存在: {root}")

    out_zip = Path(args.out) if args.out else (
        Path("dist") / f"DFEcrab_delivery_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    )
    stage = Path(args.stage).resolve()

    # 暂存目录与输出目录都要排除在扫描之外（避免把上一次的产物扫进来）
    exclude_rels: set[str] = set()
    for p in (stage, out_zip.parent):
        try:
            rel = Path(p).resolve().relative_to(root).as_posix()
            if rel != ".":
                exclude_rels.add(rel)
        except (ValueError, OSError):
            pass

    print("=" * 74)
    print("DFEcrab 直接交付包构建")
    print(f"仓库根   : {root}")
    print(f"输出      : {out_zip}")
    print("=" * 74)

    rules = load_rules(None)
    result = audit(root, rules, exclude_rels=exclude_rels)

    deliver = [f for f in result["files"] if f["level"] == "ALLOW"]
    masked = [f for f in result["files"] if f["level"] == "MASK"]
    blocked = [f for f in result["files"] if f["level"] == "BLOCK"]
    skipped = [f for f in result["files"] if f["level"] == "SKIP"]
    blocked_dirs = [d for d in result["dir_hits"] if d["level"] == "BLOCK"]
    skipped_dirs = [d for d in result["dir_hits"] if d["level"] == "SKIP"]

    print(f"\n扫描完成：共 {len(result['files'])} 个文件")
    print(f"  可直接交付 : {len(deliver)}")
    print(f"  需脱敏跳过 : {len(masked)}")
    print(f"  排除(甲方数据) : {len(blocked)} 个文件 + {len(blocked_dirs)} 个整目录")
    print(f"  排除(非源码)   : {len(skipped)} 个文件 + {len(skipped_dirs)} 个整目录")

    # ---- 复制：原样，逐字节 ----
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    for entry in deliver:
        src = root / entry["path"]
        if not src.is_file():
            die(f"源文件不存在: {src}")
        dst = stage / entry["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        total_bytes += dst.stat().st_size

    print(f"\n[1/3] 已原样复制 {len(deliver)} 个文件（{total_bytes / 1024 / 1024:.2f} MB），未做任何内容改动")

    # ---- 交付物：清单 + 说明 ----
    manifest_lines = [
        f"# 交付文件清单  共 {len(deliver)} 个（生成于 {datetime.now():%Y-%m-%d %H:%M:%S}）",
        "# 格式: SHA256<TAB>大小<TAB>路径",
    ]
    for entry in sorted(deliver, key=lambda e: e["path"]):
        p = stage / entry["path"]
        manifest_lines.append(f"{sha256_of(p)}\t{p.stat().st_size}\t{entry['path']}")
    (stage / "MANIFEST.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    readme = f"""DFEcrab 代码交付包
生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}
来源仓库：{root}

【本包内容】
仅包含「可直接交付」的文件，共 {len(deliver)} 个，合计 {total_bytes / 1024 / 1024:.2f} MB。
所有文件均为**原样复制**，未做任何脱敏、替换或改写。

【本包不含（本轮未提供）】
1. 需脱敏文件（{len(masked)} 个）：含内网地址、凭据、甲方表名等，需脱敏后才能提供，本轮未做。
2. 甲方数据本体（{len(blocked)} 个文件 + {len(blocked_dirs)} 个目录）：知识库语料、电网拓扑 XML、
   数据库表结构缓存、运行时数据与日志、本地模型权重等。
3. 非源码内容（{len(skipped)} 个文件 + {len(skipped_dirs)} 个目录）：虚拟环境、离线依赖包、
   运行时、字节码缓存、版本控制历史、与本次无关的子项目等。

详见包外随附的：
  - 待脱敏清单.txt    （需先脱敏，本轮未提供）
  - 排除清单.txt      （甲方数据 / 非源码）
  - 交付说明.txt      （范围声明，可作合同附件）

【完整性校验】
MANIFEST.txt 列出每个文件的 SHA256 与大小，可用于校验传输完整性。
"""
    (stage / "README.txt").write_text(readme, encoding="utf-8")

    # ---- 随包外文档：待脱敏清单 / 排除清单 / 范围说明 ----
    out_dir = out_zip.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump_list(filename: str, entries: list[dict], title: str, note: str) -> None:
        lines = [f"# {title}  共 {len(entries)} 个", f"# {note}", "# 格式: 路径<TAB>原因"]
        for e in sorted(entries, key=lambda x: x["path"]):
            lines.append(f"{e['path']}\t{'；'.join(clean_reasons(e['reasons']))}")
        (out_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")

    dump_list("待脱敏清单.txt", masked, "待脱敏文件",
              "含敏感值，需脱敏后才能交付；本轮未提供")
    dump_list("排除清单.txt", blocked + skipped, "排除文件",
              "甲方数据本体 / 生成物 / 部署环境，不交付")

    scope = [
        "# 本次交付范围声明",
        "",
        f"交付时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "## 一、本次交付的内容",
        "",
        f"- 「可直接交付」文件 {len(deliver)} 个（原样复制，未做任何内容改动）",
        "",
        "## 二、本次未交付的内容",
        "",
        "### 2.1 需脱敏文件",
        "",
        f"- 数量：{len(masked)} 个",
        "- 原因：内容含内网地址、凭据、甲方库表名等，需脱敏后才能提供，本轮未做",
        "- 明细：见同目录「待脱敏清单.txt」",
        "",
        "### 2.2 甲方数据本体",
        "",
        f"- 数量：{len(blocked)} 个文件 + {len(blocked_dirs)} 个整目录",
        "- 原因：内容是数据本身（语料 / 拓扑 / 表结构 / 运行数据），脱敏无意义；处置权属甲方",
        "",
        "### 2.3 非源码内容",
        "",
        f"- 数量：{len(skipped)} 个文件 + {len(skipped_dirs)} 个整目录",
        "- 原因：部署环境、生成物、字节码、版本历史、与本次无关的子项目",
        "",
        "## 三、完整性",
        "",
        "包内 `MANIFEST.txt` 提供每个文件的 SHA256，可校验传输完整性。",
        "",
    ]
    (out_dir / "交付说明.txt").write_text("\n".join(scope), encoding="utf-8")

    print("[2/3] 已生成 MANIFEST.txt / README.txt，并在输出目录生成：")
    print("        待脱敏清单.txt / 排除清单.txt / 交付说明.txt")

    # ---- 打包 ----
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(stage).as_posix())

    digest = sha256_of(out_zip)
    (out_dir / (out_zip.name + ".sha256")).write_text(f"{digest}  {out_zip.name}\n", encoding="utf-8")
    print(f"[3/3] 已出包：{out_zip}（{out_zip.stat().st_size / 1024 / 1024:.2f} MB）")
    print(f"      SHA256: {digest}")

    if not args.keep_stage:
        try:
            shutil.rmtree(stage)
            print(f"      暂存目录已清理：{stage}")
        except OSError as e:
            # 包已经出好了，清理失败不该影响交付，但必须明确告警而不是静默略过
            print(f"      [WARN] 暂存目录清理失败（包已正常生成，可手动删除）: {e}")
            print(f"             手动删除: rm -rf {stage}")
    else:
        print(f"      暂存目录保留：{stage}")

    print("\n[OK] 完成。源仓库未做任何改动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
