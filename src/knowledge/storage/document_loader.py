# src/knowledge/storage/document_loader.py
"""
文档加载器

docx 解析覆盖范围：
- 正文段落 / 表格（递归嵌套、合并单元格去重）/ 文本框（w:txbxContent）/ 页眉页脚
- 页脚页眉中的页码（"第 X 页 共 Y 页"）会被过滤，避免污染切片
图片仅计数不入库（日志提示，后续可接 OCR）。

标题识别（供上传时自动命名，结果记录在 self.last_title）：
- docx：优先 Heading 1 / Title 样式（兼容 WPS 中文样式名）
- pdf ：优先文档元数据 title（过滤 untitled 等占位符）
- md  ：首个一级标题（# xxx）
- 其余（txt / xlsx / xls / csv / doc）：不提取，由调用方回退文件名

注意：不盲目取"首个段落"当标题——公文/教材常以「四、简答题」等章节名开头，
误当标题反而更差；只有明确的一级标题样式才采纳。
"""
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from ..paths import SUPPORTED_EXTENSIONS
from .xlsx_loader import (
    extract_xlsx_text, extract_xls_text, extract_csv_text, decode_text_bytes,
)

logger = logging.getLogger(__name__)

# 页码形如「第 22 页」「第 22 页 共 22 页」
_PAGE_NUM_RE = re.compile(r'^第\s*\d+\s*页(\s*共\s*\d+\s*页)?$')


