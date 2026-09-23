# src/knowledge/core/ranking.py
"""
检索候选放量与同文档限流（纯函数，便于单测）

faiss / jieba 版 HybridRetriever 的两个易错点被抽出来单独维护：

1. ``compute_fetch_k`` —— 大库里单篇大文档会霸占 top-N，若只取 top_k 条
   再做同文档限流，限流后结果会不足；故候选先放大到
   ``top_k × max_per_doc × overfetch``（各因子做下限保护）。

2. ``diversify_by_doc`` —— 按 ``metadata.doc_id`` 限流，同一文档最多
   ``max_per_doc`` 条；``<=0`` 表示不限流。

说明
------------------------------------------------------------------
本文件为合并时重建实现（原始源码在本地分支缺失，仅存 cpython-311 字节码缓存）。
契约对齐 HybridRetriever：``compute_fetch_k(top_k, max_per_doc, overfetch)`` 与
``diversify_by_doc(ranked, max_per_doc)``（可选 top_k 截断）。
"""
from __future__ import annotations

from typing import Dict, List, Optional


def compute_fetch_k(top_k: int, max_per_doc: int = 2, overfetch: int = 4) -> int:
    """候选放大倍数：top_k × max_per_doc × overfetch。

    Args:
        top_k: 目标返回条数（>=1）
        max_per_doc: 同文档最多保留条数（<=0 视为 1）
        overfetch: 候选放大倍数（>=1）

    Returns:
        放大后的候选条数（>= top_k）

    Raises:
        TypeError: top_k 不是整数
        ValueError: top_k <= 0
    """
    try:
        k = int(top_k)
    except (TypeError, ValueError):
        raise TypeError("top_k 必须是整数")
    if k <= 0:
        raise ValueError("top_k 必须 >= 1")

    try:
        m = int(max_per_doc)
    except (TypeError, ValueError):
        m = 1
    m = max(1, m)

    try:
        o = int(overfetch)
    except (TypeError, ValueError):
        o = 1
    o = max(1, o)

    return max(k, k * m * o)


def diversify_by_doc(ranked: List[Dict], max_per_doc: int = 2,
                     top_k: Optional[int] = None) -> List[Dict]:
    """按 doc_id 限流（保持原排序）。

    Args:
        ranked: 融合后的候选列表（元素需含 metadata.doc_id 或顶层 doc_id）
        max_per_doc: 同一文档最多保留条数；<=0 表示不限流
        top_k: 可选，限流后最多返回条数（None/<=0 表示不截断）

    Returns:
        限流后的候选列表
    """
    if not ranked:
        return []

    try:
        limit = int(max_per_doc)
    except (TypeError, ValueError):
        limit = 0

    if limit <= 0:
        out = list(ranked)
        return out[:top_k] if top_k and top_k > 0 else out

    result: List[Dict] = []
    doc_count: Dict[str, int] = {}
    for item in ranked:
        metadata = item.get("metadata") or {}
        doc_id = str(metadata.get("doc_id") or item.get("doc_id") or "")
        n = doc_count.get(doc_id, 0)
        if n >= limit:
            continue
        doc_count[doc_id] = n + 1
        result.append(item)
        if top_k and top_k > 0 and len(result) >= top_k:
            break
    return result
