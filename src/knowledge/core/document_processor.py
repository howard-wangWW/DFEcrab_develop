# src/knowledge/core/document_processor.py
"""
文档切片处理器（结构感知）

切分策略（参考 LlamaIndex SentenceSplitter / LangChain RecursiveCharacterTextSplitter）
--------------------------------------------------------------------------------------
1. 按空行分段（加载器统一以 \\n\\n 分隔段落/块，契约一致）
2. **跨段落聚合**：普通段落累积到 chunk_size 再成片（避免短段落各自成片、切片过碎）
3. 表格块（多行以 " | " 分隔）单独处理：表头继承 + 每 N 行一片
4. 普通段落聚合到 chunk_size；超长内容先按句子切（**保留原标点**），再按长度硬切
5. 相邻切片带 overlap（各分支均生效，避免语义断裂）
6. 问答体（可选）：片尾悬空问句与下一片合并，降低"问/答被拆到两片"的概率
7. chunk_id = md5(doc_id + 序号 + 内容)，避免重复内容撞 ID

说明：metadata["content"] 会保留——向量库只持久化 metadata，检索侧
（retriever._build_text_cache）依赖该字段取正文，属存储契约而非冗余。
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


class DocumentProcessor:
    """文档切片处理器（结构感知 + 跨段落聚合 + overlap 贯穿）"""

    # 句末标点后切开（后视断言，保留标点）
    _SENTENCE_SPLIT_RE = re.compile(r'(?<=[。！？；!?;])')

    def __init__(self, chunk_size: int = 500, overlap: int = 50,
                 min_chunk_size: int = 50, table_rows_per_chunk: int = 20,
                 qa_pair_keep: bool = True):
        self.chunk_size = max(100, int(chunk_size))
        self.overlap = max(0, min(int(overlap), self.chunk_size // 2))
        self.min_chunk_size = max(1, int(min_chunk_size))
        self.table_rows_per_chunk = max(1, int(table_rows_per_chunk))
        self.qa_pair_keep = bool(qa_pair_keep)

    # ────────────────────────────── 主入口 ──────────────────────────────

    def process_document(self, content: str, metadata: Dict = None) -> List[DocumentChunk]:
        """处理文档，生成切片列表"""
        if not content or len(content.strip()) < self.min_chunk_size:
            return []

        metadata = metadata or {}
        texts: List[str] = []

        # 普通段落先累积，遇到表格块再统一切分——保证短段落能合并成完整语义片
        para_buffer: List[str] = []
        for block in self._split_blocks(content):
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
            texts = self._merge_qa_pairs(texts)

        # 去重（完全相同内容只保留一次）+ 生成切片（以去重后序号生成稳定 ID）
        chunks: List[DocumentChunk] = []
        seen = set()
        for text in texts:
            text = text.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            chunks.append(self._create_chunk(text, metadata, len(chunks)))
        return chunks

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

    def _merge_qa_pairs(self, texts: List[str]) -> List[str]:
        """若某片**片尾是悬空问句**（答案大概率在下一片），与下一片合并。

        聚合切片后，问答多数已在同一片内；此处仅作边界兜底，避免过度合并。
        """
        merged: List[str] = []
        limit = int(self.chunk_size * 1.8)
        i = 0
        while i < len(texts):
            cur = texts[i]
            if i + 1 < len(texts) and self._looks_like_question(cur):
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

    def _create_chunk(self, content: str, metadata: Dict, index: int) -> DocumentChunk:
        content = content.strip()
        doc_id = metadata.get("doc_id", "")
        # ★ 修复：原为 md5(content) 纯内容哈希，重复内容（表格重复行、模板段落）会撞 ID；
        #   现加入 doc_id + 序号，保证唯一。
        chunk_id = hashlib.md5(
            f"{doc_id}#{index}#{content}".encode("utf-8")
        ).hexdigest()[:16]

        metadata_copy = dict(metadata)
        metadata_copy["content"] = content  # 存储契约：向量库只存 metadata，检索侧据此取正文

        return DocumentChunk(id=chunk_id, content=content, metadata=metadata_copy)
