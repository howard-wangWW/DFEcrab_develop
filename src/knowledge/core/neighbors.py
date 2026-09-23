# src/knowledge/core/neighbors.py
"""
图片「邻近带出」（2026-09-11）

图片片**不进索引**（见 DocumentProcessor._image_chunk_meta）：它们没有检索文本，
既不进向量库也不进 BM25 语料，所以搜不到、也无需去搜。让用户看到图的路径是——

    搜到图片附近的正文 → 顺带把那张图带出来

依据是切片文件里的**数组顺序**：加载器已按文档顺序输出（document_loader._load_docx），
切片器按同一顺序成片，因此 chunks.json 里的下标就是文档位置。命中片 i 取
[i-radius, i+radius] 窗口内的图片片，挂到该结果上。

为什么不做 OCR 索引：界面截图 / SCADA 系统图里大部分文字与上下文无关，
OCR 按检测框输出的破碎文本命中率低、还把噪声引进检索（现场反馈）。

设计取舍：
- **只做增强，不做拦截**：任何一步失败（文件读不到、JSON 坏了、字段缺失）都静默跳过，
  检索结果本身一个字节都不该因此改变。
- 同一篇文档只读一次盘 —— 一遍检索里常常命中同文档多片。
- 按 URL 去重：一张图在同一条结果里只出现一次。
- 只按「数组下标」定位，**不解析 chunk_id 里的序号** —— 那串 md5 不可反解。
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .document_processor import is_image_chunk

logger = logging.getLogger(__name__)

# 默认片距：命中片前后各 1 片。图片通常是「图 + 标题 + 说明」紧挨着正文，
# ±1 足以覆盖，且不会把一整章的图都拖出来。
DEFAULT_RADIUS = 1

# 单条结果最多挂几张图（一张图被多个命中片同时带出时的兜底上限）
MAX_IMAGES_PER_RESULT = 8

# doc_id → (chunks, {chunk_id: 下标})；值为 None 表示读失败/不存在（负缓存）
_CacheValue = Optional[Tuple[list, Dict[str, int]]]


def _load_doc_chunks(repo, doc_id: str, cache: Dict[str, _CacheValue]) -> _CacheValue:
    """读某文档的切片列表并建 id→下标 索引；失败/不存在返回 None（负缓存）"""
    if doc_id in cache:
        return cache[doc_id]

    value: _CacheValue = None
    try:
        path = Path(repo.get_chunks_path(doc_id))
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                chunks = json.load(f)
            if isinstance(chunks, list):
                value = (chunks, {
                    c.get("id"): i
                    for i, c in enumerate(chunks)
                    if isinstance(c, dict) and c.get("id")
                })
    except Exception as e:
        logger.debug(f"[KB/邻近带图] 读取切片失败 doc_id={doc_id}: {e}")

    cache[doc_id] = value
    return value


def collect_neighbor_images(repo, doc_id: str, chunk_id: str, radius: int,
                            cache: Dict[str, _CacheValue]) -> List[Dict]:
    """取 chunk_id 前后 ±radius 片范围内的图片片，返回 [{name, url}, ...]

    按窗口内的出现顺序返回（即文档顺序）；同一条结果里按 url 去重。
    """
    loaded = _load_doc_chunks(repo, doc_id, cache)
    if not loaded:
        return []

    chunks, id_to_index = loaded
    index = id_to_index.get(chunk_id)
    if index is None:
        # 切片文件与索引不同步（如刚上传、索引还没重建）时静默跳过
        return []

    lo = max(0, index - radius)
    hi = min(len(chunks), index + radius + 1)

    images: List[Dict] = []
    seen_urls = set()
    for chunk in chunks[lo:hi]:
        if not isinstance(chunk, dict):
            continue
        meta = chunk.get("metadata") or {}
        if not is_image_chunk(meta):
            continue
        for img in meta.get("images") or []:
            if not isinstance(img, dict):
                continue
            url = img.get("url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            images.append({"name": img.get("name", ""), "url": url})
            if len(images) >= MAX_IMAGES_PER_RESULT:
                return images
    return images


def attach_neighbor_images(repo, results: List[Dict], radius: int = DEFAULT_RADIUS) -> int:
    """给每条命中结果挂上「同文档内邻近的图片片」（**就地修改** results）

    Args:
        repo:    DocumentRepo，需实现 get_chunks_path(doc_id)
        results: 命中列表，每项需含 "id"（chunk_id）与 "metadata"（含 doc_id）
        radius:  片距；0 = 只取命中片自身的图，<0 = 关闭带图

    Returns:
        本次新挂上的图片张数（去重后）。

    契约说明：图片写进 ``result["metadata"]["images"]``，与批次 19 里
    「图片片自身的 metadata.images」是**同一个键**——前端不用改渲染逻辑，
    只是这里给的是「**该结果附近的**图」，可能不止一张。
    """
    try:
        radius = int(radius)
    except (TypeError, ValueError):
        radius = DEFAULT_RADIUS
    if not results or radius < 0:
        return 0

    cache: Dict[str, _CacheValue] = {}
    attached = 0

    for item in results:
        try:
            if not isinstance(item, dict):
                continue
            meta = item.get("metadata")
            if not isinstance(meta, dict):
                meta = {}
                item["metadata"] = meta

            doc_id = meta.get("doc_id") or ""
            chunk_id = item.get("id") or ""
            if not doc_id or not chunk_id:
                continue

            found = collect_neighbor_images(repo, doc_id, chunk_id, radius, cache)
            if not found:
                continue

            existing = [i for i in (meta.get("images") or []) if isinstance(i, dict)]
            seen_urls = {i.get("url") for i in existing}

            merged = list(existing)
            for img in found:
                if img["url"] in seen_urls:
                    continue
                seen_urls.add(img["url"])
                merged.append(img)

            if len(merged) > len(existing):
                meta["images"] = merged
                attached += len(merged) - len(existing)
        except Exception as e:
            # 单条失败不影响其它结果，更不影响检索本身
            logger.debug(f"[KB/邻近带图] 处理失败（跳过该条）: {e}")
            continue

    return attached
