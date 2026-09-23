#!/usr/bin/env python3
"""
知识库文档导入脚本

用法（必须用项目虚拟环境运行；依赖 jieba/faiss/numpy）:
    venv/bin/python3 scripts/import_knowledge.py --file /path/to/file.txt --category power_grid
    venv/bin/python3 scripts/import_knowledge.py --dir /path/to/documents
    venv/bin/python3 scripts/import_knowledge.py --list
    venv/bin/python3 scripts/import_knowledge.py --stats
"""
import argparse
import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent))

# 运行时依赖守卫：本脚本依赖 venv 内的 jieba/faiss/numpy，误用系统 python 会报难以定位的 ModuleNotFoundError
from src.knowledge.paths import require_runtime_deps
require_runtime_deps()

from src.knowledge.storage.document_repo import DocumentRepository, store_document_images
from src.knowledge.storage.document_loader import DocumentLoader
from src.knowledge.core.document_processor import DocumentProcessor, filter_indexable
from src.knowledge.embedding.local_embedder import LocalEmbedder
from src.knowledge.core.vector_store import VectorStore
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def process_document(doc_id: str, repo: DocumentRepository):
    """处理单个文档"""
    doc_path = repo.get_document_path(doc_id)
    if not doc_path:
        logger.error(f"文档不存在: {doc_id}")
        return False
    
    try:
        repo.update_status(doc_id, "processing")
        
        # 加载文档
        loader = DocumentLoader()
        content = loader.load_document(str(doc_path))
        
        if not content or len(content.strip()) < 50:
            logger.warning(f"文档内容为空或太短: {doc_path.name}")
            repo.update_status(doc_id, "failed")
            return False
        
        # 保存处理后的文本
        text_path = repo.get_processed_text_path(doc_id)
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # 切片
        doc_info = repo.get_document(doc_id)
        processor = DocumentProcessor(chunk_size=500, overlap=50)
        metadata = {
            "doc_id": doc_id,
            "source": doc_path.name,
            "category": doc_info.category,
            "title": doc_info.title,
            "file_name": doc_info.file_name,
        }
        # 图片落盘 + 占位块映射（与上传链路 / 重建脚本共用同一份逻辑）
        image_map = store_document_images(repo, doc_id, loader.last_images)
        chunks = processor.process_document(content, metadata, image_map)
        
        if not chunks:
            logger.warning(f"文档切片为空: {doc_path.name}")
            repo.update_status(doc_id, "failed")
            return False
        
        # 保存切片
        chunks_data = []
        for c in chunks:
            chunks_data.append({
                "id": c.id,
                "content": c.content,
                "metadata": c.metadata
            })
        
        chunks_path = repo.get_chunks_path(doc_id)
        with open(chunks_path, 'w', encoding='utf-8') as f:
            json.dump(chunks_data, f, ensure_ascii=False, indent=2)
        
        repo.update_status(doc_id, "processed", chunk_count=len(chunks))
        logger.info(f"✅ 文档处理完成: {doc_info.title} ({len(chunks)} 个切片)")
        
        # 打印切片预览
        for i, chunk in enumerate(chunks[:2]):
            preview = chunk.content[:100].replace('\n', ' ')
            logger.info(f"   切片 {i+1}: {preview}...")
        
        return True
        
    except Exception as e:
        logger.error(f"文档处理失败 {doc_id}: {e}")
        import traceback
        traceback.print_exc()
        repo.update_status(doc_id, "failed")
        return False


def rebuild_vector_index():
    """重建向量索引"""
    repo = DocumentRepository()
    
    # 收集所有已处理的切片
    all_chunks = []
    for doc_id, doc_info in repo.documents.items():
        if doc_info.status in ["processed", "indexed"]:
            chunks_path = repo.get_chunks_path(doc_id)
            if chunks_path.exists():
                try:
                    with open(chunks_path, 'r', encoding='utf-8') as f:
                        chunks = filter_indexable(json.load(f))
                        for chunk in chunks:
                            chunk["metadata"]["title"] = doc_info.title
                            chunk["metadata"]["category"] = doc_info.category
                        all_chunks.extend(chunks)
                        logger.info(f"  加载 {doc_info.title}: {len(chunks)} 个切片")
                except Exception as e:
                    logger.error(f"加载切片失败 {doc_id}: {e}")
    
    if not all_chunks:
        logger.warning("没有找到已处理的切片")
        return
    
    logger.info(f"📊 索引 {len(all_chunks)} 个切片...")
    
    try:
        embedder = LocalEmbedder()
        # 嵌入统一取「检索位」metadata["content"]（图片片已被 filter_indexable 剔除，
        # 它们不进索引，靠检索后邻近带出）
        contents = [
            (c.get("metadata") or {}).get("content") or c["content"]
            for c in all_chunks
        ]
        
        # 分批处理
        batch_size = 100
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
        
    except Exception as e:
        logger.error(f"索引构建失败: {e}")
        import traceback
        traceback.print_exc()
        raise


