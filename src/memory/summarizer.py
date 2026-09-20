"""
会话滚动摘要器（阶段 C）

长对话上下文压缩：每 N 轮对话后，用 LLM 将「旧摘要 + 新增对话」合并为滚动摘要，
写入 session.summary 并在下一轮注入（_build_enhanced_message 已支持），
同时持久化到每日记忆 category=session_summary。

参考成熟平台：摘要随对话滚动更新，始终保留关键对话脉络，
而不是只取最近 N 条原始消息（超出窗口的上下文会自然丢失）。
"""

from typing import Any, Dict, List

from src.utils.logger import get_logger
from src.session.manager import get_session_manager
from src.memory.global_manager import get_global_memory_manager

logger = get_logger(__name__)


class SessionSummarizer:
    """会话滚动摘要器（LLM 驱动，fire-and-forget）"""

    def __init__(self, interval: int = 10):
        self.interval = max(3, interval)  # 每 N 轮触发一次

    async def maybe_rolling_summary(
        self,
        llm_adapter: Any,
        session_id: str,
        user_id: str = "",
    ) -> bool:
        """满足轮次条件时滚动摘要并持久化，返回是否执行了摘要"""
        try:
            sm = get_session_manager()
            session = sm.get_session(session_id)
            if not session:
                return False

            msgs = sm.get_messages_as_dicts(session_id, limit=2000)
            user_rounds = [m for m in msgs if m.get("role") == "user"]
            round_num = len(user_rounds)
            if round_num < self.interval:
                return False

            # 轮次去重：每过 interval 轮只摘要一次（重启后可能重复一次，可接受）
            last = int((session.metadata or {}).get("summary_round", 0) or 0)
            if round_num - last < self.interval:
                return False
            session.metadata["summary_round"] = round_num

            recent = msgs[-self.interval * 2:]
            new_summary = await self._llm_roll(llm_adapter, session.summary or "", self._format_msgs(recent))
            if not new_summary:
                return False

            sm.set_summary(session_id, new_summary)

            # 持久化到每日记忆（跨会话可查的对话脉络）
            try:
                gm = get_global_memory_manager()
                gm.save_daily_memory(
                    f"[会话滚动摘要] session={session_id} 第{round_num}轮\n{new_summary}",
                    category="session_summary",
                    user_id=user_id,
                )
            except Exception:
                pass

            logger.info(f"[Memory] 会话滚动摘要完成 (session={session_id}, round={round_num})")
            return True
        except Exception as e:
            logger.debug(f"[Memory] 会话滚动摘要失败（静默）: {e}")
            return False

    async def compact_session(
        self,
        llm_adapter: Any,
        session_id: str,
        user_id: str = "",
        keep_recent: int = 2,
    ) -> bool:
        """上下文自动压缩（P0，同步执行，参考 Claude Code AutoCompact / CodeBuddy Autocompact）。

        与 `maybe_rolling_summary` 的区别：
        - maybe_rolling_summary：按轮次（每 N 轮）触发，异步 fire-and-forget；
        - compact_session：按「上下文占用达到阈值」触发，同步执行，用于对话开始前的上下文缩减。

        做法（无损）：用 LLM 将「旧摘要 + 较老历史」合并为新摘要并更新 `session.summary`；
        会话消息本身不删除（历史接口仍可查全量），由调用方在注入上下文时减少原始历史条数。

        Args:
            llm_adapter: LLM 适配器
            session_id: 会话 ID
            user_id: 用户 ID
            keep_recent: 压缩时保留最近多少轮作为"新增"入料（每轮含 user+assistant）

        Returns:
            bool: 是否成功执行压缩；失败返回 False，调用方可降级为纯截断
        """
        try:
            sm = get_session_manager()
            session = sm.get_session(session_id)
            if not session:
                return False
            msgs = sm.get_messages_as_dicts(session_id, limit=2000)
            recent = msgs[-(keep_recent * 2):]
            new_summary = await self._llm_roll(llm_adapter, session.summary or "", self._format_msgs(recent))
            if not new_summary:
                logger.warning(f"[Memory] 自动压缩失败（LLM 未产出摘要）: session={session_id}")
                return False
            sm.set_summary(session_id, new_summary)
            round_num = len([m for m in msgs if m.get("role") == "user"])
            session.metadata["summary_round"] = round_num  # 与滚动摘要共用轮次标记，防重复
            # 持久化到每日记忆（跨会话可查对话脉络）
            try:
                gm = get_global_memory_manager()
                gm.save_daily_memory(
                    f"[上下文自动压缩] session={session_id}\n{new_summary}",
                    category="session_summary",
                    user_id=user_id,
                )
            except Exception:
                pass
            logger.info(f"[Memory] 上下文自动压缩完成 (session={session_id}, round={round_num})")
            return True
        except Exception as e:
            logger.debug(f"[Memory] 上下文自动压缩失败（静默）: {e}")
            return False

    async def _llm_roll(self, llm_adapter: Any, prev_summary: str, new_text: str) -> str:
        prompt = (
            "你是会话摘要助手。请把「旧摘要」和「新增对话」合并为一份滚动摘要。\n"
            "要求：\n"
            "1. 保留旧摘要中的重要信息（用户的稳定事实、进行中的任务、关键结论）\n"
            "2. 补充新增对话中的新进展、新决策\n"
            "3. 合并后控制在 300 字以内，用简洁的要点\n"
            "4. 只输出摘要文本，不要任何解释或前缀\n\n"
            f"【旧摘要】\n{prev_summary[:500] or '(无)'}\n\n"
            f"【新增对话】\n{new_text[:2000]}"
        )
        try:
            result = await llm_adapter.chat_with_tools(
                messages=[{"role": "system", "content": prompt}],
                tools=[],
                tool_choice="none",
                temperature=0.2,
                max_tokens=400,
            )
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            content = (content or "").strip().strip("`")
            return content[:500] if len(content) > 500 else content
        except Exception as e:
            logger.debug(f"[Memory] 滚动摘要 LLM 调用失败（静默）: {e}")
            return ""

    @staticmethod
    def _format_msgs(msgs: List[Dict]) -> str:
        parts = []
        for m in msgs:
            role = m.get("role", "")
            if role not in ("user", "assistant"):
                continue
            content = (m.get("content") or "")[:300]
            if not content:
                continue
            label = "用户" if role == "user" else "AI"
            parts.append(f"{label}: {content}")
        return "\n".join(parts)
