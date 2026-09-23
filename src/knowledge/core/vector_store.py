# src/knowledge/core/vector_store.py
"""
FAISS向量存储

索引类型（大库提速）
------------------------------------------------------------------
    flat : IndexFlatIP —— 精确暴力检索。N 小（< 数十万）时延迟已经很低，召回 100%
    ivf  : IndexIVFFlat —— 倒排聚类，查询只扫 nprobe 个簇。N 很大（百万级）时
           把延迟从数百 ms 压到几 ms，代价是近似召回（nprobe 越大越接近精确）
    auto : 按切片数自动选择（N > ivf_threshold 切 ivf），默认策略

说明：本项目每次都是"全量重建索引"，因此 IVF 的 train 用当前全量向量完成，
不存在增量训练问题；向量已归一化，故用内积 (METRIC_INNER_PRODUCT) 等价余弦。
"""
import faiss
import math
import numpy as np
import pickle
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging

from ..paths import INDEX_DIR

logger = logging.getLogger(__name__)


def _index_kind(index) -> str:
    """判定索引类型：IVF 系列带 nprobe 属性"""
    return "ivf" if hasattr(index, "nprobe") else "flat"


class VectorStore:
    """FAISS向量存储"""
    
    def __init__(self, dim: int, index_path: Optional[str] = None,
                 index_type: str = "flat", ivf_nlist: int = 0,
                 ivf_nprobe: int = 16, ivf_threshold: int = 500000):
        """
        Args:
            dim: 向量维度
            index_path: 索引目录（存在则自动加载）
            index_type: flat / ivf / auto（auto 依 ivf_threshold 决定）
            ivf_nlist: IVF 聚类数，0=自动 sqrt(N)
            ivf_nprobe: IVF 查询探测簇数
            ivf_threshold: auto 模式下切换 IVF 的切片数阈值
        """
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)  # 内积相似度（向量需归一化）
        self.chunk_ids = []
        self.metadatas = []
        self.index_path = Path(index_path) if index_path else None
        self.index_type = str(index_type or "flat").strip().lower()
        self.ivf_nlist = int(ivf_nlist or 0)
        self.ivf_nprobe = max(1, int(ivf_nprobe or 16))
        self.ivf_threshold = int(ivf_threshold or 0)
        
        # 加载索引（如果存在）
        if self.index_path and self.index_path.exists():
            self.load(str(self.index_path))

    # ------------------------------------------------------------------
    # 索引类型决策
    # ------------------------------------------------------------------
    def _resolve_kind(self, n_total: int) -> str:
        """按配置与规模决定目标索引类型"""
        if self.index_type == "ivf":
            return "ivf"
        if self.index_type == "auto" and self.ivf_threshold > 0 and n_total > self.ivf_threshold:
            return "ivf"
        return "flat"

    def _build_ivf(self, embeddings: np.ndarray):
        """构建并训练 IVF 索引（训练集=本次全量向量）。

        失败（样本不足等）返回 None，由调用方回落 flat，保证"永不因索引类型而丢数据"。
        """
        n = int(embeddings.shape[0])
        nlist = self.ivf_nlist or max(1, int(math.sqrt(max(n, 1))))
        # faiss 建议每簇 ≥ 39 个训练点，否则训练质量差
        nlist = max(1, min(nlist, max(1, n // 39)))
        if nlist < 2:
            logger.info(f"ℹ️ 切片数 {n} 过少，IVF 不适用，回落 flat")
            return None
        try:
            quantizer = faiss.IndexFlatIP(self.dim)
            index = faiss.IndexIVFFlat(quantizer, self.dim, nlist,
                                       faiss.METRIC_INNER_PRODUCT)
            index.train(embeddings)
            index.nprobe = min(self.ivf_nprobe, nlist)
            logger.info(f"🔧 已构建 IVF 索引: nlist={nlist}, nprobe={index.nprobe}, "
                        f"训练样本={n}（切片数超阈值 {self.ivf_threshold}，用近似检索降延迟）")
            return index
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ IVF 构建失败，回落 flat 精确检索: {e}")
            return None
    
    def add(self, embeddings: np.ndarray, chunk_ids: List[str], 
            metadatas: List[Dict]) -> int:
        """添加向量到索引"""
        if len(embeddings) == 0:
            return 0
        
        assert embeddings.shape[0] == len(chunk_ids)
        assert embeddings.shape[1] == self.dim
        
        # 转换为float32
        embeddings = np.ascontiguousarray(embeddings, dtype=np.float32)
        
        n_total = len(self.chunk_ids) + len(chunk_ids)
        kind = self._resolve_kind(n_total)
        cur_kind = _index_kind(self.index)

        if kind == "ivf" and cur_kind != "ivf":
            ivf_index = self._build_ivf(embeddings)
            if ivf_index is not None:
                self.index = ivf_index
                cur_kind = "ivf"

        # 添加到FAISS索引（IVF 未训练时先训练当前批次）
        if cur_kind == "ivf" and not self.index.is_trained:
            self.index.train(embeddings)
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
        k = min(max(1, int(top_k)), len(self.chunk_ids))
        # IVF：按配置设置探测簇数（越大越准越慢）
        if hasattr(self.index, "nprobe"):
            try:
                self.index.nprobe = max(1, min(self.ivf_nprobe, self.index.nlist))
            except Exception:  # noqa: BLE001
                pass
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
        
        # 保存配置（记录真实索引类型，便于 /knowledge/health 与排障时判断是否走了 IVF）
        config_file = path / "config.json"
        with open(config_file, 'w') as f:
            json.dump({
                "dim": self.dim,
                "total_count": len(self.chunk_ids),
                "index_type": _index_kind(self.index),
                "ivf_nlist": int(getattr(self.index, "nlist", 0) or 0),
                "ivf_nprobe": int(getattr(self.index, "nprobe", self.ivf_nprobe) or self.ivf_nprobe),
            }, f)
        
        logger.info(f"索引已保存: {path}, 共 {len(self.chunk_ids)} 条记录 "
                    f"(类型={_index_kind(self.index)})")
    
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
        # IVF：加载后恢复探测簇数配置
        if hasattr(self.index, "nprobe"):
            try:
                self.index.nprobe = max(1, min(self.ivf_nprobe, self.index.nlist))
            except Exception:  # noqa: BLE001
                pass
        
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
        """清空索引（重置为未训练的 flat，后续 add 时按规模重新决策类型）"""
        self.index = faiss.IndexFlatIP(self.dim)
        self.chunk_ids = []
        self.metadatas = []
    
    def get_stats(self) -> Dict:
        """获取索引统计信息"""
        kind = _index_kind(self.index)
        stats = {
            "dim": self.dim,
            "total_count": len(self.chunk_ids),
            "index_type": "IVFFlat" if kind == "ivf" else "FlatIP",
        }
        if kind == "ivf":
            stats["ivf_nlist"] = int(getattr(self.index, "nlist", 0) or 0)
            stats["ivf_nprobe"] = int(getattr(self.index, "nprobe", 0) or 0)
        return stats


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
        store = VectorStore(dim=dim, ivf_nprobe=_cfg_ivf_nprobe())
        store.load(str(INDEX_DIR))
        logger.info(f"✅ 加载向量索引: {len(store.chunk_ids)} 条记录 ({INDEX_DIR}) "
                    f"类型={_index_kind(store.index)}")
        _DEFAULT_STORE_CACHE[dim] = (sig, store)
        return store

    # 索引缺失：不缓存空索引（后续导入重建后可被正常加载）
    store = VectorStore(dim=dim, ivf_nprobe=_cfg_ivf_nprobe())
    logger.warning(f"⚠️ 向量索引不存在: {INDEX_DIR}，请先导入文档")
    return store


def _cfg_ivf_nprobe() -> int:
    """IVF 查询探测簇数（gateway.yaml knowledge.ivf_nprobe，默认 16）；读不到用默认"""
    try:
        from config.port_loader import knowledge_chunk_config
        return int(knowledge_chunk_config().get("ivf_nprobe", 16) or 16)
    except Exception:  # noqa: BLE001
        return 16


def invalidate_default_vector_store() -> None:
    """主动清空默认索引缓存（索引重建完成后调用，确保下次按新磁盘态加载）。"""
    _DEFAULT_STORE_CACHE.clear()
