"""ReAct 执行器（React Domain）

从 `grpc_server.GatewayV2GRPC` 逐字迁出：`_react_chat_generator` ——
对话的"思考-行动-观察"循环主体（工具调用、事件流、上下文压缩、答案门控）。

`EVENT_TYPE_MAP`：ReAct 内部事件类型到 SSE 事件类型的映射表（本模块私有）。

依赖单向：不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)
react_logger = logging.getLogger("dfecrab.react")

EVENT_TYPE_MAP = {
    "think_start": "think_start",
    "think": "think",
    "think_end": "think_end",
    "skill_match": "skill_match",
    "tool_call": "tool_call",
    "tool_result": "tool_result",
    "tool_start": "tool_start",
    "tool_progress": "tool_progress",
    "message_end": "message_end",
    "message_start": "message_start",
    "message": "message",           # ★ v4.1: 流式正文 chunk（ReAct 正文 token 实时转发）
    "error": "error",
    "confirmation": "confirmation",
    "plan_created": "plan_created",
    "plan_step": "plan_step",
}


class ReactDomainMixin:
    """ReAct 执行器（方法实现逐字自 grpc_server 迁出）"""

    async def _react_chat_generator(
        self,
        agent_id: str,
        message: str,
        session_messages: List[Dict],
        session_id: str,
        user_id: str = "default",
        session_summary: str = "",
        use_plan: bool = False,
        intent: str = "task",
        manager_parameters: Optional[Dict] = None,
        correlation_id: str = "",
        mcp_servers: Optional[List[str]] = None,
        compact_context: bool = False,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """带 ReAct 循环的流式对话生成器

        当 agent 启用了技能时，使用此方法进行带工具调用的对话。
        ★ P0-4: 集成链路A的4个成熟能力（历史过滤、时间上下文、摘要、记忆沉淀）
        ★ P1-7: use_plan=True 时先调 Planner 拆步骤，再逐步骤跑 ReAct
        ★ 阶段3 Step6: Manager 参数注入 Worker system_prompt
        """
        # ★ tool_choice 决策已下沉到 _resolve_agent_tool_choice（需先归一化 agent_id、
        #   拿到 enabled_skills 才能判定，见下方调用）

        from src.agent.llm.adapter import LLMAdapter
        from src.agent.loop import ReActLoop
        from src.skill.registry import get_tool_registry

        start_time = time.time()

        # ★ 提前归一化 agent_id（default → dfecrab 等）。
        #   必须在此处（预判断之前）归一化，否则下面 _get_agent_skills / has_mcp 用
        #   原始 "default" 查不到配置，ReActLoop 内部虽会 normalize 但根本到不了那里。
        from src.agent.agent_config import normalize_agent_id
        agent_id = normalize_agent_id(agent_id) or "dfecrab"

        # 1. 获取 agent 配置
        enabled_skills = self._get_agent_skills(agent_id)
        system_prompt = self._get_agent_system_prompt(agent_id)

        # ★ tool_choice 决策（多级）：agent config.json 显式配置 > 全局默认策略
        #   背景：qwen3_a3b 等小参数量模型在 auto 下常"不调技能直接编数据"，
        #   task + 启用技能默认 required（ReActLoop 内仅约束第 1 轮，后续轮回 auto）
        tool_choice = self._resolve_agent_tool_choice(
            agent_id=agent_id,
            intent=intent,
            enabled_skills=enabled_skills,
        )

        # ★ 阶段3 Step6: 注入 Manager 参数到 system_prompt
        if manager_parameters:
            params_str = json.dumps(manager_parameters, ensure_ascii=False, indent=2)
            system_prompt += f"\n\n【Manager 提取的参数】\n{params_str}"
            react_logger.info(f"[ReAct] 注入 Manager 参数到 [{agent_id}]: {list(manager_parameters.keys())}")

        # ★ MCP instructions 注入（对齐 LibreChat serverInstructions：服务端声明的
        #   工具调用 SOP 进入 system_prompt，弱模型也能遵守"先 search_feeders 定位唯一
        #   file、再 get_feeder_topology 取拓扑"等规范）
        if mcp_servers:
            try:
                from src.mcp import get_mcp_client
                _ins_parts = []
                for _sn in mcp_servers:
                    _ins = get_mcp_client().get_server_instructions(_sn)
                    if _ins and _ins.strip():
                        _ins_parts.append(f"【{_sn} MCP 使用须知】\n{_ins.strip()}")
                if _ins_parts:
                    system_prompt += "\n\n" + "\n\n".join(_ins_parts)
                    react_logger.info(f"[ReAct] 注入 MCP instructions: {mcp_servers}")
            except Exception as e:
                react_logger.warning(f"[ReAct] MCP instructions 注入失败: {e}")
        
        # ★ MCP 绑定决定是否进 ReAct（工具池确有该 agent 绑定的 MCP 工具）
        has_mcp = False
        try:
            has_mcp = get_tool_registry().has_mcp_tools_for_agent(agent_id)
        except Exception:
            has_mcp = False

        # ★ alert_judge 为空壳智能体：走专属微调模型文本 ReAct 旁路，
        #   不依赖本地技能/MCP 绑定/传参的通用装配判断（主路径靠传 alert_judge_tools 触发，
        #   P0 快速路由为自动兜底）
        if agent_id != "alert_judge" and not enabled_skills and not has_mcp and not mcp_servers:
            # 无本地技能、未绑定 MCP 工具、且未通过请求体 mcp 参数临时指定 → 使用普通对话模式
            react_logger.info(f"[ReAct] Agent [{agent_id}] 无启用的技能、无绑定 MCP、未传 mcp 参数")
            yield {
                "type": "message",
                "data": {
                    "content": "该Agent未配置技能，使用普通对话模式",
                    "agent_id": agent_id
                }
            }
            return

        react_logger.info(
            f"[ReAct] Agent [{agent_id}] 启用技能: {enabled_skills} | "
            f"绑定MCP激活: {has_mcp}"
        )

        # 2. 获取 LLM 配置（★ 按 agent 模型解析：model_config 优先，否则跟随全局）
        llm_config = self._resolve_agent_llm_config(agent_id)
        if not llm_config:
            yield {
                "type": "error",
                "data": {"content": "LLM 配置不可用"}
            }
            return

        # ★ P0-4 能力1: 语义历史过滤（复用链路A的 HistoryFilter）
        filtered_history = session_messages
        try:
            filtered_history = self._history_filter.filter_history(
                current_msg=message,
                history=session_messages
            )
        except Exception as e:
            react_logger.warning(f"[ReAct] 历史过滤失败，使用原始历史: {e}")

        # ★ 时间上下文注入 system_prompt（不混入用户消息，避免模型把系统时间当用户问题）
        # alert_judge 的消息是 JSON 告警信号，不需要时间上下文
        enhanced_message = message
        if agent_id != "alert_judge":
            try:
                from src.utils.time_parser import get_time_context
                system_prompt = f"{get_time_context()}\n\n{system_prompt}"
            except Exception as e:
                react_logger.warning(f"[ReAct] 时间上下文生成失败: {e}")

            # ★ 沙箱工具移植（深圳现场）：登记请求级会话上下文。
            #   ToolRegistry.execute_tool 只透传模型参数，工具函数本身取不到 session_id；
            #   沙箱工具（bash_tool / read_file）需要它来定位本会话的附件与工作区。
            #   用 locals() 取值以兼容不同版本的变量命名。
            try:
                from src.sandbox.context import set_request_context_from_locals
                set_request_context_from_locals(locals())
            except Exception as e:
                react_logger.warning(f"[Sandbox] 请求上下文登记失败（忽略继续）: {e}")

            # ★ 批次12-C2：会话附件自动注入（本会话 active 附件摘要进上下文）。
            #   生命周期对齐 LibreChat：上传即挂会话 → 每轮自动带上 → 叉掉/删除后不再注入
            #   （build_session_context 只取 status=active；删会话由 delete_session 联动清理）。
            #   仅注入"发给模型的当前轮"，不污染历史/摘要（历史已按原始 message 落库）。
            try:
                from src.files.service import FileService
                _ctx_len = int((llm_config or {}).get("context_length") or 0) or 32768
                _attach_block = FileService.build_session_context(session_id or "", _ctx_len)
                if _attach_block:
                    enhanced_message = _attach_block + "\n\n" + enhanced_message
                    react_logger.info(
                        f"[Pipeline] 会话附件注入 {len(_attach_block)} 字符 (session={session_id})"
                    )
            except Exception as e:
                react_logger.warning(f"[Pipeline] 会话附件注入失败（忽略继续）: {e}")

        # ★ alert_judge 特殊处理：走标准三件套适配链路（src/alert_judge/ 对应现场标准文件），
        #   跳过通用 LLM 层。agent_caller2 按 Thought:/Action: 文本 ReAct 输出，
        #   工具由标准 tools.py 直连后端服务执行，产出完整 thought/tool_call/task 事件流。
        if agent_id == "alert_judge":
            react_logger.info(f"[ReAct] alert_judge 专用链路：标准三件套（src/alert_judge）")
            async for event in self._alert_judge_direct_react(
                alert_json=enhanced_message,
                session_id=session_id,
                user_id=user_id,
                correlation_id=correlation_id,
            ):
                yield event
            return

        # 3. 构建消息列表
        messages = []
        # 添加历史消息（已过滤）——HistoryFilter 现按"持续上下文"默认带回最近 6 条完整轮。
        # ★ P0：本次触发过自动压缩时保留最近 4 条（老上下文已由摘要承担）；普通场景取 6 条
        _hist_num = 4 if compact_context else 6
        recent_history = filtered_history[-_hist_num:] if len(filtered_history) > _hist_num else filtered_history
        for msg in recent_history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            messages.append({"role": role, "content": content})
        
        # 添加当前用户消息（增强版）
        messages.append({"role": "user", "content": enhanced_message})

        # 4. 初始化 ReAct 循环
        llm_adapter = LLMAdapter(llm_config)
        tool_registry = get_tool_registry()
        # ★ ReAct 最大轮数：读 dfecrab.json agent_defaults.max_iterations（AgentConfig.from_id 已合并全局默认），兜底 3
        _max_iter = 3
        try:
            from src.agent.agent_config import AgentConfig
            _max_iter = int(AgentConfig.from_id(agent_id).max_iterations or 3)
        except Exception:
            pass
        react_logger.info(f"[ReAct] Agent[{agent_id}] 最大轮数={_max_iter}")
        react_loop = ReActLoop(
            llm_adapter=llm_adapter,
            tool_registry=tool_registry,
            max_iterations=_max_iter
        )

        # ★ 统一初始化（批次10 修复：此前 tool_calls_made 仅在非 Plan 分支初始化，
        #   Plan 分支收尾使用 → complex 任务必崩 UnboundLocalError）
        tool_calls_made = []
        matched_skills = []

        # ★ S3.1: Plan 模式（执行器保留：供 plan_mode=explicit / 未来多智能体编排复用）
        plan = None
        if use_plan:
            from src.agent.planner import get_task_planner
            planner = get_task_planner()
            plan = await planner.plan(
                user_message=message,
                llm_adapter=llm_adapter,
                enabled_skills=enabled_skills,
            )
            if plan.steps:
                yield {
                    "type": "plan_created",
                    "data": {
                        "plan_id": plan.id,
                        "steps": [s.to_dict() for s in plan.steps],
                        "total": plan.total,
                        "agent_id": agent_id,
                    }
                }
                logger.info(
                    f"[ReAct+Plan] 开始执行 {plan.total} 步计划 (plan_id={plan.id})"
                )

        # ★ S3.1: 如果有 plan 且有 steps，逐步骤执行
        if plan and plan.steps:
            full_response_parts = []

            for step in plan.steps:
                planner.start_step(step.index)
                step_event = yield {
                    "type": "plan_step",
                    "data": {
                        "step_index": step.index,
                        "step_desc": step.description,
                        "status": "running",
                        "agent_id": agent_id,
                    }
                }

                # 构建该步骤的提示消息
                step_message = (
                    f"【步骤 {step.index}/{plan.total}】{step.description}\n"
                    + (f"建议工具: {step.suggested_tool}" if step.suggested_tool else "")
                )
                step_messages = list(messages)  # 复制原始消息
                step_messages.append({"role": "user", "content": step_message})

                # 为该步骤运行 ReAct 循环
                step_response = ""
                step_tool_calls = []

                async for event in react_loop.run(
                    messages=step_messages,
                    agent_id=agent_id,
                    enabled_skills=enabled_skills,
                    system_prompt=system_prompt,
                    # temperature / max_tokens 不传 → 由 LLMAdapter 从 dfecrab.json provider 读取
                    tool_choice=tool_choice,
                    mcp_servers=mcp_servers,
                    user_id=user_id,
                ):
                    event_type = event.get("type")
                    event_data = event.get("data", {})

                    if event_type == "tool_call":
                        step_tool_calls.append({
                            "tool_name": event_data.get("tool_name", ""),
                            "arguments": event_data.get("tool_args", event_data.get("arguments", {})),
                        })

                    elif event_type == "message_end":  # ★ final → message_end
                        step_response = event_data.get("full_response", event_data.get("content", ""))

                    # 透传事件给前端（加上步骤上下文）
                    mapped_type = EVENT_TYPE_MAP.get(event_type, event_type)
                    yield {
                        "type": mapped_type,
                        "data": {
                            **event_data,
                            "step_index": step.index,
                            "step_desc": step.description,
                            "agent_id": agent_id,
                        }
                    }

                    # EventBus 派发
                    if self._event_bus:
                        try:
                            await self._event_bus.publish_react(
                                event_type=event_type,
                                data=event_data,
                                session_id=session_id,
                                user_id=user_id,
                            )
                        except Exception:
                            pass

                # 保存步骤结果
                if step_response:
                    full_response_parts.append(f"步骤{step.index}: {step_response}")
                    planner.set_step_result(step.index, step_response)
                    planner.complete_step(step.index)
                    tool_calls_made.extend(step_tool_calls)

                    yield {
                        "type": "plan_step",
                        "data": {
                            "step_index": step.index,
                            "step_desc": step.description,
                            "status": "completed",
                            "result": step_response,
                            "agent_id": agent_id,
                        }
                    }
                    logger.info(f"[ReAct+Plan] 步骤 {step.index} 完成")
                else:
                    planner.fail_step(step.index)
                    yield {
                        "type": "plan_step",
                        "data": {
                            "step_index": step.index,
                            "step_desc": step.description,
                            "status": "failed",
                            "result": "步骤未返回有效结果",
                            "agent_id": agent_id,
                        }
                    }
                    logger.warning(f"[ReAct+Plan] 步骤 {step.index} 失败")

            full_response = "\n\n".join(full_response_parts)
            planner.current_plan.status = "completed"
            logger.info(f"[ReAct+Plan] 计划完成 (plan_id={plan.id})")

        # ★ 非 Plan 模式：直接跑 ReAct 循环
        else:
            # 5. 运行 ReAct 循环（内联，S3.1 保留原有逻辑）
            #   tool_calls_made / matched_skills 已在函数顶部统一初始化（批次10，Plan/非 Plan 共用）
            full_response = ""

            async for event in react_loop.run(
                messages=messages,
                agent_id=agent_id,
                enabled_skills=enabled_skills,
                system_prompt=system_prompt,
                # temperature / max_tokens 不传 → 由 LLMAdapter 从 dfecrab.json provider 读取
                tool_choice=tool_choice,
                mcp_servers=mcp_servers,
                user_id=user_id,
            ):
                event_type = event.get("type")
                event_data = event.get("data", {})
                mapped_type = EVENT_TYPE_MAP.get(event_type, event_type)

                # ★ S2.2: 协议事件透传（格式已对齐 event_types.py）
                # ★ v4.0: thinking 拆为三段式 think_start / think / think_end
                if event_type == "think_start":
                    yield {
                        "type": "think_start",
                        "data": {
                            "phase": event_data.get("phase", "worker"),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "think":
                    yield {
                        "type": "think",
                        "data": {
                            "chunk": event_data.get("chunk", ""),  # ★ content → chunk
                            "phase": event_data.get("phase", "worker"),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "think_end":
                    yield {
                        "type": "think_end",
                        "data": {
                            "full_reasoning": event_data.get("full_reasoning", ""),
                            "phase": event_data.get("phase", "worker"),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "skill_match":  # ★ 独立事件
                    matched_skills = event_data.get("skills", [])
                    yield {
                        "type": "skill_match",
                        "data": {
                            "skills": event_data.get("skills", []),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "tool_call":
                    # ★ S2.2: 使用 event_data（make_event 格式）
                    tool_name = event_data.get("tool_name", "")
                    arguments = event_data.get("tool_args", event_data.get("arguments", {}))
                    tool_calls_made.append({
                        "tool_name": tool_name,
                        "arguments": arguments
                    })

                    yield {
                        "type": mapped_type,
                        "data": {
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "content": f"调用技能: {tool_name}({json.dumps(arguments, ensure_ascii=False)})",
                            "agent_id": agent_id
                        }
                    }

                elif event_type == "tool_result":
                    result = event_data.get("result", {})
                    # ★ 展示工具执行的实质内容（stdout/stderr），替代机械的"技能执行完成: success"
                    _status = "done"
                    _summary = ""
                    if isinstance(result, dict):
                        _status = result.get("status", "unknown")
                        _inner = result.get("content", {})
                        if isinstance(_inner, dict):
                            _summary = _inner.get("stdout", "") or _inner.get("stderr", "")
                        if not _summary:
                            _summary = result.get("error", "") or ""
                    _summary = str(_summary).strip()[:200]
                    _content = f"技能执行完成: {_status}"
                    if _summary:
                        _content += f" | {_summary}"
                    yield {
                        "type": mapped_type,
                        "data": {
                            "tool_name": event_data.get("tool_name", ""),
                            "result": result,
                            "success": event_data.get("success", True),
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "elapsed_ms": event_data.get("elapsed_ms", 0),
                            "corrected": event_data.get("corrected", False),
                            "content": _content,
                            "agent_id": agent_id
                        }
                    }

                elif event_type == "tool_start":
                    yield {
                        "type": "tool_start",
                        "data": {
                            "tool_name": event_data.get("tool_name", ""),
                            "tool_args": event_data.get("tool_args", {}),
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "start_time": event_data.get("start_time", 0.0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "tool_progress":
                    yield {
                        "type": "tool_progress",
                        "data": {
                            "tool_name": event_data.get("tool_name", ""),
                            "tool_call_id": event_data.get("tool_call_id", ""),
                            "iteration": event_data.get("iteration", 0),
                            "progress": event_data.get("progress", ""),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "message_start":  # ★ v4.0: 正文开始（透传给前端）
                    yield {
                        "type": "message_start",
                        "data": {
                            "agent_id": agent_id
                        }
                    }

                elif event_type == "message":  # ★ v4.1: 流式正文 chunk（loop.py 实时 token 转发）
                    yield {
                        "type": "message",
                        "data": {
                            "chunk": event_data.get("chunk", ""),
                            "iteration": event_data.get("iteration", 0),
                            "agent_id": agent_id,
                        }
                    }

                elif event_type == "message_end":  # ★ final → message_end
                    full_response = event_data.get("full_response", event_data.get("content", ""))
                    yield {
                        "type": "message_end",
                        "data": {
                            "full_response": full_response,
                            "iterations": event_data.get("iterations", 0),
                            "tools_used": event_data.get("tools_used", []),
                            "elapsed_ms": int((time.time() - start_time) * 1000),
                            "agent_id": agent_id,
                            # ★ 上下文统计：透传 ReActLoop 计算的 usage（token 占比）
                            "usage": event_data.get("usage"),
                        }
                    }

                elif event_type == "error":
                    yield {
                        "type": mapped_type,
                        "data": {
                            "message": event_data.get("message", event_data.get("content", "Unknown error")),
                            "iteration": event_data.get("iteration", 0),
                            "recoverable": event_data.get("recoverable", False),
                            "agent_id": agent_id
                        }
                    }
                    # 只有不可恢复的错误才 return
                    if not event_data.get("recoverable", False):
                        return

                elif event_type == "confirmation":
                    yield {
                        "type": mapped_type,
                        "data": {
                            "message": event_data.get("message", ""),
                            "options": event_data.get("options", []),
                            "timeout_sec": event_data.get("timeout_sec", 0),
                            "tool_name": event_data.get("tool_name", ""),
                            "error": event_data.get("error", ""),
                            "agent_id": agent_id,
                        }
                    }

                # ★ S2.3: EventBus 派发 ReAct 事件（所有事件类型透传）
                if self._event_bus:
                    try:
                        await self._event_bus.publish_react(
                            event_type=event_type,
                            data=event_data,
                            session_id=session_id,
                            user_id=user_id,
                        )
                    except Exception:
                        pass  # EventBus 派发失败不中断主流程

        # ★ P0-4 能力3+4: 会话摘要 + 记忆沉淀（复用链路A的 save_daily_memory + add_to_long_term）
        elapsed = time.time() - start_time
        try:
            # 3. 更新会话摘要
            if session_summary:
                try:
                    from src.session.manager import get_session_manager
                    sm = get_session_manager()
                    sm.set_summary(session_id, session_summary)
                except Exception:
                    pass
            
            # 4. 沉淀每日记忆 + 长期记忆
            from src.memory.global_manager import get_global_memory_manager
            from src.memory.long_term import MemoryManager
            global_memory_mgr = get_global_memory_manager()
            
            memory_content = f"""
