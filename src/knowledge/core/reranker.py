# src/knowledge/core/reranker.py
"""
重排序器 - 使用交叉编码器精排
"""
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class Reranker:
    """交叉编码器重排序"""
    
    MODELS = {
        "tiny": "cross-encoder/ms-marco-TinyBERT-L-2-v2",
        "small": "BAAI/bge-reranker-base",
        "medium": "BAAI/bge-reranker-large",
    }
    
    def __init__(self, model_name: str = "small", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """加载模型"""
        if self.model is not None:
            return
        
        try:
            from sentence_transformers import CrossEncoder
            import os
            from pathlib import Path

            # 优先加载本地模型（离线），否则回退到 HuggingFace 在线
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            local_model = project_root / "models" / "bge-reranker-base"
            if local_model.exists():
                model_key = str(local_model)
                os.environ['HF_HUB_OFFLINE'] = '1'
                os.environ['TRANSFORMERS_OFFLINE'] = '1'
            else:
                model_key = self.MODELS.get(self.model_name, self.MODELS["small"])

            logger.info(f"加载重排序模型: {model_key}")
            self.model = CrossEncoder(model_key, device=self.device)
            logger.info("重排序模型加载成功")
            
        except ImportError:
            raise ImportError("请安装 sentence-transformers")
        except Exception as e:
            logger.warning(f"重排序模型加载失败: {e}，将跳过重排序")
            self.model = None
    
    def rerank(self, query: str, passages: List[str], top_k: int = 5) -> List[Tuple[int, float]]:
        """对检索结果进行重排序"""
        if self.model is None or not passages:
            return list(enumerate([1.0] * min(top_k, len(passages))))[:top_k]
        
        # 构建pair
        pairs = [[query, p] for p in passages]
        
        # 预测分数
        try:
            scores = self.model.predict(pairs)
        except Exception as e:
            logger.warning(f"重排序预测失败: {e}")
            return list(enumerate([1.0] * min(top_k, len(passages))))[:top_k]
        
        # 按分数排序
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        
        return indexed_scores[:top_k]
    
    def is_available(self) -> bool:
        """检查重排序是否可用"""
        return self.model is not None


# ──────────────────────────────────────────────────────────────
# 进程级单例（C-1）：多检索器共用同一 reranker，避免重复加载模型
# ──────────────────────────────────────────────────────────────

_RERANKER_SINGLETON: Optional["Reranker"] = None


def get_reranker(model_name: str = "small", device: str = "cpu") -> "Reranker":
    """获取进程级 Reranker 单例（C-1）。

    Reranker 内部加载 CrossEncoder，进程内只需一份；
    knowledge_qa / knowledge_search / 其它检索器共用同一实例。
    """
    global _RERANKER_SINGLETON
    if _RERANKER_SINGLETON is None:
        _RERANKER_SINGLETON = Reranker(model_name=model_name, device=device)
    return _RERANKER_SINGLETON
