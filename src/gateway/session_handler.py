"""
会话管理核心逻辑 —— HTTP/WS 共用

将 HTTP REST 端点和 WebSocket 消息处理器中调用 SessionManager 的核心逻辑抽取为
协议无关的服务层，保证两边的行为完全一致：每一行业务逻辑只写一份，HTTP/WS 只是
协议适配层（解析自己的协议 -> 调用 SessionService -> 包装成自己的协议返回）。
"""

from typing import Dict, Any, Optional

from src.session.manager import get_session_manager
from src.gateway.permission import PermissionService

logger = None


def _get_logger():
    global logger
    if logger is None:
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
    return logger


class SessionService:
    """会话管理服务（协议无关）"""

    @staticmethod
    def list_sessions(user_id: Optional[str] = None, limit: int = 50,
                      include_empty: bool = False) -> Dict[str, Any]:
        """列出会话（数据范围 all 看全部，own 只看自己的）

        include_empty: 是否包含空会话（默认 False，空会话仅在内存暂存、列表不展示）。
        """
        try:
            session_mgr = get_session_manager()
            filter_user_id = None if PermissionService().data_scope_of(user_id or "") == "all" else user_id
            sessions = session_mgr.list_sessions(
                limit=limit,
                user_id=filter_user_id,
                include_empty=include_empty,
            )
            return {
                "success": True,
                "count": len(sessions),
                "sessions": [session_mgr.session_to_dict(s, load_messages=True) for s in sessions]
            }
        except Exception as e:
            _get_logger().error(f"列出会话失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def create_session(user_id: str = "default", topic: Optional[str] = None) -> Dict[str, Any]:
        """创建新会话"""
        try:
            from src.session.manager import ClientType
            session_mgr = get_session_manager()
            session = session_mgr.create_session(
                user_id=user_id,
                topic=topic,
                client_type=ClientType.API
            )
            _get_logger().info(f"🆕 创建新会话: {session.id}")
            return {
                "success": True,
                "session": session_mgr.session_to_dict(session, load_messages=False)
            }
        except Exception as e:
            _get_logger().error(f"创建会话失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_session(session_id: str, current_user: str = "default") -> Dict[str, Any]:
        """获取会话详情（带权限检查）"""
        try:
            session_mgr = get_session_manager()
            session = session_mgr.get_session(session_id)
            if not session:
                return {"success": False, "error": f"会话不存在或已过期: {session_id}"}
            if not PermissionService().can_access_record(current_user or "", "read", session.user_id):
                return {"success": False, "error": "无权限访问此会话"}
            return {"success": True, "session": session_mgr.session_to_dict(session, load_messages=True)}
        except Exception as e:
            _get_logger().error(f"获取会话失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_session_messages(session_id: str, current_user: str = "default",
                             limit: int = 20) -> Dict[str, Any]:
        """获取会话消息历史（带权限检查）"""
        try:
            session_mgr = get_session_manager()
            # 先获取 session 做权限检查
            session = session_mgr.get_session(session_id)
            if not session:
                return {"success": False, "error": f"会话不存在或已过期: {session_id}"}
            if not PermissionService().can_access_record(current_user or "", "read", session.user_id):
                return {"success": False, "error": "无权限访问此会话"}
            messages = session_mgr.get_messages_as_dicts(session_id, limit=limit)
            # ★ 为每条 assistant 消息附加「上下文占用统计」（每轮上下文占比/水位），
            #   数据来自已落库 tokens.prompt + metadata.context_length + model。
            #   旧数据（P3 前落库，无 context_length）不附加，前端做空值兜底。
            for m in messages:
                if m.get("role") != "assistant":
                    continue
                tk = m.get("tokens") or {}
                prompt = int(tk.get("prompt") or 0)
                clen = int((m.get("metadata") or {}).get("context_length") or 0)
                if prompt > 0 and clen > 0:
                    m["context_usage"] = {
                        "prompt_tokens": prompt,
                        "completion_tokens": int(tk.get("completion") or 0),
                        "total_tokens": int(tk.get("total") or 0),
                        "context_length": clen,
                        "used_percent": round(prompt / clen * 100, 1),
                        "free_space": max(0, clen - prompt),
                        "model": m.get("model"),
                    }
            return {"success": True, "count": len(messages), "messages": messages}
        except Exception as e:
            _get_logger().error(f"获取会话消息失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def delete_session(session_id: str, current_user: str = "default") -> Dict[str, Any]:
        """删除会话（带权限检查）"""
        try:
            session_mgr = get_session_manager()
            # 权限检查
            session = session_mgr.get_session(session_id)
            if not session:
                return {"success": False, "error": f"会话不存在或已过期: {session_id}"}
            if not PermissionService().can_access_record(current_user or "", "write", session.user_id):
                return {"success": False, "error": "无权限删除此会话"}
            success = session_mgr.delete_session(session_id)
            if success:
                # ★ 批次12步骤3：删会话联动清理该会话全部附件（注册记录 + 落盘目录）
                #   幂等、best-effort；清理失败不影响会话删除结果，仅记日志
                try:
                    from src.files.service import FileService
                    _pr = FileService.purge_session(session_id)
                    if _pr.get("removed_records"):
                        _get_logger().info(
                            f"[Files] 删会话联动清理: session={session_id}, "
                            f"records={_pr['removed_records']}, path={_pr.get('removed_path')}"
                        )
                    elif _pr.get("error"):
                        _get_logger().warning(
                            f"[Files] 删会话联动清理异常: session={session_id}, {_pr['error']}"
                        )
                except Exception as e:
                    _get_logger().warning(f"[Files] 删会话联动清理异常: session={session_id}, {e}")
                return {"success": True, "message": f"会话已删除: {session_id}"}
            return {"success": False, "error": f"删除会话失败: {session_id}"}
        except Exception as e:
            _get_logger().error(f"删除会话失败: {e}")
            return {"success": False, "error": str(e)}
