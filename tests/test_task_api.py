"""任务域（src/task）回归测试 —— 纯标准库，可直接运行

覆盖：
  A. 模型/进度聚合       TaskProgress
  B. 审计日志            AuditLogger
  C. 周期调度器          CronSpec / PeriodicScheduler（含 tick 触发与持久化）
  D. 轻量调度器          TaskScheduler 待办 CRUD + 持久化
  E. 任务 HTTP 接口层    src/task/api_routes.py 全部端点（用 FakeRequest 直调）
  F. 路由表完整性        get_task_routes()

运行：
    python tests/test_task_api.py
    # 或 pytest tests/test_task_api.py（若已安装 pytest）

说明：
  - 测试通过环境变量 DFECRAB_TASKS_DIR 指向临时目录，不污染真实 data/tasks；
  - 创建任务统一使用 execution_mode=manual + selected_agents，
    绕开 Manager 的 LLM 推荐调用，保证离线、快速、结果确定。
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ⚠️ 必须在导入 src.task.* 之前设置：api_routes.TASKS_DIR 在导入时读取该变量
_TMP_DIR = tempfile.mkdtemp(prefix="dfecrab_task_test_")
os.environ["DFECRAB_TASKS_DIR"] = _TMP_DIR

from src.task import api_routes                                    # noqa: E402
from src.task.audit import AuditLogger                             # noqa: E402
from src.task.models import TaskProgress, TaskStatus, TaskType     # noqa: E402
from src.task.periodic_scheduler import CronSpec, PeriodicScheduler  # noqa: E402
from src.task.scheduler import TaskPriority, TaskScheduler, TaskStatus as SchedStatus  # noqa: E402
from src.task.task_manager import get_task_manager                 # noqa: E402

_PASSED = []


def ok(name: str):
    _PASSED.append(name)
    print(f"  ✅ {name}")


# ──────────────────────────────────────────────────────────────
# FakeRequest：模拟 gateway 的 HTTPRequest 接口
# ──────────────────────────────────────────────────────────────

class FakeRequest:
    def __init__(self, body=None, query=None, path_params=None):
        self.body = json.dumps(body).encode("utf-8") if body is not None else b""
        self._json = body or {}
        self.query_params = query or {}
        self.path_params = path_params or {}

    async def json(self):
        return self._json


def req(body=None, query=None, task_id=None):
    return FakeRequest(body=body, query=query, path_params={"task_id": task_id} if task_id else {})


def create_body(topic="测试任务", **extra):
    """创建任务的请求体。

    固定 execution_mode=manual + selected_agents，绕开 Manager 的 LLM 推荐
    （auto_select 会真实调用大模型，测试必须离线可跑、结果确定）。
    """
    body = {
        "topic": topic,
        "task_type": "temporary",
        "description": "回归测试",
        "execution_mode": "manual",
        "selected_agents": ["dfecrab"],
        "agent_group_config": {"members": [{"agent_id": "dfecrab", "role": "analyst"}]},
    }
    body.update(extra)
    return body


# ──────────────────────────────────────────────────────────────
# A. 模型
# ──────────────────────────────────────────────────────────────

def test_progress_model():
    print("\n【A】TaskProgress 进度聚合")
    manager = get_task_manager(api_routes.TASKS_DIR)
    task = manager.create_task(
        topic="进度聚合测试", task_type=TaskType.TEMPORARY, description="",
        execution_mode="manual", selected_agents=["a1", "a2"],
        agent_group_config={"members": [{"agent_id": "a1", "role": "w"}, {"agent_id": "a2", "role": "w"}]},
    )["task"]
    manager.update_task_step(task.task_id, 0, "completed")
    progress = TaskProgress.from_task(manager.get_task(task.task_id))
    assert progress.total_steps >= 1, progress.total_steps
    assert progress.completed_steps == 1
    assert progress.overall_progress > 0
    assert progress.to_dict()["is_complete"] in (True, False)
    ok("TaskProgress.from_task / overall_progress / to_dict")


def test_status_enum():
    assert TaskStatus.CONVERTED.value == "converted"
    ok("TaskStatus.CONVERTED 已补齐（V2 契约）")


# ──────────────────────────────────────────────────────────────
# B. 审计
# ──────────────────────────────────────────────────────────────

def test_audit_logger():
    print("\n【B】AuditLogger 审计日志")
    audit_dir = os.path.join(_TMP_DIR, "audit_unit")
    logger = AuditLogger("task_unit_1", storage_dir=audit_dir)
    logger.log("create", details={"k": 1})
    logger.log("step_running", agent="a1")
    logger.log("step_completed", agent="a1")
    logger.log("approve", agent="admin")

    logs = logger.get_logs(limit=10)
    assert len(logs) == 4, len(logs)
    assert len(logger.get_logs(agent="a1")) == 2
    assert len(logger.get_logs(action="create")) == 1
    assert logs[0].timestamp >= logs[-1].timestamp  # 倒序

    summary = logger.summary()
    assert summary["total_actions"] == 4
    assert summary["by_agent"]["a1"] == 2
    assert summary["last_action"] is not None

    # 持久化：换实例仍可读
    assert len(AuditLogger("task_unit_1", storage_dir=audit_dir).get_logs(limit=10)) == 4
    # 清理
    assert logger.clear() is True
    assert logger.get_logs(limit=10) == []
    ok("写入/过滤/汇总/持久化/清理")


# ──────────────────────────────────────────────────────────────
# C. 周期调度器
# ──────────────────────────────────────────────────────────────

def test_cron_spec():
    print("\n【C1】CronSpec 解析与匹配")
    from datetime import datetime

    spec = CronSpec("0 9 * * 1")           # 每周一 09:00
    assert spec.matches(datetime(2026, 9, 21, 9, 0))       # 周一
    assert not spec.matches(datetime(2026, 9, 21, 9, 1))
    assert not spec.matches(datetime(2026, 9, 22, 9, 0))   # 周二

    step = CronSpec("*/15 * * * *")
    assert step.matches(datetime(2026, 9, 18, 10, 30))
    assert not step.matches(datetime(2026, 9, 18, 10, 31))

    nxt = CronSpec("0 9 * * 1").next_after(datetime(2026, 9, 18, 10, 0))
    assert nxt == datetime(2026, 9, 21, 9, 0), nxt

    try:
        CronSpec("bad")
        raise AssertionError("非法 cron 应抛错")
    except ValueError:
        pass
    ok("cron 匹配 / next_after / 非法表达式校验")


async def test_periodic_scheduler():
    print("\n【C2】PeriodicScheduler 触发与持久化")
    store = os.path.join(_TMP_DIR, "sched_unit")
    scheduler = PeriodicScheduler(tasks_dir=store)
    fired = []

    def cb(task_id, args):
        fired.append((task_id, args))

    scheduler.register_callback("t1", cb)
    assert scheduler.add_cron_job("t1", "*/5 * * * *", args={"x": 1}) is True
    assert scheduler.add_interval_job("t2", 3600) is True
    assert scheduler.add_cron_job("bad", "not-a-cron") is False

    assert scheduler.get_job("t1").next_run
    assert len(scheduler.list_tasks()) == 2
    assert scheduler.get_stats()["cron_count"] == 1
    assert scheduler.get_stats()["interval_count"] == 1

    # 把下次触发时间改成过去，验证 tick 真的会回调
    job = scheduler.get_job("t1")
    job.next_run = "2000-01-01T00:00:00"
    await scheduler._tick()
    assert fired and fired[0][0] == "t1", fired
    assert job.run_count == 1
    assert scheduler.get_job("t1").next_run != "2000-01-01T00:00:00"

    # 暂停 / 恢复
    assert scheduler.pause_job("t1") is True
    assert scheduler.get_job("t1").enabled is False
    assert scheduler.resume_job("t1") is True
    assert scheduler.get_job("t1").enabled is True
    assert scheduler.pause_job("nope") is False

    # 持久化 + 重启恢复
    assert scheduler.remove_job("t2") is True
    reloaded = PeriodicScheduler(tasks_dir=store)
    ids = [t["task_id"] for t in reloaded.list_tasks()]
    assert "t1" in ids and "t2" not in ids, ids
    ok("注册/触发/暂停/恢复/移除/重启恢复")


# ──────────────────────────────────────────────────────────────
# D. 轻量调度器（待办）
# ──────────────────────────────────────────────────────────────

def test_todo_scheduler():
    print("\n【D】TaskScheduler 待办")
    store = os.path.join(_TMP_DIR, "todo_unit")
    scheduler = TaskScheduler(tasks_dir=store)
    todo = scheduler.create_todo("巡检台账", description="每日巡检", priority=TaskPriority.HIGH)
    assert todo is not None and todo.task_id
    assert scheduler.create_todo("   ") is None
    scheduler.create_todo("低优先", priority=TaskPriority.LOW)

    assert len(scheduler.list_todos()) == 2
    assert len(scheduler.list_todos(priority=TaskPriority.HIGH)) == 1
    assert scheduler.complete_todo(todo.task_id) is True
    assert len(scheduler.list_todos(status=SchedStatus.COMPLETED)) == 1
    assert scheduler.complete_todo("nope") is False

    stats = scheduler.get_stats()
    assert stats["todo_count"] == 2 and stats["todo_completed"] == 1

    reloaded = TaskScheduler(tasks_dir=store)
    assert len(reloaded.list_todos()) == 2
    ok("待办创建/排序/过滤/完成/持久化")


# ──────────────────────────────────────────────────────────────
# E. HTTP 接口层
# ──────────────────────────────────────────────────────────────

async def test_api_create_and_query():
    print("\n【E1】创建 / 列表 / 详情 / 进度")
    r = await api_routes.handle_create_task(req(create_body("分析电网故障")))
    assert r["success"] is True, r
    task_id = r["data"]["task_id"]
    assert r["data"]["task_type"] == "temporary"
    assert "agent_group" in r["data"] and "task" in r["data"]

    # 缺参校验（以下分支在调用 LLM 之前返回）
    assert (await api_routes.handle_create_task(req({"topic": "x"})))["success"] is False
    assert (await api_routes.handle_create_task(req({"topic": "", "agent_group_config": {"members": [1]}})))["success"] is False
    assert (await api_routes.handle_create_task(req({"topic": "x", "agent_group_config": {"members": [{}]}, "task_type": "bad"})))["success"] is False

    listed = await api_routes.handle_list_tasks(req(query={"limit": "100"}))
    assert listed["success"] is True
    assert listed["data"]["count"] >= 1
    assert "tasks" in listed and listed["count"] == listed["data"]["count"]  # 兼容顶层字段

    detail = await api_routes.handle_get_task(req(task_id=task_id))
    assert detail["success"] is True
    assert detail["data"]["task_id"] == task_id
    assert "progress" in detail["data"]

    progress = await api_routes.handle_get_progress(req(task_id=task_id))
    assert progress["success"] is True
    assert "overall_progress" in progress["data"]
    assert "total_steps" in progress["data"]

    assert (await api_routes.handle_get_task(req(task_id="nope")))["success"] is False
    assert (await api_routes.handle_get_progress(req(task_id="nope")))["success"] is False
    ok("create/list/get/progress（含错误分支）")


async def test_api_approve_audit_dashboard():
    print("\n【E2】审批 / 审计 / 看板")
    r = await api_routes.handle_create_task(req(create_body("审计链路验证")))
    task_id = r["data"]["task_id"]

    # 非法 approved
    assert (await api_routes.handle_approve_task(req({"approved": "yes"}, task_id=task_id)))["success"] is False

    approved = await api_routes.handle_approve_task(req({"approved": True, "approved_by": "tester"}, task_id=task_id))
    assert approved["success"] is True, approved
    assert approved["data"]["status"] == "pending"

    audit = await api_routes.handle_get_audit(req(task_id=task_id, query={"limit": "50"}))
    assert audit["success"] is True
    actions = [entry["action"] for entry in audit["data"]["logs"]]
    assert "create" in actions and "approve" in actions, actions

    dashboard = await api_routes.handle_get_dashboard(req(task_id=task_id))
    assert dashboard["success"] is True
    assert dashboard["data"]["task_id"] == task_id
    assert "workflow" in dashboard["data"] and "members" in dashboard["data"]
    assert dashboard["data"]["audit_summary"]["total_actions"] >= 2
    ok("approve 生效 + 审计落库 + 看板聚合")


async def test_api_convert():
    print("\n【E3】任务类型转化")
    r = await api_routes.handle_create_task(req(create_body("转化链路")))
    task_id = r["data"]["task_id"]

    converted = await api_routes.handle_convert_task(req({"target_type": "periodic"}, task_id=task_id))
    assert converted["success"] is True, converted
    assert converted["data"]["new_task_type"] == "periodic"
    assert converted["data"]["original_task_id"] == task_id

    # 原任务被置为 converted
    old = await api_routes.handle_get_task(req(task_id=task_id))
    assert old["data"]["status"] == "converted", old["data"]["status"]

    assert (await api_routes.handle_convert_task(req({"target_type": "bad"}, task_id=task_id)))["success"] is False
    assert (await api_routes.handle_convert_task(req({"target_type": "periodic"}, task_id="nope")))["success"] is False
    ok("convert 新建 + 原任务置 converted + 错误分支")


async def test_api_schedule_pause_resume():
    print("\n【E4】周期任务注册 / 暂停 / 恢复")
    r = await api_routes.handle_create_task(req(create_body(
        "周期任务调度", task_type="periodic", schedule={"cron": "0 9 * * 1"},
    )))
    task_id = r["data"]["task_id"]
    approved = await api_routes.handle_approve_task(req({"approved": True}, task_id=task_id))
    assert approved["success"] is True

    scheduled = await api_routes.handle_list_scheduled(req())
    assert scheduled["success"] is True
    ids = [t["task_id"] for t in scheduled["data"]["tasks"]]
    assert task_id in ids, ids

    paused = await api_routes.handle_pause_task(req(task_id=task_id))
    assert paused["success"] is True, paused
    assert paused["data"]["status"] == "paused"

    resumed = await api_routes.handle_resume_task(req(task_id=task_id))
    assert resumed["success"] is True, resumed
    assert resumed["data"]["status"] == "pending"
    assert resumed["data"]["next_run"]

    # 非调度任务 pause 应给出明确错误
    r2 = await api_routes.handle_create_task(req(create_body("普通任务")))
    assert (await api_routes.handle_pause_task(req(task_id=r2["data"]["task_id"])))["success"] is False
    ok("cron 注册 → 列表可见 → 暂停 → 恢复（含 next_run）")


async def test_api_execute_guards():
    print("\n【E5】执行接口护栏")
    r = await api_routes.handle_create_task(req(create_body("未确认任务", require_confirmation=True)))
    task_id = r["data"]["task_id"]
    # DRAFT 任务不应被执行
    res = await api_routes.handle_execute_task(req({}, task_id=task_id))
    assert res["success"] is False and "approve" in res["error"], res
    assert (await api_routes.handle_execute_task(req({}, task_id="nope")))["success"] is False
    assert (await api_routes.handle_trigger_task(req({}, task_id="nope")))["success"] is False
    ok("draft 拒执行 / 不存在任务报错")


async def test_api_todos_and_stats():
    print("\n【E6】待办接口 / 统计接口")
    created = await api_routes.handle_add_todo(req({"title": "接口待办", "priority": "high"}))
    assert created["success"] is True
    todo_id = created["data"]["todo"]["task_id"]
    assert (await api_routes.handle_add_todo(req({"title": "  "})))["success"] is False

    listed = await api_routes.handle_list_todos(req())
    assert listed["success"] is True and listed["data"]["count"] >= 1

    done = await api_routes.handle_complete_todo(req({"result": "ok"}, task_id=todo_id))
    assert done["success"] is True
    assert (await api_routes.handle_complete_todo(req(task_id="nope")))["success"] is False

    stats = await api_routes.handle_get_stats(req())
    assert stats["success"] is True
    assert {"tasks", "scheduled", "todos"} <= set(stats["data"].keys())
    assert stats["data"]["tasks"]["total"] >= 1

    heartbeats = await api_routes.handle_list_heartbeats(req())
    assert heartbeats["success"] is True and "stats" in heartbeats
    ok("todos CRUD + stats（任务/调度/待办三合一）")


async def test_api_preview_and_delete():
    print("\n【E7】推荐预览 / 删除")
    assert (await api_routes.handle_preview(req({"description": ""})))["success"] is False

    r = await api_routes.handle_create_task(req(create_body("待删除任务")))
    task_id = r["data"]["task_id"]
    deleted = await api_routes.handle_delete_task(req(task_id=task_id))
    assert deleted["success"] is True, deleted
    assert (await api_routes.handle_get_task(req(task_id=task_id)))["success"] is False
    # 再次删除应报不存在（历史上删除成功却返回 400）
    assert (await api_routes.handle_delete_task(req(task_id=task_id)))["success"] is False
    ok("删除幂等语义 + 不存在报错")


# ──────────────────────────────────────────────────────────────
# F. 路由表
# ──────────────────────────────────────────────────────────────

def test_route_table():
    print("\n【F】路由表完整性")
    routes = api_routes.get_task_routes()
    expected = {
        "POST /api/v2/tasks", "GET /api/v2/tasks", "GET /api/v2/tasks/{task_id}",
        "DELETE /api/v2/tasks/{task_id}", "POST /api/v2/tasks/preview",
        # 定时规则校验/预览（前端"时间选择器 → cron"用，2026-09 新增）
        "GET /api/v2/tasks/schedule/preview",
        "POST /api/v2/tasks/{task_id}/convert", "POST /api/v2/tasks/{task_id}/approve",
        "POST /api/v2/tasks/{task_id}/pause", "POST /api/v2/tasks/{task_id}/resume",
        "POST /api/v2/tasks/{task_id}/trigger", "POST /api/v2/tasks/{task_id}/execute",
        "GET /api/v2/tasks/{task_id}/progress", "GET /api/v2/tasks/{task_id}/audit",
        "GET /api/v2/tasks/{task_id}/dashboard",
        "GET /api/tasks/heartbeats", "GET /api/tasks/scheduled", "GET /api/tasks/stats",
        "GET /api/tasks/todos", "POST /api/tasks/todos",
        "POST /api/tasks/todos/{task_id}/complete",
    }
    assert expected == set(routes.keys()), expected ^ set(routes.keys())
    assert all(callable(h) for h in routes.values())
    ok(f"共 {len(routes)} 条任务路由，无重复无遗漏")


# ──────────────────────────────────────────────────────────────

async def run_all():
    print("=" * 64)
    print("DFEcrab 任务域回归测试")
    print(f"临时存储目录: {_TMP_DIR}")
    print("=" * 64)

    test_progress_model()
    test_status_enum()
    test_audit_logger()
    test_cron_spec()
    await test_periodic_scheduler()
    test_todo_scheduler()

    await test_api_create_and_query()
    await test_api_approve_audit_dashboard()
    await test_api_convert()
    await test_api_schedule_pause_resume()
    await test_api_execute_guards()
    await test_api_todos_and_stats()
    await test_api_preview_and_delete()

    test_route_table()

    print("\n" + "=" * 64)
    print(f"🎉 全部通过：{len(_PASSED)} 组断言")
    for name in _PASSED:
        print(f"   ✅ {name}")
    print("=" * 64)
    return True


def main():
    try:
        return asyncio.run(run_all())
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)