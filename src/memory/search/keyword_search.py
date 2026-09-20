"""
记忆关键词检索引擎（BM25 / 倒排）

检索三类记忆语料（按用户隔离）：
1. 用户级记忆  data/memory/users/{user_id}/memories.json
2. Agent 经验  data/memory/users/{user_id}/agents/{agent_id}/memory.json
3. 每日日志    data/memory/users/{user_id}/global/DAILY/*.md

纯标准库实现（无第三方依赖）：中文用 bigram 分词 + BM25 打分。
"""

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
USERS_BASE = PROJECT_ROOT / "data" / "memory" / "users"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> List[str]:
    """中文 bigram + 英文/数字单词分词"""
    text = (text or "").lower()
    tokens: List[str] = []
    for w in _WORD_RE.findall(text):
        tokens.append(w)
    for block in _CJK_RE.findall(text):
        if len(block) == 1:
            tokens.append(block)
        else:
            for i in range(len(block) - 1):
                tokens.append(block[i:i + 2])
    return tokens


def _load_user_memories(user_id: str) -> List[Dict]:
    """加载用户级记忆"""
    f = USERS_BASE / (user_id or "default") / "memories.json"
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"读取用户记忆失败 {f}: {e}")
        return []
    docs = []
    for m in data.get("memories", []):
        text = f"{m.get('key', '')} {m.get('content', '')}".strip()
        if text:
            docs.append({
                "source": "user_memory",
                "doc_id": m.get("id", ""),
                "title": m.get("key", ""),
                "content": text,
                "tokens": tokenize(text),
            })
    return docs


def _load_agent_memories(user_id: str) -> List[Dict]:
    """加载该用户所有 Agent 的经验记忆"""
    docs: List[Dict] = []
    agents_dir = USERS_BASE / (user_id or "default") / "agents"
    if not agents_dir.exists():
        return docs
    for ad in agents_dir.iterdir():
        if not ad.is_dir():
            continue
        agent_id = ad.name
        mf = ad / "memory.json"
        if not mf.exists():
            continue
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        lt = data.get("long_term", {}) or {}
        for cat in ("patterns", "lessons", "facts"):
            for e in lt.get(cat, []):
                content = e.get("content", "") if isinstance(e, dict) else str(e)
                if content:
                    docs.append({
                        "source": "agent_memory",
                        "doc_id": f"{agent_id}:{cat}",
                        "title": f"[{agent_id}/{cat}]",
                        "content": content,
                        "tokens": tokenize(content),
                    })
    return docs


def _load_daily(user_id: str, days: int = 30) -> List[Dict]:
    """加载该用户近 N 天的每日日志"""
    docs: List[Dict] = []
    daily_dir = USERS_BASE / (user_id or "default") / "global" / "DAILY"
    if not daily_dir.exists():
        return docs
    files = sorted(daily_dir.glob("*.md"), reverse=True)[:days]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if text.strip():
            docs.append({
                "source": "daily",
                "doc_id": f.stem,
                "title": f.stem,
                "content": text,
                "tokens": tokenize(text),
            })
    return docs


def _bm25(query_tokens: List[str], docs: List[Dict],
          k1: float = 1.5, b: float = 0.75) -> List[Dict]:
    """BM25 打分，返回带 score 的文档（按分数降序）"""
    n = len(docs)
    if n == 0 or not query_tokens:
        return []
    avgdl = sum(len(d["tokens"]) for d in docs) / n
    df = Counter()
    for d in docs:
        for t in set(d["tokens"]):
            df[t] += 1
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in set(query_tokens)}

    scored: List[Dict] = []
    for d in docs:
        dl = len(d["tokens"])
        tf = Counter(d["tokens"])
        score = 0.0
        for t in set(query_tokens):
            f = tf.get(t, 0)
            if f == 0:
                continue
            score += idf.get(t, 0) * f * (k1 + 1) / (f + k1 * (1 - b + b * dl / avgdl))
        if score > 0:
            item = dict(d)
            item["score"] = round(score, 4)
            scored.append(item)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


class MemorySearchEngine:
    """记忆检索引擎（BM25，按用户隔离）"""

    def index_memory(self, memory_entry) -> None:
        """兼容入口：BM25 每次 search 时从磁盘全量加载，无需增量索引（no-op）"""
        logger.debug(f"[Memory] index_memory 收到条目（BM25 免增量索引，忽略）: {getattr(memory_entry, 'id', '')}")

    def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        scope: str = "all",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """检索记忆

        Args:
            query: 查询文本
            user_id: 用户 ID（按用户隔离）
            scope: all | user_memory | agent_memory | daily
            limit: 返回条数

        Returns:
            [{score, source, doc_id, title, content}]
        """
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        docs: List[Dict] = []
        if scope in ("all", "user_memory"):
            docs += _load_user_memories(user_id)
        if scope in ("all", "agent_memory"):
            docs += _load_agent_memories(user_id)
        if scope in ("all", "daily"):
            docs += _load_daily(user_id)

        results = _bm25(query_tokens, docs)
        return [
            {
                "score": r["score"],
                "source": r["source"],
                "doc_id": r["doc_id"],
                "title": r["title"],
                "content": r["content"][:300],
            }
            for r in results[:limit]
        ]
