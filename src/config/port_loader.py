"""
本地端口统一读取模块（单一事实源）

所有本地服务端口从 config/gateway.yaml 的 local_ports 段读取，
避免各脚本散落硬编码端口导致漂移（如 8602/8603 不一致问题）。

用法:
    from config.port_loader import load_local_ports, mcp_port, knowledge_api_port

    ports = load_local_ports()          # {'knowledge_api': 6788, 'mcp': {...}}
    p = mcp_port("demo")                 # 8600
    k = knowledge_api_port()             # 6788

模块会自动定位项目根目录（包含 config/gateway.yaml 的目录），
脚本单独运行或在 dfecrab 下调用均可。

注意：本文件位于 src/config/ 下（真正的 Python 包目录）。
脚本若单独运行，需确保 sys.path 中包含项目根目录或项目根/src，
否则 `from config.port_loader import ...` 会解析失败。
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Optional


def _find_project_root() -> Path:
    """自动定位项目根目录（包含 config/gateway.yaml 的目录）"""
    current = Path(__file__).resolve().parent.parent  # src/config -> src
    for parent in [current] + list(current.parents):
        if (parent / "config" / "gateway.yaml").exists():
            return parent
    return current


def load_local_ports(config_path: Optional[str] = None) -> Dict:
    """读取 gateway.yaml 的 local_ports 段。

    返回结构：
        {
            "knowledge_api": 6788,
            "mcp": {"demo": 8600, "alert_judge_tools": 8601, "blackxml_topology": 8602},
        }
    若文件不存在或无 local_ports 段，返回 {}。
    """
    if config_path:
        path = Path(config_path)
    else:
        path = _find_project_root() / "config" / "gateway.yaml"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("local_ports", {}) or {}
    except Exception:
        return {}


def mcp_port(name: str, default: Optional[int] = None) -> Optional[int]:
    """获取指定本地 MCP 服务端口。

    - 优先读环境变量 MCP_PORT（支持启动时覆盖）
    - 其次读 gateway.yaml 的 local_ports.mcp.<name>
    - 兜底返回 default
    """
    env_port = os.environ.get("MCP_PORT")
    if env_port is not None:
        try:
            return int(env_port)
        except ValueError:
            pass
    ports = load_local_ports().get("mcp", {}) or {}
    port = ports.get(name)
    if port is not None:
        return int(port)
    return default


def knowledge_api_port(default: int = 6788) -> int:
    """获取知识库 API 端口（默认 6788）。"""
    env_port = os.environ.get("KNOWLEDGE_API_PORT")
    if env_port is not None:
        try:
            return int(env_port)
        except ValueError:
            pass
    port = load_local_ports().get("knowledge_api")
    if port is not None:
        return int(port)
    return default


def knowledge_upload_max_mb(default: int = 50) -> int:
    """知识库单文件上传上限(MB)。

    优先读环境变量 KNOWLEDGE_UPLOAD_MAX_MB，其次 gateway.yaml 顶层
    knowledge.upload_max_mb，兜底 default（默认 50MB，参考成熟平台可配置上限设计）。
    """
    env_val = os.environ.get("KNOWLEDGE_UPLOAD_MAX_MB")
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            pass
    path = _find_project_root() / "config" / "gateway.yaml"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            mb = (data.get("knowledge") or {}).get("upload_max_mb")
            if mb is not None:
                return int(mb)
        except Exception:
            pass
    return default


def knowledge_chunk_config(default: Optional[Dict] = None) -> Dict:
    """知识库运行参数（切片 + 召回）单一读取入口。

    优先读 gateway.yaml 顶层 knowledge 段；缺失项用内置默认值兜底。
    返回: {chunk_size, chunk_overlap, min_chunk_size, table_rows_per_chunk,
           qa_pair_keep, filter_overfetch}
    """
    cfg: Dict = {
        "chunk_size": 450,
        "chunk_overlap": 90,
        "min_chunk_size": 50,
        "table_rows_per_chunk": 20,
        "qa_pair_keep": True,
        "filter_overfetch": 6,
    }
    if default:
        cfg.update(default)

    path = _find_project_root() / "config" / "gateway.yaml"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            kn = data.get("knowledge") or {}
            for key in list(cfg.keys()):
                if kn.get(key) is not None:
                    cfg[key] = kn[key]
        except Exception:
            pass

    # 类型规整（防止 YAML 写成字符串等）
    for key in ("chunk_size", "chunk_overlap", "min_chunk_size",
                "table_rows_per_chunk", "filter_overfetch"):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            pass
    cfg["qa_pair_keep"] = bool(cfg["qa_pair_keep"])
    return cfg
