# scripts/knowledge_health_check.py
#!/usr/bin/env python3
"""
知识库健康检查
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 运行时依赖守卫：本脚本依赖 venv 内的 jieba/faiss/numpy
from src.knowledge.paths import require_runtime_deps
require_runtime_deps()

from src.knowledge.storage.document_repo import DocumentRepository
from src.knowledge.embedding.local_embedder import LocalEmbedder
from src.knowledge.core.vector_store import VectorStore
import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def _read_index_dim(index_dir: Path) -> int:
    """从索引目录读取向量维度"""
    # 优先从 config.json 读取
    config_file = index_dir / "config.json"
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return config.get("dim", 300)
        except Exception:
            pass

    # 从 metadata.pkl 读取
    metadata_file = index_dir / "metadata.pkl"
    if metadata_file.exists():
        try:
            import pickle
            with open(metadata_file, 'rb') as f:
                data = pickle.load(f)
                return data.get("dim", 300)
        except Exception:
            pass

    # 从 FAISS 索引读取
    import faiss
    index_file = index_dir / "index.faiss"
    if index_file.exists():
        try:
            index = faiss.read_index(str(index_file))
            return index.d
        except Exception:
            pass

    return 300  # 默认 TF-IDF 维度


def check_knowledge_base():
    """检查知识库状态"""
    print("\n" + "=" * 60)
    print("📊 知识库健康检查")
    print("=" * 60)

    # 1. 检查目录结构
    print("\n📁 目录结构检查:")
    repo = DocumentRepository()
    dirs = [
        ("documents", repo.documents_dir),
        ("processed", repo.processed_dir),
        ("index", repo.index_dir),
        ("cache", repo.cache_dir),
        ("config", repo.config_dir),
    ]
    for name, path in dirs:
        status = "✅" if path.exists() else "❌"
        print(f"  {status} {name}: {path}")

    # 2. 检查文档
    print("\n📄 文档统计:")
    stats = repo.get_stats()
    print(f"  📄 文档总数: {stats['total_documents']}")
    print(f"  📦 切片总数: {stats['total_chunks']}")
    print(f"  📂 分类: {stats['by_category']}")
    print(f"  📌 状态: {stats['by_status']}")

    # 3. 检查向量索引
    print("\n🗂️ 向量索引检查:")
    index_dir = repo.index_dir
    if index_dir.exists():
        index_file = index_dir / "index.faiss"
        if index_file.exists():
            try:
                dim = _read_index_dim(index_dir)
                vector_store = VectorStore(dim=dim)
                vector_store.load(str(index_dir))
                print(f"  ✅ 索引文件存在: {index_file}")
                print(f"  📐 向量维度: {dim}")
                print(f"  📊 索引记录数: {len(vector_store.chunk_ids)}")
            except Exception as e:
                print(f"  ❌ 索引加载失败: {e}")
        else:
            print(f"  ❌ 索引文件不存在: {index_file}")
    else:
        print(f"  ❌ 索引目录不存在: {index_dir}")

    # 4. 检查嵌入模型（自动降级：有 sentence-transformers 用 BGE，没有用 TF-IDF）
    print("\n🤖 嵌入模型检查:")
    try:
        embedder = LocalEmbedder()
        test_emb = embedder.embed(["测试文本"])
        model_info = embedder.get_model_info()
        print(f"  ✅ 模型加载成功")
        print(f"  📐 向量维度: {len(test_emb[0])}")
        print(f"  📦 模式: {'ML模型' if model_info['use_ml_model'] else 'TF-IDF分词'}")
        if model_info['use_ml_model']:
            print(f"  🏷️ 模型名: {model_info['model_name']}")
    except Exception as e:
        print(f"  ❌ 模型加载失败: {e}")

    # 5. 测试检索
    print("\n🔍 检索测试:")
    try:
        if index_dir.exists() and (index_dir / "index.faiss").exists():
            embedder = LocalEmbedder()
            dim = _read_index_dim(index_dir)
            vector_store = VectorStore(dim=dim)
            vector_store.load(str(index_dir))

            query = "倒闸操作"
            query_emb = embedder.embed_queries([query])
            results = vector_store.search(query_emb, top_k=3)

            if results:
                print(f"  ✅ 检索成功，返回 {len(results)} 条结果")
                for i, (chunk_id, score, metadata) in enumerate(results[:2]):
                    content = metadata.get("content", "")[:50]
                    print(f"    [{i+1}] 分数: {score:.4f}")
                    print(f"        内容: {content}...")
            else:
                print("  ⚠️ 检索结果为空")
        else:
            print("  ⚠️ 索引不存在，跳过检索测试")
    except Exception as e:
        print(f"  ❌ 检索测试失败: {e}")

    print("\n" + "=" * 60)
    print("✅ 健康检查完成")
    print("=" * 60)


if __name__ == "__main__":
    check_knowledge_base()
