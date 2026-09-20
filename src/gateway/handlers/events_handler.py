"""
事件索引系统处理器

处理事件相关的 HTTP 请求
"""

from dataclasses import asdict
from typing import Dict, Any, Optional
from src.reflection import get_events_index


class EventsHandler:
    """事件索引系统处理器"""

    @staticmethod
    async def search(request: Any) -> Dict[str, Any]:
        """搜索事件"""
        try:
            query = request.query_params.get("q", "")
            limit = int(request.query_params.get("limit", 10))

            if not query:
                return {"success": False, "error": "缺少查询参数 q"}

            events_index = get_events_index()
            results = events_index.search(query, limit)

            return {
                "success": True,
                "data": {
                    "query": query,
                    "results": [asdict(e) for e in results]
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def recent(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取最近事件"""
        try:
            limit = 20
            if request is not None and hasattr(request, 'query_params'):
                limit = int(request.query_params.get("limit", 20))

            events_index = get_events_index()
            events = events_index.get_recent(limit)

            return {
                "success": True,
                "data": {
                    "events": [asdict(e) for e in events]
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def stats(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取事件统计"""
        try:
            events_index = get_events_index()
            stats = events_index.get_stats()

            return {
                "success": True,
                "data": stats
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def add(request: Any) -> Dict[str, Any]:
        """添加事件"""
        try:
            body = await request.json()
            title = body.get("title", "")
            category = body.get("category", "general")
            content = body.get("content", "")
            importance = body.get("importance", "normal")
            tags = body.get("tags", [])

            if not title:
                return {"success": False, "error": "缺少标题"}

            events_index = get_events_index()
            event_id = events_index.add_event(title, category, content, importance, tags=tags)

            return {
                "success": True,
                "message": f"事件已添加: {event_id}",
                "data": {"event_id": event_id}
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
