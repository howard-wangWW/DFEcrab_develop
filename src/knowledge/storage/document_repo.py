# src/knowledge/storage/document_repo.py
"""
文档仓库管理
"""
import os
import json
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict, field
import logging

from ..paths import KNOWLEDGE_BASE, MEDIA_DIR, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass
class DocumentInfo:
    """文档信息"""
    doc_id: str
    file_name: str
    file_path: str
    file_type: str
    category: str
    title: str
    description: str = ""
    upload_time: str = ""
    file_size: int = 0
    status: str = "pending"  # pending, processing, processed, indexed, failed
    chunk_count: int = 0


def store_document_images(repo: "DocumentRepository", doc_id: str,
                          images: List[dict]) -> Dict[str, Dict]:
    """把 DocumentLoader.last_images 里的原图写到 media/{doc_id}/，
    返回 {文件名: {"ocr_text", "url"}}，供切片器给图片片挂 images（展示）与
    content（检索位）。

    三条入库通路共用：knowledge_service.upload_document、
    scripts/import_knowledge.py、scripts/rebuild_knowledge_chunks.py。
    漏掉任何一条，那条通路的切片就会只有占位块、没有图内文字进检索。

    降级原则：**落盘失败绝不能让上传/重建整体失败**。单张失败就跳过该张
    （正文里仍留着占位块，前端取图会 404，日志有明确记录）；目录都建不出来
    就整体放弃，此时切片退化为纯文本（与改造前行为一致）。
    """
    if not images:
        return {}

    try:
        media_dir = repo.get_media_dir(doc_id, create=True)
    except Exception as e:
        logger.warning(f"⚠️ 图片目录创建失败，本次不落盘图片（切片退化为纯文本）: {e}")
        return {}

    result: Dict[str, Dict] = {}
    total_bytes = 0
    for item in images:
        name = (item.get("name") or "").strip()
        blob = item.get("blob") or b""
        if not name or not blob:
            continue
        try:
            (media_dir / name).write_bytes(blob)
        except Exception as e:
            logger.warning(f"⚠️ 图片落盘失败，前端将取不到该图: {name} ({e})")
            continue
        total_bytes += len(blob)
        result[name] = {
            "ocr_text": item.get("ocr_text") or "",
            "url": f"/knowledge/media/{doc_id}/{name}",
        }

    # doc_id 是内容寻址：同内容重传会解析出同一批图。但改了 max_images / dpi
    # 之后可能少几张，残留旧文件会让前端拿到已无切片引用的图 —— 清掉。
    try:
        for old in media_dir.iterdir():
            if old.is_file() and old.name not in result:
                old.unlink()
    except Exception as e:
        logger.warning(f"⚠️ 清理过期图片失败（忽略）: {e}")

    if result:
        logger.info(
            f"🖼️  图片入库 {len(result)}/{len(images)} 张"
            f"（约 {total_bytes / 1024 / 1024:.1f} MB）→ {media_dir}"
        )
    return result


