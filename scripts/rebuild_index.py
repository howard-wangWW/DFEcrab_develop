#!/usr/bin/env python3
"""
向量索引重建脚本 - 本地TF-IDF版本

⚠️【已废弃 · 请勿直接使用】
本脚本功能已被 `scripts/rebuild_knowledge_index.py` 完全覆盖（后者还带维度诊断，
且与 dfecrab 启动时的自动重建共用同一入口）。保留仅为历史参考，后续清理中移除。
重建索引请用：
    python3 scripts/rebuild_knowledge_index.py      # 只重建向量索引（切片不动）
    python3 scripts/rebuild_knowledge_chunks.py     # 重切片 + 重建索引
"""
import sys
import json
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge.storage.document_repo import DocumentRepository
from src.knowledge.embedding.local_embedder import LocalEmbedder
from src.knowledge.core.vector_store import VectorStore
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def rebuild_index(batch_size: int = 100):
    """重建向量索引"""
    repo = DocumentRepository()
    
    # 收集所有切片
    all_chunks = []
    for doc_id, doc_info in repo.documents.items():
        if doc_info.status in ["processed", "indexed"]:
            chunks_path = repo.get_chunks_path(doc_id)
            if chunks_path.exists():
                try:
                    with open(chunks_path, 'r', encoding='utf-8') as f:
                        chunks = json.load(f)
                        for chunk in chunks:
                            chunk["metadata"]["title"] = doc_info.title
                            chunk["metadata"]["category"] = doc_info.category
                            chunk["metadata"]["doc_id"] = doc_id
                        all_chunks.extend(chunks)
                        logger.info(f"  📄 {doc_info.title}: {len(chunks)} 个切片")
                except Exception as e:
                    logger.error(f"加载切片失败 {doc_id}: {e}")
    
    if not all_chunks:
        logger.warning("没有找到已处理的切片，请先导入文档")
        return
    
    logger.info(f"📊 索引 {len(all_chunks)} 个切片...")
    
    try:
        # 使用本地嵌入
        embedder = LocalEmbedder()
        contents = [c["content"] for c in all_chunks]
        
        # 分批生成向量
        all_embeddings = []
        total = len(contents)
        for i in range(0, total, batch_size):
            batch = contents[i:i+batch_size]
            embeddings = embedder.embed(batch)
            all_embeddings.append(embeddings)
            logger.info(f"  进度: {min(i+batch_size, total)}/{total}")
        
        embeddings = np.vstack(all_embeddings)
        
        # 创建索引
        vector_store = VectorStore(dim=embedder.get_dim())
        chunk_ids = [c["id"] for c in all_chunks]
        metadatas = [c["metadata"] for c in all_chunks]
        
        vector_store.add(embeddings, chunk_ids, metadatas)
        vector_store.save(str(repo.index_dir))
        
        logger.info(f"✅ 向量索引已保存: {repo.index_dir}")
        logger.info(f"   记录数: {len(vector_store.chunk_ids)}")
        
        # 更新文档状态
        for doc_id in repo.documents:
            if repo.get_chunks_path(doc_id).exists():
                repo.update_status(doc_id, "indexed")
        
        logger.info("✅ 索引重建完成")
        
    except Exception as e:
        logger.error(f"索引重建失败: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="重建向量索引")
    parser.add_argument("--batch-size", type=int, default=100, help="批次大小")
    args = parser.parse_args()
    
    rebuild_index(args.batch_size)
