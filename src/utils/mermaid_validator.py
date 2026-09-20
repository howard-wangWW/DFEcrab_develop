import re
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MERMIAID_DARK_THEME = """%%{init: {
  'theme': 'base',
  'themeVariables': {
    'background': '#0A2A44',
    'primaryColor': '#4A9EFF',
    'primaryTextColor': '#FFFFFF',
    'primaryBorderColor': '#8EC8FF',
    'lineColor': '#6AB0FF',
    'secondaryColor': '#1E4468',
    'tertiaryColor': '#002A4F',
    'clusterBkg': '#0A2A44',
    'edgeLabelBackground':'#0A2A44'
  }
}}%%"""


def validate_mermaid_blocks(text: str) -> Dict:
    """
    验证文本中所有 Mermaid 代码块的格式正确性
    
    返回:
        {
            "valid": bool,
            "total_blocks": int,
            "errors": [{"type": "...", "detail": "...", "position": int}],
            "blocks": [{"start": int, "end": int, "has_opening": bool, "has_closing": bool, "content": str}]
        }
    """
    errors = []
    blocks = []
    
    # 1. 检查标准 ```mermaid ... ``` 代码块
    pattern_standard = re.compile(r'```mermaid\s*\n(.*?)```', re.DOTALL)
    standard_matches = list(pattern_standard.finditer(text))
    
    for m in standard_matches:
        blocks.append({
            "start": m.start(),
            "end": m.end(),
            "has_opening": True,
            "has_closing": True,
            "content": m.group(1),
            "type": "standard"
        })
    
    # 2. 检查裸露的 mermaid 关键词（缺少 ``` 包裹）
    pattern_bare = re.compile(r'(?:^|\n)\s*(mermaid)\s*\n(.*?)(?=\n[A-Z#]|$)', re.DOTALL)
    bare_matches = list(pattern_bare.finditer(text))
    
    for m in bare_matches:
        # 排除已被标准代码块匹配的部分
        is_inside_standard = any(
            m.start() >= s["start"] and m.end() <= s["end"]
            for s in blocks
        )
        if not is_inside_standard:
            errors.append({
                "type": "missing_backticks",
                "detail": "mermaid 代码缺少 ``` 包裹",
                "position": m.start()
            })
            blocks.append({
                "start": m.start(),
                "end": m.end(),
                "has_opening": False,
                "has_closing": False,
                "content": m.group(2),
                "type": "bare"
            })
    
    # 3. 检查有开头 ``` 但缺少结尾 ``` 的情况
    pattern_unclosed = re.compile(r'```mermaid\s*\n(.*?)(?=\n[A-Z#]|$)', re.DOTALL)
    unclosed_matches = list(pattern_unclosed.finditer(text))
    for m in unclosed_matches:
        is_already_matched = any(
            m.start() >= s["start"] and m.end() <= s["end"]
            for s in blocks
        )
        if not is_already_matched:
            errors.append({
                "type": "unclosed_block",
                "detail": "mermaid 代码块缺少结尾 ```",
                "position": m.start()
            })
            blocks.append({
                "start": m.start(),
                "end": m.end(),
                "has_opening": True,
                "has_closing": False,
                "content": m.group(1),
                "type": "unclosed"
            })
    
    # 4. 检查 flowchart/graph 关键词是否在代码块内
    flowchart_pattern = re.compile(r'(flowchart|graph)\s+(TD|LR|RL|BT|TB)', re.IGNORECASE)
    for m in flowchart_pattern.finditer(text):
        is_inside_block = any(
            m.start() >= s["start"] and m.end() <= s["end"]
            for s in blocks
        )
        if not is_inside_block:
            errors.append({
                "type": "flowchart_outside_block",
                "detail": f"'{m.group()}' 不在任何代码块内",
                "position": m.start()
            })
    
    return {
        "valid": len(errors) == 0,
        "total_blocks": len([b for b in blocks if b["type"] == "standard"]),
        "errors": errors,
        "blocks": blocks
    }


