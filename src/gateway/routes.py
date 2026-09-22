"""HTTP 路由声明表（唯一事实源）

把原先散落在 `GatewayV2GRPC._register_routes` 里的 400 行 if/append 收敛为一张声明表：

    (HTTP方法, 路径, handler 引用, 权限级别, 是否仅 admin)

handler 引用形式：
    "gw:<method>"                      → GatewayV2GRPC 的绑定方法（如 gw:_handle_health）
    "mod:<模块路径>:<类>.<方法>"         → 惰性 import 后取属性（如 mod:src.gateway.handlers.mcp_handler:MCPHandler.list_servers）

设计要点：
- 只声明，不 import handler → 本文件可被静态分析/测试直接读取（零依赖、无副作用）；
- 顺序即匹配优先级：**静态路径在前，参数化路径在后**，调整顺序会改变匹配结果；
- 权限级别缺省由方法推导（POST/PUT/DELETE/PATCH=write，其余=read）；
- providers（plan_router / task）保留原注册与去重语义，见 PROVIDERS。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, Dict, List, Tuple

#: 路由声明：(method, path, handler_ref, required_level, admin_only)
ROUTES: List[Tuple[str, str, str, str, bool]] = [
    ("GET", "/health", "gw:_handle_health", "read", False),
    ("POST", "/api/v2/chat", "gw:_handle_chat", "write", False),
    ("POST", "/api/v2/chat/stream", "gw:_handle_chat_stream", "write", False),
    ("GET", "/api/v2/workers", "mod:src.gateway.handlers.worker_handler:WorkerHandler.list_workers", "read", False),
    ("GET", "/api/v2/sessions", "mod:src.gateway.handlers.session_handler:SessionHandler.list_sessions", "read", False),
    ("POST", "/api/v2/sessions", "mod:src.gateway.handlers.session_handler:SessionHandler.create_session", "write", False),
    ("GET", "/api/v2/sessions/{session_id}", "mod:src.gateway.handlers.session_handler:SessionHandler.get_session", "read", False),
    ("GET", "/api/v2/sessions/{session_id}/messages", "mod:src.gateway.handlers.session_handler:SessionHandler.get_messages", "read", False),
    ("GET", "/api/v2/sessions/{session_id}/usage", "mod:src.gateway.handlers.usage_handler:UsageHandler.session_usage", "read", False),
    ("GET", "/api/v2/usage/stats", "mod:src.gateway.handlers.usage_handler:UsageHandler.usage_stats", "read", False),
    ("DELETE", "/api/v2/sessions/deleteSession/{session_id}", "mod:src.gateway.handlers.session_handler:SessionHandler.close_session", "write", False),
    ("GET", "/api/users", "mod:src.gateway.handlers.user_handler:UserHandler.list_users", "read", True),
    ("POST", "/api/users", "mod:src.gateway.handlers.user_handler:UserHandler.create_user", "write", True),
    ("PUT", "/api/users/{user_id}", "mod:src.gateway.handlers.user_handler:UserHandler.update_user", "write", True),
    ("DELETE", "/api/users/{user_id}", "mod:src.gateway.handlers.user_handler:UserHandler.delete_user", "write", True),
    ("GET", "/api/agents", "gw:_handle_list_agents", "read", False),
    ("POST", "/api/agents", "gw:_handle_create_agent", "write", False),
    ("GET", "/api/agents/{agent_id}", "gw:_handle_get_agent", "read", False),
    ("PUT", "/api/agents/{agent_id}", "gw:_handle_update_agent", "write", False),
    ("DELETE", "/api/agents/{agent_id}", "gw:_handle_delete_agent", "write", False),
    ("PUT", "/api/agents/{agent_id}/default", "gw:_handle_set_default_agent", "write", False),
    ("DELETE", "/api/agents/{agent_id}/default", "gw:_handle_clear_default_agent", "write", False),
    ("GET", "/api/services", "mod:src.gateway.handlers.worker_handler:WorkerHandler.list_services", "read", False),
    ("GET", "/api/invariants", "mod:src.gateway.handlers.worker_handler:WorkerHandler.check_invariants", "read", False),
    ("GET", "/api/skills", "mod:src.gateway.handlers.skill_handler:SkillHandler.list_skills", "read", False),
    ("POST", "/api/skills/reload", "mod:src.gateway.handlers.skill_handler:SkillHandler.reload", "write", False),
    ("GET", "/api/skills/search", "mod:src.gateway.handlers.skill_handler:SkillHandler.search", "read", False),
    ("GET", "/api/mcp/servers", "mod:src.gateway.handlers.mcp_handler:MCPHandler.list_servers", "read", False),
    ("POST", "/api/mcp/servers/{name}/toggle", "mod:src.gateway.handlers.mcp_handler:MCPHandler.toggle_server", "write", False),
    ("POST", "/api/mcp/servers/{name}/sync", "mod:src.gateway.handlers.mcp_handler:MCPHandler.sync_server", "write", False),
    ("POST", "/api/mcp/servers/{name}/binding", "mod:src.gateway.handlers.mcp_handler:MCPHandler.bind_server", "write", False),
    ("GET", "/api/agents/{agent_id}/mcp", "mod:src.gateway.handlers.mcp_handler:MCPHandler.get_agent_mcp", "read", False),
    ("POST", "/api/agents/{agent_id}/mcp", "mod:src.gateway.handlers.mcp_handler:MCPHandler.set_agent_mcp", "write", False),
    ("PUT", "/api/agents/{agent_id}/mcp", "gw:_handle_save_agent_mcp", "write", False),
    ("GET", "/mcp-admin", "mod:src.gateway.handlers.mcp_handler:MCPHandler.admin_page", "read", False),
    ("POST", "/api/mcp/servers", "mod:src.gateway.handlers.mcp_handler:MCPHandler.add_server", "write", False),
    ("DELETE", "/api/mcp/servers/{name}", "mod:src.gateway.handlers.mcp_handler:MCPHandler.delete_server", "write", False),
    ("POST", "/api/mcp/servers/test", "mod:src.gateway.handlers.mcp_handler:MCPHandler.test_server", "write", False),
    ("GET", "/api/models", "mod:src.gateway.handlers.model_handler:ModelHandler.list_models", "read", False),
    ("GET", "/api/models/current", "mod:src.gateway.handlers.model_handler:ModelHandler.get_current", "read", False),
    ("POST", "/api/models/switch", "mod:src.gateway.handlers.model_handler:ModelHandler.switch", "write", False),
    ("POST", "/api/models", "mod:src.gateway.handlers.model_handler:ModelHandler.create", "write", False),
    ("PUT", "/api/models/{config_name}", "mod:src.gateway.handlers.model_handler:ModelHandler.update", "write", False),
    ("DELETE", "/api/models/{config_name}", "mod:src.gateway.handlers.model_handler:ModelHandler.delete", "write", False),
    ("POST", "/api/models/{config_name}/toggle", "mod:src.gateway.handlers.model_handler:ModelHandler.toggle", "write", False),
    ("POST", "/api/models/{config_name}/discover", "mod:src.gateway.handlers.model_handler:ModelHandler.discover", "write", False),
    ("GET", "/api/fallback/status", "mod:src.gateway.handlers.fallback_handler:FallbackHandler.status", "read", False),
    ("GET", "/api/memory/stats", "mod:src.gateway.handlers.memory_handler:MemoryHandler.stats", "read", False),
    ("GET", "/api/memory/recent", "mod:src.gateway.handlers.memory_handler:MemoryHandler.recent", "read", False),
    ("GET", "/api/memory/search", "mod:src.gateway.handlers.memory_handler:MemoryHandler.search", "read", False),
    ("GET", "/api/memory/files", "mod:src.gateway.handlers.memory_handler:MemoryHandler.files", "read", False),
    ("GET", "/api/memory/storage", "mod:src.gateway.handlers.memory_handler:MemoryHandler.storage", "read", False),
    ("GET", "/api/memory/index_health", "mod:src.gateway.handlers.memory_handler:MemoryHandler.index_health", "read", False),
    ("GET", "/api/memory/agents/{agent_id}", "mod:src.gateway.handlers.memory_handler:MemoryHandler.agent_memory", "read", False),
    ("GET", "/api/memory/agents", "mod:src.gateway.handlers.memory_handler:MemoryHandler.agent_memory_summary", "read", False),
    ("GET", "/api/memory/users", "mod:src.gateway.handlers.memory_handler:MemoryHandler.user_memories", "read", False),
    ("POST", "/api/memory/users/{user_id}", "mod:src.gateway.handlers.memory_handler:MemoryHandler.user_memories_create", "write", False),
    ("PUT", "/api/memory/users/{user_id}/{mem_id}", "mod:src.gateway.handlers.memory_handler:MemoryHandler.user_memories_update", "write", False),
    ("DELETE", "/api/memory/users/{user_id}/{mem_id}", "mod:src.gateway.handlers.memory_handler:MemoryHandler.user_memories_delete", "write", False),
    ("GET", "/api/files/{file_id}/download", "mod:src.gateway.handlers.file_handler:FileHandler.download", "read", False),
    ("GET", "/api/files", "mod:src.gateway.handlers.file_handler:FileHandler.list_files", "read", False),
    ("POST", "/api/files", "mod:src.gateway.handlers.file_handler:FileHandler.upload", "write", False),
    ("DELETE", "/api/files/{file_id}", "mod:src.gateway.handlers.file_handler:FileHandler.delete", "write", False),
    ("GET", "/api/stats/daily", "mod:src.gateway.handlers.stats_handler:StatsHandler.daily", "read", False),
    ("GET", "/api/stats/mcp", "mod:src.gateway.handlers.stats_handler:StatsHandler.mcp", "read", False),
    ("GET", "/api/stats/tokens", "mod:src.gateway.handlers.stats_handler:StatsHandler.tokens", "read", False),
    ("GET", "/api/stats/trend", "mod:src.gateway.handlers.stats_handler:StatsHandler.trend", "read", False),
    ("GET", "/api/stats/overview", "mod:src.gateway.handlers.stats_handler:StatsHandler.overview", "read", False),
    ("POST", "/api/images/generate", "mod:src.gateway.handlers.image_handler:ImageHandler.generate", "write", False),
    ("GET", "/api/images/providers", "mod:src.gateway.handlers.image_handler:ImageHandler.list_providers", "read", False),
    ("GET", "/api/images", "mod:src.gateway.handlers.image_handler:ImageHandler.list_images", "read", False),
    ("GET", "/api/images/gallery", "mod:src.gateway.handlers.image_handler:ImageHandler.gallery", "read", False),
    ("GET", "/api/images/{image_id}", "mod:src.gateway.handlers.image_handler:ImageHandler.get_image", "read", False),
    ("DELETE", "/api/images/{image_id}", "mod:src.gateway.handlers.image_handler:ImageHandler.delete_image", "write", False),
    ("GET", "/api/events/search", "mod:src.gateway.handlers.events_handler:EventsHandler.search", "read", False),
    ("GET", "/api/events/recent", "mod:src.gateway.handlers.events_handler:EventsHandler.recent", "read", False),
    ("GET", "/api/events/stats", "mod:src.gateway.handlers.events_handler:EventsHandler.stats", "read", False),
    ("POST", "/api/events/add", "mod:src.gateway.handlers.events_handler:EventsHandler.add", "write", False),
    ("GET", "/api/plan/current", "mod:src.gateway.handlers.plan_handler:PlanHandler.get_current", "read", False),
    ("GET", "/api/plan/list", "mod:src.gateway.handlers.plan_handler:PlanHandler.get_list", "read", False),
    ("POST", "/api/plan/next", "mod:src.gateway.handlers.plan_handler:PlanHandler.next_step", "write", False),
    ("POST", "/api/plan/skip", "mod:src.gateway.handlers.plan_handler:PlanHandler.skip", "write", False),
    ("POST", "/api/plan/cancel", "mod:src.gateway.handlers.plan_handler:PlanHandler.cancel", "write", False),
    ("GET", "/api/reflections", "mod:src.gateway.handlers.reflection_handler:ReflectionHandler.list_reflections", "read", False),
    ("GET", "/api/reflections/{reflection_id}", "mod:src.gateway.handlers.reflection_handler:ReflectionHandler.get_reflection", "read", False),
    ("POST", "/api/reflections/{reflection_id}/implement", "mod:src.gateway.handlers.reflection_handler:ReflectionHandler.implement_improvements", "write", False),
]

#: 独立路由提供方（(provider 名, 去重, 写方法按 write 保护) 由 register_providers 处理）
#:   plan_router：与 PlanHandler 互补的 3 条 plan 路由；
PROVIDERS: Tuple[str, ...] = ("plan_router",)


def resolve_handler(ref: str, gateway: Any = None) -> Callable:
    """解析 handler 引用为可调用对象。

    :param ref: "gw:xxx" 或 "mod:模块:类.方法"
    :param gateway: GatewayV2GRPC 实例（解析 gw: 前缀时必需）
    """
    if ref.startswith("gw:"):
        if gateway is None:
            raise ValueError(f"解析 {ref} 需要 gateway 实例")
        return getattr(gateway, ref[3:])
    if ref.startswith("mod:"):
        mod_path, attr_path = ref[4:].split(":", 1)
        obj: Any = importlib.import_module(mod_path)
        for part in attr_path.split("."):
            obj = getattr(obj, part)
        return obj
    raise ValueError(f"非法 handler 引用: {ref}")


def iter_provider_routes(name: str) -> Dict[str, Callable]:
    """返回提供方的 {\"METHOD /path\": handler} 映射。"""
    if name == "plan_router":
        from src.gateway.plan_router import get_plan_routes
        return get_plan_routes()
    if name == "task":
        from src.task.api_routes import get_task_routes
        return get_task_routes()
    raise ValueError(f"未知路由提供方: {name}")

