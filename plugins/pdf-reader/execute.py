"""
PDF Reader Skill - 读取 PDF 文件

提取 PDF 文本内容，支持指定页码和图片提取
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional, List

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def execute(
    file_path: str,
    pages: Optional[List[int]] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
    extract_images: bool = False,
    output_dir: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    读取 PDF 文件，提取文本内容

    Args:
        file_path: PDF 文件路径
        pages: 指定页码列表
        start_page: 起始页码
        end_page: 结束页码
        extract_images: 是否提取图片
        output_dir: 图片输出目录

    Returns:
        {
            "status": "SUCCESS" | "ERROR",
            "content": {...}
        }
    """
    try:
        from src.services.pdf_service import get_pdf_service
        import asyncio

        # 获取 PDF 服务
        service = get_pdf_service()

        # 确保初始化
        loop = asyncio.get_event_loop()
        if not service._initialized:
            loop.run_until_complete(service.initialize())

        # 验证文件存在
        if not os.path.exists(file_path):
            return {
                "status": "ERROR",
                "content": {"error": f"文件不存在: {file_path}"}
            }

        # 提取文本
        result = service.extract_text(
            pdf_path=file_path,
            pages=pages,
            start_page=start_page,
            end_page=end_page
        )

        # 提取图片（可选）
        if extract_images:
            images = service.extract_images(
                pdf_path=file_path,
                pages=pages,
                output_dir=output_dir
            )
            result["images"] = [img.to_dict() for img in images]

        return {
            "status": "SUCCESS",
            "content": result
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "ERROR",
            "content": {"error": str(e)}
        }


# 直接执行时的入口
if __name__ == "__main__":
    if len(sys.argv) > 1:
        params = json.loads(sys.argv[1])
    else:
        # 测试参数
        params = {
            "file_path": "/Users/zhanghanzhi/DFEcrab/README.md"
        }

    result = execute(**params)
    print(json.dumps(result, ensure_ascii=False, indent=2))