def fix_mermaid_blocks(text: str, add_dark_theme: bool = True) -> Tuple[str, List[str]]:
    """
    自动修复文本中的 Mermaid 格式问题
    
    修复内容:
    1. 裸露的 mermaid 关键词 → 补上 ``` 包裹
    2. 缺少结尾 ``` → 补上
    3. flowchart/graph 在代码块外 → 包裹进代码块
    4. 可选：添加深色主题配置
    
    返回:
        (修复后的文本，修复日志列表)
    """
    fixes = []
    result = text
    
    # 辅助函数：检查位置是否在已有的 mermaid 代码块内
    def is_inside_mermaid_block(pos, text_to_check):
        """检查给定位置是否在 mermaid 代码块内"""
        # 找到所有 ```mermaid 和 ``` 的位置
        mermaid_opens = [(m.start(), m.end()) for m in re.finditer(r'```mermaid', text_to_check)]
        closes = [m.start() for m in re.finditer(r'```(?!\w)', text_to_check)]
        
        for open_start, open_end in mermaid_opens:
            # 找到对应的闭合
            for close_pos in closes:
                if close_pos > open_end:
                    if open_start <= pos <= close_pos + 3:
                        return True
                    break
        return False
    
    # 修复 1: 裸露的 "mermaid\nflowchart..." → "```mermaid\nflowchart...\n```"
    pattern_bare_mermaid = re.compile(
        r'(^|\n)\s*mermaid\s*\n((?:(?!```|\n[A-Z#]).)*)',
        re.DOTALL
    )
    
    def fix_bare_mermaid(match):
        prefix = match.group(1)
        content = match.group(2).strip()
        if not content:
            return match.group(0)
        
        # 检查是否已经在 mermaid 块内
        if is_inside_mermaid_block(match.start(), result):
            return match.group(0)
        
        fixes.append(f"修复裸露 mermaid 块 (位置 {match.start()})")
        
        theme_prefix = ""
        if add_dark_theme and "%%{init" not in content:
            theme_prefix = MERMIAID_DARK_THEME + "\n"
            fixes.append(f"  -> 添加深色主题配置")
        
        return f"{prefix}```mermaid\n{theme_prefix}{content}\n```"
    
    result = pattern_bare_mermaid.sub(fix_bare_mermaid, result)
    
    # 修复 2: 有 ```mermaid 开头但缺少结尾 ```
    pattern_unclosed = re.compile(
        r'```mermaid\s*\n((?:(?!```).)*)\n(?=\n[A-Z#]|$)',
        re.DOTALL
    )
    
    def fix_unclosed(match):
        # 检查是否已经闭合
        if is_inside_mermaid_block(match.start(), result):
            return match.group(0)
        
        content = match.group(1).strip()
        fixes.append(f"修复未闭合 mermaid 块 (位置 {match.start()})")
        
        theme_prefix = ""
        if add_dark_theme and "%%{init" not in content:
            theme_prefix = MERMIAID_DARK_THEME + "\n"
            fixes.append(f"  -> 添加深色主题配置")
        
        return f"```mermaid\n{theme_prefix}{content}\n```\n"
    
    result = pattern_unclosed.sub(fix_unclosed, result)
    
    # 修复 3: flowchart/graph 行不在任何代码块内
    flowchart_pattern = re.compile(
        r'((?:^|\n)\s*(flowchart|graph)\s+(TD|LR|RL|BT|TB).*?(?=\n[A-Z#]|$))',
        re.IGNORECASE | re.DOTALL
    )
    
    for m in list(flowchart_pattern.finditer(result)):
        if is_inside_mermaid_block(m.start(), result):
            continue
        
        fixes.append(f"修复裸露 flowchart 定义 (位置 {m.start()})")
        content = m.group(1).strip()
        
        theme_prefix = ""
        if add_dark_theme and "%%{init" not in content:
            theme_prefix = MERMIAID_DARK_THEME + "\n"
            fixes.append(f"  -> 添加深色主题配置")
        
        replacement = f"\n```mermaid\n{theme_prefix}{content}\n```"
        result = result[:m.start()] + replacement + result[m.end():]
        break  # 修复后重新扫描
    
    return result, fixes


def ensure_mermaid_format(text: str) -> str:
    """
    一站式 Mermaid 格式保障：验证 + 修复 + 日志
    
    在 reporter_agent 输出后调用，确保流程图格式正确。
    """
    validation = validate_mermaid_blocks(text)
    
    if validation["valid"]:
        logger.info(f"[MermaidValidator] 流程图格式验证通过，共 {validation['total_blocks']} 个代码块")
        return text
    
    logger.warning(f"[MermaidValidator] 发现 {len(validation['errors'])} 个格式问题:")
    for err in validation["errors"]:
        logger.warning(f"  - [{err['type']}] {err['detail']} (位置 {err['position']})")
    
    fixed_text, fixes = fix_mermaid_blocks(text, add_dark_theme=True)
    
    if fixes:
        logger.info(f"[MermaidValidator] 已自动修复 {len(fixes)} 个问题:")
        for fix in fixes:
            logger.info(f"  - {fix}")
        
        # 修复后二次验证
        recheck = validate_mermaid_blocks(fixed_text)
        if recheck["valid"]:
            logger.info(f"[MermaidValidator] 二次验证通过")
        else:
            logger.warning(f"[MermaidValidator] 二次验证仍有问题，可能需要人工检查")
    
    return fixed_text
