#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据回填脚本：给缺失 model_config 的 Agent 配置补上默认模型。

背景：老版本创建 Agent 时没有把 model_config 写入 config.json，
导致 GET /api/agents 列表里 model_config / model_name 为空，前端显示「无模型」。

本脚本遍历 agents/<agent_id>/config.json，若字段缺失则补上 DEFAULT_MODEL，
已存在则跳过（不会覆盖已有配置）。

用法：
    python scripts/backfill_agent_model.py
    python scripts/backfill_agent_model.py --model qwen3_32b_q4 --agents-dir /path/to/agents
"""

import argparse
import glob
import json
import os
import sys

# 默认模型：与 GET /api/models 的 current_provider 保持一致
DEFAULT_MODEL = "qwen3_32b_q4"


def resolve_agents_dir(explicit=None):
    if explicit:
        return explicit
    # 脚本位于 <project>/scripts/backfill_agent_model.py
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(os.path.dirname(here), "agents")
    if os.path.isdir(candidate):
        return candidate
    # 兜底：当前工作目录下的 agents
    cwd_candidate = os.path.join(os.getcwd(), "agents")
    if os.path.isdir(cwd_candidate):
        return cwd_candidate
    return None


def backfill(agents_dir, model):
    if not agents_dir or not os.path.isdir(agents_dir):
        print(f"[error] agents 目录不存在: {agents_dir}", file=sys.stderr)
        return 1

    total = 0
    updated = 0
    skipped = 0
    for cfg_path in sorted(glob.glob(os.path.join(agents_dir, "*", "config.json"))):
        total += 1
        agent_id = os.path.basename(os.path.dirname(cfg_path))
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"[warn] 跳过 {agent_id}: 读取失败 ({e})", file=sys.stderr)
            continue

        existing = cfg.get("model_config")
        if existing:
            print(f"[skip]    {agent_id:<18} 已有 model_config={existing}")
            skipped += 1
            continue

        cfg["model_config"] = model
        # 保持与源码一致的格式（2 空格缩进、保留中文/emoji、保持字段顺序）
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"[update]  {agent_id:<18} -> model_config={model}")
        updated += 1

    print(f"\n完成：共扫描 {total} 个 Agent，更新 {updated} 个，跳过 {skipped} 个。")
    return 0


def main():
    parser = argparse.ArgumentParser(description="回填 Agent 默认模型配置")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"默认模型名 (默认 {DEFAULT_MODEL})")
    parser.add_argument("--agents-dir", default=None, help="agents 目录路径 (默认自动探测)")
    args = parser.parse_args()

    agents_dir = resolve_agents_dir(args.agents_dir)
    print(f"agents 目录: {agents_dir}")
    print(f"回填模型:   {args.model}\n")
    return backfill(agents_dir, args.model)


if __name__ == "__main__":
    sys.exit(main())
