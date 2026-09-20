# src/knowledge/rag/query_engine.py
"""
RAG查询引擎
"""
from typing import List, Dict, Optional, Any
import json
import logging
from .prompt_builder import PromptBuilder
from ..core.retriever import HybridRetriever

logger = logging.getLogger(__name__)


class RAGQueryEngine:
    """RAG查询引擎"""
    
    def __init__(self, 
                 retriever: HybridRetriever,
                 llm_client: Optional[Any] = None,
                 max_context_chunks: int = 5,
                 top_k: int = 5):
        self.retriever = retriever
        self.llm_client = llm_client
        self.max_context_chunks = max_context_chunks
        self.top_k = top_k
        self.prompt_builder = PromptBuilder()
        
        logger.info("RAG查询引擎初始化完成")
    
    def query(self, 
              question: str, 
              top_k: Optional[int] = None,
              with_context: bool = True,
              need_llm: bool = False) -> Dict:
        """
        执行RAG查询
        """
        top_k = top_k or self.top_k
        
        # 1. 检索
        retrieved_chunks = self.retriever.search(question, top_k=top_k)
        
        # 2. 构建上下文
        context = self._build_context(retrieved_chunks)
        
        # 3. 生成回答（LLM 失败时降级为本地拼接，而非误报"未找到"）
        if with_context and need_llm and self.llm_client:
            answer = self._generate_answer(question, context, retrieved_chunks)
        else:
            # 本地模式：直接返回检索到的内容
            answer = self._build_local_answer(question, retrieved_chunks)
        
        return {
            "question": question,
            "answer": answer,
            "context": context,
            "sources": [
                {
                    "id": chunk.get("id", ""),
                    "content": chunk.get("content", ""),
                    "score": float(chunk.get("rerank_score", chunk.get("vector_score", 0))),
                    "metadata": chunk.get("metadata", {})
                }
                for chunk in retrieved_chunks
            ],
            "total_sources": len(retrieved_chunks)
        }
    
    def _build_context(self, chunks: List[Dict], max_chunks: int = None) -> str:
        """构建上下文"""
        max_chunks = max_chunks or self.max_context_chunks
        context_parts = []
        
        for i, chunk in enumerate(chunks[:max_chunks], 1):
            content = chunk.get("content", "")
            metadata = chunk.get("metadata", {})
            title = metadata.get("title", "未知来源")
            
            part = f"[{i}] 来自: {title}\n{content}\n"
            context_parts.append(part)
        
        return "\n---\n".join(context_parts)
    
    def _build_local_answer(self, question: str, chunks: List[Dict]) -> str:
        """构建本地答案（不调用LLM）"""
        if not chunks:
            return "未找到相关内容，请尝试换个问法或扩大检索范围。"
        
        answer_parts = []
        answer_parts.append(f"针对您的问题「{question}」，找到以下相关信息：\n")
        
        for i, chunk in enumerate(chunks[:5], 1):
            content = chunk.get("content", "")
            score = float(chunk.get("rerank_score", chunk.get("vector_score", 0)))
            metadata = chunk.get("metadata", {})
            title = metadata.get("title", "未知来源")
            
            answer_parts.append(f"【来源{i}】{title} (相关度: {score:.3f})")
            answer_parts.append(content)
            answer_parts.append("")
        
        return "\n".join(answer_parts)
    
    def _generate_answer(self, question: str, context: str, chunks: Optional[List[Dict]] = None) -> str:
        """调用LLM生成回答；LLM 不可用或调用失败时降级为本地拼接（保留检索片段）"""
        if not self.llm_client:
            return self._build_local_answer(question, chunks or [])
        
        try:
            prompt = self.prompt_builder.build_qa_prompt(question, context)
            
            # 适配不同的LLM接口
            if hasattr(self.llm_client, 'chat'):
                response = self.llm_client.chat(prompt)
            elif hasattr(self.llm_client, 'generate'):
                response = self.llm_client.generate(prompt)
            else:
                response = self.llm_client(prompt)
            
            return response
        except Exception as e:
            # ★ 修复：原降级传空列表，导致"检索到内容却回答未找到"；现保留实际片段
            logger.error(f"LLM生成失败，降级为本地拼接: {e}")
            return self._build_local_answer(question, chunks or [])
    
    def stream_query(self, question: str, top_k: Optional[int] = None):
        """流式查询"""
        top_k = top_k or self.top_k
        
        retrieved_chunks = self.retriever.search(question, top_k=top_k)
        context = self._build_context(retrieved_chunks)
        
        if self.llm_client and hasattr(self.llm_client, 'stream_chat'):
            prompt = self.prompt_builder.build_qa_prompt(question, context)
            for chunk in self.llm_client.stream_chat(prompt):
                yield chunk
        else:
            yield self._build_local_answer(question, retrieved_chunks)
