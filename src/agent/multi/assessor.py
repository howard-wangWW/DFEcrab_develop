"""
Self Assessor — 自我评估器

在 ReActLoop final 前评估回复质量，决定是否需要 HelpSeeker 求助。

评估流程：
  1. 规则快检（0 延迟）→ 分数够高就直接通过
  2. LLM 深度评估（规则分不够时触发）→ 给出最终 quality_score

使用示例：
    from src.agent.multi.assessor import SelfAssessor, get_self_assessor

    a = get_self_assessor()
    result = await a.assess("查询结果: 123", {"tools_used": 1})
    if result.need_help:
        # 走 HelpSeeker
        ...

质量分数定义：
  quality_score >= 0.6  → 通过，直接 final
  quality_score <  0.6  → 不通过，need_help=True
"""

from __future__ import annotations

import json
import logging
import re as _re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 枚举 + 数据类
# ──────────────────────────────────────────────────────────────

class TaskType(str, Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"


class AssessmentStatus(str, Enum):
    """评估状态"""
    PASSED  = "passed"   # 质量达标
    NEED_HELP = "need_help"  # 需要求助
    SKIPPED = "skipped"  # 跳过评估（如纯闲聊）


@dataclass
class Assessment:
    """评估结果"""

    # ── 质量 ──
    quality_score: float = 0.5          # 质量分数 [0.0, 1.0]
    quality_level: str = "medium"       # high / medium / low

    # ── 判定 ──
    need_help: bool = False             # 是否需要求助
    help_type: str = ""                 # retry / human / agent_handoff / ""
    reason: str = ""                    # 评估理由

    # ── 元信息 ──
    task_type: TaskType = TaskType.SIMPLE
    status: AssessmentStatus = AssessmentStatus.PASSED
    should_ask_user: bool = False
    required_experts: List[str] = field(default_factory=list)
    collaboration_mode: str = "single"
    assessment_method: str = "rule"     # rule / llm / skipped

    # ── 调试 ──
    rule_score: Optional[float] = None
    llm_raw_response: Optional[str] = None

    # ── 向后兼容 ──
    @property
    def needs_help(self) -> bool:
        """兼容旧代码"""
        return self.need_help

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quality_score": self.quality_score,
            "quality_level": self.quality_level,
            "need_help": self.need_help,
            "help_type": self.help_type,
            "reason": self.reason,
            "task_type": self.task_type.value,
            "status": self.status.value,
            "assessment_method": self.assessment_method,
        }


@dataclass
class Verification:
    """answer gate 验证结果（语义判定，零关键词表）"""
    passed: bool = True
    feedback: str = ""
    method: str = "llm"    # llm / skipped(无适配器) / fallback(调用或解析异常)


# ──────────────────────────────────────────────────────────────
# SelfAssessor
# ──────────────────────────────────────────────────────────────

