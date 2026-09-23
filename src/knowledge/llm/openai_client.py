# src/knowledge/llm/openai_client.py
"""知识库 LLM 客户端：同步 OpenAI 兼容接口，供 RAG 引擎生成回答"""
import json
import logging

import httpx

# ★ api_base 规范化：防现场误填完整接口地址导致重复拼接 /chat/completions
from src.utils.api_base import normalize_api_base

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """同步 OpenAI 兼容客户端，实现 .chat(prompt) -> str 与 .stream_chat(prompt) 接口"""

    def __init__(self, config: dict):
        # 统一清洗（含去尾斜杠），下游再拼 /chat/completions 不会重复
        self.api_base = normalize_api_base(config.get("api_base", ""))
        self.model_name = config.get("model_name", "")
        self.api_key = config.get("api_key", "not-needed")
        self.timeout = config.get("timeout", 300)
        # 单次生成的最大 token 数（调大，避免长回答被截断）
        self.max_tokens = config.get("max_tokens", 4096)
        # 生成温度（由场景级配置注入，默认 0.2；不再写死在请求体里）
        self.temperature = float(config.get("temperature", 0.2))
        # ★ 思考开关（Qwen3 等混合思考模型）：None=不下发该字段（其他现场/模型零影响）；
        #   False/True → 下发 chat_template_kwargs.enable_thinking，从源头控制是否生成思考
        self.enable_thinking = config.get("enable_thinking")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, prompt: str, stream: bool = False) -> dict:
        """统一构造请求体（chat / stream_chat 共用，避免两处重复拼装）"""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if stream:
            payload["stream"] = True
        # ★ 思考开关：仅在显式配置时下发（未配置的现场请求体与历史行为完全一致）
        if self.enable_thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": bool(self.enable_thinking)}
        return payload

    def chat(self, prompt: str) -> str:
        """单轮生成，返回文本回答"""
        logger.info(f"[LLM] POST {self.api_base}/chat/completions model={self.model_name} "
                    f"prompt_len={len(prompt)} enable_thinking={self.enable_thinking}")
        _t0 = __import__("time").time()
        resp = httpx.post(
            f"{self.api_base}/chat/completions",
            headers=self._headers(),
            json=self._payload(prompt),
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        content = choice["message"]["content"].strip()
        logger.info(f"[LLM] 响应 status={resp.status_code} answer_len={len(content)} "
                    f"finish_reason={choice.get('finish_reason')} "
                    f"耗时={__import__('time').time()-_t0:.2f}s")
        # 截断检测：finish_reason 为 length 表示答案被 max_tokens 截断
        if choice.get("finish_reason") == "length":
            logger.warning(
                f"[LLM] ⚠️ 回答被 max_tokens 截断（{len(content)} 字），"
                f"建议缩小问题范围或降低 top_k"
            )
        return content

    def stream_chat(self, prompt: str):
        """流式生成（供 RAGQueryEngine.stream_query 使用）"""
        with httpx.stream(
            "POST",
            f"{self.api_base}/chat/completions",
            headers=self._headers(),
            json=self._payload(prompt, stream=True),
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                if line == "data: [DONE]":
                    break
                delta = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
