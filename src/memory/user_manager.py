"""
用户级记忆管理器

管理每个用户的结构化记忆（KV 形式），存储在：
    data/memory/users/{user_id}/memories.json

支持 CRUD：list / add / update / delete。
记忆条目结构：
    {
        "id": "mem_<timestamp>_<random>",
        "key": "常驻地",
        "content": "昆明",
        "scope": "user",          # user=仅该用户可见, agent=指定 Agent 可见
        "tags": ["偏好", "基础信息"],
        "source": "api | conversation | reflection",
        "created_at": "...",
        "updated_at": "..."
    }
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
USERS_BASE = PROJECT_ROOT / "data" / "memory" / "users"


class UserMemoryManager:
    """用户级记忆管理器（结构化 KV，按 user_id 隔离）"""

    @staticmethod
    def _user_file(user_id: str) -> Path:
        return USERS_BASE / (user_id or "default") / "memories.json"

    @staticmethod
    def _read(user_id: str) -> Dict[str, Any]:
        f = UserMemoryManager._user_file(user_id)
        if not f.exists():
            return {}
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"读取用户记忆失败 {f}: {e}")
            return {}

    @staticmethod
    def list_memories(user_id: str) -> List[Dict[str, Any]]:
        """列出用户所有记忆"""
        return UserMemoryManager._read(user_id).get("memories", [])

    @staticmethod
    def add_memory(user_id: str, key: str, content: str,
                   scope: str = "user", tags: Optional[List[str]] = None,
                   source: str = "api") -> Dict[str, Any]:
        """新增用户记忆；同 key 已存在时更新内容"""
        user_id = user_id or "default"
        f = UserMemoryManager._user_file(user_id)
        f.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat()
        data = UserMemoryManager._read(user_id)
        memories = data.get("memories", [])

        for m in memories:
            if m.get("key") == key:
                m["content"] = content
                m["scope"] = scope
                m["tags"] = tags or []
                m["source"] = source
                m["updated_at"] = now
                data["last_updated"] = now
                try:
                    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as e:
                    logger.error(f"保存用户记忆失败 {f}: {e}")
                    raise
                return m

        mem = {
            "id": f"mem_{int(datetime.now().timestamp() * 1000)}_{uuid.uuid4().hex[:6]}",
            "key": key,
            "content": content,
            "scope": scope,
            "tags": tags or [],
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        memories.append(mem)
        data["user_id"] = user_id
        data["version"] = "1.0"
        data["last_updated"] = now
        data["memories"] = memories
        try:
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"保存用户记忆失败 {f}: {e}")
            raise
        return mem

    @staticmethod
    def update_memory(user_id: str, mem_id: str, **fields) -> Optional[Dict[str, Any]]:
        """更新指定记忆条目，返回更新后的条目；不存在返回 None"""
        f = UserMemoryManager._user_file(user_id)
        data = UserMemoryManager._read(user_id)
        memories = data.get("memories", [])
        now = datetime.now().isoformat()
        for m in memories:
            if m.get("id") == mem_id:
                for k in ("key", "content", "scope", "tags"):
                    if k in fields and fields[k] is not None:
                        m[k] = fields[k]
                m["updated_at"] = now
                data["last_updated"] = now
                try:
                    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as e:
                    logger.error(f"更新用户记忆失败 {f}: {e}")
                    raise
                return m
        return None

    @staticmethod
    def delete_memory(user_id: str, mem_id: str) -> bool:
        """删除指定记忆条目"""
        f = UserMemoryManager._user_file(user_id)
        data = UserMemoryManager._read(user_id)
        memories = data.get("memories", [])
        new_memories = [m for m in memories if m.get("id") != mem_id]
        if len(new_memories) == len(memories):
            return False
        data["memories"] = new_memories
        data["last_updated"] = datetime.now().isoformat()
        try:
            f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"删除用户记忆失败 {f}: {e}")
            raise
        return True
