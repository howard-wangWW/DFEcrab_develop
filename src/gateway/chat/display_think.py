"""display 思考流（Display Think Domain）

把模型思考过程"可视化"给前端的整条链路，从 `grpc_server.GatewayV2GRPC` 逐字迁出：

    意图/骨架    _match 规则短路由 chat.intent 负责，本模块负责
                 _build_gateway_display_think_skeleton / _extract_gateway_display_think_lines
    分片与推送   _chunk_gateway_think_text / _emit_gateway_think_chunks
    提示词构建   _build_gateway_display_system_prompt / _build_gateway_display_domain_context
                 / _build_gateway_display_user_prompt
    模型直连流   _gateway_model_display_think_stream / _stream_gateway_display_think
                 / _gateway_llm_think_stream

依赖单向：不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List

from src.utils.api_base import normalize_api_base

try:  # 离线环境可能缺 httpx
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)


class DisplayThinkMixin:
    """display 思考流（方法实现逐字自 grpc_server 迁出）"""


    def _build_gateway_display_think_skeleton(self, intent: Dict, raw_query: str) -> str:
        """根据稳定 intent 构造展示思考的骨架文本。"""
        query = (raw_query or "").strip() or "当前请求"
        intent_type = intent.get("type", "simple")
        category = intent.get("category", "chat")
        target_agent = intent.get("target_agent", "")
        reason = intent.get("reason", "")
        descriptions = self._scan_agent_descriptions()
        target_name = descriptions.get(target_agent, {}).get("name", target_agent)

        if intent_type == "complex":
            steps = (((intent.get("workflow") or {}).get("steps")) or [])
            step_agents = []
            for step in steps[:2]:
                agent_id = step.get("agent", "")
                display_name = descriptions.get(agent_id, {}).get("name", agent_id or "未知智能体")
                if display_name:
                    step_agents.append(display_name)
            lines = [
                f"用户询问的是{query}，这类请求需要拆成多个步骤协同处理。",
                "当前判断这不是普通对话，而是需要按流程分发的复合型任务。"
            ]
            if step_agents:
                lines.append(f"后续将按{' -> '.join(step_agents)}的顺序继续执行，并汇总处理结果。")
            else:
                lines.append("后续将进入多智能体协作流程，并逐步完成处理。")
            return " ".join(lines)

        if category == "chat" or not target_agent:
            return " ".join([
                f"用户询问的是{query}，当前看更像普通对话或通用问答场景。",
                "这类请求不需要进入专项数据查询链路。",
                "后续将由Manager直接生成回复。"
            ])

        domain_background, next_action = self._build_gateway_display_domain_context(
            query,
            target_name or target_agent or "对应智能体",
            reason
        )
        lines = [
            f"用户询问的是{query}，{domain_background}",
            f"根据路由规则，此类请求更适合交由{target_name or target_agent}处理。"
        ]
        if next_action:
            lines.append(next_action)
        else:
            lines.append("后续将由对应智能体继续完成检索并返回结果。")
        return " ".join(lines)



    def _extract_gateway_display_think_lines(self, text: str, incremental: bool = False) -> List[str]:
        """从模型展示流中抽取<think>标签内的思考句子。
        
        提取<think>和</think>标签之间的完整思考内容。
        """
        if not text:
            return []

        think_start = text.find("<think>")
        think_end = text.find("</think>")
        
        if think_start == -1 or think_end == -1 or think_end <= think_start:
            return []
        
        think_content = text[think_start + len("<think>"):think_end]
        think_content = think_content.replace("\r", "\n").strip()
        
        if not think_content:
            return []

        parts: List[str] = []
        for line in think_content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for seg in re.split(r'(?<=[。！？])', stripped):
                seg = seg.strip()
                if seg:
                    parts.append(seg)
        return parts

    def _chunk_gateway_think_text(self, text: str) -> List[str]:
        """将思考文本切成 2-4 个字的小块，模拟更细粒度的流式输出。"""
        compact = re.sub(r"\s+", "", text or "")
        if not compact:
            return []

        chunks: List[str] = []
        idx = 0
        total = len(compact)
        while idx < total:
            remain = total - idx
            if remain <= 4:
                step = remain
            elif remain == 5:
                step = 2
            else:
                step = 3
            chunks.append(compact[idx:idx + step])
            idx += step

        if len(chunks) >= 2 and len(chunks[-1]) == 1:
            chunks[-2] += chunks[-1]
            chunks.pop()
        return [chunk for chunk in chunks if chunk]

    async def _emit_gateway_think_chunks(self, text: str, delay: float = 0.05):
        """把一段 think 文本按小块连续发给前端。"""
        for chunk in self._chunk_gateway_think_text(text):
            yield {"type": "think", "data": {"content": chunk}}
            await asyncio.sleep(delay)

    def _build_gateway_display_system_prompt(self, agent_list: str) -> str:
        """构建展示用的 Manager 风格提示词，保留中文分析风格，去掉 JSON 输出要求。"""
        manager_prompt = (self._get_agent_system_prompt("manager_agent") or "").strip()
        if manager_prompt:
            manager_prompt = manager_prompt.replace("{{AGENT_LIST}}", agent_list or "无可调用Agent")
            if "【输出格式】" in manager_prompt:
                manager_prompt = manager_prompt.split("【输出格式】", 1)[0].rstrip()
            manager_prompt += (
                "\n\n【输出格式】\n"
                "- 只输出2-3句简短自然的中文分析\n"
                "- 不要JSON，不要Markdown，不要额外说明\n"
                "- 禁止输出英文、步骤编号、检查约束、Draft、Here's a thinking process 等模板内容"
            )
            return self._truncate_system_prompt(manager_prompt, max_chars=2200)

        fallback_prompt = (
            "你是DFEcrab的总调度员(Manager)，负责分析用户意图并将任务分派给合适的Agent。\n\n"
            "【约束】\n"
            "- 只分析最匹配的1个Agent\n"
            "- 禁止输出英文、步骤编号、检查约束、Draft 等模板内容\n"
            "- 只输出2到3句简短自然的中文分析\n"
            "- 不要JSON，不要Markdown，不要额外说明\n\n"
            f"【可调用Agent】\n{agent_list or '无可调用Agent'}"
        )
        return self._truncate_system_prompt(fallback_prompt, max_chars=2200)

    def _build_gateway_display_domain_context(self, query: str, target_name: str, reason: str) -> tuple[str, str]:
        """为展示层生成更自然的业务背景与后续动作。"""
        text = f"{query} {reason}"

        if "受令资格" in text:
            return (
                "这是电网人员资质核验场景，通常需要先识别人员姓名，再确认是否具备受令资格。",
                f"下一步会交给{target_name}继续做人员识别和资格核验。"
            )
        if "异常信号" in text:
            return (
                "这是配网运行监测相关查询，通常需要先明确时间范围，再查看异常信号明细或统计情况。",
                f"下一步会交给{target_name}继续检索异常信号数据。"
            )
        if "跳闸" in text:
            return (
                "这是配网跳闸事件查询场景，通常需要先确定查询时间范围，再查看对应跳闸记录。",
                f"下一步会交给{target_name}继续检索跳闸事件数据。"
            )
        if "早会材料" in text or "早会" in text:
            return (
                "这是电网业务材料汇总场景，通常需要先明确时间范围和主题，再整理对应数据内容。",
                f"下一步会交给{target_name}继续整理相关业务材料。"
            )
        if "保供电" in text:
            return (
                "这是保供电相关业务查询，通常需要结合时间和对象范围整理相关信息。",
                f"下一步会交给{target_name}继续检索保供电相关数据。"
            )
        if "svg" in text.lower():
            return (
                "这是配网设备或线路分组查询场景，通常需要先明确对象范围，再查询对应设备数据。",
                f"下一步会交给{target_name}继续检索对应设备信息。"
            )
        if target_name and target_name != "Manager":
            return (
                f"这属于{target_name}更擅长处理的业务查询场景，需要结合当前问题继续做针对性检索。",
                f"下一步会交给{target_name}继续完成分析和处理。"
            )
        return (
            "这是一个需要结合当前语义继续判断处理方式的请求。",
            "下一步会根据当前预判继续完成后续处理。"
        )

    def _build_gateway_display_user_prompt(
        self,
        intent: Dict,
        raw_query: str,
        target_name: str,
        reason: str,
        step_names: List[str],
    ) -> str:
        """构建展示层的用户提示，尽量贴近 Manager 风格，不直接暴露机器规则术语。"""
        query = (raw_query or "").strip() or "当前请求"

        if intent.get("type") == "complex":
            workflow_line = ""
            if step_names:
                workflow_line = f"\n协作流程：{' -> '.join(step_names)}。"
            return (
                f"用户问题：{query}\n"
                "请像总调度员一样，先判断这不是普通闲聊，而是需要多步骤协作处理的任务。"
                f"{workflow_line}\n"
                "请只输出2到3句自然中文分析。"
            )

        if intent.get("category") == "chat" or not intent.get("target_agent"):
            return (
                f"用户问题：{query}\n"
                "请像总调度员一样，判断这是普通对话或通用问答，给出2到3句自然中文分析。"
            )

        domain_background, next_action = self._build_gateway_display_domain_context(query, target_name, reason)
        return (
            f"用户问题：{query}\n"
            f"业务背景：{domain_background}\n"
            f"当前判断：这个问题更适合交给{target_name}处理。\n"
            f"后续动作：{next_action}\n"
            "请像总调度员一样，只输出2到3句自然中文分析。"
        )

    async def _gateway_model_display_think_stream(self, intent: Dict, raw_query: str):
        """用独立模型流生成前端展示的 think 内容；失败时回退模板骨架。"""
        skeleton = self._build_gateway_display_think_skeleton(intent, raw_query)
        skeleton_lines = [part.strip() for part in skeleton.splitlines() if part.strip()]
        llm_config = self._get_gateway_llm_config()
        # ★ 统一清洗：即使配置误填完整接口地址，也剥成根地址再拼
        api_base = normalize_api_base(llm_config.get("api_base", ""))
        model_name = llm_config.get("model_name")
        api_key = llm_config.get("api_key", "not-needed")

        descriptions = self._scan_agent_descriptions()
        target_agent = intent.get("target_agent", "")
        target_name = descriptions.get(target_agent, {}).get("name", target_agent or "Manager")
        reason = intent.get("reason", "")
        query = (raw_query or "").strip() or "当前请求"
        workflow = intent.get("workflow") or {}
        steps = workflow.get("steps") or []
        step_names = []
        for step in steps[:3]:
            agent_id = step.get("agent", "")
            if agent_id:
                step_names.append(descriptions.get(agent_id, {}).get("name", agent_id))
        agent_list, _ = self._build_gateway_agent_list()

        if not api_base or not model_name:
            async for line in self._stream_gateway_display_think(skeleton):
                async for event in self._emit_gateway_think_chunks(line, delay=0.04):
                    yield event
            yield {"type": "think_end", "data": {"content": skeleton}}
            return

        system_prompt = self._build_gateway_display_system_prompt(agent_list)
        user_prompt = self._build_gateway_display_user_prompt(
            intent=intent,
            raw_query=query,
            target_name=target_name,
            reason=reason,
            step_names=step_names,
        )

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": True,
            "temperature": 0.25,
            "max_tokens": 1024,
        }
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"

        raw_text = ""
        emitted_lines: List[str] = []
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                async with client.stream(
                    "POST",
                    f"{api_base}/chat/completions",
                    json=payload,
                    headers=headers
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except Exception:
                            continue

                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        delta_text = delta.get("content") or delta.get("reasoning_content") or ""
                        if not delta_text:
                            continue
                        raw_text += delta_text

                        candidate_lines = self._extract_gateway_display_think_lines(raw_text, incremental=True)
                        if len(candidate_lines) < 1:
                            continue

                        while len(emitted_lines) < len(candidate_lines):
                            current_line = candidate_lines[len(emitted_lines)]
                            emitted_lines.append(current_line)
                            async for event in self._emit_gateway_think_chunks(current_line, delay=0.03):
                                yield event
        except Exception as e:
            logger.warning(f"⚠️ Gateway 展示思考流生成失败，回退模板: {e}")
            raw_text = ""
            emitted_lines = []

        final_lines = self._extract_gateway_display_think_lines(raw_text)
        logger.info(f"🧠 [Gateway] 展示流原文预览: {(raw_text or '')[:200]}")
        logger.info(f"🧠 [Gateway] 展示流抽取句数: {len(final_lines)}")
        if len(final_lines) < 1:
            final_text = skeleton
            for line in skeleton_lines[len(emitted_lines):]:
                async for event in self._emit_gateway_think_chunks(line, delay=0.04):
                    yield event
        else:
            if len(final_lines) > 4:
                final_lines = final_lines[:4]
            if len(final_lines) < 3:
                for skeleton_line in skeleton_lines:
                    if skeleton_line not in final_lines:
                        final_lines.append(skeleton_line)
                    if len(final_lines) >= 3:
                        break
            for line in final_lines[len(emitted_lines):]:
                async for event in self._emit_gateway_think_chunks(line, delay=0.04):
                    yield event
            final_text = "\n".join(final_lines)
            logger.info("🧠 [Gateway] 展示思考已使用模型流输出")

        yield {"type": "think_end", "data": {"content": final_text}}

    async def _stream_gateway_display_think(self, think_text: str):
        """按句流式发送伪思考文本，保持 WS 对话体验。"""
        for line in [part.strip() for part in (think_text or "").splitlines() if part.strip()]:
            yield line
            await asyncio.sleep(0.12)

    async def _gateway_llm_think_stream(self, message: str, session_id: str):
        """Gateway 轻量意图识别。

        先走基于 Agent 配置关键词的动态规则短路；未命中时，再用非流式
        `json_object` 方式做结构化意图识别，避免 WS 首层继续依赖思维链。
        """
        clean_message = (message or "").strip()

        rule_intent = self._match_gateway_rule_based_intent(clean_message)
        if rule_intent:
            logger.info(f"🧠 [Gateway] 意图识别: {rule_intent.get('type')}/{rule_intent.get('category')}")
            if rule_intent.get("target_agent"):
                logger.info(f"   └─ 目标 Agent: {rule_intent['target_agent']}")
            yield {"type": "think_end", "data": {"content": clean_message, "intent": rule_intent, "replace": True}}
            return

        llm_config = self._get_gateway_llm_config()
        if not llm_config.get("api_base"):
            logger.error("❌ Gateway LLM 配置不可用，降级")
            fallback_intent = {"type": "simple", "category": "chat", "reason": "LLM不可用"}
            yield {"type": "think_end", "data": {"content": clean_message, "intent": fallback_intent, "replace": True}}
            return

        agent_list, route_rules = self._build_gateway_agent_list()
        system_prompt = f"""你是意图识别助手，将用户问题路由到正确的智能体。

