"""
知识库检索技能 - 包装 src.knowledge.skills.knowledge_search.KnowledgeSearchSkill
"""
import argparse
import json
import sys
from pathlib import Path

# 确保项目根在 sys.path 中，使 `src.knowledge.*` 可被导入（无论启动工作目录在哪）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.knowledge.skills.knowledge_search import KnowledgeSearchSkill, SKILL_METADATA

_skill = KnowledgeSearchSkill()


def execute(query: str = "", top_k: int = 5,
            category: str = None, knowledge_base: str = None, **kwargs):
    return _skill.execute(query=query, top_k=top_k,
                          category=category, knowledge_base=knowledge_base, **kwargs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--category", default=None)
    parser.add_argument("--knowledge-base", default=None)
    args = parser.parse_args()
    result = execute(query=args.query, top_k=args.top_k,
                     category=args.category, knowledge_base=args.knowledge_base)
    print(json.dumps(result, ensure_ascii=False, default=str))
