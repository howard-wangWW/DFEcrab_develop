# src/knowledge/core/retriever.py
"""
混合检索器 - 向量检索 + 关键词检索 + 重排序
"""
from typing import List, Dict, Tuple, Optional
import numpy as np
import math
from .keyword_index import KeywordIndex, search_scan
from .ranking import compute_fetch_k, diversify_by_doc
from .vector_store import VectorStore
from ..embedding.local_embedder import LocalEmbedder
from .reranker import Reranker, get_reranker
import logging

logger = logging.getLogger(__name__)


def _kn_cfg() -> Dict:
    """知识库调优参数（gateway.yaml 的 knowledge 段）；读取失败时用安全默认值"""
    try:
        from config.port_loader import knowledge_chunk_config
        return knowledge_chunk_config()
    except Exception:  # noqa: BLE001
        return {}


class HybridRetriever:
    """混合检索器（向量 + 关键词 + 可选重排）

    大库（十万级切片）关键设计：
      - 关键词检索走**倒排索引**（构建一次，查询只扫候选），避免每次查询全量分词
      - 候选先放大（top_k × max_per_doc × overfetch）再做同文档限流，防止"限流后结果不足"
    """

    def __init__(self,
                 vector_store: VectorStore,
                 embedder: LocalEmbedder,
                 use_rerank: bool = False,
                 max_per_doc: Optional[int] = None,
                 overfetch: Optional[int] = None,
                 keyword_search_mode: Optional[str] = None):
        """
        Args:
            vector_store: 向量存储
            embedder: 嵌入模型
            use_rerank: 是否使用重排序（本地模式建议关闭）
            max_per_doc: 同一文档最多保留的切片数（None=读 gateway.yaml，默认 2；<=0 不限流）
            overfetch: 候选放大倍数（None=读 gateway.yaml，默认 4）
            keyword_search_mode: index=倒排索引 / scan=逐片全扫（None=读 gateway.yaml）
        """
        cfg = _kn_cfg()
        self.vector_store = vector_store
        self.embedder = embedder
        self.use_rerank = use_rerank
        self.max_per_doc = int(cfg.get("max_per_doc", 2) if max_per_doc is None else max_per_doc)
        self.overfetch = int(cfg.get("retrieve_overfetch", 4) if overfetch is None else overfetch)
        mode = keyword_search_mode or cfg.get("keyword_search_mode", "index")
        self.keyword_search_mode = str(mode).strip().lower()
        self.keyword_max_df_ratio = float(cfg.get("keyword_max_df_ratio", 0.5))
        # ★ C-1：reranker 进程级单例（重复 new 会重复加载 CrossEncoder）
        self.reranker = get_reranker() if use_rerank else None

        # 构建文本缓存
        self.texts = []
        self.text_to_idx = {}
        self._kw_index = KeywordIndex(
            tokenizer=self.embedder._tokenize,
            max_df_ratio=self.keyword_max_df_ratio,
        )
        self._build_text_cache()

    def _build_text_cache(self):
        """构建文本缓存（并为新语料重置关键词索引，改为惰性重建）"""
        self.texts = []
        self.text_to_idx = {}
        for idx, metadata in enumerate(self.vector_store.metadatas):
            content = metadata.get("content", "")
            self.texts.append(content)
            chunk_id = self.vector_store.chunk_ids[idx] if idx < len(self.vector_store.chunk_ids) else None
            if chunk_id:
                self.text_to_idx[chunk_id] = idx
        # 语料变化 → 倒排索引失效，下次查询时重建（避免这里阻塞热刷新路径）
        self._kw_index = KeywordIndex(
            tokenizer=self.embedder._tokenize,
            max_df_ratio=self.keyword_max_df_ratio,
        )

    def warmup_keyword_index(self) -> bool:
        """预热关键词倒排索引（索引重建完成后在后台线程调用，避免首个用户查询变慢）"""
        if self.keyword_search_mode != "index" or not self.texts:
            return False
        return self._kw_index.ensure_built(self.texts)
    
    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """混合检索"""
        total = len(self.vector_store.chunk_ids)
        if total == 0:
            return []

        # ★ 候选放大：大库里单篇大文档会霸占 top-N，限流后结果不足，故先取
        #   top_k × max_per_doc × overfetch 再限流（小库无副作用，仅多取几条）
        fetch_k = min(compute_fetch_k(top_k, self.max_per_doc, self.overfetch), total)

        # 1. 向量检索
        query_emb = self.embedder.embed_queries([query])
        vector_results = self.vector_store.search(query_emb, top_k=fetch_k)

        if not vector_results:
            return []

        # 2. 关键词检索（倒排索引：构建一次，查询只扫候选）
        keyword_results = self._keyword_search(query, top_k=fetch_k)

        # 3. 融合结果（RRF）
        merged = self._merge_results(vector_results, keyword_results)

        # 4. 同文档去重（召回多样性）：按 doc_id 限流，同一文档最多 max_per_doc 条
        merged = self._diversify(merged)

        # 5. 重排序（可选）
        if self.use_rerank and self.reranker is not None and self.reranker.is_available():
            candidates = merged[: top_k * 3]
            passages = [m["content"] for m in candidates]
            ranked = self.reranker.rerank(query, passages, top_k=top_k)
            results = []
            for i, score in ranked:
                if i < len(candidates):
                    c = dict(candidates[i])
                    c["rerank_score"] = float(score)
                    c["final_score"] = float(score)
                    results.append(c)
            return results

        return merged[:top_k]

    def _diversify(self, ranked: List[Dict]) -> List[Dict]:
        """按文档去重（实现见 core/ranking.py，纯函数便于单测）"""
        return diversify_by_doc(ranked, self.max_per_doc)

    def _keyword_search(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """关键词检索（默认倒排索引；scan 模式保留旧的全扫行为作兜底）

        返回 [(chunk_id, score)]，供 RRF 融合使用（只用名次）。
        """
        if not self.texts:
            return []

        if self.keyword_search_mode == "scan":
            pairs = search_scan(self.texts, self.embedder._tokenize, query, top_k)
        else:
            # 惰性构建：首次查询建一次（与旧实现"单次查询成本"相当），之后查询均为 O(候选)
            if not self._kw_index.ensure_built(self.texts):
                pairs = search_scan(self.texts, self.embedder._tokenize, query, top_k)
            else:
                pairs = self._kw_index.search(query, top_k)

        results = []
        for idx, score in pairs:
            if 0 <= idx < len(self.vector_store.chunk_ids):
                results.append((self.vector_store.chunk_ids[idx], float(score)))
        return results
    
    def _merge_results(self, vector_results, keyword_results) -> List[Dict]:
        """RRF融合结果"""
        result_map = {}
        rrf_k = 60
        
        # 向量检索结果
        for rank, (chunk_id, score, metadata) in enumerate(vector_results):
            result_map[chunk_id] = {
                "id": chunk_id,
                "content": metadata.get("content", ""),
                "vector_score": score,
                "keyword_score": 0,
                "metadata": metadata,
                "rrf_score": 1.0 / (rrf_k + rank + 1)
            }
        
        # 关键词检索结果
        for rank, (chunk_id, score) in enumerate(keyword_results):
            if chunk_id in result_map:
                result_map[chunk_id]["keyword_score"] = score
                result_map[chunk_id]["rrf_score"] += 1.0 / (rrf_k + rank + 1)
        
        # 按RRF分数排序
        results = sorted(result_map.values(), key=lambda x: x["rrf_score"], reverse=True)
        return results
    
    def get_stats(self) -> Dict:
        """获取统计信息（含关键词索引状态，便于大库排查"检索慢/召回少"）"""
        return {
            "total_chunks": len(self.vector_store.chunk_ids),
            "text_cache_size": len(self.texts),
            "use_rerank": self.use_rerank,
            "max_per_doc": self.max_per_doc,
            "retrieve_overfetch": self.overfetch,
            "keyword_search_mode": self.keyword_search_mode,
            "keyword_index": self._kw_index.stats(),
        }
