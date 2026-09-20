"""
模型管理器

负责管理多个 AI 模型配置，提供模型切换、降级链等功能
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ★ 上下文窗口安全默认值（阶段 A 统一收口，定义于 src/utils/context_usage.py）
from src.utils.context_usage import DEFAULT_CONTEXT_LENGTH
# ★ api_base 规范化（根地址约定，防现场误填完整接口地址 → 重复拼接 404）
from src.utils.api_base import normalize_api_base


class ModelManager:
    """模型管理器"""
    
    _instance: Optional['ModelManager'] = None
    
    def __init__(self):
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._current_provider: str = "default"
        self._fallback_chain: List[str] = []
        self._config_file: Path = Path(__file__).parent.parent.parent / "config" / "dfecrab.json"
        
        # 模型健康检查缓存（避免频繁重试）
        self._health_cache: Dict[str, Dict] = {}  # {provider_name: {"alive": bool, "timestamp": float}}
        self._health_cache_ttl: float = 30.0  # 缓存30秒，避免频繁检查
        
        # 加载配置
        self._load_config()
    
    @classmethod
    def get_instance(cls) -> 'ModelManager':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _load_config(self) -> None:
        """加载模型配置"""
        if not self._config_file.exists():
            logger.warning(f"⚠️ 配置文件不存在：{self._config_file}")
            return
        
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 加载模型配置（统一读 model_providers 段，各模型平等）
            model_providers = config.get("model_providers", {})
            for name, provider_config in model_providers.items():
                self._providers[name] = {
                    "config_name": name,
                    "provider": provider_config.get("provider", "openai_compatible"),
                    "model_name": provider_config.get("model_name", ""),
                    "model_type": provider_config.get("model_type", "openai_chat"),
                    # ★ 统一清洗：现场可能误填完整接口地址（带 /chat/completions 等），剥成根地址
                    "api_base": normalize_api_base(provider_config.get("api_base", "")),
                    "api_key": provider_config.get("api_key", ""),
                    "timeout": provider_config.get("timeout", 120),
                    "temperature": provider_config.get("temperature", 0.7),
                    "enabled": provider_config.get("enabled", True),
                    "context_length": provider_config.get("context_length", DEFAULT_CONTEXT_LENGTH),  # ★ 上下文窗口，供 token 占比计算
                    "max_tokens": provider_config.get("max_tokens", 2048),          # ★ 生成上限，agent 级模型需要
                    "think_config": provider_config.get("think_config")             # ★ 思考标签配置，agent 级模型需要
                }
            
            # ★ current_provider：默认第一个 enabled（多模型运行时切换由 switch_provider 管理）
            first_enabled = next(
                (n for n, c in self._providers.items() if c.get("enabled", False)),
                None
            )
            if first_enabled:
                self._current_provider = first_enabled
            elif self._providers:
                # 全禁用时指向第一个，便于后续 switch_provider 接管
                self._current_provider = next(iter(self._providers))

            # 降级链：其余 enabled 且非当前模型
            self._fallback_chain = [
                name for name, cfg in self._providers.items()
                if cfg.get("enabled", False) and name != self._current_provider
            ]

            logger.info(f"📦 已加载 {len(self._providers)} 个模型配置")
            logger.info(f"🔄 当前模型：{self._current_provider}")
            logger.info(f"🔄 降级链：{self._fallback_chain}")
            
        except Exception as e:
            logger.error(f"❌ 加载模型配置失败：{e}")
    
    def get_current_provider_name(self) -> str:
        """获取当前模型名称"""
        return self._current_provider
    
    def get_provider_config(self, provider_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取模型配置"""
        name = provider_name or self._current_provider
        return self._providers.get(name)
    
    def get_model_configs_for_agentscope(self) -> List[Dict[str, Any]]:
        """获取适用于 AgentScope 的模型配置列表"""
        configs = []
        for name, config in self._providers.items():
            if config.get("enabled", False):
                configs.append({
                    "config_name": name,
                    "model_type": config.get("model_type", "openai_chat"),
                    "model_name": config.get("model_name", ""),
                    "api_base": config.get("api_base", ""),
                    "api_key": config.get("api_key", ""),
                })
        return configs

    def get_all_providers(self) -> List[Dict[str, Any]]:
        """返回所有模型供应商的元信息（含 disabled，脱敏，用于前端模型下拉）

        与 get_model_configs_for_agentscope 的区别：
        - 返回所有 provider（含 disabled），供前端展示/置灰；
        - 不暴露 api_key，仅用 has_api_key 表示是否已配置。
        """
        result = []
        for name, config in self._providers.items():
            result.append({
                "config_name": name,
                "model_name": config.get("model_name", ""),
                "model_type": config.get("model_type", "openai_chat"),
                "provider": config.get("provider", "openai_compatible"),
                "enabled": config.get("enabled", True),
                "api_base": config.get("api_base", ""),
                "has_api_key": bool(config.get("api_key")),
                "context_length": config.get("context_length", DEFAULT_CONTEXT_LENGTH),  # ★ 上下文窗口（可自动发现）
                # ★ 模型级参数（供前端编辑弹窗回填，本次 LLM 参数配置化新增）
                "temperature": config.get("temperature", 0.7),
                "max_tokens": config.get("max_tokens", 2048),
                "timeout": config.get("timeout", 120),
            })
        return result

    def get_fallback_chain(self) -> List[str]:
        """获取降级链"""
        return self._fallback_chain
    
    def switch_provider(self, provider_name: str) -> bool:
        """切换模型"""
        if provider_name not in self._providers:
            logger.error(f"❌ 模型不存在：{provider_name}")
            return False
        
        if not self._providers[provider_name].get("enabled", False):
            logger.error(f"❌ 模型未启用：{provider_name}")
            return False
        
        old_provider = self._current_provider
        self._current_provider = provider_name
        logger.info(f"🔄 模型已切换：{old_provider} -> {provider_name}")
        return True

    def _check_alive(self, config: Dict[str, Any], verify_content: bool = False) -> bool:
        """检测模型服务是否可达（可选项验证内容质量）

        Args:
            config: 模型配置
            verify_content: True 时额外验证模型能否返回有效内容

        Returns:
            bool: 服务是否存活且健康
        """
        import httpx
        import time as _time

        # ★ 统一清洗：config 可能来自外部直接构造，兜底剥掉完整接口地址
        api_base = normalize_api_base(config.get("api_base", ""))
        provider_name = config.get("config_name", "unknown")

        # ✅ 新增：检查 enabled 字段，禁用的模型直接返回 False，不探活
        if config.get("enabled") is False:
            logger.debug(f"📦 [{provider_name}] 已禁用(enabled=false)，跳过探活")
            return False

        if not api_base:
            logger.error(f"❌ [{provider_name}] 探活失败：api_base 为空")
            return False

        # 检查缓存
        current_time = _time.time()
        if provider_name in self._health_cache:
            cache = self._health_cache[provider_name]
            if current_time - cache["timestamp"] < self._health_cache_ttl:
                logger.debug(f"📦 [{provider_name}] 使用缓存结果: {'存活' if cache['alive'] else '不可达'}")
                return cache["alive"]

        headers = {}
        if config.get("api_key") and config["api_key"] != "not-needed":
            headers["Authorization"] = f"Bearer {config['api_key']}"
        model_name = config.get("model_name", "")
        timeout = config.get("timeout", 120)

        logger.debug(f"🔍 [{provider_name}] 开始探活 - API: {api_base}, Model: {model_name}")

        # HTTP 不需要 verify 参数；trust_env=False 避免环境变量代理干扰
        # ✅ 优化：超时从 10s/3s 缩短到 5s/2s，减少不可达模型的等待时间
        with httpx.Client(timeout=httpx.Timeout(5, connect=2.0), trust_env=False) as client:
            # Step 1: GET /models 轻量探测
            try:
                logger.debug(f"🔍 [{provider_name}] 尝试 GET {api_base}/models")
                resp = client.get(f"{api_base}/models", headers=headers)
                if resp.status_code == 200:
                    logger.debug(f"✅ [{provider_name}] /models 接口正常")
                    # 缓存存活结果
                    self._health_cache[provider_name] = {"alive": True, "timestamp": current_time}
                    return True
                else:
                    logger.debug(f"⚠️ [{provider_name}] /models 返回 HTTP {resp.status_code}")
            except Exception as e:
                logger.debug(f"⚠️ [{provider_name}] /models 接口失败: {type(e).__name__}")

            # Step 2: POST /chat/completions（只重试 1 次，间隔 1 秒）
            # ✅ 优化：从 2 次重试减少到 1 次，间隔从 2 秒减少到 1 秒
            for attempt in range(1):
                try:
                    if verify_content:
                        payload = {
                            "model": model_name,
                            "messages": [{"role": "user", "content": "回复OK"}],
                            "max_tokens": 10,
                            "temperature": 0.1,
                        }
                    else:
                        payload = {"model": model_name, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10}

                    url = f"{api_base}/chat/completions"
                    logger.debug(f"🔍 [{provider_name}] 尝试 POST {url}（第 {attempt + 1}/1 次）")
                    resp = client.post(url, json=payload, headers=headers)

                    if resp.status_code == 200:
                        logger.debug(f"✅ [{provider_name}] chat/completions 响应正常")
                        # 缓存存活结果
                        self._health_cache[provider_name] = {"alive": True, "timestamp": current_time}
                        return True
                    elif resp.status_code in [400, 401, 403]:
                        logger.debug(f"⚠️ [{provider_name}] 服务存活（HTTP {resp.status_code}）")
                        # 缓存存活结果（认证错误但服务存活）
                        self._health_cache[provider_name] = {"alive": True, "timestamp": current_time}
                        return True
                    elif resp.status_code == 404:
                        # ★ 404 多为 api_base 误填完整接口地址导致重复拼接，给出可行动的提示
                        logger.error(
                            f"❌ [{provider_name}] POST {url} 返回 404 —— 请检查 api_base 是否为根地址"
                            f"（当前: {api_base}，应为 http://ip:port/v1 或 http://ip:port/apis/ais-v2）"
                        )
                    else:
                        logger.debug(f"⚠️ [{provider_name}] POST 返回 HTTP {resp.status_code}")
                except Exception as e:
                    # ✅ 探活失败降为 DEBUG，避免日志噪音（真正的不可达由 get_active_model_config 的 WARNING 处理）
                    logger.debug(f"⚠️ [{provider_name}] 连接异常：{type(e).__name__}")

            # 缓存不可达结果
            self._health_cache[provider_name] = {"alive": False, "timestamp": current_time}
            logger.debug(f"❌ [{provider_name}] 探活失败：所有尝试均未通过")
            return False

    def get_active_model_config(self) -> Optional[Dict[str, Any]]:
        """
        核心方法：自动探活并返回当前可用的模型配置。
        ✅ 优化：探到第一个可用就返回，不再继续探活剩余模型。

        策略：
        1. 优先测试当前主模型（如果 enabled=true）
        2. 主模型不可用，按 fallback_chain 顺序探活，找到第一个可用就返回
        3. 找到后自动切换 current_provider，后续请求直接用缓存
        """
        # 1. 优先测试当前主模型（跳过 enabled=false 的）
        current_config = self._providers.get(self._current_provider)
        if current_config and current_config.get("enabled", True):
            if self._check_alive(current_config, verify_content=True):
                return current_config

        logger.warning(f"⚠️ 主模型 {self._current_provider} 不可用，开始尝试降级链...")

        # 2. 遍历降级链，找到第一个可用就返回
        for fallback_name in self._fallback_chain:
            fallback_config = self._providers.get(fallback_name)
            if not fallback_config or not fallback_config.get("enabled", True):
                continue
            if self._check_alive(fallback_config, verify_content=True):
                logger.info(f"✅ 找到可用模型：{fallback_name}，切换并返回")
                self.switch_provider(fallback_name)
                return fallback_config

        logger.error("❌ 所有模型服务均不可达！")
        return None

    def get_all_alive_configs(self) -> List[Dict[str, Any]]:
        """获取所有存活的模型配置列表（按优先级排序）。
        
        与 get_active_model_config 不同：
        - 不切换 current_provider
        - 返回所有存活模型的列表
        - 用于请求级 fallback 轮询
        """
        alive_configs = []

        # 1. 先测试当前主模型（跳过 enabled=false 的）
        current = self._providers.get(self._current_provider)
        if current and current.get("enabled", True) and self._check_alive(current, verify_content=True):
            alive_configs.append({
                "name": self._current_provider,
                **current
            })

        # 2. 再测试降级链中的模型（跳过 enabled=false 的）
        for name in self._fallback_chain:
            cfg = self._providers.get(name)
            if not cfg or not cfg.get("enabled", True):
                continue
            if self._check_alive(cfg, verify_content=True):
                alive_configs.append({
                    "name": name,
                    **cfg
                })
        
        if alive_configs:
            alive_names = [c["name"] for c in alive_configs]
            logger.info(f"✅ 存活模型列表: {alive_names}")
        else:
            logger.error("❌ 所有模型均不可达")
        
        return alive_configs
    
    def get_next_fallback(self) -> Optional[str]:
        """获取下一个备用模型"""
        current_index = -1
        for i, name in enumerate(self._fallback_chain):
            if name == self._current_provider:
                current_index = i
                break
        
        # 返回下一个模型
        next_index = current_index + 1 if current_index >= 0 else 0
        if next_index < len(self._fallback_chain):
            return self._fallback_chain[next_index]
        
        return None
    
    def list_providers(self) -> List[Dict[str, Any]]:
        """列出所有模型"""
        return [
            {
                "name": name,
                "provider": config.get("provider"),
                "model_name": config.get("model_name"),
                "enabled": config.get("enabled", False),
                "is_current": name == self._current_provider
            }
            for name, config in self._providers.items()
        ]
    
    def reload_config(self) -> None:
        """重新加载配置"""
        self._providers.clear()
        self._load_config()
        logger.info("🔄 模型配置已重新加载")

    # ──────────────────────────────────────────────────────────────
    # 模型 CRUD（持久化到 dfecrab.json + 热生效，免重启）
    # ──────────────────────────────────────────────────────────────

    def _update_config_provider(self, name: str, fields: Dict[str, Any], remove: bool = False) -> bool:
        """把单个 provider 写回 dfecrab.json 的 model_providers（原子写 + 备份）。

        Args:
            name: provider 名
            fields: 要合并进该 provider 的字段（remove=True 时忽略）
            remove: True 时删除该 provider

        Returns:
            bool: 是否写入成功
        """
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 写前备份
            (self._config_file.with_suffix('.json.bak')).write_text(
                json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            mp = config.setdefault("model_providers", {})
            if remove:
                mp.pop(name, None)
            else:
                current = mp.get(name, {})
                current.update(fields)
                mp[name] = current
            # 原子写：临时文件 + replace
            tmp = self._config_file.with_suffix('.json.tmp')
            tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
            tmp.replace(self._config_file)
            logger.info(f"💾 已写回模型配置: {name} (remove={remove})")
            return True
        except Exception as e:
            logger.error(f"❌ 写回模型配置失败 [{name}]: {e}")
            return False

    def _normalize_provider(self, name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """把外部传入的模型配置规范化为内部 _providers 结构"""
        return {
            "config_name": name,
            "provider": cfg.get("provider", "openai_compatible"),
            "model_name": cfg.get("model_name", ""),
            "model_type": cfg.get("model_type", "openai_chat"),
            # ★ 统一清洗：CRUD 前端传完整接口地址也能自动剥成根地址
            "api_base": normalize_api_base(cfg.get("api_base", "")),
            "api_key": cfg.get("api_key", ""),
            "timeout": cfg.get("timeout", 120),
            "enabled": cfg.get("enabled", True),
            "context_length": cfg.get("context_length", DEFAULT_CONTEXT_LENGTH),
            "max_tokens": cfg.get("max_tokens", 2048),
            "think_config": cfg.get("think_config"),
        }

    def _rebuild_fallback(self) -> None:
        """重建降级链（除当前外的 enabled provider）"""
        self._fallback_chain = [
            n for n, c in self._providers.items()
            if c.get("enabled", False) and n != self._current_provider
        ]

    def add_provider(self, name: str, cfg: Dict[str, Any]) -> bool:
        """新增模型：写回文件 + 更新内存 + 重建降级链。"""
        if not name or name in self._providers:
            logger.error(f"❌ 新增模型失败：{name} 已存在或为空")
            return False
        norm = self._normalize_provider(name, cfg)
        persist = dict(norm)
        persist.pop("config_name", None)
        if not self._update_config_provider(name, persist):
            return False
        self._providers[name] = norm
        self._rebuild_fallback()
        logger.info(f"➕ 已新增模型: {name} ({norm.get('model_name')})")
        return True

    def update_provider(self, name: str, cfg: Dict[str, Any]) -> bool:
        """编辑模型（只覆盖传入字段，保留未传字段）。"""
        existing = self._providers.get(name)
        if not existing:
            logger.error(f"❌ 编辑模型失败：{name} 不存在")
            return False
        merged = dict(existing)
        merged.update({k: v for k, v in cfg.items() if v is not None})
        # ★ 统一清洗：编辑时若传了完整接口地址，剥成根地址再落盘
        merged["api_base"] = normalize_api_base(merged.get("api_base", ""))
        merged.setdefault("enabled", True)
        merged.setdefault("context_length", DEFAULT_CONTEXT_LENGTH)
        merged.setdefault("max_tokens", 2048)
        persist = dict(merged)
        persist.pop("config_name", None)
        if not self._update_config_provider(name, persist):
            return False
        self._providers[name] = merged
        self._rebuild_fallback()
        logger.info(f"✏️  已编辑模型: {name}")
        return True

    def remove_provider(self, name: str) -> bool:
        """删除模型（不能删除当前全局模型）。"""
        if name not in self._providers:
            logger.error(f"❌ 删除模型失败：{name} 不存在")
            return False
        if name == self._current_provider:
            logger.error(f"❌ 删除模型失败：{name} 是当前全局模型，请先切换")
            return False
        if not self._update_config_provider(name, {}, remove=True):
            return False
        self._providers.pop(name, None)
        self._rebuild_fallback()
        logger.info(f"🗑️  已删除模型: {name}")
        return True

    def toggle_provider(self, name: str, enabled: bool) -> bool:
        """启用/禁用模型；禁用当前全局模型时自动切换到下一个可用。"""
        if name not in self._providers:
            logger.error(f"❌ 启停模型失败：{name} 不存在")
            return False
        enabled = bool(enabled)
        self._providers[name]["enabled"] = enabled
        if not self._update_config_provider(name, {"enabled": enabled}):
            return False
        self._rebuild_fallback()
        if not enabled and name == self._current_provider:
            first = next((n for n, c in self._providers.items() if c.get("enabled")), name)
            if first != name:
                logger.warning(f"⚠️ 当前模型 {name} 已禁用，自动切换到 {first}")
                self._current_provider = first
        logger.info(f"🔀 模型 {name} → {'启用' if enabled else '禁用'}")
        return True

    def discover_context_length(self, name: str) -> Optional[int]:
        """从 vLLM/OpenAI 兼容的 /models 接口自动发现模型上下文窗口（max_model_len）。

        探测成功后写回 dfecrab.json（原子写 + 备份）并热更新内存，一次探测持久化。

        Args:
            name: provider 名

        Returns:
            探测到的 context_length；失败返回 None。
        """
        cfg = self._providers.get(name)
        if not cfg:
            logger.error(f"❌ [Discover] 模型不存在: {name}")
            return None
        api_base = cfg.get("api_base", "")
        if not api_base:
            logger.warning(f"⚠️ [Discover] {name} 未配置 api_base")
            return None
        headers = {}
        if cfg.get("api_key") and cfg["api_key"] != "not-needed":
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        import httpx
        try:
            with httpx.Client(timeout=httpx.Timeout(5, connect=3.0), trust_env=False) as client:
                resp = client.get(f"{api_base}/models", headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"⚠️ [Discover] {name} /models HTTP {resp.status_code}")
                    return None
                data = resp.json()
                clen = None
                for item in (data.get("data", []) or []):
                    ml = item.get("max_model_len") or (item.get("meta") or {}).get("max_model_len")
                    if ml:
                        clen = int(ml)
                        break
                if not clen:
                    logger.warning(f"⚠️ [Discover] {name} /models 未返回 max_model_len（非 vLLM？）")
                    return None
                # 写回配置 + 热更新内存
                self._providers[name]["context_length"] = clen
                if not self._update_config_provider(name, {"context_length": clen}):
                    logger.warning(f"⚠️ [Discover] {name} 写回配置失败（内存已更新）")
                logger.info(f"🔍 [Discover] {name} 上下文窗口自动发现: {clen}")
                return clen
        except Exception as e:
            logger.warning(f"⚠️ [Discover] {name} 探测失败: {e}")
            return None


# 全局实例
model_manager = ModelManager.get_instance()
