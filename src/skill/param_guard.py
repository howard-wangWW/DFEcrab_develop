"""
param_guard.py - 工具参数护栏（弱模型参数填充兜底）

背景：
    小参数量模型（如现场 qwen3_a3b）function calling 的"机械能力"可用（能按 schema
    产出 tool_call），但"参数填充"不可靠——枚举瞎填（endpoint='tiaozha'）、日期算错
    （今日 → 2023-04-10）、必填缺失。本模块在工具执行前做一次纯规则校验，发现错误时
    用【代码提取】兜底修复：能从用户原话确定性推导出的参数（分类 / 时间 / 人名 / 局名）
    由代码补齐，模型本来填对的字段原样保留。

设计原则：
    - 模型填充优先：参数全过 → 零干预（强模型现场几乎不触发修复）
    - 代码兜底修复：仅对"校验不通过 + 代码能推导"的字段动手
    - 修不了就放行：维持工具自身错误提示 / 模型重试的既有行为
    - 修复率 = 模型能力仪表盘：日志可观测，换模型免改码

扩展方式：
    - 内置提取器：src/skill/extractors/<site>.py 调用 register_extractor 注册
    - 技能自带提取器：<技能目录>/param_extractor.py 暴露
      extract(tool_name, args, ctx) -> {"invalid": [...], "repair": {path: value}}

提取器契约：
    extract(tool_name: str, args: dict, ctx: dict) -> dict
        invalid: 校验不通过的字段路径列表（支持 "params.startTime" 点号路径）
        repair:  修复候选值 {字段路径: 值}
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("dfecrab.react")

# 工具名 → 提取器
_EXTRACTORS: Dict[str, Callable] = {}
_BUILTIN_LOADED = False
_ENABLED: Optional[bool] = None
# 技能自带提取器缓存（tool_name → extract 或 None）
_SKILL_EXTRACTOR_CACHE: Dict[str, Optional[Callable]] = {}


def register_extractor(tool_name: str, fn: Callable) -> None:
    """注册字段提取器（内置提取器/站点扩展调用）。"""
    if tool_name and callable(fn):
        _EXTRACTORS[tool_name] = fn


def _is_enabled() -> bool:
    """总开关：react.param_guard（缺省开启）。"""
    global _ENABLED
    if _ENABLED is None:
        try:
            from src.config.app_config import get_dfecrab
            _cfg = (get_dfecrab() or {}).get("react") or {}
            _ENABLED = bool(_cfg.get("param_guard", True))
        except Exception:
            _ENABLED = True
    return bool(_ENABLED)


def _ensure_builtin_extractors() -> None:
    """懒加载内置提取器集合（触发站点模块的 register_extractor）。"""
    global _BUILTIN_LOADED
    if _BUILTIN_LOADED:
        return
    _BUILTIN_LOADED = True
    try:
        from src.skill import extractors  # noqa: F401
    except Exception as e:
        logger.warning(f"[ParamGuard] 内置提取器加载失败（跳过兜底修复）: {e}")


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_path(obj: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _short(data: Dict[str, Any], limit: int = 200) -> str:
    try:
        text = str(data)
    except Exception:
        text = "<unprintable>"
    return text[:limit]


def _schema_required(tool_name: str, registry: Any = None) -> List[str]:
    """从工具 schema 读取 required 字段（registry 缺省走全局单例）。"""
    try:
        if registry is None:
            from src.skill.registry import get_tool_registry
            registry = get_tool_registry()
        info = registry.get_tool_info(tool_name) or {}
        params = info.get("parameters") or {}
        req = params.get("required") or []
        return [str(x) for x in req] if isinstance(req, list) else []
    except Exception:
        return []


def _skill_local_extractor(tool_name: str, registry: Any = None) -> Optional[Callable]:
    """技能自带参数提取器：<技能目录>/param_extractor.py 的 extract 函数（可选件）。"""
    if tool_name in _SKILL_EXTRACTOR_CACHE:
        return _SKILL_EXTRACTOR_CACHE[tool_name]
    fn: Optional[Callable] = None
    try:
        if registry is not None:
            info = registry.get_tool_info(tool_name) or {}
            skill_dir = info.get("skill_dir")
            if skill_dir:
                path = Path(skill_dir) / "param_extractor.py"
                if path.exists():
                    import importlib.util
                    import sys
                    mod_name = f"skills.{Path(skill_dir).name}.param_extractor"
                    spec = importlib.util.spec_from_file_location(mod_name, path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[mod_name] = module
                        spec.loader.exec_module(module)
                        _fn = getattr(module, "extract", None)
                        if callable(_fn):
                            fn = _fn
    except Exception as e:
        logger.warning(f"[ParamGuard] 技能自带提取器加载失败: tool={tool_name} err={e}")
    _SKILL_EXTRACTOR_CACHE[tool_name] = fn
    return fn


def validate_and_repair(
    tool_name: str,
    args: Dict[str, Any],
    ctx: Optional[Dict[str, Any]] = None,
    registry: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """工具执行前的参数校验 + 代码兜底修复。

    Args:
        tool_name: 工具名
        args:      模型产出的参数（原地修复）
        ctx:       上下文（至少含 user_message；可含 agent_id / session_id）
        registry:  ToolRegistry（缺省走全局单例）

    Returns:
        (args, info)：args 为（可能被修复的）参数；info 为空 dict 表示未干预，
        否则含 {"invalid": [...], "repaired": [...], "before": {...}}
    """
    if not isinstance(args, dict) or not _is_enabled():
        return args, {}

    ctx = ctx or {}
    try:
        _ensure_builtin_extractors()

        invalid: List[str] = []
        for field in _schema_required(tool_name, registry):
            if field not in invalid and _is_empty(args.get(field)):
                invalid.append(field)

        extractor = _EXTRACTORS.get(tool_name) or _skill_local_extractor(tool_name, registry)
        repair: Dict[str, Any] = {}
        if extractor:
            try:
                res = extractor(tool_name, dict(args), ctx) or {}
                for path in (res.get("invalid") or []):
                    if path not in invalid:
                        invalid.append(path)
                repair = res.get("repair") or {}
            except Exception as e:
                logger.warning(f"[ParamGuard] 提取器异常（跳过修复）: tool={tool_name} err={e}")

        if not invalid:
            return args, {}

        before = {p: _get_path(args, p) for p in invalid}
        repaired: List[str] = []
        for path in invalid:
            if path in repair and not _is_empty(repair[path]):
                _set_path(args, path, repair[path])
                repaired.append(path)

        if not repaired:
            # 校验不通过但代码也修不了 → 放行原参数（维持工具自身错误提示）
            return args, {}

        info = {"invalid": invalid, "repaired": repaired, "before": before}
        after = {p: _get_path(args, p) for p in repaired}
        logger.warning(
            f"[ParamGuard] 参数修复 | tool={tool_name} | 无效={invalid} | 已修复={repaired} | "
            f"修复前={_short(before)} | 修复后={_short(after)}"
        )
        return args, info
    except Exception as e:
        logger.warning(f"[ParamGuard] 校验异常，放行原参数: tool={tool_name} err={e}")
        return args, {}
