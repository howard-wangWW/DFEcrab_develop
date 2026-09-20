"""任务审计日志（Task Audit Log）

背景：原实现只在 gateway 里按文件名 glob 找审计文件，而磁盘上的
`data/tasks/audit/audit_<hex>_<ts>.json` 实际是**会话**审计（另一套），
任务审计从未落库 —— audit / dashboard 接口因此长期返回空。

本模块提供任务级审计的唯一实现：
- 按任务一文件持久化：`<storage_dir>/<task_id>.json`（JSON 数组，可读可校验）
- 线程安全（每文件一把锁），失败不抛（审计失败不能影响主流程）
- `AuditLogEntry` 复用 `src.task.models` 的定义，避免两套模型

用法：
    from src.task.audit import AuditLogger
    logger = AuditLogger("task_abc")
    logger.log("approve", agent="admin", details={"approved": True})
    logs = logger.get_logs(action="approve", limit=50)
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.task.models import AuditLogEntry

logger = logging.getLogger(__name__)

#: 审计文件默认目录（与任务存储同级）
DEFAULT_AUDIT_DIR = "data/tasks/audit"

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


class AuditLogger:
    """单任务审计日志读写器。

    :param task_id: 任务 ID
    :param storage_dir: 审计目录；默认 `data/tasks/audit`
    """

    def __init__(self, task_id: str, storage_dir: Optional[str] = None):
        self.task_id = task_id
        self.storage_dir = Path(storage_dir or DEFAULT_AUDIT_DIR)
        self._file = self.storage_dir / f"{task_id}.json"

    # ---------- 写 ----------
    def log(self, action: str, agent: str = "", details: Optional[Dict[str, Any]] = None) -> Optional[AuditLogEntry]:
        """追加一条审计；返回写入的条目，失败返回 None（不抛异常）。"""
        entry = AuditLogEntry(task_id=self.task_id, action=action, agent=agent or "", details=details or {})
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            with _lock_for(self._file):
                records = self._read_raw()
                records.append(entry.to_dict())
                self._file.write_text(
                    json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            return entry
        except Exception as e:  # 审计失败不阻断业务流程
            logger.warning(f"[AuditLogger] 写入审计失败 task={self.task_id} action={action}: {e}")
            return None

    # ---------- 读 ----------
    def get_logs(
        self,
        agent: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditLogEntry]:
        """按 agent / action 过滤，按时间倒序返回最近 limit 条。"""
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 100
        records = self._read_raw()
        entries = [AuditLogEntry.from_dict(r) for r in records if isinstance(r, dict)]
        if agent:
            entries = [e for e in entries if e.agent == agent]
        if action:
            entries = [e for e in entries if e.action == action]
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[:limit] if limit > 0 else entries

    def summary(self) -> Dict[str, Any]:
        """审计汇总（供 dashboard 使用）：总数 / 按 agent / 按 action / 最近一条。"""
        entries = self.get_logs(limit=0)
        by_agent: Dict[str, int] = {}
        by_action: Dict[str, int] = {}
        for e in entries:
            if e.agent:
                by_agent[e.agent] = by_agent.get(e.agent, 0) + 1
            by_action[e.action] = by_action.get(e.action, 0) + 1
        return {
            "total_actions": len(entries),
            "by_agent": by_agent,
            "by_action": by_action,
            "last_action": entries[0].to_dict() if entries else None,
        }

    def clear(self) -> bool:
        """清空该任务审计（删除任务时调用）。"""
        try:
            with _lock_for(self._file):
                if self._file.exists():
                    self._file.unlink()
            return True
        except Exception as e:
            logger.warning(f"[AuditLogger] 清理审计失败 task={self.task_id}: {e}")
            return False

    # ---------- 内部 ----------
    def _read_raw(self) -> List[Dict[str, Any]]:
        if not self._file.exists():
            return []
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning(f"[AuditLogger] 读取审计失败 task={self.task_id}: {e}")
            return []


def audit(task_id: str, action: str, agent: str = "", details: Optional[Dict[str, Any]] = None) -> None:
    """便捷函数：对默认目录写一条审计。"""
    AuditLogger(task_id).log(action, agent=agent, details=details)