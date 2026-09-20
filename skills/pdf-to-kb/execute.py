"""
PDF to Knowledge Base Skill

将 PDF 文档内容保存为 DFEcrab 的知识库
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def execute(
    file_path: str,
    title: Optional[str] = None,
    agent_id: Optional[str] = None,
    memory_type: str = "long_term",
    pages: Optional[List[int]] = None,
    summarize: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    将 PDF 保存为知识库

    Args:
        file_path: PDF 文件路径
        title: 文档标题
        agent_id: 目标智能体 ID（None 则保存到共享记忆）
        memory_type: 记忆类型
        pages: 指定页码
        summarize: 是否生成摘要

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
        pdf_service = get_pdf_service()
        loop = asyncio.get_event_loop()
        if not pdf_service._initialized:
            loop.run_until_complete(pdf_service.initialize())

        # 验证文件存在
        if not os.path.exists(file_path):
            return {
                "status": "ERROR",
                "content": {"error": f"文件不存在: {file_path}"}
            }

        # 提取文本
        result = pdf_service.extract_text(file_path, pages=pages)
        text = result["text"]

        # 获取元数据
        metadata = pdf_service.get_metadata(file_path)

        # 确定标题
        if not title:
            title = metadata.get("title") or Path(file_path).stem

        # 确定保存路径
        if agent_id:
            # 智能体记忆
            memory_dir = project_root / "agents" / agent_id
        else:
            # 共享记忆
            memory_dir = project_root / "data" / "shared_memory"

        memory_dir.mkdir(parents=True, exist_ok=True)

        if memory_type == "daily":
            today = datetime.now().strftime("%Y-%m-%d")
            memory_file = memory_dir / "memory" / f"{today}.md"
        else:
            memory_file = memory_dir / "MEMORY.md"

        memory_file.parent.mkdir(parents=True, exist_ok=True)

        # 生成摘要
        summary = ""
        if summarize and len(text) > 500:
            # 简单摘要：取前 500 字符
            summary = text[:500] + "...\n"
        else:
            summary = text

        # 构建知识条目
        knowledge_entry = f"""

## {title}

> 来源：{Path(file_path).name}
> 时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}
> 页数：{result['total_pages']} 页

### 文档信息

- 总页数：{result['total_pages']}
- 字符数：{len(text)}
- 作者：{metadata.get('author', '未知')}

### 内容摘要

{summary}

### 关键信息

"""

        # 提取关键段落（包含"建设"、"系统"、"目标"等关键词的段落）
        keywords = ["建设", "系统", "目标", "架构", "功能", "应用", "平台"]
        key_paragraphs = []
        for para in text.split("\n\n"):
            if any(kw in para for kw in keywords) and len(para) > 50:
                key_paragraphs.append(para[:200])
                if len(key_paragraphs) >= 5:
                    break

        if key_paragraphs:
            knowledge_entry += "\n".join(f"- {p}..." for p in key_paragraphs)

        # 追加到记忆文件
        if memory_file.exists():
            with open(memory_file, 'r', encoding='utf-8') as f:
                existing_content = f.read()
        else:
            existing_content = f"# {'共享记忆' if not agent_id else f'{agent_id} 记忆'}\n\n_最后更新：{datetime.now().strftime('%Y-%m-%d')}_\n"

        # 更新内容
        new_content = existing_content + knowledge_entry
        new_content += f"\n\n---\n_最后更新：{datetime.now().strftime('%Y-%m-%d %H:%M')}_\n"

        with open(memory_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return {
            "status": "SUCCESS",
            "content": {
                "title": title,
                "total_pages": result['total_pages'],
                "saved_pages": result['extracted_pages'],
                "saved_to": str(memory_file),
                "char_count": len(text),
                "memory_type": memory_type
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "ERROR",
            "content": {"error": str(e)}
        }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        params = json.loads(sys.argv[1])
    else:
        params = {
            "file_path": "/Users/zhanghanzhi/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/zhanghanzhi2008_0bcf/msg/file/2026-03/地区电网新一代调度技术支持系统建设方案（试行）20231107发文版.pdf"
        }

    result = execute(**params)
    print(json.dumps(result, ensure_ascii=False, indent=2))
