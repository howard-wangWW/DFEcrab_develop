# src/knowledge/storage/document_loader.py
"""
文档加载器

docx 解析覆盖范围：
- 正文段落 / 表格（递归嵌套、合并单元格去重）/ 文本框（w:txbxContent）/ 页眉页脚
- 页脚页眉中的页码（"第 X 页 共 Y 页"）会被过滤，避免污染切片
- 图片：正文里只放 `【图片：NNN.ext】` 占位块，原图经 self.last_images 交给调用方落盘，
        由 /knowledge/media/{doc_id}/{name} 提供，前端自行渲染。
        默认**不做 OCR**（ocr.enabled 默认 false，见 config/port_loader.py）——
        界面截图类图片的文字与上下文无关，按检测框输出的破碎文本会把噪声引进检索。
        图片改由「同文档 ±N 片内的正文被搜到后附带」的方式被带出
        （见 src/knowledge/core/neighbors.py）。引擎代码保留，可一键开回。

★ 正文按**文档顺序**输出（2026-09-11）：逐顶层子元素（w:p / w:tbl）就地输出文本与图片，
  图片编号即文档序。此前是「正文段落 → 顶层表格 → 文本框 → 图片」四轮分类遍历，
  图片占位块只能统一堆在文末，与正文的位置关系全丢。

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

# 旧版 VML 图片引用（WPS / 老模板常见）。
# ★ 必须用 Clark 记法而非 qn("v:imagedata")：python-docx 的 nsmap 里没有 v 前缀，
#   qn() 会直接抛 KeyError: 'v'（2026-09-11 实测踩过——该异常被下面的
#   「图片计数/OCR 失败」兜底吞掉，导致图片数恒为 0、OCR 一次都没跑）。
_VML_IMAGEDATA = "{urn:schemas-microsoft-com:vml}imagedata"

# 能直接交给浏览器渲染的图片格式。docx 里还常见 EMF/WMF 矢量图（WPS 贴图、
# 公式、流程图），Pillow 无 libwmf 打不开 —— 这类不登记落盘，否则前端拿到
# 一个必然裂图。它们退回旧的「【图片文字】…」行为，宁可有碎文字也别给裂图。
_SERVABLE_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}

# partname 拿不到后缀时的兜底（少数 WPS 文档的媒体 part 名不含扩展名）
_SERVABLE_BY_CONTENT_TYPE = {
    'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif',
    'image/bmp': '.bmp', 'image/webp': '.webp',
}


class DocumentLoader:
    """支持多种格式的文档加载器"""

    def __init__(self, ocr_config: Optional[dict] = None):
        # 白名单统一来自 paths.SUPPORTED_EXTENSIONS（单一事实源，避免与 document_repo 漂移）
        self.supported_extensions = set(SUPPORTED_EXTENSIONS)
        # 最近一次解析统计 / 候选标题（供调用方记录与标题回填）
        self.last_image_count = 0   # 图片张数（按 rId 去重，含 DrawingML 与旧版 VML）
        self.last_ocr_count = 0     # 本次实际 OCR 成功的图片数 / 页数
        self.last_ocr_chars = 0     # 本次 OCR 提取到的字符数
        # 本次解析出的图片：[{"name": "001.png", "blob": bytes, "ocr_text": str}, ...]
        # 正文里对应的是【图片：001.png】占位块 —— 调用方负责把 blob 落盘并构造
        # 占位块 → {ocr_text, url} 的映射传给切片器（见 knowledge_service.upload_document）
        self.last_images: List[dict] = []
        self.last_title: Optional[str] = None
        # OCR 配置：None 表示按需从 config/gateway.yaml 读取（见 _load_ocr_config）
        self._ocr_config = ocr_config

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

        # 每次解析前重置统计与候选标题
        self.last_image_count = 0
        self.last_ocr_count = 0
        self.last_ocr_chars = 0
        self.last_images = []
        self.last_title = None

        try:
            content = loaders[ext](file_path)
            # 清理文本
            content = self._clean_text(content)
            ocr_note = (
                f"，OCR {self.last_ocr_count} 处 / {self.last_ocr_chars} 字符"
                if self.last_ocr_count else ""
            )
            store_note = (
                f"，入库图片 {len(self.last_images)} 张" if self.last_images else ""
            )
            logger.info(
                f"📄 加载文档: {file_path.name}, 长度: {len(content)} 字符, "
                f"图片: {self.last_image_count} 张{store_note}{ocr_note}, "
                f"候选标题: {self.last_title or '-'}"
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
        """加载PDF文件（顺带尝试读取文档元数据标题）

        文本页直接取文本；某页文本少于 pdf_text_threshold 视为扫描页，
        用 pymupdf 渲染成 PNG 后走 OCR —— 扫描版 PDF 因此也能入库。
        PyPDF2 回退分支无法渲染页面，只保留原文本行为。
        """
        try:
            # pymupdf>=1.24 推荐新导入名；旧名 fitz 已弃用（1.28 起警告，未来版本会移除）
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz  # 兼容旧版 PyMuPDF
            doc = fitz.open(file_path)
            self._capture_pdf_title(doc.metadata or {})
            return self._pdf_text_with_ocr(doc)
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
        """加载DOCX文件（深度解析：段落 + 嵌套表格 + 文本框 + 页眉页脚 + 图片计数/OCR）"""
        try:
            from docx import Document
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph

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

            def _textbox_text(el) -> str:
                """提取 el 内文本框（w:txbxContent）文字；嵌套文本框只取最外层，避免重复"""
                texts = []
                for txbx in el.iter(qn("w:txbxContent")):
                    node, nested = txbx.getparent(), False
                    while node is not None and node is not el:
                        if node.tag == qn("w:txbxContent"):
                            nested = True
                            break
                        node = node.getparent()
                    if nested:
                        continue
                    t = _container_text(txbx)
                    if t:
                        texts.append(t)
                return "\n".join(texts)

            def _iter_blocks(el):
                """按文档顺序产出正文块（w:p / w:tbl），穿透内容控件 w:sdt"""
                for child in el.iterchildren():
                    tag = child.tag
                    if tag in (qn("w:p"), qn("w:tbl")):
                        yield child
                    elif tag == qn("w:sdt"):
                        content = child.find(qn("w:sdtContent"))
                        if content is not None:
                            yield from _iter_blocks(content)

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

            # 1. 正文：按**文档顺序**单次遍历顶层元素，文本与图片就地输出
            #    —— 段落文字 → 该段落内的图片；表格文字 → 该表格内的图片。
            #    图片因此紧跟它所在的段落/表格，编号也自然是文档序。
            cfg = self._load_ocr_config()
            img_ctx = self._new_image_ctx(doc, cfg)
            seen_rids = set()

            for el in _iter_blocks(doc.element.body):
                if el.tag == qn("w:p"):
                    text = (Paragraph(el, doc).text or "").strip()
                    txbx = _textbox_text(el)
                    if txbx:
                        text = f"{text}\n{txbx}" if text else txbx
                    if text:
                        parts.append(text)
                else:  # w:tbl
                    # 表格文字 + 单元格里文本框的文字（_table_text 只看单元格段落，
                    # 不看文本框，漏掉的话表格内文本框的内容整段消失）
                    t = _table_text(Table(el, doc))
                    txbx = _textbox_text(el)
                    if txbx:
                        t = f"{t}\n{txbx}" if t else txbx
                    if t:
                        parts.append(t)
                # 该元素内的图片（含嵌套表格 / 文本框里的）
                for block in self._iter_docx_images(img_ctx, el, qn, seen_rids):
                    parts.append(block)

            self.last_image_count = len(seen_rids)
            self._log_docx_image_stats(img_ctx)

            # 2. 页眉 / 页脚（仅处理显式定义、非继承自前节的）；页码行过滤掉
            #    它们不在正文流里，统一放在正文之后。
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

    # ──────────────────────────────────────────────────────────
    # OCR：图片 / 扫描页文字提取（依赖可选，不可用时静默降级为「仅计数」）
    # ──────────────────────────────────────────────────────────

    def _load_ocr_config(self) -> dict:
        """读取 OCR 配置（config/gateway.yaml 的 knowledge.ocr 段）

        任何异常都退回内置默认值——解析主链路绝不能因为读不到配置而中断。
        """
        if self._ocr_config is not None:
            return self._ocr_config

        cfg = None
        # 两种导入形态都试（项目里并存）：包内导入用 src.config.*，
        # 脚本单独运行时 src 也在 sys.path 上，config.* 同样可用。
        for mod_name in ("src.config.port_loader", "config.port_loader"):
            try:
                mod = __import__(mod_name, fromlist=["knowledge_ocr"])
                cfg = mod.knowledge_ocr()
                break
            except Exception:
                continue

        if cfg is None:
            logger.warning("⚠️ 未能读取 knowledge.ocr 配置，使用内置默认值")
            cfg = {
                "enabled": False, "max_images": 50, "max_pages": 50,
                "min_image_px": 64, "pdf_text_threshold": 20, "dpi": 200,
            }
        self._ocr_config = cfg
        return cfg

    def _get_ocr_engine(self, cfg: dict):
        """按配置取 OCR 引擎；不可用返回 None（不抛异常）"""
        if not cfg.get("enabled", False):
            return None
        try:
            from ..ocr.engine import get_ocr_engine
        except Exception as e:
            logger.warning(f"⚠️ OCR 模块不可用: {e}")
            return None
        engine = get_ocr_engine()
        return engine if engine.is_available() else None

    def _servable_ext(self, part) -> Optional[str]:
        """取「浏览器能直接显示」的图片扩展名；不可显示的格式返回 None"""
        # 优先 partname 的真实后缀（docx 媒体部件形如 /word/media/image1.png）
        try:
            ext = Path(str(part.partname)).suffix.lower()
        except Exception:
            ext = ""
        if ext in _SERVABLE_IMAGE_EXTS:
            return ext
        # 少数 WPS 文档的 part 名不带可用后缀，退回 content_type
        ct = (getattr(part, "content_type", "") or "").lower()
        return _SERVABLE_BY_CONTENT_TYPE.get(ct)

    def _new_image_ctx(self, doc, cfg: dict) -> dict:
        """建一次解析内共用的图片登记上下文（跨段落累计，实现去重与封顶）"""
        try:
            from ..ocr.engine import image_pixel_size
        except Exception:
            image_pixel_size = None

        # 引擎不可用（依赖没装 / enabled=false）时仍然登记原图，只是没有图内文字
        engine = self._get_ocr_engine(cfg)
        if cfg.get("enabled", True) and engine is None:
            logger.warning("⚠️ OCR 引擎不可用：图片将只入库原图，图内文字不进检索")

        return {
            "doc": doc,
            "cfg": cfg,
            "engine": engine,
            "size_fn": image_pixel_size,
            "min_px": cfg["min_image_px"],
            "max_images": cfg["max_images"],
            "done": set(),          # 已处理过的 rId（同一张图常被多处引用）
            "tried": 0,             # 已尝试登记的图片数（上限按 max_images 计）
            "skipped_small": 0,     # 尺寸过小（图标）跳过的张数
            "warned_cap": False,
        }

    def _iter_docx_images(self, ctx: dict, el, qn, seen_rids: set):
        """按**文档顺序**产出 el 内所有图片的占位块

        el 是正文顶层元素（段落或表格），对其做深度优先遍历即为文档序：
        a:blip（DrawingML）与 v:imagedata（旧版 VML，WPS/老模板常见）按出现次序处理。

        seen_rids 累计「出现过的全部 rId」，用于 last_image_count ——
        与改造前 `len({el.get(attr) for ...})` 的口径一致（含被跳过的矢量图/小图）。
        """
        for node in el.iter():
            if node.tag == qn("a:blip"):
                rid = node.get(qn("r:embed"))
            elif node.tag == _VML_IMAGEDATA:
                rid = node.get(qn("r:id"))
            else:
                continue
            if not rid:
                continue
            seen_rids.add(rid)
            try:
                block = self._register_docx_image(ctx, rid)
            except Exception as e:
                # 单张图登记失败不能拖垮整篇解析
                logger.warning(f"图片登记失败（忽略该张）: {e}")
                continue
            if block:
                yield block

    def _register_docx_image(self, ctx: dict, rid: str) -> Optional[str]:
        """登记 docx 内嵌的一张图片，返回正文占位块（跳过时返回 None）

        图片原样落盘（经 self.last_images 交给调用方），由前端渲染。
        图内文字仅在 OCR 开启时附带，走 last_images[].ocr_text 旁路。

        可显示格式才登记；EMF/WMF 等 Pillow 打不开的矢量格式**不登记、不发占位块**，
        否则「正文全是 WMF 流程图」的 WPS 文档会从明确报错退化成
        "上传成功但整篇是空壳"。
        """
        done = ctx["done"]
        if not rid or rid in done:   # 同一张图可能被多处引用，按 rId 去重
            return None
        done.add(rid)

        try:
            part = ctx["doc"].part.related_parts[rid]
            blob = part.blob
        except Exception:
            return None
        if not blob:
            return None

        size_fn, min_px = ctx["size_fn"], ctx["min_px"]
        if size_fn is not None:
            size = size_fn(blob)
            if size and (size[0] < min_px or size[1] < min_px):
                ctx["skipped_small"] += 1
                return None

        ext = self._servable_ext(part)
        if ext is None:
            return None

        max_images = ctx["max_images"]
        if ctx["tried"] >= max_images:
            if not ctx["warned_cap"]:
                ctx["warned_cap"] = True
                logger.warning(
                    f"⚠️ 图片数超过上限 max_images={max_images}，其余图片仅计数不落盘"
                    f"（可改 config/gateway.yaml 的 knowledge.ocr）"
                )
            return None

        ctx["tried"] += 1
        engine = ctx["engine"]
        text = (engine.image_to_text(blob) or "").strip() if engine is not None else ""
        if text:
            self.last_ocr_count += 1
            self.last_ocr_chars += len(text)

        name = f"{len(self.last_images) + 1:03d}{ext}"
        self.last_images.append({"name": name, "blob": blob, "ocr_text": text})
        return f"【图片：{name}】"

    @staticmethod
    def _log_docx_image_stats(ctx: dict) -> None:
        """打印本次解析的图片统计（仅在有跳过时开口，避免刷日志）"""
        if ctx["skipped_small"]:
            logger.info(
                f"   ↳ 跳过 {ctx['skipped_small']} 张过小图片"
                f"（任一边 < {ctx['min_px']}px，视为图标）"
            )

    def _pdf_text_with_ocr(self, doc) -> str:
        """逐页取文本；扫描页（文本过少）渲染后登记为图片，正文放占位块

        扫描页渲染一次、编两份字节：PNG 送 OCR（与改造前完全一致，不动识别率），
        JPEG 落盘给前端看（体积小约一个数量级）。图内文字同样只进检索、不进正文。

        ★ ocr.enabled=false 时**只停 OCR，不停渲染**：扫描件整篇没有文本层，
        不渲染就解析出 0 字符、上传报 400「未生成有效切片」。渲染是毫秒级的
        栅格化，换来扫描件照样能入库、页面图在前端可见。

        页间以空行分隔，与 _load_docx 保持同一段落契约（切片器按 \\n\\n 分段）。
        """
        cfg = self._load_ocr_config()
        # 引擎不可用时仍然渲染落盘（扫描页的图就是内容本身），只是没有图内文字进检索；
        # enabled=false 时 _get_ocr_engine 直接返回 None，同一分支即可覆盖两种情况。
        engine = self._get_ocr_engine(cfg)
        threshold = cfg["pdf_text_threshold"]
        max_pages = cfg["max_pages"]
        ocr_tried, ocr_pages, warned = 0, 0, False
        pages_text: List[str] = []

        for page in doc:
            raw = page.get_text()
            if len(raw.strip()) >= threshold:
                pages_text.append(raw)
                continue

            # 封顶按「尝试次数」而非「成功次数」计：OCR 是 CPU 密集操作，
            # 若整本都是空白扫描页、页页识别不出文字，按成功数计会导致
            # 每一页都被渲染+识别，限额形同虚设。
            if ocr_tried >= max_pages:
                if not warned:
                    logger.warning(
                        f"⚠️ 扫描页数超过 OCR 上限 max_pages={max_pages}，"
                        f"其余页面仅保留原文本（可改 config/gateway.yaml 的 knowledge.ocr）"
                    )
                    warned = True
                pages_text.append(raw)
                continue

            ocr_tried += 1
            text, stored, ext = "", None, ".png"
            try:
                pix = page.get_pixmap(dpi=cfg["dpi"])
                # 落盘用 JPEG：200dpi 的 A4 RGB PNG 约 1.5–3MB/页，
                # max_pages=50 就是上百 MB（而单文件上传上限才 50MB）。JPEG 小约一个数量级。
                try:
                    stored, ext = pix.tobytes("jpeg", jpg_quality=90), ".jpg"
                except Exception:
                    stored, ext = pix.tobytes("png"), ".png"
                if engine is not None:
                    # OCR 输入仍用 PNG，与改造前逐字节一致，不去动识别率。
                    # 引擎不可用（依赖缺失 / enabled=false）时不编 PNG —— 白编一份没人看。
                    text = engine.image_to_text(pix.tobytes("png"))
            except Exception as e:
                logger.warning(f"扫描页渲染/OCR 失败（该页仅保留原文本）: {e}")

            if text:
                text = text.strip()
                ocr_pages += 1
                self.last_ocr_count += 1
                self.last_ocr_chars += len(text)

            # 登记落盘 —— 只有真渲染出来才登记
            block = None
            if stored:
                name = f"{len(self.last_images) + 1:03d}{ext}"
                self.last_images.append({"name": name, "blob": stored, "ocr_text": text})
                block = f"【图片：{name}】"

            head = raw.strip()
            if block:
                # 该页原有文字不能丢：页文本低于阈值只说明它「像扫描页」，
                # 并不代表没有文本层（如仅有标题的页）。占位块**独立成段**（空行分隔）。
                pages_text.append(f"{head}\n\n{block}" if head else block)
            else:
                pages_text.append(raw)

        if ocr_pages:
            logger.info(f"   ↳ 扫描页 OCR: {ocr_pages} 页")
        return '\n\n'.join(pages_text)

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()
