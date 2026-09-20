# src/knowledge/skills/knowledge_search.py
"""
知识库检索技能 - 纯检索，不生成回答
"""
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

SKILL_METADATA = {
    "name": "knowledge_search",
    "version": "1.0.0",
    "description": "在知识库中检索文档内容，返回相关片段",
    "author": "DFEcrab Team",
    "parameters": {
        "query": {
            "type": "string",
            "description": "搜索关键词或问题"
        },
        "top_k": {
            "type": "integer",
            "description": "返回结果数量，默认5",
            "default": 5
        },
        "category": {
            "type": "string",
            "description": "文档分类过滤，可选: power_grid/operation_manual/training/cases/other",
            "default": None
        },
        "knowledge_base": {
            "type": "string",
            "description": "知识库名称过滤",
            "default": None
        }
    }
}


class KnowledgeSearchSkill:
    """知识库检索技能"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.rag_engine = None
        self.repo = None
        self._init_engine()
    
    def _init_engine(self):
        try:
            from ..core.vector_store import load_default_vector_store
            from ..embedding.local_embedder import get_local_embedder
            from ..core.retriever import HybridRetriever
            from ..rag.query_engine import RAGQueryEngine
            from ..storage.document_repo import DocumentRepository
            
            top_k = self.config.get("top_k", 5)
            embedder = get_local_embedder()
            
            vector_store = load_default_vector_store(embedder.get_dim())
            
            retriever = HybridRetriever(
                vector_store=vector_store,
                embedder=embedder,
                use_rerank=True
            )
            
            self.rag_engine = RAGQueryEngine(
                retriever=retriever,
                llm_client=None,
                top_k=top_k
            )
            
            self.repo = DocumentRepository()
            
            logger.info("✅ 知识库检索技能初始化成功")
            
        except Exception as e:
            logger.error(f"知识库检索技能初始化失败: {e}")
            self.rag_engine = None
    
    def execute(self, query: str = "", top_k: int = 5, 
                category: str = None, knowledge_base: str = None,
                **kwargs) -> Dict[str, Any]:
        """执行检索"""
        if not query:
            return {"status": "error", "message": "查询不能为空"}
        
        if not self.rag_engine:
            return {"status": "error", "message": "知识库未初始化"}
        
        try:
            # 如果指定了知识库名称，在查询中添加
            search_query = query
            if knowledge_base:
                search_query = f"{query} {knowledge_base}"
            
            result = self.rag_engine.query(search_query, top_k=top_k * 2)
            
            # 过滤结果
            sources = result.get("sources", [])
            
            # 按分类过滤
            if category:
                sources = [
                    s for s in sources
                    if s.get("metadata", {}).get("category") == category
                ]
            
            # 按知识库名称过滤
            if knowledge_base:
                sources = [
                    s for s in sources
                    if knowledge_base in s.get("metadata", {}).get("title", "")
                ]
            
            # 限制返回数量
            sources = sources[:top_k]
            
            return {
                "status": "success",
                "query": query,
                "total": len(sources),
                "category": category,
                "knowledge_base": knowledge_base,
                "results": [
                    {
                        "content": s.get("content", ""),
                        "score": s.get("score", 0),
                        "title": s.get("metadata", {}).get("title", "未知"),
                        "source": s.get("metadata", {}).get("source", "未知"),
                        "category": s.get("metadata", {}).get("category", "other"),
                        "doc_id": s.get("metadata", {}).get("doc_id", "")
                    }
                    for s in sources
                ]
            }
            
        except Exception as e:
            logger.error(f"检索失败: {e}")
            return {"status": "error", "message": str(e)}
    
    def get_info(self) -> Dict:
        """获取技能信息"""
        return SKILL_METADATA
    
    def is_ready(self) -> bool:
        """检查技能是否就绪"""
        return self.rag_engine is not None
