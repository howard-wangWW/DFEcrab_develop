# src/knowledge/core/document_processor.py
"""
文档切片处理器（结构感知）

切分策略（参考 LlamaIndex SentenceSplitter / LangChain RecursiveCharacterTextSplitter）
--------------------------------------------------------------------------------------
1. 按空行分段（加载器统一以 \\n\\n 分隔段落/块，契约一致）
2. **跨段落聚合**：普通段落累积到 chunk_size 再成片（避免短段落各自成片、切片过碎）
3. 表格块（多行以 " | " 分隔）单独处理：表头继承 + 每 N 行一片
4. 普通段落聚合到 chunk_size；超长内容先按句子切（**保留原标点**），再按长度硬切
5. 相邻切片带 overlap（文本分支生效；表格分支与图片分支本就独立成片，不参与 overlap）
6. 问答体（可选）：片尾悬空问句与下一片合并，降低"问/答被拆到两片"的概率
7. chunk_id = md5(doc_id + 序号 + 内容)，避免重复内容撞 ID

说明：metadata["content"] 会保留——向量库只持久化 metadata，检索侧
（retriever._build_text_cache）依赖该字段取正文，属存储契约而非冗余。

图片片（2026-09-11 批次 19）：加载器把内嵌图片登记落盘后，正文里只留
`【图片：NNN.ext】` 占位块。这类块独立成片、不参与聚合/overlap/QA 合并，
metadata["images"] 带上 {name, url} 供前端渲染。

★ 图片片的检索位**留空**（2026-09-11 改）：图片片不进向量库、不进 BM25 语料，
  只能由「同文档内邻近的正文片被命中后附带」被带出（src/knowledge/core/neighbors.py）。
  原因：界面截图类图片的文字与上下文无关，OCR 按检测框输出的破碎文本命中率低、
  噪声大。判据统一走 is_image_chunk()。
"""
import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class DocumentChunk:
    """文档切片"""
    id: str
    content: str
    metadata: Dict
    embedding: Optional[List[float]] = None


def is_image_chunk(meta: Dict) -> bool:
    """判定一条切片的 metadata 是否属于图片片（= 带 images 字段）

    图片片**不进索引**（见 DocumentProcessor._image_chunk_meta 与
    src/knowledge/core/neighbors.py），索引构建 / 嵌入 / 检索后处理各处
    统一走这一个判据，避免各写一遍导致口径漂移。
    """
    if not meta:
        return False
    try:
        return bool(meta.get("images"))
    except AttributeError:
        return False


def filter_indexable(chunks: List[dict]) -> List[dict]:
    """从「切片 dict 列表」里剔掉图片片 —— 索引 / 嵌入各点统一走这里

    图片片的检索位是空串（见 _image_chunk_meta），进索引只会白白占向量空间；
    它们靠 neighbors.attach_neighbor_images 在检索后作为附件带出。

    ★ ids 与 texts 必须**同步过滤**（先过滤 chunks 再各自取值），
    否则向量与 chunk_id 会整体错位，检索结果张冠李戴。
    """
    return [c for c in (chunks or []) if not is_image_chunk((c or {}).get("metadata"))]


