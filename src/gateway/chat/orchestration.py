"""Manager 编排与工具装配（Chat Orchestration Domain）

从 `grpc_server.GatewayV2GRPC` 逐字迁出：

    _get_agent_skills / _get_agent_system_prompt / _resolve_agent_tool_choice   工具与提示词装配
    _run_knowledge_base_branch                                                 知识库分支
    _manager_orchestrate / _parse_manager_decision                              Manager 决策与解析
    _fallback_classify / _handle_clarification                                  兜底分类与澄清
    _resolve_plan_use / _resolve_user_id                                        计划开关与用户解析

依赖单向：不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

#: 项目根目录（src/gateway/chat/orchestration.py → 上溯 3 层：chat → gateway → src → 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)
manager_logger = logging.getLogger("dfecrab.manager")
react_logger = logging.getLogger("dfecrab.react")


class ChatOrchestrationMixin:
    """Manager 编排与工具装配（方法实现逐字自 grpc_server 迁出）"""

    def _get_agent_skills(self, agent_id: str) -> List[str]:
        """获取指定 agent 启用的技能列表"""
        tools_path = PROJECT_ROOT / "agents" / agent_id / "tools.json"
        if tools_path.exists():
            try:
                with open(tools_path, 'r', encoding='utf-8') as f:
                    tools = json.load(f)
                return tools.get("enabled_skills", [])
            except Exception as e:
                logger.warning(f"⚠️ 读取 agent [{agent_id}] tools.json 失败: {e}")
        return []

    def _get_agent_system_prompt(self, agent_id: str) -> str:
        """获取指定 agent 的 system_prompt"""
        config_path = PROJECT_ROOT / "agents" / agent_id / "config.json"
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                return config.get("system_prompt", "")
            except Exception as e:
                logger.warning(f"⚠️ 读取 agent [{agent_id}] config.json 失败: {e}")
        return ""

    def _resolve_agent_tool_choice(
        self,
        agent_id: str,
        intent: str = "task",
        enabled_skills: Optional[List[str]] = None,
    ) -> str:
        """解析 tool_choice：agent config.json 显式配置 > 全局默认策略

        策略背景（对齐成熟平台的确定性工具编排，缓解 qwen3_a3b 等小参数量模型
        在 auto 模式下"不调技能直接编造数据"的问题）：
          - agent config.json 显式配置 tool_choice(auto/required/none) 最高优先
          - intent == "chat"            → "none"     （闲聊不装配工具）
          - task（含原 complex，批次10 退役归一）+ 启用了技能 → "required"（首轮强制调工具）
          - 其它（MCP 直调等无本地技能） → "auto"

        注意：required 在 ReActLoop 中只约束第 1 轮，工具返回后自动回到 auto，
        避免"拿到结果后仍被强制重复调工具"无法收尾。
        """
        try:
            from src.agent.agent_config import AgentConfig
            cfg = AgentConfig.from_id(agent_id)
            cfg_tc = (cfg.tool_choice or "").strip().lower()
            if cfg_tc in ("required", "auto", "none"):
                react_logger.info(
                    f"[ReAct] Agent[{agent_id}] tool_choice 命中 agent 配置: {cfg_tc}"
                )
                return cfg_tc
        except Exception as e:
            react_logger.warning(
                f"[ReAct] 读取 agent tool_choice 配置失败，走默认策略: {e}"
            )
        if intent == "chat":
            return "none"
        if enabled_skills:
            return "required"
        return "auto"

    # ──────────────────────────────────────────────────────────
    # ★ 短路分支: 知识库直答 / MCP 直调
    # ──────────────────────────────────────────────────────────

    async def _run_knowledge_base_branch(
        self,
        message: str,
        kb_category: Optional[str],
        kb_top_k: int,
        streaming: bool,
        ctx: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """知识库直答分支：调用 6788 /knowledge/chat，输出兼容现有事件流"""
        import httpx
        try:
            from config.port_loader import knowledge_api_port
            kb_port = knowledge_api_port()
        except Exception:
            kb_port = 6788
        kb_url = f"http://localhost:{kb_port}/knowledge/chat"

        payload = {
            "question": message,
            "category": kb_category,
            "top_k": kb_top_k,
        }
        logger.info(f"[KB-Branch] 调用知识库直答: {kb_url} payload={payload}")

        # 会话 ID（保存历史用）
        try:
            _session_id = ctx["session"].id if ctx.get("session") else None
        except Exception:
            _session_id = None
        from src.session.manager import get_session_manager
        session_mgr = get_session_manager()

        # 成功/失败都先发 manager_decision，便于前端识别走了 KB 分支
        yield {
            "type": "manager_decision",
            "data": {
                "intent": "knowledge_base",
                "target_agent": "knowledge_base",
                "parameters": {"category": kb_category, "top_k": kb_top_k},
                "reasoning": "指定 knowledge_base 参数，直接走知识库直答",
            }
        }

        # 注：用户消息由标准流程（_prepare_stream_context）统一保存，此处不再重复保存

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(kb_url, json=payload)
                resp.raise_for_status()
                kb_result = resp.json()
        except Exception as e:
            logger.error(f"[KB-Branch] 调用知识库服务失败: {e}")
            err_msg = f"知识库服务调用失败: {str(e)}"
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        if kb_result.get("status") != "success":
            err_msg = kb_result.get("message", "知识库问答失败")
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        answer = kb_result.get("answer", "")
        sources = kb_result.get("sources", [])

        # ★ 上下文统计：知识库直答本地估算 usage（KB 服务在独立进程 6788，拿不到真实 usage）
        from src.utils.context_usage import build_context_usage, usage_to_tokens
        kb_usage = build_context_usage(
            system_prompt="你是知识库问答助手，根据检索内容回答用户问题。",
            current=message,
            tool_results=[{"content": json.dumps(sources, ensure_ascii=False, default=str)}] if sources else [],
            context_length=self._gateway_context_length(),
            model=self._gateway_llm_model(),
        )
        kb_usage["source"] = "local_estimate"

        # ★ 用量统计：KB 直答 token 事件落盘（本地估算，source=local_estimate）
        try:
            from src.monitoring.usage_store import record_llm_call
            _kb_tokens = usage_to_tokens(kb_usage)
            record_llm_call(
                model=kb_usage.get("model") or "",
                prompt_tokens=_kb_tokens.get("prompt", 0),
                completion_tokens=_kb_tokens.get("completion", 0),
                source=kb_usage.get("source") or "local_estimate",
                session_id=_session_id or "",
            )
        except Exception:
            pass

        # 保存助手回答（含来源摘要），供会话回看
        if _session_id:
            try:
                source_titles = [
                    s.get("metadata", {}).get("title") or s.get("metadata", {}).get("source", "")
                    for s in sources
                    if s.get("metadata")
                ]
                session_mgr.add_message(
                    _session_id, "assistant", answer,
                    status="completed",
                    model=kb_usage.get("model") or None,  # ★ P3：实际使用模型
                    tokens=usage_to_tokens(kb_usage),  # ★ 上下文统计：token 落库
                    metadata={
                        "intent": "knowledge_base",
                        "kb_category": kb_category,
                        "sources": sources,
                        "source_titles": source_titles,
                        "matched_skills": ["knowledge_base"],
                        "context_length": kb_usage.get("context_length"),  # ★ P3：该模型窗口
                    },
                    task_type="knowledge_base",
                    agents_used=["knowledge_base"],
                    execution_flow=[
                        {"type": "knowledge_base", "content": f"调用知识库直答 (category={kb_category})"}
                    ],
                )
            except Exception as e:
                logger.warning(f"[KB-Branch] 保存助手历史失败: {e}")

        if streaming:
            yield {"type": "message_start", "data": {"agent_id": "knowledge_base"}}
            chunk_size = 80
            for i in range(0, len(answer), chunk_size):
                yield {
                    "type": "message",
                    "data": {
                        "chunk": answer[i:i + chunk_size],
                        "agent_id": "knowledge_base"
                    }
                }

        yield {
            "type": "message_end",
            "data": {
                "full_response": answer,
                "content": answer,
                "success": True,
                "kb_category": kb_category,
                "sources": sources,
                "matched_skills": ["knowledge_base"],
                "tool_calls": [],
                "execution_flow": [
                    {"type": "knowledge_base", "content": f"调用知识库直答 (category={kb_category})"}
                ],
                "iterations": 0,
                "tools_used": [],
                # ★ 上下文统计：知识库直答 usage（本地估算）
                "usage": kb_usage,
            }
        }

    # ──────────────────────────────────────────────────────────
    # ★ v4.0: Manager 编排层
    # ──────────────────────────────────────────────────────────

    async def _manager_orchestrate(
        self,
        message: str,
        session_id: str,
        user_id: str = "default",
        session_history: List[Dict] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ v4.0 Manager 编排层 — 统一入口

        所有对话路径（HTTP/WS）都先走此方法：
        1. 加载 Manager system_prompt
        2. 注入用户画像和 Agent 列表
        3. 流式调用 Manager LLM（输出 think 事件）
        4. 解析 JSON 决策
        5. yield manager_decision 事件
        6. 缺参时 yield clarification

        Yields:
            事件字典:
            - think_start(think, think_end) — Manager 思考流式输出
            - manager_decision — 路由决策
            - clarification — 缺参澄清（需要外部处理）
        """
        import time as _time
        from src.agent.llm.adapter import LLMAdapter
        from src.memory.unified_manager import get_unified_manager

        manager_logger.info(
            f"[Manager] 请求入口 | session={session_id} | user={user_id} | "
            f"message={message[:100]}"
        )

        # 1. 加载 Manager system_prompt
        manager_prompt = self._get_agent_system_prompt("manager_agent")
        if not manager_prompt:
            manager_logger.warning("[Manager] manager_agent config.json 无 system_prompt，降级")
            yield {
                "type": "manager_decision",
                "data": {
                    "intent": "task",
                    "target_agent": "dfecrab",
                    "parameters": {},
                    "missing_params": [],
                    "reasoning": "Manager 降级（无配置）",
                }
            }
            return

        # 2. 注入 {{USER_PROFILE}}
        try:
            memory_mgr = get_unified_manager()
            user_profile = await memory_mgr.get_user_profile(user_id)
        except Exception as e:
            manager_logger.warning(f"[Manager] 获取用户画像失败: {e}")
            user_profile = "（暂无用户画像）"
        manager_prompt = manager_prompt.replace("{{USER_PROFILE}}", user_profile)

        # 3. 注入 {{AGENT_LIST}}（含完整描述 + 技能列表）
        try:
            agent_descs = self._scan_agent_descriptions()

            # 读取 agents_index.json 获取 skills
            index_skills = {}
            index_file = PROJECT_ROOT / "config" / "agents_index.json"
            if index_file.exists():
                try:
                    with open(index_file, 'r', encoding='utf-8') as f:
                        index_data = json.load(f)
                    for aid, info in index_data.get("agents", {}).items():
                        index_skills[aid] = info.get("skills", [])
                except Exception:
                    pass

            # 构建含描述 + 技能的 Agent 列表
            agent_list_parts = []
            for aid, desc in agent_descs.items():
                name = desc.get("name", aid)
                description = desc.get("description", "")

                # 获取该 agent 的技能列表（合并 agents_index + tools.json）
                skills = list(index_skills.get(aid, []))
                try:
                    tools = self._get_agent_skills(aid)
                    for t in tools:
                        if t not in skills:
                            skills.append(t)
                except Exception:
                    pass

                skills_str = ", ".join(skills) if skills else "无"
                agent_list_parts.append(
                    f"- {aid}（{name}）: {description}\n  技能: {skills_str}"
                )

            agent_list_text = "\n".join(agent_list_parts)
        except Exception as e:
            manager_logger.warning(f"[Manager] 构建 Agent 列表失败: {e}")
            agent_list_text = "- default（默认助手）: 通用智能助手\n  技能: weather, file_read, excel-read, web-fetch\n- kunming（昆明配网数据专家）: 配网业务数据查询\n  技能: kunming_classifier, kunming_api"
        manager_prompt = manager_prompt.replace("{{AGENT_LIST}}", agent_list_text)

        # 4. 获取 LLM 配置
        llm_config = self._get_gateway_llm_config()
        if not llm_config:
            manager_logger.error("[Manager] LLM 配置不可用")
            yield {
                "type": "manager_decision",
                "data": {
                    "intent": "task",
                    "target_agent": "dfecrab",
                    "parameters": {},
                    "missing_params": [],
                    "reasoning": "LLM 不可用降级",
                }
            }
            return

        # 5. 构建消息（含历史上下文，合并为 prompt 字符串）
        prompt_parts = []
        if session_history:
            for msg in session_history[-6:]:  # 最近6条历史
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    prompt_parts.append(f"用户: {content}")
                elif role == "assistant":
                    prompt_parts.append(f"系统: {content}")
        prompt_parts.append(f"用户: {message}\n/no_think")
        merged_prompt = "\n".join(prompt_parts)

        # 6. 流式调用 Manager LLM
        llm_adapter = LLMAdapter(llm_config)

        yield {
            "type": "think_start",
            "data": {"phase": "manager", "iteration": 0}
        }

        full_reasoning = ""
        full_response = ""

        try:
            async for event in llm_adapter.call_stream(
                prompt=merged_prompt,
                system_prompt=manager_prompt,
                max_tokens=1024,
                response_format={"type": "json_object"},
            ):
                if event["type"] == "reasoning":
                    full_reasoning += event["content"]
                elif event["type"] == "token":
                    full_response += event["content"]
                    # Manager 的决策 JSON 落在 content；reasoning 兜底累积（/no_think 后通常为空）
                    full_reasoning += event["content"]
                elif event["type"] == "done":
                    break
        except Exception as e:
            manager_logger.error(f"[Manager] LLM 流式调用失败: {e}")
            yield {
                "type": "think_end",
                "data": {"phase": "manager", "full_reasoning": f"Manager 调用失败: {e}"}
            }
            # 降级：用 IntentClassifier
            intent = await self._fallback_classify(message, llm_config)
            yield {
                "type": "manager_decision",
                "data": {
                    "intent": intent,
                    "target_agent": "dfecrab",
                    "parameters": {},
                    "missing_params": [],
                    "reasoning": f"Manager 降级（LLM 失败）→ IntentClassifier={intent}",
                }
            }
            return

        manager_logger.info(
            f"[Manager] 思考完成 | reasoning_len={len(full_reasoning)} | "
            f"reasoning={full_reasoning[:200]}"
        )

        # 7. 解析 JSON 决策（同时尝试 full_response 和 full_reasoning）
        decision = self._parse_manager_decision(full_response, full_reasoning)
        if decision is None:
            # JSON 解析失败，降级（单行结构化日志，避免多行输出难排查）
            _resp_head = (full_response or "").replace("\n", " ").strip()[:120]
            manager_logger.warning(
                f"[Manager] 决策解析失败 | response_len={len(full_response or '')} | "
                f"head={_resp_head or '(空)'} | 降级待分类"
            )
            intent = await self._fallback_classify(message, llm_config)
            decision = {
                "intent": intent,
                "target_agent": "dfecrab",
                "parameters": {},
                "missing_params": [],
                "reasoning": f"Manager JSON 解析失败，降级 IntentClassifier={intent}",
            }

        manager_logger.info(
            f"[Manager] 路由决策 | intent={decision['intent']} | "
            f"target_agent={decision['target_agent']} | "
            f"missing_params={decision['missing_params']} | "
            f"reasoning={decision.get('reasoning', '')[:100]}"
        )

        # 8. 只推一句话路由理由（决策 JSON 不再逐 chunk 外泄）
        _reason_text = str(decision.get("reasoning", "")).strip()
        if _reason_text:
            yield {
                "type": "think",
                "data": {
                    "chunk": _reason_text,
                    "phase": "manager",
                    "iteration": 0,
                }
            }
        yield {
            "type": "think_end",
            "data": {"phase": "manager", "full_reasoning": _reason_text}
        }

        # 9. yield manager_decision 事件
        yield {
            "type": "manager_decision",
            "data": decision
        }

        # 10. 如果缺参，yield clarification
        if decision.get("missing_params"):
            yield {
                "type": "clarification",
                "data": {
                    "message": f"请补充以下信息: {', '.join(decision['missing_params'])}",
                    "missing_params": decision["missing_params"],
                    "options": [],
                }
            }

    def _parse_manager_decision(self, full_response: str, full_reasoning: str = "") -> Optional[Dict]:
        """解析 Manager LLM 输出的 JSON 决策

        优先解析 full_response（content 字段），
        失败则尝试 full_reasoning（reasoning_content 字段）。
        使用括号平衡匹配支持嵌套 JSON。

        Returns:
            dict: {intent, target_agent, parameters, missing_params, reasoning}
            None: 解析失败
        """
        import json

        def _extract_json_objects(text: str) -> list:
            """使用括号平衡匹配提取所有 JSON 对象"""
            objects = []
            depth = 0
            start = -1
            for i, ch in enumerate(text):
                if ch == '{':
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0 and start >= 0:
                        json_str = text[start:i + 1]
                        objects.append(json_str)
                        start = -1
            return objects

        # 按优先级尝试解析：full_response → full_reasoning → 合并
        sources = []
        if full_response:
            sources.append(("response", full_response))
        if full_reasoning:
            sources.append(("reasoning", full_reasoning))
        if full_response and full_reasoning:
            sources.append(("combined", full_response + "\n" + full_reasoning))

        for source_name, raw_text in sources:
            json_objects = _extract_json_objects(raw_text)
            for json_str in reversed(json_objects):
                try:
                    decision = json.loads(json_str)
                    if "intent" in decision or "target_agent" in decision:
                        decision.setdefault("intent", "task")
                        decision.setdefault("target_agent", "dfecrab")
                        decision.setdefault("parameters", {})
                        decision.setdefault("missing_params", [])
                        decision.setdefault("reasoning", "")
                        manager_logger.info(f"[Manager] JSON 解析成功（来源: {source_name}）")
                        return decision
                except json.JSONDecodeError:
                    continue

        manager_logger.warning(f"[Manager] JSON 解析失败。response={full_response[:100]}, reasoning={full_reasoning[:100]}")
        return None

    async def _fallback_classify(self, message: str, llm_config: Dict) -> str:
        """Manager 降级时的意图分类（使用 IntentClassifier）"""
        try:
            from src.agent.intent_classifier import IntentClassifier
            classifier = IntentClassifier(llm_config=llm_config, use_llm=True)
            return await classifier.classify(message, has_skills=True)
        except Exception as e:
            manager_logger.warning(f"[Manager] IntentClassifier 降级也失败: {e}")
            return "task"

    async def _handle_clarification(
        self,
        original_message: str,
        user_reply: str,
        missing_params: List[str],
        session_id: str,
        user_id: str = "default",
        session_history: List[Dict] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ v4.0 Clarification 完整流程

        当 Manager 标记 missing_params 后：
        1. 前端展示 clarification 事件
        2. 用户回复补充信息
        3. 合并用户回复到原消息
        4. 重新走 _manager_orchestrate

        Args:
            original_message: 原始用户消息
            user_reply: 用户补充的回复
            missing_params: 缺失的参数列表
            session_id: 会话 ID
            user_id: 用户 ID
            session_history: 会话历史
        """
        # 合并用户回复到原消息
        merged_message = f"{original_message} {user_reply}"
        logger.info(
            f"[Clarification] 合并消息: '{original_message[:30]}' + '{user_reply[:30]}'"
        )

        # 重新走 Manager 编排
        async for event in self._manager_orchestrate(
            message=merged_message,
            session_id=session_id,
            user_id=user_id,
            session_history=session_history,
        ):
            yield event

    def _resolve_plan_use(self, request_use_plan: Optional[bool] = None) -> bool:
        """Plan 执行器开关（react.plan_mode，批次10：complex intent 已退役）。

        - off（默认）：恒不启用 Plan 分步——多步骤复杂度由 task 工具循环消化（日志实证更优）
        - explicit：仅请求体显式 use_plan=true 时启用（预留"计划确认模式/多智能体编排"底座）
        判定纯配置驱动，无关键词。
        """
        try:
            from src.config.app_config import section as _cfg_section
            mode = (_cfg_section("react") or {}).get("plan_mode", "off")
        except Exception:
            mode = "off"
        return bool(request_use_plan) if mode == "explicit" else False

    # ══════════════════════════════════════════════════════════
    # user_id 收敛（批次 10-B-2）
    # ══════════════════════════════════════════════════════════

    # 按来源（ws/chat、http/chat 等）记录最近一次"缺失 user_id"告警时间，限频防刷屏
    _missing_user_warn_at: Dict[str, float] = {}

    def _resolve_user_id(self, declared: Any = None, auth: Any = None,
                         source: str = "chat") -> str:
        """user_id 解析收敛（B-2）：declared(请求体) > auth(HTTP 头/WS 认证) > 配置默认。

        仅在两个候选都真实缺失（空串/None）时回落 config.identity.default_user_id，
        并按 source 限频打 WARNING，提示前端必传 user_id（多用户现场避免会话/记忆
        落到同一默认用户）。判定纯配置驱动，无关键词表、无硬编码名单。
        """
        for cand in (declared, auth):
            if isinstance(cand, str) and cand.strip():
                return cand.strip()
        try:
            from src.config.app_config import section as _cfg_section
            _idn = _cfg_section("identity") or {}
        except Exception:
            _idn = {}
        _default = str(_idn.get("default_user_id") or "default").strip() or "default"
        if _idn.get("warn_missing_user_id", True):
            _now = time.time()
            _gap = float(_idn.get("warn_missing_interval_s", 300) or 300)
            _last = type(self)._missing_user_warn_at.get(source, 0.0)
            if _now - _last >= _gap:
                type(self)._missing_user_warn_at[source] = _now
                logger.warning(
                    f"[Identity] {source} 请求未携带 user_id（请求体/认证均缺失），"
                    f"回落默认用户 '{_default}'。多用户现场请前端必传 user_id，"
                    f"否则会话与记忆按默认用户隔离。"
                )
        return _default