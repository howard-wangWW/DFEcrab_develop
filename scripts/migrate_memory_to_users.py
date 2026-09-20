"""
记忆数据迁移脚本：从旧路径迁移到按用户隔离路径

配合 Phase 3 用户维度改造，将旧数据迁移到新目录结构：

1. Agent 私有记忆 agents/{agent_id}/memory.json
   → data/memory/users/{user_id}/agents/{agent_id}/memory.json

2. 全局每日日志 data/shared_memory/DAILY/{date}.md
   → data/memory/users/{user_id}/global/DAILY/{date}.md

归属规则：
- 优先通过 data/sessions/*.json 的 user_id + agent_id 统计各 (用户, Agent) 交互量；
- Agent 记忆归属到交互量最高的用户；无任何交互记录时归 admin；
- DAILY 日志按条目内 "用户: xxx" 拆分到各用户目录，无用户标记的条目归 admin；
- 迁移前自动备份旧文件到 data/backup/memory_migrate_<时间戳>/。

用法：
    python scripts/migrate_memory_to_users.py            # 执行迁移
    python scripts/migrate_memory_to_users.py --dry-run  # 仅预览，不写任何文件
    python scripts/migrate_memory_to_users.py --user admin  # 强制所有记忆归属 admin
"""

import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = PROJECT_ROOT / "data" / "sessions"
DAILY_DIR = PROJECT_ROOT / "data" / "shared_memory" / "DAILY"
AGENTS_DIR = PROJECT_ROOT / "agents"
USERS_BASE = PROJECT_ROOT / "data" / "memory" / "users"
BACKUP_BASE = PROJECT_ROOT / "data" / "backup"

DEFAULT_OWNER = "admin"
_MEMORY_CATEGORIES = ("facts", "patterns", "lessons")


def _normalize_agent(agent_id: str) -> str:
    """归一化 agent_id（与 src.agent.agent_config.normalize_agent_id 保持一致）"""
    agent_id = (agent_id or "").strip()
    if agent_id in ("default", "auto", ""):
        return "dfecrab"
    return agent_id


def collect_user_agent_stats() -> dict:
    """从 data/sessions/*.json 统计 {agent_id: {user_id: count}}"""
    stats = defaultdict(lambda: defaultdict(int))
    if not SESSIONS_DIR.exists():
        return stats
    for f in SESSIONS_DIR.glob("*.json"):
        if f.name.endswith("_messages.json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            user = data.get("user_id") or "default"
            agent = _normalize_agent(data.get("agent_id") or "")
            stats[agent][user] += 1
        except Exception:
            continue
    return stats


def collect_daily_user_stats() -> dict:
    """兜底统计：从 DAILY 日志统计 {user_id: count}"""
    stats = defaultdict(int)
    if not DAILY_DIR.exists():
        return stats
    for f in DAILY_DIR.glob("*.md"):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"^用户:\s*(\S+)", text, re.M):
            stats[m.group(1)] += 1
    return stats


def resolve_agent_owner(agent_id: str, stats: dict, daily_stats: dict,
                        force_user: str = None) -> str:
    """确定 Agent 记忆的归属用户"""
    if force_user:
        return force_user
    candidates = stats.get(agent_id, {})
    if candidates:
        return max(candidates, key=candidates.get)
    if daily_stats:
        return max(daily_stats, key=daily_stats.get)
    return DEFAULT_OWNER


def parse_daily_entries(text: str) -> list:
    """解析 DAILY md 文件为条目列表 [{content, user}]"""
    entries = []
    # 文件结构：'# {date} 对话日志' + 若干条目（**[ts**] [category] ... ---）
    blocks = re.split(r"\n---\s*\n", text)
    for block in blocks:
        block = block.strip()
        if not block or block.startswith("# "):
            continue
        m = re.search(r"用户:\s*(\S+)", block)
        user = m.group(1) if m else DEFAULT_OWNER
        entries.append({"content": block, "user": user})
    return entries


def _normalize_long_term(data: dict) -> dict:
    """把任意 memory.json 结构归一化为 V3.0 格式 {long_term: {facts, patterns, lessons}}"""
    lt = data.get("long_term", {}) or data.get("long_term_memory", {}) or data.get("experience", {}) or {}
    return {
        "facts": list(lt.get("facts", []) or []),
        "patterns": list(lt.get("patterns", []) or lt.get("successful_patterns", [])),
        "lessons": list(lt.get("lessons", []) or lt.get("lessons_learned", [])),
    }


def _merge_long_term(base: dict, extra: dict) -> dict:
    """合并两份 long_term（按 content 去重）"""
    merged = {cat: list(base.get(cat, [])) for cat in _MEMORY_CATEGORIES}
    for cat in _MEMORY_CATEGORIES:
        seen = {e.get("content") for e in merged[cat] if isinstance(e, dict)}
        for e in extra.get(cat, []):
            if not isinstance(e, dict):
                e = {"content": str(e)}
            if e.get("content") not in seen:
                merged[cat].append(e)
                seen.add(e.get("content"))
    return merged


