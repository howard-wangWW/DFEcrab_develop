"""
用户事实自动提取器（阶段 B）

对话结束后，用 LLM 从本轮对话中提取高置信度的用户事实
（常驻地 / 职业 / 偏好 / 称呼等），写入用户级记忆 memories.json。

参考 Coze 的自动记忆机制：只提取用户明确表达的稳定事实，避免垃圾 KV 污染；
同 key 自动更新（UserMemoryManager.add_memory 已支持）。
"""

import json
import re
from typing import Any, Dict, List

from src.utils.logger import get_logger
from src.memory.user_manager import UserMemoryManager

logger = get_logger(__name__)


class UserFactExtractor:
    """用户事实提取器（LLM 驱动，fire-and-forget）"""

    async def extract(self, llm_adapter: Any, user_text: str, ai_response: str) -> List[Dict[str, str]]:
        """用 LLM 从对话中提取用户事实，返回 [{"key": ..., "value": ...}]"""
        user_text = (user_text or "").strip()[:500]
        ai_response = (ai_response or "").strip()[:500]
        if not user_text:
            return []

        prompt = (
            "你是一个用户画像提取器。请从下面的对话中提取高置信度的用户稳定事实。\n"
            "可提取的事实包括：常驻地/所在城市、职业/身份、偏好（回复风格、语言）、称呼、家庭/工作信息等。\n"
            "不要提取：临时任务请求、一次性指令、闲聊话题、AI 自己的内容。\n"
            "只输出 JSON 数组，不要任何多余文字或解释，格式示例：\n"
            '[{"key": "常驻地", "value": "昆明"}, {"key": "偏好", "value": "简洁回复"}]\n'
            "如果没有任何可提取的事实，只输出：[]\n\n"
            f"用户消息：{user_text}\n\n"
            f"AI 回复：{ai_response}"
        )
        try:
            result = await llm_adapter.chat_with_tools(
                messages=[{"role": "system", "content": prompt}],
                tools=[],
                tool_choice="none",
                temperature=0.1,
                max_tokens=200,
            )
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            return self._parse_json_array(content)
        except Exception as e:
            logger.debug(f"[Memory] 用户事实提取调用失败（静默）: {e}")
            return []

    @staticmethod
    def _parse_json_array(text: str) -> List[Dict[str, str]]:
        """解析 LLM 返回的 JSON 数组（容忍 ```json 围栏与前后缀文字）"""
        if not text:
            return []
        # 去掉 ```json ... ``` 围栏
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
        if m:
            text = m.group(1)
        else:
            m = re.search(r"\[.*\]", text, re.S)
            if m:
                text = m.group(0)
        try:
            data = json.loads(text)
        except Exception:
            return []
        if not isinstance(data, list):
            return []

        facts: List[Dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            value = str(item.get("value") or item.get("content") or "").strip()
            if key and value and len(key) <= 20 and len(value) <= 200:
                facts.append({"key": key, "value": value})
        return facts

    async def extract_and_store(
        self,
        llm_adapter: Any,
        user_text: str,
        ai_response: str,
        user_id: str,
    ) -> int:
        """提取并写入用户级记忆，返回写入条数（失败静默，不抛异常）"""
        if not user_id:
            return 0
        facts = await self.extract(llm_adapter, user_text, ai_response)
        stored = 0
        for f in facts:
            try:
                UserMemoryManager.add_memory(
                    user_id=user_id,
                    key=f["key"],
                    content=f["value"],
                    scope="user",
                    tags=["自动提取"],
                    source="conversation",
                )
                stored += 1
            except Exception as e:
                logger.debug(f"[Memory] 写入用户事实失败: {e}")
        if stored:
            logger.info(f"[Memory] 已自动提取 {stored} 条用户事实 (user={user_id})")
        return stored
