"""
llm_adapter.py - 统一 LLM 调用适配器

提供统一的 LLM 调用接口，支持多模型、多思考格式。
不依赖 LangChain，使用纯 httpx 实现，避免依赖冲突。

核心功能：
1. 统一的同步/异步调用接口
2. 流式调用自动处理思考内容（reasoning）
3. 配置化的思考标签解析
4. 模型自动切换与降级

使用示例：
    from src.agent.llm.adapter import LLMAdapter
    
    adapter = LLMAdapter(config)
    
    # 非流式调用
    response = await adapter.call(prompt, system_prompt="You are helpful")
    
    # 流式调用（自动处理思考内容）
    async for event in adapter.call_stream(prompt):
        if event["type"] == "reasoning":
            print(f"思考中: {event['content']}")
        elif event["type"] == "token":
            print(f"回复: {event['content']}")
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from src.agent.llm.think import (
    get_default_think_config,
    get_think_config_for_model,
    extract_think_content,
    extract_thinking_and_content,  # ★ v4.0 新增
)
from src.utils.context_usage import (
    DEFAULT_CONTEXT_LENGTH,
    estimate_tokens,
    compact_buffer,
)
from src.utils.api_base import normalize_api_base

logger = logging.getLogger(__name__)


class LLMAdapter:
    """统一的 LLM 调用适配器
    
    封装所有 LLM 调用逻辑，包括：
    - 请求构建
    - 响应解析
    - 思考内容提取
    - 错误处理
    """
    
    def __init__(self, config: Dict):
        """初始化适配器
        
        Args:
            config: 模型配置，包含 api_base, model_name, timeout 等
        """
        self.config = config
        # ★ 统一清洗：即使调用方传了完整接口地址也剥成根地址，下游再拼 /chat/completions 不会重复
        self.api_base = normalize_api_base(config.get("api_base", ""))
        self.model_name = config.get("model_name", "default")
        self.timeout = config.get("timeout", 600)
        self.max_tokens = config.get("max_tokens", 2048)
        self.api_key = config.get("api_key", "")
        self.temperature = config.get("temperature", 0.1)
        # ★ 上下文窗口大小（来自 config/dfecrab.json 的 context_length），用于上下文占比计算
        self.context_length = int(config.get("context_length", DEFAULT_CONTEXT_LENGTH) or DEFAULT_CONTEXT_LENGTH)
        
        # 复用连接池的异步客户端（懒加载），避免每次调用新建 TCP/TLS 连接
        self._client = None

        # 获取思考配置
        self.think_config = get_think_config_for_model(config)

        # ★ 思考开关透传（Qwen3 等混合思考模型）：provider 配置 chat_template_kwargs
        #   或便捷键 enable_thinking；未配置则不发送该字段（其它现场零影响）。
        #   现场实测：昆明 qwen3_a3b 开思考时首轮 85s 长考且不调工具，置 false 后秒级出调用。
        self.chat_template_kwargs: Dict[str, Any] = {}
        _ctk = config.get("chat_template_kwargs")
        if isinstance(_ctk, dict):
            self.chat_template_kwargs.update(_ctk)
        if config.get("enable_thinking") is not None:
            self.chat_template_kwargs["enable_thinking"] = bool(config.get("enable_thinking"))

    def _estimate_input_tokens(self, messages: List[Dict], tools: Optional[List[Dict]] = None) -> int:
        """本地粗估本轮发送的输入 token 数（message 文本/结构 + 工具 schema），
        对齐 context_usage.estimate_tokens 的口径。"""
        total = 0
        for m in messages or []:
            if isinstance(m, dict):
                total += estimate_tokens(m.get("content") or "")
                tc = m.get("tool_calls")
                if tc:
                    total += estimate_tokens(json.dumps(tc, ensure_ascii=False, default=str))
            else:
                total += estimate_tokens(str(m))
        if tools:
            total += estimate_tokens(json.dumps(tools, ensure_ascii=False, default=str))
        return total

    def _clamp_max_tokens(self, payload: Dict, messages: List[Dict], tools: Optional[List[Dict]] = None) -> None:
        """★ vLLM 防护：vLLM 把 max_tokens 当硬约束，max_tokens+input > max_model_len 时直接 400，
        不会像 OpenAI 那样截断（见 vllm#42474）。发前把 max_tokens 钳到剩余上下文预算内，
        宁可少生成也不拒单。buffer 与自动压缩阈值对齐（compact_buffer，默认 8%）。"""
        if self.context_length <= 0:
            return
        try:
            _input = self._estimate_input_tokens(messages, tools)
        except Exception:
            return
        _buffer = compact_buffer(self.context_length)   # 8% 预留
        _budget = self.context_length - _input - _buffer
        if _budget <= 0:
            return  # 输入已近占满 → 交由上层 auto_compact 先压缩，此处不强行改以免越界
        _cur = payload.get("max_tokens")
        if _cur is not None and _cur > _budget:
            payload["max_tokens"] = max(1, int(_budget))

    def _get_client(self):
        """懒加载并复用 httpx.AsyncClient，高并发下减少握手开销。"""
        import httpx
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=50),
            )
        return self._client
    
    def _build_headers(self) -> Dict:
        """构建请求头"""
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    def _build_payload(
        self,
        messages: List[Dict],
        response_format: Optional[Dict] = None,
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict:
        """构建请求体"""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if response_format:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        # ★ 思考开关（provider 配置 chat_template_kwargs / enable_thinking）；未配置不发送
        if self.chat_template_kwargs:
            payload["chat_template_kwargs"] = dict(self.chat_template_kwargs)
        # ★ 流式请求显式要求返回 usage（vLLM/OpenAI 兼容），供上下文占比统计
        if stream:
            payload["stream_options"] = {"include_usage": True}
        # ★ vLLM 防护：默认 max_tokens 也先钳到剩余上下文预算内（调用方显式覆盖后仍会再次 clamp）
        self._clamp_max_tokens(payload, messages, tools)
        return payload
    
    async def call(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: Optional[Dict] = None,
        with_usage: bool = False
    ) -> Any:
        """非流式调用 LLM
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            response_format: 响应格式要求
            with_usage: True 时返回 (回复文本, usage dict)；False 时只返回回复文本。
                用于上下文占比统计（LLM 响应带 usage.prompt_tokens 等）。
            
        Returns:
            默认返回模型回复文本（已移除思考标签）；with_usage=True 时返回 (content, usage)
        """
        if not self.api_base:
            return ("", {}) if with_usage else ""
        
        usage: Dict = {}
        content = ""
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            url = f"{self.api_base}/chat/completions"
            payload = self._build_payload(messages, response_format, stream=False)
            headers = self._build_headers()
            
            client = self._get_client()
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if "usage" in data and isinstance(data["usage"], dict):
                usage = data["usage"]
            
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"]
                # ★ v4.0: 不再删除思考，只返回正文（思考由 call_stream 单独输出）
                _, content = extract_thinking_and_content(content, self.think_config)
                return (content, usage) if with_usage else content
                    
        except Exception as e:
            logger.error(f"❌ LLM 调用失败: {e}")
        
        return (content, usage) if with_usage else content
    
    async def call_stream(
        self,
        prompt: str,
        system_prompt: str = "",
        response_format: Optional[Dict] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Dict, None]:
        """流式调用 LLM，自动处理思考内容
        
        生成的事件格式：
        {"type": "reasoning", "content": str}  # 思考内容
        {"type": "token", "content": str}      # 回复内容
        {"type": "done"}                       # 流结束
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示
            response_format: 响应格式要求
            max_tokens: 覆盖默认 max_tokens（Manager 精简思考用）
            
        Yields:
            事件字典，包含 type 和 content 字段
        """
        if not self.api_base:
            yield {"type": "done"}
            return
        
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            url = f"{self.api_base}/chat/completions"
            payload = self._build_payload(messages, response_format, stream=True)
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            # ★ vLLM 防护：显式覆盖后仍按剩余上下文预算钳制，避免 400
            self._clamp_max_tokens(payload, messages)
            headers = self._build_headers()
            
            # 思考配置
            start_tags = self.think_config["start_tags"]
            end_tags = self.think_config["end_tags"]
            reasoning_fields = self.think_config["reasoning_fields"]
            max_tag_len = self.think_config["max_tag_len"]
            
            # 状态机变量
            in_think = False
            tag_buffer = ""
            reasoning_count = 0
            
            logger.debug(f"🧠 [LLMAdapter] think_config: start_tags={start_tags}, end_tags={end_tags}")
            
            client = self._get_client()
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()
                    
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        
                        data_str = line[6:].strip()
                        
                        # 流结束
                        if data_str == "[DONE]":
                            if tag_buffer:
                                if in_think:
                                    reasoning_count += 1
                                    yield {"type": "reasoning", "content": tag_buffer}
                                else:
                                    yield {"type": "token", "content": tag_buffer}
                                tag_buffer = ""
                            
                            logger.debug(f"📦 [LLMAdapter] 流结束，共 {reasoning_count} 个 reasoning 事件")
                            yield {"type": "done"}
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            # ★ 上下文统计：捕获带 usage 的块（vLLM/OpenAI 兼容，其 choices 为空，需在取 delta 前处理）
                            if chunk.get("usage"):
                                yield {"type": "usage", "usage": chunk["usage"]}
                                continue
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content", "")
                            
                            # 1. 检查 reasoning 字段
                            reasoning = ""
                            for field in reasoning_fields:
                                val = delta.get(field, "")
                                if val:
                                    reasoning = val
                                    break
                            
                            if reasoning:
                                reasoning_count += 1
                                yield {"type": "reasoning", "content": reasoning}
                                continue
                            
                            # 空 token 跳过
                            if not token:
                                continue
                            
                            # 2. 处理 content 中的思考标签
                            combined = tag_buffer + token
                            
                            while combined:
                                # 查找所有开始标签和结束标签
                                found_start_idx = -1
                                found_start_tag = None
                                for start_tag in start_tags:
                                    idx = combined.lower().find(start_tag.lower())
                                    if idx >= 0 and (found_start_idx == -1 or idx < found_start_idx):
                                        found_start_idx = idx
                                        found_start_tag = start_tag
                                
                                found_end_idx = -1
                                found_end_tag = None
                                for end_tag in end_tags:
                                    idx = combined.lower().find(end_tag.lower())
                                    if idx >= 0 and (found_end_idx == -1 or idx < found_end_idx):
                                        found_end_idx = idx
                                        found_end_tag = end_tag
                                
                                # 找到开始标签
                                if found_start_idx >= 0:
                                    before = combined[:found_start_idx]
                                    if before:
                                        if in_think:
                                            reasoning_count += 1
                                            yield {"type": "reasoning", "content": before}
                                        else:
                                            yield {"type": "token", "content": before}
                                    combined = combined[found_start_idx + len(found_start_tag):]
                                    in_think = True
                                    tag_buffer = ""
                                    continue
                                
                                # 找到结束标签
                                if found_end_idx >= 0:
                                    before = combined[:found_end_idx]
                                    if before:
                                        reasoning_count += 1
                                        yield {"type": "reasoning", "content": before}
                                    combined = combined[found_end_idx + len(found_end_tag):]
                                    in_think = False
                                    tag_buffer = ""
                                    continue
                                
                                # 检查是否可能是被拆分的标签
                                possible_split = False
                                all_tags = start_tags + end_tags
                                for tag in all_tags:
                                    lower_combined = combined.lower()
                                    for i in range(1, min(len(tag), max_tag_len) + 1):
                                        if lower_combined.endswith(tag[:i].lower()):
                                            split_point = len(combined) - i
                                            tag_buffer = combined[split_point:]
                                            combined = combined[:split_point]
                                            possible_split = True
                                            break
                                    if possible_split:
                                        break
                                
                                if not possible_split:
                                    # 安全输出
                                    if combined:
                                        if in_think:
                                            reasoning_count += 1
                                            yield {"type": "reasoning", "content": combined}
                                        else:
                                            yield {"type": "token", "content": combined}
                                    tag_buffer = ""
                                    combined = ""
                                    break
                                else:
                                    # 保留可能是标签的部分
                                    if combined:
                                        if in_think:
                                            reasoning_count += 1
                                            yield {"type": "reasoning", "content": combined}
                                        else:
                                            yield {"type": "token", "content": combined}
                                    combined = ""
                                    break
                        
                        except json.JSONDecodeError:
                            continue
                            
        except Exception as e:
            logger.error(f"❌ LLM 流式调用失败: {e}")
            yield {"type": "error", "content": str(e)}
            yield {"type": "done"}
    
    async def call_with_reasoning(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> Tuple[str, str]:
        """调用 LLM 并返回完整的回复和思考内容
        
        Returns:
            (回复内容, 思考内容) 元组
        """
        full_response = ""
        full_reasoning = ""
        
        async for event in self.call_stream(prompt, system_prompt):
            if event["type"] == "reasoning":
                full_reasoning += event["content"]
            elif event["type"] == "token":
                full_response += event["content"]
            elif event["type"] == "done":
                break
        
        return full_response, full_reasoning

    async def chat_with_tools(
        self,
        messages: List[Dict],
        tools: List[Dict],
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """带工具调用的 LLM 对话
        
        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            tools: 工具定义列表 (OpenAI tools 格式)
            tool_choice: 工具选择策略 (auto, required, none)
            temperature: 温度 (覆盖默认值)
            max_tokens: 最大 token 数 (覆盖默认值)
            
        Returns:
            {
                "content": str,           # 文本回复
                "tool_calls": list,       # 工具调用列表
                "finish_reason": str      # "stop" | "tool_calls"
            }
        """
        if not self.api_base:
            return {"content": "", "tool_calls": [], "finish_reason": "stop"}
        
        try:
            import httpx
            
            # 构建请求
            payload = self._build_payload(
                messages=messages,
                stream=False,
                tools=tools,
                tool_choice=tool_choice
            )
            
            # 覆盖温度和max_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            # ★ vLLM 防护：显式覆盖后仍按剩余上下文预算钳制，避免 400
            self._clamp_max_tokens(payload, messages, tools)
            
            url = f"{self.api_base}/chat/completions"
            headers = self._build_headers()
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                # ★ 上下文统计：捕获响应中的 usage
                usage = data.get("usage", {}) if isinstance(data.get("usage"), dict) else {}
                if "choices" in data and len(data["choices"]) > 0:
                    choice = data["choices"][0]
                    message = choice.get("message", {})
                    
                    # 提取内容 (可能为 None 当有 tool_calls 时)
                    content = message.get("content") or ""
                    # ★ v4.0: 不再删除思考，分离返回
                    _, content = extract_thinking_and_content(content, self.think_config)
                    
                    # 提取工具调用
                    tool_calls = message.get("tool_calls", [])
                    
                    return {
                        "content": content,
                        "tool_calls": tool_calls,
                        "finish_reason": choice.get("finish_reason", "stop"),
                        "usage": usage,
                    }
                    
        except Exception as e:
            logger.error(f"❌ LLM 工具调用失败: {e}")
        
        return {"content": "", "tool_calls": [], "finish_reason": "stop", "usage": {}}

    # ──────────────────────────────────────────────────────────
    # ★ v4.0: 流式工具调用
    # ──────────────────────────────────────────────────────────

    async def chat_with_tools_stream(
        self,
        messages: List[Dict],
        tools: List[Dict],
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        no_think: bool = False
    ) -> AsyncGenerator[Dict, None]:
        """带工具调用的流式 LLM 对话

        生成的事件格式：
        {"type": "think", "content": str}       # 思考增量（★ v4.0: thinking → think）
        {"type": "token", "content": str}       # 正文增量
        {"type": "tool_calls", "tool_calls": list}  # 工具调用（完整）
        {"type": "done", "finish_reason": str}  # 流结束

        Args:
            messages: 消息列表
            tools: 工具定义列表
            tool_choice: 工具选择策略 (auto/required/none)
            temperature: 温度
            max_tokens: 最大 token 数

        Yields:
            事件字典
        """
        if not self.api_base:
            yield {"type": "done", "finish_reason": "stop"}
            return

        try:
            import httpx

            # ★ no_think：追加 /no_think 指令关闭 Qwen3 深度思考（结果整理轮使用；副本不污染调用方消息）
            if no_think:
                messages = list(messages) + [{"role": "user", "content": "/no_think"}]

            payload = self._build_payload(
                messages=messages,
                stream=True,  # ★ 流式
                tools=tools,
                tool_choice=tool_choice
            )
            if temperature is not None:
                payload["temperature"] = temperature
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            # ★ vLLM 防护：显式覆盖后仍按剩余上下文预算钳制，避免 400
            self._clamp_max_tokens(payload, messages, tools)

            url = f"{self.api_base}/chat/completions"
            headers = self._build_headers()

            # 思考配置
            start_tags = self.think_config["start_tags"]
            end_tags = self.think_config["end_tags"]
            reasoning_fields = self.think_config["reasoning_fields"]
            max_tag_len = self.think_config["max_tag_len"]

            in_think = False
            tag_buffer = ""
            accumulated_tool_calls = []
            finish_reason = "stop"

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    resp.raise_for_status()

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                            # ★ 上下文统计：捕获带 usage 的块（vLLM/OpenAI 兼容，其 choices 为空，需在取 delta 前处理）
                            if chunk.get("usage"):
                                yield {"type": "usage", "usage": chunk["usage"]}
                                continue
                            choice = chunk.get("choices", [{}])[0]
                            delta = choice.get("delta", {})

                            # 1. 优先检查 reasoning_content 字段（标准思考字段）
                            reasoning = ""
                            for field in reasoning_fields:
                                val = delta.get(field, "")
                                if val:
                                    reasoning = val
                                    break

                            if reasoning:
                                yield {"type": "think", "content": reasoning}  # ★ v4.0: thinking → think
                                continue

                            # 2. 处理 content 中的 <think> 标签
                            token = delta.get("content", "")
                            if token:
                                combined = tag_buffer + token
                                tag_buffer = ""
                                output_parts = []

                                while combined:
                                    # 查找最早的标签
                                    first_start_idx = -1
                                    first_start_tag = None
                                    for tag in start_tags:
                                        idx = combined.lower().find(tag.lower())
                                        if idx >= 0 and (first_start_idx == -1 or idx < first_start_idx):
                                            first_start_idx = idx
                                            first_start_tag = tag

                                    first_end_idx = -1
                                    first_end_tag = None
                                    for tag in end_tags:
                                        idx = combined.lower().find(tag.lower())
                                        if idx >= 0 and (first_end_idx == -1 or idx < first_end_idx):
                                            first_end_idx = idx
                                            first_end_tag = tag

                                    # 找到开始标签
                                    if first_start_idx >= 0 and (first_end_idx == -1 or first_start_idx < first_end_idx):
                                        if first_start_idx > 0:
                                            output_parts.append(("token" if not in_think else "think", combined[:first_start_idx]))
                                        combined = combined[first_start_idx + len(first_start_tag):]
                                        in_think = True
                                        continue

                                    # 找到结束标签
                                    if first_end_idx >= 0:
                                        if first_end_idx > 0:
                                            output_parts.append(("think", combined[:first_end_idx]))
                                        combined = combined[first_end_idx + len(first_end_tag):]
                                        in_think = False
                                        continue

                                    # 检查是否可能是被拆分的标签
                                    possible_split = False
                                    all_tags = start_tags + end_tags
                                    for tag in all_tags:
                                        lower_combined = combined.lower()
                                        for i in range(1, min(len(tag), max_tag_len) + 1):
                                            if lower_combined.endswith(tag[:i].lower()):
                                                split_point = len(combined) - i
                                                if split_point > 0:
                                                    output_parts.append(("token" if not in_think else "think", combined[:split_point]))
                                                tag_buffer = combined[split_point:]
                                                possible_split = True
                                                break
                                        if possible_split:
                                            break

                                    if not possible_split:
                                        output_parts.append(("token" if not in_think else "think", combined))
                                    combined = ""

                                # yield 输出部分
                                for part_type, part_content in output_parts:
                                    if part_content:
                                        yield {"type": part_type, "content": part_content}

                            # 3. 处理工具调用增量
                            tool_calls_delta = delta.get("tool_calls", [])
                            for tc in tool_calls_delta:
                                idx = tc.get("index", 0)
                                while len(accumulated_tool_calls) <= idx:
                                    accumulated_tool_calls.append({
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""}
                                    })
                                if tc.get("id"):
                                    accumulated_tool_calls[idx]["id"] = tc["id"]
                                func = tc.get("function", {})
                                if func.get("name"):
                                    accumulated_tool_calls[idx]["function"]["name"] += func["name"]
                                if func.get("arguments"):
                                    accumulated_tool_calls[idx]["function"]["arguments"] += func["arguments"]

                            # 4. 记录 finish_reason
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]

                        except json.JSONDecodeError:
                            continue

            # 流结束后，先冲刷标签缓冲区残留（避免模型回复尾部恰好以半个标签前缀收尾时被静默丢弃）
            if tag_buffer:
                yield {"type": "think" if in_think else "token", "content": tag_buffer}
                tag_buffer = ""

            # 流结束后，如果有工具调用，一次性 yield
            if accumulated_tool_calls:
                yield {"type": "tool_calls", "tool_calls": accumulated_tool_calls}

            yield {"type": "done", "finish_reason": finish_reason}

        except Exception as e:
            logger.error(f"❌ LLM 流式工具调用失败: {e}")
            yield {"type": "error", "content": str(e)}
            yield {"type": "done", "finish_reason": "error"}


class LLMAdapterManager:
    """LLM 适配器管理器
    
    管理多个模型的适配器，支持模型切换和降级
    """
    
    def __init__(self, config_path: str = "config/dfecrab.json"):
        """初始化管理器
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.adapters: Dict[str, LLMAdapter] = {}
        self.primary_adapter: Optional[LLMAdapter] = None
        self.fallback_adapters: List[LLMAdapter] = []
        
        self._load_config()
    
    def _load_config(self):
        """加载配置并初始化适配器"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            # ★ 主/备用统一取自 model_providers：primary=第一个 enabled，其余 enabled 作 fallback
            enabled = [
                (name, pc) for name, pc in config.get("model_providers", {}).items()
                if pc.get("enabled", False) and pc.get("api_base")
            ]
            if enabled:
                primary_name, primary_cfg = enabled[0]
                self.primary_adapter = LLMAdapter(primary_cfg)
                self.adapters[primary_name] = self.primary_adapter
                logger.info(f"✅ 主模型适配器初始化: {primary_cfg.get('model_name')}")
                for name, pc in enabled[1:]:
                    adapter = LLMAdapter(pc)
                    self.adapters[name] = adapter
                    self.fallback_adapters.append(adapter)
                    logger.info(f"✅ 备用模型适配器初始化: {name} -> {pc.get('model_name')}")
                    
        except Exception as e:
            logger.error(f"❌ 加载配置失败: {e}")
    
    async def call_with_fallback(
        self,
        prompt: str,
        system_prompt: str = "",
    ) -> Tuple[str, str]:
        """带降级的调用
        
        先尝试主模型，失败后依次尝试备用模型
        """
        # 尝试主模型
        if self.primary_adapter:
            try:
                response, reasoning = await self.primary_adapter.call_with_reasoning(
                    prompt, system_prompt
                )
                if response:
                    return response, reasoning
            except Exception as e:
                logger.warning(f"⚠️ 主模型调用失败: {e}")
        
        # 尝试备用模型
        for adapter in self.fallback_adapters:
            try:
                response, reasoning = await adapter.call_with_reasoning(
                    prompt, system_prompt
                )
                if response:
                    return response, reasoning
            except Exception as e:
                logger.warning(f"⚠️ 备用模型调用失败: {e}")
        
        logger.error("❌ 所有模型调用失败")
        return "", ""
    
    def get_stream_adapter(self) -> Optional[LLMAdapter]:
        """获取当前可用的流式适配器"""
        if self.primary_adapter and self.primary_adapter.api_base:
            return self.primary_adapter
        if self.fallback_adapters:
            return self.fallback_adapters[0]
        return None