def migrate_agent_memories(stats: dict, daily_stats: dict, dry_run: bool = False,
                           force_user: str = None) -> dict:
    """迁移 agents/{agent_id}/memory.json 到用户目录"""
    report = {"agents": [], "by_owner": defaultdict(int), "skipped": []}
    if not AGENTS_DIR.exists():
        return report
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_id = agent_dir.name
        src = agent_dir / "memory.json"
        if not src.exists():
            continue

        owner = resolve_agent_owner(agent_id, stats, daily_stats, force_user)
        target = USERS_BASE / owner / "agents" / agent_id / "memory.json"
        report["by_owner"][owner] += 1
        report["agents"].append({"agent_id": agent_id, "owner": owner, "target": str(target)})

        if dry_run:
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            normalized = _normalize_long_term(data)
            target.parent.mkdir(parents=True, exist_ok=True)

            final = {
                "version": "3.0",
                "agent_id": agent_id,
                "created_at": data.get("created_at") or datetime.now().isoformat(),
                "last_updated": data.get("last_updated") or datetime.now().isoformat(),
                "short_term": {"session_context": [], "max_turns": 20, "last_session": None},
                "long_term": normalized,
                "context": {},
            }
            if target.exists():
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                    existing_lt = _normalize_long_term(existing)
                    merged_lt = _merge_long_term(existing_lt, normalized)
                    final["long_term"] = merged_lt
                except Exception:
                    pass  # 目标文件损坏时以源为准
            target.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            report["skipped"].append({"agent_id": agent_id, "error": str(e)})
    return report


def migrate_daily(dry_run: bool = False, force_user: str = None) -> dict:
    """按用户拆分 data/shared_memory/DAILY/*.md 到用户目录"""
    report = {"files_parsed": 0, "entries": 0, "by_user": defaultdict(int), "skipped": []}
    if not DAILY_DIR.exists():
        return report
    for f in sorted(DAILY_DIR.glob("*.md")):
        date = f.stem
        try:
            entries = parse_daily_entries(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            report["skipped"].append({"file": f.name, "error": str(e)})
            continue
        report["files_parsed"] += 1
        report["entries"] += len(entries)

        per_user = defaultdict(list)
        for e in entries:
            user = force_user or e["user"]
            per_user[user].append(e["content"])

        for user, contents in per_user.items():
            report["by_user"][user] += len(contents)
            if dry_run:
                continue
            target_dir = USERS_BASE / user / "global" / "DAILY"
            target_file = target_dir / f"{date}.md"
            target_dir.mkdir(parents=True, exist_ok=True)
            header = f"# {date} 对话日志\n"
            body = "\n\n".join(contents)
            if target_file.exists():
                existing = target_file.read_text(encoding="utf-8")
                if body.strip() and body.strip() in existing:
                    continue  # 已迁移过，跳过避免重复追加
                body = existing.rstrip() + "\n\n" + body
            target_file.write_text(header + "\n" + body + "\n", encoding="utf-8")
    return report


def backup() -> tuple:
    """备份旧数据到 data/backup/memory_migrate_<时间戳>/"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUP_BASE / f"memory_migrate_{ts}"
    n = 0
    if DAILY_DIR.exists():
        d = backup_dir / "daily"
        d.mkdir(parents=True, exist_ok=True)
        for f in DAILY_DIR.glob("*.md"):
            shutil.copy2(f, d / f.name)
            n += 1
    if AGENTS_DIR.exists():
        for ad in AGENTS_DIR.iterdir():
            if ad.is_dir():
                src = ad / "memory.json"
                if src.exists():
                    t = backup_dir / "agents" / ad.name / "memory.json"
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, t)
                    n += 1
    return backup_dir, n


def main() -> None:
    parser = argparse.ArgumentParser(description="记忆数据迁移（旧路径 → 按用户隔离路径）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写任何文件")
    parser.add_argument("--user", default=None, help="强制所有记忆归属到指定用户")
    args = parser.parse_args()

    print("=" * 70)
    print("记忆数据迁移")
    print("=" * 70)
    print(f"dry-run: {args.dry_run}   force-user: {args.user or '(自动归属)'}")
    print(f"项目根: {PROJECT_ROOT}")

    stats = collect_user_agent_stats()
    daily_stats = collect_daily_user_stats()
    total_sessions = sum(v for u in stats.values() for v in u.values())
    print(f"\n[1/3] 会话统计: {total_sessions} 条")
    print(f"      按 Agent 的用户分布: "
          f"{ {k: dict(v) for k, v in stats.items()} }")
    print(f"      DAILY 用户分布: {dict(daily_stats)}")

    if args.dry_run:
        print("[2/3] dry-run 模式，跳过备份")
    else:
        backup_dir, n_backup = backup()
        print(f"[2/3] 已备份 {n_backup} 个文件 -> {backup_dir}")

    agent_report = migrate_agent_memories(stats, daily_stats, args.dry_run, args.user)
    daily_report = migrate_daily(args.dry_run, args.user)

    print(f"\n[3/3] 迁移结果")
    print("  Agent 私有记忆:")
    for a in agent_report["agents"]:
        print(f"    - {a['agent_id']} -> 归属 {a['owner']} -> {a['target']}")
    for s in agent_report["skipped"]:
        print(f"    ✗ {s['agent_id']} 失败: {s['error']}")
    print(f"  每日日志: 解析 {daily_report['files_parsed']} 个文件 / {daily_report['entries']} 条记录")
    for user, cnt in sorted(daily_report["by_user"].items()):
        print(f"    - {user}: {cnt} 条")
    for s in daily_report["skipped"]:
        print(f"    ✗ {s['file']} 失败: {s['error']}")

    if args.dry_run:
        print("\n(dry-run 完成，未写任何文件)")
    else:
        print("\n迁移完成。旧数据仍保留在原位置，确认无误后可手动删除 "
              "agents/*/memory.json 与 data/shared_memory/DAILY。")


if __name__ == "__main__":
    main()
