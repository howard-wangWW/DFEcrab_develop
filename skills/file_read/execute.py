"""
读取文件技能

使用方式:
执行技能 file_read，文件路径：/path/to/file.txt
"""

from pathlib import Path

from src.agentscope_compat import ServiceResponse, ServiceExecStatus


def execute(file_path: str, encoding: str = "utf-8") -> ServiceResponse:
    """
    读取文本文件内容

    Args:
        file_path: 文件路径
        encoding: 文件编码 (默认 utf-8)

    Returns:
        ServiceResponse 对象
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"读取失败：文件不存在：{file_path}"
            )

        if not path.is_file():
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"读取失败：路径不是文件：{file_path}"
            )

        content = path.read_text(encoding=encoding)
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"成功读取文件，共{path.stat().st_size}字节\n\n{content}"
        )
    except UnicodeDecodeError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"读取失败：文件编码与 {encoding} 不匹配"
        )
    except Exception as exc:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"读取失败：{exc}"
        )


# 技能元数据
SKILL_METADATA = {
    "name": "file_read",
    "version": "1.0.0",
    "description": "读取文本文件内容",
    "author": "DFEcrab Team",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "文件路径"
            },
            "encoding": {
                "type": "string",
                "description": "文件编码 (默认 utf-8)",
                "default": "utf-8"
            }
        },
        "required": ["file_path"]
    }
}
