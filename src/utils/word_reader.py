"""
Word 文档读取工具。
"""

from pathlib import Path
from typing import Dict


def read_word(file_path: str) -> Dict[str, object]:
    """读取 docx 文档并返回标准化结果。"""
    path = Path(file_path)

    if not path.exists():
        return {"success": False, "error": f"文件不存在：{file_path}"}

    if path.suffix.lower() != ".docx":
        return {"success": False, "error": "当前仅支持 .docx 格式"}

    try:
        from docx import Document
    except ImportError:
        return {"success": False, "error": "缺少 python-docx 依赖，无法读取 Word 文档"}

    try:
        document = Document(str(path))
        paragraphs = [p.text.strip() for p in document.paragraphs if p.text and p.text.strip()]
        content = "\n".join(paragraphs)
        return {
            "success": True,
            "title": path.stem,
            "word_count": len(content),
            "content": content,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
