"""
History Filter - 历史消息过滤模块

对齐成熟平台（LibreChat）"持续上下文"语义：
- 默认：保留最近一段完整上下文（user + assistant 都保留）——省略/指代式追问
  （如"红岭变电站的"承接上一轮"制定F19地王一线预案"）不再因不含指代词而被丢光历史。
- 显式查历史（含"这些/刚才/上次"等信号词）时：再做 L3 语义扩展，把更早的相关历史并入。

层级：
- L1: 基于规则的"是否在显式查历史"判断（只决定要不要做 L3 扩展，不再决定"丢不丢"）
- L3: 基于语义模型的相关性判断（扩展用，失败/无模型时降级为关键词共现）
"""

import logging
import re
import json
from typing import List, Dict, Tuple, Optional
import httpx

logger = logging.getLogger(__name__)


class HistoryFilter:
    """历史消息过滤器"""

    # L1: 查历史信号关键词
    L1_HISTORY_QUERY_KEYWORDS = [
        "这些", "那些", "之前", "刚才", "上次", "前面",
        "再说一遍", "重复", "再说",
        "上面", "以上", "上述",
    ]

    # L3: 语义判断提示词模板
    L3_PROMPT_TEMPLATE = """你是一个历史消息相关性判断专家。需要判断"历史消息"是否与"当前用户问题"相关。

判断规则：
1. 如果历史消息与当前问题是同一个话题、业务领域或上下文，则相关
2. 如果历史消息是完全无关的话题，则不相关
3. 如果历史消息提供了当前问题所需的背景信息，则相关
4. 如果当前问题引用了历史消息中的内容（如"这些"、"那些"、"之前说的"等指代），则相关

只需返回 JSON 格式的结果：
{{"relevant": true/false, "reason": "简要原因"}}

历史消息: {hist_msg}

当前用户问题: {current_msg}
"""

    def __init__(self):
        """初始化 HistoryFilter"""

        # 编译关键词正则（不区分大小写）
        self._history_keyword_patterns = [
            re.compile(re.escape(kw), re.IGNORECASE)
            for kw in self.L1_HISTORY_QUERY_KEYWORDS
        ]

    def _get_model_manager(self):
        """延迟导入并获取 ModelManager 单例"""
        from src.services.model_manager import model_manager
        return model_manager

    # ★ 始终保留的最近上下文条数（完整轮，含 assistant）。
    # 对齐成熟平台"持续上下文"：连续对话的省略/指代式追问（"红岭变电站的"）依赖它承接任务锚点。
    DEFAULT_RECENT_KEEP = 6

    def filter_history(self, current_msg: str, history: List[Dict]) -> List[Dict]:
        """
        历史过滤（持续上下文语义）

        - 默认：保留最近 DEFAULT_RECENT_KEEP 条完整上下文（user + assistant），
          修复旧逻辑"不含指代词 → 丢弃全部历史"导致的跨轮断链。
        - 显式查历史语境：在最近窗口基础上做 L3 语义扩展（user/assistant 均参与判断）。

        Args:
            current_msg: 当前用户消息
            history: 历史消息列表（每条包含 role, content 等字段）

        Returns:
            过滤后的上下文消息列表（原顺序）
        """
        if not history:
            return []

        recent_window = history[-self.DEFAULT_RECENT_KEEP:]

        # Step 1: L1 —— 仅"显式查历史"时做 L3 语义扩展；否则直接返回最近窗口
        if not self._rule_based_judge(current_msg):
            logger.info(
                f"🔍 [HistoryFilter] 非查历史语境：保留最近 {len(recent_window)} 条完整上下文 "
                f"（旧逻辑此处会丢弃全部历史）"
            )
            return recent_window

        logger.info(f"🔍 [HistoryFilter] 当前消息涉及查历史，进入 L3 语义扩展")

        # Step 2: L3 —— 逐条判断（覆盖 user 与 assistant；assistant 的追问同样是连续性来源）
        relevant_keys = set()
        for i, msg in enumerate(history):
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue
            hist_content = msg.get("content", "")
            if not hist_content or not str(hist_content).strip():
                continue
            is_relevant, reason = self._semantic_judge(current_msg, str(hist_content))
            if is_relevant:
                relevant_keys.add((role, str(hist_content)))
                logger.info(f"  ✅ L3: 历史#{i}({role}) 相关 - {reason}")
            else:
                logger.info(f"  ❌ L3: 历史#{i}({role}) 不相关 - {reason}")

        # Step 3: 合并去重保序 —— 语义相关 ∪ 最近窗口，任何语境都不丢最近上下文
        recent_keys = {(m.get("role"), str(m.get("content", ""))) for m in recent_window}
        keep_keys = relevant_keys | recent_keys
        merged = [
            m for m in history
            if (m.get("role"), str(m.get("content", ""))) in keep_keys
        ]
        logger.info(f"🔍 [HistoryFilter] 结果: {len(merged)}/{len(history)} 条（语义扩展 ∪ 最近窗口）")
        return merged or recent_window

    def _rule_based_judge(self, current_msg: str) -> bool:
        """
        L1: 基于规则的"是否在查历史"判断

        检查当前消息是否包含指代词或查询历史的关键词。

        Returns:
            True: 可能在查历史
            False: 不在查历史
        """
        for pattern in self._history_keyword_patterns:
            if pattern.search(current_msg):
                logger.debug(f"  L1: 命中关键词 '{pattern.pattern}'")
                return True

        return False

    def _semantic_judge(self, current_msg: str, hist_msg: str) -> Tuple[bool, str]:
        """
        L3: 基于语义模型的动态调用判断

        通过 ModelManager 自动选择当前可用的模型。
        支持主模型和备用模型自动切换。

        Returns:
            (is_relevant: bool, reason: str)
        """
        try:
            # 通过 ModelManager 获取当前活跃的模型配置
            model_mgr = self._get_model_manager()
            model_config = model_mgr.get_active_model_config()

            if not model_config:
                logger.warning("⚠️ 模型管理器无可用的模型配置，使用降级策略")
                return self._fallback_semantic_judge(current_msg, hist_msg)

            api_base = model_config.get("api_base", "")
            model_name = model_config.get("model_name", "")
            api_key = model_config.get("api_key", "")

            if not api_base or not model_name:
                logger.warning("⚠️ 模型配置不完整，使用降级策略")
                return self._fallback_semantic_judge(current_msg, hist_msg)

            # 构造请求 URL
            api_url = f"{api_base}/chat/completions"

            prompt = self.L3_PROMPT_TEMPLATE.format(
                hist_msg=hist_msg,
                current_msg=current_msg
            )

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 128
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    api_url,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

            # 解析模型输出
            content = result["choices"][0]["message"]["content"].strip()

            # 尝试提取 JSON
            json_match = re.search(
                r'\{[^}]*"relevant"\s*:\s*(true|false)[^}]*\}',
                content, re.IGNORECASE
            )
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    is_relevant = parsed.get("relevant", False)
                    reason = parsed.get("reason", content)
                    return bool(is_relevant), reason
                except json.JSONDecodeError:
                    pass

            # 如果 JSON 解析失败，尝试简单文本匹配
            if "相关" in content and "不相关" not in content:
                return True, content[:50]
            elif "不相关" in content:
                return False, content[:50]

            return True, content[:50]

        except Exception as e:
            logger.warning(f"⚠️ L3 语义判断失败: {e}，使用降级策略")
            return self._fallback_semantic_judge(current_msg, hist_msg)

    def _fallback_semantic_judge(self, current_msg: str, hist_msg: str) -> Tuple[bool, str]:
        """
        降级策略：基于关键词共现的简单相关性判断

        用于 L3 模型调用失败时的备用方案。
        """
        current_words = set(re.findall(r'[\u4e00-\u9fff\w]+', current_msg))
        hist_words = set(re.findall(r'[\u4e00-\u9fff\w]+', hist_msg))

        common_words = current_words & hist_words

        # 过滤掉通用停用词
        stop_words = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
            "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
            "你", "会", "着", "没有", "看", "好", "自己", "这"
        }
        meaningful_common = common_words - stop_words

        overlap_ratio = len(meaningful_common) / max(len(current_words), 1)

        if overlap_ratio > 0.3:
            return True, f"降级判定: 词重叠 {overlap_ratio:.2f}"
        else:
            return False, f"降级判定: 词重叠不足 {overlap_ratio:.2f}"
