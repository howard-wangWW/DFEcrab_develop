"""
文件管理工具
"""

import os
import shutil
from pathlib import Path


def execute(action: str, path: str, content: str = None):
    """文件管理工具

    Args:
        action: 操作类型 (create, read, delete, list)
        path: 文件或目录路径
        content: 文件内容（仅 create 时需要）

    Returns:
        操作结果
    """
    try:
        path = Path(path).expanduser()

        if action == "create":
            if not content:
                return "❌ 创建文件需要提供内容"

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            return f"✅ 文件已创建: {path}"

        elif action == "read":
            if not path.exists():
                return f"❌ 文件不存在: {path}"

            content = path.read_text(encoding='utf-8')
            lines = content.split('\n')
            if len(lines) > 50:
                preview = '\n'.join(lines[:50])
                return f"📄 文件内容（前 50 行）:\n\n{preview}\n\n... (共 {len(lines)} 行)"
            return f"📄 文件内容:\n\n{content}"

        elif action == "delete":
            if not path.exists():
                return f"❌ 文件不存在: {path}"

            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return f"✅ 已删除: {path}"

        elif action == "list":
            target = path.parent if path.is_file() else path
            if not target.exists():
                return f"❌ 路径不存在: {target}"

            items = sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            output = f"📁 目录列表: {target}\n\n"

            for item in items:
                icon = "📁" if item.is_dir() else "📄"
                size = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
                output += f"{icon} {item.name}{size}\n"

            return output.strip()

        else:
            return "❌ 不支持的操作，使用: create, read, delete, list"

    except Exception as e:
        return f"❌ 操作失败: {e}"
