"""
读取文件技能

使用方式:
执行技能 file_read，文件路径：/path/to/file.txt
"""

from src.plugin_framework.builtin.builtin_tools_plugin import BuiltinToolsPlugin
from agentscope.service import ServiceResponse, ServiceExecStatus


def execute(file_path: str, encoding: str = "utf-8") -> ServiceResponse:
    """
    读取文本文件内容

    Args:
        file_path: 文件路径
        encoding: 文件编码 (默认 utf-8)

    Returns:
        ServiceResponse 对象
    """
    plugin = BuiltinToolsPlugin()
    result = plugin.file_read(file_path, encoding)

    if result.get("success"):
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"成功读取文件，共{result.get('size', 0)}字节\n\n{result.get('content', '')}"
        )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"读取失败：{result.get('error', '未知错误')}"
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