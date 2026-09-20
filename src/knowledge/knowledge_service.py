# src/knowledge/knowledge_service.py
"""
知识库服务 - 对外提供API服务
"""
import json
import re
import time
from pathlib import Path
from typing import Dict, Optional
import logging

from .paths import LLM_CONFIG_FILE
from src.utils.api_base import normalize_api_base

logger = logging.getLogger(__name__)


class KnowledgeService:
    """知识库服务"""
    
    def __init__(self):
        self.repo = None
        self.skill = None
        self._init_service()
    
    def _init_service(self):
        """初始化服务"""
        try:
            from .storage.document_repo import DocumentRepository
            from .skills.knowledge_qa import KnowledgeQASkill

            self.repo = DocumentRepository()
            llm_config = self._load_llm_config()
            self.skill = KnowledgeQASkill({"llm": llm_config} if llm_config else None)
            logger.info("✅ 知识库服务初始化成功")
        except Exception as e:
            logger.error(f"知识库服务初始化失败: {e}")

    def _load_llm_config(self) -> Optional[Dict]:
        """从 config/dfecrab.json 读取第一个 enabled 的 model_providers

        路径锚定项目根（LLM_CONFIG_FILE），避免因启动目录不同静默降级为本地拼接。
        """
        try:
            cfg_file = LLM_CONFIG_FILE
            if not cfg_file.exists():
                return None
            data = json.loads(cfg_file.read_text(encoding="utf-8"))
            for name, pc in data.get("model_providers", {}).items():
                if pc.get("enabled") and pc.get("api_base"):
                    return {
                        # ★ 统一清洗：直接读文件绕过了 ModelManager，这里兜底剥完整接口地址
                        "api_base": normalize_api_base(pc.get("api_base", "")),
                        "model_name": pc.get("model_name", ""),
                        "api_key": pc.get("api_key", "not-needed"),
                        "timeout": pc.get("timeout", 300),
                    }
        except Exception as e:
            logger.warning(f"读取模型配置失败: {e}")
        return None

    @staticmethod
    def _clean_filename_stem(filename: str) -> str:
        """文件名去扩展名，并清理常见下载重复后缀（如 "xxx (1)"、"xxx（2）"）。"""
        stem = Path(filename).stem
        cleaned = re.sub(r'\s*[（(]\d+[)）]\s*$', '', stem).strip()
        return cleaned or stem

    def upload_document(self, temp_path: str, filename: str,
                        category: str = "other", title: str = None) -> Dict:
        """导入已落盘的文档到知识库（API 层负责流式接收与大小限制）

        流程：登记 → 解析(深度 docx) → 切片 → 写磁盘 → 异步重建索引 + 内存热刷新。
        解析后无有效文本 / 未生成切片时明确报错，避免"上传成功但检索不到"的静默问题。
        """
        if not self.repo:
            return {"status": "error", "message": "知识库未初始化"}

        temp_file = Path(temp_path)
        doc_info = None
        try:
            if not temp_file.exists():
                raise ValueError(f"上传的临时文件不存在: {temp_path}")

            from .storage.document_loader import DocumentLoader
            from .core.document_processor import DocumentProcessor

            # 1. 登记文档（pending → processing）；标题初值：用户传 > 文件名（清理下载重复后缀）
            initial_title = (title or "").strip() or self._clean_filename_stem(filename)
            doc_info = self.repo.add_document(
                str(temp_file),
                category=category,
                title=initial_title,
                original_name=filename,
            )
            self.repo.update_status(doc_info.doc_id, "processing", chunk_count=0)

            # 2. 解析文本（loader 内部记录图片数 / 候选标题并打日志）
            loader = DocumentLoader()
            content = loader.load_document(str(temp_file))

            # 2.1 标题回写：用户显式指定优先；否则用正文提取（Heading / PDF 元数据 / MD 一级标题）
            if not (title or "").strip() and loader.last_title:
                new_title = loader.last_title.strip()
                if new_title and new_title != doc_info.title:
                    self.repo.update_title(doc_info.doc_id, new_title)
                    doc_info = self.repo.get_document(doc_info.doc_id) or doc_info

            if not content.strip():
                self.repo.update_status(doc_info.doc_id, "failed", chunk_count=0)
                raise ValueError(
                    "文档解析后无有效文本内容（可能为扫描件/纯图片文档），"
                    "请先转为文字版，或用 OCR 流程提取图片文字后再上传"
                )

            # 2.2 落盘解析文本（便于排查切片/召回问题；失败不影响主流程）
            try:
                text_path = self.repo.get_processed_text_path(doc_info.doc_id)
                with open(text_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                logger.warning(f"解析文本落盘失败（忽略）: {e}")

            # 3. 切片（参数来自 config/gateway.yaml 的 knowledge 段，多现场可覆盖；
            #    默认与 bge-small-zh-v1.5 的 512 token 窗口对齐）
            from config.port_loader import knowledge_chunk_config
            cc = knowledge_chunk_config()
            processor = DocumentProcessor(
                chunk_size=cc["chunk_size"],
                overlap=cc["chunk_overlap"],
                min_chunk_size=cc["min_chunk_size"],
                table_rows_per_chunk=cc["table_rows_per_chunk"],
                qa_pair_keep=cc["qa_pair_keep"],
            )
            metadata = {
                "doc_id": doc_info.doc_id,
                "source": filename,
                "category": category,
                "title": doc_info.title
            }
            chunks = processor.process_document(content, metadata)

            if not chunks:
                self.repo.update_status(doc_info.doc_id, "failed", chunk_count=0)
                raise ValueError("未生成有效切片（文本不足或均为无效内容）")

            # 4. 保存切片
            chunks_path = self.repo.get_chunks_path(doc_info.doc_id)
            chunks_data = [
                {"id": c.id, "content": c.content, "metadata": c.metadata}
                for c in chunks
            ]
            with open(chunks_path, 'w', encoding='utf-8') as f:
                json.dump(chunks_data, f, ensure_ascii=False, indent=2)

            self.repo.update_status(doc_info.doc_id, "processed", chunk_count=len(chunks))

            # 5. 异步重建索引（完成后热刷新内存索引，无需重启即可检索）
            self._rebuild_index_async()

            logger.info(
                f"📥 文档导入完成: {filename} | 字符={len(content)} | "
                f"切片={len(chunks)} | 图片={loader.last_image_count} | "
                f"doc_id={doc_info.doc_id}"
            )

            return {
                "status": "success",
                "doc_id": doc_info.doc_id,
                "title": doc_info.title,
                "chunk_count": len(chunks),
                "image_count": loader.last_image_count,
                "message": f"文档上传成功，生成 {len(chunks)} 个切片",
            }

        except Exception as e:
            logger.error(f"上传文档失败: {e}")
            if doc_info is not None:
                try:
                    self.repo.update_status(doc_info.doc_id, "failed")
                except Exception:
                    pass
            return {"status": "error", "message": str(e)}

        finally:
            # 无论成功失败都清理临时文件
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception:
                pass
    
    def search(self, query: str, top_k: int = 5, category: str = None) -> Dict:
        """
        检索文档内容
        
        Args:
            query: 搜索关键词
            top_k: 返回结果数量
            category: 文档分类过滤（支持自定义分类）
        """
        if not self.skill:
            return {"status": "error", "message": "知识库未初始化"}
        
        logger.info(f"[KB/search] 入参 query={query!r} top_k={top_k} category={category}")
        _t0 = time.time()
        try:
            # ★ 分类过滤：FAISS 无原生元数据过滤，先取 top_k 再过滤会导致结果不足；
            #   有 category 时先超采（top_k × filter_overfetch）再过滤，最后截断回 top_k。
            fetch_k = top_k * self._filter_overfetch() if category else top_k
            result = self.skill.retrieve(query, top_k=fetch_k)

            if result["status"] == "error":
                logger.warning(f"[KB/search] 检索失败: {result.get('message')}")
                return result

            # 按分类过滤（超采后过滤，截断回 top_k）
            sources = result.get("sources", []) or []
            if category:
                sources = [
                    s for s in sources
                    if s.get("metadata", {}).get("category") == category
                ][:top_k]
            
            resp = {
                "status": "success",
                "query": query,
                "total": len(sources),
                "category": category,
                "results": [
                    {
                        "content": s.get("content", ""),
                        "score": float(s.get("score", 0)),
                        "title": s.get("metadata", {}).get("title", "未知"),
                        "source": s.get("metadata", {}).get("source", "未知"),
                        "category": s.get("metadata", {}).get("category", "other"),
                        "doc_id": s.get("metadata", {}).get("doc_id", "")
                    }
                    for s in sources
                ]
            }
            # ★ 修复：原实现把日志写在 finally 里且引用可能未定义的 sources，
            #   检索失败/提前 return 时会抛 NameError 把友好错误变成 500。
            #   现改为成功路径显式输出日志。
            logger.info(f"[KB/search] 出参 total={len(sources)} 耗时={time.time()-_t0:.2f}s")
            self._log_search_hits(sources)
            return resp

        except Exception as e:
            logger.error(f"[KB/search] 检索异常: {e}")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _log_search_hits(sources) -> None:
        """检索命中详情（debug 级，供现场排查召回质量）"""
        for _i, _s in enumerate(sources[:8], 1):
            _meta = _s.get("metadata", {})
            logger.debug(f"[KB/search]   #{_i} score={_s.get('score', 0):.3f} "
                         f"doc={_meta.get('doc_id', '')} title={_meta.get('title', '')} "
                         f"content={_s.get('content', '')[:200]!r}")
    
    @staticmethod
    def _filter_overfetch() -> int:
        """分类过滤时的超采倍数（config/gateway.yaml 的 knowledge.filter_overfetch，默认 6）"""
        try:
            from config.port_loader import knowledge_chunk_config
            return max(1, int(knowledge_chunk_config().get("filter_overfetch", 6)))
        except Exception:
            return 6

    def chat(self, question: str, top_k: int = 5, category: str = None) -> Dict:
        """问答对话（支持按分类过滤）"""
        if not self.skill:
            return {"status": "error", "message": "知识库未初始化"}

        logger.info(f"[KB/chat] 入参 question={question!r} top_k={top_k} category={category}")
        _t0 = time.time()
        try:
            # ★ 同 search：有 category 时先超采再过滤，避免过滤后来源不足
            fetch_k = top_k * self._filter_overfetch() if category else top_k
            result = self.skill.execute(question, top_k=fetch_k, need_llm=True)

            if result["status"] == "error":
                logger.warning(f"[KB/chat] 问答失败: {result.get('message')}")
                return result

            # 按分类过滤来源（超采后过滤，截断回 top_k）
            sources = result.get("sources", [])
            if category:
                sources = [
                    s for s in sources
                    if s.get("metadata", {}).get("category") == category
                ][:top_k]
            
            result["sources"] = sources
            result["total_sources"] = len(sources)
            result["category"] = category

            _ans = result.get("answer", "")
            logger.info(f"[KB/chat] 出参 answer_len={len(_ans)} total_sources={len(sources)} "
                        f"耗时={time.time()-_t0:.2f}s")
            logger.debug(f"[KB/chat]  answer={_ans[:500]!r}{'...' if len(_ans) > 500 else ''}")
            for _i, _s in enumerate(sources[:8], 1):
                _meta = _s.get("metadata", {})
                logger.debug(f"[KB/chat]   #{_i} score={_s.get('score', 0):.3f} "
                             f"doc={_meta.get('doc_id', '')} title={_meta.get('title', '')} "
                             f"content={_s.get('content', '')[:150]!r}")
            return result
            
        except Exception as e:
            logger.error(f"[KB/chat] 问答异常: {e}")
            return {"status": "error", "message": str(e)}
    
    def list_documents(self) -> Dict:
        """列出所有文档"""
        if not self.repo:
            return {"status": "error", "message": "知识库未初始化"}
        
        try:
            docs = self.repo.list_documents()
            return {
                "status": "success",
                "total": len(docs),
                "documents": [
                    {
                        "doc_id": d.doc_id,
                        "title": d.title,
                        "category": d.category,
                        "status": d.status,
                        "chunk_count": d.chunk_count,
                        "upload_time": d.upload_time,
                        "file_name": d.file_name
                    }
                    for d in docs
                ]
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_document_chunks(self, doc_id: str) -> Dict:
        """
        获取文档的所有切片内容（按顺序）
        
        Args:
            doc_id: 文档ID
        
        Returns:
            {
                "status": "success",
                "doc_id": "xxx",
                "title": "xxx",
                "category": "xxx",
                "file_name": "xxx",
                "total_chunks": 10,
                "chunks": [
                    {
                        "index": 1,
                        "id": "xxx",
                        "content": "xxx",
                        "metadata": {...}
                    }
                ]
            }
        """
        if not self.repo:
            return {"status": "error", "message": "知识库未初始化"}
        
        try:
            # 检查文档是否存在
            doc_info = self.repo.get_document(doc_id)
            if not doc_info:
                return {"status": "error", "message": f"文档不存在: {doc_id}"}
            
            # 获取切片文件路径
            chunks_path = self.repo.get_chunks_path(doc_id)
            if not chunks_path.exists():
                return {
                    "status": "error", 
                    "message": f"文档切片不存在，请先处理文档: {doc_id}"
                }
            
            # 读取切片数据
            with open(chunks_path, 'r', encoding='utf-8') as f:
                chunks_data = json.load(f)
            
            # 格式化输出，按顺序排列
            formatted_chunks = []
            for idx, chunk in enumerate(chunks_data, 1):
                formatted_chunks.append({
                    "index": idx,
                    "id": chunk.get("id", ""),
                    "content": chunk.get("content", ""),
                    "metadata": chunk.get("metadata", {})
                })
            
            return {
                "status": "success",
                "doc_id": doc_id,
                "title": doc_info.title,
                "category": doc_info.category,
                "file_name": doc_info.file_name,
                "total_chunks": len(formatted_chunks),
                "chunks": formatted_chunks
            }
            
        except json.JSONDecodeError as e:
            return {"status": "error", "message": f"切片数据格式错误: {str(e)}"}
        except Exception as e:
            logger.error(f"获取文档切片失败: {e}")
            return {"status": "error", "message": str(e)}
    
    def list_knowledge_bases(self) -> Dict:
        """列出知识库（扁平模型：仅一个默认知识库，包含全部文档）"""
        if not self.repo:
            return {"status": "error", "message": "知识库未初始化"}
        try:
            docs = self.repo.list_documents()
            return {
                "status": "success",
                "total": 1,
                "knowledge_bases": [
                    {
                        "kb_id": "default",
                        "name": "默认知识库",
                        "description": "",
                        "category": "other",
                        "doc_count": len(docs),
                        "chunk_count": sum(d.chunk_count for d in docs),
                        "doc_ids": [d.doc_id for d in docs],
                    }
                ]
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def list_categories(self) -> Dict:
        """列出所有可用分类（默认分类 ∪ 文档已用分类）"""
        if not self.repo:
            return {"status": "error", "message": "知识库未初始化"}
        try:
            return {
                "status": "success",
                "total": len(self.repo.list_categories()),
                "categories": self.repo.list_categories(),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def delete_document(self, doc_id: str) -> Dict:
        """删除文档"""
        if not self.repo:
            return {"status": "error", "message": "知识库未初始化"}
        
        try:
            result = self.repo.delete_document(doc_id)
            if result:
                self._rebuild_index_async()
                return {"status": "success", "message": "文档已删除"}
            return {"status": "error", "message": "文档不存在"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        if not self.repo:
            return {"status": "error", "message": "知识库未初始化"}
        
        try:
            stats = self.repo.get_stats()
            return {"status": "success", **stats}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def _rebuild_index_async(self):
        """异步重建索引 + 内存热刷新

        重建完成后把新索引原子替换到正在服务的 retriever 上，
        修复"上传后必须重启知识库服务才能搜到新文档"的问题。
        """
        import threading
        try:
            from .core.vector_store import VectorStore, invalidate_default_vector_store
            from .embedding.local_embedder import get_local_embedder
            import numpy as np
            
            def rebuild():
                try:
                    all_chunks = []
                    for doc_id, doc_info in self.repo.documents.items():
                        if doc_info.status in ["pending", "processing", "processed", "indexed"]:
                            chunks_path = self.repo.get_chunks_path(doc_id)
                            if chunks_path.exists():
                                with open(chunks_path, 'r', encoding='utf-8') as f:
                                    chunks = json.load(f)
                                    for chunk in chunks:
                                        chunk["metadata"]["title"] = doc_info.title
                                    all_chunks.extend(chunks)

                    if not all_chunks:
                        logger.warning("⚠️ 索引重建跳过：无有效切片")
                        return

                    embedder = get_local_embedder()
                    contents = [c["content"] for c in all_chunks]
                    # ★ 分批嵌入：大文档（如 Excel 表格）切片多，一次性全量 embed 易超时/占内存
                    embed_batch = 100
                    emb_parts = [
                        embedder.embed(contents[i:i + embed_batch])
                        for i in range(0, len(contents), embed_batch)
                    ]
                    embeddings = np.vstack(emb_parts) if len(emb_parts) > 1 else emb_parts[0]

                    vector_store = VectorStore(dim=embedder.get_dim())
                    chunk_ids = [c["id"] for c in all_chunks]
                    metadatas = [c["metadata"] for c in all_chunks]

                    vector_store.add(embeddings, chunk_ids, metadatas)
                    vector_store.save(str(self.repo.index_dir))

                    for doc_id in self.repo.documents:
                        if self.repo.get_chunks_path(doc_id).exists():
                            self.repo.update_status(doc_id, "indexed")

                    # ★ 内存热刷新：无需重启服务即可检索到新上传文档
                    self._hot_swap_index(vector_store)
                    # ★ C-1：重建写盘后主动失效默认索引缓存，同进程 read 侧按新磁盘态重载
                    invalidate_default_vector_store()
                    logger.info(f"✅ 索引重建完成，共 {len(chunk_ids)} 条切片，已热刷新")

                except Exception as e:
                    logger.error(f"异步重建索引失败: {e}")
                    import traceback
                    traceback.print_exc()

            thread = threading.Thread(target=rebuild)
            thread.daemon = True
            thread.start()
            
        except Exception as e:
            logger.error(f"启动异步重建失败: {e}")

    def _hot_swap_index(self, new_store) -> None:
        """原子替换正在服务的内存向量索引，并重建检索器文本缓存"""
        try:
            if not (self.skill and getattr(self.skill, "rag_engine", None)):
                logger.warning("内存热刷新跳过：知识库技能尚未就绪")
                return
            retriever = self.skill.rag_engine.retriever
            old_count = len(retriever.vector_store.chunk_ids) if retriever.vector_store else 0
            retriever.vector_store = new_store
            retriever._build_text_cache()
            logger.info(
                f"✅ 内存索引热刷新完成（{old_count} → {len(new_store.chunk_ids)} 条）"
            )
        except Exception as e:
            logger.error(f"内存索引热刷新失败（磁盘索引已更新，重启后生效）: {e}")


# 全局单例
_knowledge_service = None

def get_knowledge_service() -> KnowledgeService:
    """获取知识库服务单例"""
    global _knowledge_service
    if _knowledge_service is None:
        _knowledge_service = KnowledgeService()
    return _knowledge_service
