#!/usr/bin/env python3
"""
知识库独立API服务
端口: 6788
"""
import sys
import os
import signal
import logging
from pathlib import Path
from uuid import uuid4

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# ★ 配置根 logger：src.knowledge 模块大量 logger.info/warning 依赖此配置输出到 stdout
#   （nohup 重定向后可落盘），否则"索引不存在/降级模式/初始化失败"等关键信息全部丢失。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from fastapi import FastAPI, APIRouter, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import uvicorn
import json
import logging

from src.knowledge.knowledge_service import get_knowledge_service
from src.knowledge.paths import KNOWLEDGE_VERSION

logger = logging.getLogger(__name__)

# ============ 创建应用 ============
app = FastAPI(
    title="DFEcrab 知识库API",
    version=KNOWLEDGE_VERSION,
    description="独立的知识库服务，提供文档上传、检索、问答功能"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# ============ 请求模型 ============
class SearchRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5
    category: Optional[str] = None


class ChatRequest(BaseModel):
    question: str
    top_k: Optional[int] = 5
    category: Optional[str] = None


# ============ API接口 ============

@router.get("/health")
async def health_check():
    """健康检查

    额外暴露索引维度一致性（version / index_dim / embed_dim / mismatch），
    用于快速定位「索引维度 ≠ 嵌入模型维度」导致的检索异常；诊断失败时该组字段可能缺省。
    """
    try:
        service = get_knowledge_service()
        stats = service.get_stats()
        result = {
            "status": "healthy",
            "service": "knowledge_api",
            "version": KNOWLEDGE_VERSION,
            "total_documents": stats.get("total_documents", 0),
            "total_chunks": stats.get("total_chunks", 0),
        }
        # 维度诊断：磁盘索引维度 vs 当前嵌入模型维度（任何异常都不影响健康检查本身）
        try:
            from src.knowledge.paths import INDEX_DIR
            index_dim = None
            cfg_file = INDEX_DIR / "config.json"
            if cfg_file.exists():
                index_dim = json.loads(cfg_file.read_text(encoding="utf-8")).get("dim")
            embed_dim = None
            skill = getattr(service, "skill", None)
            engine = getattr(skill, "rag_engine", None) if skill else None
            retriever = getattr(engine, "retriever", None) if engine else None
            embedder = getattr(retriever, "embedder", None) if retriever else None
            if embedder is not None:
                embed_dim = embedder.get_dim()
            result["index_dim"] = index_dim
            result["embed_dim"] = embed_dim
            result["mismatch"] = bool(
                index_dim is not None and embed_dim is not None and index_dim != embed_dim
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"健康检查维度诊断失败（忽略）: {e}")
        return result
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    category: str = Form("other"),
    title: Optional[str] = Form(None)
):
    """上传文档到知识库（category 支持自定义，未知分类自动创建）

    - 流式分块落盘，避免大文件整体读入内存导致 OOM
    - 大小上限配置化（gateway.yaml knowledge.upload_max_mb，默认 50MB），超限返回 413
    """
    temp_path = None
    try:
        from config.port_loader import knowledge_upload_max_mb
        max_mb = knowledge_upload_max_mb()
        max_bytes = max_mb * 1024 * 1024

        safe_name = Path(file.filename or "upload.bin").name
        temp_dir = Path("/tmp/knowledge_uploads")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{uuid4().hex}_{safe_name}"

        total = 0
        with open(temp_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        413,
                        f"文件超过大小限制 {max_mb}MB，请先拆分或压缩后再上传",
                    )
                f.write(chunk)

        if total == 0:
            raise HTTPException(400, "文件为空")

        service = get_knowledge_service()
        result = service.upload_document(
            temp_path=str(temp_path),
            filename=file.filename or safe_name,
            category=category,
            title=title
        )

        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "上传失败"))
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


@router.post("/search")
async def search(request: SearchRequest):
    """检索文档内容，支持按分类过滤（含自定义分类）"""
    try:
        service = get_knowledge_service()
        result = service.search(
            query=request.query,
            top_k=request.top_k,
            category=request.category
        )
        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "检索失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/chat")
async def chat(request: ChatRequest):
    """问答对话，支持按分类过滤（含自定义分类）"""
    try:
        service = get_knowledge_service()
        result = service.chat(
            question=request.question,
            top_k=request.top_k,
            category=request.category
        )
        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "问答失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/documents")
async def list_documents():
    """列出所有文档"""
    try:
        service = get_knowledge_service()
        result = service.list_documents()
        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "获取失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(doc_id: str):
    """
    获取文档的所有切片内容（按顺序排列）

    返回格式化的切片列表，方便前台展示

    示例:
    GET /knowledge/documents/power_grid_abc123/chunks
    """
    try:
        service = get_knowledge_service()
        result = service.get_document_chunks(doc_id)

        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "获取失败"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/knowledge-bases")
async def list_knowledge_bases():
    """列出知识库（扁平模型：仅一个默认知识库，含全部文档统计）"""
    try:
        service = get_knowledge_service()
        result = service.list_knowledge_bases()
        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "获取失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/categories")
async def list_categories():
    """列出所有可用分类（默认分类 ∪ 文档已用分类，支持自定义）"""
    try:
        service = get_knowledge_service()
        result = service.list_categories()
        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "获取失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档"""
    try:
        service = get_knowledge_service()
        result = service.delete_document(doc_id)
        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "删除失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/stats")
async def get_stats():
    """获取统计信息"""
    try:
        service = get_knowledge_service()
        result = service.get_stats()
        if result["status"] == "error":
            raise HTTPException(400, result.get("message", "获取失败"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


app.include_router(router)


# ============ 启动入口 ============
def run(host: str = "0.0.0.0", port: Optional[int] = None):
    """启动知识库API服务（端口默认从 gateway.yaml 读取）"""
    if port is None:
        # 默认端口从 gateway.yaml local_ports.knowledge_api 读取（单一事实源）
        from config.port_loader import knowledge_api_port
        port = knowledge_api_port(6788)
    print(f"📚 知识库API服务启动: http://{host}:{port}")
    print(f"📖 API文档: http://{host}:{port}/docs")
    print("")
    print("可用接口:")
    print(f"  GET  /knowledge/health                - 健康检查")
    print(f"  POST /knowledge/upload                - 上传文档")
    print(f"  POST /knowledge/search                - 检索内容")
    print(f"  POST /knowledge/chat                  - 问答对话")
    print(f"  GET  /knowledge/documents                 - 列出文档")
    print(f"  GET  /knowledge/documents/{{doc_id}}/chunks - 查看切片")
    print(f"  GET  /knowledge/knowledge-bases           - 列出知识库")
    print(f"  DELETE /knowledge/documents/{{id}}    - 删除文档")
    print(f"  GET  /knowledge/stats                 - 统计信息")
    print("")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    # 默认端口从 gateway.yaml local_ports.knowledge_api 读取（单一事实源）
    from config.port_loader import knowledge_api_port
    default_port = knowledge_api_port(6788)
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=default_port)
    args = parser.parse_args()
    run(args.host, args.port)
