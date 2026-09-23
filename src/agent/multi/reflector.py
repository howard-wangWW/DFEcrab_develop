"""
Reflector — 反思器

在 ReAct 循环结束后，对执行过程做结构化反思，产出：
  - lessons: 本次执行的经验教训
  - score: 自我评分 [0.0, 1.0]
  - improvements: 下次改进建议

反思结果写入 Memory（daily + long_term），下一轮 ReActLoop 通过
system_prompt 注入。

使用示例：
    from src.agent.multi.reflector import Reflector, get_reflector

    r = get_reflector()
    result = await r.reflect(
        user_message="帮我查数据",
        response="查询成功，共 12 条",
        tools_used=["dm_query"],
        iterations=2,
        assessment=None,
        agent_id="kunming",
    )
    # result.lessons → ["工具 dm_query 需要加日期过滤参数"]
    # result.score → 0.85
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────────────────────

@dataclass
class ReflectionResult:
    """反思结果"""

    # ── 核心字段 ──
    lessons: List[str] = field(default_factory=list)
    score: float = 0.5              # 自我评分 [0.0, 1.0]
    improvements: List[str] = field(default_factory=list)

    # ── 摘要 ──
    summary: str = ""               # 一句话总结

    # ── 元信息 ──
    agent_id: str = ""
    timestamp: float = field(default_factory=time.time)
    tools_used: List[str] = field(default_factory=list)
    iterations: int = 0
    assessment_score: Optional[float] = None

    # ── 原始 ──
    _raw: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lessons": self.lessons,
            "score": self.score,
            "improvements": self.improvements,
            "summary": self.summary,
            "agent_id": self.agent_id,
            "tools_used": self.tools_used,
            "iterations": self.iterations,
        }

    def to_prompt_text(self) -> str:
        """转为 system_prompt 注入文本"""
        if not self.lessons and not self.improvements:
            return ""

        lines = ["## 上次执行反思（Reflector）"]
        if self.summary:
            lines.append(f"总结: {self.summary}")
        lines.append(f"自我评分: {self.score:.2f}")
        if self.lessons:
            lines.append("经验教训:")
            for i, lesson in enumerate(self.lessons, 1):
                lines.append(f"  {i}. {lesson}")
        if self.improvements:
            lines.append("改进建议:")
            for i, imp in enumerate(self.improvements, 1):
                lines.append(f"  {i}. {imp}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# Reflector
# ──────────────────────────────────────────────────────────────

class Reflector:
    """反思器

    支持两种模式：
      - 规则快评（无需 LLM）：基于 metrics 给分
      - LLM 深度反思（推荐）：调用 LLM 产出 lessons
    """

    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm
        self._llm_adapter = None

    def set_llm_adapter(self, adapter) -> None:
        """注入 LLM 适配器"""
        self._llm_adapter = adapter

    # ── 主入口 ──

    async def reflect(
        self,
        user_message: str,
        response: str,
        tools_used: List[str],
        iterations: int = 1,
        assessment: Optional[Any] = None,
        agent_id: str = "dfecrab",
    ) -> ReflectionResult:
        """执行反思

        Args:
            user_message: 原始用户消息
            response: 最终回复
            tools_used: 使用的工具列表
            iterations: 迭代次数
            assessment: Assessor 评估结果（可选）
            agent_id: Agent ID

        Returns:
            ReflectionResult: 反思结果
        """
        logger.info(
            f"[Reflector] 开始反思: agent={agent_id}, "
            f"tools={len(tools_used)}, iterations={iterations}"
        )

        # 1. 规则快评
        rule_score = self._quick_score(tools_used, iterations, response)

        # 2. LLM 深度反思
        if self.use_llm and self._llm_adapter:
            try:
                llm_result = await self._llm_reflect(
                    user_message, response, tools_used, iterations,
                    assessment=assessment,
                )
                # 合并规则分和 LLM 分
                score = (rule_score + llm_result.score) / 2
                return ReflectionResult(
                    lessons=llm_result.lessons,
                    score=round(score, 2),
                    improvements=llm_result.improvements,
                    summary=llm_result.summary,
                    agent_id=agent_id,
                    tools_used=tools_used,
                    iterations=iterations,
                    assessment_score=assessment.quality_score if assessment else None,
                    _raw=llm_result._raw,
                )
            except Exception as e:
                logger.warning(f"[Reflector] LLM 反思异常，降级为规则快评: {e}")

        # 3. 降级：纯规则快评
        return ReflectionResult(
            lessons=self._rule_lessons(tools_used, iterations, response),
            score=rule_score,
            improvements=[],
            summary=f"执行 {len(tools_used)} 个工具，{iterations} 轮迭代",
            agent_id=agent_id,
            tools_used=tools_used,
            iterations=iterations,
            assessment_score=assessment.quality_score if assessment else None,
        )

    # ── 规则快评 ──

    def _quick_score(
        self,
        tools_used: List[str],
        iterations: int,
        response: str,
    ) -> float:
        """快速评分（基于 metrics）"""
        score = 0.5

        if len(tools_used) > 0:
            score += 0.2
        if iterations <= 2:
            score += 0.1
        elif iterations > 5:
            score -= 0.2

        # 回复内容质量信号
        resp_len = len(response.strip())
        if resp_len > 100:
            score += 0.15
        elif resp_len < 10:
            score -= 0.15

        # 错误信号
        error_signals = ["error", "错误", "失败", "无法", "抱歉"]
        error_count = sum(1 for s in error_signals if s.lower() in response.lower())
        score -= min(error_count * 0.1, 0.3)

        return max(0.0, min(1.0, score))

    def _rule_lessons(
        self,
        tools_used: List[str],
        iterations: int,
        response: str,
    ) -> List[str]:
        """从 metrics 中提取简单教训"""
        lessons = []
        if iterations > 5:
            lessons.append(f"执行效率低：{iterations} 轮迭代，建议减少工具调用次数")
        if not tools_used:
            lessons.append("未调用任何工具，纯文本回复可能不够准确")
        if len(response.strip()) < 20:
            lessons.append("回复内容偏短，可能不够完整")
        return lessons

    # ── LLM 深度反思 ──

    async def _llm_reflect(
        self,
        user_message: str,
        response: str,
        tools_used: List[str],
        iterations: int,
        assessment: Optional[Any] = None,
    ) -> ReflectionResult:
        """调用 LLM 做深度反思。

        ★ 两处优化：
          1) 把 Assessor 的评估结论一并喂给反思模型。原先 reflect() 收下了 assessment
             却从未传给这里，导致评估与反思各自为政、信息白白丢失。
          2) 给出评分锚点（rubric）。原先 LLM 凭感觉打分，各次之间不可比，
             与规则分做 (rule+llm)/2 盲平均后更是失真。
        """
        assess_block = ""
        if assessment is not None:
            try:
                parts = [f"评估质量分: {getattr(assessment, 'quality_score', None)}"]
                reason = getattr(assessment, "reason", None)
                if reason:
                    parts.append(f"评估理由: {str(reason)[:200]}")
                if getattr(assessment, "need_help", None):
                    parts.append("评估结论: 需要外部协助")
                assess_block = "、".join(parts) + "\n"
            except Exception:
                assess_block = ""

        prompt = (
            f"反思以下对话执行过程：\n\n"
            f"用户消息: {user_message[:300]}\n"
            f"助手回复: {response[:500]}\n"
            f"使用工具: {', '.join(tools_used) if tools_used else '(无)'}\n"
            f"迭代次数: {iterations}\n"
            f"{assess_block}\n"
            "请从以下维度反思：\n"
            "1. 执行过程是否高效？\n"
            "2. 回复是否准确完整？\n"
            "3. 有哪些经验教训？\n"
            "4. 下次如何改进？\n\n"
            "评分锚点（请严格参照，保证各次打分可比）：\n"
            "  0.9-1.0 完全达成，工具调用精准，一次成功\n"
            "  0.7-0.8 基本达成，少量冗余调用或表述不够精炼\n"
            "  0.5-0.6 部分达成，走了弯路但最终答对\n"
            "  0.3-0.4 答非所问或工具误用，需重试多次\n"
            "  0.0-0.2 失败，未产出有效结果\n\n"
            "请严格按以下 JSON 格式回复（只输出 JSON，不要其他内容）：\n"
            '{"score": 0.85, "lessons": ["教训1", "教训2"], '
            '"improvements": ["建议1"], "summary": "一句话总结"}'
        )

        raw = await self._llm_adapter.call(
            prompt=prompt,
            system_prompt=(
                "你是执行反思助手。只输出 JSON 格式的反思结果，不要输出其他内容。"
                "score 范围 0.0-1.0，lessons 和 improvements 是字符串列表。"
            ),
        )

        # 解析
        import re as _re
        try:
            json_match = _re.search(r'\{[^{}]*\}', raw)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(raw)

            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            lessons = data.get("lessons", [])
            improvements = data.get("improvements", [])
            summary = data.get("summary", "")

            if isinstance(lessons, str):
                lessons = [lessons]
            if isinstance(improvements, str):
                improvements = [improvements]

            logger.info(
                f"[Reflector] LLM 反思: score={score:.2f}, "
                f"lessons={len(lessons)}, improvements={len(improvements)}"
            )

            return ReflectionResult(
                lessons=lessons[:5],
                score=score,
                improvements=improvements[:3],
                summary=summary,
                _raw=raw,
            )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"[Reflector] LLM 输出解析失败: {e}")
            return ReflectionResult(
                lessons=[],
                score=0.5,
                improvements=[],
                summary=f"反思解析失败: {str(e)[:50]}",
                _raw=raw,
            )


# ──────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────

_instance: Optional[Reflector] = None


def get_reflector() -> Reflector:
    """获取全局 Reflector 单例"""
    global _instance
    if _instance is None:
        _instance = Reflector()
    return _instance


def reset_reflector() -> None:
    """重置全局单例"""
    global _instance
    _instance = None