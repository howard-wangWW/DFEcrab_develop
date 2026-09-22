"""Agent 管理域（Agent Domain）

从 `grpc_server.GatewayV2GRPC` 按域拆出的 Mixin，承载"智能体"相关能力：

    元信息/索引     _resolve_agent_model / _sync_agents_index / _load_agent_meta / _agents_list_ttl
    列表缓存        _agents_list_cache（TTL 缓存，绑定/增删变更时主动失效）
    HTTP 接口       GET/POST /api/agents、GET/PUT/DELETE /api/agents/{id}
                    PUT/DELETE /api/agents/{id}/default、PUT /api/agents/{id}/mcp
    Agent 辅助      _default_agent_id / _set_agent_type / _reconcile_default_agent_type /
                    _persist_default_agent / _fallback_default_agent / _recommended_mcp_servers /
                    _generate_agent_description / _notify_manager_reload_agents

为什么用 Mixin：本域方法与网关实例状态（agents 列表缓存、Manager stub、路由）耦合紧密，
逐字搬运可保证**行为零变化**；后续若需进一步函数化，可把无状态部分继续下沉到独立模块。

依赖单向：本模块不 import `src.gateway.grpc_server`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # 离线环境可能缺 httpx：仅在实际调用相关代码路径时才需要
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

try:
    from src.gateway.grpc import dfecrab_pb2
except Exception:  # pragma: no cover
    dfecrab_pb2 = None  # type: ignore

from src.gateway.lifecycle.zookeeper import pick_latest_instances

#: 项目根目录（src/gateway/agent_domain.py → 上溯 2 层）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)


class AgentDomainMixin:
    """智能体管理域（方法实现逐字自 grpc_server 迁出）"""

    # --- Agent 管理 ---

    def _resolve_agent_model(self, model_config: str) -> Dict[str, Any]:
        """解析 agent 的模型三元组（配置值 / 展示名 / 上下文窗口），一次 provider 查找。

        model_config（= GET /api/models 的 config_name）有值 → 取该 provider；
        为空（跟随全局）→ 取当前全局模型。取不到时 model_name 回退空串、窗口回退 None（前端自行兜底）。
        """
        mc = (model_config or "").strip()
        try:
            from src.services.model_manager import model_manager as _mm
            cfg = _mm.get_provider_config(mc) if mc else None
            if not cfg:
                cur = _mm.get_current_provider_name() or ""
                cfg = _mm.get_provider_config(cur) if cur else None
            if not cfg:
                alive = _mm.get_all_alive_configs()
                cfg = alive[0] if alive else None
        except Exception:
            cfg = None
        cfg = cfg or {}
        return {
            "model_config": mc,
            "model_name": cfg.get("model_name", ""),
            "context_length": cfg.get("context_length"),
        }

    def _sync_agents_index(self, agent_id: str, config: Dict[str, Any]) -> None:
        """将 Agent 信息同步到 config/agents_index.json（描述索引）"""
        try:
            index_file = PROJECT_ROOT / "config" / "agents_index.json"
            index_data = {"version": "1.0", "agents": {}}
            if index_file.exists():
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
            agents_map = index_data.setdefault("agents", {})
            skills = config.get("enabled_skills") or []
            if not skills:
                tools_path = PROJECT_ROOT / "agents" / agent_id / "tools.json"
                if tools_path.exists():
                    with open(tools_path, 'r', encoding='utf-8') as f:
                        skills = json.load(f).get("enabled_skills", []) or []
            agents_map[agent_id] = {
                "icon": config.get("icon", ""),
                "name": config.get("name", agent_id),
                "description": config.get("description", ""),
                "skills": skills,
            }
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(index_data, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Index] agents_index.json 已同步: {agent_id}")
        except Exception as e:
            logger.warning(f"⚠️ 同步 agents_index.json 失败: {e}")

    def _load_agent_meta(self, agent_id: str) -> Dict[str, Any]:
        """从 agents 目录读取智能体的元信息（图标、配色、技能）
        
        agent_id 可能是 'dm' 或 'dm_agent'，尝试多种路径匹配
        PROJECT_ROOT 指向项目根目录，agents 在项目根目录下
        """
        meta = {}
        try:
            agents_base = PROJECT_ROOT / "agents"
            logger.info(f"🔍 [META] agent_id={agent_id}, agents_base={agents_base}, exists={agents_base.exists()}")
            
            # 尝试多种目录名: agent_id, agent_id_agent, agent_id+agent
            candidates = [agent_id]
            if not agent_id.endswith("_agent"):
                candidates.append(f"{agent_id}_agent")
            
            agents_dir = None
            for candidate in candidates:
                d = agents_base / candidate
                logger.info(f"🔍 [META] 尝试路径: {d}, exists={d.exists()}")
                if d.exists():
                    agents_dir = d
                    break
            
            if not agents_dir:
                logger.warning(f"⚠️ [META] agent [{agent_id}] 未找到对应目录, candidates={candidates}, agents_base={agents_base}")
                return meta
                
            # 读取 config.json 获取图标配色
            config_path = agents_dir / "config.json"
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                meta["icon"] = cfg.get("icon", "")
                meta["iconColor"] = cfg.get("iconColor", "")
                meta["bgColor"] = cfg.get("bgColor", "")
                meta["name"] = cfg.get("name", "")
                meta["agent_type"] = cfg.get("agent_type", "")
                meta["description"] = cfg.get("description", "")
                meta["system_prompt"] = cfg.get("system_prompt", "")
                meta["model_config"] = cfg.get("model_config", "")
                meta["parent_agent"] = cfg.get("parent_agent")
                logger.info(f"✅ [META] agent [{agent_id}] 读取 config.json 成功: icon={meta.get('icon')}, iconColor={meta.get('iconColor')}, bgColor={meta.get('bgColor')}, agent_type={meta.get('agent_type')}")
            else:
                logger.warning(f"⚠️ [META] agent [{agent_id}] config.json 不存在: {config_path}")
            # 读取 tools.json 获取技能列表
            tools_path = agents_dir / "tools.json"
            if tools_path.exists():
                with open(tools_path, 'r', encoding='utf-8') as f:
                    tools = json.load(f)
                meta["skills"] = tools.get("enabled_skills", [])
                logger.info(f"✅ [META] agent [{agent_id}] 读取 tools.json 成功: skills={meta.get('skills')}")
            else:
                logger.info(f"ℹ️ [META] agent [{agent_id}] tools.json 不存在: {tools_path}")
        except Exception as e:
            logger.warning(f"⚠️ 读取 agent [{agent_id}] 元信息失败: {e}")
        return meta

    def _agents_list_ttl(self) -> float:
        """/api/agents 结果缓存 TTL（读 cache.agents_list_ttl_s，缺省 1.5s）"""
        try:
            from src.config.app_config import section as _cfg_section
            _ttl = (_cfg_section("cache") or {}).get("agents_list_ttl_s", 1.5)
            return float(_ttl)
        except Exception:
            return 1.5

    async def _handle_list_agents(self, request) -> Dict[str, Any]:
        """列出所有智能体（扫描 agents/ 目录 + Zookeeper 状态补充）

        C-2：TTL 缓存——TTL 内重复调用直接返回进程内缓存（二次访问 <10ms），
        避免每次前端轮询都重扫 agents/ 目录与 ZK；TTL 到期后自动重建，状态保持新鲜。
        """
        try:
            # ★ C-2：TTL 缓存命中
            _ttl = self._agents_list_ttl()
            _now = time.time()
            if self._agents_list_cache is not None and (_now - self._agents_list_cache_at) < _ttl:
                logger.debug(f"[API] /api/agents 命中 TTL 缓存（{( _now - self._agents_list_cache_at):.2f}s < {_ttl}s）")
                return self._agents_list_cache

            all_agents = []
            logger.info(f"📋 [API] _handle_list_agents 被调用, PROJECT_ROOT={PROJECT_ROOT}")

            # 0. 加载 agents_index.json 作为描述回退源（config.json 未写 description 的老 Agent 用）
            index_descs = {}
            index_file = PROJECT_ROOT / "config" / "agents_index.json"
            if index_file.exists():
                try:
                    with open(index_file, 'r', encoding='utf-8') as f:
                        index_descs = json.load(f).get("agents", {})
                except Exception:
                    pass

            # 1. 扫描 agents/ 目录获取所有智能体配置
            agents_base = PROJECT_ROOT / "agents"
            if agents_base.exists():
                for agent_dir in sorted(agents_base.iterdir()):
                    if agent_dir.is_dir():
                        config_path = agent_dir / "config.json"
                        if config_path.exists():
                            agent_id = agent_dir.name
                            meta = self._load_agent_meta(agent_id)
                            idx_meta = index_descs.get(agent_id, {})
                            agent_data = {
                                "agent_id": agent_id,
                                "agent_type": meta.get("agent_type", ""),
                                "icon": meta.get("icon", ""),
                                "iconColor": meta.get("iconColor", ""),
                                "bgColor": meta.get("bgColor", ""),
                                "name": meta.get("name", ""),
                                "description": meta.get("description") or idx_meta.get("description", ""),
                                "model_config": meta.get("model_config", ""),
                                "model_name": "",
                                "skills": meta.get("skills", []),
                            }
                            all_agents.append(agent_data)
            
            # 2. 获取 Zookeeper 中的 Worker Agents、Default Agent 和 Manager Agent
            try:
                if self._zk_discovery:
                    worker_instances = self._zk_discovery.discover_service("worker_agent") or []
                    manager_instances = self._zk_discovery.discover_service("manager_agent") or []
                    default_instances = self._zk_discovery.discover_service("default_agent") or []
                    all_instances = worker_instances + manager_instances + default_instances
                    # 同一 agent 多实例时只保留最新注册，避免返回死进程地址
                    all_instances = pick_latest_instances(all_instances)
                    
                    if all_instances:
                        for inst in all_instances:
                            service_id = inst.get('service_id', '')
                            
                            # ★ 收敛：统一走 _zk_instance_agent_id 解析（不再产出 'default' 触发迁移告警）
                            agent_id = self._zk_instance_agent_id(inst)

                            # 根据 ZK 注册的服务类型判断 agent_type（manager 特判；default/worker 由末段按默认助手归一，
                            # 不再硬编码 dfecrab=default —— agent_type=default 跟随默认助手，切换默认后旧的自动变 worker）
                            service_name = inst.get('service_name', '')
                            if service_name == "manager_agent" or agent_id in ("manager", "manager_agent"):
                                agent_type = "manager"
                            else:
                                agent_type = "worker"
                            
                            if agent_id not in [a.get('agent_id') for a in all_agents]:
                                meta = self._load_agent_meta(agent_id)
                                # 本地 agents/ 目录无此 Agent（无 config.json）的 ZK 注册视为孤儿，
                                # 如 default_localhost.localdomain_* 之类的残留进程，跳过不展示
                                if not meta and agent_id != "manager_agent":
                                    logger.warning(
                                        f"⚠️ [API] 跳过 ZK 孤儿注册: agent_id={agent_id}, "
                                        f"service_id={service_id}（本地 agents/ 目录无此 Agent）"
                                    )
                                    continue
                                logger.info(f"📋 [API] ZK agent [{agent_id}] meta={meta}")
                                agent_data = {
                                    "agent_id": agent_id,
                                    "agent_type": agent_type,
                                    "status": "active",
                                    "address": f"{inst.get('host')}:{inst.get('port')}",
                                    "service_id": service_id
                                }
                                agent_data.update(meta)
                                all_agents.append(agent_data)
                            else:
                                # ZK 中发现的 agent 已在本地存在，补充 ZK 信息
                                for existing in all_agents:
                                    if existing.get('agent_id') == agent_id:
                                        existing["status"] = "active"
                                        existing["address"] = f"{inst.get('host')}:{inst.get('port')}"
                                        existing["service_id"] = service_id
                                        if not existing.get("agent_type"):
                                            existing["agent_type"] = agent_type
                                        break
            except Exception as e:
                logger.warning(f"⚠️ 获取 Agents 失败: {e}")
            
            # 根据 agent_type 统一颜色（同类 agent 使用相同配色）
            type_colors = {
                "manager": {"iconColor": "#FFB800", "bgColor": "#FFF8E1"},
                "worker":  {"iconColor": "#2196F3", "bgColor": "#E3F2FD"},
                "default": {"iconColor": "#FF6B6B", "bgColor": "#FFE5E5"},
            }

            # 收集 ZK 中活跃的 agent_id 集合，用于判断 status
            zk_active_ids = set()
            try:
                if self._zk_discovery:
                    for service_type in ["worker_agent", "manager_agent", "default_agent"]:
                        for inst in (self._zk_discovery.discover_service(service_type) or []):
                            # ★ 收敛：统一解析（不再产出 'default'）
                            zk_active_ids.add(self._zk_instance_agent_id(inst))
            except Exception:
                pass

            for agent in all_agents:
                # ★ agent_type 动态归一：default 全局唯一且跟随默认助手，manager 保持，其余 worker
                #（读侧修正，兼容历史 config.json 里 dfecrab 恒 default 等脏数据）
                aid = agent.get("agent_id", "")
                at = self._normalize_agent_type(aid, agent.get("agent_type", ""))
                agent["agent_type"] = at
                colors = type_colors.get(at, type_colors["default"])
                if not agent.get("iconColor"):
                    agent["iconColor"] = colors["iconColor"]
                if not agent.get("bgColor"):
                    agent["bgColor"] = colors["bgColor"]

                # 设置 status: 纯粹根据 ZK 注册记录判断
                # active: ZK 中有注册（正在运行）
                # inactive: ZK 中无注册（未运行）
                if not agent.get("status"):
                    aid = agent.get("agent_id", "")
                    if aid in zk_active_ids:
                        agent["status"] = "active"
                    else:
                        agent["status"] = "inactive"

            # 统一输出格式：确保字段顺序一致
            default_agent_id = self._default_agent_id()
            formatted_agents = []
            for agent in all_agents:
                aid = agent.get("agent_id", "")
                # ★ 模型字段一次解析（model_config 为空=跟随全局，model_name/context_length 已按全局解析好）
                am = self._resolve_agent_model(agent.get("model_config", ""))
                formatted = {
                    "agent_id": aid,
                    "agent_type": agent.get("agent_type", ""),
                    "status": agent.get("status", "inactive"),
                    "icon": agent.get("icon", ""),
                    "iconColor": agent.get("iconColor", ""),
                    "bgColor": agent.get("bgColor", ""),
                    "name": agent.get("name", ""),
                    "description": agent.get("description", ""),
                    "model_config": am["model_config"],
                    "model_name": am["model_name"],
                    "context_length": am["context_length"],
                    "skills": agent.get("skills", []),
                    # ★ 派生字段：推荐 MCP（服务级绑定反向聚合）+ 默认助手标记
                    "recommended_mcp": self._recommended_mcp_servers(aid),
                    "is_default": aid == default_agent_id,
                }
                # 可选字段（ZK 发现的 agent 才有）
                if agent.get("address"):
                    formatted["address"] = agent["address"]
                if agent.get("service_id"):
                    formatted["service_id"] = agent["service_id"]
                formatted_agents.append(formatted)

            # ★ C-2：重建后写入 TTL 缓存（含默认助手 ID，供前端预选/高亮）
            self._agents_list_cache = {"default_agent_id": default_agent_id, "agents": formatted_agents}
            self._agents_list_cache_at = time.time()
            return self._agents_list_cache
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _generate_agent_description(self, agent_id: str, system_prompt: str) -> str:
        """用LLM生成智能体功能描述（≤20字），失败时返回 agent_id"""
        try:
            from src.services.model_manager import model_manager
            provider_cfg = model_manager.get_provider_config("qwen3")
            if not provider_cfg or not provider_cfg.get("enabled", False):
                alive_configs = model_manager.get_all_alive_configs()
                if alive_configs:
                    provider_cfg = alive_configs[0]
            if not provider_cfg:
                return agent_id

            api_base = provider_cfg.get("api_base", "")
            model_name = provider_cfg.get("model_name", "")
            api_key = provider_cfg.get("api_key", "not-needed")

            prompt = f"""根据以下智能体描述，用10个字以内概括它的核心功能：
{system_prompt[:500]}
直接输出简短概括，不要任何前缀后缀、不要引号、不要解释。"""

            messages = [
                {"role": "system", "content": "你是一个精准的文本概括助手。只输出概括结果，不要任何额外内容。"},
                {"role": "user", "content": prompt}
            ]

            req_headers = {"Content-Type": "application/json"}
            if api_key and api_key != "not-needed":
                req_headers["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    json={"model": model_name, "messages": messages, "temperature": 0.1, "max_tokens": 50},
                    headers=req_headers
                )
                resp.raise_for_status()
                data = resp.json()
                if "choices" in data and data["choices"]:
                    desc = data["choices"][0]["message"]["content"].strip()
                    desc = re.sub(r'^[\'"]+|[\'"]+$', '', desc).strip()
                    if desc:
                        return desc[:20]
        except Exception as e:
            logger.warning(f"⚠️ 自动生成description失败: {e}")
        return agent_id

    async def _notify_manager_reload_agents(self) -> None:
        """通知 Manager 重新加载 Agent 描述（最佳努力，不抛异常）"""
        try:
            stub = self._get_manager_stub()
            if not stub:
                logger.warning("⚠️ Manager 不可用，跳过通知")
                return
            internal_msg = "__INTERNAL__:RELOAD_AGENTS"
            await asyncio.to_thread(
                lambda: stub.Chat(dfecrab_pb2.ChatRequest(
                    message=internal_msg,
                    session_id="__internal__",
                    user_id="__system__"
                ), timeout=10.0)
            )
            logger.info("📨 已通知 Manager 重新加载 Agent 描述")
        except Exception as e:
            logger.warning(f"⚠️ 通知 Manager 重新加载失败（不影响创建）: {e}")

    async def _handle_create_agent(self, request) -> Dict[str, Any]:
        """
        创建智能体

        在 agents/{agent_id}/ 目录下创建：
          - config.json   : 核心配置（agent_type / name / icon / system_prompt 等）
          - tools.json    : 技能清单（空列表）
          - memory.json   : 记忆文件（默认空结构，供 MemoryManager 加载）

        Body 参数：
          agent_id     (必填) - 唯一标识，仅允许小写字母/数字/下划线/连字符
          agent_type   (必填) - 三选一：worker / manager / default
          system_prompt(必填) - 系统提示词，决定 agent 行为
          description  (选填) - 功能描述（≤20字），不传则由LLM自动生成
          name         (选填) - 展示名，默认 = agent_id
          icon         (选填) - 图标 emoji，默认 "🤖"
          iconColor    (选填) - 标题颜色，默认按 agent_type 映射
          bgColor      (选填) - 背景颜色，默认按 agent_type 映射
          model_config (选填) - 模型配置名，不传则使用全局默认模型
          parent_agent (选填) - 父 agent ID，默认 null
          enabled_skills(选填)- 启用的技能列表
          builtin_tools (选填)- 内置工具列表
          custom_tools  (选填)- 自定义工具列表
          auto_start    (选填)- 是否自动启动进程（默认 true，manager 类型除外）

        注意：
          - worker/default 类型创建后会自动启动 gRPC 服务进程（通过 subprocess.Popen）
          - manager 类型由 gateway 自动管理
          - 启动的进程由 Gateway 管理，网关停止时自动清理
          - 可通过 auto_start: false 跳过自动启动
        """
        try:
            body = await request.json()
            agent_id = body.get("agent_id", "").strip()

            # ── agent_id 校验 ──
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}
            if not re.match(r'^[a-z0-9_-]+$', agent_id):
                return {"success": False, "error": "agent_id 仅允许小写字母、数字、下划线、连字符"}

            # ── agent_type 校验 ──
            valid_types = {"worker", "manager", "default"}
            agent_type = body.get("agent_type", "")
            if agent_type not in valid_types:
                return {"success": False, "error": f"agent_type 必须是 {', '.join(sorted(valid_types))} 之一"}

            # ── system_prompt 校验 ──
            system_prompt = body.get("system_prompt", "").strip()
            if not system_prompt:
                return {"success": False, "error": "system_prompt 不能为空，请提供智能体的核心行为定义"}

            # ── description 处理：用户提供或LLM自动生成 ──
            description = body.get("description", "").strip()
            if not description:
                description = await self._generate_agent_description(agent_id, system_prompt)
                logger.info(f"   🤖 自动生成 description: {description}")

            # ── 目录准备 ──
            agents_base = PROJECT_ROOT / "agents"
            agent_dir = agents_base / agent_id
            if agent_dir.exists():
                return {"success": False, "error": f"Agent [{agent_id}] 已存在"}

            agent_dir.mkdir(parents=True, exist_ok=True)

            # ── 按 agent_type 映射默认颜色 ──
            type_colors = {
                "manager": {"iconColor": "#FFB800", "bgColor": "#FFF8E1"},
                "worker":  {"iconColor": "#2196F3", "bgColor": "#E3F2FD"},
                "default": {"iconColor": "#FF6B6B", "bgColor": "#FFE5E5"},
            }
            colors = type_colors.get(agent_type, type_colors["worker"])

            # ── model_config 处理：校验必须是已启用的 provider；缺省存空 = 跟随全局模型 ──
            model_config = body.get("model_config", "").strip()
            if model_config:
                _pc = model_manager.get_provider_config(model_config)
                if not _pc or not _pc.get("enabled", False):
                    return {"success": False, "error": f"模型配置不存在或已禁用: {model_config}"}

            # ── 1. 创建 config.json ──
            now = datetime.now().isoformat()
            config = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "name": body.get("name", agent_id),
                "icon": body.get("icon", "🤖"),
                "iconColor": body.get("iconColor", colors["iconColor"]),
                "bgColor": body.get("bgColor", colors["bgColor"]),
                "system_prompt": system_prompt,
                "description": description,
                "model_config": model_config,
                "parent_agent": body.get("parent_agent"),
                "created_at": now,
                "updated_at": now,
                "welcome_message": body.get("welcome_message"),
                "auto_start": body.get("auto_start", True),
            }
            # 去除值为 None 的字段（保持 config.json 整洁）
            config = {k: v for k, v in config.items() if v is not None}

            config_path = agent_dir / "config.json"
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Create] config.json 写入: {config_path}")

            # ── 2. 创建 tools.json ──
            tools = {
                "enabled_skills": body.get("enabled_skills", []),
                "builtin_tools": body.get("builtin_tools", []),
                "custom_tools": body.get("custom_tools", []),
            }
            tools_path = agent_dir / "tools.json"
            with open(tools_path, 'w', encoding='utf-8') as f:
                json.dump(tools, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Create] tools.json 写入: {tools_path}")

            # ── 2.5 同步 agents_index.json（描述索引） ──
            self._sync_agents_index(agent_id, config)

            # ── 3. 创建 memory.json（默认空结构，MemoryManager 格式） ──
            now = datetime.now().isoformat()
            memory = {
                "short_term_memory": [],
                "long_term_memory": {
                    "professional_knowledge": [],
                    "experience": {
                        "successful_patterns": [],
                        "lessons_learned": []
                    },
                    "user_preferences": {},
                    "metadata": {
                        "created_at": now,
                        "last_updated": now,
                        "version": "2.0"
                    }
                }
            }
            memory_path = agent_dir / "memory.json"
            with open(memory_path, 'w', encoding='utf-8') as f:
                json.dump(memory, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ [Create] memory.json 写入: {memory_path}")

            # ── 通知 Manager 重新加载 Agent 描述 ──
            await self._notify_manager_reload_agents()
            # ★ C-2：agents 列表已变更，主动失效 TTL 缓存（避免列表页 1.5s 内返回旧数据）
            self._agents_list_cache = None
            auto_start = body.get("auto_start", True)
            started = False
            process_pid = None
            if auto_start and agent_type != "manager":
                proc = await self._start_agent_process(agent_id)
                if proc:
                    started = True
                    process_pid = proc.pid

            # ── 返回创建结果 ──
            am = self._resolve_agent_model(model_config)
            result = {
                "success": True,
                "agent_id": agent_id,
                "agent": {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "status": "running" if started else "inactive",
                    "process_pid": process_pid,
                    "process_started": started,
                    "name": config.get("name", agent_id),
                    "description": description,
                    "model_config": am["model_config"],
                    "model_name": am["model_name"],
                    "icon": config.get("icon", "🤖"),
                    "iconColor": config.get("iconColor", colors["iconColor"]),
                    "bgColor": config.get("bgColor", colors["bgColor"]),
                    "skills": tools.get("enabled_skills", []),
                }
            }
            logger.info(f"✅ Agent [{agent_id}] 创建成功 (description: {description}, process_started: {started})")
            return result

        except Exception as e:
            logger.error(f"❌ Agent 创建失败: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_agent(self, request, **kwargs) -> Dict[str, Any]:
        """获取单个智能体的完整配置（详情）"""
        try:
            agent_id = kwargs.get("agent_id") or (request.path_params.get("agent_id") if hasattr(request, "path_params") else None)
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}

            agent_dir = PROJECT_ROOT / "agents" / agent_id
            if not agent_dir.exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}

            meta = self._load_agent_meta(agent_id)
            # description 回退：config.json 未写时用 agents_index.json 描述索引（与列表口径一致，
            # 老 agent 如 alert_judge 的 config.json 无 description，详情页否则为空）
            if not meta.get("description"):
                try:
                    _idx_file = PROJECT_ROOT / "config" / "agents_index.json"
                    if _idx_file.exists():
                        with open(_idx_file, 'r', encoding='utf-8') as f:
                            meta["description"] = (((json.load(f).get("agents", {}) or {})
                                                    .get(agent_id) or {}).get("description", ""))
                except Exception:
                    pass
            # ★ 模型字段一次解析 + agent_type 归一（default 跟随默认助手，兼容历史脏数据）
            am = self._resolve_agent_model(meta.get("model_config", ""))
            detail = {
                "agent_id": agent_id,
                "agent_type": self._normalize_agent_type(agent_id, meta.get("agent_type", "")),
                "name": meta.get("name", ""),
                "description": meta.get("description", ""),
                "system_prompt": meta.get("system_prompt", ""),
                "model_config": am["model_config"],
                "model_name": am["model_name"],
                "context_length": am["context_length"],
                "icon": meta.get("icon", ""),
                "iconColor": meta.get("iconColor", ""),
                "bgColor": meta.get("bgColor", ""),
                "parent_agent": meta.get("parent_agent"),
                "skills": meta.get("skills", []),
            }

            # 时间戳 / 开场白 / 自动启动（config.json 补充字段）
            try:
                with open(agent_dir / "config.json", 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                detail["created_at"] = cfg.get("created_at", "")
                detail["updated_at"] = cfg.get("updated_at", "")
                detail["welcome_message"] = cfg.get("welcome_message", "")
                # auto_start：老 agent 的 config.json 可能没有（手建文件），缺省 True
                #（进程由网关 auto_start 扫描拉起；仅写 True 展示语义，不据此强制重启）
                detail["auto_start"] = cfg.get("auto_start", True)
                # 老 agent 无时间戳：兜底 config.json 文件 mtime（新 agent 创建即带，仅手建老文件缺失）
                if not detail["created_at"] or not detail["updated_at"]:
                    _mtime = datetime.fromtimestamp(
                        (agent_dir / "config.json").stat().st_mtime).isoformat()
                    if not detail["created_at"]:
                        detail["created_at"] = _mtime
                    if not detail["updated_at"]:
                        detail["updated_at"] = _mtime
            except Exception:
                pass

            # 运行状态（ZK 补充）
            detail["status"] = "inactive"
            try:
                if self._zk_discovery:
                    for service_type in ["worker_agent", "manager_agent", "default_agent"]:
                        for inst in (self._zk_discovery.discover_service(service_type) or []):
                            zk_aid = self._zk_instance_agent_id(inst)
                            if zk_aid == agent_id:
                                detail["status"] = "active"
                                detail["address"] = f"{inst.get('host')}:{inst.get('port')}"
                                detail["service_id"] = inst.get("service_id", "")
                                break
            except Exception:
                pass

            # ★ 派生字段（与列表一致，配置页一个请求拿全）：推荐 MCP + 默认助手标记
            detail["recommended_mcp"] = self._recommended_mcp_servers(agent_id)
            detail["is_default"] = agent_id == self._default_agent_id()

            return {"success": True, "data": detail}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_update_agent(self, request, **kwargs) -> Dict[str, Any]:
        """更新智能体配置（部分更新，支持热加载）

        Body 可包含任意可编辑字段；传 restart: true 时平滑重启该 agent 进程，
        使 system_prompt / model_config 等启动期缓存的配置真正生效。
        """
        try:
            agent_id = kwargs.get("agent_id") or (request.path_params.get("agent_id") if hasattr(request, "path_params") else None)
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}

            agent_dir = PROJECT_ROOT / "agents" / agent_id
            config_path = agent_dir / "config.json"
            if not config_path.exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}

            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            body = await request.json()
            if not isinstance(body, dict):
                return {"success": False, "error": "请求体必须是 JSON 对象"}

            # 可更新到 config.json 的字段
            editable = ["name", "description", "system_prompt", "icon", "iconColor", "bgColor",
                        "parent_agent", "welcome_message"]
            for key in editable:
                if key in body:
                    config[key] = body[key]

            # model_config：空串 = 清空（恢复跟随全局）；非空需校验为已启用的 provider
            #（修复：原 `and body.get("model_config")` 让空串被 falsy 吞掉，固定模型后无法改回跟随全局）
            if "model_config" in body:
                mc = str(body.get("model_config") or "").strip()
                if mc:
                    _pc = model_manager.get_provider_config(mc)
                    if not _pc or not _pc.get("enabled", False):
                        return {"success": False, "error": f"模型配置不存在或已禁用: {mc}"}
                config["model_config"] = mc

            # 技能/工具更新到 tools.json
            if any(k in body for k in ("enabled_skills", "builtin_tools", "custom_tools")):
                tools_path = agent_dir / "tools.json"
                tools = {}
                if tools_path.exists():
                    with open(tools_path, 'r', encoding='utf-8') as f:
                        tools = json.load(f)
                if "enabled_skills" in body:
                    tools["enabled_skills"] = body["enabled_skills"]
                if "builtin_tools" in body:
                    tools["builtin_tools"] = body["builtin_tools"]
                if "custom_tools" in body:
                    tools["custom_tools"] = body["custom_tools"]
                with open(tools_path, 'w', encoding='utf-8') as f:
                    json.dump(tools, f, ensure_ascii=False, indent=2)

            # 时间戳
            from datetime import datetime
            config["updated_at"] = datetime.now().isoformat()

            # 写回 config.json
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

            # 同步 agents_index.json（描述索引）
            self._sync_agents_index(agent_id, config)

            # 通知 Manager 重新加载描述
            await self._notify_manager_reload_agents()
            # ★ C-2：agents 列表已变更，主动失效 TTL 缓存
            self._agents_list_cache = None

            # 热加载：如需对运行中的进程生效，平滑重启该 agent 进程
            restart = body.get("restart", False)
            if restart:
                await self._stop_agent_process(agent_id)
                await self._start_agent_process(agent_id)

            am = self._resolve_agent_model(config.get("model_config", ""))
            return {
                "success": True,
                "message": f"Agent [{agent_id}] 已更新",
                "data": {
                    "agent_id": agent_id,
                    "name": config.get("name", agent_id),
                    "description": config.get("description", ""),
                    "model_config": am["model_config"],
                    "model_name": am["model_name"],
                    "restarted": bool(restart),
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════
    # 平台默认助手（config/dfecrab.json → default_agent，全局唯一）
    # 语义：仅作为对话页"默认预选/高亮 + 初始传参"的配置源，
    #       不接管缺省路由（不带 agent_id 仍走 Manager 智能语义路由）。
    # ══════════════════════════════════════════════════════════

    def _fallback_default_agent(self, exclude: str = "") -> str:
        """默认助手回退目标：优先 dfecrab，其次任一仍存在且非 manager 的 agent。

        用于取消/删除默认助手时保持 default_agent 始终指向存在的 agent。
        """
        try:
            agents_base = PROJECT_ROOT / "agents"
            candidates = ["dfecrab"]
            if agents_base.exists():
                candidates += sorted(
                    d.name for d in agents_base.iterdir()
                    if d.is_dir() and (d / "config.json").exists()
                )
            for cid in candidates:
                if cid == exclude or cid == "manager_agent":
                    continue
                if (agents_base / cid / "config.json").exists():
                    return cid
        except Exception as e:
            logger.warning(f"[Agent] 计算默认助手回退目标失败，回退 dfecrab: {e}")
        return "dfecrab"

    def _default_agent_id(self) -> str:
        """读取平台默认助手 agent_id。

        缺省 / 配置为空 / 指向的 agent 目录不存在时回退可用兜底 agent（_fallback_default_agent）。
        通过 app_config.section() 读取（自动剔除 _note），随配置写盘热更新。
        """
        agent_id = "dfecrab"
        try:
            from src.config.app_config import section
            cfg = section("default_agent") or {}
            candidate = str(cfg.get("agent_id", "") or "").strip()
            if candidate and (PROJECT_ROOT / "agents" / candidate / "config.json").exists():
                agent_id = candidate
            elif candidate:
                logger.warning(f"[Agent] 默认助手 [{candidate}] 不存在，回退兜底 agent")
                agent_id = self._fallback_default_agent(exclude=candidate)
        except Exception as e:
            logger.warning(f"[Agent] 读取默认智能体配置失败，回退 dfecrab: {e}")
        return agent_id

    def _recommended_mcp_servers(self, agent_id: str) -> List[str]:
        """某 agent 的推荐 MCP 服务名（enabled 且服务级绑定含该 agent 或全局 *）。

        派生自 mcporter.json 的 bound_agents（MCP 侧单一事实源），只读、失败返回空。
        """
        try:
            from src.mcp import get_mcp_client
            return sorted(get_mcp_client().get_bound_server_names(agent_id))
        except Exception as e:
            logger.debug(f"[Agent] 读取 {agent_id} 推荐 MCP 失败: {e}")
            return []

    def _set_agent_type(self, agent_id: str, agent_type: str) -> None:
        """同步 agent 的 agent_type 到 config.json（默认助手唯一化的落盘动作，best-effort）。"""
        try:
            config_path = PROJECT_ROOT / "agents" / agent_id / "config.json"
            if not config_path.exists():
                return
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            if cfg.get("agent_type") == agent_type:
                return
            cfg["agent_type"] = agent_type
            cfg["updated_at"] = datetime.now().isoformat()
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self._agents_list_cache = None
            logger.info(f"✅ [AgentType] {agent_id}.agent_type → {agent_type}")
        except Exception as e:
            logger.warning(f"⚠️ 同步 {agent_id} agent_type 失败: {e}")

    def _normalize_agent_type(self, agent_id: str, agent_type: str) -> str:
        """读侧修正 agent_type（防历史脏数据）：默认助手⇔default，manager 保持，其余 worker。"""
        if agent_type == "manager":
            return "manager"
        return "default" if agent_id == self._default_agent_id() else "worker"

    def _reconcile_default_agent_type(self) -> None:
        """启动对账：default_agent.agent_id 与各 agent config.json 的 agent_type 对齐（幂等）。

        修复历史脏数据（如老部署 dfecrab 恒 default、或默认指向 worker 类型 agent），
        保证"agent_type=default 全局唯一且跟随默认助手"这一不变量。
        """
        try:
            cur = self._default_agent_id()
            agents_base = PROJECT_ROOT / "agents"
            if not agents_base.exists():
                return
            for d in agents_base.iterdir():
                if not (d.is_dir() and (d / "config.json").exists()):
                    continue
                with open(d / "config.json", 'r', encoding='utf-8') as f:
                    at = json.load(f).get("agent_type", "")
                if d.name == cur and at != "manager":
                    self._set_agent_type(d.name, "default")
                elif at == "default" and d.name != cur:
                    self._set_agent_type(d.name, "worker")
        except Exception as e:
            logger.warning(f"⚠️ 默认助手类型对账失败（不影响启动）: {e}")

    def _persist_default_agent(self, agent_id: str) -> bool:
        """把某 agent 写为平台默认（单值覆盖 → 全局唯一），并同步 agent_type：

        - 旧默认自动降级 worker、新默认升级 default（agent_type 跟随默认，全局唯一）
        - manager 不可作为默认（调用方已拦截，此处兜底）
        - 保留 dfecrab.json 中 default_agent._note 维护说明（首次写入用默认文案）
        - 失效列表缓存
        """
        try:
            if agent_id == "manager_agent":
                logger.error("❌ manager_agent 不可设为默认助手")
                return False
            if not (PROJECT_ROOT / "agents" / agent_id / "config.json").exists():
                logger.error(f"❌ 默认助手目标 [{agent_id}] 不存在")
                return False

            from src.config.app_config import update_section, get_dfecrab_raw
            prev_raw = (get_dfecrab_raw() or {}).get("default_agent") or {}
            prev = str(prev_raw.get("agent_id", "") or "")
            note = prev_raw.get("_note") or (
                "平台默认助手（全局唯一，多现场随部署文件差异化）：agent_type=default 跟随本字段，"
                "切换时旧默认自动降级 worker；PUT /api/agents/{id}/default 设置；"
                "取消/删除默认 agent 自动回退兜底 agent（优先 dfecrab）"
            )
            update_section("default_agent", {"agent_id": agent_id, "_note": note})

            # agent_type 同步：旧的降 worker、新的升 default（prev == agent_id 时幂等跳过）
            if prev and prev != agent_id and prev != "manager_agent":
                self._set_agent_type(prev, "worker")
            self._set_agent_type(agent_id, "default")

            self._agents_list_cache = None
            logger.info(f"✅ 平台默认助手: {prev or '(无)'} → {agent_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 设置默认智能体失败: {e}")
            return False

    async def _handle_set_default_agent(self, request, **kwargs) -> Dict[str, Any]:
        """PUT /api/agents/{agent_id}/default — 设为平台默认助手（旧默认自动清除并降级 worker）"""
        try:
            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}
            if not (PROJECT_ROOT / "agents" / agent_id / "config.json").exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}
            if agent_id == "manager_agent":
                return {"success": False, "error": "manager_agent 是任务路由器，不可设为默认助手"}
            if not self._persist_default_agent(agent_id):
                return {"success": False, "error": "设置默认智能体失败（配置写入异常）"}
            return {
                "success": True,
                "message": f"已将 [{agent_id}] 设为平台默认助手",
                "data": {"agent_id": agent_id, "default_agent_id": agent_id, "is_default": True},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_clear_default_agent(self, request, **kwargs) -> Dict[str, Any]:
        """DELETE /api/agents/{agent_id}/default — 取消默认（回退兜底 agent，幂等）

        仅当该 agent 确为当前默认时才回退；对非默认 agent 调用是 no-op（不误伤真默认）。
        """
        try:
            agent_id = kwargs.get("agent_id") or request.path_params.get("agent_id")
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}
            if not (PROJECT_ROOT / "agents" / agent_id / "config.json").exists():
                return {"success": False, "error": f"Agent [{agent_id}] 不存在"}
            current = self._default_agent_id()
            if agent_id != current:
                return {
                    "success": True,
                    "message": f"[{agent_id}] 非平台默认助手，无需变更",
                    "data": {"agent_id": agent_id, "default_agent_id": current, "is_default": False},
                }
            fallback = self._fallback_default_agent(exclude=agent_id)
            if not self._persist_default_agent(fallback):
                return {"success": False, "error": "取消默认智能体失败（配置写入异常）"}
            return {
                "success": True,
                "message": f"已取消默认助手，平台默认回退 {fallback}",
                "data": {"agent_id": agent_id, "default_agent_id": fallback, "is_default": False},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_save_agent_mcp(self, request, **kwargs) -> Dict[str, Any]:
        """PUT /api/agents/{agent_id}/mcp — 网关包装：调 MCPHandler 保存绑定后立即失效列表缓存。

        列表缓存内含 recommended_mcp 派生字段，绑定变更必须主动失效（TTL 仅 1.5s 兜底）。
        """
        from src.gateway.handlers.mcp_handler import MCPHandler
        result = await MCPHandler.save_agent_mcp(request, **kwargs)
        if result.get("success"):
            self._agents_list_cache = None
        return result


    async def _handle_delete_agent(self, request, **kwargs) -> Dict[str, Any]:
        """删除智能体（删除 agents/ 目录 + 停止进程）"""
        try:
            agent_id = kwargs.get('agent_id') or request.path_params.get('agent_id')
            if not agent_id:
                return {"success": False, "error": "agent_id 不能为空"}

            process_stopped = await self._stop_agent_process(agent_id)
            if process_stopped:
                logger.info(f"   ✅ Agent [{agent_id}] 进程已停止")

            agents_base = PROJECT_ROOT / "agents"
            agent_dir = agents_base / agent_id

            if not agent_dir.exists():
                return {"success": False, "error": f"Agent {agent_id} 不存在"}

            import shutil
            shutil.rmtree(agent_dir)

            try:
                index_file = PROJECT_ROOT / "config" / "agents_index.json"
                if index_file.exists():
                    with open(index_file, 'r', encoding='utf-8') as f:
                        index_data = json.load(f)
                    if agent_id in index_data.get("agents", {}):
                        del index_data["agents"][agent_id]
                        with open(index_file, 'w', encoding='utf-8') as f:
                            json.dump(index_data, f, ensure_ascii=False, indent=2)
                    logger.info(f"✅ [Index] agents_index.json 已清理: {agent_id}")
            except Exception as e:
                logger.warning(f"⚠️ 清理 agents_index.json 失败: {e}")

            try:
                if agent_id == self._default_agent_id():
                    fallback = self._fallback_default_agent(exclude=agent_id)
                    self._persist_default_agent(fallback)
                    logger.info(f"✅ 默认助手 [{agent_id}] 已删除，平台默认回退 {fallback}")
            except Exception as e:
                logger.warning(f"⚠️ 清理平台默认助手失败: {e}")

            logger.info(f"✅ Agent {agent_id} 删除成功")
            # ★ C-2：agents 列表已变更，主动失效 TTL 缓存
            self._agents_list_cache = None
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}
    def _scan_agent_descriptions(self) -> Dict[str, Dict]:
        """扫描 agents 目录，优先从 agents_index.json 读取描述（带缓存）"""
        agents_dir = PROJECT_ROOT / "agents"
        if not agents_dir.exists():
            return {}

        # 检查目录修改时间
        current_mtime = agents_dir.stat().st_mtime
        current_snapshot = {}
        for f in agents_dir.iterdir():
            if f.is_dir() and (f / "config.json").exists():
                try:
                    current_snapshot[f.name] = (f / "config.json").stat().st_mtime
                except:
                    pass

        # 未变更，直接返回缓存
        if current_mtime == self._agents_dir_mtime and self._agents_dir_snapshot == current_snapshot:
            return self._agent_descriptions

        # 优先从 agents_index.json 读取描述
        index_file = PROJECT_ROOT / "config" / "agents_index.json"
        index_info = {}
        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                    index_info = index_data.get("agents", {})
            except Exception as e:
                logger.warning(f"⚠️ 读取 {index_file} 失败: {e}")

        # 有变更，重新扫描
        descriptions = {}
        for d in sorted(agents_dir.iterdir()):
            if not d.is_dir():
                continue
            cfg_file = d / "config.json"
            if not cfg_file.exists():
                continue
            try:
                with open(cfg_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                agent_id = d.name
                if agent_id == "manager_agent":
                    continue
                
                # 优先从 index 获取描述，没有则从 config.json 获取
                index_entry = index_info.get(agent_id, {})
                descriptions[agent_id] = {
                    "name": index_entry.get("name", cfg.get("name", agent_id)),
                    "description": index_entry.get("description", cfg.get("description", "")),
                    "keywords": cfg.get("keywords", []),
                }
            except:
                pass

        self._agent_descriptions = descriptions
        self._agents_dir_mtime = current_mtime
        self._agents_dir_snapshot = current_snapshot
        logger.info(f"🔄 Gateway Agent列表已刷新，共 {len(descriptions)} 个可用Agent")
        return descriptions

    def _build_gateway_agent_list(self) -> tuple:
        """构建 Gateway 可用 Agent 列表 + 动态路由规则（带缓存）

        Returns:
            (agent_list_str, route_rules_str)
        """
        descriptions = self._scan_agent_descriptions()

        agent_lines = []
        route_lines = []

        for agent_id, info in descriptions.items():
            name = info["name"]
            desc = info["description"]
            keywords = info["keywords"]

            # Agent 列表行
            kw_str = "、".join(keywords[:5]) if keywords else ""
            desc_str = f"（关键词：{kw_str}）" if kw_str else ""
            # alert_judge 特殊标注
            if agent_id == "alert_judge":
                desc_str = "（仅处理JSON格式告警信号，不处理自然语言查询）"
            agent_lines.append(f"- {agent_id}（{name}）: {desc}{desc_str}")

            # 动态路由规则行
            if agent_id == "alert_judge":
                # alert_judge 不生成关键词路由，仅在输入为JSON告警格式时匹配
                continue
            if keywords:
                route_lines.append(f"- {'/'.join(keywords[:3])}等 → {agent_id}")
            elif desc:
                route_lines.append(f"- {desc} → {agent_id}")

        agent_list = "\n".join(agent_lines) if agent_lines else "无可调用 Agent"
        route_rules = "\n".join(route_lines) if route_lines else ""
        return agent_list, route_rules
