# src/knowledge/core/keyword_index.py
"""
关键词倒排索引（大库检索提速）

背景
------------------------------------------------------------------
HybridRetriever._keyword_search 旧实现是"每次查询遍历全部切片":

    for idx, text in enumerate(self.texts):          # N = 切片数
        text_words = set(self.embedder._tokenize(text))   # 每次都重新分词！

每次查询都要对 N 个切片重新 jieba 分词，十万级切片时单次查询要几秒。
倒排索引把这部分成本从"每次查询 O(N)"变成"构建一次 O(N) + 每次查询 O(候选)"。

内存取舍
------------------------------------------------------------------
只存 token → array('i')（切片下标）的倒排表 + 每片词数：
  - 不存每片的词频表（tf 直接按 1 计，BM25 用 df + 文档长度归一即可）
  - 十万级切片、数百 MB 语料实测倒排表在 200MB 量级
  - 构建一次 10~20 秒（与旧实现单次查询成本相当），之后查询均为毫秒级

剪枝
------------------------------------------------------------------
高频词（df/N > max_df_ratio，如"的""是"）区分度低，构建时整词剪掉；
查询里的被剪枝词不参与打分（等价于 idf 近似下限）。

说明
------------------------------------------------------------------
本文件为合并时重建实现（原始源码在本地分支缺失，仅存 cpython-311 字节码缓存）。
对外契约完全对齐 HybridRetriever 的调用：ensure_built / search / stats / is_built
以及模块级 search_scan；行为与旧全扫实现（RRF 只用名次，不用绝对分）兼容。
"""
from __future__ import annotations

import array
import logging
import math
import re
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 纯符号/空白 token（无检索意义）直接丢弃
_MEANINGLESS_RE = re.compile(r"^[\W_]+$", re.UNICODE)


class KeywordIndex:
    """BM25 关键词倒排索引（构建一次，查询只扫候选）"""

    #: BM25 参数（与主流默认一致）
    _K1 = 1.5
    _B = 0.75

    def __init__(self,
                 tokenizer: Callable[[str], List[str]],
                 max_df_ratio: float = 0.5,
                 max_scan_postings: int = 200000):
        """
        Args:
            tokenizer: 分词函数（复用 embedder._tokenize，保证与向量链路同口径）
            max_df_ratio: 高频词剪枝阈值（df/N 超过则整词剪掉；<=0 表示不剪枝）
            max_scan_postings: 单次查询扫描倒排项上限（过热保护）
        """
        self._tokenizer = tokenizer
        self.max_df_ratio = float(max_df_ratio)
        self.max_scan_postings = int(max_scan_postings)
        self._postings: Dict[str, array.array] = {}
        self._doc_len: List[int] = []
        self.avg_len: float = 0.0
        self.total_postings: int = 0
        self.pruned_tokens: int = 0
        self.build_seconds: float = 0.0
        self._built = False
        self._lock = threading.Lock()

    def is_built(self) -> bool:
        """索引是否已构建"""
        return self._built

    def ensure_built(self, texts: List[str], progress_every: Optional[int] = None) -> bool:
        """确保索引已构建（惰性构建；失败返回 False，由调用方回落全扫）"""
        if self._built:
            return True
        if not texts:
            return False
        with self._lock:
            if self._built:
                return True
            try:
                self.build(texts, progress_every=progress_every)
                return self._built
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[KeywordIndex] 倒排索引构建失败，回落全扫: {e}")
                return False

    def build(self, texts: List[str], progress_every: Optional[int] = None) -> None:
        """构建倒排表（去重后存切片下标）"""
        t0 = time.time()
        postings: Dict[str, List[int]] = defaultdict(list)
        doc_len: List[int] = []

        for idx, text in enumerate(texts):
            toks = self._tokenizer(text or "")
            seen = set()
            for tok in toks:
                if not tok or _MEANINGLESS_RE.match(tok):
                    continue
                if tok in seen:
                    continue
                seen.add(tok)
                postings[tok].append(idx)
            doc_len.append(len(seen))
            if progress_every and (idx + 1) % progress_every == 0:
                logger.info(f"[KeywordIndex] 构建中 {idx + 1}/{len(texts)} ...")

        n = max(1, len(texts))
        max_df = max(1, int(n * self.max_df_ratio)) if self.max_df_ratio > 0 else 0

        final: Dict[str, array.array] = {}
        pruned = 0
        total = 0
        for tok, lst in postings.items():
            if max_df and len(lst) > max_df:
                pruned += 1
                continue
            final[tok] = array.array("i", lst)
            total += len(lst)

        self._postings = final
        self._doc_len = doc_len
        self.avg_len = (sum(doc_len) / n) if doc_len else 0.0
        self.total_postings = total
        self.pruned_tokens = pruned
        self.build_seconds = time.time() - t0
        self._built = True
        logger.info(f"[KeywordIndex] 构建完成: {len(final)} 词, 剪枝 {pruned} 个高频词, "
                    f"平均片长 {self.avg_len:.1f}, 耗时 {self.build_seconds:.1f}s")

    def search(self, query: str, top_k: int) -> List[Tuple[int, float]]:
        """BM25 检索，返回 [(切片下标, 分数)]（降序）"""
        if not self._built or not query:
            return []

        qtokens = set()
        for tok in self._tokenizer(query):
            if tok and not _MEANINGLESS_RE.match(tok):
                qtokens.add(tok)
        if not qtokens:
            return []

        n_docs = max(1, len(self._doc_len))
        avg = self.avg_len or 1.0
        scores: Dict[int, float] = {}
        scanned = 0

        for tok in qtokens:
            arr = self._postings.get(tok)
            if arr is None or len(arr) == 0:
                continue
            df = len(arr)
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            for idx in arr:
                dl = self._doc_len[idx] if 0 <= idx < len(self._doc_len) else 0
                norm = 1 - self._B + self._B * (float(dl) / avg if avg else 1.0)
                scores[idx] = scores.get(idx, 0.0) + (idf / norm if norm > 0 else idf)
            scanned += df
            if self.max_scan_postings and scanned > self.max_scan_postings:
                logger.debug(f"[KeywordIndex] 命中倒排项过热({scanned})，提前停止扫描")
                break

        if not scores:
            return []
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [(int(i), float(s)) for i, s in ranked[: max(1, int(top_k))]]

    def stats(self) -> Dict:
        """索引状态（便于大库排查"检索慢/召回少"）"""
        return {
            "built": self._built,
            "chunks": len(self._doc_len),
            "vocabulary": len(self._postings),
            "pruned_stopwords": self.pruned_tokens,
            "avg_chunk_tokens": round(self.avg_len, 2),
            "build_seconds": round(self.build_seconds, 2),
        }


def search_scan(texts: List[str], tokenizer: Callable[[str], List[str]],
                query: str, top_k: int) -> List[Tuple[int, float]]:
    """旧版全扫关键词检索（scan 模式 / 倒排索引不可用时兜底）。

    返回 [(切片下标, 分数)]，供 RRF 融合使用（只用名次）。
    """
    if not texts:
        return []
    query_words = set(tokenizer(query))
    if not query_words:
        return []

    scores: List[Tuple[int, float]] = []
    for idx, text in enumerate(texts):
        text_words = set(tokenizer(text))
        common = query_words & text_words
        if common:
            # 改进的 Jaccard 相似度 + 匹配词数加权
            score = len(common) / (len(query_words) + len(text_words) - len(common))
            score = score * (1 + 0.5 * len(common) / max(len(query_words), 1))
        else:
            score = 0.0
        scores.append((idx, float(score)))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[: max(1, int(top_k))]
