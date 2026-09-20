# src/knowledge/storage/xlsx_loader.py
"""
Excel / CSV 解析（知识库统一入口）

设计目标
--------
- .xlsx：**纯标准库**（zipfile + xml.etree）解析，零第三方依赖（离线内网可部署）。
- .xls ：可选依赖 xlrd（老 BIFF 二进制格式，标准库无法解析；缺失时给出明确安装提示）。
- .csv ：标准库 csv + 多编码探测。

统一输出为可切片的纯文本：

    ## Sheet: <sheet 名>
    <表头行>
    <数据行>
    ...

xlsx 解析必须处理（否则数据会错/丢）
------------------------------------
1. `sharedStrings.xml` 共享字符串（含富文本 `<r><t>` 分段拼接）。
2. 单元格 `r="B3"` 列标 → 按列回填，行内空单元格不丢列（否则整行错位）。
3. 日期：单元格存的是序列号（如 45123），需按 `styles.xml` 的 numFmt 还原为可读日期。
4. 公式：只读缓存值 `<v>`（Excel/WPS 保存时写入），不重算。

注意：仅读「缓存值」，不计算公式；未被 Excel/WPS 保存过缓存的公式单元格可能为空。
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from xml.etree import ElementTree as ET

# OOXML 命名空间
_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# ECMA-376 内置日期/时间格式编号（14-22 日期时间，45-47 时间）
_BUILTIN_DATE_FMT_IDS = set(range(14, 23)) | set(range(45, 48))

# Excel 1900 日期系统纪元（序列号 1 = 1900-01-01；用 1899-12-30 抵消其闰年 bug）
_EXCEL_EPOCH = datetime(1899, 12, 30)

_CELL_REF_RE = re.compile(r"^\$?([A-Za-z]+)\$?\d+$")


# ────────────────────────────── xlsx（纯标准库） ──────────────────────────────

def _col_letters_to_index(letters: str) -> int:
    """列字母 → 0 基索引：A→0，Z→25，AA→26。"""
    idx = 0
    for ch in letters:
        if ch.isalpha():
            idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _iter_t_text(node) -> str:
    """拼接节点下所有 <t> 文本（共享字符串富文本、内联字符串通用）。"""
    return "".join(t.text or "" for t in node.iter(f"{{{_NS_MAIN}}}t"))


def _parse_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    """解析 xl/sharedStrings.xml → 字符串列表（富文本按段拼接）。"""
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [_iter_t_text(si) for si in root.findall(f"{{{_NS_MAIN}}}si")]


def _looks_like_date_format(code: str) -> bool:
    """粗判自定义 numFmt 是否日期/时间格式。"""
    code = re.sub(r"\[[^\]]*\]", "", code)   # 去颜色/条件段
    code = re.sub(r'"[^"]*"', "", code)      # 去字面量
    code = code.replace("\\", "")
    return any(ch in code.lower() for ch in ("y", "m", "d", "h", "s"))


def _parse_date_style_indexes(zf: zipfile.ZipFile) -> set:
    """返回「日期样式」的样式下标集合（对应单元格 s="N" 的 N）。"""
    if "xl/styles.xml" not in zf.namelist():
        return set()
    root = ET.fromstring(zf.read("xl/styles.xml"))

    date_fmt_ids = set(_BUILTIN_DATE_FMT_IDS)
    for numfmt in root.iter(f"{{{_NS_MAIN}}}numFmt"):
        if _looks_like_date_format(numfmt.get("formatCode") or ""):
            try:
                date_fmt_ids.add(int(numfmt.get("numFmtId", "0")))
            except ValueError:
                pass

    style_indexes = set()
    cellxfs = root.find(f"{{{_NS_MAIN}}}cellXfs")
    if cellxfs is not None:
        for i, xf in enumerate(cellxfs.findall(f"{{{_NS_MAIN}}}xf")):
            try:
                if int(xf.get("numFmtId", "0")) in date_fmt_ids:
                    style_indexes.add(i)
            except ValueError:
                continue
    return style_indexes


def _excel_serial_to_text(value: float) -> str:
    """Excel 日期序列号 → 可读日期 / 日期时间。"""
    dt = _EXCEL_EPOCH + timedelta(days=value)
    if dt.hour or dt.minute or dt.second:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d")


def _format_numeric(raw: str, is_date: bool) -> str:
    """数字单元格格式化：日期还原、整数去 .0、浮点保精度。"""
    try:
        num = float(raw)
    except (TypeError, ValueError):
        return raw
    if is_date and num > 0:
        try:
            return _excel_serial_to_text(num)
        except (OverflowError, ValueError):
            return raw
    if num.is_integer():
        return str(int(num))
    return "%g" % num


def _cell_text(cell, shared: Sequence[str], date_style_indexes: set) -> str:
    """单个 <c> 单元格 → 文本。"""
    ctype = cell.get("t")
    v_node = cell.find(f"{{{_NS_MAIN}}}v")

    if ctype == "s":  # 共享字符串
        if v_node is None or v_node.text is None:
            return ""
        try:
            return shared[int(v_node.text)]
        except (ValueError, IndexError):
            return v_node.text
    if ctype == "inlineStr":  # 内联字符串
        is_node = cell.find(f"{{{_NS_MAIN}}}is")
        return _iter_t_text(is_node) if is_node is not None else ""
    if ctype == "b":  # 布尔
        return "TRUE" if (v_node is not None and (v_node.text or "").strip() == "1") else "FALSE"
    if ctype == "e":  # 错误值
        return v_node.text if (v_node is not None and v_node.text) else ""
    if v_node is None or v_node.text is None:
        return ""

    is_date = False
    style_idx = cell.get("s")
    if style_idx is not None:
        try:
            is_date = int(style_idx) in date_style_indexes
        except ValueError:
            is_date = False
    return _format_numeric(v_node.text, is_date)


def _parse_sheet_rows(zf: zipfile.ZipFile, sheet_path: str,
                      shared: Sequence[str], date_style_indexes: set) -> List[List[str]]:
    """解析单个 worksheet XML → 二维文本数组（按列回填，空单元格不丢列）。"""
    root = ET.fromstring(zf.read(sheet_path))
    rows: List[List[str]] = []
    for row in root.iter(f"{{{_NS_MAIN}}}row"):
        cells: Dict[int, str] = {}
        for cell in row.findall(f"{{{_NS_MAIN}}}c"):
            ref = cell.get("r") or ""
            m = _CELL_REF_RE.match(ref)
            if m:
                col = _col_letters_to_index(m.group(1))
            else:
                col = (max(cells) + 1) if cells else 0
            cells[col] = (_cell_text(cell, shared, date_style_indexes) or "").strip()
        if not cells:
            rows.append([])
            continue
        width = max(cells) + 1
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def _sheet_name_path_map(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """从 workbook.xml + rels 解析 [(sheet 名, worksheet xml 路径)]，保持工作表顺序。"""
    if "xl/workbook.xml" not in zf.namelist():
        return []

    rels: Dict[str, str] = {}
    rels_path = "xl/_rels/workbook.xml.rels"
    if rels_path in zf.namelist():
        rel_root = ET.fromstring(zf.read(rels_path))
        for rel in rel_root:
            rels[rel.get("Id") or ""] = rel.get("Target") or ""

    result: List[Tuple[str, str]] = []
    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
    for sheet in wb_root.iter(f"{{{_NS_MAIN}}}sheet"):
        target = rels.get(sheet.get(f"{{{_NS_REL}}}id") or "", "")
        if not target:
            continue
        target = target.lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target.lstrip("./")
        result.append((sheet.get("name") or Path(path).stem, path))
    return result


def extract_xlsx_text(file_path, max_rows_per_sheet: int = 200000) -> str:
    """把 .xlsx 转为「Sheet 名 + 表头 + 数据行」文本（纯标准库）。

    Args:
        file_path: .xlsx 文件路径
        max_rows_per_sheet: 单表行数上限（防御超大表；0 表示不限制）
    """
    path = Path(file_path)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        shared = _parse_shared_strings(zf)
        date_style_indexes = _parse_date_style_indexes(zf)

        sheets = _sheet_name_path_map(zf)
        if not sheets:  # 兜底：无 workbook.xml 时按文件名顺序取
            sheets = [(Path(n).stem, n) for n in sorted(names)
                      if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]

        parts: List[str] = []
        for name, sp in sheets:
            if sp not in names:
                continue
            rows = _parse_sheet_rows(zf, sp, shared, date_style_indexes)
            lines = [f"## Sheet: {name}"]
            emitted = 0
            for row in rows:
                if not any(cell for cell in row):
                    continue  # 跳过完全空行
                lines.append(" | ".join(row).rstrip(" |"))
                emitted += 1
                if max_rows_per_sheet and emitted >= max_rows_per_sheet:
                    lines.append(f"...（本 Sheet 行数超过 {max_rows_per_sheet}，已截断）")
                    break
            if len(lines) > 1:
                parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ────────────────────────────── xls（可选依赖 xlrd） ──────────────────────────────

def _xls_cell_text(cell, book) -> str:
    """xlrd 单元格 → 文本（日期类型还原）。"""
    import xlrd

    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            y, m, d, hh, mm, ss = xlrd.xldate_as_tuple(cell.value, book.datemode)
            if hh or mm or ss:
                return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:{ss:02d}"
            return f"{y:04d}-{m:02d}-{d:02d}"
        except Exception:  # noqa: BLE001
            return str(cell.value)
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        num = float(cell.value)
        return str(int(num)) if num.is_integer() else ("%g" % num)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if cell.value else "FALSE"
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    return (str(cell.value) or "").strip()


def extract_xls_text(file_path) -> str:
    """把 .xls 转为文本。依赖 xlrd（老 BIFF 格式无法用标准库解析）。"""
    try:
        import xlrd
    except ImportError as e:
        raise ImportError(
            "解析 .xls 需要 xlrd（老 BIFF 二进制格式，标准库无法解析）。"
            "离线环境请将 xlrd 的 wheel 放入 wheels/ 后执行 "
            "`pip install --no-index --find-links wheels/ xlrd`，"
            "或把文件另存为 .xlsx / .csv 再上传。"
        ) from e

    book = xlrd.open_workbook(str(file_path))
    parts: List[str] = []
    for sheet in book.sheets():
        lines = [f"## Sheet: {sheet.name}"]
        for r in range(sheet.nrows):
            row_text = [_xls_cell_text(sheet.cell(r, c), book) for c in range(sheet.ncols)]
            if any(v for v in row_text):
                lines.append(" | ".join(row_text).rstrip(" |"))
        if len(lines) > 1:
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ────────────────────────────── csv（标准库） ──────────────────────────────

def decode_text_bytes(raw: bytes) -> str:
    """编码探测：utf-8-sig → utf-8 → gbk → utf-16 → 兜底 replace。

    供文本 / CSV 等按字节读取的场景共用，避免各处重复实现编码探测。
    """
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


def extract_csv_text(file_path) -> str:
    """把 .csv 转为「行内以 ' | ' 分隔」的文本（标准库 + 编码探测）。"""
    raw = Path(file_path).read_bytes()
    text = decode_text_bytes(raw)
    reader = csv.reader(io.StringIO(text))
    lines: List[str] = []
    for row in reader:
        cells = [(c or "").strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells).rstrip(" |"))
    return "\n".join(lines)