class SelfAssessor:
    """自我评估器

    规则快检（零延迟） + LLM 深度评估（按需触发）。

    初始化参数:
        use_llm: bool = True    是否启用 LLM 深度评估
        quality_threshold: float = 0.6   质量通过线
    """

    # ── 规则快检阈值 ──
    RULE_PASS_THRESHOLD: float = 0.75     # 规则分 >= 0.75 直接通过，不调 LLM
    RULE_FAIL_THRESHOLD: float = 0.35     # 规则分 <= 0.35 直接判定不通过

    # ── 错误关键词（匹配到降分） ──
    ERROR_KEYWORDS: List[str] = [
        "error", "错误", "失败", "exception", "异常",
        "无法", "不能", "不支持", "超时", "timeout",
        "权限不足", "拒绝访问", "not found", "404",
        "抱歉，我无法", "sorry",
    ]

    # ── 高质量信号（匹配到加分） ──
    QUALITY_KEYWORDS: List[str] = [
        "成功", "完成", "已", "结果", "数据",
        "统计", "汇总", "分析", "建议",
    ]

    # ── 幻觉/思考体特征：命中的文本不是"给用户的答案"，规则快检不得给满分 ──
    #   现场实测（2026-09-10）：模型把分析过程当答案输出——"1. **理解决策**：当用户询问…
    #   我需要引导用户提供更多上下文…"，含"数据"等质量词、长度 561 字，旧规则算出 1.00
    #   并触发 Reflector 沉淀教训，形成"错误回答→错误教训→下轮跑偏"的恶性循环。
    META_TALK_MARKERS: List[str] = [
        "<think", "</think", "理解决策", "我需要先", "我需要引导", "用户询问",
        "根据当前的系统流程", "作为一个ai", "作为ai", "我的任务是", "接下来我需要",
    ]

    def __init__(
        self,
        use_llm: bool = True,
        quality_threshold: float = 0.6,
    ):
        self.use_llm = use_llm
        self.quality_threshold = quality_threshold
        self._llm_adapter = None  # 延迟注入

    def set_llm_adapter(self, adapter) -> None:
        """注入 LLM 适配器"""
        self._llm_adapter = adapter

    # ── 主入口 ──

    async def assess(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Assessment:
        """评估回复质量

        Args:
            content: 回复文本内容
            context: 上下文信息，如 {"tools_used": 1, "iterations": 2, "message": "原始用户消息"}

        Returns:
            Assessment: 评估结果
        """
        ctx = context or {}

        # 0. 纯闲聊跳过评估
        if self._is_trivial(content, ctx):
            return Assessment(
                quality_score=0.9,
                quality_level="high",
                need_help=False,
                reason="纯闲聊，跳过评估",
                status=AssessmentStatus.SKIPPED,
                assessment_method="skipped",
            )

        # 1. 规则快检
        rule_score = self._rule_check(content, ctx)
        rule_reason = self._rule_reason(rule_score)

        # 规则分够高 → 直接通过，不调 LLM
        if rule_score >= self.RULE_PASS_THRESHOLD:
            return Assessment(
                quality_score=rule_score,
                quality_level="high" if rule_score >= 0.8 else "medium",
                need_help=False,
                reason=rule_reason,
                assessment_method="rule",
                rule_score=rule_score,
            )

        # 规则分很低 → 直接判定不通过
        if rule_score <= self.RULE_FAIL_THRESHOLD:
            return Assessment(
                quality_score=rule_score,
                quality_level="low",
                need_help=True,
                help_type="retry",
                reason=rule_reason,
                status=AssessmentStatus.NEED_HELP,
                assessment_method="rule",
                rule_score=rule_score,
            )

        # 2. LLM 深度评估（规则分在中间区间 + use_llm=True）
        if self.use_llm and self._llm_adapter:
            try:
                llm_score, llm_need_help, llm_reason, llm_raw = await self._llm_assess(
                    content, ctx
                )
                return Assessment(
                    quality_score=llm_score,
                    quality_level="high" if llm_score >= 0.8 else ("medium" if llm_score >= 0.5 else "low"),
                    need_help=llm_need_help,
                    help_type="retry" if llm_need_help else "",
                    reason=llm_reason,
                    status=AssessmentStatus.NEED_HELP if llm_need_help else AssessmentStatus.PASSED,
                    assessment_method="llm",
                    rule_score=rule_score,
                    llm_raw_response=llm_raw,
                )
            except Exception as e:
                logger.warning(f"[Assessor] LLM 评估异常，降级为规则分: {e}")
                # 降级：用规则分
                return Assessment(
                    quality_score=rule_score,
                    quality_level="medium" if rule_score >= 0.5 else "low",
                    need_help=(rule_score < self.quality_threshold),
                    help_type="retry" if rule_score < self.quality_threshold else "",
                    reason=f"{rule_reason} (LLM降级)",
                    assessment_method="rule",
                    rule_score=rule_score,
                )

        # 3. 无 LLM → 规则分直接判断
        need_help = rule_score < self.quality_threshold
        return Assessment(
            quality_score=rule_score,
            quality_level="medium" if rule_score >= 0.5 else "low",
            need_help=need_help,
            help_type="retry" if need_help else "",
            reason=rule_reason,
            status=AssessmentStatus.NEED_HELP if need_help else AssessmentStatus.PASSED,
            assessment_method="rule",
            rule_score=rule_score,
        )

    # ── answer gate：语义验证 ──

    async def verify(
        self,
        content: str,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Verification:
        """★ answer gate：语义验证工具型最终回复（纯 LLM 判定，零关键词表）。

        检查三项（任一项不满足则 passed=False）：
          1. 数据支撑：回复中的量化结论是否来自已调用工具的真实结果；
          2. 完成度：回复是否含"待调用工具确认"类占位，导致核心结论未定；
          3. 对象一致性：回复的分析/操作对象是否与用户请求对象一致。

        Returns:
            Verification；无 LLM 适配器 / 调用或解析异常时默认放行（passed=True）。
        """
        ctx = ctx or {}
        if not self._llm_adapter:
            return Verification(method="skipped")
        _tool_names = ctx.get("tool_names") or []
        _tools_str = ", ".join(str(t) for t in _tool_names) if _tool_names else "（未调用工具）"
        prompt = (
            "你是对话质检员。判断助手对工具型任务的最终回复能否直接交付，"
            '只输出 JSON：{"pass": true/false, "feedback": "一句话说明问题"}，不要输出其他文字。\n\n'
            f"用户请求: {str(ctx.get('message', ''))[:300]}\n"
            f"助手已调用工具: {_tools_str}\n"
            f"助手最终回复: {content[:1500]}\n\n"
            "检查三点（任一点不满足则 pass=false）：\n"
            "1. 数据支撑：回复中出现的数量/户数/数值等量化结论，是否由已调用工具的真实结果得出；"
            "纯估算或编造则判不通过。\n"
            "2. 完成度：回复是否仍包含'待调用工具确认/需核实/等数据返回'类未完成占位，"
            "使核心结论悬而未决；有则判不通过。\n"
            "3. 对象一致性：回复分析或操作的对象（线路、设备、变电站、馈线等名称）"
            "是否与用户请求的对象一致；明显不一致（如拿错线路）则判不通过。\n"
            "feedback 用一句话（中文）指出具体问题；全部满足时 feedback 可为空字符串。"
        )
        try:
            raw = await self._llm_adapter.call(
                prompt=prompt,
                system_prompt="你是质检员。只输出合法 JSON，不要任何多余文字。",
            )
        except Exception as e:
            logger.warning(f"[Assessor/Verify] LLM 调用失败，默认放行: {e}")
            return Verification(method="fallback")
        try:
            raw_text = str(raw or "").strip()
            m = _re.search(r"\{.*\}", raw_text, _re.S)
            data = json.loads(m.group()) if m else json.loads(raw_text)
            passed = bool(data.get("pass", True))
            feedback = str(data.get("feedback", "") or "")
            logger.info(f"[Assessor/Verify] passed={passed} | feedback={feedback[:80]}")
            return Verification(passed=passed, feedback=feedback, method="llm")
        except Exception as e:
            logger.warning(f"[Assessor/Verify] 输出解析失败，默认放行: {e}, raw={str(raw)[:120]}")
            return Verification(method="fallback")

    # ── 规则快检 ──

    def _rule_check(
        self,
        content: str,
        ctx: Dict[str, Any],
    ) -> float:
        """规则快速评分 [0.0, 1.0]

        评分维度：
          - 是否有工具调用（tools_used > 0 → +0.3）
          - 内容长度（>20 字 → +0.1，>50 字 → +0.2）
          - 是否含错误关键词（-0.3 ~ -0.5）
          - 是否含高质量信号（+0.1 ~ +0.2）
        """
        score = 0.5  # 基准分

        # 工具调用
        tools_used = ctx.get("tools_used", 0)
        if tools_used > 0:
            score += 0.3
        else:
            score -= 0.1

        # 内容长度
        content_len = len(content.strip())
        if content_len > 50:
            score += 0.2
        elif content_len > 20:
            score += 0.1
        elif content_len < 5:
            score -= 0.2

        # 错误关键词
        error_count = sum(
            1 for kw in self.ERROR_KEYWORDS
            if kw.lower() in content.lower()
        )
        if error_count >= 2:
            score -= 0.5
        elif error_count == 1:
            score -= 0.3

        # 高质量信号
        quality_count = sum(
            1 for kw in self.QUALITY_KEYWORDS
            if kw in content
        )
        score += min(quality_count * 0.1, 0.2)

        # 幻觉/思考体特征：把分析过程当答案输出 → 压到不通过区间（交由重试/深度评估），
        #   不再让"长文本 + 质量词"把错误回答算成满分（防脏记忆回流）。
        meta_hit = sum(1 for mk in self.META_TALK_MARKERS if mk in content.lower())
        if meta_hit:
            score = min(score, self.RULE_FAIL_THRESHOLD)

        return max(0.0, min(1.0, score))

    def _rule_reason(self, score: float) -> str:
        """规则分 → 理由文本"""
        if score >= 0.8:
            return "规则快检：质量高，直接通过"
        elif score >= 0.6:
            return "规则快检：质量中等"
        elif score >= 0.4:
            return "规则快检：质量偏低"
        else:
            return "规则快检：质量差，需重试"

    # ── LLM 深度评估 ──

    async def _llm_assess(
        self,
        content: str,
        ctx: Dict[str, Any],
    ) -> tuple:
        """调用 LLM 评估回复质量

        Returns:
            (quality_score, need_help, reason, raw_response)
        """
        prompt = (
            f"评估以下助手回复的质量，给出 0.0-1.0 的分数：\n\n"
            f"用户消息: {ctx.get('message', '(无)')[:200]}\n"
            f"助手回复: {content[:500]}\n"
            f"工具调用次数: {ctx.get('tools_used', 0)}\n"
            f"迭代次数: {ctx.get('iterations', 0)}\n\n"
            "评估标准：\n"
            "- 是否完整回答了用户问题\n"
            "- 回答是否准确、有用\n"
            "- 是否需要进一步澄清或重试\n\n"
            "请严格按以下 JSON 格式回复（只输出 JSON，不要其他内容）：\n"
            '{"score": 0.8, "need_help": false, "reason": "回答完整准确"}'
        )

        raw = await self._llm_adapter.call(
            prompt=prompt,
            system_prompt=(
                "你是质量评估助手。只输出 JSON 格式的评估结果，不要输出其他内容。"
            ),
        )

        # 解析 LLM 输出
        try:
            # 尝试提取 JSON
            json_match = _re.search(r'\{[^}]+\}', raw)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(raw)

            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            need_help = bool(data.get("need_help", False))
            reason = str(data.get("reason", "LLM 评估"))

            logger.info(
                f"[Assessor] LLM 评估: score={score:.2f}, "
                f"need_help={need_help}, reason={reason[:50]}"
            )

            return score, need_help, reason, raw

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # 解析失败 → 降级给默认分
            logger.warning(f"[Assessor] LLM 输出解析失败: {e}, raw={raw[:100]}")
            return 0.5, False, f"LLM 解析失败，默认分 0.5 ({str(e)[:50]})", raw

    # ── 辅助 ──

    def _is_trivial(self, content: str, ctx: Dict[str, Any]) -> bool:
        """判断是否为纯闲聊（跳过评估）"""
        if ctx.get("tools_used", 0) > 0:
            return False
        if ctx.get("iterations", 0) > 0:
            return False

        content_stripped = content.strip()
        # 内容很短且无工具调用 → 闲聊
        if len(content_stripped) < 15:
            # 但如果有错误关键词 → 不能跳过，需要评估
            content_lower = content_stripped.lower()
            has_error = any(
                kw.lower() in content_lower
                for kw in self.ERROR_KEYWORDS
            )
            if has_error:
                return False
            return True
        return False


# ──────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────

_instance: Optional[SelfAssessor] = None


def get_self_assessor() -> SelfAssessor:
    """获取全局 SelfAssessor 单例"""
    global _instance
    if _instance is None:
        _instance = SelfAssessor()
    return _instance


def reset_self_assessor() -> None:
    """重置全局单例"""
    global _instance
    _instance = None
