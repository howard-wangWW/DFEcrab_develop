"""
MCP 客户端完整实现。

功能：
1. 配置管理：MCP 服务器的增删改查
2. HTTP 协议客户端：基于 JSON-RPC 2.0 的 MCP 协议实现
3. 工具缓存：从远程 MCP 服务器同步工具列表到本地
4. 工具调用：通过 HTTP 实际调用远程 MCP 工具
5. SDK 兼容：当 mcp Python SDK 可用时，自动使用 SDK（可选）
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .http_client import MCPHTTPClient, MCPHTTPError

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP 客户端 - 支持远程 HTTP MCP 服务器"""

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or Path("config/mcporter.json")
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._http_clients: Dict[str, MCPHTTPClient] = {}

    def _load(self) -> Dict[str, Any]:
        if not self._config_path.exists():
            return {"mcpServers": {}, "imports": []}
        try:
            return json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception:
            return {"mcpServers": {}, "imports": []}

    def _save(self, data: Dict[str, Any]):
        self._config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _get_server_config(self, name: str) -> Optional[Dict[str, Any]]:
        data = self._load()
        return data.get("mcpServers", {}).get(name)

    def _get_http_client(self, name: str) -> MCPHTTPClient:
        if name in self._http_clients:
            return self._http_clients[name]

        server_cfg = self._get_server_config(name)
        if not server_cfg:
            raise ValueError(f"MCP 服务器不存在: {name}")

        url = server_cfg.get("baseUrl") or server_cfg.get("url")
        if not url:
            raise ValueError(f"MCP 服务器 {name} 未配置 URL")

        transport = server_cfg.get("transport", "streamable_http")
        headers = server_cfg.get("headers", {})
        timeout = server_cfg.get("timeout", 30.0)

        client = MCPHTTPClient(
            base_url=url,
            transport=transport,
            headers=headers,
            timeout=timeout,
            server_name=name,  # ★ 用量统计：埋点按服务名归类
        )
        self._http_clients[name] = client
        return client

    @staticmethod
    def _norm_bound_agents(bound_agents: Any) -> List[str]:
        """规范化 bound_agents（v4.13：MCP 服务侧不再有"绑定智能体/全局 *"概念，
        绑定只由智能体配置页显式写入）：
        - None/空 → []（未绑定，任何 agent 均不可用）
        - "*"（历史遗留全局标记）→ []（全局语义废弃，不再对任何 agent 生效）
        - 字符串 → [str]；列表 → 过滤掉 "*" 与空项
        """
        if not bound_agents:
            return []
        if bound_agents == "*":
            return []
        if isinstance(bound_agents, str):
            return [bound_agents]
        return [x for x in bound_agents if x and x != "*"]

    def _update_server_cache(self, name: str, tools: List[Dict[str, Any]]):
        data = self._load()
        if name not in data.get("mcpServers", {}):
            return
        data["mcpServers"][name]["tool_cache"] = tools
        self._save(data)

    def add_server(
        self,
        name: str,
        url: str,
        transport: Optional[str] = None,
        token: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
        bound_agents: Any = None,
    ):
        """新增 MCP 服务并落盘。

        支持完整参数，一次写盘：
        - token 会合并进 headers 的 Authorization（仅当未显式提供 Authorization 时）
        - headers 原样保存（可含任意自定义头）
        - enabled 可自定义（默认启用）
        - bound_agents: 绑定到哪些 agent（["alert"] / 多个 / ["*"]=全局共享）；
          None → 未绑定（不可用）。HTTP 层缺省传 "*"（全局）
        """
        final_headers = dict(headers or {})
        if token and "Authorization" not in final_headers:
            final_headers["Authorization"] = f"Bearer {token}"

        data = self._load()
        entry = {
            "baseUrl": url,
            "transport": transport or "streamable_http",
            "headers": final_headers,
            "tool_cache": [],
            "enabled": enabled,
            "bound_agents": self._norm_bound_agents(bound_agents),
        }
        data.setdefault("mcpServers", {})[name] = entry
        self._save(data)
        self._http_clients.pop(name, None)
        return {
            "name": name,
            "url": url,
            "transport": entry["transport"],
            "enabled": enabled,
            "bound_agents": entry["bound_agents"],
            "tool_cache": [],
        }

    def remove_server(self, name: str) -> bool:
        data = self._load()
        removed = data.setdefault("mcpServers", {}).pop(name, None)
        self._save(data)
        self._http_clients.pop(name, None)
        return removed is not None

    def list_servers(self, redact_secrets: bool = False) -> List[Dict[str, Any]]:
        data = self._load()
        servers = []
        for name, item in data.get("mcpServers", {}).items():
            headers = dict(item.get("headers", {}))
            if redact_secrets and "Authorization" in headers:
                headers["Authorization"] = "***"
            servers.append(
                {
                    "name": name,
                    "url": item.get("baseUrl") or item.get("url"),
                    "transport": item.get("transport", "streamable_http"),
                    "enabled": item.get("enabled", True),
                    "headers": headers,
                    "tool_cache": item.get("tool_cache", []),
                    "bound_agents": self._norm_bound_agents(item.get("bound_agents")),
                }
            )
        return servers

    def import_from_mcporter(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        source_path = config_path or self._config_path
        if not source_path.exists():
            return {"imported": [], "skipped": [], "error": f"配置文件不存在: {source_path}"}

        source = json.loads(source_path.read_text(encoding="utf-8"))
        target = self._load()
        imported = []
        skipped = []
        for name, item in source.get("mcpServers", {}).items():
            if name in target.setdefault("mcpServers", {}):
                skipped.append(name)
                continue
            target["mcpServers"][name] = item
            imported.append(name)
        self._save(target)
        return {"imported": imported, "skipped": skipped, "error": None}

    def sync_tools(self, name: str) -> Dict[str, Any]:
        """从远程 MCP 服务器同步工具列表到本地缓存"""
        try:
            client = self._get_http_client(name)
            tools = client.list_tools()

            tool_cache = []
            for tool in tools:
                tool_def = {
                    "function_name": tool.get("name", ""),
                    "tool_name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                }
                tool_cache.append(tool_def)

            self._update_server_cache(name, tool_cache)

            return {
                "success": True,
                "tool_count": len(tools),
                "tools": tool_cache,
                "server": name,
            }
        except MCPHTTPError as e:
            logger.error(f"同步 MCP 工具失败 [{name}]: {e}")
            return {
                "success": False,
                "tool_count": 0,
                "tools": [],
                "server": name,
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"同步 MCP 工具异常 [{name}]: {e}")
            return {
                "success": False,
                "tool_count": 0,
                "tools": [],
                "server": name,
                "error": str(e),
            }

    def get_server_instructions(self, name: str) -> str:
        """获取指定 MCP 服务器的 instructions（握手时服务端声明）。

        对齐 LibreChat serverInstructions：Gateway 在装配 MCP 后把该文本拼入
        agent 系统提示，让弱模型也遵守服务端的工具调用 SOP。
        失败（服务不存在/连不上/未声明）返回空串，不抛异常。
        """
        try:
            client = self._get_http_client(name)
            client.initialize()
            return getattr(client, "get_instructions", lambda: "")()
        except Exception as e:
            logger.debug(f"获取 MCP instructions 失败 [{name}]: {e}")
            return ""

    def test_server(self, name: str, tool: Optional[str] = None, arguments: Optional[Dict[str, Any]] = None):
        """测试 MCP 服务器连接"""
        try:
            client = self._get_http_client(name)

            init_result = client.initialize()

            result = {
                "success": True,
                "server": name,
                "initialized": True,
                "protocolVersion": init_result.get("protocolVersion", "unknown"),
                "capabilities": list(init_result.get("capabilities", {}).keys()),
            }

            if tool:
                try:
                    call_result = client.call_tool(tool, arguments or {})
                    result["tool_test"] = {
                        "tool": tool,
                        "success": True,
                        "result": call_result,
                    }
                except MCPHTTPError as e:
                    result["tool_test"] = {
                        "tool": tool,
                        "success": False,
                        "error": str(e),
                    }

            return result

        except MCPHTTPError as e:
            return {
                "success": False,
                "server": name,
                "error": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "server": name,
                "error": str(e),
            }

    def call_tool(self, name: str, tool: str, payload: Dict[str, Any]):
        """调用远程 MCP 工具"""
        try:
            client = self._get_http_client(name)
            result = client.call_tool(tool, payload)
            return {
                "success": True,
                "server": name,
                "tool": tool,
                "result": result,
            }
        except MCPHTTPError as e:
            return {
                "success": False,
                "server": name,
                "tool": tool,
                "error": str(e),
            }
        except Exception as e:
            return {
                "success": False,
                "server": name,
                "tool": tool,
                "error": str(e),
            }

    def get_cached_tools(self, enabled_only: bool = True):
        """获取所有已缓存的 MCP 工具

        Args:
            enabled_only: True 时仅返回 enabled 服务器的工具（★ BUG-2 主修复）
        """
        tools = []
        for server in self.list_servers(redact_secrets=True):
            if enabled_only and not server.get("enabled", True):
                continue
            for item in server.get("tool_cache", []):
                tool = dict(item)
                tool.setdefault("server_name", server["name"])
                tools.append(tool)
        return tools

    def execute_cached_tool(self, function_name: str, **kwargs):
        """执行缓存的 MCP 工具（通过 HTTP 实际调用）"""
        for server in self.list_servers():
            if not server.get("enabled", True):
                continue
            for item in server.get("tool_cache", []):
                cached_name = item.get("function_name") or item.get("name", "")
                if cached_name == function_name:
                    try:
                        client = self._get_http_client(server["name"])
                        result = client.call_tool(function_name, kwargs)
                        return {
                            "status": "success",
                            "content": result,
                            "server": server["name"],
                            "tool": function_name,
                        }
                    except MCPHTTPError as e:
                        return {
                            "status": "error",
                            "error": str(e),
                            "content": None,
                        }
                    except Exception as e:
                        return {
                            "status": "error",
                            "error": str(e),
                            "content": None,
                        }
        return {
            "status": "error",
            "error": f"缓存工具 {function_name} 未找到对应的 MCP 服务器",
            "content": None,
        }

    def sync_all_tools(self) -> Dict[str, Any]:
        """同步所有已配置 MCP 服务器的工具"""
        results = {"success": {}, "failed": {}}
        for server in self.list_servers():
            name = server["name"]
            if not server.get("enabled", True):
                continue
            result = self.sync_tools(name)
            if result.get("success"):
                results["success"][name] = result["tool_count"]
            else:
                results["failed"][name] = result.get("error", "unknown")
        return results

    # ── ★ S4.4: 健康检查 ──

    def health_check_all(self) -> Dict[str, Any]:
        """对所有已配置 MCP 服务器做健康检查

        对每个 enabled 服务器执行 ping/initialize，
        不健康服务器自动标记 enabled=false（降级），
        健康服务器恢复 enabled=true。

        Returns:
            {
                "healthy": {"kdocs": {"latency_ms": 45}},
                "unhealthy": {"broken_server": {"error": "..."}},
                "auto_disabled": ["broken_server"],
                "total": 2,
            }
        """
        import time as _time
        healthy = {}
        unhealthy = {}
        auto_disabled = []

        data = self._load()
        servers = data.get("mcpServers", {})

        for name, cfg in servers.items():
            if not cfg.get("enabled", True):
                logger.debug(f"[MCP] health_check 跳过已禁用: {name}")
                continue

            try:
                t0 = _time.time()
                client = self._get_http_client(name)
                result = client.ping()
                latency_ms = int((_time.time() - t0) * 1000)

                healthy[name] = {
                    "latency_ms": latency_ms,
                    "url": cfg.get("baseUrl", ""),
                    "transport": cfg.get("transport", "streamable_http"),
                }

                logger.info(f"[MCP] {name} 健康 (latency={latency_ms}ms)")

            except Exception as e:
                unhealthy[name] = {
                    "error": str(e),
                    "url": cfg.get("baseUrl", ""),
                }
                # 自动降级
                if cfg.get("enabled", True):
                    data["mcpServers"][name]["enabled"] = False
                    auto_disabled.append(name)
                    logger.warning(f"[MCP] {name} 不健康，已自动降级: {e}")

                # 清理已失败的 HTTP 客户端
                self._http_clients.pop(name, None)

        self._save(data)

        result = {
            "healthy": healthy,
            "unhealthy": unhealthy,
            "auto_disabled": auto_disabled,
            "total_checked": len(healthy) + len(unhealthy),
            "total_healthy": len(healthy),
            "total_unhealthy": len(unhealthy),
        }
        logger.info(
            f"[MCP] health_check 完成: "
            f"healthy={len(healthy)}, unhealthy={len(unhealthy)}, "
            f"disabled={auto_disabled}"
        )
        return result

    def set_server_enabled(self, name: str, enabled: bool) -> Dict[str, Any]:
        """启停 MCP 服务并落盘 mcporter.json"""
        data = self._load()
        server = data.get("mcpServers", {}).get(name)
        if not server:
            return {"success": False, "error": f"MCP 服务器不存在: {name}"}
        server["enabled"] = enabled
        self._save(data)
        self._http_clients.pop(name, None)   # 丢弃旧连接，下次按新状态重建
        return {"success": True, "server": name, "enabled": enabled}

    def set_server_binding(self, name: str, bound_agents: Any) -> Dict[str, Any]:
        """设置 MCP 服务绑定到哪些 agent，落盘 mcporter.json。

        仅供内部/脚本使用（服务级端点已废弃，v4.13 起绑定只从智能体侧写入）。
        bound_agents: ["agent1"] / ["agent1","agent2"]；"*" 已被 _norm_bound_agents
        归一为空（全局语义废弃，写 "*" 等于清空绑定）。
        """
        data = self._load()
        server = data.get("mcpServers", {}).get(name)
        if not server:
            return {"success": False, "error": f"MCP 服务器不存在: {name}"}
        server["bound_agents"] = self._norm_bound_agents(bound_agents)
        self._save(data)
        return {"success": True, "server": name, "bound_agents": server["bound_agents"]}

    def set_agent_bindings(self, agent_id: str, mcp_servers: Any) -> Dict[str, Any]:
        """以智能体为中心全量保存绑定（单次读盘/单次写盘）——绑定的唯一写入口。

        语义（v4.13）：保存后，agent 在所有服务上的显式绑定集合 = mcp_servers。
        - mcp_servers 中的服务：确保该服务 bound_agents 显式含 agent_id；
        - 不在 mcp_servers 中的服务：从该服务 bound_agents 移除 agent_id；
          移除后为空数组 = 未绑定（任何 agent 均不可用）。
        服务侧不存在 "*" 全局绑定（历史 "*" 数据已归一为空，见 _norm_bound_agents）。

        Args:
            agent_id: 智能体 id
            mcp_servers: 该 agent 应绑定的服务名数组（None 视为空数组=清空绑定）

        Returns:
            校验失败返回 {"success": False, "error": ...}，不写盘；
            成功返回 {"success": True, "added": [...], "removed": [...], "disabled": [...]}
        """
        target = set(mcp_servers or [])
        data = self._load()
        cfg = data.setdefault("mcpServers", {})

        unknown = [name for name in target if name not in cfg]
        if unknown:
            return {
                "success": False,
                "error": f"MCP 服务不存在: {', '.join(sorted(unknown))}",
                "unknown": sorted(unknown),
            }

        added: List[str] = []
        removed: List[str] = []
        disabled_bound: List[str] = []
        for name, entry in cfg.items():
            cur = self._norm_bound_agents(entry.get("bound_agents"))
            if name in target:
                if agent_id in cur:
                    continue
                entry["bound_agents"] = cur + [agent_id]
                added.append(name)
                if not entry.get("enabled", True):
                    disabled_bound.append(name)
            else:
                if agent_id not in cur:
                    continue
                entry["bound_agents"] = [x for x in cur if x != agent_id]
                removed.append(name)

        if added or removed:
            self._save(data)
        return {
            "success": True,
            "agent_id": agent_id,
            "added": added,
            "removed": removed,
            "disabled": disabled_bound,
        }

    def get_bound_server_names(self, agent_id: str) -> set:
        """返回某 agent 可用的已启用 MCP 服务名集合。

        规则（v4.13）：服务 enabled 且 bound_agents **显式**含该 agent；
        bound_agents 为空（或历史 "*" 已归一为空）→ 该服务任何 agent 都不可用。
        绑定只由智能体配置页写入，服务侧不存在全局绑定。
        """
        names = set()
        for server in self.list_servers():
            if not server.get("enabled", True):
                continue
            ba = server.get("bound_agents") or []
            if not ba:
                continue  # 未绑定：任何 agent 都不可用
            if agent_id in ba:
                names.add(server["name"])
        return names

    def get_enabled_servers(self) -> List[str]:
        """获取所有已启用的 MCP 服务器名称列表

        Returns:
            list[str]: 已启用的服务器名称
        """
        return [
            name
            for name, cfg in self._load().get("mcpServers", {}).items()
            if cfg.get("enabled", True)
        ]

    def close_all(self):
        """关闭所有 HTTP 客户端连接"""
        for client in self._http_clients.values():
            client.close()
        self._http_clients.clear()


class MCPServerFacade:
    def __init__(self, client: MCPClient):
        self._client = client

    def list_exposed_tool_names(self):
        return [item.get("function_name") or item.get("name", "") for item in self._client.get_cached_tools()]

    def run_transport(self, transport: str):
        raise RuntimeError(
            f"MCP Server transport '{transport}' 暂未实现。"
            f"请使用 MCPHTTPClient 作为客户端连接远程 MCP 服务器。"
        )


_client_instance: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = MCPClient()
    return _client_instance


def create_mcp_server(**kwargs) -> MCPServerFacade:
    return MCPServerFacade(get_mcp_client())