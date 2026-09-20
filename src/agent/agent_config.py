"""
AgentConfig — 统一 Agent 配置管理

替代散落在 grpc_server.py 各处的直接 open/read config.json，
提供 from_id() 统一读取入口，支持：
  - 全局默认配置（config/dfecrab.json 的 agent_defaults）
  - Agent 级覆盖（agents/{agent_id}/config.json）
  - 降级：config.json 缺失时返回全局默认，不报错

使用示例：
    from src.agent.agent_config import AgentConfig, list_agents

    cfg = AgentConfig.from_id("kunming")
    print(cfg.model_name)        # "Qwen3-14B-HGY"
    print(cfg.skills_whitelist)  # ["kunming_classifier", "kunming_api"]
    print(cfg.system_prompt)     # 从 config.json 读取

    all_agents = list_agents()   # ["dfecrab", "kunming", "manager_agent"]
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 项目根路径（与 config/dfecrab.json 的 directories 对齐）
# ──────────────────────────────────────────────────────────────

def _get_project_root() -> Path:
    """获取项目根目录"""
    # 向上找包含 config/dfecrab.json 的目录
    current = Path(__file__).resolve().parent.parent.parent  # src/agent → src → root
    return current


def _load_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """安全加载 JSON 文件，失败返回 None"""
    try:
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"[AgentConfig] 加载 JSON 失败: {file_path} — {e}")
        return None


# ──────────────────────────────────────────────────────────────
# 智能体 ID 兼容映射
# ──────────────────────────────────────────────────────────────

# 旧 ID → 新 ID 映射。当前迁移：default → dfecrab（默认智能体改名"东方电子小螃蟹"）。
_AGENT_ID_ALIASES = {
    "default": "dfecrab",
}


# 进程级"已告警"集合：同一旧 ID 只打印一次 deprecation 日志（C-1，防 default→dfecrab 刷屏）
_WARNED_AGENT_IDS = set()


def normalize_agent_id(agent_id: Optional[str]) -> Optional[str]:
    """将历史遗留的智能体 ID 归一化到当前 ID。

    用于兼容：已持久化的会话、旧 API 调用、ZK 服务类型等仍传 "default" 的场景，
    透明映射到 "dfecrab"，并打印一次 deprecation 日志，避免旧数据/旧调用因改名而失效。

    Args:
        agent_id: 原始智能体 ID（可能为 None）

    Returns:
        归一化后的智能体 ID（未命中映射或为 None 时原样返回）
    """
    if not agent_id:
        return agent_id
    mapped = _AGENT_ID_ALIASES.get(agent_id)
    if mapped is not None:
        # C-1：同进程内同一旧 ID 只告警一次，避免每次请求都打（缓存日志仅一次）
        if agent_id not in _WARNED_AGENT_IDS:
            _WARNED_AGENT_IDS.add(agent_id)
            logger.warning(
                f"[AgentConfig] 智能体 ID '{agent_id}' 已改名/迁移为 '{mapped}'，请更新调用方"
            )
        return mapped
    return agent_id


# ──────────────────────────────────────────────────────────────
# 全局默认配置
# ──────────────────────────────────────────────────────────────

_DEFAULT_CONFIG = {
    "model_name": "Qwen3-14B-HGY",
    "max_iterations": 3,
    "llm_timeout": 180,
    "tool_choice": "auto",
}


def _get_global_defaults() -> Dict[str, Any]:
    """从 config/dfecrab.json 读取全局默认配置"""
    root = _get_project_root()
    cfg_file = root / "config" / "dfecrab.json"
    data = _load_json(cfg_file)
    if data and "agent_defaults" in data:
        defaults = dict(_DEFAULT_CONFIG)
        defaults.update(data["agent_defaults"])
        return defaults
    return dict(_DEFAULT_CONFIG)


def _apply_tools_json(merged: Dict[str, Any], root: Path, agent_id: str) -> None:
    """读取 agents/{agent_id}/tools.json，覆盖 enabled_skills

    MCP 已迁移为"MCP 为中心"（绑定写在服务配置 bound_agents），
    agent 侧不再保存 enabled_mcp_servers / mcp_tools_whitelist。
    """
    tools_data = _load_json(root / "agents" / agent_id / "tools.json") or {}
    if tools_data.get("enabled_skills") is not None:
        merged["skills_whitelist"] = tools_data["enabled_skills"]


# ──────────────────────────────────────────────────────────────
# AgentConfig
# ──────────────────────────────────────────────────────────────

@dataclass
class AgentConfig:
    """Agent 配置（从 agents/{agent_id}/config.json 读取，合并全局默认）"""

    agent_id: str

    # ── LLM ──
    model_name: str = "Qwen3-14B-HGY"      # 项目硬约束：LLM 必须用此模型名

    # ── 技能 ──
    skills_whitelist: Optional[List[str]] = None
    # None  = 加载全部技能
    # []    = 不加载任何技能
    # ["dm_query", "kunming_api"] = 只加载指定技能
    # ⚠ deprecated：config.json 写法，优先级低于 tools.json/enabled_skills

    # ── 提示 ──
    system_prompt: str = ""

    # ── 行为 ──
    max_iterations: int = 3
    llm_timeout: int = 180  # ★ 单轮 LLM 调用超时（秒）；agent 级 config.json 可覆盖
    tool_choice: str = "auto"  # auto / required / none

    # ── 元信息（非配置，纯展示用） ──
    name: str = ""
    agent_type: str = "default"
    parent_agent: Optional[str] = None
    keywords: List[str] = field(default_factory=list)

    # ── 原始数据（调试用） ──
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    # ══════════════════════════════════════════════════════════
    # 工厂方法
    # ══════════════════════════════════════════════════════════

    @classmethod
    def from_id(cls, agent_id: str) -> "AgentConfig":
        """从 agents/{agent_id}/config.json 读取，合并全局默认配置

        合并规则：
          1. 读取 config/dfecrab.json 的 agent_defaults → 全局默认
          2. 读取 agents/{agent_id}/config.json → agent 级覆盖
          3. agent 级字段优先（只有 agent 级未设置的字段才用全局默认）

        降级策略：
          - config.json 不存在 → 返回全局默认配置（不报错）
          - 字段缺失 → 用全局默认填充
          - skills_whitelist 拼错工具名 → 日志告警，仍返回（不因配置错误导致无工具）

        Args:
            agent_id: Agent 唯一标识

        Returns:
            AgentConfig 实例
        """
        # 0. 兼容映射（default → dfecrab），避免旧 ID 失效
        agent_id = normalize_agent_id(agent_id) or "dfecrab"

        # 1. 全局默认
        global_defaults = _get_global_defaults()

        # 2. agent 级配置
        root = _get_project_root()
        agent_cfg_file = root / "agents" / agent_id / "config.json"
        agent_data = _load_json(agent_cfg_file)

        if agent_data is None:
            # 降级：config.json 不存在，返回全局默认
            logger.info(
                f"[AgentConfig] {agent_id}/config.json 不存在，使用全局默认"
            )
            # 仍读取 tools.json（enabled_skills 为 UI 勾选落盘源）
            merged = dict(global_defaults)
            _apply_tools_json(merged, root, agent_id)
            return cls(
                agent_id=agent_id,
                model_name=merged.get("model_name", "Qwen3-14B-HGY"),
                skills_whitelist=merged.get("skills_whitelist"),
                max_iterations=merged.get("max_iterations", 3),
                llm_timeout=merged.get("llm_timeout", 180),
                tool_choice=merged.get("tool_choice", "auto"),
                system_prompt="",
                _raw={"source": "global_defaults"},
            )

        # 3. 合并：agent 级覆盖全局默认
        merged = dict(global_defaults)
        # 只合并已知字段，避免污染
        for key in (
            "model_name", "skills_whitelist",
            "system_prompt", "max_iterations", "llm_timeout", "tool_choice"
        ):
            if key in agent_data and agent_data[key] is not None:
                merged[key] = agent_data[key]

        # 3.5 tools.json 覆盖（最高优先级，UI 勾选落盘源）
        _apply_tools_json(merged, root, agent_id)

        # 4. 验证 skills_whitelist
        skills = merged.get("skills_whitelist")
        if isinstance(skills, list) and len(skills) > 0:
            logger.debug(
                f"[AgentConfig] {agent_id} skills_whitelist: {skills}"
            )
        elif skills == []:
            logger.info(f"[AgentConfig] {agent_id} skills_whitelist=[], 不加载任何技能")

        # 5. 构建实例
        return cls(
            agent_id=agent_id,
            model_name=merged.get("model_name", "Qwen3-14B-HGY"),
            skills_whitelist=merged.get("skills_whitelist"),
            system_prompt=merged.get("system_prompt", ""),
            max_iterations=merged.get("max_iterations", 3),
            llm_timeout=merged.get("llm_timeout", 180),
            tool_choice=merged.get("tool_choice", "auto"),
            # 元信息（纯展示）
            name=agent_data.get("name", ""),
            agent_type=agent_data.get("agent_type", "default"),
            parent_agent=agent_data.get("parent_agent"),
            keywords=agent_data.get("keywords", []),
            _raw=agent_data,
        )

    @classmethod
    def list_agents(cls) -> List[str]:
        """列出所有可用 agent_id

        扫描 agents/ 目录下所有含 config.json 的子目录。

        Returns:
            list[str]: agent_id 列表，如 ["dfecrab", "kunming", "manager_agent"]
        """
        root = _get_project_root()
        agents_dir = root / "agents"

        if not agents_dir.exists():
            logger.warning(f"[AgentConfig] agents 目录不存在: {agents_dir}")
            return []

        agent_ids = []
        for item in sorted(agents_dir.iterdir()):
            if item.is_dir() and (item / "config.json").exists():
                agent_ids.append(item.name)

        logger.debug(f"[AgentConfig] 发现 {len(agent_ids)} 个 agent: {agent_ids}")
        return agent_ids

    # ══════════════════════════════════════════════════════════
    # 便捷方法
    # ══════════════════════════════════════════════════════════

    def has_skills(self) -> bool:
        """是否有可用技能（whitelist 非空列表 或 None=全量）"""
        return self.skills_whitelist is None or len(self.skills_whitelist) > 0

    def is_tool_required(self) -> bool:
        """是否强制调工具"""
        return self.tool_choice == "required"

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（不含 _raw）"""
        return {
            "agent_id": self.agent_id,
            "model_name": self.model_name,
            "skills_whitelist": self.skills_whitelist,
            "system_prompt": self.system_prompt[:100] + "..." if len(self.system_prompt) > 100 else self.system_prompt,
            "max_iterations": self.max_iterations,
            "tool_choice": self.tool_choice,
            "name": self.name,
            "agent_type": self.agent_type,
            "parent_agent": self.parent_agent,
        }


# ──────────────────────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────────────────────

_default_config: Optional[AgentConfig] = None


def get_agent_config(agent_id: str = "dfecrab") -> AgentConfig:
    """获取 AgentConfig（便捷函数，带缓存）

    Args:
        agent_id: Agent ID

    Returns:
        AgentConfig 实例
    """
    # 简单实现：每次都重新读取（确保配置热更新）
    # 如需缓存，后续可加 TTL 缓存
    return AgentConfig.from_id(agent_id)


# ──────────────────────────────────────────────────────────────
# 便捷函数（与 grpc_server.py 现有方法兼容）
# ──────────────────────────────────────────────────────────────

def list_agents() -> List[str]:
    """列出所有可用 agent_id（与 AgentConfig.list_agents() 等效）"""
    return AgentConfig.list_agents()
