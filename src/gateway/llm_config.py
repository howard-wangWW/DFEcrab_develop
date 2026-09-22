"""网关 LLM 配置解析（纯函数，供对话链路 / 用量统计 / 上下文占比共用）

从 `GatewayV2GRPC` 抽出：
    get_gateway_llm_config()          全局默认模型配置（current_provider，带 alive 校验 + fallback）
    resolve_agent_llm_config(agent_id) Agent 固定模型优先，回落全局
    gateway_context_length()          当前模型上下文窗口
    gateway_llm_model()               当前模型名
    context_engine_conf()             上下文引擎参数（dfecrab.json 的 react 段）

依赖单向：本模块不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict

from src.services.model_manager import model_manager
from src.utils.context_usage import DEFAULT_CONTEXT_LENGTH

logger = logging.getLogger(__name__)

#: 项目根目录（src/gateway/llm_config.py → 上溯 2 层）
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_gateway_llm_config() -> Dict:
    """获取全局默认 LLM 配置（timeout 默认 600s）。

    使用 current_provider（`/api/models/switch` 切换即真正生效），
    主配置不可用（disabled / 探活失败）时回落第一个存活配置，均不可用返回 {}。
    """
    try:
        provider_cfg = model_manager.get_provider_config()  # current_provider
        if provider_cfg and provider_cfg.get("enabled", False):
            if model_manager._check_alive(provider_cfg, verify_content=True):
                return {
                    "api_base": provider_cfg.get("api_base", ""),
                    "model_name": provider_cfg.get("model_name", ""),
                    "timeout": provider_cfg.get("timeout", 600),
                    "temperature": provider_cfg.get("temperature", 0.7),
                    "max_tokens": provider_cfg.get("max_tokens", 1024),
                    "api_key": provider_cfg.get("api_key", "not-needed"),
                    "context_length": provider_cfg.get("context_length", DEFAULT_CONTEXT_LENGTH),
                    "think_config": provider_cfg.get("think_config") or None,
                    # 思考开关/模板参数透传（否则白名单会丢掉，现场表现为"配了不生效"）
                    "enable_thinking": provider_cfg.get("enable_thinking"),
                    "chat_template_kwargs": provider_cfg.get("chat_template_kwargs") or None,
                    "provider_name": provider_cfg.get("config_name", ""),
                }
    except Exception as e:
        logger.warning(f"⚠️ 主模型配置读取失败: {e}")
    # fallback
    try:
        alive = model_manager.get_all_alive_configs()
        if alive:
            return {
                "api_base": alive[0].get("api_base", ""),
                "model_name": alive[0].get("model_name", ""),
                "timeout": alive[0].get("timeout", 600),
                "temperature": alive[0].get("temperature", 0.7),
                "max_tokens": alive[0].get("max_tokens", 1024),
                "api_key": alive[0].get("api_key", "not-needed"),
                "context_length": alive[0].get("context_length", DEFAULT_CONTEXT_LENGTH),
                "think_config": alive[0].get("think_config") or None,
                "enable_thinking": alive[0].get("enable_thinking"),
                "chat_template_kwargs": alive[0].get("chat_template_kwargs") or None,
                "provider_name": alive[0].get("config_name", ""),
            }
    except Exception as e:
        logger.warning(f"⚠️ Fallback 模型读取失败: {e}")
    return {}


def resolve_agent_llm_config(agent_id: str) -> Dict:
    """按优先级解析 Agent 执行用 LLM 配置：

    1. Agent 配置的 `model_config`（最高优先级，固定模型，不受全局切换影响）
    2. 全局默认模型（回落 `get_gateway_llm_config()`）
    """
    try:
        cfg_path = PROJECT_ROOT / "agents" / agent_id / "config.json"
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            mc = (data.get("model_config") or "").strip()
            if mc:
                pc = model_manager.get_provider_config(mc)
                if pc and pc.get("enabled", False):
                    return {
                        "api_base": pc.get("api_base", ""),
                        "model_name": pc.get("model_name", ""),
                        "timeout": pc.get("timeout", 600),
                        "temperature": pc.get("temperature", 0.7),
                        "max_tokens": pc.get("max_tokens", 2048),
                        "api_key": pc.get("api_key", "not-needed"),
                        "context_length": pc.get("context_length", DEFAULT_CONTEXT_LENGTH),
                        "think_config": pc.get("think_config") or None,
                        "enable_thinking": pc.get("enable_thinking"),
                        "chat_template_kwargs": pc.get("chat_template_kwargs") or None,
                        "provider_name": mc,
                    }
    except Exception as e:
        logger.warning(f"⚠️ Agent 模型解析失败（走全局）: {agent_id}: {e}")
    cfg = get_gateway_llm_config()
    cfg["provider_name"] = cfg.get("provider_name", "")
    return cfg


def gateway_context_length() -> int:
    """当前网关 LLM 模型的上下文窗口大小（供上下文占比计算）"""
    try:
        return int(get_gateway_llm_config().get("context_length", DEFAULT_CONTEXT_LENGTH)
                   or DEFAULT_CONTEXT_LENGTH)
    except Exception:
        return DEFAULT_CONTEXT_LENGTH


def gateway_llm_model() -> str:
    """当前网关 LLM 模型名（用于上下文占比按模型统计 / 标注口径）"""
    try:
        return get_gateway_llm_config().get("model_name", "") or ""
    except Exception:
        return ""


def context_engine_conf() -> Dict:
    """读取上下文引擎配置（`config/dfecrab.json` 的 react 段，回落旧 context_engine 段）。

    - auto_compact_threshold: 上下文占用达该比例触发自动压缩（默认 0.85）
    - compact_keep_recent:    压缩后保留最近消息轮数（默认 2）
    """
    try:
        cfg_path = PROJECT_ROOT / "config" / "dfecrab.json"
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            ce = data.get("react") or data.get("context_engine") or {}
            return {
                "auto_compact_threshold": float(ce.get("auto_compact_threshold", 0.85)),
                "compact_keep_recent": int(ce.get("compact_keep_recent", 2)),
            }
    except Exception as e:
        logger.warning(f"⚠️ react/context_engine 配置读取失败: {e}")
    return {"auto_compact_threshold": 0.85, "compact_keep_recent": 2}