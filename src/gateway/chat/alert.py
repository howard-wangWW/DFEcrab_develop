"""告警直连链路（Alert Domain）

从 `grpc_server.GatewayV2GRPC` 逐字迁出，承载告警 JSON 的"绕开 Manager 编排"的快路径：

    _alert_ephemeral_stream      告警临时会话流（轻量回执）
    _alert_judge_direct_react    直接交给 alert_judge 走 ReAct

告警信号的识别（快检 / 严格判定）在 `chat.intent`，本模块只负责链路编排。
依赖单向：不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, AsyncGenerator, Dict

react_logger = logging.getLogger("dfecrab.react")
logger = logging.getLogger(__name__)


class AlertDomainMixin:
    """告警直连链路（方法实现逐字自 grpc_server 迁出）"""


    async def _alert_ephemeral_stream(
        self,
        alert_json: str,
        user_id: str,
        correlation_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """alert 短期会话（type=alert）：不创建/不落库 session_mgr，强制走 alert_judge。

        与 `_alert_judge_direct_react` 的区别：跳过通用 _run_chat_pipeline 的
        会话管理与上下文注入，避免每次告警在左侧"今日"列表里塞一条无意义记录。
        事件流格式与正常 alert_judge 链路一致：meta → thought → … → task_complete → task_finish。
        """
        yield {
            "type": "meta",
            "id": str(uuid.uuid4()),
            "data": {
                "session_id": "",
                "is_new_session": False,
                "agent_id": "alert_judge",
                "session_summary": "",
                "ephemeral": True,  # ★ 前端可据此识别"一次性研判，不建会话"
            },
            "timestamp": datetime.now().isoformat(),
            "correlation_id": correlation_id,
        }
        try:
            async for event in self._alert_judge_direct_react(
                alert_json=alert_json,
                session_id="",
                user_id=user_id,
                correlation_id=correlation_id,
            ):
                yield event
        except Exception as e:
            react_logger.error(f"[alert_ephemeral] 异常: {e}", exc_info=True)
            yield {
                "type": "error",
                "id": str(uuid.uuid4()),
                "data": {"content": f"alert 处理异常: {str(e)}"},
                "timestamp": datetime.now().isoformat(),
                "correlation_id": correlation_id,
            }

    async def _alert_judge_direct_react(
        self,
        alert_json: str,
        session_id: str,
        user_id: str,
        correlation_id: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """★ alert_judge 专用链路：透传标准三件套适配事件流

        alert_judge 走 src/alert_judge/ 三件套（tools.py / config.py / agent_caller2.py，
        与现场标准文件一一对应）成熟逻辑，产出自己的事件标准
        （thought / chat_stream / tool_start / tool_end / task_complete / error / task_finish），
        不走 DFEcrab 通用事件标准（think_start / think / think_end / tool_call / tool_result / message_end）。

        grpc_server 不做事件类型转换，直接透传给 SSE。
        """
        from mcp_servers.mcp_alert_judge import run as alert_react_run

        correlation_id = correlation_id or str(uuid.uuid4())
        react_logger.info(
            f"[alert_judge] 走专属 pipeline 链路 | "
            f"correlation_id={correlation_id} | alert_json={alert_json[:300]}"
        )

        try:
            async for event in alert_react_run(alert_json, correlation_id=correlation_id):
                # ★ 上下文统计：alert_judge 以 task_complete 终止，本地估算 usage 附加到该事件
                #   （微调模型走文本 ReAct，无 LLM usage；且研判为单轮场景，估算精度要求低）
                if isinstance(event, dict) and event.get("type") == "task_complete" \
                        and isinstance(event.get("data"), dict):
                    try:
                        from src.utils.context_usage import build_context_usage
                        _usage = build_context_usage(
                            system_prompt="你是告警研判助手，基于告警信号与运行数据给出研判结论。",
                            current=alert_json,
                            context_length=self._gateway_context_length(),
                            model=self._gateway_llm_model(),
                        )
                        _usage["source"] = "local_estimate"
                        event = dict(event)
                        event["data"] = dict(event["data"])
                        event["data"]["usage"] = _usage
                    except Exception as _e:
                        react_logger.debug(f"[alert_judge] usage 附加失败（忽略）: {_e}")
                yield event
        except Exception as e:
            react_logger.error(f"[alert_judge] pipeline 异常: {e}", exc_info=True)
            yield {
                "type": "error",
                "id": str(uuid.uuid4()),
                "data": {"content": f"研判流程异常: {str(e)}"},
                "timestamp": datetime.now().isoformat(),
                "correlation_id": correlation_id,
            }

    # ==================== LLM 配置解析（实现见 src/gateway/llm_config.py）====================
