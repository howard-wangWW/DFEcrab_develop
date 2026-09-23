"""
昆明配网理论题本地问答检索技能。

支持：
1. 直接按“第X题”命中
2. 按问题文本做本地语义近似检索

注意：data/shared_memory/knowledge 知识库已移除（与新知识库系统冲突），
本技能依赖的 kunming_theory_qa.json 已备份到 data/backup/knowledge_removed_*，
数据文件缺失时 execute 会返回友好错误提示；如需继续使用请接入新知识库系统。
"""

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = PROJECT_ROOT / "data" / "shared_memory" / "knowledge" / "kunming_theory_qa.json"
QUESTION_ID_RE = re.compile(r"(?:第\s*)(\d{1,2})\s*题")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[A-Za-z0-9_]+")

SKILL_METADATA = {
    "name": "kunming_theory_qa",
    "description": "检索昆明配网理论题本地问答库，适用于理论题、简答题、操作票、调度纪律等知识问答",
    "parameters": {
        "query": {
            "type": "string",
            "description": "用户原始问题，支持自然语言或第X题",
        },
        "top_k": {
            "type": "integer",
            "description": "返回候选数量，默认3",
            "default": 3,
        },
        "min_score": {
            "type": "number",
            "description": "最低相似度阈值，默认0.2",
            "default": 0.2,
        },
    },
}


def _load_items() -> List[Dict]:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _extract_question_id(text: str) -> Optional[int]:
    match = QUESTION_ID_RE.search(text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "", text)
    return re.sub(r"[，。！？；：、“”‘’（）()《》【】\[\],.!?;:]", "", text)


def _tokenize(text: str) -> List[str]:
    normalized = _normalize(text)
    tokens: List[str] = []

    for word in WORD_RE.findall(normalized):
        if word:
            tokens.append(word)

    for block in CHINESE_RE.findall(normalized):
        if not block:
            continue
        if len(block) == 1:
            tokens.append(block)
            continue
        for size in (2, 3):
            if len(block) >= size:
                for i in range(len(block) - size + 1):
                    tokens.append(block[i : i + size])

    return tokens


def _cosine_similarity(a_tokens: List[str], b_tokens: List[str]) -> float:
    if not a_tokens or not b_tokens:
        return 0.0

    a_counter = Counter(a_tokens)
    b_counter = Counter(b_tokens)

    dot = sum(a_counter[token] * b_counter.get(token, 0) for token in a_counter)
    norm_a = math.sqrt(sum(value * value for value in a_counter.values()))
    norm_b = math.sqrt(sum(value * value for value in b_counter.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _score_query(query: str, question: str) -> float:
    normalized_query = _normalize(query)
    normalized_question = _normalize(question)
    base_score = _cosine_similarity(_tokenize(query), _tokenize(question))

    # 轻量加权：子串命中时给额外加分，提升短问法的命中率。
    bonus = 0.0
    if normalized_query and normalized_query in normalized_question:
        bonus += 0.35
    elif normalized_question and normalized_question in normalized_query:
        bonus += 0.2

    return min(base_score + bonus, 1.0)


def execute(query: str = "", top_k: int = 3, min_score: float = 0.2, **kwargs):
    items = _load_items()
    if not items:
        return {"status": "error", "message": f"理论题数据文件不存在或为空: {DATA_FILE}"}

    query = (query or "").strip()
    if not query:
        return {"status": "error", "message": "query 不能为空"}

    question_id = _extract_question_id(query)
    if question_id is not None:
        for item in items:
            if int(item.get("id", 0)) == question_id:
                return {
                    "status": "success",
                    "matched_by": "question_id",
                    "hit": {
                        "id": item["id"],
                        "question": item["question"],
                        "answer": item["answer"],
                        "score": 1.0,
                    },
                    "candidates": [
                        {
                            "id": item["id"],
                            "question": item["question"],
                            "score": 1.0,
                        }
                    ],
                }

    scored: List[Tuple[float, Dict]] = []
    for item in items:
        score = _score_query(query, item.get("question", ""))
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top_k = max(1, int(top_k or 1))
    top_hits = scored[:top_k]
    best_score, best_item = top_hits[0]

    candidates = [
        {
            "id": item["id"],
            "question": item["question"],
            "score": round(score, 4),
        }
        for score, item in top_hits
    ]

    if best_score < float(min_score):
        answer = "未在理论题库中找到足够接近的问题，请换个问法，或直接说“第几题”。"
        return {
            "status": "success",
            "matched_by": "semantic",
            "low_confidence": True,
            "message": answer,
            "hit": {
                "id": best_item["id"],
                "question": best_item["question"],
                "answer": answer,
                "score": round(best_score, 4),
            },
            "candidates": candidates,
        }

    return {
        "status": "success",
        "matched_by": "semantic",
        "low_confidence": False,
        "hit": {
            "id": best_item["id"],
            "question": best_item["question"],
            "answer": best_item["answer"],
            "score": round(best_score, 4),
        },
        "candidates": candidates,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=0.2)
    args = parser.parse_args()
    result = execute(query=args.query, top_k=args.top_k, min_score=args.min_score)
    print(json.dumps(result, ensure_ascii=False, default=str))
