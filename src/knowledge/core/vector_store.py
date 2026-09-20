# src/knowledge/core/vector_store.py
"""
FAISS向量存储
"""
import faiss
import numpy as np
import pickle
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging

from ..paths import INDEX_DIR

logger = logging.getLogger(__name__)


class VectorStore:
    """FAISS向量存储"""
    
    def __init__(self, dim: int, index_path: Optional[str] = None):
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)  # 内积相似度（向量需归一化）
        self.chunk_ids = []
        self.metadatas = []
        self.index_path = Path(index_path) if index_path else None
        
        # 加载索引（如果存在）
        if self.index_path and self.index_path.exists():
            self.load(str(self.index_path))
    
    def add(self, embeddings: np.ndarray, chunk_ids: List[str], 
            metadatas: List[Dict]) -> int:
        """添加向量到索引"""
        if len(embeddings) == 0:
            return 0
        
        assert embeddings.shape[0] == len(chunk_ids)
        assert embeddings.shape[1] == self.dim
        
        # 转换为float32
        embeddings = embeddings.astype(np.float32)
        
        # 添加到FAISS索引
        self.index.add(embeddings)
        
        # 保存元数据
        self.chunk_ids.extend(chunk_ids)
        self.metadatas.extend(metadatas)
        
        return len(chunk_ids)
    
    def search(self, query_embedding: np.ndarray, top_k: int = 10) -> List[Tuple[str, float, Dict]]:
        """搜索最相似的top_k个结果"""
        if len(self.chunk_ids) == 0:
            return []
        
        query_embedding = query_embedding.astype(np.float32).reshape(1, -1)
        k = min(top_k, len(self.chunk_ids))
        scores, indices = self.index.search(query_embedding, k)
        
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < len(self.chunk_ids):
                results.append((
                    self.chunk_ids[idx],
                    float(score),
                    self.metadatas[idx] if idx < len(self.metadatas) else {}
                ))
        return results
    
    def save(self, path: str):
        """保存索引到磁盘"""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        
        # 保存FAISS索引
        faiss.write_index(self.index, str(path / "index.faiss"))
        
        # 保存元数据
        metadata_file = path / "metadata.pkl"
        with open(metadata_file, 'wb') as f:
            pickle.dump({
                "chunk_ids": self.chunk_ids,
                "metadatas": self.metadatas,
                "dim": self.dim,
                "total_count": len(self.chunk_ids)
            }, f)
        
        # 保存配置
        config_file = path / "config.json"
        with open(config_file, 'w') as f:
            json.dump({
                "dim": self.dim,
                "total_count": len(self.chunk_ids),
                "index_type": "FlatIP"
            }, f)
        
        logger.info(f"索引已保存: {path}, 共 {len(self.chunk_ids)} 条记录")
    
    def load(self, path: str):
        """从磁盘加载索引"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"索引目录不存在: {path}")
        
        index_file = path / "index.faiss"
        metadata_file = path / "metadata.pkl"
        
        if not index_file.exists():
            raise FileNotFoundError(f"索引文件不存在: {index_file}")
        
        # 加载FAISS索引
        self.index = faiss.read_index(str(index_file))
        self.dim = self.index.d
        
        # 加载元数据
        if metadata_file.exists():
            with open(metadata_file, 'rb') as f:
                data = pickle.load(f)
                self.chunk_ids = data.get("chunk_ids", [])
                self.metadatas = data.get("metadatas", [])
        else:
            self.chunk_ids = []
            self.metadatas = []
        
        logger.info(f"索引已加载: {path}, 共 {len(self.chunk_ids)} 条记录")
    
    def clear(self):
        """清空索引"""
        self.index = faiss.IndexFlatIP(self.dim)
        self.chunk_ids = []
        self.metadatas = []
    
    def get_stats(self) -> Dict:
        """获取索引统计信息"""
        return {
            "dim": self.dim,
            "total_count": len(self.chunk_ids),
            "index_type": "FlatIP"
        }


# 进程级默认索引缓存（C-1）：key = dim → (signature, store)
# 以磁盘文件 mtime_ns+size 为签名，重建索引写盘后自动失效重载，
# 既避免 knowledge_qa / knowledge_search 重复加载同一索引，又不破坏"上传后热刷新"。
_DEFAULT_STORE_CACHE: Dict[int, tuple] = {}


def _index_signature() -> Optional[tuple]:
    """索引目录磁盘签名（index.faiss / metadata.pkl / config.json 的 mtime_ns+size）。

    Returns:
        签名 tuple；索引目录或其关键文件缺失时返回 None（视为不可缓存）。
    """
    if not INDEX_DIR.exists():
        return None
    sig = []
    for name in ("index.faiss", "metadata.pkl", "config.json"):
        f = INDEX_DIR / name
        if not f.exists():
            return None
        st = f.stat()
        sig.append((st.st_mtime_ns, st.st_size))
    return tuple(sig)


def load_default_vector_store(dim: int) -> "VectorStore":
    """加载项目默认向量索引（knowledge_base/index）——带磁盘签名缓存（C-1）。

    - 索引不存在时返回空索引，不抛错（调用方据此提示先导入文档）
    - 与重建索引（knowledge_service._rebuild_index_async）共用 INDEX_DIR，
      保证"写入磁盘的位置"与"运行服务加载的位置"是同一处
    - 同 dim 在索引未变更时复用进程内实例；重建写盘（mtime 变化）后自动重新加载
    """
    sig = _index_signature()
    if sig is not None:
        cached = _DEFAULT_STORE_CACHE.get(dim)
        if cached and cached[0] == sig:
            return cached[1]
        store = VectorStore(dim=dim)
        store.load(str(INDEX_DIR))
        logger.info(f"✅ 加载向量索引: {len(store.chunk_ids)} 条记录 ({INDEX_DIR})")
        _DEFAULT_STORE_CACHE[dim] = (sig, store)
        return store

    # 索引缺失：不缓存空索引（后续导入重建后可被正常加载）
    store = VectorStore(dim=dim)
    logger.warning(f"⚠️ 向量索引不存在: {INDEX_DIR}，请先导入文档")
    return store


def invalidate_default_vector_store() -> None:
    """主动清空默认索引缓存（索引重建完成后调用，确保下次按新磁盘态加载）。"""
    _DEFAULT_STORE_CACHE.clear()
