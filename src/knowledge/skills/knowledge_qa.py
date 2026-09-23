# src/knowledge/skills/knowledge_qa.py
"""
知识库问答技能 - 集成到DFEcrab技能系统
"""
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)

# 技能元数据
SKILL_METADATA = {
    "name": "knowledge_qa",
    "version": "1.0.0",
    "description": "基于知识库的智能问答，检索 + LLM 综合生成回答（LLM 不可用时自动降级为本地拼接）",
    "author": "DFEcrab Team",
    "parameters": {
        "question": {
            "type": "string",
            "description": "用户要查询的问题"
        },
        "top_k": {
            "type": "integer",
            "description": "返回的文档片段数量，默认5",
            "default": 5
        }
    }
}


class KnowledgeQASkill:
    """知识库问答技能 - 检索 + LLM 生成回答"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.rag_engine = None
        self._init_engine()

    def _init_llm_client(self):
        """从 config 初始化 LLM 客户端；未配置/失败返回 None（自动降级为本地拼接）"""
        llm_config = self.config.get("llm")
        if not llm_config:
            return None
        try:
            from ..llm.openai_client import OpenAICompatibleClient
            client = OpenAICompatibleClient(llm_config)
            logger.info(f"✅ LLM 已接入: {client.model_name} @ {client.api_base}")
            return client
        except Exception as e:
            logger.warning(f"LLM 初始化失败，chat 将使用本地拼接回答: {e}")
            return None

    def _init_engine(self):
        """初始化RAG引擎"""
        try:
            from ..core.vector_store import load_default_vector_store
            from ..embedding.local_embedder import get_local_embedder
            from ..core.retriever import HybridRetriever
            from ..rag.query_engine import RAGQueryEngine

            # 配置（gateway.yaml → knowledge 段的 qa_* 场景参数，由 KnowledgeService 注入）
            top_k = self.config.get("top_k", 5)
            max_per_doc = self.config.get("max_per_doc", 2)
            # 送入 LLM 的切片数上限，缺省与 top_k 对齐（避免 sources 与 LLM 实际依据不一致）
            max_context_chunks = self.config.get("max_context_chunks", top_k)

            # 使用本地嵌入 + 统一位置向量索引（锚定项目根 knowledge_base/index）
            embedder = get_local_embedder()
            vector_store = load_default_vector_store(embedder.get_dim())

            # 创建检索器
            retriever = HybridRetriever(
                vector_store=vector_store,
                embedder=embedder,
                use_rerank=True,
                max_per_doc=max_per_doc
            )

            # 创建RAG引擎（接入 LLM，失败自动降级为本地拼接）
            llm_client = self._init_llm_client()
            self.rag_engine = RAGQueryEngine(
                retriever=retriever,
                llm_client=llm_client,
                top_k=top_k,
                max_context_chunks=max_context_chunks,
            )
            mode = "LLM问答模式" if llm_client else "本地TF-IDF模式"
            logger.info(f"✅ 知识库技能初始化成功（{mode}）")

        except Exception as e:
            logger.error(f"知识库技能初始化失败: {e}")
            self.rag_engine = None

    def execute(self, question: str = "", top_k: int = None,
                need_llm: bool = True, **kwargs) -> Dict[str, Any]:
        """问答：检索 + 生成回答。need_llm=True 且 LLM 可用 → 综合生成；否则拼接降级

        top_k 缺省时回落配置值（knowledge.qa_top_k），保证技能链路与服务链路召回口径一致。
        """
        if not question:
            return {"status": "error", "message": "问题不能为空"}

        top_k = top_k or self.config.get("top_k", 5)

        if not self.rag_engine:
            return {"status": "error", "message": "知识库未初始化，请先导入文档"}

        logger.info(f"[QA/execute] question={question!r} top_k={top_k} need_llm={need_llm} "
                    f"llm_mode={'on' if self.rag_engine.llm_client else 'off'}")
        try:
            result = self.rag_engine.query(question, top_k=top_k, need_llm=need_llm)

            if not result["sources"]:
                logger.info(f"[QA/execute] 无召回结果")
                return {
                    "status": "success",
                    "answer": "未找到相关内容，请尝试换个问法或扩大检索范围。",
                    "question": question,
                    "sources": []
                }

            _ans = result["answer"]
            logger.info(f"[QA/execute] 召回 {result['total_sources']} 条, answer_len={len(_ans)}")
            logger.debug(f"[QA/execute] answer={_ans[:300]!r}{'...' if len(_ans) > 300 else ''}")
            return {
                "status": "success",
                "answer": _ans,
                "question": result["question"],
                "sources": result["sources"],
                "total_sources": result["total_sources"]
            }

        except Exception as e:
            logger.error(f"[QA/execute] 查询失败: {e}")
            return {"status": "error", "message": f"查询失败: {str(e)}"}

    def retrieve(self, query: str = "", top_k: int = 5, **kwargs) -> Dict[str, Any]:
        """纯检索（供 search 使用）：只返回片段，不生成 answer"""
        if not query:
            return {"status": "error", "message": "查询不能为空"}

        if not self.rag_engine:
            return {"status": "error", "message": "知识库未初始化，请先导入文档"}

        try:
            chunks = self.rag_engine.retriever.search(query, top_k=top_k)
            return {
                "status": "success",
                "query": query,
                "sources": [
                    {
                        "content": c.get("content", ""),
                        "score": float(c.get("rerank_score", c.get("vector_score", 0))),
                        "metadata": c.get("metadata", {}),
                    }
                    for c in chunks
                ],
                "total_sources": len(chunks),
            }
        except Exception as e:
            logger.error(f"知识库检索失败: {e}")
            return {"status": "error", "message": f"检索失败: {str(e)}"}

    def get_info(self) -> Dict:
        """获取技能信息"""
        return SKILL_METADATA

    def is_ready(self) -> bool:
        """检查技能是否就绪"""
        return self.rag_engine is not None
