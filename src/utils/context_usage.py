"""
context_usage.py - 上下文（token）占用统计

参考 CodeBuddy / Claude Code / Antigravity 等成熟平台的"上下文使用量"指示器：

    ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁    glm-4.7 · 38.1k/200k tokens (19%)
    Estimated usage by category:
      System prompt / System tools / Memory files / Skills / Messages ...

设计约定（对齐业界惯例）：
1. 展示形式统一为「已用 token / 上下文窗口总量 (百分比)」；
2. LLM 返回 `usage`（OpenAI 兼容，含 prompt_tokens / completion_tokens）时以实际为准；
   未返回时用本地估算兜底（source 区分两者）；
3. 分类明细（system_prompt / tools / memory / skills / messages）为本地估算，
   与 CodeBuddy "Estimated usage by category" 一致 —— LLM 只给总数，细分靠估算。
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ★ 上下文窗口安全默认值（阶段 A 统一收口，各模块引用此常量，不再散落 16384）
DEFAULT_CONTEXT_LENGTH = 16384

# ──────────────────────────────────────────────────────────────
# 估算系数（业界常用粗略值）
#   英文: 1 token ≈ 4 字符 ≈ 0.75 词
#   中文: 1 token ≈ 1 个汉字左右（视 tokenizer 而定，Qwen3 中文略低于 1）
# ──────────────────────────────────────────────────────────────
_EN_CHARS_PER_TOKEN = 4.0
_CN_CHARS_PER_TOKEN = 1.0


def estimate_tokens(text: Any) -> int:
    """本地估算一段文本的 token 数（LLM 未返回 usage 时的兜底）。

    Args:
        text: 待估算文本（非 str 会被 str() 化）

    Returns:
        估算的 token 数（至少 1）
    """
    if not text:
        return 0
    if not isinstance(text, str):
        text = str(text)
    # 统计中日韩等宽字符与其余字符
    cn_chars = sum(
        1 for ch in text
        if '\u4e00' <= ch <= '\u9fff'          # CJK 统一汉字
        or '\u3000' <= ch <= '\u303f'          # CJK 标点
        or '\uff00' <= ch <= '\uffef'          # 全角字符
    )
    other_chars = len(text) - cn_chars
    return max(1, int(cn_chars / _CN_CHARS_PER_TOKEN + other_chars / _EN_CHARS_PER_TOKEN))


def _json_tokens(obj: Any) -> int:
    """估算对象序列化为 JSON 后的 token 数（工具定义 schema 用）"""
    try:
        return estimate_tokens(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return 0


def compact_buffer(context_length: int, ratio: float = 0.08) -> int:
    """自动压缩预留空间（参考 CodeBuddy Autocompact buffer，默认预留 8%）。

    Args:
        context_length: 上下文窗口大小
        ratio: 预留比例

    Returns:
        预留的 token 数
    """
    return max(0, int(context_length * ratio))


def should_compact(last_prompt_tokens: int, context_length: int, threshold: float = 0.85) -> bool:
    """判断上一轮上下文占用是否达到自动压缩阈值（参考 Claude Code AutoCompact，默认 85%）。

    Args:
        last_prompt_tokens: 上一轮实际发送给模型的 prompt token 数（来自 message tokens.prompt）
        context_length: 模型上下文窗口大小
        threshold: 触发压缩的占用比例（0~1）

    Returns:
        是否触发压缩
    """
    if last_prompt_tokens <= 0 or context_length <= 0:
        return False
    return last_prompt_tokens / context_length >= threshold


def _scale_to_total(cat_tokens: Dict[str, int], target: int) -> Dict[str, int]:
    """按估算比例把分类 token 缩放到目标总数（归一化），使分类总和 = target。

    参考 CodeBuddy "Estimated usage by category"：LLM 只给总数，分类按比例分配，
    避免分类之和与 prompt_tokens 对不上。
    """
    est_sum = sum(cat_tokens.values())
    if est_sum <= 0:
        return cat_tokens
    scaled = {k: round(v * target / est_sum) for k, v in cat_tokens.items()}
    # 修正舍入误差：差值补到最大类
    diff = target - sum(scaled.values())
    if diff and scaled:
        max_k = max(scaled, key=scaled.get)
        scaled[max_k] += diff
    return scaled


def build_context_usage(
    llm_usage: Optional[Dict[str, Any]] = None,
    system_prompt: str = "",
    memory_text: str = "",
    skill_prompt: str = "",
    tools: Optional[List[Any]] = None,
    history: Optional[List[Dict]] = None,
    current: str = "",
    tool_results: Optional[List[Dict]] = None,
    context_length: int = DEFAULT_CONTEXT_LENGTH,
    buffer_ratio: float = 0.08,
    model: str = "",
) -> Dict[str, Any]:
    """构建上下文占用统计。

    Args:
        llm_usage: LLM 返回的 usage（OpenAI 兼容，含 prompt_tokens / completion_tokens），
                   未返回时传 None 走本地估算。
        system_prompt: 系统提示词（含工具调用规则，不含记忆/技能注入）。
        memory_text: 记忆上下文文本（对应 "Memory files"）。
        skill_prompt: 技能注入说明（对应 "Skills"）。
        tools: 工具定义 schema 列表（对应 "System tools"）。
        history: 历史对话消息列表（对应 "history"）。
        current: 当前用户消息文本（对应 "current"）。
        tool_results: 本轮工具结果消息列表（对应 "tool_results"）。
        context_length: 模型上下文窗口大小（来自 config/dfecrab.json 的 context_length）。
        buffer_ratio: 自动压缩预留比例（默认 8%）。
        model: 实际使用的模型名（用于多模型对话时按模型统计 / 标注占比口径）。

    Returns:
        {
            "prompt_tokens": 已用（本次发送）token 数,
            "completion_tokens": 本次生成 token 数,
            "context_length": 上下文窗口总量,
            "used_percent": 占窗口百分比（保留 1 位小数）,
            "free_space": 剩余可用空间,
            "categories": {分类名: {"tokens": int, "percent": float}},  # LLM usage 时归一化到 prompt_tokens
            "source": "llm_usage" | "local_estimate",
            "auto_compact_buffer": 压缩预留空间,
        }
    """
    history = history or []
    tool_results = tool_results or []
    tools = tools or []

    # 1. 分类 token 估算（本地）
    est_system = estimate_tokens(system_prompt)
    est_tools = _json_tokens(tools)
    est_memory = estimate_tokens(memory_text)
    est_skills = estimate_tokens(skill_prompt)
    est_history = sum(estimate_tokens(str(m.get("content", ""))) for m in history)
    est_current = estimate_tokens(current)
    est_tool_results = sum(estimate_tokens(str(m.get("content", ""))) for m in tool_results)

    est_items = {
        "system_prompt": est_system,
        "tools": est_tools,
        "memory": est_memory,
        "skills": est_skills,
        "history": est_history,
        "current": est_current,
        "tool_results": est_tool_results,
    }
    estimated_prompt = sum(est_items.values())

    # 2. 已用总数：优先 LLM 实际 usage，否则本地估算
    if llm_usage:
        prompt_tokens = int(llm_usage.get("prompt_tokens") or 0) or estimated_prompt
        completion_tokens = int(llm_usage.get("completion_tokens") or 0)
        source = "llm_usage"
    else:
        prompt_tokens = estimated_prompt
        completion_tokens = 0
        source = "local_estimate"

    # 3. 分类 token：LLM usage 时归一化到 prompt_tokens（分类总和 = prompt_tokens）
    cat_tokens = _scale_to_total(est_items, prompt_tokens) if source == "llm_usage" else est_items

    # 4. 分类明细（各分类占窗口百分比）
    categories = {
        name: {
            "tokens": tokens,
            "percent": round(tokens / context_length * 100, 1) if context_length else 0.0,
        }
        for name, tokens in cat_tokens.items()
    }

    # 5. 汇总
    used_percent = round(prompt_tokens / context_length * 100, 1) if context_length else 0.0
    free_space = max(0, context_length - prompt_tokens)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "context_length": context_length,
        "used_percent": used_percent,
        "free_space": free_space,
        "categories": categories,
        "source": source,
        # ★ 自动压缩预留空间（参考 CodeBuddy Autocompact buffer）
        "auto_compact_buffer": compact_buffer(context_length, buffer_ratio),
        # ★ 实际使用的模型名（多模型对话时用于按模型统计 / 标注占比口径）
        "model": model,
    }


def usage_to_tokens(usage: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """把上下文 usage 折算成 Message.tokens 落库结构（prompt/completion/total）。

    Args:
        usage: build_context_usage 的返回值，或 OpenAI usage dict。

    Returns:
        {"prompt": int, "completion": int, "total": int}
    """
    if not usage:
        return {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    return {
        "prompt": prompt,
        "completion": completion,
        "total": prompt + completion,
    }
