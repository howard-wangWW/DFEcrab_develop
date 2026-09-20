# scripts/rebuild_knowledge_chunks.py
"""按新切片参数重建全部知识库文档的切片 + 向量索引。

用法（必须用项目虚拟环境运行；依赖 jieba/faiss/numpy）:
    venv/bin/python3 scripts/rebuild_knowledge_chunks.py [--chunk-size 800] [--overlap 100]

说明:
    - 读取 knowledge_base/config/document_mapping.json 里登记的全部文档
    - 用 DocumentLoader 读取原始文件 -> DocumentProcessor 重新切片 -> 覆写 chunks 文件
    - 用 VectorStore + LocalEmbedder 重建向量索引
    - 更新每个文档的 chunk_count / status
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# 确保项目根在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 运行时依赖守卫：本脚本依赖 venv 内的 jieba/faiss/numpy，误用系统 python 会报难以定位的 ModuleNotFoundError
from src.knowledge.paths import require_runtime_deps
require_runtime_deps()

from src.knowledge.storage.document_repo import DocumentRepository
from src.knowledge.storage.document_loader import DocumentLoader
from src.knowledge.core.document_processor import DocumentProcessor
from src.knowledge.core.vector_store import VectorStore
from src.knowledge.embedding.local_embedder import LocalEmbedder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def rebuild(chunk_size: int, overlap: int):
    repo = DocumentRepository()
    loader = DocumentLoader()
    processor = DocumentProcessor(chunk_size=chunk_size, overlap=overlap)
    embedder = LocalEmbedder()

    all_chunks = []
    docs = repo.list_documents()

    if not docs:
        logger.warning("⚠️ 未登记任何文档，无需重建")
        return

    for doc in docs:
        # ★ 修复：doc.file_path 是相对 knowledge_base 的路径（如 documents/power_grid/x.docx），
        #   直接用 Path(doc.file_path) 会相对 CWD 解析，从项目根运行时必然误判"文件不存在"→ 全部跳过、
        #   重建静默空转。统一走 repo 解析出的绝对路径（与 paths.py 消除 CWD 依赖的初衷一致）。
        file_path = repo.get_document_path(doc.doc_id)
        if not file_path or not file_path.exists():
            logger.warning(f"⚠️ 文档原始文件不存在，跳过: {doc.doc_id} ({doc.file_name})")
            continue

        logger.info(f"🔁 重新切片: {doc.file_name} (id={doc.doc_id})")
        try:
            content = loader.load_document(str(file_path))
            metadata = {
                "doc_id": doc.doc_id,
                "source": doc.file_name,
                "category": doc.category,
                "title": doc.title,
            }
            chunks = processor.process_document(content, metadata)

            # 覆写切片文件
            chunks_path = repo.get_chunks_path(doc.doc_id)
            chunks_data = [
                {"id": c.id, "content": c.content, "metadata": c.metadata}
                for c in chunks
            ]
            chunks_path.parent.mkdir(parents=True, exist_ok=True)
            with open(chunks_path, "w", encoding="utf-8") as f:
                json.dump(chunks_data, f, ensure_ascii=False, indent=2)

            repo.update_status(doc.doc_id, "processed", chunk_count=len(chunks))
            logger.info(f"   ✅ {len(chunks)} 个切片 (chunk_size={chunk_size})")

            # 汇总用于索引
            for c in chunks:
                c.metadata["title"] = doc.title
                all_chunks.append(
                    {"id": c.id, "content": c.content, "metadata": c.metadata}
                )

        except Exception as e:
            logger.error(f"❌ 切片失败: {doc.file_name}: {e}")
            repo.update_status(doc.doc_id, "failed")
            continue

    # 重建向量索引
    if not all_chunks:
        logger.warning("⚠️ 未生成任何切片，跳过索引重建")
        return

    logger.info(f"🛠️  重建向量索引，共 {len(all_chunks)} 个切片 ...")
    contents = [c["content"] for c in all_chunks]
    embeddings = embedder.embed(contents)
    vector_store = VectorStore(dim=embedder.get_dim())
    vector_store.add(embeddings, [c["id"] for c in all_chunks], [c["metadata"] for c in all_chunks])
    vector_store.save(str(repo.index_dir))

    for doc in repo.documents.values():
        if repo.get_chunks_path(doc.doc_id).exists():
            repo.update_status(doc.doc_id, "indexed")

    logger.info("✅ 全部重建完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重建知识库切片 + 索引")
    parser.add_argument("--chunk-size", type=int, default=800, help="切片大小")
    parser.add_argument("--overlap", type=int, default=100, help="重叠大小")
    args = parser.parse_args()
    rebuild(args.chunk_size, args.overlap)