会话ID: {session_id}
用户: {user_id}
用户消息: {message[:200]}
AI响应: {full_response[:500] if full_response else '(无文本响应)'}
使用的工具: {[t['tool_name'] for t in tool_calls_made] if tool_calls_made else '无'}
"""
            mem_category = "conversation" if full_response else "error_log"
            global_memory_mgr.save_daily_memory(memory_content, category=mem_category, user_id=user_id)
            
            # ★ S3.5: Plan 模式 Memory 持久化（按 plan_id 维度存取）
            if plan and plan.steps:
                plan_memory_content = (
                    f"[计划 {plan.id}]\n"
                    f"用户消息: {message[:200]}\n"
                    f"总步骤: {plan.total} / 完成: {plan.completed}\n"
                    f"步骤详情:\n" +
                    "\n".join(
                        f"  [{s.status}] 步骤{s.index}: {s.description}"
                        for s in plan.steps
                    ) +
                    f"\n最终结果: {full_response[:500] if full_response else '(无)'}"
                )
                try:
                    global_memory_mgr.save_daily_memory(
                        plan_memory_content,
                        category="plan_execution",
                        user_id=user_id,
                    )
                except Exception:
                    pass

                # 长期记忆：plan 级别的经验沉淀
                try:
                    mm = MemoryManager(agent_id=agent_id, user_id=user_id)
                    plan_tags = ["react", "plan", agent_id, plan.status]
                    mm.add_to_long_term(
                        "plan_executions",
                        f"计划 {plan.id}: {plan.total} 步, 完成 {plan.completed}, 状态 {plan.status}",
                        tags=plan_tags,
                    )
                except Exception:
                    pass

                logger.info(
                    f"[ReAct+Plan] Plan 记忆已持久化 (plan_id={plan.id}, "
                    f"steps={plan.total}/{plan.completed})"
                )
            
            # 长期记忆（按 agent + user 写入）
            try:
                mm = MemoryManager(agent_id=agent_id, user_id=user_id)
                mm.add_to_long_term(
                    "successful_patterns" if full_response else "lessons_learned",
                    f"会话 {session_id}: {message[:100]} -> {full_response[:200] if full_response else '无响应'}",
                    tags=["react", agent_id]
                )
            except Exception:
                pass
            
            react_logger.info(f"[ReAct] 记忆已沉淀 (session={session_id}, elapsed={elapsed:.2f}s)")

            # ★ 阶段B: 自动提取用户事实（LLM，fire-and-forget，不阻塞主流程）
            if full_response and (message or "").strip():
                try:
                    from src.memory.extractor import UserFactExtractor
                    asyncio.create_task(
                        UserFactExtractor().extract_and_store(
                            llm_adapter, message, full_response, user_id
                        )
                    )
                except Exception:
                    pass

            # ★ 阶段C: 长对话滚动摘要（LLM，fire-and-forget，每 N 轮合并一次）
            if session_id:
                try:
                    from src.memory.summarizer import SessionSummarizer
                    asyncio.create_task(
                        SessionSummarizer().maybe_rolling_summary(
                            llm_adapter, session_id, user_id
                        )
                    )
                except Exception:
                    pass

            # ★ 持久化会话由主链路 _run_chat_pipeline 统一负责（含 reasoning/工具/技能元数据），
            #   此处不再重复保存，避免历史出现无思考内容的裸 assistant 消息
        except Exception as e:
            react_logger.warning(f"[ReAct] 记忆沉淀失败（降级继续）: {e}")

        # ★ G2 修复: 不再 yield 重复的 message_end
        # ReActLoop.run() 内部已 yield 过 message_end（L3749-3760 转发逻辑）
        # 此处再 yield 会产生双 message_end 事件
        react_logger.debug(f"[ReAct] 流生成器结束，message_end 由 ReActLoop 统一 yield")

        # ★ S5.4: 反思已由 ReActLoop 后台执行（_reflect_in_background），
        #   网关侧不再重复触发，避免一次对话反思两次、重复写记忆。

    # ★ S1.2: 旧版 _classify_intent + _CHAT_PATTERNS / _COMPLEX_PATTERNS 已迁移至
    #   src/agent/intent_classifier.py → IntentClassifier 类
    #   此处不再保留重复定义。
