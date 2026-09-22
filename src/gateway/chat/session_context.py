"""会话上下文构建（Session Context Domain）

从 `grpc_server.GatewayV2GRPC` 逐字迁出：

    _generate_session_summary  会话摘要（LLM 生成，失败降级为前 30 字截取）
    _build_enhanced_message    把时间/主题/历史拼进用户消息，供 Manager 理解上下文

依赖单向：不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

from src.utils.time_parser import get_time_context

logger = logging.getLogger(__name__)


class SessionContextMixin:
    """会话摘要与消息增强（方法实现逐字自 grpc_server 迁出）"""


    async def _generate_session_summary(self, message: str) -> str:
        """生成会话摘要：调用 LLM 生成 <=30 字摘要，失败时降级为截取前30字"""
        from src.agent.llm.think import remove_think_tags, get_default_think_config
        
        # 先尝试 LLM 生成真实摘要
        try:
            llm_config = self._get_gateway_llm_config()
            if llm_config:
                from src.agent.llm.adapter import LLMAdapter
                llm = LLMAdapter(llm_config)
                prompt = f"请为以下对话生成一个不超过30字的简短摘要：\n\n用户: {message}"
                summary = await llm.call(
                    prompt=prompt,
                    system_prompt="你是会话摘要助手，只输出不超过30字的摘要，不要输出其他内容。",
                    max_tokens=50
                )
                summary = summary.strip()
                if summary and len(summary) <= 50:
                    logger.info(f"LLM 生成会话摘要: {summary}")
                    return summary[:30] + "..." if len(summary) > 30 else summary
        except Exception as e:
            logger.debug(f"LLM 摘要生成失败，降级为截取: {e}")
        
        # 降级：直接截取用户消息前30字符
        think_config = get_default_think_config()
        clean = remove_think_tags(message, think_config)
        clean = re.sub(r'\n+', ' ', clean).strip()
        return clean[:30] + "..." if len(clean) > 30 else clean
    
    def _build_enhanced_message(
        self,
        message: str,
        session_id: str,
        session_summary: str,
        session_history: List[Dict]
    ) -> str:
        """
        构建增强的消息，包含 session 上下文和当前时间信息
        
        这样 Manager Agent 可以了解：
        1. 当前会话的主题
        2. 之前的对话历史
        3. 用户消息在上下文中的位置
        4. 当前时间（用户消息中的相对时间已被 Gateway 解析为具体日期）
        """
        # 获取时间上下文
        time_context = get_time_context()
        
        # 如果有历史消息，添加到消息前面作为上下文
        if session_history:
            history_text = "\n\n".join([
                f"[{'用户' if m['role'] == 'user' else '助手'}]: {m['content']}"
                for m in session_history[-5:]  # 最近 5 条
            ])
            
            enhanced = f"""{time_context}

[会话上下文]
主题: {session_summary}
Session ID: {session_id}

历史对话:
{history_text}

---
当前消息: {message}"""
        else:
            enhanced = f"""{time_context}

[新会话]
主题: {session_summary}
Session ID: {session_id}

消息: {message}"""
        
        return enhanced

    # ==================== Session 管理接口 ====================