class DocumentLoader:
    """支持多种格式的文档加载器"""

    def __init__(self):
        # 白名单统一来自 paths.SUPPORTED_EXTENSIONS（单一事实源，避免与 document_repo 漂移）
        self.supported_extensions = set(SUPPORTED_EXTENSIONS)
        # 最近一次解析统计 / 候选标题（供调用方记录与标题回填）
        self.last_image_count = 0
        self.last_title: Optional[str] = None

    def load_document(self, file_path: str) -> str:
        """加载文档内容，返回纯文本"""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = file_path.suffix.lower()
        if ext not in self.supported_extensions:
            raise ValueError(f"不支持的文件格式: {ext}，支持: {self.supported_extensions}")

        loaders = {
            '.txt': self._load_text,
            '.md': self._load_text,
            '.pdf': self._load_pdf,
            '.docx': self._load_docx,
            '.doc': self._load_doc,
            '.xlsx': self._load_xlsx,
            '.xls': self._load_xls,
            '.csv': self._load_csv,
        }

        self.last_image_count = 0   # 每次解析前重置统计
        self.last_title = None      # 每次解析前重置候选标题

        try:
            content = loaders[ext](file_path)
            # 清理文本
            content = self._clean_text(content)
            logger.info(
                f"📄 加载文档: {file_path.name}, 长度: {len(content)} 字符, "
                f"图片: {self.last_image_count} 张, 候选标题: {self.last_title or '-'}"
            )
            return content
        except Exception as e:
            raise RuntimeError(f"加载文档失败 {file_path}: {str(e)}")

    def _load_text(self, file_path: Path) -> str:
        """加载文本文件（统一编码探测；.md 顺带提取首个一级标题作为候选标题）"""
        text = decode_text_bytes(file_path.read_bytes())
        if file_path.suffix.lower() == '.md':
            self.last_title = self._extract_md_title(text)
        return text

    @staticmethod
    def _extract_md_title(text: str) -> Optional[str]:
        """从 Markdown 提取首个一级标题（# xxx）"""
        for line in text.splitlines()[:50]:
            s = line.strip()
            if s.startswith('# '):
                title = s[2:].strip()
                if title:
                    return title
        return None

    def _load_pdf(self, file_path: Path) -> str:
        """加载PDF文件（顺带尝试读取文档元数据标题）"""
        try:
            # pymupdf>=1.24 推荐新导入名；旧名 fitz 已弃用（1.28 起警告，未来版本会移除）
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz  # 兼容旧版 PyMuPDF
            doc = fitz.open(file_path)
            self._capture_pdf_title(doc.metadata or {})
            text = [page.get_text() for page in doc]
            # 页间以空行分隔，便于切片器分段（页内换行保持不变）
            return '\n\n'.join(text)
        except ImportError:
            pass

        try:
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                meta = getattr(reader, "metadata", None)
                self._capture_pdf_title({"title": (getattr(meta, "title", "") or "") if meta else ""})
                text = []
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text.append(page_text)
                # 页间以空行分隔，便于切片器分段（页内换行保持不变）
                return '\n\n'.join(text)
        except ImportError:
            raise ImportError("请安装 pymupdf 或 PyPDF2: pip install pymupdf")

    def _capture_pdf_title(self, metadata: dict) -> None:
        """从 PDF 元数据提取候选标题（过滤空值 / 占位符 / 过长噪声）"""
        try:
            title = str((metadata or {}).get("title") or "").strip()
        except Exception:
            return
        if not title or len(title) > 100:
            return
        if title.lower() in ("untitled", "无标题", "microsoft word", "doc1"):
            return
        self.last_title = title

    def _load_docx(self, file_path: Path) -> str:
        """加载DOCX文件（深度解析：段落 + 嵌套表格 + 文本框 + 页眉页脚 + 图片计数）"""
        try:
            from docx import Document
            from docx.oxml.ns import qn

            doc = Document(file_path)
            parts: List[str] = []

            def _table_text(tbl) -> str:
                """递归提取表格文本（含单元格内段落、嵌套表格；合并单元格去重）"""
                lines = []
                for row in tbl.rows:
                    row_cells = []
                    seen = set()
                    for cell in row.cells:
                        tc = cell._tc
                        if id(tc) in seen:  # 跨行合并单元格去重，避免重复拼接
                            continue
                        seen.add(id(tc))
                        cell_lines = []
                        for p in cell.paragraphs:
                            if p.text.strip():
                                cell_lines.append(p.text.strip())
                        for nested in cell.tables:
                            nested_txt = _table_text(nested)
                            if nested_txt:
                                cell_lines.append(nested_txt)
                        if cell_lines:
                            row_cells.append("；".join(cell_lines))
                    if row_cells:
                        lines.append(" | ".join(row_cells))
                return "\n".join(lines)

            def _container_text(container) -> str:
                """提取某容器（如文本框 w:txbxContent）下全部段落文字"""
                texts = []
                for p in container.iter(qn("w:p")):
                    t = "".join(node.text or "" for node in p.iter(qn("w:t")))
                    if t.strip():
                        texts.append(t.strip())
                return "\n".join(texts)

            # 0. 候选标题：仅采纳明确的一级标题 / Title 样式（兼容 WPS 中文样式名）
            for para in doc.paragraphs[:30]:
                text = (para.text or "").strip()
                if not text:
                    continue
                try:
                    style = (para.style.name or "") if para.style else ""
                except Exception:
                    style = ""
                if style == "Title" or style.startswith(("Heading 1", "标题 1", "标题1")):
                    self.last_title = text
                    break

            # 1. 正文顶层段落
            for para in doc.paragraphs:
                if para.text.strip():
                    parts.append(para.text.strip())

            # 2. 顶层表格（递归处理嵌套表格）
            for tbl in doc.tables:
                t = _table_text(tbl)
                if t:
                    parts.append(t)

            # 3. 文本框及其它正文 XML 中的游离段落
            #    docx 里正文可能包含文本框(w:txbxContent)；python-docx 的 paragraphs
            #    只暴露顶层段落，文本框内文字必须从 XML 提取。
            for txbx in doc.element.body.iter(qn("w:txbxContent")):
                t = _container_text(txbx)
                if t:
                    parts.append(t)

            # 4. 页眉 / 页脚（仅处理显式定义、非继承自前节的）；页码行过滤掉
            for section in doc.sections:
                for hf in (section.header, section.footer):
                    try:
                        if hf.is_linked_to_previous:
                            continue
                        for p in hf.paragraphs:
                            t = p.text.strip()
                            if t and not _PAGE_NUM_RE.match(t):
                                parts.append(t)
                        for tbl in hf.tables:
                            t = _table_text(tbl)
                            if t:
                                parts.append(t)
                    except Exception as e:
                        logger.warning(f"页眉/页脚解析失败(忽略该节): {e}")

            # 5. 图片计数（a:blip 图片引用，覆盖正文/表格/文本框内图片）
            try:
                self.last_image_count = sum(1 for _ in doc.element.body.iter(qn("a:blip")))
            except Exception:
                self.last_image_count = 0

            # ★ 段落契约：以空行分隔，供切片器（_split_blocks 按 \n\n 分段）正确识别段落
            return "\n\n".join(parts)
        except ImportError:
            raise ImportError("请安装 python-docx: pip install python-docx")

    def _load_doc(self, file_path: Path) -> str:
        """加载DOC文件"""
        try:
            result = subprocess.run(
                ['antiword', str(file_path)],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        raise ValueError("DOC文件解析失败，请安装 antiword，或将文件另存为 .docx 后再上传")

    def _load_xlsx(self, file_path: Path) -> str:
        """加载 .xlsx（纯标准库：共享字符串 / 日期还原 / 按列回填）"""
        return extract_xlsx_text(file_path)

    def _load_xls(self, file_path: Path) -> str:
        """加载 .xls（需 xlrd；缺失时抛出明确的安装提示）"""
        return extract_xls_text(file_path)

    def _load_csv(self, file_path: Path) -> str:
        """加载 .csv（标准库 + 编码探测）"""
        return extract_csv_text(file_path)

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()
