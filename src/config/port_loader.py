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
    """知识库运行参数（切片 + 召回 + 入库 + 索引 + 问答）单一读取入口。

    优先读 gateway.yaml 顶层 knowledge 段；缺失项用内置默认值兜底。
    返回: {chunk_size, chunk_overlap, min_chunk_size, table_rows_per_chunk,
          qa_pair_keep, filter_overfetch, image_neighbor_radius,
          max_per_doc, retrieve_overfetch, keyword_search_mode, keyword_max_df_ratio,
          embed_batch_size, index_type, ivf_threshold, ivf_nlist, ivf_nprobe,
          qa_enable_thinking, qa_temperature, qa_top_k, qa_max_per_doc,
          qa_max_context_chunks}

    注：本函数是**多条链路共用**的单一入口 ——
        · 知识库入库/检索链路（image_neighbor_radius、filter_overfetch、
          keyword_*、index_type/ivf_*、embed_batch_size）
        · 知识库问答链路（qa_* 五参数，经 src/knowledge/llm/config_loader.py 装配）
    2026-09-14 合并：此前两方各持一份同名函数互相覆盖，现统一到这一份。
    """
    cfg: Dict = {
        # 切片
        "chunk_size": 450,
        "chunk_overlap": 90,
        "min_chunk_size": 50,
        "table_rows_per_chunk": 20,
        "qa_pair_keep": True,
        # 召回
        "filter_overfetch": 6,
        # 图片片不参与检索，靠「同文档内 ±N 片范围的正文命中后附带」被带出；
        # 0 = 关闭带图（只带命中片自身的图）。
        "image_neighbor_radius": 1,
        "max_per_doc": 2,
        "retrieve_overfetch": 4,
        "keyword_search_mode": "index",
        "keyword_max_df_ratio": 0.5,
        # 入库
        "embed_batch_size": 100,
        # 向量索引
        "index_type": "auto",
        "ivf_threshold": 500000,
        "ivf_nlist": 0,
        "ivf_nprobe": 16,
        # 问答生成参数（场景级）：qa_enable_thinking=None 表示不下发该字段（其他现场零影响）
        "qa_enable_thinking": None,
        "qa_temperature": 0.2,
        "qa_top_k": 5,
        "qa_max_per_doc": 2,
        "qa_max_context_chunks": 5,
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
                "table_rows_per_chunk", "filter_overfetch", "image_neighbor_radius",
                "max_per_doc", "retrieve_overfetch", "embed_batch_size",
                "ivf_threshold", "ivf_nlist", "ivf_nprobe",
                "qa_top_k", "qa_max_per_doc", "qa_max_context_chunks"):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            pass
    for key in ("keyword_max_df_ratio", "qa_temperature"):
        try:
            cfg[key] = float(cfg[key])
        except (TypeError, ValueError):
            pass
    cfg["qa_pair_keep"] = bool(cfg["qa_pair_keep"])
    # None 表示"不下发该字段"（未配置的现场零影响），其余按布尔规整
    if cfg["qa_enable_thinking"] is not None:
        cfg["qa_enable_thinking"] = bool(cfg["qa_enable_thinking"])
    # 模式串归一（大小写/空白容错）
    mode = str(cfg.get("keyword_search_mode") or "index").strip().lower()
    cfg["keyword_search_mode"] = mode if mode in ("index", "scan") else "index"
    itype = str(cfg.get("index_type") or "auto").strip().lower()
    cfg["index_type"] = itype if itype in ("auto", "flat", "ivf") else "auto"
    return cfg


# OCR 配置默认值（gateway.yaml 的 knowledge.ocr 段缺失时逐项兜底）
# ★ enabled 默认 False（2026-09-11 改，此前为 True）：现场反馈「用 OCR 文本做图片索引
#   效果不好」——界面截图 / SCADA 系统图里大部分文字与上下文无关，按检测框输出的
#   破碎文本命中率低、还把噪声引进检索；且 15 图的手册要跑半分钟。
#   现改为：图片只落盘给前端看，靠「邻近正文片被搜到时附带」被带出
#   （src/knowledge/core/neighbors.py）。
#   要开回来：环境变量 KNOWLEDGE_OCR_ENABLED=true，或 gateway.yaml 的
#   knowledge.ocr.enabled: true（引擎代码一行没删）。注意开了也只是进检索位，
#   不进正文，且图片片已不进索引——需一并把 neighbors 那套关掉才回到批次 19 行为。
_DEFAULT_OCR_CONFIG = {
    "enabled": False,
    "max_images": 50,
    "max_pages": 50,
    "min_image_px": 64,
    "pdf_text_threshold": 20,
    "dpi": 200,
}

# 需要按整数处理的键（yaml 里被写成字符串时做一次防御性转换）
_OCR_INT_KEYS = ("max_images", "max_pages", "min_image_px", "pdf_text_threshold", "dpi")


def knowledge_ocr(default: Optional[Dict] = None) -> Dict:
    """知识库 OCR 配置（gateway.yaml 顶层 knowledge.ocr 段）。

    返回**已合并默认值**的完整配置，调用方无需再逐个兜底：
        {
            "enabled": False,            # 总开关，默认关（见 _DEFAULT_OCR_CONFIG 注释）
            "max_images": 50,            # 单文档最多 OCR 图片数
            "max_pages": 50,             # 扫描版 PDF 最多 OCR 页数
            "min_image_px": 64,          # 小于该边长的图片跳过
            "pdf_text_threshold": 20,    # 页面文本少于该字数视为扫描页
            "dpi": 200,                  # 扫描页渲染精度
        }

    读取顺序（与既有函数同范式）：
        环境变量 KNOWLEDGE_OCR_ENABLED（仅覆盖总开关，便于不改编排地应急关闭）
        → gateway.yaml 的 knowledge.ocr 段
        → default（缺省用本模块内置默认值）

    说明：既有 knowledge_upload_max_mb 是「一 key 一函数」；OCR 有 6 个参数，
    逐个建函数过于啰嗦，故改为一个函数返回整段 dict（经权衡的偏离，仍只维护
    这一个读取器，不新增第三个 config reader）。
    """
    cfg: Dict = dict(_DEFAULT_OCR_CONFIG)
    if default:
        cfg.update(default)

    path = _find_project_root() / "config" / "gateway.yaml"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            section = (data.get("knowledge") or {}).get("ocr") or {}
            if isinstance(section, dict):
                cfg.update(section)
        except Exception:
            pass

    # 数值键防御性转换：yaml 里写成 "50" 之类的字符串也不至于让比较逻辑炸掉
    for key in _OCR_INT_KEYS:
        try:
            cfg[key] = int(cfg[key])
        except (KeyError, TypeError, ValueError):
            cfg[key] = int(_DEFAULT_OCR_CONFIG[key])

    # 总开关的环境变量覆盖
    env_val = os.environ.get("KNOWLEDGE_OCR_ENABLED")
    if env_val is not None:
        cfg["enabled"] = env_val.strip().lower() in ("1", "true", "yes", "on")

    cfg["enabled"] = bool(cfg.get("enabled", False))
    return cfg
