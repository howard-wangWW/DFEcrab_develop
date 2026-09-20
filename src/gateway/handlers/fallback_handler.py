"""
Fallback Handler - 降级处理器
当主服务不可用时提供降级响应
"""

import logging
from typing import Optional, Dict, Any
from aiohttp import web

logger = logging.getLogger(__name__)


class FallbackHandler:
    """降级处理器"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        logger.info("✅ FallbackHandler 初始化完成")
    
    # ========== 类方法/静态方法（用于路由注册） ==========
    
    @staticmethod
    async def status(request):
        """获取降级服务状态 - 用于 /api/fallback/status 路由"""
        return web.json_response({
            "status": "healthy",
            "handler": "fallback",
            "enabled": True,
            "message": "降级服务运行正常"
        })
    
    @staticmethod
    async def handle(request):
        """处理降级请求 - 用于 /api/fallback/handle 路由"""
        logger.warning("⚠️ 触发降级处理")
        return web.json_response({
            "status": "fallback",
            "message": "服务暂时不可用，已触发降级响应",
            "data": None
        })
    
    # ========== 实例方法 ==========
    
    async def handle_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理降级请求（实例方法版本）"""
        logger.warning("⚠️ 触发降级处理")
        return {
            "status": "fallback",
            "message": "服务暂时不可用，已触发降级响应",
            "data": None
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "handler": "fallback",
            "enabled": True
        }
