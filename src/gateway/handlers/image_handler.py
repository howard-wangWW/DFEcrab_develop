"""
ImageHandler - 图片生成与访问接口

路由（注册见 grpc_server._register_routes）：
    POST   /api/images/generate       生成图片            [write]
    GET    /api/images                列出已生成图片      [read]
    GET    /api/images/{image_id}     二进制直出 PNG      [read]
    DELETE /api/images/{image_id}     删除图片            [write]

权限口径：
    - 列表 / 删除：普通用户只能操作自己的（admin 可指定 ?user_id=）
    - 二进制直出：不做归属校验——``image_id`` 为 16 位随机 hex（capability URL），
      这样前端 ``<img src="/api/images/xxx">`` 才能在不带自定义请求头的情况下加载。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from src.gateway.http.server import HTTPResponse

logger = logging.getLogger(__name__)


class ImageHandler:
    """图片生成处理器（无状态，均为 staticmethod）"""

    # ──────────────────────────────────────────────────────
    # 内部
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _current_user(request) -> str:
        return request.headers.get("x-user-id", "default") or "default"

    @staticmethod
    def _is_admin(request) -> bool:
        try:
            from src.gateway.permission import PermissionService
            return PermissionService().is_admin(ImageHandler._current_user(request))
        except Exception:
            return False

    # ──────────────────────────────────────────────────────
    # 接口
    # ──────────────────────────────────────────────────────

    # 画廊页面（纯静态资源，前端 JS 自己拉 /api/images 渲染 <img>）
    _GALLERY_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DFEcrab 图片画廊</title>
<style>
  body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
  header{padding:16px 20px;border-bottom:1px solid #232733;position:sticky;top:0;background:#0f1115}
  h1{margin:0;font-size:16px}
  .meta{color:#8b93a7;font-size:12px;margin-top:4px}
  main{padding:20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
  figure{margin:0;background:#161a22;border:1px solid #232733;border-radius:10px;overflow:hidden}
  img{width:100%;display:block;background:#0b0d12}
  figcaption{padding:10px 12px;font-size:12px;color:#b9c0d0;word-break:break-word}
  .err{color:#ff6b6b}.empty{color:#8b93a7}
</style>
</head>
<body>
<header><h1>DFEcrab 图片画廊</h1><div class="meta" id="meta">加载中…</div></header>
<main id="grid"></main>
<script>
var grid=document.getElementById('grid'),meta=document.getElementById('meta');
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function pick(o,keys){for(var i=0;i<keys.length;i++){if(o[keys[i]])return o[keys[i]];}return '';}
async function load(){
  try{
    var r=await fetch('/api/images?limit=200',{headers:{'X-User-ID':'default'}});
    if(!r.ok)throw new Error('HTTP '+r.status);
    var d=await r.json();
    var items=d.items||d.images||d.data||[];
    meta.textContent='共 '+items.length+' 张';
    if(!items.length){grid.innerHTML='<p class="empty">还没有图片。让智能体画一张后刷新本页。</p>';return;}
    grid.innerHTML=items.map(function(it){
      var id=pick(it,['image_id','id']);
      var p=pick(it,['prompt','Prompt']);
      var ts=pick(it,['created_at','timestamp','ts']);
      var sz=pick(it,['size']);
      return '<figure><img loading="lazy" src="/api/images/'+esc(id)+'" alt="'+esc(String(p).slice(0,60))+'">'
        +'<figcaption><div>'+esc(ts)+' · '+esc(sz)+'</div>'
        +'<div style="margin-top:6px">'+esc(String(p).slice(0,160))+'</div>'
        +'</figcaption></figure>';
    }).join('');
  }catch(e){
    grid.innerHTML='<p class="err">加载失败：'+esc(e.message)+'</p>';
    meta.textContent='加载失败';
  }
}
load();
</script>
</body></html>"""

    @staticmethod
    async def gallery(request) -> Any:
        """图片画廊：GET /api/images/gallery

        存在的理由：项目当前唯一的交互界面是终端 TUI（Ink），而 Ink 只能渲染文本、
        无法显示位图——图片就算生成成功，用户在界面上也看不见。
        这里提供一个最小可用的 Web 视图，配合 GET /api/images/{id} 的二进制直出，
        即可在浏览器中看到智能体生成的图片。

        ★ 路由顺序：必须注册在 "/api/images/{image_id}" 之前，否则会被通配规则抢占。
        """
        resp = HTTPResponse().text(ImageHandler._GALLERY_HTML)
        resp.headers["Content-Type"] = "text/html; charset=utf-8"
        return resp

    @staticmethod
    async def generate(request) -> Any:
        """生成图片：POST /api/images/generate

        body: {"prompt": "...", "size": "1024x1024", "n": 1, "provider": "...", "session_id": "..."}
        """
        from src.services.image_service import ImageProviderError, get_image_service

        try:
            body = await request.json()
        except Exception:
            body = {}

        prompt = body.get("prompt") or request.query_params.get("prompt") or ""
        user_id = str(body.get("user_id") or ImageHandler._current_user(request))
        session_id = str(body.get("session_id") or "")

        service = get_image_service()
        try:
            # 图片生成是同步阻塞调用（requests），放线程池避免阻塞事件循环
            result = await asyncio.to_thread(
                service.generate,
                prompt,
                body.get("size"),
                body.get("n", 1),
                body.get("provider"),
                user_id,
                session_id,
            )
        except ImageProviderError as exc:
            return HTTPResponse(400).json({"success": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ImageHandler] 生成失败: {exc}", exc_info=True)
            return HTTPResponse(500).json({"success": False, "error": f"图片生成失败: {exc}"})

        return {"success": True, **result}

    @staticmethod
    async def list_images(request) -> Dict[str, Any]:
        """列出已生成图片：GET /api/images?date=&limit=&offset="""
        from src.services.image_service import get_image_service

        current_user = ImageHandler._current_user(request)
        is_admin = ImageHandler._is_admin(request)
        requested_user = (request.query_params.get("user_id") or "").strip()
        user_filter = (requested_user or None) if is_admin else current_user

        service = get_image_service()
        day = (request.query_params.get("date") or "").strip() or None
        limit = request.query_params.get("limit", 50)
        offset = request.query_params.get("offset", 0)

        data = await asyncio.to_thread(
            service.list_images, day, user_filter, limit, offset
        )
        return {
            "success": True,
            "scope": {"current_user": current_user, "is_admin": is_admin},
            "date": day,
            "user_id": user_filter or "*",
            **data,
        }

    @staticmethod
    async def get_image(request, image_id: str = "") -> Any:
        """二进制直出：GET /api/images/{image_id}"""
        from src.services.image_service import get_image_service

        image_id = image_id or request.path_params.get("image_id", "")
        service = get_image_service()
        record = await asyncio.to_thread(service.get_image, image_id)
        if not record:
            return HTTPResponse(404).json({"success": False, "error": f"图片不存在: {image_id}"})

        try:
            blob = Path(record["path"]).read_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[ImageHandler] 读取图片失败 {image_id}: {exc}")
            return HTTPResponse(500).json({"success": False, "error": "读取图片文件失败"})

        response = HTTPResponse(200)
        response.bytes(blob, "image/png")
        response.headers["Cache-Control"] = "public, max-age=86400"
        response.headers["Content-Disposition"] = f'inline; filename="{image_id}.png"'
        return response

    @staticmethod
    async def delete_image(request, image_id: str = "") -> Any:
        """删除图片：DELETE /api/images/{image_id}"""
        from src.services.image_service import get_image_service

        image_id = image_id or request.path_params.get("image_id", "")
        current_user = ImageHandler._current_user(request)
        is_admin = ImageHandler._is_admin(request)

        service = get_image_service()
        record = await asyncio.to_thread(service.get_image, image_id)
        if not record:
            return HTTPResponse(404).json({"success": False, "error": f"图片不存在: {image_id}"})

        owner = str(record.get("user_id") or "")
        if not is_admin and owner and owner != current_user:
            return HTTPResponse(403).json({"success": False, "error": "无权限删除该图片"})

        result = await asyncio.to_thread(service.delete_image, image_id)
        if not result.get("success"):
            return HTTPResponse(400).json(result)
        return result

    @staticmethod
    async def list_providers(request) -> Dict[str, Any]:
        """列出图片生成 Provider（脱敏）：GET /api/images/providers

        ★ 注意：该路径必须注册在 GET /api/images/{image_id} 之前，
        否则会被通配路径抢先匹配。
        """
        from src.services.image_service import get_image_service

        service = get_image_service()
        return {
            "success": True,
            "providers": service.list_providers(redact_secrets=True),
        }