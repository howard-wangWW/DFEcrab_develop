"""
DFEcrab 电网运维智能助手
多智能体协同系统，支持电网调度、故障分析和智能决策。
"""

__version__ = "4.0.0"
__author__ = "DFEcrab Team"

from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 配置目录
CONFIG_DIR = PROJECT_ROOT / "config"


def get_project_path(*paths: str) -> Path:
    """获取项目内指定路径"""
    return PROJECT_ROOT.joinpath(*paths)


def get_data_path(*paths: str) -> Path:
    """获取数据目录路径"""
    return PROJECT_ROOT / "data" / Path(*paths)


def get_config_path(*paths: str) -> Path:
    """获取配置目录路径"""
    return CONFIG_DIR / Path(*paths)


def get_plugins_path(*paths: str) -> Path:
    """获取插件目录路径"""
    return PROJECT_ROOT / "plugins" / Path(*paths)


def get_skills_path(*paths: str) -> Path:
    """获取技能目录路径"""
    return PROJECT_ROOT / "skills" / Path(*paths)


def get_agents_path(*paths: str) -> Path:
    """获取 Agent 目录路径"""
    return PROJECT_ROOT / "agents" / Path(*paths)


__all__ = [
    "__version__",
    "PROJECT_ROOT",
    "CONFIG_DIR",
    "get_project_path",
    "get_data_path",
    "get_config_path",
    "get_plugins_path",
    "get_skills_path",
    "get_agents_path",
]