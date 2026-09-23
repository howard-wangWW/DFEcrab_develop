"""
读取 Word 文档技能

使用方式:
执行技能 word_read，文件路径：/path/to/document.docx
"""

from src.utils.word_reader import read_word
from agentscope.service import ServiceResponse, ServiceExecStatus


def execute(file_path: str) -> ServiceResponse:
    """
    读取 Word 文档并返回内容

    Args:
        file_path: Word 文档路径 (.docx 格式)

    Returns:
        ServiceResponse 对象
    """
    result = read_word(file_path)

    if result.get("success"):
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"成功读取文档《{result.get('title')}》，共{result.get('word_count')}字\n\n{result.get('content', '')}"
        )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"读取失败：{result.get('error', '未知错误')}"
        )


# 技能元数据
SKILL_METADATA = {
    "name": "word_read",
    "version": "1.0.0",
    "description": "读取 Word 文档 (.docx 格式)",
    "author": "DFEcrab Team",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Word 文档路径，如：/path/to/document.docx"
            }
        },
        "required": ["file_path"]
    }
}
