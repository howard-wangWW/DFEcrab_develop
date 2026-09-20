"""
app_config.py - config/dfecrab.json 运行时配置单点加载

收敛目标（步骤6）：本仓库所有模块读取 dfecrab.json 应统一经本模块，替换
「各自 import 时 json.load + 各自 try/except 默认值」的散落写法，避免同一文件被反复读。

设计约定：
  1. 唯一真实来源：{PROJECT_ROOT}/config/dfecrab.json（路径锚定，消除 CWD 依赖）；
  2. 模块首次访问时读取一次并缓存；运行期热更由 model_manager 写回文件后调用 reload_dfecrab()；
  3. 以 "_" 开头的键（如 react._note / mcp._note）是给维护者的说明注释，_clean() 自动剔除，
     调用方永远拿不到（JSON 标准不支持行尾注释，用下划线前缀键承载说明，解析仍为纯 JSON）；
  4. 本模块只依赖标准库，任何环境下导入都不抛异常（读失败返回空配置，调用方自行兜底）。

用法：
    from src.config.app_config import get_dfecrab, section, reload_dfecrab
    react_cfg = section("react")          # {} 不存在时为 {}
    raw = get_dfecrab()                   # 已剔除 "_" 说明键的运行时视图
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH: Path = _PROJECT_ROOT / "config" / "dfecrab.json"

_lock = threading.Lock()
_CACHE: Optional[Dict[str, Any]] = None


def _load() -> Dict[str, Any]:
    """从磁盘读取 dfecrab.json；失败返回空配置（调用方自行兜底），不抛异常。"""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
            return json.load(_f)
    except Exception:
        logger.warning("app_config: %s 读取/解析失败，返回空配置", _CONFIG_PATH)
        return {}


def _clean(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """递归剔除 "_" 前缀的维护说明键，返回运行时视图副本（不污染缓存）。"""
    out: Dict[str, Any] = {}
    for _k, _v in cfg.items():
        if isinstance(_k, str) and _k.startswith("_"):
            continue
        out[_k] = _clean(_v) if isinstance(_v, dict) else _v
    return out


def get_dfecrab_raw() -> Dict[str, Any]:
    """原始缓存（含 _note 等说明键），仅供需要原始结构的内部使用。"""
    global _CACHE
    if _CACHE is None:
        with _lock:
            if _CACHE is None:
                _CACHE = _load()
    return _CACHE


def get_dfecrab() -> Dict[str, Any]:
    """运行时配置视图（已剔除 '_' 说明键）。"""
    return _clean(get_dfecrab_raw())


def section(name: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """取顶层某段（如 react / mcp / model_providers）；缺失返回 default 或空 dict。"""
    cfg = get_dfecrab()
    _v = cfg.get(name)
    if isinstance(_v, dict):
        return _v
    return dict(default) if default else {}


def reload_dfecrab() -> None:
    """配置写回文件后调用，刷新进程内缓存（幂等）。"""
    global _CACHE
    with _lock:
        _CACHE = _load()


def update_section(name: str, data: Dict[str, Any]) -> None:
    """覆写 dfecrab.json 顶层某段并落盘 + 刷新进程内缓存。

    写入口统一收敛在本模块：新增/修改运行期配置段（如 default_agent）都走这里，
    避免各 handler 自行 open/json 散落读写导致与缓存不同步。

    Args:
        name: 顶层段名，如 "default_agent"（不存在时自动新增）
        data: 段内容；需保留维护说明时含 "_note" 键（读侧 _clean 会剔除）

    Raises:
        写盘失败时抛原始异常，并自动恢复内存缓存为磁盘现状。
    """
    raw = dict(get_dfecrab_raw())  # 浅拷贝：仅新增/替换顶层段，不动其它段对象
    raw[name] = data
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as _f:
            json.dump(raw, _f, ensure_ascii=False, indent=2)
    except Exception:
        reload_dfecrab()  # 写盘失败：内存回滚为磁盘现状，避免脏缓存
        raise
    reload_dfecrab()


if __name__ == "__main__":
    # 冒烟：python -m src.config.app_config
    import json as _json
    print("project_root =", _PROJECT_ROOT)
    print("config_path  =", _CONFIG_PATH)
    print("react keys   =", sorted(get_dfecrab().get("react", {}).keys()))
    print("mcp keys     =", sorted(get_dfecrab().get("mcp", {}).keys()))
