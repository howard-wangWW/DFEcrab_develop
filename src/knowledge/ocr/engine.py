# src/knowledge/ocr/engine.py
"""
OCR 引擎 - 图片内文字识别（可选依赖，缺失时降级且不影响主流程）

为什么是可选依赖：
    知识库主链路（txt/md/纯文字 pdf/docx）不应该因为没装 OCR 就跑不起来。
    因此本模块所有加载失败都只 logger.warning，绝不抛异常；
    调用方通过 is_available() 判断，不可用时按「图片文字不入库」走原逻辑。

写法对齐本项目既有先例：
    - src/knowledge/embedding/local_embedder.py::_try_load_ml_model  （探测失败降级）
    - src/knowledge/core/reranker.py::is_available / get_reranker     （可用性 + C-1 单例）

引擎选型：rapidocr 家族，按后端依次尝试
    RapidOCR 按推理后端拆成多个发行包，识别模型与调用方式完全一致，只有后端不同：

    1. rapidocr-onnxruntime —— 纯 Python wheel（py3-none-any），ONNX 模型内置包内，
       无需联网下载模型。但其后端 onnxruntime 对 Python 3.12 **只发过
       manylinux_2_27 及以上的 wheel**，所以 glibc < 2.27 的老系统（如 CentOS 7，
       glibc 2.17）装不上。
    2. rapidocr-openvino —— 同一项目、同一版本的另一个后端，依赖 openvino。
       openvino 提供 manylinux2014（glibc 2.17）的 cp312 wheel，
       是 glibc 2.16/2.17 机器上唯一可行的选择（已实测其 .so 最高只要求
       GLIBC_2.16 / GLIBCXX_3.4.19 / CXXABI_1.3.3）。
       注意：它用的是 openvino.runtime 命名空间，该命名空间在 openvino 2025.0
       已被移除，故必须配 openvino 2024.x，不能升到 2025.x。

    两个包都装不上时按「图片文字不入库」降级，主链路不受影响。
"""
import importlib
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class OCREngine:
    """图片文字识别引擎（rapidocr 封装，多后端自动选择）"""

    # 后端按优先级排列：(模块名, 展示名)
    # onnxruntime 优先——它的 wheel 覆盖面最广；openvino 是 glibc 2.17 老系统的兜底。
    BACKENDS = (
        ("rapidocr_onnxruntime", "rapidocr-onnxruntime"),
        ("rapidocr_openvino", "rapidocr-openvino"),
    )

    ENGINE_NAME = "rapidocr"          # 兜底展示名，实际由 self.engine_name 覆盖

    def __init__(self):
        self.available = False
        self._engine = None
        self.engine_name = self.ENGINE_NAME
        # 不可用时的原因（供 get_info / 上传报错提示使用）
        self.error: Optional[str] = None
        self._try_load()

    def _try_load(self):
        """按 BACKENDS 顺序尝试加载；全部失败仅记录原因，绝不抛异常"""
        errors = []
        for module_name, label in self.BACKENDS:
            try:
                mod = importlib.import_module(module_name)
                self._engine = mod.RapidOCR()
            except Exception as e:
                # ImportError（未装 / 缺 libGL / 平台无 wheel）与初始化异常统一处理
                errors.append(f"{label}: {type(e).__name__}: {e}")
                continue

            self.engine_name = label
            self.available = True
            self.error = None
            logger.info(f"✅ OCR 引擎加载成功: {label}")
            return

        # 重要——此处绝不能抛，否则 knowledge_api 进程会起不来。
        self._engine = None
        self.available = False
        self.error = " | ".join(errors) if errors else "未安装任何 OCR 后端"
        logger.warning(
            f"⚠️ OCR 引擎不可用（{self.error}），图片文字将不入库；"
            "如需识别图片文字，请安装 rapidocr-onnxruntime（glibc >= 2.27）"
            "或 rapidocr-openvino（glibc 2.17 老系统，需配 openvino 2024.x）"
        )

    def is_available(self) -> bool:
        """OCR 是否可用（对齐 Reranker.is_available）"""
        return self.available and self._engine is not None

    def image_to_text(self, image: bytes) -> str:
        """识别图片字节中的文字，返回按行拼接的文本；不可用/失败返回空串。"""
        if not self.is_available() or not image:
            return ""

        try:
            result, _elapse = self._engine(image)
        except Exception as first_err:
            # rapidocr 各版本对 bytes 入参支持不一致，退回自行解码成 ndarray 再试一次
            try:
                import cv2
                import numpy as np
                arr = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
                if arr is None:
                    raise ValueError("图片解码失败")
                result, _elapse = self._engine(arr)
            except Exception as e:
                logger.warning(f"OCR 识别失败（忽略该图）: {first_err} / 重试: {e}")
                return ""

        return self._join_result(result)

    @staticmethod
    def _join_result(result) -> str:
        """把 rapidocr 的 [[box, text, score], ...] 结果拼成文本"""
        if not result:
            return ""
        lines: List[str] = []
        for item in result:
            try:
                text = item[1]
            except (TypeError, IndexError):
                continue
            if text and str(text).strip():
                lines.append(str(text).strip())
        return "\n".join(lines)

    def get_info(self) -> dict:
        """获取引擎信息（对齐 LocalEmbedder.get_model_info）"""
        return {
            "available": self.is_available(),
            "engine": self.engine_name,
            "error": self.error,
        }


# ──────────────────────────────────────────────────────────────
# 进程级单例（C-1）：knowledge_service 每次上传都取同一个引擎
# ──────────────────────────────────────────────────────────────

_OCR_SINGLETON: Optional["OCREngine"] = None


def get_ocr_engine() -> "OCREngine":
    """获取进程级 OCREngine 单例（C-1）。

    RapidOCR 初始化要加载 det/cls/rec 三个 ONNX 模型（约 15MB），
    进程内只需一份；上传/重建等多处调用共用同一实例。
    """
    global _OCR_SINGLETON
    if _OCR_SINGLETON is None:
        _OCR_SINGLETON = OCREngine()
    return _OCR_SINGLETON


def image_pixel_size(image: bytes) -> Optional[Tuple[int, int]]:
    """读取图片像素尺寸 (宽, 高)，用于过滤图标/logo。

    Pillow 不可用或图片无法解码时返回 None（调用方按「不跳过」处理）。
    """
    if not image:
        return None
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(image)) as im:
            return im.size
    except Exception:
        return None
