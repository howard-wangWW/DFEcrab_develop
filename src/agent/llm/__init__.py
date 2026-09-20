"""
LLM 适配层 - agent.llm 域
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.llm.adapter import LLMAdapter, LLMAdapterManager
    from src.agent.llm.service import LLMService, LegacyLLMService
    from src.agent.llm.fallback import ModelFallbackManager, FallbackHandler
    from src.agent.llm.retry import RetryConfig, RetryManager

__all__ = [
    'LLMAdapter', 'LLMAdapterManager',
    'LLMService', 'LegacyLLMService',
    'ModelFallbackManager', 'FallbackHandler', 'get_fallback_manager',
    'get_default_think_config', 'get_think_config_for_model',
    'remove_think_tags', 'extract_think_content', 'strip_cot',
    'find_first_tag_position', 'check_split_tag',
    'RetryConfig', 'RetryManager', 'get_retry_manager',
]


def __getattr__(name: str):
    if name in {"LLMAdapter", "LLMAdapterManager"}:
        from src.agent.llm.adapter import LLMAdapter, LLMAdapterManager

        return {
            "LLMAdapter": LLMAdapter,
            "LLMAdapterManager": LLMAdapterManager,
        }[name]
    if name in {"LLMService", "LegacyLLMService"}:
        from src.agent.llm.service import LLMService, LegacyLLMService

        return {
            "LLMService": LLMService,
            "LegacyLLMService": LegacyLLMService,
        }[name]
    if name in {"ModelFallbackManager", "FallbackHandler", "get_fallback_manager"}:
        from src.agent.llm.fallback import ModelFallbackManager, FallbackHandler, get_fallback_manager

        return {
            "ModelFallbackManager": ModelFallbackManager,
            "FallbackHandler": FallbackHandler,
            "get_fallback_manager": get_fallback_manager,
        }[name]
    if name in {
        "get_default_think_config",
        "get_think_config_for_model",
        "remove_think_tags",
        "extract_think_content",
        "strip_cot",
        "find_first_tag_position",
        "check_split_tag",
    }:
        from src.agent.llm.think import (
            get_default_think_config,
            get_think_config_for_model,
            remove_think_tags,
            extract_think_content,
            strip_cot,
            find_first_tag_position,
            check_split_tag,
        )

        return {
            "get_default_think_config": get_default_think_config,
            "get_think_config_for_model": get_think_config_for_model,
            "remove_think_tags": remove_think_tags,
            "extract_think_content": extract_think_content,
            "strip_cot": strip_cot,
            "find_first_tag_position": find_first_tag_position,
            "check_split_tag": check_split_tag,
        }[name]
    if name in {"RetryConfig", "RetryManager", "get_retry_manager"}:
        from src.agent.llm.retry import RetryConfig, RetryManager, get_retry_manager

        return {
            "RetryConfig": RetryConfig,
            "RetryManager": RetryManager,
            "get_retry_manager": get_retry_manager,
        }[name]
    raise AttributeError(f"module 'src.agent.llm' has no attribute {name!r}")