def main():
    parser = argparse.ArgumentParser(description="知识库文档导入工具")
    parser.add_argument("--dir", help="要导入的目录路径")
    parser.add_argument("--file", help="要导入的单个文件路径")
    # ★ 修复：DocumentRepository 只有 DEFAULT_CATEGORIES，没有 CATEGORIES。
    #   原 choices=DocumentRepository.CATEGORIES 在构建 parser 时即求值，
    #   会导致本脚本任何用法（含 --list / --stats）都抛 AttributeError。
    #   分类已支持自定义，故不再用 choices 限制。
    parser.add_argument("--category", default="other",
                       help="文档分类（支持内置与自定义分类，任意非空字符串）")
    parser.add_argument("--title", help="文档标题（仅单文件导入）")
    parser.add_argument("--description", help="文档描述（仅单文件导入）")
    parser.add_argument("--rebuild-index", action="store_true",
                       help="导入后重建索引")
    parser.add_argument("--list", action="store_true",
                       help="列出所有已导入的文档")
    parser.add_argument("--stats", action="store_true",
                       help="显示知识库统计信息")
    
    args = parser.parse_args()
    
    repo = DocumentRepository()
    
    if args.list:
        docs = repo.list_documents()
        print("\n📚 已导入的文档:")
        print("-" * 80)
        print(f"{'状态':<10} {'标题':<30} {'分类':<15} {'切片数':<10} {'大小':<10}")
        print("-" * 80)
        for doc in docs:
            size_mb = doc.file_size / (1024 * 1024)
            print(f"{doc.status:<10} {doc.title[:28]:<30} {doc.category:<15} "
                  f"{doc.chunk_count:<10} {size_mb:.2f}MB")
        print("-" * 80)
        print(f"总计: {len(docs)} 个文档")
        return
    
    if args.stats:
        stats = repo.get_stats()
        print("\n📊 知识库统计:")
        print(f"  📄 文档总数: {stats['total_documents']}")
        print(f"  📦 切片总数: {stats['total_chunks']}")
        print(f"  📂 分类统计: {json.dumps(stats['by_category'], ensure_ascii=False)}")
        print(f"  📌 状态统计: {json.dumps(stats['by_status'], ensure_ascii=False)}")
        print(f"  🕐 更新时间: {stats['last_updated']}")
        return
    
    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.exists():
            logger.error(f"目录不存在: {dir_path}")
            return
        
        files = []
        for ext in DocumentRepository.SUPPORTED_TYPES:
            files.extend(dir_path.glob(f"*{ext}"))
        
        if not files:
            logger.warning(f"目录中没有支持的文档: {dir_path}")
            return
        
        logger.info(f"📂 发现 {len(files)} 个文档")
        
        for file_path in files:
            try:
                doc_info = repo.add_document(
                    str(file_path),
                    args.category,
                    title=file_path.stem
                )
                process_document(doc_info.doc_id, repo)
            except Exception as e:
                logger.error(f"导入失败 {file_path.name}: {e}")
        
    elif args.file:
        try:
            doc_info = repo.add_document(
                args.file,
                args.category,
                args.title,
                args.description
            )
            process_document(doc_info.doc_id, repo)
        except Exception as e:
            logger.error(f"导入失败: {e}")
            import traceback
            traceback.print_exc()
            return
    else:
        parser.print_help()
        return
    
    # 重建索引
    if args.rebuild_index:
        logger.info("🔄 重建向量索引...")
        rebuild_vector_index()
        logger.info("✅ 索引重建完成")


if __name__ == "__main__":
    main()
