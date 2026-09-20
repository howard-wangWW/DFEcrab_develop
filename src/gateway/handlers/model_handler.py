"""
模型管理处理器

处理模型供应商相关的 HTTP 请求
"""

from typing import Dict, Any, Optional
from src.services.model_manager import model_manager
from src.agent.llm.fallback import get_fallback_manager
from src.agent.llm.retry import get_retry_manager
from src.utils.api_base import normalize_api_base


class ModelHandler:
    """模型管理处理器"""

    @staticmethod
    async def list_models(request: Optional[Any] = None) -> Dict[str, Any]:
        """列出所有模型供应商及在线状态（脱敏，用于前端模型选择下拉）"""
        try:
            all_providers = model_manager.get_all_providers()
            fallback_chain = model_manager.get_fallback_chain()
            current = model_manager.get_current_provider_name()

            # 动态探测每个启用模型的存活状态
            import httpx
            runtime_status = {}

            async def _check_alive_async(config: Dict[str, Any]) -> Dict[str, Any]:
                # ★ 统一清洗：即使配置误填完整接口地址（带 /chat/completions），剥成根地址再拼
                api_base = normalize_api_base(config.get("api_base", ""))
                if not api_base:
                    return {"status": "offline", "reachable": False, "last_error": "No api_base configured"}

                headers = {}
                if config.get("api_key") and config["api_key"] != "not-needed":
                    headers["Authorization"] = f"Bearer {config['api_key']}"
                model_name = config.get("model_name", "")

                # 1. GET /models 可达即认为 online，避免用真实推理请求误判
                #    注意：部分网关不支持 /models（返回 404/405），属正常，落入第 2 步 chat 探测
                try:
                    url = f"{api_base}/models"
                    async with httpx.AsyncClient(timeout=3.0) as client:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 200:
                            return {"status": "online", "reachable": True, "last_error": ""}
                except Exception:
                    pass  # 连接失败也走第 2 步，让 chat 探测给出最终判定

                # 2. /models 不可用时，用稳定的英文 prompt 做轻量 chat 探测
                try:
                    url = f"{api_base}/chat/completions"
                    payload = {
                        "model": model_name,
                        "messages": [{"role": "user", "content": "Say OK."}],
                        "max_tokens": 20,
                        "temperature": 0.1
                    }
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.post(url, json=payload, headers=headers)
                        if resp.status_code in [200, 400, 401, 403]:
                            return {"status": "online", "reachable": True, "last_error": ""}
                        if resp.status_code == 404:
                            return {
                                "status": "offline",
                                "reachable": False,
                                "last_error": f"HTTP 404：{url} 不存在。请检查 api_base 是否误填了完整接口地址（应填到根地址，如 http://ip:port/v1 或 http://ip:port/apis/ais-v2）",
                            }
                        return {"status": "degraded", "reachable": True, "last_error": f"HTTP {resp.status_code}"}
                except Exception as e:
                    return {"status": "offline", "reachable": False, "last_error": str(e)}

            for provider in all_providers:
                name = provider["config_name"]
                if not provider.get("enabled"):
                    runtime_status[name] = {"status": "disabled", "reachable": False, "last_error": ""}
                    continue
                config = model_manager.get_provider_config(name)
                if config:
                    runtime_status[name] = await _check_alive_async(config)

            # 组装返回：每个 provider 合并运行时状态，脱敏
            providers = []
            for p in all_providers:
                name = p["config_name"]
                status_info = runtime_status.get(
                    name, {"status": "offline", "reachable": False, "last_error": ""}
                )
                providers.append({
                    "config_name": name,
                    "model_name": p.get("model_name", ""),
                    "model_type": p.get("model_type", "openai_chat"),
                    "enabled": p.get("enabled", True),
                    "status": status_info.get("status", "offline"),
                    "reachable": status_info.get("reachable", False),
                    "last_error": status_info.get("last_error", ""),
                    "has_api_key": p.get("has_api_key", False),
                    "api_base": p.get("api_base", "") if p.get("enabled") else "",
                    "context_length": p.get("context_length"),  # ★ 上下文窗口（可自动发现）
                    # ★ v4.5 生成参数：数据源(get_all_providers)已含，此处透传供前端编辑弹窗回填
                    "temperature": p.get("temperature", 0.7),
                    "max_tokens": p.get("max_tokens", 2048),
                    "timeout": p.get("timeout", 120),
                })

            return {
                "success": True,
                "data": {
                    "providers": providers,
                    "fallback_chain": fallback_chain,
                    "current_provider": current,
                    "runtime_status": runtime_status
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def get_current(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取当前模型信息"""
        try:
            current = model_manager.get_current_provider_name()
            config = model_manager.get_provider_config(current)
            return {
                "success": True,
                "data": {
                    "current_provider": current,
                    "config": config
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def switch(request: Any) -> Dict[str, Any]:
        """切换模型供应商"""
        try:
            body = await request.json()
            provider_name = body.get("provider")

            if not provider_name:
                return {"success": False, "error": "未指定供应商名称"}

            config = model_manager.get_provider_config(provider_name)

            if not config:
                return {"success": False, "error": f"未找到供应商: {provider_name}"}

            if not config.get("enabled", True):
                return {"success": False, "error": f"供应商 {provider_name} 已禁用"}

            model_manager._current_provider = provider_name

            return {
                "success": True,
                "message": f"已切换到供应商: {provider_name}",
                "data": {
                    "current_provider": provider_name,
                    "config": config
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def create(request: Any) -> Dict[str, Any]:
        """新增模型（持久化到 dfecrab.json + 热生效，免重启）"""
        try:
            body = await request.json()
            name = str(body.get("config_name") or "").strip()
            if not name:
                return {"success": False, "error": "config_name 必填"}
            if model_manager.get_provider_config(name):
                return {"success": False, "error": f"模型已存在: {name}"}
            if not (body.get("api_base") or "").strip():
                return {"success": False, "error": "api_base 必填"}
            if not (body.get("model_name") or "").strip():
                return {"success": False, "error": "model_name 必填"}
            if not model_manager.add_provider(name, body):
                return {"success": False, "error": f"新增模型失败: {name}"}
            # ★ 阶段A：未显式指定 context_length 时，自动从 /models 探测真实窗口
            if not (body.get("context_length") or ""):
                discovered = model_manager.discover_context_length(name)
                note = f"，context_length=自动发现 {discovered}" if discovered else "，context_length=探测失败（用默认值）"
            else:
                note = ""
            if body.get("set_current"):
                model_manager.switch_provider(name)
            return {
                "success": True,
                "message": f"已新增模型: {name}{note}",
                "data": {"config_name": name, "current_provider": model_manager.get_current_provider_name()},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def update(request: Any, **kwargs) -> Dict[str, Any]:
        """编辑模型（只覆盖传入字段，保留未传字段）"""
        try:
            name = kwargs.get("config_name") or (
                request.path_params.get("config_name") if hasattr(request, "path_params") else None
            )
            if not name:
                return {"success": False, "error": "config_name 必填"}
            body = await request.json()
            if not model_manager.update_provider(name, body):
                return {"success": False, "error": f"编辑模型失败: {name}（不存在）"}
            # ★ 阶段A：编辑后未显式指定 context_length 时，尝试自动探测（best-effort，失败不影响）
            if not (body.get("context_length") or ""):
                model_manager.discover_context_length(name)
            return {"success": True, "message": f"已编辑模型: {name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def discover(request: Any, **kwargs) -> Dict[str, Any]:
        """手动触发上下文窗口自动发现（从 /models 读 max_model_len，写回配置）"""
        try:
            name = kwargs.get("config_name") or (
                request.path_params.get("config_name") if hasattr(request, "path_params") else None
            )
            if not name:
                return {"success": False, "error": "config_name 必填"}
            clen = model_manager.discover_context_length(name)
            if not clen:
                return {"success": False,
                        "error": f"探测失败: {name}（检查 api_base 是否为 vLLM/OpenAI 兼容 /models）"}
            return {"success": True, "message": f"已发现 {name} 上下文窗口: {clen}",
                    "data": {"config_name": name, "context_length": clen}}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def delete(request: Any, **kwargs) -> Dict[str, Any]:
        """删除模型（不能删当前全局模型；不能删被 Agent 引用的模型）"""
        try:
            from pathlib import Path
            import json as _json
            import glob as _glob
            name = kwargs.get("config_name") or (
                request.path_params.get("config_name") if hasattr(request, "path_params") else None
            )
            if not name:
                return {"success": False, "error": "config_name 必填"}
            # 检查是否被 Agent 的 model_config 引用
            agents_dir = Path(__file__).resolve().parent.parent.parent / "agents"
            referenced = []
            for cfg_file in _glob.glob(str(agents_dir / "*" / "config.json")):
                try:
                    with open(cfg_file, encoding="utf-8") as f:
                        d = _json.load(f)
                    if (d.get("model_config") or "") == name:
                        referenced.append(Path(cfg_file).parent.name)
                except Exception:
                    pass
            if referenced:
                return {"success": False, "error": f"模型 {name} 正被 Agent 引用: {referenced}，请先解除绑定"}
            if not model_manager.remove_provider(name):
                return {"success": False, "error": f"删除模型失败: {name}（不存在或为当前全局模型，请先切换）"}
            return {"success": True, "message": f"已删除模型: {name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def toggle(request: Any, **kwargs) -> Dict[str, Any]:
        """启用/禁用模型"""
        try:
            name = kwargs.get("config_name") or (
                request.path_params.get("config_name") if hasattr(request, "path_params") else None
            )
            if not name:
                return {"success": False, "error": "config_name 必填"}
            body = await request.json()
            enabled = bool(body.get("enabled", True))
            if not model_manager.toggle_provider(name, enabled):
                return {"success": False, "error": f"启停模型失败: {name}（不存在）"}
            return {"success": True, "message": f"模型 {name} {'已启用' if enabled else '已禁用'}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class FallbackHandler:
    """容错机制处理器"""

    @staticmethod
    async def status(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取容错状态"""
        try:
            fallback_mgr = get_fallback_manager()
            retry_mgr = get_retry_manager()

            fallback_stats = fallback_mgr.get_stats()
            circuit_breakers = {}
            for name, cb in retry_mgr.circuit_breakers.items():
                circuit_breakers[name] = {
                    "state": cb.state,
                    "failure_count": cb.failure_count
                }

            return {
                "success": True,
                "data": {
                    "fallback": fallback_stats,
                    "circuit_breakers": circuit_breakers
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