class DocumentRepository:
    """文档仓库管理"""
    
    # 白名单统一来自 paths.SUPPORTED_EXTENSIONS（单一事实源，避免与 document_loader 漂移）
    SUPPORTED_TYPES = set(SUPPORTED_EXTENSIONS)
    DEFAULT_CATEGORIES = ['power_grid', 'operation_manual', 'training', 'cases', 'other']
    
    def __init__(self, base_dir: Optional[str] = None):
        # 默认锚定项目根下的 knowledge_base，消除 CWD 依赖（改目录启动也能定位到同一数据）
        self.base_dir = Path(base_dir) if base_dir else KNOWLEDGE_BASE
        self.documents_dir = self.base_dir / "documents"
        self.processed_dir = self.base_dir / "processed"
        self.index_dir = self.base_dir / "index"
        self.cache_dir = self.base_dir / "cache"
        self.config_dir = self.base_dir / "config"
        self.media_dir = self.base_dir / "media"
        
        self._create_directories()
        self.mapping_file = self.config_dir / "document_mapping.json"
        self.documents: Dict[str, DocumentInfo] = self._load_mapping()

    def _create_directories(self):
        """创建目录"""
        for dir_path in [self.documents_dir, self.processed_dir,
                         self.index_dir, self.cache_dir, self.config_dir,
                         self.media_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        for cat in self.DEFAULT_CATEGORIES:
            (self.documents_dir / cat).mkdir(exist_ok=True)
    
    def _load_mapping(self) -> Dict[str, DocumentInfo]:
        """加载文档映射"""
        if not self.mapping_file.exists():
            return {}
        
        try:
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    doc_id: DocumentInfo(**doc_data)
                    for doc_id, doc_data in data.items()
                }
        except Exception as e:
            logger.error(f"加载文档映射失败: {e}")
            return {}
    
    def _save_mapping(self):
        """保存文档映射"""
        data = {
            doc_id: asdict(doc_info)
            for doc_id, doc_info in self.documents.items()
        }
        with open(self.mapping_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def add_document(self, file_path: str, category: str = "other",
                     title: str = None, description: str = "",
                     original_name: str = None) -> DocumentInfo:
        """添加文档

        Args:
            original_name: 原始文件名。上传链路里的临时文件带 uuid 前缀，
                传入原始名可避免落盘 file_name 被污染（如 "07d4..._xxx.xlsx"）。
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        if file_path.suffix.lower() not in self.SUPPORTED_TYPES:
            raise ValueError(f"不支持的文件类型: {file_path.suffix}")
        
        # 支持自定义分类：分类非空即可，未知分类自动创建目录
        category = (category or "other").strip() or "other"
        
        # 生成ID
        file_hash = hashlib.md5(file_path.read_bytes()).hexdigest()[:16]
        doc_id = f"{category}_{file_hash}"
        
        # 检查是否已存在
        if doc_id in self.documents:
            existing = self.documents[doc_id]
            if existing.file_size == file_path.stat().st_size:
                logger.info(f"文档已存在: {file_path.name}")
                return existing
        
        # 复制文件（自定义分类目录可能不存在，自动创建）
        target_dir = self.documents_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        display_name = Path(original_name).name if original_name else file_path.name
        target_path = target_dir / display_name
        
        # 处理重名
        if target_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = Path(display_name).stem
            suffix = Path(display_name).suffix
            target_path = target_dir / f"{stem}_{timestamp}{suffix}"
        
        shutil.copy2(file_path, target_path)
        
        # 创建文档信息
        doc_info = DocumentInfo(
            doc_id=doc_id,
            file_name=target_path.name,
            file_path=str(target_path.relative_to(self.base_dir)),
            file_type=file_path.suffix.lower()[1:],
            category=category,
            title=title or file_path.stem,
            description=description,
            upload_time=datetime.now().isoformat(),
            file_size=file_path.stat().st_size,
            status="pending"
        )
        
        self.documents[doc_id] = doc_info
        self._save_mapping()
        
        logger.info(f"✅ 文档已添加: {doc_info.title} (ID: {doc_id})")
        return doc_info
    
    def list_documents(self, category: str = None, status: str = None) -> List[DocumentInfo]:
        """列出文档"""
        docs = list(self.documents.values())
        if category:
            docs = [d for d in docs if d.category == category]
        if status:
            docs = [d for d in docs if d.status == status]
        return sorted(docs, key=lambda x: x.upload_time, reverse=True)
    
    def get_document(self, doc_id: str) -> Optional[DocumentInfo]:
        return self.documents.get(doc_id)

    def list_categories(self) -> List[str]:
        """列出所有可用分类（默认分类 ∪ 文档已用分类）"""
        used = {d.category for d in self.documents.values()}
        return sorted(set(self.DEFAULT_CATEGORIES) | used)
    
    def update_title(self, doc_id: str, title: str) -> bool:
        """更新文档标题（标题提取后回填；title 为空则忽略）"""
        if doc_id in self.documents and title:
            self.documents[doc_id].title = title
            self._save_mapping()
            return True
        return False

    def update_status(self, doc_id: str, status: str, chunk_count: int = None):
        if doc_id in self.documents:
            self.documents[doc_id].status = status
            if chunk_count is not None:
                self.documents[doc_id].chunk_count = chunk_count
            self._save_mapping()
            return True
        return False
    
    def get_document_path(self, doc_id: str) -> Optional[Path]:
        if doc_id not in self.documents:
            return None
        return self.base_dir / self.documents[doc_id].file_path
    
    def get_processed_text_path(self, doc_id: str) -> Path:
        path = self.processed_dir / "parsed" / f"{doc_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_chunks_path(self, doc_id: str) -> Path:
        path = self.processed_dir / "chunks" / f"{doc_id}_chunks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_media_dir(self, doc_id: str, create: bool = False) -> Path:
        """文档内嵌图片目录（knowledge_base/media/{doc_id}/）

        create=False 时只算路径不建目录 —— 取图路由要靠「路径存在与否」判断 404，
        不能因为取一次图就把空目录建出来。
        """
        path = self.media_dir / doc_id
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def delete_document(self, doc_id: str) -> bool:
        if doc_id not in self.documents:
            return False
        
        doc_info = self.documents[doc_id]
        file_path = self.base_dir / doc_info.file_path
        if file_path.exists():
            file_path.unlink()
        
        for path in [self.get_processed_text_path(doc_id),
                     self.get_chunks_path(doc_id)]:
            if path.exists():
                path.unlink()

        # 切片正文里的图片占位块会失效，原图一并清掉，避免 media 目录只增不减
        media_dir = self.get_media_dir(doc_id)
        if media_dir.exists():
            shutil.rmtree(media_dir, ignore_errors=True)

        del self.documents[doc_id]
        self._save_mapping()
        logger.info(f"文档已删除: {doc_info.title}")
        return True
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        total_docs = len(self.documents)
        total_chunks = sum(d.chunk_count for d in self.documents.values())
        by_category = {}
        by_status = {}
        
        for doc in self.documents.values():
            by_category[doc.category] = by_category.get(doc.category, 0) + 1
            by_status[doc.status] = by_status.get(doc.status, 0) + 1
        
        return {
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "by_category": by_category,
            "by_status": by_status,
            "last_updated": datetime.now().isoformat()
        }
