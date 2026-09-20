# src/knowledge/core/retriever.py
"""
混合检索器 - 向量检索 + 关键词检索 + 重排序
"""
from typing import List, Dict, Tuple, Optional
import numpy as np
import math
from .vector_store import VectorStore
from ..embedding.local_embedder import LocalEmbedder
from .reranker import Reranker, get_reranker
import logging

logger = logging.getLogger(__name__)


class HybridRetriever:
    """混合检索器"""
    
    def __init__(self, 
                 vector_store: VectorStore,
                 embedder: LocalEmbedder,
                 use_rerank: bool = False,
                 max_per_doc: int = 2):
        """
        Args:
            vector_store: 向量存储
            embedder: 嵌入模型
            use_rerank: 是否使用重排序（本地模式建议关闭）
            max_per_doc: 同一文档最多保留的切片数（召回多样性，避免单篇霸占）
        """
        self.vector_store = vector_store
        self.embedder = embedder
        self.use_rerank = use_rerank
        self.max_per_doc = max_per_doc
        # ★ C-1：reranker 进程级单例（重复 new 会重复加载 CrossEncoder）
        self.reranker = get_reranker() if use_rerank else None
        
        # 构建文本缓存
        self.texts = []
        self.text_to_idx = {}
        self._build_text_cache()
    
    def _build_text_cache(self):
        """构建文本缓存"""
        self.texts = []
        self.text_to_idx = {}
        for idx, metadata in enumerate(self.vector_store.metadatas):
            content = metadata.get("content", "")
            self.texts.append(content)
            chunk_id = self.vector_store.chunk_ids[idx] if idx < len(self.vector_store.chunk_ids) else None
            if chunk_id:
                self.text_to_idx[chunk_id] = idx
    
    def search(self, query: str, top_k: int = 10) -> List[Dict]:
        """混合检索"""
        if len(self.vector_store.chunk_ids) == 0:
            return []
        
        # 1. 向量检索
        query_emb = self.embedder.embed_queries([query])
        vector_results = self.vector_store.search(query_emb, top_k=top_k * 2)
        
        if not vector_results:
            return []
        
        # 2. 关键词检索（BM25风格）
        keyword_results = self._keyword_search(query, top_k=top_k * 2)
        
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
        """按文档去重：同一 doc_id 最多保留 max_per_doc 个切片，其余让给其他文档。

        基于已按 rrf_score 降序的列表，顺序扫描并计数，超过上限的跳过。
        保留同文档中相关度最高的切片，同时给其他文档留出位置。
        """
        if self.max_per_doc <= 0:
            return ranked

        result = []
        doc_count: Dict[str, int] = {}
        for item in ranked:
            doc_id = (item.get("metadata") or {}).get("doc_id") or ""
            if not doc_id:
                # 无 doc_id 的切片不参与限流（理论上不存在，防御性保留）
                result.append(item)
                continue
            n = doc_count.get(doc_id, 0)
            if n >= self.max_per_doc:
                continue
            doc_count[doc_id] = n + 1
            result.append(item)
        return result
    
    def _keyword_search(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        """关键词检索"""
        if not self.texts:
            return []
        
        # 分词
        query_words = set(self.embedder._tokenize(query))
        if not query_words:
            return []
        
        # 计算BM25分数
        scores = []
        for idx, text in enumerate(self.texts):
            text_words = set(self.embedder._tokenize(text))
            common = query_words & text_words
            if common:
                # 使用改进的Jaccard相似度
                score = len(common) / (len(query_words) + len(text_words) - len(common))
                # 加权：匹配词越多越好
                score = score * (1 + 0.5 * len(common) / max(len(query_words), 1))
            else:
                score = 0
            scores.append((idx, score))
        
        # 排序
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # 返回结果
        results = []
        for idx, score in scores[:top_k]:
            if idx < len(self.vector_store.chunk_ids):
                chunk_id = self.vector_store.chunk_ids[idx]
                results.append((chunk_id, score))
        
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
        """获取统计信息"""
        return {
            "total_chunks": len(self.vector_store.chunk_ids),
            "text_cache_size": len(self.texts),
            "use_rerank": self.use_rerank
        }
