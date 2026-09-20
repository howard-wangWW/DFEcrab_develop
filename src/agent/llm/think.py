"""
think_utils.py - 思考标签处理工具（配置化）

统一处理多模型思考格式：
1. reasoning_content 字段（标准格式）
2. content 字段中的标签包裹（如 <think>...思考标签）
3. 标签可能被拆分到多个 chunk
"""

import re
from typing import Dict, List, Optional


def get_default_think_config() -> Dict:
    """获取默认的思考标签配置"""
    return {
        "start_tags": ["<think>", "<thinking>"],
        "end_tags": ["</thinking>", "</think>"],
        "reasoning_fields": ["reasoning_content", "reasoning"],
        "max_tag_len": 20
    }


def get_think_config_for_model(model_config: Optional[Dict] = None) -> Dict:
    """根据模型配置获取对应的 think_config
    
    优先级：
    1. 模型配置中的 think_config
    2. 全局 dfecrab.json 中的 think_config
    3. 默认配置
    """
    default = get_default_think_config()
    
    # 1. 检查模型配置
    if model_config:
        model_think = model_config.get("think_config", {})
        if model_think:
            return {
                "start_tags": model_think.get("start_tags", default["start_tags"]),
                "end_tags": model_think.get("end_tags", default["end_tags"]),
                "reasoning_fields": model_think.get("reasoning_fields", default["reasoning_fields"]),
                "max_tag_len": model_think.get("max_tag_len", default["max_tag_len"])
            }
    
    # 2. 尝试读取全局配置
    try:
        from src.config.config_loader import config as _cfg
        global_think = _cfg.raw_config.get("think_config", {})
        if global_think:
            return {
                "start_tags": global_think.get("start_tags", default["start_tags"]),
                "end_tags": global_think.get("end_tags", default["end_tags"]),
                "reasoning_fields": global_think.get("reasoning_fields", default["reasoning_fields"]),
                "max_tag_len": global_think.get("max_tag_len", default["max_tag_len"])
            }
    except Exception:
        pass
    
    # 3. 返回默认
    return default


def remove_think_tags(text: str, think_config: Optional[Dict] = None) -> str:
    """移除文本中的思考标签及其内容
    
    Args:
        text: 待处理的文本
        think_config: 思考标签配置，如果为 None 则使用默认配置
    
    Returns:
        清理后的文本
    """
    if not text:
        return ""
    
    config = think_config or get_default_think_config()
    start_tags = config["start_tags"]
    end_tags = config["end_tags"]
    all_tags = start_tags + end_tags
    
    # 移除所有开始标签+内容+结束标签的完整组合
    for start_tag in start_tags:
        for end_tag in end_tags:
            pattern = f'{re.escape(start_tag)}[\\s\\S]*?{re.escape(end_tag)}'
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # 移除单独的标签
    for tag in all_tags:
        text = re.sub(re.escape(tag), '', text, flags=re.IGNORECASE)
    
    # 清理多余的空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_think_content(text: str, think_config: Optional[Dict] = None) -> str:
    """从模型输出中提取思考标签内的内容
    
    Args:
        text: 待处理的文本
        think_config: 思考标签配置
    
    Returns:
        提取的思考内容
    """
    if not text:
        return ""
    
    config = think_config or get_default_think_config()
    start_tags = config["start_tags"]
    end_tags = config["end_tags"]
    
    # 遍历所有可能的开始/结束标签组合
    for start_tag in start_tags:
        for end_tag in end_tags:
            pattern = f'{re.escape(start_tag)}([\\s\\S]*?){re.escape(end_tag)}'
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                if content:
                    return content
    return ""


