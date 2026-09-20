"""
反思器 — 对话结束后异步触发反思 + 历史记录路由。

S5.4 新增 reflect() 方法：在对话结束后分析对话质量，产出 ReflectionReport。
反思结果写入 Memory（type=reflection），下一轮 system_prompt 注入。

使用示例：
    reflector = get_self_reflector()
    report = await reflector.reflect(
        session_id="abc123",
        agent_id="kunming",
        conversation_history=[...],
        llm_adapter=adapter,
    )
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConversationSample:
    user_message: str
    assistant_response: str
    session_id: str = ""


@dataclass
class SatisfactionAnalysis:
    score: float = 0.0
    confidence: float = 0.0
    positive_signals: List[str] = field(default_factory=list)
    negative_signals: List[str] = field(default_factory=list)
    summary: str = "当前仓库仅保留最小反思实现"


@dataclass
class Issue:
    issue_type: str
    severity: str
    description: str
    evidence: List[str] = field(default_factory=list)
    occurrence_count: int = 0


@dataclass
class ImprovementAction:
    action_type: str
    priority: str
    description: str
    expected_impact: str
    implementation_steps: List[str] = field(default_factory=list)
    estimated_effort: str = ""
    status: str = "pending"


@dataclass
class ReflectionReport:
    reflection_id: str
    agent_id: str
    timestamp: datetime
    period_start: datetime
    period_end: datetime
    conversations_analyzed: int
    satisfaction: SatisfactionAnalysis
    issues: List[Issue]
    improvement_plan: List[ImprovementAction]
    summary: str


class SelfReflector:
    def __init__(self):
        self._reflection_dir = Path("data/reflections")
        self._reflection_dir.mkdir(parents=True, exist_ok=True)

    async def start(self, gateway):
        return None

    async def stop(self):
        return None

    # ── ★ S5.4: reflect() 对话结束后触发 ──

    async def reflect(
        self,
        session_id: str,
        agent_id: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        llm_adapter=None,
    ) -> Dict[str, Any]:
        """对话结束后异步触发反思

        Args:
            session_id: 会话 ID
            agent_id: Agent ID
            conversation_history: 对话历史 [{"role":"user","content":"..."}, ...]
            llm_adapter: LLM 适配器（可选，用于深度反思）

        Returns:
            dict: 反思结果 {"insights": str, "quality": float, ...}
        """
        logger.info(
            f"[Reflector] 开始反思: session={session_id}, agent={agent_id}"
        )

        # 1. 统计摘要
        history = conversation_history or []
        summary = self._build_summary(session_id, agent_id, history)

        # 2. 反思（LLM 优先，降级为规则）
        if llm_adapter:
            try:
                reflection = await self._llm_reflect(llm_adapter, history, agent_id)
            except Exception as e:
                logger.warning(f"[Reflector] LLM 反思异常，降级为规则: {e}")
                reflection = self._rule_based_reflect(summary)
        else:
            reflection = self._rule_based_reflect(summary)

        # 3. 写入 Memory（不写文件，走 UnifiedMemoryManager）
        try:
            from src.memory.unified_manager import get_unified_manager
            from src.memory.types import MemoryType, MemoryCategory
            memory_mgr = get_unified_manager()
            await memory_mgr.add_memory(
                content=reflection.get("insights", ""),
                memory_type=MemoryType.AGENT_PRIVATE,
                agent_id=agent_id,
                category=MemoryCategory.LEARNING_OUTCOME,
                metadata={
                    "type": "reflection",
                    "quality": reflection.get("quality", 0.5),
                    "turn_count": summary.get("turn_count", 0),
                    "tools_used": summary.get("tools_used", []),
                    "timestamp": time.time(),
                }
            )
            logger.info(
                f"[Reflector] 反思已写入 Memory: "
                f"session={session_id}, quality={reflection.get('quality', 0.5)}"
            )
        except Exception as e:
            logger.warning(f"[Reflector] 写入 Memory 失败（降级）: {e}")

        # 4. 保留原文件存储（兼容已有 get_reflection_history）
        self._save_to_file(session_id, agent_id, reflection, summary)

        return reflection

    # ── 辅助 ──

    def _build_summary(
        self,
        session_id: str,
        agent_id: str,
        history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """从对话历史构建摘要"""
        user_messages = [m for m in history if m.get("role") == "user"]
        assistant_messages = [m for m in history if m.get("role") == "assistant"]
        turn_count = len(user_messages)

        # 提取工具使用
        tools_used = []
        for m in history:
            if m.get("tool_calls"):
                for tc in m.get("tool_calls", []):
                    tools_used.append(tc.get("tool_name", ""))

        return {
            "session_id": session_id,
            "agent_id": agent_id,
            "turn_count": turn_count,
            "tools_used": tools_used,
            "user_messages": [m.get("content", "")[:100] for m in user_messages],
            "assistant_messages": [m.get("content", "")[:100] for m in assistant_messages],
        }

    def _rule_based_reflect(self, summary: dict) -> dict:
        """规则反思（无 LLM 依赖）"""
        insights = []
        if summary.get("turn_count", 0) > 5:
            insights.append("本轮对话较长，考虑提前总结")
        if len(summary.get("tools_used", [])) == 0:
            insights.append("未使用工具，可能需要增强工具调用提示")
        quality = 0.7 if insights else 0.85
        return {
            "insights": "; ".join(insights) if insights else "对话质量良好",
            "quality": quality,
        }

    async def _llm_reflect(
        self,
        llm_adapter,
        history: List[Dict[str, Any]],
        agent_id: str,
    ) -> dict:
        """调用 LLM 做深度反思"""
        # 只取最近 10 条消息
        recent = history[-10:]
        conversation_text = "\n".join(
            f"[{m.get('role', '?')}]: {m.get('content', '')[:200]}"
            for m in recent
        )

        prompt = (
            f"反思以下对话的质量：\n\n{conversation_text}\n\n"
            "请评估：\n"
            "1. 助手回复是否准确、完整？\n"
            "2. 有什么可以改进的地方？\n"
            "3. 有什么经验教训？\n\n"
            "请严格按以下 JSON 格式回复（只输出 JSON）：\n"
            '{"insights": "反思内容", "quality": 0.85}'
        )

        raw = await llm_adapter.call(
            prompt=prompt,
            system_prompt="你是对话质量反思助手。只输出 JSON 格式，不要其他内容。",
        )

        try:
            import re as _re
            json_match = _re.search(r'\{[^{}]*\}', raw)
            data = json.loads(json_match.group() if json_match else raw)
            quality = float(data.get("quality", 0.7))
            return {
                "insights": data.get("insights", "对话质量良好"),
                "quality": max(0.0, min(1.0, quality)),
            }
        except Exception as e:
            logger.warning(f"[Reflector] LLM 输出解析失败: {e}")
            return {"insights": "LLM 反思解析失败", "quality": 0.5}

    def _save_to_file(
        self,
        session_id: str,
        agent_id: str,
        reflection: dict,
        summary: dict,
    ) -> None:
        """保存反思结果到文件（兼容 get_reflection_history）"""
        try:
            now = datetime.now()
            report = {
                "reflection_id": f"reflection_{agent_id}_{now.strftime('%Y%m%d%H%M%S')}",
                "agent_id": agent_id,
                "session_id": session_id,
                "timestamp": now.isoformat(),
                "period_start": now.isoformat(),
                "period_end": now.isoformat(),
                "conversations_analyzed": summary.get("turn_count", 0),
                "insights": reflection.get("insights", ""),
                "quality": reflection.get("quality", 0.5),
                "satisfaction": {
                    "score": reflection.get("quality", 0.5),
                    "confidence": 0.5,
                    "summary": reflection.get("insights", ""),
                },
                "issues": [],
                "improvement_plan": [],
                "summary": reflection.get("insights", ""),
            }
            file_path = self._reflection_dir / f"{report['reflection_id']}.json"
            file_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug(f"[Reflector] 反思文件已保存: {file_path}")
        except Exception as e:
            logger.warning(f"[Reflector] 保存反思文件失败: {e}")

    async def generate_reflection_report(self, agent_id: str, samples: List[ConversationSample]) -> ReflectionReport:
        now = datetime.now()
        report = ReflectionReport(
            reflection_id=f"reflection_{agent_id}_{now.strftime('%Y%m%d%H%M%S')}",
            agent_id=agent_id,
            timestamp=now,
            period_start=now,
            period_end=now,
            conversations_analyzed=len(samples),
            satisfaction=SatisfactionAnalysis(
                score=0.5 if samples else 0.0,
                confidence=0.1,
                summary="仅生成最小反思报告，未执行深度分析",
            ),
            issues=[],
            improvement_plan=[],
            summary="当前反思器为迁移后的最小兼容实现",
        )
        return report

    def get_reflection_history(self, agent_id: Optional[str] = None, limit: int = 10):
        history = []
        if not self._reflection_dir.exists():
            return history
        for json_file in sorted(self._reflection_dir.rglob("*.json"), reverse=True):
            try:
                import json

                data = json.loads(json_file.read_text(encoding="utf-8"))
                if agent_id and data.get("agent_id") != agent_id:
                    continue
                history.append(
                    ReflectionReport(
                        reflection_id=data.get("reflection_id", json_file.stem),
                        agent_id=data.get("agent_id", ""),
                        timestamp=datetime.fromisoformat(data["timestamp"]),
                        period_start=datetime.fromisoformat(data["period_start"]),
                        period_end=datetime.fromisoformat(data["period_end"]),
                        conversations_analyzed=data.get("conversations_analyzed", 0),
                        satisfaction=SatisfactionAnalysis(**data.get("satisfaction", {})),
                        issues=[Issue(**item) for item in data.get("issues", [])],
                        improvement_plan=[ImprovementAction(**item) for item in data.get("improvement_plan", [])],
                        summary=data.get("summary", ""),
                    )
                )
                if len(history) >= limit:
                    break
            except Exception as exc:
                logger.warning("读取反思历史失败: %s", exc)
        return history[:limit]

    async def implement_improvements(self, report: ReflectionReport, action_indices=None) -> int:
        if action_indices is None:
            return len(report.improvement_plan)
        return len([idx for idx in action_indices if 0 <= idx < len(report.improvement_plan)])


_instance = SelfReflector()


def get_self_reflector(gateway=None) -> SelfReflector:
    return _instance


def get_reflection_history(agent_id: Optional[str] = None, limit: int = 10) -> List[Any]:
    """模块级便捷函数：获取反思历史记录"""
    return _instance.get_reflection_history(agent_id=agent_id, limit=limit)
