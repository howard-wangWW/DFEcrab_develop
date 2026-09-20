"""
知识库问答技能 - 包装 src.knowledge.skills.knowledge_qa.KnowledgeQASkill
"""
import argparse
import json
import sys
from pathlib import Path

# 确保项目根在 sys.path 中，使 `src.knowledge.*` 可被导入（无论启动工作目录在哪）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.knowledge.skills.knowledge_qa import KnowledgeQASkill, SKILL_METADATA


def _load_llm_config() -> dict | None:
    """从 config/dfecrab.json 读取第一个 enabled 的 model provider（与 knowledge_service 保持一致）"""
    import json
    cfg_file = Path("config/dfecrab.json")
    if not cfg_file.exists():
        return None
    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
        for pc in data.get("model_providers", {}).values():
            if pc.get("enabled") and pc.get("api_base"):
                return {
                    "api_base": pc.get("api_base", ""),
                    "model_name": pc.get("model_name", ""),
                    "api_key": pc.get("api_key", "not-needed"),
                    "timeout": pc.get("timeout", 300),
                }
    except Exception:
        return None
    return None


_llm_config = _load_llm_config()
_skill = KnowledgeQASkill({"llm": _llm_config} if _llm_config else None)


def execute(question: str = "", top_k: int = 5, **kwargs):
    return _skill.execute(question=question, top_k=top_k, **kwargs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    result = execute(question=args.question, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, default=str))
