"""
内置参数提取器集合（ParamGuard 兜底修复的站点实现）。

核心 param_guard 不感知任何站点业务；本包按站点/技能注册确定性提取逻辑：
    - kunming：昆明配网分类 + 时间/人名/局名提取（弱模型参数兜底）

新增站点时，在此目录加一个模块并在下方 import 注册即可，核心代码零改动。
"""

try:
    from src.skill.extractors import kunming  # noqa: F401
except Exception:  # pragma: no cover - 单站点缺失不应影响核心
    import logging as _logging
    _logging.getLogger("dfecrab.react").warning(
        "[ParamGuard] kunming 提取器加载失败（昆明参数兜底将不可用）", exc_info=True
    )
