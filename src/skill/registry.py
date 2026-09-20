"""
ToolRegistry - 技能工具注册表

功能：
1. 动态扫描 skills/ 目录下的所有技能
2. 自动加载 execute.py 中的 execute 函数
3. 提取 SKILL_METADATA 或通过函数签名推断工具描述
4. 标准化所有技能的返回值为统一的 ToolResult 格式
5. 提供 list_tools() 方法返回 OpenAI function-calling 兼容的 JSON Schema
"""

import asyncio
import importlib.util
import inspect
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ★ MCP 工具注入上限：超过则整组不注入（fail-safe，防巨型服务撑爆 LLM 请求）
# 内网 14B 模型实测 200+ 工具触发 400 Bad Request → ReAct 空转；对齐 Dify Agent 节点工具上限量级
# ★ 可配置：dfecrab.json 的 mcp.max_tools_per_agent（默认 30）
_MAX_MCP_TOOLS_PER_AGENT = 30
# ★ 写工具过滤（步骤3）：默认不下发写工具。判定为 schema 驱动（零名单）——服务端自我声明
#   required 含 confirm / confirm.enum 含 APPLY / 未来 annotations.destructiveHint 时视为写工具。
#   可配置：dfecrab.json 的 mcp.exclude_write_tools（默认 true）；需要更新类对话时置 false。
_MCP_EXCLUDE_WRITE_TOOLS = True
try:
    # ★ 单点加载：dfecrab.json 统一经 src/config/app_config.py（步骤6 收敛）
    from src.config.app_config import section as _cfg_section
    _mcp_section = _cfg_section("mcp") or {}
    _mcp_limit = int(_mcp_section.get("max_tools_per_agent", 0) or 0)
    if _mcp_limit > 0:
        _MAX_MCP_TOOLS_PER_AGENT = _mcp_limit
    if _mcp_section.get("exclude_write_tools") is not None:
        _MCP_EXCLUDE_WRITE_TOOLS = bool(_mcp_section.get("exclude_write_tools"))
except Exception:
    pass
MAX_MCP_TOOLS_PER_AGENT = _MAX_MCP_TOOLS_PER_AGENT
MCP_EXCLUDE_WRITE_TOOLS = _MCP_EXCLUDE_WRITE_TOOLS


def _is_mcp_write_tool_schema(tool_schema: Dict[str, Any]) -> bool:
    """写工具判定（schema 驱动，零名单、零前缀）。

    仅依据服务端自我声明，新增工具/服务零维护：
      1) MCP annotations：readOnlyHint=true 明确只读 → False；destructiveHint=true → True；
      2) 写保护参数约定：required 含 confirm，或 confirm.enum 含 "APPLY" → True；
      3) 其余默认视为只读/不确定，放行（向后兼容）。
    """
    fn = (tool_schema or {}).get("function") or {}
    params = fn.get("parameters") or {}
    props = params.get("properties") or {}
    required = params.get("required") or []
    # 1) annotations（部分 MCP 服务端声明；当前 ToolInfo 未缓存时此分支不命中）
    if params.get("readOnlyHint") is True:
        return False
    if params.get("destructiveHint") is True:
        return True
    # 2) 写保护参数约定：服务端在 inputSchema 声明 confirm 参数 + APPLY 枚举
    if "confirm" in required:
        return True
    confirm_prop = props.get("confirm") or {}
    enum = confirm_prop.get("enum") or []
    if "APPLY" in enum:
        return True
    return False


@dataclass
class ToolResult:
    """统一的工具执行结果"""
    status: str = "success"  # success, error
    content: Any = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "content": self.content,
            "error": self.error
        }


@dataclass
class ToolInfo:
    """工具注册信息"""
    name: str
    description: str
    parameters: Dict[str, Any]
    execute_fn: Callable
    skill_dir: Path
    source: str = "local"                    # "local"=本地技能 | "mcp"=MCP工具
    server_name: Optional[str] = None        # MCP 服务名（source="mcp" 时）


