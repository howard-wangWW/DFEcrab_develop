"""Periodic Scheduler - 任务定时/周期调度器（真实实现）

背景：原文件是空壳 Stub（`PeriodicScheduler` 仅丢弃构造参数，没有
add_cron_job/list_tasks/pause_job/get_stats），导致：
  - `/api/tasks/scheduled`、`/api/tasks/heartbeats`、`/api/tasks/stats` 恒为空/报错；
  - 周期任务"注册成功"是假象（approve_task 里 add_cron_job 是 AttributeError 被吞）；
  - 任务重启后周期调度丢失。

本实现：
- 支持 5 字段 cron（分 时 日 月 周）与固定间隔两种调度，**不引入新三方依赖**；
- 持久化到 `<tasks_dir>/scheduled_jobs.json`，进程重启后自动恢复（含下次触发时间）；
- 基于 asyncio 的秒级 tick；`register_callback` 未注册时使用默认回调
  （懒加载 TaskManager + TaskExecutor），保证重启后仍能真正执行任务；
- 失败不中断调度循环，错误记入 job.last_error 供前端排障。

cron 字段支持：`*`、`?`、`a`、`a-b`、`*/n`、`a-b/n`、`a,b,c`（周 0/7 均表示周日）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Shanghai"
_MAX_NEXT_SCAN_MINUTES = 366 * 24 * 60  # 最长向前找 1 年


# ──────────────────────────────────────────────────────────────
# cron 解析
# ──────────────────────────────────────────────────────────────

def _parse_field(field_expr: str, low: int, high: int) -> set:
    """解析单个 cron 字段为允许值集合。"""
    expr = (field_expr or "*").strip()
    if expr in ("*", "?"):
        return set(range(low, high + 1))

    values: set = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, raw_step = part.split("/", 1)
            try:
                step = int(raw_step)
            except ValueError:
                step = 1
            step = max(step, 1)
            if part in ("", "*", "?"):
                part = f"{low}-{high}"
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
            except ValueError:
                continue
            values.update(range(start, end + 1, step))
        else:
            try:
                values.add(int(part))
            except ValueError:
                continue

    allowed = {v for v in values if low <= v <= high}
    if high == 6:  # day-of-week：7 等价于 0（周日）
        if 7 in values:
            allowed.add(0)
    return allowed or set(range(low, high + 1))


class CronSpec:
    """5 字段 cron 解析器：分 时 日 月 周。"""

    def __init__(self, expression: str):
        fields = (expression or "").split()
        if len(fields) != 5:
            raise ValueError(f"cron 必须是 5 个字段（分 时 日 月 周），当前: {expression!r}")
        self.expression = expression
        self.minutes = _parse_field(fields[0], 0, 59)
        self.hours = _parse_field(fields[1], 0, 23)
        self.days = _parse_field(fields[2], 1, 31)
        self.months = _parse_field(fields[3], 1, 12)
        self.weekdays = _parse_field(fields[4], 0, 6)
        # 标准 cron 语义：日/周均为受限字段时取"或"，只受限一个则取"与"
        self._dom_restricted = fields[2].strip() not in ("*", "?")
        self._dow_restricted = fields[4].strip() not in ("*", "?")

    def _day_matches(self, dt: datetime) -> bool:
        # 星期：Python weekday() 周一=0 → 转成 周日=0
        dow = (dt.weekday() + 1) % 7
        if self._dom_restricted and self._dow_restricted:
            return dt.day in self.days or dow in self.weekdays
        if self._dom_restricted:
            return dt.day in self.days
        if self._dow_restricted:
            return dow in self.weekdays
        return True

    def matches(self, dt: datetime) -> bool:
        return (
            dt.minute in self.minutes
            and dt.hour in self.hours
            and dt.month in self.months
            and self._day_matches(dt)
        )

    def next_after(self, dt: datetime) -> datetime:
        """返回 dt 之后的第一个匹配时刻（分钟精度）。"""
        candidate = (dt + timedelta(minutes=1)).replace(second=0, microsecond=0)
        for _ in range(_MAX_NEXT_SCAN_MINUTES):
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        raise ValueError(f"cron 无法在未来一年内匹配: {self.expression!r}")


def _resolve_timezone(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except Exception:
        return None


def _now(tz_name: str = DEFAULT_TIMEZONE) -> datetime:
    tz = _resolve_timezone(tz_name)
    if tz is not None:
        try:
            return datetime.now(tz)
        except Exception:
            pass
    return datetime.now()


# ──────────────────────────────────────────────────────────────
# 供前端使用的调度校验 / 预览（纯函数，无副作用、不落盘）
#   目的：让前端用"时间选择器"生成 cron 后先校验并回显下次执行时间，
#   避免"确认成功但根本没排上"的静默失败。
# ──────────────────────────────────────────────────────────────

def validate_schedule(schedule: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """校验调度配置。

    Args:
        schedule: {"cron": "0 9 * * 1", "timezone": "Asia/Shanghai"}
                  或 {"interval_seconds": 3600, "timezone": "..."}

    Returns:
        {
          "ok": bool,
          "kind": "cron" | "interval" | None,
          "timezone": str,
          "error": str,          # ok=False 时的原因（可直接展示给用户）
          "warning": str,        # 非致命提醒（如时区名无法识别）
        }

    说明：cron 除语法外还会校验"未来一年内是否可匹配"——例如 `0 0 29 2 *`
    在非闰年区间会匹配不到，这种表达式注册时会失败，这里提前拦掉。
    """
    if not isinstance(schedule, dict):
        return {
            "ok": False, "kind": None, "timezone": DEFAULT_TIMEZONE,
            "error": 'schedule 必须是对象，例如 {"cron": "0 9 * * 1"} 或 {"interval_seconds": 3600}',
            "warning": "",
        }

    tz = str(schedule.get("timezone") or DEFAULT_TIMEZONE)
    warning = "" if _resolve_timezone(tz) is not None else f"时区 {tz!r} 无法识别，将按本机本地时间执行"
    cron = str(schedule.get("cron") or "").strip()
    raw_interval = schedule.get("interval_seconds")

    if cron:
        try:
            spec = CronSpec(cron)
        except ValueError as e:
            return {"ok": False, "kind": "cron", "timezone": tz, "error": str(e), "warning": warning}
        try:
            spec.next_after(_now(tz))
        except ValueError as e:
            return {
                "ok": False, "kind": "cron", "timezone": tz,
                "error": f"该时间规则在未来一年内不会触发（{e}）",
                "warning": warning,
            }
        return {"ok": True, "kind": "cron", "timezone": tz, "error": "", "warning": warning}

    if raw_interval not in (None, "", 0):
        try:
            interval = int(raw_interval)
        except (TypeError, ValueError):
            return {
                "ok": False, "kind": "interval", "timezone": tz,
                "error": f"interval_seconds 必须是整数秒，当前: {raw_interval!r}",
                "warning": warning,
            }
        if interval <= 0:
            return {"ok": False, "kind": "interval", "timezone": tz,
                    "error": "interval_seconds 必须大于 0", "warning": warning}
        return {"ok": True, "kind": "interval", "timezone": tz, "error": "", "warning": warning}

    return {
        "ok": False, "kind": None, "timezone": tz,
        "error": "schedule 需含 cron（定时）或 interval_seconds（固定间隔）之一",
        "warning": warning,
    }


def preview_schedule(schedule: Optional[Dict[str, Any]], count: int = 5,
                     base: Optional[datetime] = None) -> Dict[str, Any]:
    """预览未来若干次执行时间（前端用于"下次执行：…"回显）。

    Args:
        schedule: 同 validate_schedule
        count: 返回条数（1~20）
        base: 计算基准时间（默认当前时间；测试可注入固定时间）

    Returns:
        {"ok", "kind", "timezone", "next_runs": [ISO8601...], "error"}
    """
    check = validate_schedule(schedule)
    if not check["ok"]:
        return {**check, "next_runs": []}

    # 统一口径：非数字 / <=0 → 默认 5；上限 20（避免一次返回过多）
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 5
    if count <= 0:
        count = 5
    count = min(count, 20)

    tz = check["timezone"]
    start = base or _now(tz)
    runs: List[str] = []
    try:
        if check["kind"] == "cron":
            spec = CronSpec(str(schedule["cron"]).strip())
            cursor = start
            for _ in range(count):
                cursor = spec.next_after(cursor)
                runs.append(cursor.isoformat())
        else:
            step = timedelta(seconds=int(schedule["interval_seconds"]))
            cursor = start
            for _ in range(count):
                cursor = cursor + step
                runs.append(cursor.isoformat())
    except Exception as e:  # noqa: BLE001
        return {**check, "ok": False, "error": f"预览失败: {e}", "next_runs": []}

    return {**check, "next_runs": runs}


# ──────────────────────────────────────────────────────────────
# Job
# ──────────────────────────────────────────────────────────────

@dataclass
class ScheduleJob:
    """一个被调度的任务。kind: cron | interval"""

    task_id: str
    kind: str = "cron"
    cron: str = ""
    interval_seconds: int = 0
    timezone: str = DEFAULT_TIMEZONE
    args: Dict[str, Any] = field(default_factory=dict)
    name: str = ""
    enabled: bool = True
    last_run: str = ""
    next_run: str = ""
    run_count: int = 0
    last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "cron": self.cron,
            "interval_seconds": self.interval_seconds,
            "timezone": self.timezone,
            "args": self.args,
            "name": self.name,
            "enabled": self.enabled,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduleJob":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


Callback = Callable[[str, Dict[str, Any]], Optional[Awaitable[Any]]]


class PeriodicScheduler:
    """周期/定时任务调度器（单进程内 asyncio 实现）。"""

    def __init__(self, tasks_dir: str = "data/tasks", *_, **__):
        self.tasks_dir = Path(tasks_dir)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._store_file = self.tasks_dir / "scheduled_jobs.json"
        self._jobs: Dict[str, ScheduleJob] = {}
        self._callbacks: Dict[str, Callback] = {}
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._manager_stub = None
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self._store_file.exists():
            return
        try:
            data = json.loads(self._store_file.read_text(encoding="utf-8"))
            for item in data if isinstance(data, list) else []:
                job = ScheduleJob.from_dict(item)
                if job.task_id:
                    self._jobs[job.task_id] = job
            if self._jobs:
                logger.info(f"✅ 已恢复 {len(self._jobs)} 个定时任务（{self._store_file}）")
        except Exception as e:
            logger.warning(f"⚠️ 读取定时任务失败: {e}")

    def _save(self) -> None:
        try:
            self._store_file.write_text(
                json.dumps([j.to_dict() for j in self._jobs.values()], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"⚠️ 保存定时任务失败: {e}")

    # ---------- 回调 ----------
    def register_callback(self, task_id: str, callback: Callback) -> None:
        self._callbacks[task_id] = callback

    def unregister_callback(self, task_id: str) -> None:
        self._callbacks.pop(task_id, None)

    def set_manager_stub(self, manager_stub) -> None:
        """保留旧签名：仅记录 stub，供默认回调透传（不再依赖它执行任务）。"""
        self._manager_stub = manager_stub
        logger.info("✅ Manager Stub 已设置到定时任务调度器")

    # ---------- 作业管理 ----------
    def add_cron_job(self, task_id: str, cron: str, timezone: str = DEFAULT_TIMEZONE,
                     args: Optional[Dict[str, Any]] = None, name: str = "",
                     **_ignored) -> bool:
        try:
            spec = CronSpec(cron)
        except ValueError as e:
            logger.warning(f"⚠️ cron 非法，注册失败 task={task_id}: {e}")
            return False
        job = ScheduleJob(task_id=task_id, kind="cron", cron=cron, timezone=timezone or DEFAULT_TIMEZONE,
                          args=args or {}, name=name)
        job.next_run = spec.next_after(_now(job.timezone)).isoformat()
        self._jobs[task_id] = job
        self._save()
        self.ensure_started()
        logger.info(f"✅ 已注册定时任务: {task_id} cron={cron} 下次={job.next_run}")
        return True

    def add_interval_job(self, task_id: str, interval_seconds: int,
                         args: Optional[Dict[str, Any]] = None, name: str = "",
                         timezone: str = DEFAULT_TIMEZONE, **_ignored) -> bool:
        try:
            interval_seconds = int(interval_seconds)
        except (TypeError, ValueError):
            return False
        if interval_seconds <= 0:
            return False
        job = ScheduleJob(task_id=task_id, kind="interval", interval_seconds=interval_seconds,
                          timezone=timezone or DEFAULT_TIMEZONE, args=args or {}, name=name)
        job.next_run = (_now(job.timezone) + timedelta(seconds=interval_seconds)).isoformat()
        self._jobs[task_id] = job
        self._save()
        self.ensure_started()
        logger.info(f"✅ 已注册周期任务: {task_id} 每 {interval_seconds}s")
        return True

    def remove_job(self, task_id: str) -> bool:
        existed = self._jobs.pop(task_id, None) is not None
        self._callbacks.pop(task_id, None)
        if existed:
            self._save()
            logger.info(f"🗑️ 已移除定时任务: {task_id}")
        return existed

    def pause_job(self, task_id: str) -> bool:
        job = self._jobs.get(task_id)
        if not job:
            return False
        job.enabled = False
        job.next_run = ""
        self._save()
        return True

    def resume_job(self, task_id: str) -> bool:
        job = self._jobs.get(task_id)
        if not job:
            return False
        job.enabled = True
        self._recompute_next(job)
        self._save()
        self.ensure_started()
        return True

    def get_job(self, task_id: str) -> Optional[ScheduleJob]:
        return self._jobs.get(task_id)

    def list_tasks(self, only_enabled: bool = False) -> List[Dict[str, Any]]:
        jobs = [j for j in self._jobs.values() if j.enabled or not only_enabled]
        jobs.sort(key=lambda j: j.next_run or "9999")
        return [j.to_dict() for j in jobs]

    # 兼容旧命名
    def list_jobs(self, only_enabled: bool = False) -> List[Dict[str, Any]]:
        return self.list_tasks(only_enabled=only_enabled)

    def get_stats(self) -> Dict[str, Any]:
        jobs = list(self._jobs.values())
        return {
            "running": self._running,
            "job_count": len(jobs),
            "enabled_count": sum(1 for j in jobs if j.enabled),
            "cron_count": sum(1 for j in jobs if j.kind == "cron"),
            "interval_count": sum(1 for j in jobs if j.kind == "interval"),
            "total_runs": sum(j.run_count for j in jobs),
            "manager_stub_ready": self._manager_stub is not None,
        }

    # ---------- 生命周期 ----------
    def ensure_started(self) -> bool:
        """在已有事件循环时惰性启动 tick；无循环则等 `await start()`。"""
        if self._running:
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("定时调度器等待事件循环启动（无运行中的 loop）")
            return False
        self._running = True
        self._loop_task = loop.create_task(self._loop())
        logger.info("🚀 定时任务调度器已启动")
        return True

    async def start(self) -> None:
        self.ensure_started()

    async def stop(self) -> None:
        self._running = False
        task = self._loop_task
        self._loop_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._save()
        logger.info("🛑 定时任务调度器已停止")

    # ---------- 调度循环 ----------
    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(1)
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:  # 单次异常不退出循环
                logger.error(f"定时调度循环异常: {e}")

    async def _tick(self) -> None:
        changed = False
        for job in list(self._jobs.values()):
            if not job.enabled or not job.next_run:
                continue
            try:
                due = datetime.fromisoformat(job.next_run)
            except ValueError:
                self._recompute_next(job)
                changed = True
                continue
            now = _now(job.timezone)
            # 兼容历史/手工写入的 naive 时间，避免 aware/naive 比较抛 TypeError
            if due.tzinfo is None and now.tzinfo is not None:
                due = due.replace(tzinfo=now.tzinfo)
            elif due.tzinfo is not None and now.tzinfo is None:
                now = now.replace(tzinfo=due.tzinfo)
            if now < due:
                continue

            job.last_run = due.isoformat()
            job.run_count += 1
            await self._fire(job)
            self._recompute_next(job)
            changed = True
        if changed:
            self._save()

    def _recompute_next(self, job: ScheduleJob) -> None:
        try:
            if job.kind == "cron":
                job.next_run = CronSpec(job.cron).next_after(_now(job.timezone)).isoformat()
            else:
                job.next_run = (_now(job.timezone) + timedelta(seconds=job.interval_seconds)).isoformat()
        except Exception as e:
            job.next_run = ""
            job.last_error = f"next_run 计算失败: {e}"

    async def _fire(self, job: ScheduleJob) -> None:
        callback = self._callbacks.get(job.task_id) or self._default_callback
        args = dict(job.args or {})
        args.setdefault("task_id", job.task_id)
        if self._manager_stub is not None:
            args.setdefault("manager_stub", self._manager_stub)
        logger.info(f"⏰ 触发定时任务: {job.task_id}（第 {job.run_count} 次）")
        try:
            result = callback(job.task_id, args)
            if asyncio.iscoroutine(result):
                await result
            job.last_error = ""
        except Exception as e:
            job.last_error = str(e)
            logger.error(f"❌ 定时任务执行失败 {job.task_id}: {e}")

    def _default_callback(self, task_id: str, args: Dict[str, Any]):
        """重启后无注册回调时的兜底：懒加载 TaskManager + TaskExecutor 真正执行任务。"""
        async def _run():
            from src.task.task_manager import get_task_manager
            from src.task.executor import TaskExecutor

            manager = get_task_manager()
            await TaskExecutor(manager).execute_task(task_id, args)
        return _run()


_instance: Optional[PeriodicScheduler] = None


def get_periodic_scheduler(tasks_dir: str = "data/tasks") -> PeriodicScheduler:
    """获取全局单例（首次调用决定存储目录）。"""
    global _instance
    if _instance is None:
        _instance = PeriodicScheduler(tasks_dir=tasks_dir)
    return _instance