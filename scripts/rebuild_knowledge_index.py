#!/usr/bin/env python3
"""
知识库向量索引重建脚本

作用：
    用当前嵌入模型（LocalEmbedder 实际解析到的那个）重新生成向量索引，
    修复"建索引时用了 TF-IDF(300维)、检索时用了 bge-small(512维)"造成的
    维度不一致，从而消除 faiss 检索时的维度不匹配报错。

用法（在项目根目录执行）：
    ./dfecrab stop-knowledge
    python3 scripts/rebuild_knowledge_index.py
    ./dfecrab start-knowledge
"""
import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def main():
    # 运行时依赖守卫（venv 内 jieba/faiss/numpy）
    from src.knowledge.paths import require_runtime_deps
    require_runtime_deps()

    from src.knowledge.storage.document_repo import DocumentRepository
    from src.knowledge.embedding.local_embedder import LocalEmbedder
    from src.knowledge.core.vector_store import VectorStore
    from src.knowledge.core.document_processor import filter_indexable

    # 1. 诊断当前嵌入方案
    embedder = LocalEmbedder()
    dim = embedder.get_dim()
    print(f"[诊断] 当前嵌入: use_ml_model={embedder.use_ml_model}, dim={dim}")
    if embedder.use_ml_model:
        print(f"[诊断] 模型: {embedder.get_model_info().get('model_dir')}")

    repo = DocumentRepository()

    # 2. 诊断旧索引维度
    old_config = repo.index_dir / "config.json"
    old_dim = None
    old_count = 0
    if old_config.exists():
        try:
            cfg = json.loads(old_config.read_text(encoding="utf-8"))
            old_dim = cfg.get("dim")
            old_count = cfg.get("total_count", 0)
        except Exception as e:
            print(f"[诊断] 读取旧索引 config 失败: {e}")
    print(f"[诊断] 旧索引: dim={old_dim}, count={old_count}, path={repo.index_dir}")

    if old_dim is not None and old_dim != dim:
        print(f"⚠️  检测到维度不一致: 旧索引 dim={old_dim}，当前嵌入 dim={dim}，需要重建！")
    print("")

    # 3. 收集所有已处理/已索引文档的切片
    all_chunks = []
    for doc_id, doc_info in repo.documents.items():
        if doc_info.status in ("processed", "indexed"):
            chunks_path = repo.get_chunks_path(doc_id)
            if chunks_path.exists():
                with open(chunks_path, "r", encoding="utf-8") as f:
                    chunks = filter_indexable(json.load(f))
                    for chunk in chunks:
                        chunk["metadata"]["title"] = doc_info.title
                    all_chunks.extend(chunks)

    print(f"[构建] 待索引切片数: {len(all_chunks)}")
    if not all_chunks:
        print("❌ 没有可索引的切片，请先上传并处理文档")
        return

    # 4. 生成向量并写入索引
    # 嵌入统一取「检索位」metadata["content"]（图片片已被 filter_indexable 剔除，
    # 它们不进索引，靠检索后邻近带出）
    contents = [
        (c.get("metadata") or {}).get("content") or c["content"]
        for c in all_chunks
    ]
    embeddings = embedder.embed(contents)
    print(f"[构建] 向量矩阵形状: {embeddings.shape}")

    vector_store = VectorStore(dim=dim)
    chunk_ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]
    vector_store.add(embeddings, chunk_ids, metadatas)
    vector_store.save(str(repo.index_dir))

    # 5. 更新文档状态为 indexed
    for doc_id in repo.documents:
        if repo.get_chunks_path(doc_id).exists():
            repo.update_status(doc_id, "indexed")

    print("")
    print(f"✅ 索引重建完成: {len(chunk_ids)} 条, dim={dim}")
    print(f"   保存到: {repo.index_dir}")
    print("   现在重启知识库服务后 /search、/chat 即可正常工作")


if __name__ == "__main__":
    main()
