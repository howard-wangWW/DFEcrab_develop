"""
全局记忆管理器 - V3.0 简化版

提供：
- get_global_memory_manager(): 全局单例
- GlobalMemoryManager 类：保存每日对话日志

这是对已删除的 hierarchical_memory_manager.py 的简化替代。
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from threading import Lock

from src.utils.logger import get_logger

logger = get_logger(__name__)

_DAILY_DIR = Path("data/shared_memory/DAILY")
_LOCK = Lock()
_INSTANCE: Optional["GlobalMemoryManager"] = None


class GlobalMemoryManager:
    """
    全局记忆管理器

    职责：
    1. save_daily_memory() - 将对话日志追加到当日的 DAILY 文件
    """

    def __init__(self):
        self._daily_cache: Dict[str, str] = {}
        self._last_flush = 0
        self._flush_interval = 60
        self._ensure_dirs()
        logger.info("全局记忆管理器已初始化")

    def _ensure_dirs(self):
        _DAILY_DIR.mkdir(parents=True, exist_ok=True)

    def save_daily_memory(self, content: str, category: str = "conversation",
                          user_id: Optional[str] = None) -> None:
        """
        保存每日记忆（追加到当日的 DAILY 文件）

        Args:
            content: 对话日志内容
            category: 分类标签
            user_id: 用户 ID，提供后写入 data/memory/users/{user_id}/global/DAILY/；
                     为 None 时写入旧路径 data/shared_memory/DAILY/（兼容旧调用）
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            if user_id:
                daily_dir = Path("data/memory/users") / user_id / "global" / "DAILY"
            else:
                daily_dir = _DAILY_DIR
            daily_dir.mkdir(parents=True, exist_ok=True)
            daily_file = daily_dir / f"{today}.md"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"\n**[{timestamp}**] [{category}]\n{content}\n---\n"

            with _LOCK:
                if daily_file.exists():
                    with open(daily_file, "a", encoding="utf-8") as f:
                        f.write(entry)
                else:
                    with open(daily_file, "w", encoding="utf-8") as f:
                        header = f"# {today} 对话日志\n\n"
                        f.write(header + entry)

            logger.debug(f"每日记忆已保存: {daily_file}")

        except Exception as e:
            logger.error(f"保存每日记忆失败: {e}")

    @staticmethod
    def _daily_dir(user_id: Optional[str] = None) -> Path:
        """user_id 提供时读用户目录 data/memory/users/{user_id}/global/DAILY，否则兼容旧路径"""
        if user_id:
            return Path("data/memory/users") / user_id / "global" / "DAILY"
        return _DAILY_DIR

    def get_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """获取统计信息（user_id 指定则统计该用户的每日日志）"""
        daily_dir = self._daily_dir(user_id)
        daily_files = list(daily_dir.glob("*.md")) if daily_dir.exists() else []
        return {
            "daily_files_count": len(daily_files),
            "latest_daily_file": str(max(daily_files)) if daily_files else None,
        }

    def list_daily_files(self, limit: int = 50, user_id: Optional[str] = None) -> List[str]:
        """列出每日记忆文件（按日期倒序，最多 limit 条）"""
        daily_dir = self._daily_dir(user_id)
        files = sorted(daily_dir.glob("*.md"), reverse=True) if daily_dir.exists() else []
        return [str(f) for f in files[:limit]]

    def get_storage_info(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """获取全局记忆存储路径信息"""
        return {
            "daily_path": str(self._daily_dir(user_id)),
        }

    def load_recent_daily(self, days: int = 7, user_id: Optional[str] = None) -> str:
        """加载最近 N 天的每日记忆文本（按日期倒序拼接）"""
        daily_dir = self._daily_dir(user_id)
        if not daily_dir.exists():
            return ""
        files = sorted(daily_dir.glob("*.md"), reverse=True)[:days]
        return "\n\n".join(f.read_text(encoding="utf-8") for f in files)


def get_global_memory_manager() -> GlobalMemoryManager:
    """获取全局记忆管理器单例"""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = GlobalMemoryManager()
    return _INSTANCE