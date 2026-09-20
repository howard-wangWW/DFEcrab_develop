"""
IntentClassifier — 轻量意图分类器

将用户消息分为两类意图（批次10：complex 已退役，多步骤复杂任务一律归 task）：
  - chat → 快速闲聊
  - task → 所有任务/查询（含多步骤，由智能体在工具循环内自主连续完成）

兼容说明：COMPLEX 常量与 complex_patterns 参数保留仅为外部旧调用兼容，
classify() 输出统一归一为两档（complex/未知 → task），不会向下游漏出 complex。

支持两种模式：
  1. 规则模式（默认）：基于关键词匹配，零延迟
  2. LLM 模式（可选）：调用轻量 LLM 分类，准确率更高

后续扩展：LLM 模式只需实现 _llm_classify() 即可，入口签名不变。
"""

import asyncio
import logging
import re as _re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class IntentClassifier:
    """轻量意图分类器

    使用方式:
        classifier = IntentClassifier()
        intent = classifier.classify(message="帮我查天气", has_skills=True)
        # → "task"

        intent = classifier.classify(message="你好", has_skills=True)
        # → "chat"

        intent = classifier.classify(message="批量生成所有报表并导出", has_skills=True)
        # → "task"（complex 已退役，多步骤一律 task）
    """

    # ── 可配置的规则（仅 LLM 降级时使用） ──
    # 硬编码默认值为空，规则匹配时优先使用外部注入的 patterns。
    # 历史硬编码已迁移到 agents/manager_agent/config.json 的 intent_patterns 字段。

    CHAT_PATTERNS: List[str] = []
    # 历史硬编码已迁移到 agents/manager_agent/config.json
    # COMPLEX_PATTERNS / TASK_SIGNALS 由外部配置注入，未注入时为空

    # 消息长度阈值（≤ 此值视为短消息）
    SHORT_MSG_THRESHOLD: int = 10

    # ── 分类结果 ──

    CHAT = "chat"
    TASK = "task"
    COMPLEX = "complex"

    def __init__(
        self,
        use_llm: bool = True,
        llm_config: Optional[Dict] = None,
        chat_patterns: Optional[List[str]] = None,
        complex_patterns: Optional[List[str]] = None,
        task_signals: Optional[List[str]] = None,
    ):
        """初始化意图分类器

        Args:
            use_llm: 是否启用 LLM 模式（默认 True，若 llm_config 为空则自动降级为规则）
            llm_config: LLM 配置，包含 api_base, model_name 等
            chat_patterns: 自定义闲聊关键词
            complex_patterns: 自定义复杂任务关键词
            task_signals: 自定义办事信号
        """
        self.use_llm = use_llm
        self.llm_config = llm_config
        # ★ 硬编码默认值已清空（v5 阶段 E），如需规则匹配请通过 chat_patterns / complex_patterns / task_signals 注入
        self.CHAT_PATTERNS: List[str] = chat_patterns if chat_patterns is not None else []
        self.COMPLEX_PATTERNS: List[str] = complex_patterns if complex_patterns is not None else []
        self.TASK_SIGNALS: List[str] = task_signals if task_signals is not None else []

    async def classify(
        self,
        message: str,
        has_skills: bool = True,
    ) -> str:
        """分类用户消息意图

        规则优先级（从高到低）：
          1. 无技能（has_skills=False）→ "chat"
          2. 若启用 LLM 且有配置 → 调用 _llm_classify
          3. 规则模式 → _rule_classify

        Args:
            message: 用户消息文本
            has_skills: 当前 agent 是否有可用技能（无技能则强行走 chat）

        Returns:
            str: "chat" | "task" | "complex"
        """
        # 无技能直接返回 chat
        if not has_skills:
            logger.debug(f"[IntentClassifier] has_skills=False → chat")
            return self.CHAT

        # LLM 模式（已实现）
        if self.use_llm and self.llm_config:
            return self._normalize(await self._llm_classify(message))

        # 规则模式
        return self._normalize(self._rule_classify(message))

    # ── 内部方法 ──

    @classmethod
    def _normalize(cls, intent: str) -> str:
        """批次10：complex 已退役。输出统一归一为两档——chat 保持，其余（complex/未知）一律 task。

        防御：即便旧模型/旧调用方仍产出 complex，也绝不向下游漏出（下游已无 complex 分支）。"""
        if intent == cls.CHAT:
            return cls.CHAT
        return cls.TASK

    def _rule_classify(self, message: str) -> str:
        """规则分类（当前默认实现）"""

        # 1. complex 规则命中（批次10 退役：命中即归 task，多步骤由工具循环消化）
        for pattern in self.COMPLEX_PATTERNS:
            if _re.search(pattern, message):
                logger.info(f"[IntentClassifier] complex 规则命中 → 归一 task: {pattern}")
                return self.TASK

        # 2. 闲聊判断
        is_short = len(message.strip()) <= self.SHORT_MSG_THRESHOLD
        is_chat = is_short
        for pattern in self.CHAT_PATTERNS:
            if pattern in message:
                is_chat = True
                break

        # 含办事信号则不判闲聊
        has_task_signal = any(s in message for s in self.TASK_SIGNALS)

        if is_chat and not has_task_signal:
            logger.info(
                f"[IntentClassifier] chat (len={len(message.strip())})"
            )
            return self.CHAT

        # 3. 默认 task
        logger.info("[IntentClassifier] task (default)")
        return self.TASK

    async def _llm_classify(self, message: str) -> str:
        """LLM 分类（已实现）

        设计思路：
          - 调用 LLM（3s 超时），prompt: "将以下消息分为 chat/task/complex"
          - 超时或异常降级为规则模式
        """
        try:
            from src.agent.llm.adapter import LLMAdapter
            
            # 构建分类 Prompt（批次10：只分两类，多步骤任务一律 task）
            system_prompt = (
                "你是意图分类器。将用户消息分为两类，只输出一个单词：\n"
                "- chat：闲聊、问候、自我介绍类（不需要调用工具）\n"
                "- task：所有任务/查询类，包括需要连续多次查询、多步骤、批量的复杂任务\n\n"
                "只输出 chat 或 task，不要输出其他内容。"
            )
            
            llm_adapter = LLMAdapter(self.llm_config)
            
            # 使用 asyncio.wait_for 包裹以支持超时
            response = await asyncio.wait_for(
                llm_adapter.call(
                    prompt=message,
                    system_prompt=system_prompt
                ),
                timeout=3.0
            )
            
            if response:
                # 解析 LLM 输出：取首词
                first_word = response.strip().split()[0].lower() if response.strip() else ""
                if first_word in (self.CHAT, self.TASK):
                    logger.info(f"[IntentClassifier] LLM 分类: {first_word} (response: {response[:50]})")
                    return first_word
                else:
                    logger.warning(f"[IntentClassifier] LLM 输出无法解析: '{response[:50]}'，降级为规则模式")
            else:
                logger.warning("[IntentClassifier] LLM 返回空响应，降级为规则模式")
                
        except asyncio.TimeoutError:
            logger.warning("[IntentClassifier] LLM 分类超时 (3s)，降级为规则模式")
        except Exception as e:
            logger.error(f"[IntentClassifier] LLM 分类异常: {e}，降级为规则模式")
            
        # 降级到规则模式
        logger.info("[IntentClassifier] 降级到规则模式分类")
        return self._rule_classify(message)

    # ── 便捷方法 ──

    async def is_chat(self, message: str, has_skills: bool = True) -> bool:
        """是否为闲聊"""
        intent = await self.classify(message, has_skills)
        return intent == self.CHAT

    async def is_task(self, message: str, has_skills: bool = True) -> bool:
        """是否为普通任务"""
        intent = await self.classify(message, has_skills)
        return intent == self.TASK

    async def is_complex(self, message: str, has_skills: bool = True) -> bool:
        """是否为复杂任务"""
        intent = await self.classify(message, has_skills)
        return intent == self.COMPLEX


# ── 全局单例 ──

_default_classifier: Optional[IntentClassifier] = None


def get_intent_classifier(llm_config: Optional[Dict] = None) -> IntentClassifier:
    """获取全局 IntentClassifier 单例
    
    Args:
        llm_config: LLM 配置（仅在首次调用时生效）
    """
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = IntentClassifier(llm_config=llm_config)
    elif llm_config:
        # 如果提供了新的 llm_config，更新它
        _default_classifier.llm_config = llm_config
    return _default_classifier
