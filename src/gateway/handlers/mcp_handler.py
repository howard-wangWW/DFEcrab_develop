"""
MCP 服务管理处理器

处理 MCP 服务列表/启停/同步 + Agent 级 MCP 勾选的 HTTP 请求
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# MCP 服务名称校验：小写字母开头，允许小写字母、数字、下划线、连字符
_SERVER_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_-]*$')


class MCPHandler:
    """MCP 服务管理处理器"""

    # ---------- 工具函数（模块内私有） ----------

    @staticmethod
    def _project_root() -> Path:
        # 文件位于 DFEcrab/src/gateway/handlers/mcp_handler.py → 4 级 parent = DFEcrab
        return Path(__file__).resolve().parent.parent.parent.parent

    @staticmethod
    def _registry_snapshot() -> Dict[str, int]:
        from src.skill.registry import get_tool_registry
        r = get_tool_registry()
        return {"local_tools": len(r.local_tool_names), "mcp_tools": len(r.mcp_tool_names)}

    @staticmethod
    def _clean_agents_after_delete(server_name: str, removed_tool_names) -> list:
        """清理 agent tools.json 中已废弃的 per-agent MCP 字段。

        MCP 绑定已集中到服务配置（bound_agents），agent 侧不再读取
        enabled_mcp_servers / mcp_tools_whitelist；删除服务后顺带清理这些死字段。
        返回被清理的 agent_id 列表。
        """
        cleaned = []
        agents_dir = MCPHandler._project_root() / "agents"
        if not agents_dir.exists():
            return cleaned
        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            tools_path = agent_dir / "tools.json"
            if not tools_path.exists():
                continue
            try:
                data = json.loads(tools_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            changed = False
            # 剔除已删服务名的残留引用
            servers = data.get("enabled_mcp_servers")
            if isinstance(servers, list) and server_name in servers:
                data["enabled_mcp_servers"] = [x for x in servers if x != server_name]
                changed = True
            wl = data.get("mcp_tools_whitelist")
            if removed_tool_names and isinstance(wl, list):
                new_wl = [x for x in wl if x not in removed_tool_names]
                if len(new_wl) != len(wl):
                    data["mcp_tools_whitelist"] = new_wl
                    changed = True
            # 死字段若已空则整体移除
            for f in ("enabled_mcp_servers", "mcp_tools_whitelist"):
                if f in data and not data[f]:
                    del data[f]
                    changed = True
            if changed:
                tools_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                cleaned.append(agent_dir.name)
        return cleaned

    @staticmethod
    def _ping_server(name: str) -> Dict[str, Any]:
        """对单个 MCP 服务器执行 ping，返回 alive/latency_ms（同步，供 to_thread 调用）。

        ★ BUG-5 修复：使用独立短超时(5s)的连接探测，避免默认 30s 超时拖慢列表页。
        """
        from src.mcp import get_mcp_client
        client = get_mcp_client()
        try:
            # 用独立短超时的 HTTP client 探测，不动共享连接缓存，避免相互阻塞
            from src.mcp.http_client import MCPHTTPClient
            server_cfg = client._get_server_config(name)
            if not server_cfg:
                return {"alive": False, "latency_ms": None, "error": f"服务不存在: {name}"}
            url = server_cfg.get("baseUrl") or server_cfg.get("url")
            transport = server_cfg.get("transport", "streamable_http")
            headers = server_cfg.get("headers", {})
            probe = MCPHTTPClient(base_url=url, transport=transport, headers=headers, timeout=5.0)
            t0 = time.time()
            alive = probe.ping()
            latency_ms = int((time.time() - t0) * 1000) if alive else None
            return {"alive": alive, "latency_ms": latency_ms}
        except Exception as e:
            return {"alive": False, "latency_ms": None, "error": str(e)}

    # ---------- 端点 ----------

    @staticmethod
    async def admin_page(request: Optional[Any] = None):
        """GET /mcp-admin - MCP 管理页（单文件 HTML，请求时读盘，可热改）"""
        from src.gateway.http.server import HTTPResponse
        html_path = Path(__file__).resolve().parent.parent / "static" / "mcp_admin.html"
        try:
            html = html_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return HTTPResponse(500).text(f"管理页文件缺失: {html_path}")
        resp = HTTPResponse(200).text(html)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    @staticmethod
    async def list_servers(request: Optional[Any] = None) -> Dict[str, Any]:
        """GET /api/mcp/servers[?check=true] — 服务列表（token 脱敏）"""
        try:
            from src.mcp import get_mcp_client
            client = get_mcp_client()

            do_check = False
            if request is not None and getattr(request, "query_params", None):
                do_check = request.query_params.get("check") == "true"

            servers = []
            for s in client.list_servers(redact_secrets=True):
                item = {
                    "name": s["name"],
                    "url": s.get("url", ""),
                    "transport": s.get("transport", "streamable_http"),
                    "enabled": s.get("enabled", True),
                    "bound_agents": s.get("bound_agents") or [],
                    "tool_count": len(s.get("tool_cache", [])),
                    "tools": [
                        t.get("function_name") or t.get("name", "")
                        for t in s.get("tool_cache", [])
                    ],
                }
                servers.append(item)

            # ★ BUG-5 修复：并发 ping，总耗时 = 最慢一个，而非逐个累加
            if do_check:
                enabled_names = [s["name"] for s in servers if s.get("enabled", True)]
                if enabled_names:
                    ping_results = await asyncio.gather(*[
                        asyncio.to_thread(MCPHandler._ping_server, n) for n in enabled_names
                    ])
                    result_map = dict(zip(enabled_names, ping_results))
                    for item in servers:
                        if item["name"] in result_map:
                            item.update(result_map[item["name"]])

            return {"success": True, "data": {"total": len(servers), "servers": servers}}
        except Exception as e:
            logger.error(f"列出 MCP 服务失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def toggle_server(request: Any, **kwargs) -> Dict[str, Any]:
        """POST /api/mcp/servers/{name}/toggle — body: {"enabled": bool}"""
        try:
            from src.mcp import get_mcp_client
            from src.skill.registry import get_tool_registry

            name = kwargs.get("name") or request.path_params.get("name")
            body = await request.json()
            enabled = body.get("enabled")

            if not isinstance(enabled, bool):
                return {"success": False, "error": "body 需含布尔字段 enabled"}

            client = get_mcp_client()
            result = client.set_server_enabled(name, enabled)
            if not result.get("success"):
                return result

            # 工具池热刷新（reload 内含 health_check_all，可能自动降级不健康服务）
            await asyncio.to_thread(get_tool_registry().reload)

            # 刷新后重读该服务的最终 enabled 态
            final_enabled = None
            for s in client.list_servers():
                if s["name"] == name:
                    final_enabled = s.get("enabled", True)
                    break

            auto_disabled = final_enabled is not None and final_enabled != enabled

            return {
                "success": True,
                "data": {
                    "server": name,
                    "enabled": final_enabled,
                    "registry": MCPHandler._registry_snapshot(),
                    "auto_disabled": auto_disabled,
                    "note": "工具池已热刷新；enabled 变更立即生效于后续对话",
                },
            }
        except Exception as e:
            logger.error(f"启停 MCP 服务失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def sync_server(request: Any, **kwargs) -> Dict[str, Any]:
        """POST /api/mcp/servers/{name}/sync — 拉取远程工具列表并热刷新"""
        try:
            from src.mcp import get_mcp_client
            from src.skill.registry import get_tool_registry

            name = kwargs.get("name") or request.path_params.get("name")

            client = get_mcp_client()
            r = client.sync_tools(name)
            if not r.get("success"):
                return {"success": False, "error": r.get("error"), "server": name}

            # 该服务器 enabled 时才热刷新（disabled 只回缓存数，不注册）
            is_enabled = False
            for s in client.list_servers():
                if s["name"] == name:
                    is_enabled = s.get("enabled", True)
                    break
            if is_enabled:
                await asyncio.to_thread(get_tool_registry().reload)

            return {
                "success": True,
                "data": {
                    "server": name,
                    "tool_count": r.get("tool_count", 0),
                    "registry": MCPHandler._registry_snapshot(),
                },
            }
        except Exception as e:
            logger.error(f"同步 MCP 服务失败: {e}")
            return {"success": False, "error": str(e)}

    # ---------- 新增/删除/测试 ----------

    @staticmethod
    async def add_server(request: Any) -> Dict[str, Any]:
        """POST /api/mcp/servers - 新增 MCP 服务

        body: {"name": str, "url": str, "transport"?: str, "headers"?: dict, "enabled"?: bool, "auto_sync"?: bool}
        """
        try:
            from src.mcp import get_mcp_client
            from src.skill.registry import get_tool_registry

            body = await request.json()
            name = (body.get("name") or "").strip()
            url = (body.get("url") or "").strip()

            if not name or not url:
                return {"success": False, "error": "name 和 url 为必填项"}

            if not _SERVER_NAME_PATTERN.match(name):
                return {
                    "success": False,
                    "error": "name 只能包含小写字母、数字、下划线和连字符，且以小写字母开头",
                }

            client = get_mcp_client()
            existing = [s["name"] for s in client.list_servers()]
            if name in existing:
                return {"success": False, "error": f"MCP 服务已存在: {name}"}

            transport = body.get("transport") or "streamable_http"
            headers = body.get("headers") or {}
            enabled = body.get("enabled", True)
            auto_sync = body.get("auto_sync", True)
            # 绑定：["alert"] / ["a","b"] / "*"（全局共享），缺省 "*"
            bound_agents = body.get("bound_agents", "*")

            # 提取 token（兼容 add_server 的 token 参数）
            token = None
            auth_header = headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

            # ★ BUG-3 修复：一次写盘，完整保留自定义 headers + enabled + bound_agents
            add_result = client.add_server(
                name=name,
                url=url,
                transport=transport,
                token=token,
                headers=headers,
                enabled=enabled,
                bound_agents=bound_agents,
            )

            result: Dict[str, Any] = {
                "name": name,
                "url": url,
                "transport": transport,
                "enabled": enabled,
                "bound_agents": add_result.get("bound_agents") or [],
                "tool_count": 0,
                "tools": [],
            }

            # 自动同步工具列表
            if auto_sync and enabled:
                try:
                    sync_r = client.sync_tools(name)
                    if sync_r.get("success"):
                        result["tool_count"] = sync_r.get("tool_count", 0)
                        await asyncio.to_thread(get_tool_registry().reload)
                        result["registry"] = MCPHandler._registry_snapshot()
                        for s in client.list_servers():
                            if s["name"] == name:
                                result["tools"] = [
                                    t.get("function_name") or t.get("name", "")
                                    for t in s.get("tool_cache", [])
                                ]
                                break
                    else:
                        result["sync_error"] = sync_r.get("error", "同步失败")
                except Exception as e:
                    result["sync_error"] = str(e)

            logger.info(f"[MCPHandler] 新增服务: {name} ({url})")
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"新增 MCP 服务失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def delete_server(request: Any, **kwargs) -> Dict[str, Any]:
        """DELETE /api/mcp/servers/{name} - 删除 MCP 服务"""
        try:
            from src.mcp import get_mcp_client
            from src.skill.registry import get_tool_registry

            name = kwargs.get("name") or request.path_params.get("name")

            client = get_mcp_client()
            existing = [s["name"] for s in client.list_servers()]
            if name not in existing:
                return {"success": False, "error": f"MCP 服务不存在: {name}"}

            # ★ BUG-2 修复：删除前先取该服务的工具名，供清理 agent 白名单引用
            removed_tool_names = set()
            for s in client.list_servers():
                if s["name"] == name:
                    removed_tool_names = {
                        t.get("function_name") or t.get("name", "")
                        for t in s.get("tool_cache", [])
                    }
                    break

            client.remove_server(name)
            await asyncio.to_thread(get_tool_registry().reload)

            # ★ BUG-2 修复：联动清理所有 agent 对已删服务的悬空引用
            cleaned_agents = MCPHandler._clean_agents_after_delete(name, removed_tool_names)

            logger.info(f"[MCPHandler] 删除服务: {name} (清理 agent 引用: {cleaned_agents})")
            return {
                "success": True,
                "data": {
                    "server": name,
                    "registry": MCPHandler._registry_snapshot(),
                    "cleaned_agents": cleaned_agents,
                },
            }
        except Exception as e:
            logger.error(f"删除 MCP 服务失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def test_server(request: Any) -> Dict[str, Any]:
        """POST /api/mcp/servers/test - 测试 MCP 服务连通性（不写盘）

        body: {"url": str, "transport"?: str, "headers"?: dict}
        """
        try:
            from src.mcp.http_client import MCPHTTPClient

            body = await request.json()
            url = (body.get("url") or "").strip()
            if not url:
                return {"success": False, "error": "url 为必填项"}

            transport = body.get("transport") or "streamable_http"
            headers = body.get("headers") or {}

            def _do_test() -> Dict[str, Any]:
                t0 = time.time()
                client = MCPHTTPClient(
                    base_url=url, transport=transport, headers=headers, timeout=10.0
                )
                alive = client.ping()
                latency_ms = int((time.time() - t0) * 1000) if alive else None

                tools = []
                if alive:
                    try:
                        raw_tools = client.list_tools()
                        tools = [
                            {
                                "name": t.get("name", ""),
                                "description": (t.get("description") or "")[:100],
                            }
                            for t in raw_tools
                        ]
                    except Exception as e:
                        logger.debug(f"test_server list_tools 失败: {e}")

                client.close()
                return {"alive": alive, "latency_ms": latency_ms, "tools": tools}

            result = await asyncio.to_thread(_do_test)

            return {
                "success": True,
                "data": {
                    "url": url,
                    "transport": transport,
                    "alive": result["alive"],
                    "latency_ms": result["latency_ms"],
                    "tool_count": len(result["tools"]),
                    "tools": result["tools"],
                },
            }
        except Exception as e:
            logger.error(f"测试 MCP 服务连通性失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_agent_mcp(request: Any, **kwargs) -> Dict[str, Any]:
        """GET /api/agents/{agent_id}/mcp — 只读视图：该 agent 绑定的 MCP 服务（由服务配置派生）"""
        try:
            from src.mcp import get_mcp_client

            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")

            # 存在性校验
            cfg_file = MCPHandler._project_root() / "agents" / agent_id / "config.json"
            if not cfg_file.exists():
                return {"success": False, "error": f"Agent 不存在: {agent_id}"}

            client = get_mcp_client()
            bound = sorted(client.get_bound_server_names(agent_id))

            available_servers = []
            for s in client.list_servers(redact_secrets=True):
                available_servers.append({
                    "name": s["name"],
                    "enabled": s.get("enabled", True),
                    "tool_count": len(s.get("tool_cache", [])),
                    "bound_agents": s.get("bound_agents") or [],
                })

            return {
                "success": True,
                "data": {
                    "agent_id": agent_id,
                    "enabled_mcp_servers": bound,
                    "mcp_tools_whitelist": None,
                    "available_servers": available_servers,
                },
            }
        except Exception as e:
            logger.error(f"查询 Agent MCP 配置失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def set_agent_mcp(request: Any, **kwargs) -> Dict[str, Any]:
        """POST /api/agents/{agent_id}/mcp — 已废弃。

        绑定编辑已收敛到智能体侧：MCP 服务管理页不再承担绑定操作，
        此处保留端点并返回迁移提示，避免旧调用方 404。
        """
        return {
            "success": False,
            "error": "POST /api/agents/{agent_id}/mcp 已废弃：绑定编辑已收敛到智能体配置页，"
                     "请改用 PUT /api/agents/{agent_id}/mcp（body: {\"mcp_servers\": [\"kdocs\", ...]}, 空数组=清空绑定）",
        }

    @staticmethod
    async def save_agent_mcp(request: Any, **kwargs) -> Dict[str, Any]:
        """PUT /api/agents/{agent_id}/mcp — 以智能体为中心全量保存绑定。

        body: {"mcp_servers": ["kdocs", "blackxml_topology"]}  空数组/缺省 = 清空该智能体显式绑定。

        行为：
          - 一次 diff 收敛所有服务对该智能体的 bound_agents（单次写盘），再热刷新工具池；
          - 校验：服务必须存在；受 mcp.reserved_bindings 保护的保留服务只允许绑给指定智能体
            （缺省配置保护 alert_judge_tools → 仅 alert_judge，防误触发专属研判链路）；
          - disabled 服务允许绑定（绑定是元数据，启停是全局开关），响应 warnings 提示。
        """
        try:
            from src.mcp import get_mcp_client
            from src.skill.registry import get_tool_registry

            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")
            cfg_file = MCPHandler._project_root() / "agents" / agent_id / "config.json"
            if not cfg_file.exists():
                return {"success": False, "error": f"Agent 不存在: {agent_id}"}

            body = await request.json()
            if not isinstance(body, dict):
                return {"success": False, "error": "请求体必须是 JSON 对象"}
            servers_raw = body.get("mcp_servers", [])
            if isinstance(servers_raw, str):
                servers_raw = [servers_raw]
            if not isinstance(servers_raw, list) or not all(
                isinstance(s, str) and s for s in servers_raw
            ):
                return {"success": False, "error": "mcp_servers 必须是服务名字符串或字符串数组"}
            mcp_servers = [s.strip() for s in servers_raw if s.strip()]

            # 保留绑定校验（读 dfecrab.json → mcp.reserved_bindings；未配置则跳过）
            reserved = {}
            try:
                from src.config.app_config import section
                reserved = (section("mcp") or {}).get("reserved_bindings") or {}
            except Exception:
                reserved = {}
            for s in mcp_servers:
                allow = reserved.get(s)
                if allow and agent_id not in allow:
                    return {
                        "success": False,
                        "error": f"MCP 服务 [{s}] 是保留绑定（仅限 {', '.join(allow)}），不能绑到智能体 [{agent_id}]",
                    }

            client = get_mcp_client()
            r = client.set_agent_bindings(agent_id, mcp_servers)
            if not r.get("success"):
                return {"success": False, "error": r.get("error", "保存绑定失败")}

            await asyncio.to_thread(get_tool_registry().reload)

            warnings = []
            if r.get("disabled"):
                warnings.append(
                    f"已绑定但服务当前未启用（启用后生效）: {', '.join(r['disabled'])}"
                )

            return {
                "success": True,
                "data": {
                    "agent_id": agent_id,
                    "mcp_servers": sorted(client.get_bound_server_names(agent_id)),
                    "changed": {"added": r.get("added", []), "removed": r.get("removed", [])},
                    "warnings": warnings,
                    "registry": MCPHandler._registry_snapshot(),
                },
            }
        except Exception as e:
            logger.error(f"保存 Agent MCP 绑定失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def bind_server(request: Any, **kwargs) -> Dict[str, Any]:
        """POST /api/mcp/servers/{name}/binding — body: {"bound_agents": ["alert"] | "*"}

        设置该 MCP 服务绑定到哪些 agent（单一事实源），立即热刷新工具池。
        """
        try:
            from src.mcp import get_mcp_client
            from src.skill.registry import get_tool_registry

            name = kwargs.get("name") or request.path_params.get("name")
            body = await request.json()
            bound = body.get("bound_agents")

            if bound == "*":
                pass
            elif isinstance(bound, list) and all(isinstance(x, str) and x != "*" for x in bound):
                pass
            else:
                return {
                    "success": False,
                    "error": "bound_agents 必须是字符串数组或 '*'",
                }

            client = get_mcp_client()
            r = client.set_server_binding(name, bound)
            if not r.get("success"):
                return r

            await asyncio.to_thread(get_tool_registry().reload)
            logger.info(f"[MCPHandler] 更新服务 {name} 绑定: {r['bound_agents']}")
            return {
                "success": True,
                "data": {"server": name, "bound_agents": r["bound_agents"]},
            }
        except Exception as e:
            logger.error(f"设置 MCP 服务绑定失败: {e}")
            return {"success": False, "error": str(e)}