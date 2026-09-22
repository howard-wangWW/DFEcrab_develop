# src/knowledge/embedding/local_embedder.py
"""
本地嵌入模型 - 自动检测模型，有模型用模型，无模型用分词
"""
import os
import jieba
import numpy as np
from collections import Counter
from typing import List, Union, Optional
from pathlib import Path
import math
import re
import pickle
import logging

logger = logging.getLogger(__name__)


class LocalEmbedder:
    """本地嵌入模型 - 自动选择最优方案"""
    
    def __init__(self, model_name: str = "medium", device: str = "cpu", 
                 model_dir: str = None):
        self.model_name = model_name
        self.device = device
        # 默认模型目录：项目根目录下的 models（DFEcrab/models）
        if model_dir is None:
            model_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "models")
        self.model_dir = Path(model_dir)
        self.model = None
        self.dim = None
        self.use_ml_model = False  # 是否使用机器学习模型
        
        # 初始化jieba
        try:
            import jieba
            self.jieba = jieba
        except ImportError:
            raise ImportError("请安装 jieba: pip install jieba")
        
        # 停用词
        self.stopwords = self._load_stopwords()
        
        # 尝试加载机器学习模型
        self._try_load_ml_model()
        
        # 如果模型加载失败，使用TF-IDF
        if not self.use_ml_model:
            logger.info("📝 使用 TF-IDF 分词方案")
            self.dim = 300
            self.idf_dict = {}
            self.vocab = {}
            self._load_or_build_idf()
        else:
            logger.info(f"🤖 使用机器学习模型: {self.model_name}")
    
    def _load_stopwords(self) -> set:
        """加载停用词"""
        return {
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
            '个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
            '看', '好', '自己', '来', '吗', '吧', '呢', '啊', '哦', '嗯', '这个',
            '那个', '什么', '怎么', '如何', '为什么', '哪里', '哪些', '那么', '这样',
            '可以', '应该', '需要', '进行', '已经', '时候', '就是', '不过', '只是',
            '但是', '所以', '因为', '而且', '或者', '如果', '虽然', '然后', '于是',
            '现在', '今天', '昨天', '明天', '之前', '之后', '以来', '之间',
            '之', '其', '该', '各', '每', '某', '任何', '所有', '各位'
        }
    
    def _try_load_ml_model(self):
        """尝试加载机器学习模型"""
        try:
            from sentence_transformers import SentenceTransformer
            
            # 检查模型是否存在
            model_path = self._find_model_path()
            if model_path is None:
                logger.warning("⚠️ 未找到本地模型，使用 TF-IDF 方案")
                return
            
            logger.info(f"📁 加载模型: {model_path}")
            
            # 设置离线模式
            os.environ['HF_HUB_OFFLINE'] = '1'
            os.environ['TRANSFORMERS_OFFLINE'] = '1'
            
            self.model = SentenceTransformer(str(model_path), device=self.device)
            # 兼容新旧版本 sentence-transformers：旧版用 get_sentence_embedding_dimension
            if hasattr(self.model, "get_embedding_dimension"):
                self.dim = self.model.get_embedding_dimension()
            else:
                self.dim = self.model.get_sentence_embedding_dimension()
            self.use_ml_model = True
            logger.info(f"✅ 模型加载成功，维度: {self.dim}")
            
        except ImportError:
            logger.warning("⚠️ sentence-transformers 未安装，使用 TF-IDF 方案")
        except Exception as e:
            logger.warning(f"⚠️ 模型加载失败: {e}，使用 TF-IDF 方案")
    
    def _find_model_path(self) -> Optional[Path]:
        """查找模型路径"""
        # 可能的模型名称
        model_names = {
            "medium": "bge-small-zh-v1.5",
            "large": "bge-large-zh-v1.5",
            "tiny": "text2vec-base-multilingual",
            "small": "paraphrase-multilingual-MiniLM-L12-v2",
        }
        
        model_name = model_names.get(self.model_name, "bge-small-zh-v1.5")
        
        # 检查多个可能的位置（按命中概率排序；末尾为"项目内 models/"，
        # 用 __file__ 推导而非硬编码部署路径，任何机器上都成立）
        possible_paths = [
            self.model_dir / model_name,
            self.model_dir / "models" / model_name,
            Path.home() / ".cache/huggingface/hub" / f"models--BAAI--{model_name}",
            Path(__file__).resolve().parents[3] / "models" / model_name,
        ]
        
        for path in possible_paths:
            if path.exists() and (path / "config.json").exists():
                return path
        
        # 检查是否有包含模型文件的目录
        for path in possible_paths:
            if path.exists():
                for ext in [".safetensors", ".bin"]:
                    if any(path.glob(f"*{ext}")):
                        return path
        
        return None
    
    def _load_or_build_idf(self):
        """加载或构建IDF词典（TF-IDF方案）"""
        idf_path = self.model_dir / "idf_dict.pkl"
        vocab_path = self.model_dir / "vocab.pkl"
        
        if idf_path.exists() and vocab_path.exists():
            try:
                with open(idf_path, 'rb') as f:
                    self.idf_dict = pickle.load(f)
                with open(vocab_path, 'rb') as f:
                    self.vocab = pickle.load(f)
                logger.info(f"✅ 加载IDF词典: {len(self.idf_dict)} 个词")
                return
            except Exception as e:
                logger.warning(f"加载IDF失败: {e}，重新构建")
        
        self._build_idf()
    
    def _build_idf(self):
        """构建IDF词典"""
        corpus = [
            "倒闸操作 设备 核对 双重名称 操作票 唱票 复诵 检查 设备状态 安全",
            "调度规程 配网分册 调度管理 操作规范 安全措施 调度纪律 调度指令",
            "事故处理 故障分析 事故报告 安全预警 抢修恢复 应急响应 应急预案",
            "断路器 隔离开关 接地刀闸 操作机构 合闸 分闸 储能 弹簧机构",
            "变压器 主变 配变 调压 档位 冷却系统 油温 绕组温度 绝缘",
            "母线 联络 分段 倒母线 旁路代路 合环 解环 转供电 负荷转移",
            "继电保护 差动保护 过流保护 零序保护 距离保护 高频保护 保护定值",
            "安全规程 两票三制 工作票 操作票 交接班 巡回检查 设备巡视 危险点",
            "电网调度 调度指令 调度规程 调度自动化 调度数据网 调度电话 录音",
            "配网自动化 终端 故障指示器 配电变压器 开关柜 环网柜 故障隔离",
            "合环转供电 操作步骤 注意事项 预控措施 图实不符 排查 治理 台账",
            "检修 安规 监护 复诵 录音 回放 操作命令 调度权限 调度职责",
            "SCADA 远动 通信 遥测 遥信 遥控 遥调 数据采集 监控系统 报警",
            "黑启动 孤岛运行 重合闸 备自投 低频减载 高频切机 安稳装置",
            "调度计划 调度预案 调度演练 调度评估 调度改进 事故预想 反事故演习",
        ]
        
        doc_freq = {}
        for doc in corpus:
            words = set(self._tokenize(doc))
            for word in words:
                doc_freq[word] = doc_freq.get(word, 0) + 1
        
        N = len(corpus)
        for word, freq in doc_freq.items():
            self.idf_dict[word] = math.log((N + 1) / (freq + 1)) + 1
        
        self.vocab = {word: idx for idx, word in enumerate(self.idf_dict.keys())}
        
        # 保存IDF
        os.makedirs(self.model_dir, exist_ok=True)
        with open(self.model_dir / "idf_dict.pkl", 'wb') as f:
            pickle.dump(self.idf_dict, f)
        with open(self.model_dir / "vocab.pkl", 'wb') as f:
            pickle.dump(self.vocab, f)
        
        logger.info(f"✅ IDF词典构建完成: {len(self.idf_dict)} 个词")
    
    def _tokenize(self, text: str) -> List[str]:
        """分词"""
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', text)
        words = self.jieba.cut(text)
        return [
            w.strip() for w in words 
            if len(w.strip()) >= 2 
            and w not in self.stopwords
            and not w.isdigit()
        ]
    
    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        """生成文本向量"""
        if isinstance(texts, str):
            texts = [texts]
        
        if not texts:
            return np.array([])
        
        # 如果使用机器学习模型
        if self.use_ml_model and self.model is not None:
            embeddings = self.model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=32
            )
            return embeddings.astype(np.float32)
        
        # 否则使用TF-IDF
        embeddings = []
        for text in texts:
            words = self._tokenize(text)
            if not words:
                embeddings.append(np.zeros(self.dim))
                continue
            
            word_freq = Counter(words)
            vec = np.zeros(self.dim)
            for i, (word, freq) in enumerate(word_freq.items()):
                if i >= self.dim:
                    break
                if word in self.idf_dict:
                    tf = freq / len(words)
                    idf = self.idf_dict[word]
                    vec[i] = tf * idf
            
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            embeddings.append(vec)
        
        return np.array(embeddings, dtype=np.float32)
    
    def embed_queries(self, queries: List[str]) -> np.ndarray:
        """生成查询向量"""
        return self.embed(queries)
    
    def get_dim(self) -> int:
        return self.dim
    
    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            "use_ml_model": self.use_ml_model,
            "model_name": self.model_name if self.use_ml_model else "tfidf",
            "dim": self.dim,
            "model_dir": str(self.model_dir) if self.use_ml_model else None
        }


# ──────────────────────────────────────────────────────────────
# 进程级单例（C-1）：knowledge_qa / knowledge_search / 重建共用
# ──────────────────────────────────────────────────────────────

_EMBEDDER_SINGLETON: Optional["LocalEmbedder"] = None


def get_local_embedder(model_name: str = "medium", device: str = "cpu") -> "LocalEmbedder":
    """获取进程级 LocalEmbedder 单例（C-1）。

    背景：knowledge_qa 与 knowledge_search 各 new 一个 LocalEmbedder，每次都会
    重新加载 bge 模型（日志实证一次对话"加载模型"×2），内存与启动时间双浪费。
    单例后模型进程内只加载一次；如需指定不同 model_name/device 才另建实例。
    """
    global _EMBEDDER_SINGLETON
    if _EMBEDDER_SINGLETON is None:
        _EMBEDDER_SINGLETON = LocalEmbedder(model_name=model_name, device=device)
    return _EMBEDDER_SINGLETON
