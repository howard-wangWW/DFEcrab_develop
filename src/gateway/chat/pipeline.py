"""对话主链路（Chat Pipeline Domain）

从 `grpc_server.GatewayV2GRPC` 逐字迁出，承载 HTTP 对话入口到 ReAct 之前的全部编排：

    _handle_chat / _handle_chat_stream   非流式 / 流式入口（SSE 组装）
    _apply_asr_correction                语音识别文本纠错
    _prepare_stream_context             流式上下文准备（会话、历史、增强消息）
    _run_chat_pipeline                  主链路：知识库分支 / Manager 编排 / 计划 / 直达回复
    normalize_structured_response       结构化结果归一（本模块私有）
    build_execution_flow                执行流程展示（本模块私有）

依赖单向：不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from src.core.errors import UserError, error_response
from src.gateway.http.server import HTTPResponse
from src.gateway.sse import SSEStreamingResponse
from src.utils.context_usage import DEFAULT_CONTEXT_LENGTH

try:  # 离线环境可能缺 grpc
    from src.gateway.grpc import dfecrab_pb2
except Exception:  # pragma: no cover
    dfecrab_pb2 = None  # type: ignore

logger = logging.getLogger(__name__)
manager_logger = logging.getLogger("dfecrab.manager")
react_logger = logging.getLogger("dfecrab.react")


def _strip_think_tags(text) -> str:
    """剥离模型输出中的思考标签（<think>...</think> 及孤立的思考前缀）。

    与 manager_agent 侧的逻辑保持一致，避免历史 content 混入思考过程。
    随 `normalize_structured_response` 从 grpc_server 迁入本模块（原实现遗留在
    grpc_server 导致本模块 NameError，思考标签无法剥离）。
    """
    if not text:
        return text
    import re as _re
    # 成对 <think>...</think>（含自定义标签如 <reasoning>、<thought>）
    s = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL | _re.IGNORECASE)
    s = _re.sub(r"<reasoning>.*?</reasoning>", "", s, flags=_re.DOTALL | _re.IGNORECASE)
    s = _re.sub(r"<thought>.*?</thought>", "", s, flags=_re.DOTALL | _re.IGNORECASE)
    # 孤立标签
    s = _re.sub(r"</?think>", "", s, flags=_re.IGNORECASE)
    s = _re.sub(r"</?reasoning>", "", s, flags=_re.IGNORECASE)
    s = _re.sub(r"</?thought>", "", s, flags=_re.IGNORECASE)
    return s.strip()


def normalize_structured_response(raw) -> Dict[str, Any]:
    """把 worker 可能返回的 JSON 字符串拆成结构化字段。

    背景：kunming 等智能体返回 `answer_final + other` 结构时，
    manager_agent 会把它们序列化成 JSON 字符串塞进 gRPC message，
    导致 Gateway 的 full_response 可能是纯文本也可能是 JSON 字符串，
    进而污染 session 历史的 content 字段。

    输入：raw 可以是纯文本，或形如
        '{"answer_final": "...", "other": {"recommendQuestions": "...", ...}}'
    输出：{
        "content": str,           # 最终展示纯文本（answer_final 剥离思考标签）
        "structured": dict|None,  # other 结构化字段；非结构化时为 None
        "raw": str,               # 原文，供前端调试
    }
    """
    if raw is None:
        return {"content": "", "structured": None, "raw": ""}
    raw = str(raw).strip()
    if not raw:
        return {"content": "", "structured": None, "raw": ""}

    s = raw
    if "<think>" in s or "<reasoning>" in s or "<thought>" in s:
        s = _strip_think_tags(s).strip()

    parsed = None
    if s.startswith("{") and s.endswith("}"):
        try:
            parsed = json.loads(s)
        except Exception:
            parsed = None

    if isinstance(parsed, dict) and "answer_final" in parsed:
        return {
            "content": _strip_think_tags(parsed.get("answer_final", "")),
            "structured": parsed.get("other") or {},
            "raw": raw,
        }

    return {
        "content": _strip_think_tags(raw),
        "structured": None,
        "raw": raw,
    }


def _build_execution_flow(flow_parts: List[Dict[str, Any]],
                          manager_reasoning: str = "") -> List[Dict[str, Any]]:
    """按真实时间顺序构建完整执行时间线（思考 + 工具调用与结果）。

    flow_parts 由调用方按事件接收顺序组装（think_end / tool_call / tool_result 依次追加），
    保证 execution_flow 与流式展示的顺序完全一致。供 message_end 与 session 持久化复用。

    Args:
        flow_parts: 已按时间轴排好的执行片段
        manager_reasoning: Manager 推理（如有则前置，用于解释路由/跳过原因）
    """
    flow: List[Dict[str, Any]] = list(flow_parts)
    if manager_reasoning:
        flow.insert(0, {"type": "manager_reasoning", "content": manager_reasoning})
    return flow


# _pick_latest_instances 已迁移至 src/gateway/lifecycle/zookeeper.py


class ChatPipelineMixin:
    """对话主链路（方法实现逐字自 grpc_server 迁出）"""

    async def _handle_chat(self, request) -> Dict[str, Any]:
        """
        HTTP 非流式聊天接口 - ★ G5 重构: 协议壳

        流程：解析 HTTP body → 调用共享 _run_chat_pipeline → 收集所有 events → 返回 JSON
        业务逻辑全部在 _run_chat_pipeline 中，HTTP/WS 4 个入口共用。
        """
        try:
            # 1. 解析请求体（协议适配）
            body = await request.json()
            message = body.get("message", "")
            session_id = body.get("session_id")
            # ★ B-2：user_id 收敛（请求体 > X-User-Id 头 > 配置默认，缺失限频告警）
            user_id = self._resolve_user_id(
                body.get("user_id"),
                auth=request.headers.get("x-user-id"),
                source="http/chat",
            )
            agent_id = body.get("agent_id")
            knowledge_base = body.get("knowledge_base")
            kb_category = body.get("kb_category")
            kb_top_k = body.get("kb_top_k", 5)
            mcp = body.get("mcp")
            use_plan = body.get("use_plan")   # ★ 预留：plan_mode=explicit 时前端可显式开启 Plan 分步

            # ★ 兼容 dict 格式的 message（如告警JSON），自动转为 JSON 字符串
            if isinstance(message, dict):
                message = json.dumps(message, ensure_ascii=False)

            if not message:
                raise UserError(
                    message="message is required",
                    details={"field": "message", "value": ""},
                    build_hint="请提供非空的 message 参数",
                    status_code=400,
                )

            logger.info(f"📨 收到非流式聊天请求: {message[:50]}...")

            # 2. ★ 复用共享核心: 收集所有 events（非流式模式）
            events = []
            full_response = ""
            tool_calls_made = []
            matched_skills = []
            intent = "task"
            session_id_final = session_id
            session_summary = ""
            is_new_session = False

            async for event in self._run_chat_pipeline(
                message=message,
                session_id=session_id,
                user_id=user_id,
                agent_id=agent_id,
                knowledge_base=knowledge_base,
                kb_category=kb_category,
                kb_top_k=kb_top_k,
                mcp=mcp,
                streaming=False,  # ★ 非流式：跳过 think chunk，只保留 think_end
                use_plan=use_plan,
            ):
                events.append(event)
                et = event.get("type")
                ed = event.get("data", {})

                if et == "message_end":
                    full_response = ed.get("full_response", ed.get("content", ""))
                elif et == "tool_call":
                    tool_calls_made.append({
                        "tool_name": ed.get("tool_name", ""),
                        "arguments": ed.get("tool_args", ed.get("arguments", {}))
                    })
                elif et == "skill_match":
                    matched_skills = ed.get("skills", [])
                elif et == "meta":
                    session_id_final = ed.get("session_id", session_id)
                    session_summary = ed.get("session_summary", "")
                    is_new_session = ed.get("is_new_session", False)
                    intent = ed.get("intent", intent)

            # 3. 协议壳：返回 JSON
            return HTTPResponse(200).json({
                "success": True,
                "message": "ReAct 循环执行完成",
                "data": {
                    "response": full_response,
                    "session_id": session_id_final,
                    "session_summary": session_summary,
                    "is_new_session": is_new_session,
                    "intent": intent,
                    "events": events,
                    "tool_calls": tool_calls_made,
                    "matched_skills": matched_skills,
                }
            })

        except Exception as e:
            logger.error(f"[Chat] 请求处理失败: {e}")
            import traceback
            traceback.print_exc()
            err = error_response(e)
            return HTTPResponse(err.get("status_code", 500)).json(err)

    async def _handle_chat_stream(self, request):
        """
        HTTP 流式聊天接口 - SSE 输出 - G6 重构: 协议壳

        流程：解析 HTTP body -> 包装 _run_chat_pipeline 为 SSE 响应
        业务逻辑全部在 _run_chat_pipeline 中，HTTP/WS 4 个入口共用。
        """
        try:
            body = await request.json()
            message = body.get("message", "")
            session_id = body.get("session_id")
            # ★ B-2：user_id 收敛（请求体 > X-User-Id 头 > 配置默认，缺失限频告警）
            user_id = self._resolve_user_id(
                body.get("user_id"),
                auth=request.headers.get("x-user-id"),
                source="http/chat_stream",
            )
            agent_id = body.get("agent_id")
            knowledge_base = body.get("knowledge_base")
            kb_category = body.get("kb_category")
            kb_top_k = body.get("kb_top_k", 5)
            mcp = body.get("mcp")
            use_plan = body.get("use_plan")   # ★ 预留：plan_mode=explicit 时前端可显式开启 Plan 分步
            request_type = body.get("type", "chat")

            # ★ 兼容 dict 格式的 message（如告警JSON），自动转为 JSON 字符串
            if isinstance(message, dict):
                message = json.dumps(message, ensure_ascii=False)

            if not message:
                raise UserError(
                    message="message is required",
                    details={"field": "message", "value": ""},
                    build_hint="请提供非空的 message 参数",
                    status_code=400,
                )

            # ★ 允许客户端传入 correlation_id，未传则自动生成
            correlation_id = body.get("correlation_id") or str(uuid.uuid4())

            logger.info(f"SSE stream: type={request_type} {message[:50]}...")

            # ★ type=alert：短期会话，跳过 session_mgr 全套（不创建会话、不写历史），
            #   强制走 alert_judge 专属研判链路；SSE 事件流照常透传，但不进入左侧会话列表
            if request_type == "alert":
                return SSEStreamingResponse(
                    stream_generator=self._alert_ephemeral_stream(
                        alert_json=message,
                        user_id=user_id,
                        correlation_id=correlation_id,
                    ),
                    session_id="",
                    correlation_id=correlation_id,
                )

            return SSEStreamingResponse(
                stream_generator=self._run_chat_pipeline(
                    message=message,
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    knowledge_base=knowledge_base,
                    kb_category=kb_category,
                    kb_top_k=kb_top_k,
                    mcp=mcp,
                    correlation_id=correlation_id,
                    use_plan=use_plan,
                ),
                session_id=session_id or "",
                correlation_id=correlation_id,
            )

        except Exception as e:
            logger.error(f"SSE parse fail: {e}")
            err = error_response(e)
            return HTTPResponse(err.get("status_code", 500)).json(err)

    # ========== 流式聊天统一准备逻辑（HTTP/WS 共用）==========

    async def _apply_asr_correction(self, text: str) -> str:
        """ASR 纠错：在所有处理之前纠正 ASR 识别错误"""
        if not text:
            return text
        try:
            import sys
            from pathlib import Path
            _skills_dir = Path(__file__).resolve().parent.parent.parent.parent / "skills" / "asr_corrector"
            if str(_skills_dir) not in sys.path:
                sys.path.insert(0, str(_skills_dir))
            import importlib
            _spec = importlib.util.spec_from_file_location(
                "asr_corrector",
                _skills_dir / "execute.py"
            )
            if _spec and _spec.loader:
                _module = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_module)
                _result = _module.execute(text=text, use_model=True)
                if _result.get("has_correction"):
                    text = _result["corrected_text"]
                    logger.info(f"✅ ASR纠错: {_result.get('correction_count')}处修正 → '{text}'")
        except Exception as e:
            logger.warning(f"⚠️ ASR纠错失败: {e}，使用原文继续处理")
        return text

    async def _prepare_stream_context(self, message: str, session_id: Optional[str],
                                      user_id: str, agent_id: Optional[str] = None
                                      ) -> Dict[str, Any]:
        """
        流式聊天的统一准备逻辑（HTTP/WS 共用）

        包含：ASR纠错 → 会话管理 → 摘要 → 历史过滤 → 增强消息 → gRPC Stub → ReAct 检查
        返回统一的上下文 dict，供 HTTP/WS 各自的协议适配层使用。
        注意：Manager 编排不在本函数中执行，由 _run_chat_pipeline 统一调用一次。
        """
        from src.session.manager import get_session_manager, ClientType

        # 1. ASR 纠错
        message = await self._apply_asr_correction(message)

        # ★ P0 快速路由预检：JSON 告警 → 直接锁定 alert_judge（不经过 Manager LLM，避免路由错误）
        if not agent_id and self._is_alert_json_message(message):
            agent_id = "alert_judge"
            react_logger.info(f"[Route] 检测到JSON告警信号，快速路由 → alert_judge")

        # 2. 会话管理
        session_mgr = get_session_manager()
        existing_session = session_mgr.get_session(session_id) if session_id else None
        
        # ★ P0-1: 反转守卫逻辑 — 优先从 session / 显式参数取 agent_id，未指定时用 "auto"
        effective_agent_id = agent_id or (
            existing_session.agent_id if existing_session else None
        ) or "auto"
        # ★ 兼容旧 ID（default → dfecrab），统一在下游解析为当前智能体
        try:
            from src.agent.agent_config import normalize_agent_id
            effective_agent_id = normalize_agent_id(effective_agent_id) or effective_agent_id
        except Exception:
            pass
        
        session = session_mgr.get_or_create_session(
            session_id=session_id,
            user_id=user_id,
            agent_id=effective_agent_id,
            client_type=ClientType.API
        )
        is_new_session = (
            (not session_id) or
            (existing_session is None) or
            (session.message_count == 0)
        )
        logger.info(f"📋 流式聊天会话: {session.id} (新会话: {is_new_session})")
        # ★ 请求参数日志：明确展示是否显式指定 agent_id（用于判断是否跳过 Manager 路由）
        logger.info(
            "[ChatRequest] session=%s user=%s agent_id=%s effective=%s explicit=%s "
            "message_len=%s new=%s",
            session.id, user_id, agent_id, effective_agent_id,
            bool(agent_id), len(message), is_new_session
        )
        session_mgr.add_message(session.id, "user", message)

        # 3. 摘要生成/更新
        session_summary = session.summary
        if is_new_session or not session.summary_generated:
            try:
                session_summary = await self._generate_session_summary(message)
                session_mgr.set_summary(session.id, session_summary)
            except Exception as e:
                logger.warning(f"⚠️ 摘要生成失败: {e}")
                session_summary = message[:50]
                session_mgr.set_summary(session.id, session_summary)
        elif not session_summary:
            # ★ 阶段C: 不再每轮用 message[:50] 覆盖已有摘要（避免摘要每轮漂移），
            #   长对话滚动摘要由 SessionSummarizer 异步更新（见 _run_chat_pipeline 沉淀处）
            session_summary = message[:50]
            session_mgr.set_summary(session.id, session_summary)

        # 4. 历史过滤
        session_history = session_mgr.get_messages_as_dicts(session.id, limit=10)
        relevant_history = self._history_filter.filter_history(
            current_msg=message,
            history=session_history
        )
        if relevant_history != session_history:
            session_history = relevant_history

        # 4.5 ★ P0 上下文自动压缩：上一轮上下文占用 ≥ 阈值（默认 85%）时同步压缩历史。
        #   做法（无损）：LLM 将「旧摘要 + 老历史」合并为新摘要（SessionSummarizer.compact_session），
        #   会话消息不删除，仅减少本次注入的原始历史条数（老上下文由摘要承担）。
        compacted = False
        ce_conf = self._context_engine_conf()
        try:
            _msgs = session_mgr.get_messages_as_dicts(session.id, limit=20)
            last_prompt = 0
            for _m in reversed(_msgs):
                if _m.get("role") == "assistant":
                    last_prompt = int((_m.get("tokens") or {}).get("prompt", 0) or 0)
                    break
            if last_prompt > 0:
                # ★ 按 agent 模型解析（若该 agent 配置了 model_config 用其窗口，否则全局）
                _llm_config = self._resolve_agent_llm_config(effective_agent_id)
                _context_length = int(_llm_config.get("context_length", DEFAULT_CONTEXT_LENGTH) or DEFAULT_CONTEXT_LENGTH)
                from src.utils.context_usage import should_compact
                if should_compact(last_prompt, _context_length, ce_conf["auto_compact_threshold"]):
                    from src.agent.llm.adapter import LLMAdapter
                    from src.memory.summarizer import SessionSummarizer
                    compacted = await SessionSummarizer().compact_session(
                        LLMAdapter(_llm_config), session.id, user_id,
                        keep_recent=ce_conf["compact_keep_recent"],
                    )
                    if compacted:
                        # 压缩成功后：摘要已更新，本次注入的历史减到最近 keep 条
                        session_summary = session.summary
                        session_history = session_history[-ce_conf["compact_keep_recent"]:]
                        react_logger.info(
                            f"[Compaction] 上下文已自动压缩: session={session.id}, "
                            f"last_prompt={last_prompt}/{_context_length} "
                            f"(threshold={ce_conf['auto_compact_threshold']})"
                        )
        except Exception as e:
            react_logger.warning(f"[Compaction] 自动压缩触发失败（降级为不压缩）: {e}")
            compacted = False

        # 5. 增强消息
        enhanced_message = self._build_enhanced_message(
            message=message,
            session_id=session.id,
            session_summary=session_summary,
            session_history=session_history
        )

        # 6. gRPC Stub
        stub = self._get_manager_stub()

        # 7. System prompt
        manager_system_prompt = self._get_agent_system_prompt("manager_agent")

        # 8. ReAct 检查（HTTP/WS 对齐）
        # ★ P0-1: 默认走 ReAct 链路 — 用 effective_agent_id 替代显式 agent_id
        react_decision = None
        agent_skills = self._get_agent_skills(effective_agent_id)
        # ★ 方案1-L2: 预检补齐 MCP 维度（本地技能 或 已激活的 MCP 工具，都算"有工具"）
        has_active_mcp = False
        try:
            from src.skill.registry import get_tool_registry
            has_active_mcp = get_tool_registry().has_mcp_tools_for_agent(effective_agent_id)
        except Exception:
            pass
        if agent_skills or has_active_mcp:
            react_decision = {"agent_id": effective_agent_id, "skills": agent_skills}
            react_logger.info(
                f"[ReAct] 自动选择 Agent [{effective_agent_id}]，技能: {agent_skills} | "
                f"MCP激活: {has_active_mcp}"
            )
        else:
            react_logger.info(f"[ReAct] Agent [{effective_agent_id}] 无技能且无激活MCP，降级到标准 gRPC 链路")

        return {
            "session": session,
            "session_summary": session_summary,
            "is_new_session": is_new_session,
            "session_history": session_history,
            "enhanced_message": enhanced_message,
            "grpc_request": dfecrab_pb2.ChatRequest(
                message=enhanced_message,
                session_id=session.id,
                user_id=user_id
            ),
            "manager_system_prompt": manager_system_prompt,
            "stub": stub,
            "react_decision": react_decision,
            "raw_message": message,  # ★ 保存原始消息（alert_judge 需要未增强的原始JSON）
            "compacted": compacted,  # ★ P0 上下文压缩标记（message_end.usage 透传给前端）
            "explicit_agent_id": agent_id,  # ★ 显式指定的agent_id（含P0告警快速路由锁定），供pipeline跳过Manager
        }

    async def _run_chat_pipeline(
        self,
        message: str,
        session_id: Optional[str],
        user_id: str = "default",
        agent_id: Optional[str] = None,
        knowledge_base: Optional[str] = None,
        kb_category: Optional[str] = None,
        kb_top_k: int = 5,
        mcp: Optional[Dict[str, Any]] = None,
        streaming: bool = True,
        correlation_id: str = "",
        use_plan: Optional[bool] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ G1 共享核心: 4 个接口共用的对话流水线

        流程：
            1. 准备阶段（ASR、会话、摘要、历史）
            2. Manager 编排（think_start → think 流式 → think_end → manager_decision）
            3. 路由执行（chat 直调 LLM / task/complex 走 ReAct）
            4. 唯一 message_end 终止

        Args:
            streaming: True=流式（yield 每个 think chunk），False=非流式（跳过 think chunk，只保留 think_end）

        HTTP/WS 4 个入口共用此生成器，只在协议层（HTTP-JSON / SSE / WS）做适配：
            - HTTP /api/v2/chat (非流式)         : streaming=False → 收集 events → return JSON
            - HTTP /api/v2/chat/stream (流式)    : streaming=True → SSEStreamingResponse(gen())
            - WS /ws/chat/stream (流式)          : streaming=True → for event in gen(): ws.send()
            - WS /ws/chat/sync (非流式)          : streaming=False → 收集 events → ws.send() 一次
        """
        from src.session.manager import get_session_manager

        # ★ 请求追踪日志
        react_logger.info(
            f"[Pipeline] 请求开始 | session={session_id} | user={user_id} | "
            f"agent_id={agent_id} | message={message[:100]}"
        )

        # 1. 准备阶段
        ctx = await self._prepare_stream_context(
            message=message, session_id=session_id,
            user_id=user_id, agent_id=agent_id,
        )

        session = ctx["session"]
        session_summary = ctx["session_summary"]
        is_new_session = ctx["is_new_session"]
        session_history = ctx["session_history"]
        raw_message = ctx.get("raw_message", message)  # ★ 获取原始消息（alert_judge 需要）
        session_mgr = get_session_manager()
        # 初始化默认值（从 react_decision 获取初始 agent_id）
        # ★ 未传 agent_id 时显示 "auto" 表示自动路由，传了才显示实际值
        effective_agent_id = agent_id or "auto"
        # ★ 兼容旧 ID（default → dfecrab），统一在下游解析为当前智能体
        try:
            from src.agent.agent_config import normalize_agent_id
            effective_agent_id = normalize_agent_id(effective_agent_id) or effective_agent_id
        except Exception:
            pass
        react_decision = ctx.get("react_decision")
        if react_decision:
            effective_agent_id = react_decision.get("agent_id", effective_agent_id)

        # ★ 用量统计：注入本次请求上下文（user/session/agent），
        #   供下游 MCP 调用埋点与 token 事件自动补齐身份字段，实现按用户隔离统计。
        #   ContextVar 在 asyncio Task 之间隔离，不会串请求。
        try:
            from src.monitoring.usage_store import set_usage_context
            set_usage_context(
                user_id=user_id,
                session_id=session.id,
                agent_id="" if effective_agent_id == "auto" else effective_agent_id,
            )
        except Exception:
            pass

        # 2. meta 事件（所有接口统一）
        yield {
            "type": "meta",
            "data": {
                "session_id": session.id,
                "session_summary": session_summary,
                "is_new_session": is_new_session,
                "agent_id": effective_agent_id,
            }
        }

        # ★ 短路分支参数校验
        # knowledge_base 与 agent_id/mcp 互斥；agent_id 和 mcp 可共存
        if knowledge_base and (agent_id or mcp):
            err_msg = "knowledge_base 与 agent_id/mcp 参数互斥"
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        # agent_id 只能是单个字符串
        if agent_id and not isinstance(agent_id, str):
            err_msg = "agent_id 必须是单个字符串"
            yield {
                "type": "message_end",
                "data": {
                    "full_response": err_msg,
                    "content": err_msg,
                    "success": False,
                }
            }
            return

        # ★ 知识库直答分支：直接调用 6788 /knowledge/chat，跳过 Manager/ReAct
        if knowledge_base:
            async for event in self._run_knowledge_base_branch(
                message=message,
                kb_category=kb_category,
                kb_top_k=kb_top_k,
                streaming=streaming,
                ctx=ctx,
            ):
                yield event
            return

        # ★ 解析 mcp 参数：MCP 服务名字符串或字符串数组，运行时临时覆盖该 agent 的 MCP 服务
        mcp_servers = None
        if mcp:
            if isinstance(mcp, str):
                mcp_servers = [mcp]
            elif isinstance(mcp, list):
                mcp_servers = [s for s in mcp if isinstance(s, str) and s]
            else:
                mcp_servers = []
            if not mcp_servers:
                err_msg = "mcp 参数必须是非空的 MCP 服务名字符串或字符串数组"
                yield {
                    "type": "message_end",
                    "data": {
                        "full_response": err_msg,
                        "content": err_msg,
                        "success": False,
                    }
                }
                return

        # 3. ★ G1 优化: Manager 编排（仅调用一次，同时输出 think 流 + 获取决策）
        full_response = ""
        tool_calls_made = []
        matched_skills = []
        message_end_seen = False
        manager_decision = None
        intent = "task"
        parameters = {}
        manager_reasoning = ""  # ★ S3: 捕获 Manager 推理过程
        worker_reasoning = ""   # ★ 捕获 Worker 推理过程
        full_tool_calls = []    # ★ 完整工具调用（含 result/elapsed_ms）
        execution_flow_parts = []  # ★ 按时间轴收集执行片段（think_end/tool_call/tool_result）
        pipeline_usage = None   # ★ 上下文统计：记录本次对话的 usage（供 message_end 与落库）

        # ★ 显式指定 agent_id（用户传参 / P0告警快速路由）时跳过 Manager LLM 思考，
        #    直接从 manager_decision 的下一步（路由执行）开始
        # ★ 指定 mcp 时同样跳过 Manager：agent_id 缺省用默认智能体 dfecrab。
        #   特殊地，mcp 中若包含 alert_judge_tools，说明想走 alert_judge 专属研判链路，
        #   此时在 agent_id 为空或 default 的情况下，自动路由到 alert_judge。
        if mcp_servers:
            # alert_judge_tools 是专属研判链路开关：只要 mcp 参数里带它，
            # 不论 agent_id 是什么，都路由到 alert_judge 走自己的流程。
            if "alert_judge_tools" in mcp_servers:
                routed_agent_id = "alert_judge"
            else:
                routed_agent_id = agent_id or "dfecrab"
        else:
            routed_agent_id = agent_id or ctx.get("explicit_agent_id")
        # ★ 路由决策日志：判断是否因绑定 agent 而跳过 Manager 编排
        logger.info(
            "[Pipeline] 路由决策 | agent_id=%s routed=%s skip_manager=%s",
            agent_id, routed_agent_id, bool(routed_agent_id)
        )
        if routed_agent_id:
            # ★ S3: 记录跳过 Manager 路由的原因，供历史接口解释"为什么没走 Manager"
            manager_reasoning = f"指定 agent_id={routed_agent_id}，跳过 Manager 路由直接执行"
            manager_decision = {
                "intent": "task",
                "target_agent": routed_agent_id,
                "parameters": {},
                "missing_params": [],
                "reasoning": manager_reasoning,
            }
            intent = "task"
            effective_agent_id = routed_agent_id
            react_decision = {
                "agent_id": routed_agent_id,
                "skills": self._get_agent_skills(routed_agent_id),
            }
            react_logger.info(
                f"[Pipeline] 指定 agent_id={routed_agent_id}，跳过 Manager 编排直接执行"
            )
            yield {"type": "manager_decision", "data": manager_decision}

        try:
            llm_config = self._get_gateway_llm_config()
            if llm_config and not routed_agent_id:
                async for event in self._manager_orchestrate(
                    message=message,
                    session_id=session.id,
                    user_id=user_id,
                    session_history=session_history,
                ):
                    et = event.get("type")
                    # ★ S3: 捕获 Manager 推理过程
                    if et == "think_end":
                        manager_reasoning = event.get("data", {}).get("full_reasoning", "")
                    # ★ 非流式模式：跳过 think chunk，只保留 think_end
                    if not streaming and et == "think":
                        continue
                    # ★ 流式模式：透传所有 think 事件
                    if streaming and et in ("think_start", "think", "think_end"):
                        yield event
                        continue
                    # 非流式模式：跳过 think_start，yield think_end
                    if not streaming and et == "think_start":
                        continue
                    if not streaming and et == "think_end":
                        yield event
                        continue

                    # clarification 事件
                    if et == "clarification":
                        yield event
                        return

                    # manager_decision 捕获
                    # （显式指定 agent_id 时已在上方短路合成决策，不会走到这里）
                    if et == "manager_decision":
                        manager_decision = event["data"]
                        intent = manager_decision.get("intent", "task")
                        target_agent = manager_decision.get("target_agent", "")
                        if target_agent:
                            effective_agent_id = target_agent
                            new_skills = self._get_agent_skills(target_agent)
                            react_decision = {"agent_id": target_agent, "skills": new_skills}
                        parameters = manager_decision.get("parameters", {})
                        logger.info(
                            f"[Intent] Manager 决策: intent={intent}, "
                            f"target_agent={effective_agent_id}"
                        )
                    yield event
            else:
                if routed_agent_id:
                    # 显式指定 agent_id（或 mcp）：跳过 Manager 编排属正常路径，非错误
                    logger.debug(f"[Intent] 指定 agent_id={routed_agent_id}，跳过 Manager 编排")
                else:
                    # LLM 配置不可用，降级到 task 模式
                    logger.warning("[Intent] LLM 配置不可用，降级为 task")
                manager_decision = {"intent": "task", "target_agent": effective_agent_id}

            # 4. 路由执行（chat 意图保持 chat：MCP 绑定不再强制改判，agent_id 权威，auto 决策）
            if intent == "chat":
                # chat 模式：直调 LLM（按 agent 模型解析，配置过 model_config 的用其模型）
                llm_config = self._resolve_agent_llm_config(effective_agent_id)
                if not llm_config:
                    yield {"type": "error", "data": {"message": "LLM 配置不可用"}}
                    return

                from src.agent.llm.adapter import LLMAdapter
                llm_adapter = LLMAdapter(llm_config)
                system_prompt = self._get_agent_system_prompt(effective_agent_id)
                _direct_usage: Dict = {}
                try:
                    direct_response, _direct_usage = await llm_adapter.call(
                        prompt=message,
                        system_prompt=system_prompt,
                        with_usage=True
                    )
                except Exception as e:
                    react_logger.error(f"[Pipeline] chat LLM 调用失败: {e}")
                    direct_response = "抱歉，处理您的请求时出错。"

                full_response = direct_response
                # ★ 上下文统计：chat 直答的上下文 = system_prompt + 当前消息
                from src.utils.context_usage import build_context_usage
                pipeline_usage = build_context_usage(
                    llm_usage=_direct_usage or None,
                    system_prompt=system_prompt,
                    current=message,
                    context_length=getattr(llm_adapter, "context_length", DEFAULT_CONTEXT_LENGTH),
                    model=getattr(llm_adapter, "model_name", ""),
                )
                pipeline_usage["compacted"] = ctx.get("compacted", False)  # ★ P0 压缩标记
                # ★ 统一 message_end 结构：拆 JSON + 补全字段
                _norm = normalize_structured_response(direct_response)
                if streaming:
                    # 流式模式：先 message_start，再 message 分块，最后 message_end
                    yield {"type": "message_start", "data": {"agent_id": effective_agent_id}}
                    yield {"type": "message", "data": {"chunk": _norm["content"], "agent_id": effective_agent_id}}
                yield {
                    "type": "message_end",
                    "data": {
                        "full_response": _norm["content"],
                        "structured": _norm["structured"],
                        "matched_skills": [],
                        "tool_calls": [],
                        "execution_flow": [{"type": "manager_reasoning", "content": manager_reasoning}] if manager_reasoning else [],
                        "iterations": 0,
                        "tools_used": [],
                        "elapsed_ms": 0,
                        "agent_id": effective_agent_id,
                        "usage": pipeline_usage,
                    }
                }
                message_end_seen = True
            else:
                # ★ 批次10：complex intent 已退役。无论 Manager 输出何种 intent
                #   （含旧模型残留 complex/未知值），一律归一为 task 直跑；
                #   Plan 分步仅当 plan_mode=explicit 且请求显式 use_plan=true 才启用。
                if intent != "task":
                    react_logger.info(f"[Pipeline] intent={intent} 归一化为 task（complex 已退役，批次10）")
                    intent = "task"
                _effective_use_plan = self._resolve_plan_use(use_plan)
                # ★ alert_judge 特殊：传原始 raw_message（纯JSON告警，不含时间/会话上下文）
                worker_message = raw_message if effective_agent_id == "alert_judge" else message
                async for event in self._react_chat_generator(
                    agent_id=effective_agent_id,
                    message=worker_message,
                    session_messages=session_history,
                    session_id=session.id,
                    user_id=user_id,
                    session_summary=session_summary,
                    use_plan=_effective_use_plan,
                    intent=intent,
                    manager_parameters=parameters,
                    correlation_id=correlation_id,
                    mcp_servers=mcp_servers,
                    compact_context=ctx.get("compacted", False),
                ):
                    et = event.get("type")
                    ed = event.get("data", {})
                    # ★ 非流式模式：跳过 think / 正文 chunk 增量，只保留 think_end 与 message_end
                    #   message_start/message 为流式正文转发，非流式下仅由 message_end 携带完整内容
                    if not streaming and et in ("think_start", "think", "message_start", "message"):
                        continue
                    # ★ 统一 message_end：拆 JSON + 收集 reasoning/tool_calls
                    if et == "message_end":
                        if message_end_seen:
                            react_logger.warning("[Pipeline] 检测到重复 message_end，跳过")
                            continue
                        message_end_seen = True
                        raw_full = ed.get("full_response", ed.get("content", ""))
                        full_response = raw_full
                        # ★ 上下文统计：记录 usage 供落库；透传给前端展示 token 占比
                        pipeline_usage = ed.get("usage") or pipeline_usage
                        if isinstance(pipeline_usage, dict):
                            pipeline_usage["compacted"] = ctx.get("compacted", False)  # ★ P0 压缩标记
                        _norm = normalize_structured_response(raw_full)
                        yield {
                            "type": "message_end",
                            "data": {
                                "full_response": _norm["content"],
                                "structured": _norm["structured"],
                                "matched_skills": matched_skills,
                                "tool_calls": full_tool_calls,
                                "execution_flow": _build_execution_flow(
                                    execution_flow_parts, manager_reasoning
                                ),
                                "iterations": ed.get("iterations", 0),
                                "tools_used": ed.get("tools_used", [t["tool_name"] for t in full_tool_calls]),
                                "elapsed_ms": ed.get("elapsed_ms", 0),
                                "agent_id": effective_agent_id,
                                "usage": pipeline_usage,
                            }
                        }
                        continue
                    elif et == "think_end":
                        worker_reasoning = (worker_reasoning + "\n" if worker_reasoning else "") + ed.get("full_reasoning", "")
                        # ★ 按时间轴就地插入 think_end（保持与流式顺序一致）
                        execution_flow_parts.append({
                            "type": "think_end",
                            "phase": "worker",
                            "iteration": ed.get("iteration", 0),
                            "full_reasoning": ed.get("full_reasoning", ""),
                        })
                    elif et == "tool_call":
                        _tc = {
                            "tool_name": ed.get("tool_name", ""),
                            "arguments": ed.get("tool_args", ed.get("arguments", {})),
                            "tool_call_id": ed.get("tool_call_id", ""),
                            "iteration": ed.get("iteration", 0),
                            "result": None,
                            "success": None,
                            "elapsed_ms": 0,
                            "agent_id": effective_agent_id,
                        }
                        full_tool_calls.append(_tc)
                        tool_calls_made.append({
                            "tool_name": _tc["tool_name"],
                            "arguments": _tc["arguments"],
                            "tool_call_id": _tc["tool_call_id"],
                            "iteration": _tc["iteration"],
                            "success": None,
                        })
                        # ★ 按时间轴就地插入 tool_call
                        execution_flow_parts.append({
                            "type": "tool_call",
                            "tool_name": _tc["tool_name"],
                            "arguments": _tc["arguments"],
                            "tool_call_id": _tc["tool_call_id"],
                            "iteration": _tc["iteration"],
                            "agent_id": effective_agent_id,
                        })
                    elif et == "tool_result":
                        # 按 tool_call_id 关联结果；无 id 时挂到最近一次调用
                        _tid = ed.get("tool_call_id", "")
                        _target = None
                        if _tid:
                            for _tc in reversed(full_tool_calls):
                                if _tc.get("tool_call_id") == _tid:
                                    _target = _tc
                                    break
                        if _target is None and full_tool_calls:
                            _target = full_tool_calls[-1]
                        if _target is not None:
                            _target["result"] = ed.get("result")
                            _target["success"] = ed.get("success", True)
                            _target["elapsed_ms"] = ed.get("elapsed_ms", 0)
                            # 同步回填轻量摘要 tool_calls_made 的成功态（工具结果只保留在 execution_flow）
                            if _tid:
                                for _mc in tool_calls_made:
                                    if _mc.get("tool_call_id") == _tid:
                                        _mc["success"] = ed.get("success", True)
                                        break
                            elif tool_calls_made:
                                tool_calls_made[-1]["success"] = ed.get("success", True)
                            # ★ 按时间轴就地插入 tool_result
                            execution_flow_parts.append({
                                "type": "tool_result",
                                "tool_name": _target.get("tool_name", ""),
                                "result": ed.get("result"),
                                "success": ed.get("success", True),
                                "tool_call_id": ed.get("tool_call_id", ""),
                                "iteration": ed.get("iteration", 0),
                                "elapsed_ms": ed.get("elapsed_ms", 0),
                                "agent_id": effective_agent_id,
                            })
                    elif et == "skill_match":
                        matched_skills = ed.get("skills", [])
                    yield event

        except Exception as e:
            react_logger.error(f"[Pipeline] 流水线异常: {e}", exc_info=True)
            yield {"type": "error", "data": {"message": str(e)}}

        # 5. 兜底：如果 ReAct 路径没 yield message_end（异常退出），补一个
        # ★ alert_judge 走专属 pipeline，以 task_complete 终止，不补 message_end
        if not message_end_seen and effective_agent_id != "alert_judge":
            react_logger.warning(f"[Pipeline] 未收到 message_end，强制补一个")
            yield {
                "type": "message_end",
                "data": {
                    "full_response": full_response or "对话未产生有效响应",
                    "structured": None,
                    "matched_skills": matched_skills,
                    "tool_calls": full_tool_calls,
                    "execution_flow": _build_execution_flow(
                        execution_flow_parts, manager_reasoning
                    ),
                    "iterations": 0,
                    "tools_used": [t["tool_name"] for t in tool_calls_made],
                    "elapsed_ms": 0,
                    "agent_id": effective_agent_id,
                }
            }

        # 6. 保存会话（含丰富元数据：思考过程、工具调用、技能匹配）
        if full_response:
            try:
                # 统一结构：content 存纯文本，structured 存 other 字段
                _norm = normalize_structured_response(full_response)
                _reasoning = manager_reasoning + ("\n" + worker_reasoning if worker_reasoning else "")
                # 构建执行流摘要（按时间轴顺序，含完整 reasoning + 工具调用详情）
                execution_flow = _build_execution_flow(
                    execution_flow_parts, manager_reasoning
                )
                if not execution_flow and _norm["structured"]:
                    execution_flow.append({
                        "type": "manager_reasoning",
                        "content": _reasoning,
                    })

                from src.utils.context_usage import usage_to_tokens
                _msg_tokens = usage_to_tokens(pipeline_usage)  # ★ 上下文统计：token 用量落库（累计到 Session.total_tokens）
                session_mgr.add_message(
                    session.id, "assistant", _norm["content"],
                    structured=_norm["structured"],
                    reasoning=_reasoning,
                    tool_calls=tool_calls_made,
                    agent_id=effective_agent_id,
                    task_type=intent,
                    model=(pipeline_usage or {}).get("model") or None,  # ★ P3：实际使用模型（多模型对话按模型统计）
                    tokens=_msg_tokens,
                    execution_flow=execution_flow,
                    status="completed",
                    metadata={
                        "matched_skills": matched_skills,
                        "tools_used": [t["tool_name"] for t in full_tool_calls],
                        "intent": intent,
                        "has_manager_reasoning": bool(manager_reasoning),
                        "manager_reasoning_length": len(manager_reasoning) if manager_reasoning else 0,
                        "tool_call_count": len(full_tool_calls),
                        "context_length": (pipeline_usage or {}).get("context_length"),  # ★ P3：该模型窗口（按模型聚合水位）
                    }
                )
                # ★ 用量统计：LLM token 事件落盘（与 MCP 事件同一事件流，供"按天统计 token 消耗"）
                try:
                    from src.monitoring.usage_store import record_llm_call
                    record_llm_call(
                        model=(pipeline_usage or {}).get("model") or "",
                        prompt_tokens=_msg_tokens.get("prompt", 0),
                        completion_tokens=_msg_tokens.get("completion", 0),
                        source=(pipeline_usage or {}).get("source") or "llm_usage",
                        session_id=session.id,
                    )
                except Exception:
                    pass
                session_mgr.save_session(session.id)
                react_logger.info(
                    f"[Pipeline] Session 已持久化: {session.id}, "
                    f"intent={intent}, tools={len(full_tool_calls)}, "
                    f"reasoning_len={len(_reasoning)}"
                )
            except Exception as e:
                react_logger.warning(f"[Pipeline] save_session 失败: {e}")

    # ========== ReAct 循环集成 ==========