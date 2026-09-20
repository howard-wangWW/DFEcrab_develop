"""
Excel Read - 读取 Excel 文件
使用 openpyxl 读取 Excel 文件内容
"""

import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

SKILL_METADATA = {
    "name": "excel-read",
    "description": "读取 Excel (.xlsx, .xls) 文件内容。当用户要查看 Excel 文件内容时使用。",
    "parameters": {
        "file_path": {
            "type": "string",
            "description": "Excel 文件路径",
            "default": ""
        },
        "sheet_name": {
            "type": "string",
            "description": "工作表名称，默认为第一个工作表",
            "default": ""
        },
        "max_rows": {
            "type": "integer",
            "description": "最大读取行数，默认为 100",
            "default": 100
        }
    }
}


def execute(file_path: str = "", sheet_name: str = "", max_rows: int = 100) -> str:
    """
    读取 Excel 文件内容

    Args:
        file_path: Excel 文件路径
        sheet_name: 工作表名称
        max_rows: 最大读取行数

    Returns:
        ServiceResponse 对象
    """
    from src.agentscope_compat import ServiceResponse, ServiceExecStatus

    if not file_path:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content="请提供 Excel 文件路径，例如: execute(file_path='/path/to/file.xlsx')"
        )

    path = Path(file_path)
    if not path.exists():
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"文件不存在: {file_path}"
        )

    try:
        import openpyxl
    except ImportError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content="需要安装 openpyxl: pip install openpyxl"
        )

    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)

        if sheet_name:
            if sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
            else:
                return ServiceResponse(
                    status=ServiceExecStatus.ERROR,
                    content=f"未找到工作表: {sheet_name}\n可用工作表: {', '.join(wb.sheetnames)}"
                )
        else:
            ws = wb.active

        rows = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                rows.append(f"... (共 {ws.max_row} 行，已显示前 {max_rows} 行)")
                break
            rows.append(row)

        wb.close()

        if not rows:
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content="Excel 文件为空"
            )

        header = rows[0] if rows else ()
        data = rows[1:] if len(rows) > 1 else []

        result = f"📊 文件: {path.name}\n"
        result += f"📑 工作表: {ws.title}\n"
        result += f"📏 数据: {ws.max_row} 行 x {ws.max_column} 列\n\n"

        if header:
            result += "**表头:**\n" + " | ".join(str(h) if h is not None else "" for h in header) + "\n\n"

        if data:
            result += f"**数据 (前 {len(data)} 行):**\n"
            for row in data[:10]:
                result += " | ".join(str(c) if c is not None else "" for c in row) + "\n"

        return ServiceResponse(status=ServiceExecStatus.SUCCESS, content=result)

    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"读取 Excel 出错: {str(e)}"
        )
