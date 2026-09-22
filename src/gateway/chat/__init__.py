"""对话域（Chat Domain）

把原本堆在 `grpc_server.py` 里的对话相关能力按职责拆成独立模块，
`GatewayV2GRPC` 只保留薄入口与编排：

    intent.py        意图/信号解析（告警 JSON 识别、JSON 提取、提示词截断）—— 纯函数
    （后续阶段）pipeline.py / react.py / display_think.py / alert.py / llm_config.py

约定：本包**不得** import `src.gateway.grpc_server`（依赖单向）。
"""

from src.gateway.chat.intent import (  # noqa: F401
    ALERT_JSON_FIELDS,
    extract_json_fragment,
    extract_json_object,
    is_alert_signal_json,
    looks_like_alert_json,
    normalize_target_agent,
    truncate_system_prompt,
)

__all__ = [
    "ALERT_JSON_FIELDS",
    "looks_like_alert_json",
    "is_alert_signal_json",
    "normalize_target_agent",
    "extract_json_object",
    "extract_json_fragment",
    "truncate_system_prompt",
]