class ToolRegistry:
    """技能工具注册表"""

    _instance: Optional["ToolRegistry"] = None

    # ★ P0-7/P0-8: 系统功能黑名单 — 不应被 LLM 当作工具调用
    SYSTEM_SKILLS_BLACKLIST = {"planner", "project_memory"}

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._local_tools: Dict[str, ToolInfo] = {}   # 本地 skills/
        self._mcp_tools: Dict[str, ToolInfo] = {}     # MCP 远程工具
        self._project_root = self._find_project_root()
        self._skills_dir = self._project_root / "skills"
        self._discover_tools()

    @property
    def _tools(self) -> Dict[str, ToolInfo]:
        """合并视图（本地+MCP），兼容旧代码只读访问（已核实外部无写入）"""
        merged = dict(self._local_tools)
        merged.update(self._mcp_tools)
        return merged

    @property
    def local_tool_names(self) -> set:
        return set(self._local_tools)

    @property
    def mcp_tool_names(self) -> set:
        return set(self._mcp_tools)

    def _find_project_root(self) -> Path:
        """查找项目根目录（skills 目录所在位置）"""
        current = Path(__file__).resolve().parent
        for parent in [current] + list(current.parents):
            if (parent / "skills").exists():
                return parent
        return current.parent

    def _discover_tools(self) -> None:
        """扫描 skills/ 目录并注册所有技能"""
        if not self._skills_dir.exists():
            logger.warning(f"Skills directory not found: {self._skills_dir}")
            return

        for skill_dir in self._skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith('.'):
                continue
            # ★ P0-7/P0-8: 跳过系统功能（planner/project_memory），不注册为 LLM 工具
            if skill_dir.name in self.SYSTEM_SKILLS_BLACKLIST:
                logger.info(f"Skip system skill (blacklist): {skill_dir.name}")
                continue
            execute_path = skill_dir / "execute.py"
            if not execute_path.exists():
                continue
            try:
                tool_info = self._load_tool(skill_dir, execute_path)
                if tool_info:
                    self._local_tools[tool_info.name] = tool_info
                    logger.info(f"Registered tool: {tool_info.name}")
            except Exception as e:
                logger.error(f"Failed to load skill '{skill_dir.name}': {e}")

        self._discover_mcp_tools()

    def _discover_mcp_tools(self) -> None:
        """从 MCP 配置缓存中注册外部工具，并尝试同步远程工具列表

        ★ S4.4: 启动时自动健康检查 → 不健康服务器跳过 + 自动降级
        """
        try:
            from src.mcp import get_mcp_client

            mcp_client = get_mcp_client()

            # ★ S4.4: 启动时自动健康检查（对已启用服务器 ping 一次）
            try:
                health_result = mcp_client.health_check_all()
                if health_result.get("auto_disabled"):
                    logger.warning(
                        f"[ToolRegistry] MCP 自动降级 {len(health_result['auto_disabled'])} 个服务器: "
                        f"{health_result['auto_disabled']}"
                    )
                logger.info(
                    f"[ToolRegistry] MCP 健康检查完成: "
                    f"healthy={health_result.get('total_healthy')}, "
                    f"unhealthy={health_result.get('total_unhealthy')}"
                )
            except Exception as e:
                logger.debug(f"[ToolRegistry] MCP 健康检查异常（降级继续）: {e}")

            # 尝试同步每个启用的 MCP 服务器工具（3秒超时，失败不影响启动）
            for server in mcp_client.list_servers():
                if not server.get("enabled", True):
                    continue
                server_name = server["name"]
                try:
                    result = mcp_client.sync_tools(server_name)
                    if result.get("success"):
                        logger.info(f"Synced MCP tools from {server_name}: {result.get('tool_count', 0)} tools")
                    else:
                        logger.debug(f"Skip MCP sync for {server_name}: {result.get('error', 'unknown')}")
                except Exception as e:
                    logger.debug(f"MCP sync failed for {server_name}: {e}")

            # 注册所有（同步后的）缓存工具
            # ★ BUG-2 双保险：注册前按 enabled 服务器过滤（主修复在 1.2 get_cached_tools）
            try:
                enabled_servers = set(mcp_client.get_enabled_servers())
            except Exception:
                enabled_servers = set()

            for item in mcp_client.get_cached_tools():
                name = item.get("function_name") or item.get("name", "")
                if not name:
                    continue
                server_name = item.get("server_name", "unknown")
                if enabled_servers and server_name not in enabled_servers:
                    continue
                if name in self._local_tools or name in self._mcp_tools:
                    logger.warning("Skip MCP tool due to name collision: %s", name)
                    continue

                def _make_execute(function_name: str, server_name: str):
                    def _execute(**kwargs):
                        return mcp_client.execute_cached_tool(function_name, **kwargs)
                    _execute.__name__ = f"mcp_{function_name}"
                    return _execute

                tool_info = ToolInfo(
                    name=name,
                    description=item.get("description") or f"MCP tool {server_name}.{name}",
                    parameters=item.get("parameters") or {"type": "object", "properties": {}},
                    execute_fn=_make_execute(name, server_name),
                    skill_dir=self._project_root / "config",
                    source="mcp",
                    server_name=server_name,
                )
                self._mcp_tools[name] = tool_info
                logger.info(f"Registered MCP tool: {name} (from {server_name})")

        except Exception as exc:
            logger.warning(f"Failed to load MCP tools: %s", exc)

    def _load_tool(self, skill_dir: Path, execute_path: Path) -> Optional[ToolInfo]:
        """动态加载单个技能的 execute.py"""
        module_name = f"skills.{skill_dir.name}.execute"

        spec = importlib.util.spec_from_file_location(module_name, execute_path)
        if spec is None or spec.loader is None:
            logger.error(f"Cannot create module spec for {execute_path}")
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error(f"Error loading {execute_path}: {e}")
            return None

        # 获取 execute 函数
        if not hasattr(module, "execute"):
            logger.warning(f"No 'execute' function in {execute_path}")
            return None

        execute_fn = module.execute

        # 提取元数据
        metadata = getattr(module, "SKILL_METADATA", None)
        if metadata:
            name = metadata.get("name", skill_dir.name)
            description = metadata.get("description", "")
            parameters = metadata.get("parameters", {})
        else:
            # 从函数签名推断
            name = skill_dir.name
            description = self._extract_docstring(execute_fn)
            parameters = self._infer_parameters(execute_fn)

        return ToolInfo(
            name=name,
            description=description,
            parameters=parameters,
            execute_fn=execute_fn,
            skill_dir=skill_dir
        )

    def _extract_docstring(self, fn: Callable) -> str:
        """提取函数的 docstring 作为描述"""
        doc = inspect.getdoc(fn) or ""
        # 提取第一行作为简要描述
        if doc:
            return doc.split('\n')[0].strip()
        return f"Skill: {fn.__name__}"

    def _infer_parameters(self, fn: Callable) -> Dict[str, Any]:
        """从函数签名推断参数定义"""
        sig = inspect.signature(fn)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_info = {
                "type": "string",
                "description": f"Parameter: {param_name}"
            }

            # 推断类型
            annotation = param.annotation
            if annotation is not inspect.Parameter.empty:
                type_str = str(annotation).lower()
                if "int" in type_str:
                    param_info["type"] = "integer"
                elif "float" in type_str or "number" in type_str:
                    param_info["type"] = "number"
                elif "bool" in type_str:
                    param_info["type"] = "boolean"
                elif "list" in type_str or "array" in type_str:
                    param_info["type"] = "array"
                elif "dict" in type_str or "object" in type_str:
                    param_info["type"] = "object"

            # 处理默认值
            if param.default is not inspect.Parameter.empty:
                param_info["default"] = param.default
            else:
                required.append(param_name)

            properties[param_name] = param_info

        result = {"type": "object", "properties": properties}
        if required:
            result["required"] = required

        return result

    async def execute_tool(self, tool_name: str, **kwargs) -> ToolResult:
        """执行指定工具并返回标准化结果（支持 async 技能）"""
        tool_info = self._tools.get(tool_name)
        if not tool_info:
            return ToolResult(
                status="error",
                error=f"Tool '{tool_name}' not found. Available: {list(self._tools.keys())}"
            )

        try:
            fn = tool_info.execute_fn
            if asyncio.iscoroutinefunction(fn):
                # async 技能：直接 await，不阻塞事件循环
                raw_result = await fn(**kwargs)
            else:
                # 同步技能：扔线程池执行，避免阻塞 asyncio 事件循环导致所有并发请求卡住
                raw_result = await asyncio.to_thread(fn, **kwargs)
            # 兜底：个别 execute_fn 直接返回协程对象
            if asyncio.iscoroutine(raw_result):
                raw_result = await raw_result
            return self._normalize_result(raw_result)
        except Exception as e:
            # 检测 UserError，保留结构化信息
            from src.core.errors import UserError
            if isinstance(e, UserError):
                error_detail = {
                    "error": e.message,
                    "candidates": e.candidates,
                    "buildHint": e.build_hint,
                }
                return ToolResult(
                    status="error",
                    error=e.message,
                    content=error_detail,
                )
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return ToolResult(
                status="error",
                error=str(e),
                content=f"Tool execution failed: {e}"
            )

    def _normalize_result(self, result: Any) -> ToolResult:
        """将不同格式的返回值标准化为 ToolResult"""
        if isinstance(result, ToolResult):
            return result

        # ServiceResponse 格式 (src.agentscope_compat)
        if hasattr(result, 'status') and hasattr(result, 'content'):
            status_str = "success" if "SUCCESS" in str(result.status) else "error"
            return ToolResult(
                status=status_str,
                content=result.content
            )

        # dict 格式
        if isinstance(result, dict):
            status = result.get("status", "success")
            if isinstance(status, str) and status.lower() in ("success", "error"):
                error_msg = result.get("message") if status == "error" else None
                return ToolResult(
                    status=status,
                    content=result,
                    error=error_msg
                )
            # 其他 dict 直接作为 content
            return ToolResult(status="success", content=result)

        # str 或其他类型
        return ToolResult(status="success", content=result)

    def list_tools(self) -> List[Dict[str, Any]]:
        """返回所有工具的 JSON Schema 列表（兼容 function calling）"""
        tools = []
        for name, info in self._tools.items():
            tool_schema = self._build_tool_schema(name, info)
            tools.append(tool_schema)
        return tools

    def list_tools_for_agent(
        self,
        agent_id: str,
        bound_servers_override: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """按 agent 配置装配工具列表。

        本地技能语义：skills_whitelist=None=全量 / []=无 / 列表=勾选。
        MCP 采用"MCP 为中心"语义：由服务配置里的 bound_agents 决定该 agent 能用哪些服务
        （enabled 服务且绑定含该 agent 或 "*"），不再在 agent 侧重复配置。

        Args:
            agent_id: Agent 唯一标识
            bound_servers_override: 可选，运行时临时覆盖该 agent 可用的 MCP 服务名列表。
                传了则忽略 mcporter.json 里的 bound_agents（不落盘），用于"对话传 mcp 服务名"的场景。

        Returns:
            list[dict]: 过滤后的工具 JSON Schema 列表
        """
        from src.agent.agent_config import AgentConfig

        cfg = AgentConfig.from_id(agent_id)
        skills_wl = cfg.skills_whitelist          # 本地技能白名单

        # ① 本地技能装配（语义不变：None=全量 / []=无 / 列表=勾选）
        if skills_wl is None:
            local_tools = [
                self._build_tool_schema(n, i)
                for n, i in self._local_tools.items()
            ]
        elif not skills_wl:
            local_tools = []
        else:
            local_tools = []
            for n in skills_wl:
                info = self._local_tools.get(n)
                if info:
                    local_tools.append(self._build_tool_schema(n, info))
                else:
                    logger.warning(
                        f"[ToolRegistry] agent={agent_id} skills_whitelist 含未知工具: {n}"
                    )

        # ② MCP 装配：★ 仅显式传参才装配（参考 Claude：MCP 必须显式指定）。
        #   不再从 mcporter.json 的 bound_agents 隐式派生。
        #   bound_servers_override=None（未传 mcp_servers）→ 无 MCP 工具。
        if bound_servers_override is not None:
            bound_servers = set(bound_servers_override)
            logger.info(
                f"[ToolRegistry] agent={agent_id} MCP 服务（显式传参）: {sorted(bound_servers)}"
            )
        else:
            bound_servers = set()  # ★ 移除 get_bound_server_names 隐式派生
            logger.info(f"[ToolRegistry] agent={agent_id} 未传 mcp_servers，不装配 MCP 工具")

        mcp_tools = [
            self._build_tool_schema(n, i)
            for n, i in self._mcp_tools.items()
            if i.server_name in bound_servers
        ]

        # ③-0 ★ 写工具默认不下发（schema 驱动，见 _is_mcp_write_tool_schema；配置 mcp.exclude_write_tools）
        if MCP_EXCLUDE_WRITE_TOOLS:
            _write_names = sorted(
                t.get("function", {}).get("name", "")
                for t in mcp_tools
                if _is_mcp_write_tool_schema(t)
            )
            if _write_names:
                mcp_tools = [
                    t for t in mcp_tools
                    if not _is_mcp_write_tool_schema(t)
                ]
                logger.info(
                    f"[ToolRegistry] agent={agent_id} 已过滤写工具（schema 判定）: {_write_names}"
                )

        # ③ ★ 上限保护（fail-safe）：绑定服务的 MCP 工具总数超上限时整组不注入，
        #    宁可无 MCP 工具走纯文本，也不撑爆 LLM 请求；修复方式：减少绑定该 agent 的服务
        if len(mcp_tools) > MAX_MCP_TOOLS_PER_AGENT:
            over_servers = sorted({
                info.server_name for info in self._mcp_tools.values()
                if info.server_name in bound_servers
            })
            logger.error(
                f"[ToolRegistry] agent={agent_id} MCP 工具数 {len(mcp_tools)} 超上限 "
                f"{MAX_MCP_TOOLS_PER_AGENT} (services={over_servers})，本次不注入；"
                f"请减少绑定该 agent 的服务"
            )
            mcp_tools = []

        tools = local_tools + mcp_tools

        logger.info(
            f"[ToolRegistry] agent={agent_id} 最终工具数: {len(tools)} "
            f"(local={len(local_tools)}, mcp={len(mcp_tools)}, "
            f"skills={skills_wl}, mcp_bound_servers={sorted(bound_servers)})"
        )
        return tools

    def _build_tool_schema(self, name: str, info: ToolInfo) -> Dict[str, Any]:
        """构建单个工具的 JSON Schema"""
        normalized_params = self._normalize_parameters(info.parameters)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": info.description or f"Skill: {name}",
                "parameters": normalized_params
            }
        }
    
    def _normalize_parameters(self, parameters: Any) -> Dict[str, Any]:
        """规范化 parameters 格式，确保符合 JSON Schema 标准"""
        if not isinstance(parameters, dict):
            # 如果不是 dict，返回默认空对象结构
            return {"type": "object", "properties": {}}
        
        # 兼容旧格式：{"arg": {"type": "...", ...}}
        if "type" not in parameters and "properties" not in parameters:
            if parameters and all(isinstance(v, dict) for v in parameters.values()):
                parameters = {
                    "type": "object",
                    "properties": parameters
                }
            else:
                return {"type": "object", "properties": {}}

        # 检查是否有 type 字段
        if "type" not in parameters:
            # 如果有 properties，补齐 type
            if "properties" in parameters:
                parameters["type"] = "object"
            else:
                # 返回默认结构
                return {"type": "object", "properties": {}}
        
        # 确保 properties 存在
        if "properties" not in parameters:
            parameters["properties"] = {}
        
        # 遍历并规范化每个属性
        properties = parameters.get("properties", {})
        if isinstance(properties, dict):
            for prop_name, prop_info in properties.items():
                if isinstance(prop_info, dict):
                    # 确保每个属性都有 type
                    if "type" not in prop_info:
                        prop_info["type"] = "string"
        
        return parameters

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取单个工具的详细信息"""
        tool_info = self._tools.get(tool_name)
        if not tool_info:
            return None
        return {
            "name": tool_info.name,
            "description": tool_info.description,
            "parameters": tool_info.parameters,
            "skill_dir": str(tool_info.skill_dir)
        }

    def has_mcp_tools_for_agent(self, agent_id: str) -> bool:
        """agent 是否有已注册的 MCP 工具（服务 enabled 且绑定该 agent）。

        由服务配置 bound_agents 派生；仅判断"确实注册了工具"，避免误判。
        """
        bound_servers = set()
        try:
            from src.mcp import get_mcp_client
            bound_servers = get_mcp_client().get_bound_server_names(agent_id)
        except Exception:
            bound_servers = set()
        if not bound_servers:
            return False
        return any(
            info.server_name in bound_servers
            for info in self._mcp_tools.values()
        )

    # ★ 同前缀但功能完全不同，禁止互相替代的工具对
    #   注：kunming_theory_qa 已下线（理论题改由 knowledge_agent 知识库承接），相关工具对随技能一并移除
    NON_SUBSTITUTABLE_PAIRS = {
        ("kunming_api", "kunming_classifier"),
    }

    def find_alternative_tool(
        self, tool_name: str, context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """查找同效替代工具（用于 Tool 失败后的自动降级）

        策略：
        1. 先按 name/description 关键词相似度匹配
        2. 匹配到 score > 0 且不同于原工具 → 返回替代工具名
        3. 无匹配 → 返回 None

        Args:
            tool_name: 失败的工具名
            context: 可选的上下文（用于语义匹配，暂未启用）

        Returns:
            替代工具名，或 None 表示无替代
        """
        original_tool = self._tools.get(tool_name)
        if not original_tool:
            return None

        # 从原始工具提取关键词用于匹配
        orig_keywords = set()
        for text in [tool_name, original_tool.description or ""]:
            for part in text.replace("-", " ").replace("_", " ").lower().split():
                if len(part) >= 3:
                    orig_keywords.add(part)

        if not orig_keywords:
            return None

        best_name = None
        best_score = 0

        for name, info in self._tools.items():
            if name == tool_name:
                continue
            # 禁止本地/远程跨池错替
            if info.source != original_tool.source:
                continue

            score = 0
            alt_text = f"{name} {info.description or ''}".lower()

            for kw in orig_keywords:
                if kw in alt_text:
                    score += 1

            if score > best_score:
                best_score = score
                best_name = name

        if best_name and best_score >= 2:
            # ★ 检查是否在禁止替代列表中
            pair = (tool_name, best_name)
            pair_rev = (best_name, tool_name)
            if pair in self.NON_SUBSTITUTABLE_PAIRS or pair_rev in self.NON_SUBSTITUTABLE_PAIRS:
                logger.info(
                    f"[ToolRegistry] 跳过替代（功能不同）: {tool_name} → {best_name} "
                    f"(score={best_score}, 在禁止替代列表中)"
                )
                return None
            logger.info(
                f"[ToolRegistry] 找到替代工具: {tool_name} → {best_name} "
                f"(score={best_score})"
            )
            return best_name

        return None

    def get_tool_defaults(self, tool_name: str) -> Dict[str, Any]:
        """获取工具的默认参数值（用于失败后自动补参重试）"""
        tool_info = self._tools.get(tool_name)
        if not tool_info:
            return {}

        defaults = {}
        params = tool_info.parameters
        if not isinstance(params, dict):
            return {}

        properties = params.get("properties", {})
        if not isinstance(properties, dict):
            return {}

        for param_name, param_info in properties.items():
            if isinstance(param_info, dict) and "default" in param_info:
                defaults[param_name] = param_info["default"]

        return defaults

    def reload(self) -> int:
        """重新扫描并加载所有工具"""
        self._local_tools.clear()
        self._mcp_tools.clear()
        self._discover_tools()
        return len(self._tools)

    def get_all_tools(self) -> Dict[str, ToolInfo]:
        """获取所有已注册的工具"""
        return self._tools.copy()


def get_tool_registry() -> ToolRegistry:
    """获取全局 ToolRegistry 实例"""
    return ToolRegistry()