【路由规则】
{route_rules}
- 其他 → default

【输出要求】
- 只输出一个 JSON 对象
- 禁止解释、分析、Markdown、<think>、额外文字
- simple/chat:
{{"type":"simple","category":"chat","reason":"理由"}}
- simple/query:
{{"type":"simple","category":"query","target_agent":"agent_id","reason":"理由"}}
- complex:
{{"type":"complex","category":"xxx","reason":"理由","workflow":{{"steps":[{{"agent":"xxx","action":"xxx","description":"xxx"}}]}}}}
- simple 非 chat 时，target_agent 和 category 必须同时出现
- 字段名必须是 target_agent，禁止用 target、agent、agent_id 等别名"""
        system_prompt = self._truncate_system_prompt(system_prompt, max_chars=2000)

        user_prompt = f"""用户消息：{clean_message}

可用Agent：
{agent_list}

请返回一个 JSON 对象。"""

        api_base = llm_config["api_base"]
        model_name = llm_config.get("model_name", "default")
        timeout = llm_config.get("timeout", 600)
        api_key = llm_config.get("api_key", "not-needed")
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": min(llm_config.get("max_tokens", 256), 256),
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if api_key and api_key != "not-needed":
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{api_base}/chat/completions",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
        except Exception as e:
            logger.error(f"❌ Gateway 轻量意图识别失败: {e}")
            fallback_intent = {"type": "simple", "category": "chat", "reason": "Gateway意图识别失败"}
            yield {
                "type": "think_end",
                "data": {
                    "content": clean_message,
                    "intent": fallback_intent,
                    "replace": True
                }
            }
            return

        choice = (result.get("choices") or [{}])[0]
        message_obj = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")
        content = (
            message_obj.get("content")
            or message_obj.get("reasoning_content")
            or ""
        )
        if finish_reason == "length":
            logger.warning("⚠️ Gateway 轻量意图识别仍被截断，准备降级")

        intent = self._parse_intent_from_json(content)
        if not intent:
            logger.warning("⚠️ Gateway 轻量意图识别 JSON 解析失败，降级为 chat")
            intent = {"type": "simple", "category": "chat", "reason": "Gateway意图识别JSON解析失败"}

        logger.info(f"🧠 [Gateway] 意图识别: {intent.get('type')}/{intent.get('category')}")
        if intent.get("target_agent"):
            logger.info(f"   └─ 目标 Agent: {intent['target_agent']}")

        yield {"type": "think_end", "data": {"content": content, "intent": intent, "replace": True}}
