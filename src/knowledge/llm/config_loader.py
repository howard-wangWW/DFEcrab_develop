# src/knowledge/llm/config_loader.py
"""知识库问答配置装配（模型级 + 场景级单一入口）

供两条链路共用，避免各读一份配置导致口径漂移（参考成熟平台的"节点级配置装配"）：
- 知识库服务链路：scripts/knowledge_api.py → KnowledgeService → KnowledgeQASkill
- 技能链路：skills/knowledge_qa、skills/knowledge_search（网关进程内加载）

配置来源（均为单一事实源）：
- 模型级：config/dfecrab.json 第一个 enabled 的 model_providers
  （api_base / model_name / max_tokens / enable_thinking）
- 场景级：config/gateway.yaml 的 knowledge.qa_*
  （qa_temperature / qa_top_k / qa_max_per_doc / qa_max_context_chunks / qa_enable_thinking）
"""
import json
import logging
from typing import Dict, Optional

from ..paths import LLM_CONFIG_FILE
from src.utils.api_base import normalize_api_base

logger = logging.getLogger(__name__)


def load_llm_config() -> Optional[Dict]:
    """模型级配置：config/dfecrab.json 第一个 enabled 且 api_base 非空的 provider

    路径锚定项目根（LLM_CONFIG_FILE），避免因启动目录不同静默降级为本地拼接。
    """
    try:
        if not LLM_CONFIG_FILE.exists():
            return None
        data = json.loads(LLM_CONFIG_FILE.read_text(encoding="utf-8"))
        for pc in data.get("model_providers", {}).values():
            if pc.get("enabled") and pc.get("api_base"):
                return {
                    # ★ 统一清洗：直接读文件绕过了 ModelManager，这里兜底剥完整接口地址
                    "api_base": normalize_api_base(pc.get("api_base", "")),
                    "model_name": pc.get("model_name", ""),
                    "api_key": pc.get("api_key", "not-needed"),
                    "timeout": pc.get("timeout", 300),
                    # ★ 模型级：生成上限 + 思考开关（未配置则不下发，其他现场零影响）
                    "max_tokens": pc.get("max_tokens", 4096),
                    "enable_thinking": pc.get("enable_thinking"),
                }
    except Exception as e:
        logger.warning(f"读取模型配置失败: {e}")
    return None


def _chunk_config() -> Dict:
    """知识库运行参数（gateway.yaml → knowledge 段），读取失败返回空字典

    两种导入形态都试（项目里并存）：服务进程与 scripts/knowledge_api.py 会把
    「项目根/src」塞进 sys.path，用 config.*；install.sh 自检、部分独立脚本
    只塞项目根，那就要走 src.config.*。**少试一种会在那些入口静默退回内置默认值**
    （值恰好相同，所以不报错、只是现场在 gateway.yaml 里的覆盖不生效）。
    """
    err: Optional[Exception] = None
    for mod_name in ("config.port_loader", "src.config.port_loader"):
        try:
            mod = __import__(mod_name, fromlist=["knowledge_chunk_config"])
            return mod.knowledge_chunk_config() or {}
        except Exception as e:
            err = e
    logger.warning(f"读取知识库运行参数失败（使用内置默认值）: {err}")
    return {}


def load_retrieval_config() -> Dict:
    """场景级检索参数（纯检索技能与问答技能共用）"""
    cc = _chunk_config()
    return {
        "top_k": cc.get("qa_top_k", 5),
        "max_per_doc": cc.get("qa_max_per_doc", 2),
        "max_context_chunks": cc.get("qa_max_context_chunks", 5),
        "filter_overfetch": cc.get("filter_overfetch", 6),
    }


def load_skill_config() -> Dict:
    """KnowledgeQASkill 完整配置 = 场景级检索参数 + 模型级 + 场景级生成参数覆盖

    思考开关优先级：qa_enable_thinking > provider.enable_thinking > 不下发该字段。
    """
    cfg = load_retrieval_config()
    llm_config = load_llm_config()
    if llm_config:
        cc = _chunk_config()
        # ★ 场景级覆盖模型级：知识库问答可独立关思考（None 时沿用 provider 配置）
        if cc.get("qa_enable_thinking") is not None:
            llm_config["enable_thinking"] = bool(cc["qa_enable_thinking"])
        llm_config["temperature"] = cc.get("qa_temperature", 0.2)
        cfg["llm"] = llm_config
    return cfg
