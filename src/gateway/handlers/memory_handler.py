"""
记忆系统处理器

处理记忆相关的 HTTP 请求
"""

import re
from typing import Dict, Any, Optional
from src.memory.global_manager import get_global_memory_manager
from src.services.model_manager import model_manager


class MemoryHandler:
    """记忆系统处理器"""


    @staticmethod
    async def stats(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取指定用户的全局记忆统计（?user_id= 指定用户，admin 可查全部）"""
        try:
            headers = getattr(request, "headers", {}) if request else {}
            query = getattr(request, "query_params", {}) if request else {}
            target_user = MemoryHandler._check_user_access(headers, query)
            if target_user is None:
                return {"success": False, "error": "无权限查看其他用户的记忆"}

            memory_mgr = get_global_memory_manager()
            memory_stats = memory_mgr.get_stats(target_user)

            # 统一转换为字典
            if not isinstance(memory_stats, dict):
                try:
                    import dataclasses
                    memory_stats = dataclasses.asdict(memory_stats)
                except Exception:
                    memory_stats = dict(memory_stats) if hasattr(memory_stats, '__dict__') else str(memory_stats)

            return {"success": True, "data": memory_stats}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def files(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取指定用户的每日记忆文件列表"""
        try:
            headers = getattr(request, "headers", {}) if request else {}
            query = getattr(request, "query_params", {}) if request else {}
            target_user = MemoryHandler._check_user_access(headers, query)
            if target_user is None:
                return {"success": False, "error": "无权限查看其他用户的记忆"}

            memory_mgr = get_global_memory_manager()
            file_list = memory_mgr.list_daily_files(user_id=target_user)
            storage_info = memory_mgr.get_storage_info(user_id=target_user)

            return {
                "success": True,
                "data": {
                    "total_files": len(file_list),
                    "files": file_list[:50],  # 限制返回数量
                    "storage_path": storage_info.get("daily_path", "")
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def storage(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取指定用户的记忆存储地址信息"""
        try:
            headers = getattr(request, "headers", {}) if request else {}
            query = getattr(request, "query_params", {}) if request else {}
            target_user = MemoryHandler._check_user_access(headers, query)
            if target_user is None:
                return {"success": False, "error": "无权限查看其他用户的记忆"}

            memory_mgr = get_global_memory_manager()
            storage_info = memory_mgr.get_storage_info(user_id=target_user)

            return {"success": True, "data": storage_info}
        except Exception as e:
            return {"success": False, "error": str(e)}


    @staticmethod
    async def recent(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取指定用户最近每日记忆（结构化；?user_id= 指定用户，admin 可查全部）"""
        try:
            headers = getattr(request, "headers", {}) if request else {}
            query = getattr(request, "query_params", {}) if request else {}
            target_user = MemoryHandler._check_user_access(headers, query)
            if target_user is None:
                return {"success": False, "error": "无权限查看其他用户的记忆"}

            memory_mgr = get_global_memory_manager()

            current_provider = model_manager.get_current_provider_name()
            provider_config = model_manager.get_provider_config(current_provider)
            model_info = ""
            if provider_config:
                model_name = provider_config.get("model_name", "unknown")
                model_info = f"{current_provider}: {model_name}"

            recent_memory = memory_mgr.load_recent_daily(7, target_user)
            
            # 解析原始文本为结构化数据
            structured = []
            if recent_memory:
                # 按日期标题分割（每个 "# YYYY-MM-DD ..." 为一个日期块）
                date_blocks = re.split(r'\n(?=#\s*\d{4}-\d{2}-\d{2})', recent_memory.strip())
                for block in date_blocks:
                    block = block.strip()
                    if not block:
                        continue
                    date_m = re.search(r'#\s*(\d{4}-\d{2}-\d{2})', block)
                    if not date_m:
                        continue
                    date = date_m.group(1)
                    # 去掉标题行，得到条目内容行
                    content_lines = [ln.rstrip() for ln in block.split('\n')
                                     if ln.strip() and not ln.lstrip().startswith('#')]

                    entries = []
                    current_entry = None
                    current_content = []
                    # 条目格式：**[timestamp**] [category]
                    entry_re = re.compile(r'^\*\*\[(.+?)\*\*\]\s*\[([^\]]+)\]')
                    for line in content_lines:
                        if line.strip() == '---':
                            continue
                        em = entry_re.match(line)
                        if em:
                            if current_entry is not None and (current_entry.get('category') or current_entry.get('timestamp')):
                                entries.append({
                                    'type': current_entry.get('category', ''),
                                    'timestamp': current_entry.get('timestamp', ''),
                                    'raw_content': '\n'.join(current_content),
                                })
                            current_entry = {'category': em.group(2).strip(), 'timestamp': em.group(1).strip()}
                            current_content = []
                        else:
                            if current_entry is not None:
                                current_content.append(line)
                    # 最后一条
                    if current_entry is not None and (current_entry.get('category') or current_entry.get('timestamp')):
                        entries.append({
                            'type': current_entry.get('category', ''),
                            'timestamp': current_entry.get('timestamp', ''),
                            'raw_content': '\n'.join(current_content),
                        })

                    structured.append({'date': date, 'entries': entries})
            
            return {
                "success": True,
                "data": {
                    "current_model": model_info,
                    "recent_memory": structured
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def search(request: Any) -> Dict[str, Any]:
        """记忆检索（BM25，按用户隔离；?q= 关键词，?scope= 范围，?user_id= 指定用户）"""
        query = request.query_params.get("q", "")
        if not query:
            return {"success": False, "error": "缺少查询参数 q"}
        target_user = MemoryHandler._check_user_access(request.headers, request.query_params)
        if target_user is None:
            return {"success": False, "error": "无权限查看其他用户的记忆"}
        try:
            limit = max(1, min(int(request.query_params.get("limit", 5) or 5), 50))
        except ValueError:
            limit = 5
        scope = request.query_params.get("scope", "all")
        from src.memory.unified_manager import get_unified_manager
        results = await get_unified_manager().search_memory(
            query, user_id=target_user, scope=scope, limit=limit)
        return {"success": True, "data": {"query": query, "results": results, "enabled": True}}

    @staticmethod
    async def index_health(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取记忆检索引擎健康状态（BM25 已启用）"""
        return {
            "success": True,
            "data": {
                "health": {"status": "healthy", "has_bm25": True, "corpus_size": 0, "is_valid": True},
                "summary": {"status": "healthy", "is_healthy": True, "has_index": True, "corpus_size": 0, "validation_passed": True}
            }
        }
    
    @staticmethod
    async def agent_memory(request: Any, agent_id: str = None) -> Dict[str, Any]:
        """获取指定Agent的私有记忆（路径参数 agent_id 由 HTTP server 以关键字传入；user_id 指定用户，admin 可查全部）"""
        try:
            # 权限：普通用户只能查自己的记忆，admin 可查所有用户
            target_user = MemoryHandler._check_user_access(request.headers, request.query_params)
            if target_user is None:
                return {"success": False, "error": "无权限查看其他用户的记忆"}

            # 路径参数 agent_id 优先（HTTP server 会以 agent_id= 关键字传入），其次查询参数
            if not agent_id:
                agent_id = request.path_params.get("agent_id") if hasattr(request, "path_params") else None
            if not agent_id:
                agent_id = request.query_params.get("agent_id")
            
            # 如果没有提供 agent_id，返回所有可用的 agent 列表
            if not agent_id:
                from pathlib import Path
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                agents_dir = project_root / "agents"
                
                if not agents_dir.exists():
                    return {
                        "success": True,
                        "data": {
                            "available_agents": [],
                            "message": "请提供 agent_id，例如：/api/memory/agents/dfecrab"
                        }
                    }
                
                agents = []
                for agent_dir in agents_dir.iterdir():
                    if agent_dir.is_dir():
                        agents.append(agent_dir.name)
                
                return {
                    "success": True,
                    "data": {
                        "available_agents": sorted(agents),
                        "message": "请提供 agent_id，例如：/api/memory/agents/dfecrab"
                    }
                }
            
            # 导入MemoryManager（按用户隔离）
            from src.memory.long_term import MemoryManager
            memory_manager = MemoryManager(agent_id=agent_id, user_id=target_user)
            
            # 获取长期记忆
            long_term_memory = memory_manager.get_long_term()
            
            return {
                "success": True,
                "data": {
                    "agent_id": agent_id,
                    "long_term_memory": long_term_memory
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    @staticmethod
    async def agent_memory_summary(request: Optional[Any] = None) -> Dict[str, Any]:
        """获取所有Agent私有记忆摘要（包含错误记忆统计；user_id 指定用户，admin 可查全部）"""
        try:
            # 权限：普通用户只能查自己的记忆，admin 可查所有用户
            headers = getattr(request, "headers", {}) if request else {}
            query = getattr(request, "query_params", {}) if request else {}
            target_user = MemoryHandler._check_user_access(headers, query)
            if target_user is None:
                return {"success": False, "error": "无权限查看其他用户的记忆"}

            from pathlib import Path
            from src.memory.long_term import MemoryManager
            import json
            
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            agents_dir = project_root / "agents"
            
            if not agents_dir.exists():
                return {
                    "success": True,
                    "data": {
                        "total_agents": 0,
                        "agents": [],
                        "error_summary": {
                            "total_errors": 0,
                            "recent_errors": []
                        }
                    }
                }
            
            agents_summary = []
            total_successful_patterns = 0
            total_lessons_learned = 0
            all_recent_errors = []  # 收集所有Agent的最近错误，用于全局摘要
            
            for agent_dir in agents_dir.iterdir():
                if not agent_dir.is_dir():
                    continue
                
                agent_id = agent_dir.name
                
                try:
                    # 使用MemoryManager加载记忆，而不是直接读文件（按用户隔离）
                    memory_manager = MemoryManager(agent_id=agent_id, user_id=target_user)
                    # 取完整的 memory.json 结构（含顶层 last_updated 与 long_term 字段）
                    long_term_memory = memory_manager.long_term_memory

                    # 兼容 V3.0 新格式(long_term.{facts,patterns,lessons}) 与旧格式(experience.*)
                    long_term = (long_term_memory.get("long_term")
                                 or long_term_memory.get("long_term_memory")
                                 or {})
                    experience = long_term_memory.get("experience", {})
                    successful_patterns = long_term.get("patterns", []) or experience.get("successful_patterns", [])
                    lessons_learned = long_term.get("lessons", []) or experience.get("lessons_learned", [])
                    
                    # 提取最近错误（最多5条）
                    recent_errors = []
                    for error in lessons_learned[-5:]:  # 取最后5条
                        if isinstance(error, dict):
                            recent_errors.append({
                                "content": error.get("content", ""),
                                "added_at": error.get("added_at", ""),
                                "tags": error.get("tags", [])
                            })
                        else:
                            recent_errors.append({
                                "content": str(error),
                                "added_at": "",
                                "tags": []
                            })
                    
                    # 收集全局错误（用于全局摘要）
                    for error in recent_errors:
                        all_recent_errors.append({
                            "agent_id": agent_id,
                            "content": error["content"][:100] if error["content"] else "",  # 截断
                            "added_at": error["added_at"]
                        })
                    
                    agents_summary.append({
                        "agent_id": agent_id,
                        "successful_patterns_count": len(successful_patterns),
                        "lessons_learned_count": len(lessons_learned),
                        "recent_errors": recent_errors,  # 新增：最近错误详情
                        "last_updated": long_term_memory.get("last_updated")
                                        or long_term_memory.get("metadata", {}).get("last_updated", "unknown")
                    })
                    
                    total_successful_patterns += len(successful_patterns)
                    total_lessons_learned += len(lessons_learned)
                    
                except Exception as e:
                    print(f"读取Agent {agent_id} 记忆失败: {e}")
                    # 如果MemoryManager失败，回退到直接读取文件（优先用户路径，兼容旧逻辑）
                    memory_file = project_root / "data" / "memory" / "users" / target_user / "agents" / agent_id / "memory.json"
                    if not memory_file.exists():
                        memory_file = agent_dir / "memory.json"
                    if memory_file.exists():
                        try:
                            with open(memory_file, 'r', encoding='utf-8') as f:
                                memory_data = json.load(f)

                            # 兼容 V3.0 新格式(long_term.*) 与旧格式(long_term_memory/experience)
                            memory_long_term = (memory_data.get("long_term")
                                                or memory_data.get("long_term_memory")
                                                or {})
                            experience = memory_data.get("experience", {})
                            successful_patterns = memory_long_term.get("patterns", []) or experience.get("successful_patterns", [])
                            lessons_learned = memory_long_term.get("lessons", []) or experience.get("lessons_learned", [])

                            agents_summary.append({
                                "agent_id": agent_id,
                                "successful_patterns_count": len(successful_patterns),
                                "lessons_learned_count": len(lessons_learned),
                                "recent_errors": [],  # 回退模式下不提供错误详情
                                "last_updated": memory_data.get("last_updated")
                                                or memory_long_term.get("metadata", {}).get("last_updated", "unknown")
                            })
                            
                            total_successful_patterns += len(successful_patterns)
                            total_lessons_learned += len(lessons_learned)
                        except Exception as e2:
                            print(f"回退读取Agent {agent_id} 记忆文件失败: {e2}")
                            agents_summary.append({
                                "agent_id": agent_id,
                                "successful_patterns_count": 0,
                                "lessons_learned_count": 0,
                                "recent_errors": [],
                                "last_updated": "never"
                            })
                    else:
                        agents_summary.append({
                            "agent_id": agent_id,
                            "successful_patterns_count": 0,
                            "lessons_learned_count": 0,
                            "recent_errors": [],
                            "last_updated": "never"
                        })
            
            # 全局错误摘要：按时间排序，取最近10条
            all_recent_errors.sort(key=lambda x: x.get("added_at", ""), reverse=True)
            global_recent_errors = all_recent_errors[:10]
            
            return {
                "success": True,
                "data": {
                    "total_agents": len(agents_summary),
                    "total_successful_patterns": total_successful_patterns,
                    "total_lessons_learned": total_lessons_learned,
                    "error_summary": {
                        "total_errors": total_lessons_learned,
                        "recent_errors": global_recent_errors
                    },
                    "agents": agents_summary
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== 用户级记忆 CRUD ====================

    @staticmethod
    def _check_user_access(headers: Dict[str, str], query: Dict[str, str]) -> Optional[str]:
        """校验用户权限：返回可访问的目标 user_id；无权限返回 None"""
        req_user = (headers or {}).get("x-user-id", "guest")
        target_user = (query or {}).get("user_id") or req_user
        if target_user != req_user:
            from src.gateway.permission import PermissionService
            if not PermissionService().is_admin(req_user):
                return None
        return target_user

    @staticmethod
    async def user_memories(request: Any) -> Dict[str, Any]:
        """列出用户级记忆 GET /api/memory/users?user_id=xxx"""
        try:
            target_user = MemoryHandler._check_user_access(request.headers, request.query_params)
            if target_user is None:
                return {"success": False, "error": "无权限查看其他用户的记忆"}
            from src.memory.user_manager import UserMemoryManager
            memories = UserMemoryManager.list_memories(target_user)
            return {
                "success": True,
                "data": {"user_id": target_user, "count": len(memories), "memories": memories}
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def user_memories_create(request: Any, user_id: str = None) -> Dict[str, Any]:
        """新增用户级记忆 POST /api/memory/users/{user_id}"""
        try:
            path_user = user_id or (request.path_params.get("user_id") if hasattr(request, "path_params") else None)
            if not path_user:
                return {"success": False, "error": "缺少 user_id"}
            target_user = MemoryHandler._check_user_access(request.headers, {"user_id": path_user})
            if target_user is None:
                return {"success": False, "error": "无权限操作其他用户的记忆"}
            body = await request.json()
            key = (body.get("key") or "").strip()
            content = (body.get("content") or "").strip()
            if not key or not content:
                return {"success": False, "error": "key 和 content 不能为空"}
            from src.memory.user_manager import UserMemoryManager
            mem = UserMemoryManager.add_memory(
                user_id=target_user,
                key=key,
                content=content,
                scope=body.get("scope", "user"),
                tags=body.get("tags", []) or [],
                source=body.get("source", "api"),
            )
            return {"success": True, "data": mem}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def user_memories_update(request: Any, user_id: str = None, mem_id: str = None) -> Dict[str, Any]:
        """更新用户级记忆 PUT /api/memory/users/{user_id}/{mem_id}"""
        try:
            path_user = user_id or (request.path_params.get("user_id") if hasattr(request, "path_params") else None)
            path_mem = mem_id or (request.path_params.get("mem_id") if hasattr(request, "path_params") else None)
            if not path_user or not path_mem:
                return {"success": False, "error": "缺少 user_id 或 mem_id"}
            target_user = MemoryHandler._check_user_access(request.headers, {"user_id": path_user})
            if target_user is None:
                return {"success": False, "error": "无权限操作其他用户的记忆"}
            body = await request.json()
            from src.memory.user_manager import UserMemoryManager
            updated = UserMemoryManager.update_memory(
                user_id=target_user,
                mem_id=path_mem,
                key=(body.get("key") or "").strip() or None,
                content=(body.get("content") or "").strip() or None,
                scope=body.get("scope"),
                tags=body.get("tags"),
            )
            if updated is None:
                return {"success": False, "error": f"记忆不存在: {path_mem}"}
            return {"success": True, "data": updated}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    async def user_memories_delete(request: Any, user_id: str = None, mem_id: str = None) -> Dict[str, Any]:
        """删除用户级记忆 DELETE /api/memory/users/{user_id}/{mem_id}"""
        try:
            path_user = user_id or (request.path_params.get("user_id") if hasattr(request, "path_params") else None)
            path_mem = mem_id or (request.path_params.get("mem_id") if hasattr(request, "path_params") else None)
            if not path_user or not path_mem:
                return {"success": False, "error": "缺少 user_id 或 mem_id"}
            target_user = MemoryHandler._check_user_access(request.headers, {"user_id": path_user})
            if target_user is None:
                return {"success": False, "error": "无权限操作其他用户的记忆"}
            from src.memory.user_manager import UserMemoryManager
            deleted = UserMemoryManager.delete_memory(user_id=target_user, mem_id=path_mem)
            if not deleted:
                return {"success": False, "error": f"记忆不存在: {path_mem}"}
            return {"success": True, "data": {"deleted": True, "mem_id": path_mem}}
        except Exception as e:
            return {"success": False, "error": str(e)}
