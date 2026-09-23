"""
PDF 工具技能
"""

from pathlib import Path
from agentscope.service import ServiceToolkit


def rotate_pdf(pdf_path: str, rotation: int, output_path: str = None) -> str:
    """
    旋转 PDF 文件

    Args:
        pdf_path: PDF 文件路径
        rotation: 旋转角度（90, 180, 270）
        output_path: 输出路径（可选）

    Returns:
        操作结果
    """
    import pypdf

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        return f"❌ 文件不存在: {pdf_path}"

    output = Path(output_path) if output_path else pdf_file.parent / f"{pdf_file.stem}_rotated.pdf"

    try:
        reader = pypdf.PdfReader(pdf_path)
        writer = pypdf.PdfWriter()

        for page in reader.pages:
            page.rotate(rotation)
            writer.add_page(page)

        with open(output, "wb") as f:
            writer.write(f)

        return f"✅ PDF 旋转成功: {output}"
    except Exception as e:
        return f"❌ 旋转失败: {e}"


def execute(toolkit=None, **kwargs) -> str:
    """
    PDF 工具执行入口

    支持的参数:
        action: 操作类型（rotate, merge, split）
        input: 输入文件路径
        rotation: 旋转角度（rotate 时使用）
        output: 输出文件路径
    """
    action = kwargs.get("action", "rotate")
    pdf_path = kwargs.get("input")

    if not pdf_path:
        return "❌ 请提供 PDF 文件路径"

    if action == "rotate":
        rotation = kwargs.get("rotation", 90)
        output = kwargs.get("output")
        return rotate_pdf(pdf_path, int(rotation), output)

    return f"❌ 不支持的操作: {action}"
