# src/knowledge/knowledge_service.py
"""
知识库服务 - 对外提供API服务
"""
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional
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
        """初始化服务

        配置装配优先走 .llm.config_loader（问答链路与技能链路共用的事实源：
        场景级 config/gateway.yaml 的 knowledge.qa_* + 模型级 config/dfecrab.json
        的 provider）；该模块在当前现场不存在时回落到下方 _load_skill_config
        的内置读取，避免知识库因缺一个可选模块而整体起不来。
        """
        try:
            from .storage.document_repo import DocumentRepository
            from .skills.knowledge_qa import KnowledgeQASkill

            self.repo = DocumentRepository()
            self.skill = KnowledgeQASkill(self._load_skill_config())
            logger.info("✅ 知识库服务初始化成功")
        except Exception as e:
            logger.error(f"知识库服务初始化失败: {e}")

    def _load_skill_config(self) -> Optional[Dict]:
        """知识库问答技能的完整配置装配（返回 None 表示不传，技能自行用内置默认值）

        首选 .llm.config_loader.load_skill_config()：它把「场景级检索/生成参数」
        （qa_top_k / qa_max_per_doc / qa_max_context_chunks / filter_overfetch /
        qa_temperature / qa_enable_thinking）与「模型级参数」（max_tokens /
        enable_thinking）一次装配好，且与 src/knowledge/skills/* 链路同源。
        该模块不在时（如现场只同步了入库链路那批改动）回落到内置读取 ——
        读的是同一份 config，只是少了 qa_temperature / enable_thinking 的下发。
        """
        try:
            from .llm.config_loader import load_skill_config
            return load_skill_config()
        except Exception as e:
            logger.warning(f"未使用 .llm.config_loader 装配问答配置（{e}），改用内置读取")

        cc = self._chunk_config()
        if not cc:
            logger.warning("读取知识库运行参数失败（技能将用内置默认值）")
        cfg: Dict = {
            "top_k": cc.get("qa_top_k", 5),
            "max_per_doc": cc.get("qa_max_per_doc", 2),
            "max_context_chunks": cc.get("qa_max_context_chunks", 5),
            "filter_overfetch": cc.get("filter_overfetch", 6),
        }

        llm_config = self._load_llm_config()
        if llm_config:
            cfg["llm"] = llm_config
        return cfg or None

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

    @staticmethod
    def _diagnose_images(loader) -> str:
        """无有效文本时，若文档含图片则补充图片/OCR 情况说明；否则返回空串

        目的：把"上传失败"从笼统一句话，变成能直接指导下一步的提示——
        到底是没装 OCR、OCR 认不出、还是图片太小被跳过。
        """
        try:
            n = int(getattr(loader, "last_image_count", 0) or 0)
        except Exception:
            n = 0
        if n <= 0:
            return ""

        try:
            from .ocr.engine import get_ocr_engine
            available = get_ocr_engine().is_available()
        except Exception:
            available = False

        # ★ 批次 19 起：图片不再"转成文字进正文"，而是原图落盘、前端渲染。
        #   所以走到这里（切片仍为空）意味着连图片块都没产出 —— 只可能是图不可显示
        #   （EMF/WMF 等矢量图，见 document_loader._servable_ext）或 ocr.enabled=false。
        stored = len(getattr(loader, "last_images", None) or [])
        if stored:
            return (f"；该文档含 {n} 张图片，其中 {stored} 张已入库为图片切片，"
                    f"但未切出文本片段，请在切片接口查看 images 字段")

        if not available:
            # 注意：2026-09-11 起 ocr.enabled 默认 false，所以「引擎不可用」是常态，
            # 不再等于依赖没装 —— 提示里两种可能都写出来，免得现场白装一遍依赖。
            return (f"；该文档含 {n} 张图片，但都不是浏览器可显示的格式"
                    f"（如 WMF/EMF 矢量图）—— 这类图无法作为图片切片入库。"
                    f"OCR 当前未启用或不可用（默认关闭，可设 "
                    f"knowledge.ocr.enabled: true 或 KNOWLEDGE_OCR_ENABLED=true 开回）")
        if int(getattr(loader, "last_ocr_count", 0) or 0) == 0:
            return (f"；该文档含 {n} 张图片，但都不是浏览器可显示的格式"
                    f"（如 WMF/EMF 矢量图），无法作为图片切片入库；"
                    f"OCR 也未识别出有效文字，请确认图片是否清晰、确含文字"
                    f"（过小的图标会被跳过）")
        return (f"；该文档含 {n} 张图片，均不可作为图片切片入库，OCR 也仅提取到 "
                f"{int(getattr(loader, 'last_ocr_chars', 0) or 0)} 字符，仍不足切片下限")

    def _store_images(self, doc_id: str, loader) -> Dict[str, Dict]:
        """图片落盘 + 构造占位块映射（实现见 document_repo.store_document_images，
        与 scripts/ 下两条入库通路共用同一份逻辑，避免三处漂移）"""
        from .storage.document_repo import store_document_images
        return store_document_images(
            self.repo, doc_id, getattr(loader, "last_images", None) or []
        )

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
                    "文档解析后无有效文本内容（可能为扫描件/纯图片文档、或格式不支持）"
                    + self._diagnose_images(loader)
                )

            # 2.2 落盘解析文本（便于排查切片/召回问题；失败不影响主流程）
            try:
                text_path = self.repo.get_processed_text_path(doc_info.doc_id)
                with open(text_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                logger.warning(f"解析文本落盘失败（忽略）: {e}")

            # 2.3 图片落盘 + 占位块映射（正文里是【图片：NNN.ext】，原图存
            #     knowledge_base/media/{doc_id}/，前端经 /knowledge/media/... 取图）
            image_map = self._store_images(doc_info.doc_id, loader)

            # 3. 切片（参数来自 config/gateway.yaml 的 knowledge 段，多现场可覆盖；
            #    默认与 bge-small-zh-v1.5 的 512 token 窗口对齐）
            cc = self._chunk_config()
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
            chunks = processor.process_document(content, metadata, image_map)

            if not chunks:
                self.repo.update_status(doc_info.doc_id, "failed", chunk_count=0)
                raise ValueError(
                    f"未生成有效切片（解析出 {len(content.strip())} 字符，"
                    f"不足切片下限 {processor.min_chunk_size}）"
                    + self._diagnose_images(loader)
                )

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
                f"入库图片={len(image_map)} | "
                f"OCR={loader.last_ocr_count}处/{loader.last_ocr_chars}字符 | "
                f"doc_id={doc_info.doc_id}"
            )

            return {
                "status": "success",
                "doc_id": doc_info.doc_id,
                "title": doc_info.title,
                "chunk_count": len(chunks),
                "image_count": loader.last_image_count,
                # 批次 19 新增：真正落盘、可在切片里展示的图片数（<= image_count，
                # 差额是 EMF/WMF 这类不可显示格式或落盘失败的）
                "image_media_count": len(image_map),
                # 纯新增字段：前端可选用，用于展示"图内文字是否进了检索"
                "ocr_count": loader.last_ocr_count,
                "ocr_chars": loader.last_ocr_chars,
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
            result = self.skill.retrieve(query, top_k=self._fetch_k(top_k, category))

            if result["status"] == "error":
                logger.warning(f"[KB/search] 检索失败: {result.get('message')}")
                return result

            # 按分类过滤（超采后过滤，截断回 top_k）
            sources = self._filter_by_category(
                result.get("sources", []) or [], category, top_k
            )

            # 图片「邻近带出」：图片片不进索引，靠命中片附近的图挂上来
            self._attach_images(sources)

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
                        "doc_id": s.get("metadata", {}).get("doc_id", ""),
                        # 图片片：命中证据 content 仍是图内文字（上面那行），
                        # 但前端要展示的是原图 —— 给出可渲染的 URL 列表（批次 19）。
                        # 文本片该键为空数组，前端统一按空数组处理即可。
                        "images": s.get("metadata", {}).get("images", []) or []
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
    def _chunk_config() -> Dict:
        """知识库运行参数读取入口（延迟导入，避免启动期依赖 sys.path 顺序）

        两种导入形态都试（项目里并存）：服务进程与 scripts/knowledge_api.py 会同时把
        「项目根/src」塞进 sys.path，用 config.*；install.sh 自检、部分独立脚本
        （rebuild_knowledge_chunks.py / import_knowledge.py）只塞项目根，那就要走
        src.config.*。**少试一种会在那些入口静默退回内置默认值** —— 值恰好相同，
        所以不报错，只是现场在 gateway.yaml 里的覆盖不生效。
        """
        for mod_name in ("config.port_loader", "src.config.port_loader"):
            try:
                mod = __import__(mod_name, fromlist=["knowledge_chunk_config"])
                return mod.knowledge_chunk_config() or {}
            except Exception:
                continue
        return {}

    @classmethod
    def _filter_overfetch(cls) -> int:
        """分类过滤时的超采倍数（config/gateway.yaml 的 knowledge.filter_overfetch，默认 6）"""
        return max(1, int(cls._chunk_config().get("filter_overfetch", 6)))

    def _fetch_k(self, top_k: int, category: str = None) -> int:
        """召回条数：有分类过滤时先超采（FAISS 无原生元数据过滤，search/chat 共用）"""
        return top_k * self._filter_overfetch() if category else top_k

    @staticmethod
    def _filter_by_category(sources: List[Dict], category: str, top_k: int) -> List[Dict]:
        """按分类过滤并截断回 top_k；无 category 时原样返回（search/chat 共用）"""
        if not category:
            return sources
        return [
            s for s in sources
            if s.get("metadata", {}).get("category") == category
        ][:top_k]

    def _attach_images(self, sources) -> None:
        """把命中片附近的图片挂到结果上（就地修改；失败绝不影响检索）

        调用方是 search() 与 chat()，两处共用同一实现。
        """
        if not sources:
            return
        try:
            from .core.neighbors import attach_neighbor_images
            radius = int(self._chunk_config().get("image_neighbor_radius", 1))
            attached = attach_neighbor_images(self.repo, sources, radius)
            if attached:
                logger.debug(f"[KB/邻近带图] 附带图片 {attached} 张（radius={radius}）")
        except Exception as e:
            logger.debug(f"[KB/邻近带图] 跳过（不影响检索）: {e}")

    def chat(self, question: str, top_k: int = 5, category: str = None) -> Dict:
        """问答对话（支持按分类过滤）"""
        if not self.skill:
            return {"status": "error", "message": "知识库未初始化"}

        logger.info(f"[KB/chat] 入参 question={question!r} top_k={top_k} category={category}")
        _t0 = time.time()
        try:
            # ★ 同 search：有 category 时先超采再过滤，避免过滤后来源不足
            result = self.skill.execute(
                question, top_k=self._fetch_k(top_k, category), need_llm=True
            )

            if result["status"] == "error":
                logger.warning(f"[KB/chat] 问答失败: {result.get('message')}")
                return result

            # 按分类过滤来源（超采后过滤，截断回 top_k）
            sources = self._filter_by_category(
                result.get("sources", []) or [], category, top_k
            )

            # 图片「邻近带出」（与 search 同一套；问答侧供 sources[].metadata.images）
            self._attach_images(sources)

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
                # 展示接口不带"检索位"：图片片的 metadata["content"] 是整段图内文字，
                # 原样透传会把用户明确要求移出正文的破碎 OCR 换个 key 又送回去，
                # 响应体还会翻倍。改为长度计数，前端要看图请用 metadata["images"]。
                # （切片**文件**里那份不剥 —— 重建索引要靠它。）
                meta = dict(chunk.get("metadata", {}) or {})
                if "content" in meta:
                    meta["content_chars"] = len(meta.pop("content") or "")
                formatted_chunks.append({
                    "index": idx,
                    "id": chunk.get("id", ""),
                    "content": chunk.get("content", ""),
                    "metadata": meta
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
            from .core.document_processor import filter_indexable
            import numpy as np
            
            def rebuild():
                try:
                    all_chunks = []
                    for doc_id, doc_info in self.repo.documents.items():
                        if doc_info.status in ["pending", "processing", "processed", "indexed"]:
                            chunks_path = self.repo.get_chunks_path(doc_id)
                            if chunks_path.exists():
                                with open(chunks_path, 'r', encoding='utf-8') as f:
                                    # 图片片不进索引（无检索内容，靠检索后邻近带出）
                                    chunks = filter_indexable(json.load(f))
                                    for chunk in chunks:
                                        chunk["metadata"]["title"] = doc_info.title
                                    all_chunks.extend(chunks)

                    if not all_chunks:
                        logger.warning("⚠️ 索引重建跳过：无有效切片")
                        return

                    embedder = get_local_embedder()
                    # 嵌入统一取「检索位」metadata["content"]
                    # （图片片已被 filter_indexable 剔除，它们不进索引）
                    contents = [
                        (c.get("metadata") or {}).get("content") or c["content"]
                        for c in all_chunks
                    ]
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