class DocumentProcessor:
    """文档切片处理器（结构感知 + 跨段落聚合 + overlap 贯穿）"""

    # 句末标点后切开（后视断言，保留标点）
    _SENTENCE_SPLIT_RE = re.compile(r'(?<=[。！？；!?;])')

    # 图片占位块——整块即占位（加载器生成，形如「【图片：001.png】」）。
    # 用 fullmatch 精确匹配整块，正文里恰好写成同形的文字才会误伤（不靠子串匹配）。
    # 注意：占位块内不含空格/控制字符，因为加载器的 _clean_text 会压缩空白与控制符。
    _IMAGE_BLOCK_RE = re.compile(r'【图片：([^】\s]+)】')

    def __init__(self, chunk_size: int = 500, overlap: int = 50,
                 min_chunk_size: int = 50, table_rows_per_chunk: int = 20,
                 qa_pair_keep: bool = True):
        self.chunk_size = max(100, int(chunk_size))
        self.overlap = max(0, min(int(overlap), self.chunk_size // 2))
        self.min_chunk_size = max(1, int(min_chunk_size))
        self.table_rows_per_chunk = max(1, int(table_rows_per_chunk))
        self.qa_pair_keep = bool(qa_pair_keep)

    # ────────────────────────────── 主入口 ──────────────────────────────

    def process_document(self, content: str, metadata: Dict = None,
                         image_map: Dict[str, Dict] = None) -> List[DocumentChunk]:
        """处理文档，生成切片列表

        Args:
            image_map: 占位块文件名 → {"ocr_text": 图内文字, "url": 取图地址}。
                由调用方（knowledge_service.upload_document）从 loader.last_images 构造。
                不传时行为与改造前完全一致——scripts/ 下的旧调用点不受影响。
        """
        metadata = metadata or {}
        image_map = image_map or {}
        blocks = self._split_blocks(content)

        # ★ 图片块必须参与"这篇文档算不算空"的判断：纯图文档的正文只有
        #   【图片：001.png】十几个字符，按老逻辑会被下面这行判死、直接返回空切片，
        #   上传报 400「未生成有效切片」——那正是本批要修的症状。
        has_image = any(self._IMAGE_BLOCK_RE.fullmatch(b) for b in blocks)
        if not has_image and (not content or len(content.strip()) < self.min_chunk_size):
            return []

        texts: List[str] = []
        # 占位块文本 → 该图片片独有的 metadata 增量（images / 检索位 content）
        image_meta: Dict[str, Dict] = {}

        # 普通段落先累积，遇到表格块再统一切分——保证短段落能合并成完整语义片
        para_buffer: List[str] = []
        for block in blocks:
            m = self._IMAGE_BLOCK_RE.fullmatch(block)
            if m:
                # 图片块独立成片：先 flush 段落缓冲（与表格分支同构），再把占位块
                # 直接放进 texts —— 不经过 _split_paragraph，因而不会被累积聚合、
                # 不会被 overlap 尾巴污染、也不会被 chunk_size 截断。
                if para_buffer:
                    texts.extend(self._split_paragraph("\n".join(para_buffer)))
                    para_buffer = []
                texts.append(block)
                image_meta[block] = self._image_chunk_meta(m.group(1), metadata, image_map)
                continue

            if self._is_table_block(block):
                if para_buffer:
                    texts.extend(self._split_paragraph("\n".join(para_buffer)))
                    para_buffer = []
                texts.extend(self._split_table(block))
            else:
                para_buffer.append(block)
        if para_buffer:
            texts.extend(self._split_paragraph("\n".join(para_buffer)))

        if self.qa_pair_keep:
            texts = self._merge_qa_pairs(texts, image_meta)

        # 去重（完全相同内容只保留一次）+ 生成切片（以去重后序号生成稳定 ID）
        chunks: List[DocumentChunk] = []
        seen = set()
        for text in texts:
            text = text.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            chunks.append(self._create_chunk(text, metadata, len(chunks),
                                             image_meta.get(text)))
        return chunks

    @staticmethod
    def _image_chunk_meta(name: str, metadata: Dict, image_map: Dict[str, Dict]) -> Dict:
        """构造图片片的 metadata 增量：images（展示）+ 空检索位

        ★ 检索位**刻意留空**（2026-09-11 起）：图片片不进向量库、不进 BM25 语料，
        只能由「同文档内邻近的正文片被搜到后附带」（src/knowledge/core/neighbors.py）。
        原因：界面截图 / SCADA 系统图里大部分文字与上下文无关，OCR 按检测框输出的
        破碎文本命中率低、噪声大，不如不做。

        必须是**显式**空串：_create_chunk 的 setdefault("content", content) 会把
        占位块「【图片：001.png】」当成检索文本嵌进去，等于图片反过来能被占位块文本搜到。
        """
        info = image_map.get(name) or {}
        doc_id = metadata.get("doc_id", "")
        # 相对路径，不能是绝对 URL —— 网关与前端可能在不同机器上
        url = info.get("url") or f"/knowledge/media/{doc_id}/{name}"
        return {"images": [{"name": name, "url": url}], "content": ""}

    # 模块级判据的类内别名：已有 DocumentProcessor 引用的调用点可直接用
    is_image_chunk = staticmethod(is_image_chunk)

    # ────────────────────────── 分段 / 表格 / 段落 ──────────────────────────

    @staticmethod
    def _split_blocks(content: str) -> List[str]:
        """按空行分段（加载器契约：段落/块之间以 \\n\\n 分隔）"""
        return [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]

    @staticmethod
    def _is_table_block(block: str) -> bool:
        """判定是否为表格块（多数行含 " | " 分隔符）"""
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            return False
        pipe_lines = sum(1 for l in lines if " | " in l)
        return pipe_lines >= max(2, int(len(lines) * 0.6))

    def _split_table(self, block: str) -> List[str]:
        """表格块切分：表头继承（表头 = 首个含 " | " 的行），每 N 行一片。

        - 表头之前的行（如 "## Sheet: xxx"、标题说明行）作为上下文前缀，随每片重复；
        - 数据行严格带着列名表头，避免后续片丢失表头语义。
        """
        lines = [l.rstrip() for l in block.splitlines() if l.strip()]
        if not lines:
            return []

        header_idx = next((i for i, l in enumerate(lines) if " | " in l), 0)
        prefix = "\n".join(lines[:header_idx])
        header = lines[header_idx]
        body = lines[header_idx + 1:]
        head_line = f"{prefix}\n{header}" if prefix else header

        if not body:
            return [head_line]

        chunks = []
        for i in range(0, len(body), self.table_rows_per_chunk):
            batch = body[i:i + self.table_rows_per_chunk]
            chunks.append("\n".join([head_line] + batch))
        return chunks

    def _split_paragraph(self, text: str) -> List[str]:
        """段落文本 → 若干 ≤ chunk_size 的片（句子优先，超长硬切，带 overlap）"""
        chunks: List[str] = []
        current = ""
        for unit in self._iter_sentences(text):
            if len(unit) > self.chunk_size:
                # 单句超长：先落盘已累积内容，再对该句硬切
                if current.strip():
                    chunks.append(current.strip())
                    current = ""
                chunks.extend(self._hard_split(unit))
                continue
            if current and len(current) + len(unit) + 1 > self.chunk_size:
                chunks.append(current.strip())
                current = self._overlap_tail(current) + unit + "\n"
            else:
                current += unit + "\n"
        if current.strip():
            chunks.append(current.strip())
        return chunks

    def _iter_sentences(self, text: str) -> List[str]:
        """按句子切分并**保留原标点**（不再统一补句号）"""
        units = [s.strip() for s in self._SENTENCE_SPLIT_RE.split(text) if s.strip()]
        return units or ([text.strip()] if text.strip() else [])

    def _hard_split(self, text: str) -> List[str]:
        """超长单句 → 按 chunk_size 硬切（带 overlap）"""
        step = max(1, self.chunk_size - self.overlap)
        return [text[i:i + self.chunk_size] for i in range(0, len(text), step)]

    def _overlap_tail(self, text: str) -> str:
        """取与下一片重叠的尾部（对齐句子开头，避免从半句开始）"""
        if self.overlap <= 0:
            return ""
        if len(text) <= self.overlap:
            return text
        tail = text[-self.overlap:]
        for sep in ("。", "！", "？", "；", "!", "?", ";", "\n"):
            pos = tail.find(sep)
            if pos != -1 and pos < len(tail) - 1:
                return tail[pos + 1:]
        return tail

    # ────────────────────────────── 问答对保持 ──────────────────────────────

    def _merge_qa_pairs(self, texts: List[str],
                        image_meta: Dict[str, Dict] = None) -> List[str]:
        """若某片**片尾是悬空问句**（答案大概率在下一片），与下一片合并。

        聚合切片后，问答多数已在同一片内；此处仅作边界兜底，避免过度合并。

        ★ 图片片是**合并屏障**：qa_pair_keep 默认开着，而培训/问答手册正是图片密集
        的语料。不排除的话，问句在图片片之前时会把图片片粘走，占位块不再独立成片，
        `image_meta.get(text)` 落空 —— 图内文字既不在正文也不在检索位，**静默消失**。
        """
        image_meta = image_meta or {}
        merged: List[str] = []
        limit = int(self.chunk_size * 1.8)
        i = 0
        while i < len(texts):
            cur = texts[i]
            if (i + 1 < len(texts) and self._looks_like_question(cur)
                    and cur not in image_meta and texts[i + 1] not in image_meta):
                nxt = texts[i + 1]
                if len(cur) + len(nxt) + 1 <= limit:
                    merged.append(cur + "\n" + nxt)
                    i += 2
                    continue
            merged.append(cur)
            i += 1
        return merged

    def _looks_like_question(self, text: str) -> bool:
        """判定是否为「悬空问句」（片尾以问号结尾）。"""
        t = text.strip()
        return t.endswith(("？", "?"))

    # ────────────────────────────── 切片对象 ──────────────────────────────

    def _create_chunk(self, content: str, metadata: Dict, index: int,
                      extra_meta: Dict = None) -> DocumentChunk:
        content = content.strip()
        doc_id = metadata.get("doc_id", "")
        # ★ 修复：原为 md5(content) 纯内容哈希，重复内容（表格重复行、模板段落）会撞 ID；
        #   现加入 doc_id + 序号，保证唯一。
        chunk_id = hashlib.md5(
            f"{doc_id}#{index}#{content}".encode("utf-8")
        ).hexdigest()[:16]

        metadata_copy = dict(metadata)
        if extra_meta:
            metadata_copy.update(extra_meta)
        # 存储契约：向量库只存 metadata，检索侧（retriever._build_text_cache 等）据此取正文。
        # 普通片两层 content 相同；图片片顶层是占位块（展示位），而这里被 extra_meta
        # 覆盖成图内文字（检索位）——正是靠这一处分叉实现「图能看、字能搜」。
        metadata_copy.setdefault("content", content)

        return DocumentChunk(id=chunk_id, content=content, metadata=metadata_copy)