def strip_cot(text: str, think_config: Optional[Dict] = None) -> str:
    """增强版思维链剥离 - 处理模型输出的各种思考过程格式
    
    Args:
        text: 待处理的文本
        think_config: 思考标签配置
    
    Returns:
        清理后的文本
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        import json
        try:
            text = json.dumps(text, ensure_ascii=False, default=str)
        except Exception:
            text = str(text)

    config = think_config or get_default_think_config()
    start_tags = config["start_tags"]
    end_tags = config["end_tags"]
    all_tags = start_tags + end_tags

    # 1. 移除所有开始标签+内容+结束标签的完整组合
    for start_tag in start_tags:
        for end_tag in end_tags:
            pattern = f'{re.escape(start_tag)}[\\s\\S]*?{re.escape(end_tag)}'
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    # 2. 移除孤立的标签
    for tag in all_tags:
        text = re.sub(re.escape(tag), '', text, flags=re.IGNORECASE)

    # 3. 清理 "Here's a thinking process:" 格式
    pattern = r"Here's a thinking process:[\s\S]*?(?=\n\n[\u4e00-\u9fff])"
    text = re.sub(pattern, '', text, flags=re.DOTALL)
    if "Here's a thinking process:" in text or "Here's a thinking process:" in text:
        text = re.sub(r"Here['']?s a thinking process:[\s\S]*$", '', text, flags=re.DOTALL)

    # 4. 清理常见的中文推理前缀
    reasoning_prefixes = [
        r'用户问题是',
        r'当前技能列表',
        r'仔细看技能列表',
        r'再仔细看技能列表',
        r'哦，用户的问题是',
        r'让我思考一下',
        r'我再检查一遍',
        r'我再仔细检查',
        r'所以结论是',
        r'所以，我将回复',
        r'所以，最终的输出是',
        r'但是，等等',
        r'不过，作为',
        r'因此，输出应该是',
        r'有没有可能',
        r'有没有可能漏掉了',
        r'正在分析用户意图',
        r'分析用户意图',
    ]
    for prefix in reasoning_prefixes:
        text = re.sub(prefix, '', text)

    # 5. 清理 Draft/Self-Correction 等推理标记
    text = re.sub(r'\d+\.\s+\*{2}.+?\*{2}[\s\S]*?(?=\n\d+\.|\n\n|$)', '', text, flags=re.DOTALL)
    text = re.sub(r'(?m)^(Draft|Self-Correction|Verification|Self-Check|Final Check)[:\s].*$', '', text)
    text = re.sub(r'[✅☑️✓✗⬜🔍]', '', text)
    text = re.sub(r'Ready\..*?✅', '', text)

    # 6. 压缩多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def find_first_tag_position(text: str, think_config: Optional[Dict] = None) -> Optional[Dict]:
    """查找文本中第一个标签的位置
    
    Args:
        text: 待处理的文本
        think_config: 思考标签配置
    
    Returns:
        {"type": "start"|"end", "tag": str, "position": int} 或 None
    """
    if not text:
        return None
    
    config = think_config or get_default_think_config()
    start_tags = config["start_tags"]
    end_tags = config["end_tags"]
    
    min_pos = -1
    result = None
    
    # 查找开始标签
    for tag in start_tags:
        pos = text.lower().find(tag.lower())
        if pos >= 0 and (min_pos == -1 or pos < min_pos):
            min_pos = pos
            result = {"type": "start", "tag": tag, "position": pos}
    
    # 查找结束标签
    for tag in end_tags:
        pos = text.lower().find(tag.lower())
        if pos >= 0 and (min_pos == -1 or pos < min_pos):
            min_pos = pos
            result = {"type": "end", "tag": tag, "position": pos}
    
    return result


def check_split_tag(text: str, think_config: Optional[Dict] = None) -> Optional[str]:
    """检查文本末尾是否可能是被拆分的标签
    
    Args:
        text: 待处理的文本
        think_config: 思考标签配置
    
    Returns:
        如果可能是被拆分的标签，返回该标签；否则返回 None
    """
    if not text:
        return None
    
    config = think_config or get_default_think_config()
    all_tags = config["start_tags"] + config["end_tags"]
    max_tag_len = config["max_tag_len"]
    
    lower_text = text.lower()
    for tag in all_tags:
        for i in range(1, min(len(tag), max_tag_len) + 1):
            if lower_text.endswith(tag[:i].lower()):
                return tag
    
    return None


# ──────────────────────────────────────────────────────────────
# ★ v4.0: 思考与正文分离
# ──────────────────────────────────────────────────────────────

def extract_thinking_and_content(
    text: str,
    think_config: Optional[Dict] = None
) -> tuple:
    """从模型输出中分离思考内容与正文内容

    Args:
        text: 模型原始输出（可能含 <think>...</think> 标签）
        think_config: 思考标签配置

    Returns:
        (thinking, content) 元组
        - thinking: 思考内容（标签内的文本，已去标签）
        - content: 正文内容（标签外的文本）

    示例:
        >>> text = "<think>用户问天气</think>烟台今天晴"
        >>> extract_thinking_and_content(text)
        ('用户问天气', '烟台今天晴')
    """
    if not text:
        return "", ""

    config = think_config or get_default_think_config()
    start_tags = config["start_tags"]
    end_tags = config["end_tags"]

    thinking_parts = []
    content_parts = []
    remaining = text

    # 循环提取所有 <think>...</think> 块
    while remaining:
        # 查找最早的开始标签
        earliest_start_idx = -1
        earliest_start_tag = None
        for tag in start_tags:
            idx = remaining.lower().find(tag.lower())
            if idx >= 0 and (earliest_start_idx == -1 or idx < earliest_start_idx):
                earliest_start_idx = idx
                earliest_start_tag = tag

        if earliest_start_idx == -1:
            # 没有更多思考块，剩余全是正文
            content_parts.append(remaining)
            break

        # 开始标签之前的内容是正文
        if earliest_start_idx > 0:
            content_parts.append(remaining[:earliest_start_idx])

        # 查找对应的结束标签
        after_start = remaining[earliest_start_idx + len(earliest_start_tag):]
        earliest_end_idx = -1
        earliest_end_tag = None
        for tag in end_tags:
            idx = after_start.lower().find(tag.lower())
            if idx >= 0 and (earliest_end_idx == -1 or idx < earliest_end_idx):
                earliest_end_idx = idx
                earliest_end_tag = tag

        if earliest_end_idx == -1:
            # 没有结束标签，剩余全是思考
            thinking_parts.append(after_start)
            break

        # 提取思考内容
        thinking_parts.append(after_start[:earliest_end_idx])
        remaining = after_start[earliest_end_idx + len(earliest_end_tag):]

    thinking = "\n".join(p.strip() for p in thinking_parts if p.strip())
    content = "".join(content_parts)
    # 清理多余空行
    content = re.sub(r'\n{3,}', '\n\n', content).strip()

    return thinking, content
