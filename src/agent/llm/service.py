"""
llm_service.py - LLM 服务封装层

提供与现有代码兼容的接口，内部使用 LLMAdapter 实现。
这是迁移到统一适配器的过渡层，后续可逐步替换。

使用方式：
    from src.agent.llm.service import LLMService
    
    service = LLMService(config)
    
    # 非流式调用
    response = await service.call(prompt, system_prompt)
    
    # 流式调用
    async for event in service.call_stream(prompt):
        ...
"""

import asyncio
import logging
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from src.agent.llm.adapter import LLMAdapter

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 服务封装
    
    提供与现有代码兼容的接口，内部使用 LLMAdapter。
    """
    
    def __init__(self, config: Dict):
        """初始化服务
        
        Args:
            config: 模型配置
        """
        self.adapter = LLMAdapter(config)
        self.config = config
        self.think_config = self.adapter.think_config
        
    async def call(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: Optional[Dict] = None
    ) -> str:
        """非流式调用（兼容接口）
        
        Returns:
            模型回复文本（已移除思考标签）
        """
        return await self.adapter.call(
            prompt, system_prompt, response_format
        )
    
    async def call_stream(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> AsyncGenerator[Dict, None]:
        """流式调用（兼容接口）
        
        生成的事件格式与旧版兼容：
        {"token": str, "reasoning": str}
        
        Yields:
            兼容格式的事件字典
        """
        async for event in self.adapter.call_stream(prompt, system_prompt):
            if event["type"] == "reasoning":
                yield {"token": "", "reasoning": event["content"]}
            elif event["type"] == "token":
                yield {"token": event["content"], "reasoning": ""}
            elif event["type"] == "done":
                break
            elif event["type"] == "error":
                logger.error(f"LLM 错误: {event['content']}")
                break
    
    async def call_with_reasoning(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> Tuple[str, str]:
        """调用并返回完整回复和思考内容
        
        Returns:
            (回复内容, 思考内容) 元组
        """
        return await self.adapter.call_with_reasoning(
            prompt, system_prompt
        )


class LegacyLLMService(LLMService):
    """旧版 LLM 服务（完全兼容原有接口）
    
    这个类提供了与原代码完全相同的方法签名，
    可以直接替换原有的 _call_llm 和 _call_llm_async_stream 方法。
    """
    
    async def _call_llm(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: Optional[Dict] = None
    ) -> str:
        """非流式调用（旧版接口名）"""
        return await self.call(prompt, system_prompt, response_format)
    
    async def _call_llm_async(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: Optional[Dict] = None
    ) -> str:
        """非流式调用（旧版接口名）"""
        return await self.call(prompt, system_prompt, response_format)
    
    async def _call_llm_async_stream(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> AsyncGenerator[Dict, None]:
        """流式调用（旧版接口名）
        
        Yields:
            {"token": str, "reasoning": str} 格式的事件
        """
        async for event in self.call_stream(prompt, system_prompt):
            yield event
