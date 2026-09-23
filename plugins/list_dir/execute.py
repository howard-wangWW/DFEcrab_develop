"""
目录列表技能

列出目录下的文件和子目录。
"""

import os
from pathlib import Path
from agentscope.service import ServiceResponse, ServiceExecStatus


def execute(dir_path: str, pattern: str = "*", recursive: bool = False) -> ServiceResponse:
    """
    列出目录下的文件

    Args:
        dir_path: 目录路径
        pattern: 文件匹配模式 (默认 "*" 匹配所有文件)
        recursive: 是否递归子目录 (默认 False)

    Returns:
        ServiceResponse 对象，包含目录文件列表
    """
    try:
        path = Path(dir_path)

        if not path.exists():
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"目录不存在：{dir_path}"
            )

        if not path.is_dir():
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"路径不是目录：{dir_path}"
            )

        result_parts = [f"📁 目录: {dir_path}\n"]

        if recursive:
            items = sorted(path.rglob(pattern))
            result_parts.append("🔄 递归模式\n")
        else:
            items = sorted(path.glob(pattern))
            result_parts.append("📂 当前目录\n")

        files = []
        dirs = []

        for item in items:
            if item == path:
                continue

            if item.is_file():
                size = item.stat().st_size
                size_str = _format_size(size)
                files.append(f"  📄 {item.name} ({size_str})")
            elif item.is_dir():
                dirs.append(f"  📁 {item.name}/")

        result_parts.append(f"\n📊 统计: {len(files)} 个文件, {len(dirs)} 个子目录\n")

        if dirs:
            result_parts.append("\n子目录:\n")
            result_parts.append("\n".join(dirs))

        if files:
            result_parts.append("\n\n文件:\n")
            result_parts.append("\n".join(files[:50]))

            if len(files) > 50:
                result_parts.append(f"\n... 还有 {len(files) - 50} 个文件")

        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content="".join(result_parts)
        )

    except PermissionError:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"权限不足，无法访问目录：{dir_path}"
        )
    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"读取目录失败：{str(e)}"
        )


def _format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


SKILL_METADATA = {
    "name": "list_dir",
    "version": "1.0.0",
    "description": "列出目录下的文件和子目录",
    "author": "DFEcrab Team",
    "parameters": {
        "type": "object",
        "properties": {
            "dir_path": {
                "type": "string",
                "description": "目录路径"
            },
            "pattern": {
                "type": "string",
                "description": "文件匹配模式，如 '*.py' 或 '*'",
                "default": "*"
            },
            "recursive": {
                "type": "boolean",
                "description": "是否递归子目录",
                "default": False
            }
        },
        "required": ["dir_path"]
    }
}