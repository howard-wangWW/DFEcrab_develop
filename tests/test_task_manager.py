"""TaskManager / AgentGroup / 数据模型 单元测试（对齐当前实现）

运行：
    python tests/test_task_manager.py
    # 或 pytest tests/test_task_manager.py

覆盖：
  - Task / TaskStep / TaskProgress / AuditLogEntry 模型序列化
  - AgentGroup 成员管理
  - TaskManager: 创建 / 查询 / 列表 / 状态机 / 更新 / 转化 / 删除 / 持久化 / 统计 / 审计

注：历史版本的本文件引用了从未实现的 `TaskInstance / TaskMember / MemberMode`
   等类，长期处于失败状态；本次改写为与 `src/task/*` 实际实现一一对应。
"""

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.task.agent_group import AgentGroup                        # noqa: E402
from src.task.audit import AuditLogger                             # noqa: E402
from src.task.models import (                                      # noqa: E402
    AuditLogEntry,
    CollaborationMode,
    TaskProgress,
    TaskStatus,
    TaskStep,
    TaskType,
)
from src.task.task_manager import TaskManager                      # noqa: E402

_PASSED = []


def ok(name: str):
    _PASSED.append(name)
    print(f"  ✅ {name}")


def test_models():
    print("\n【测试 1】数据模型")
    step = TaskStep(task_id="t1", agent_id="a1", step_order=0, step_name="步骤1", status="running")
    assert step.to_dict()["status"] == "running"
    assert TaskStep.from_dict(step.to_dict()).agent_id == "a1"

    entry = AuditLogEntry(task_id="t1", action="assign_step", agent="a1", details={"step": 1})
    assert entry.to_dict()["action"] == "assign_step"
    assert AuditLogEntry.from_dict(entry.to_dict()).task_id == "t1"
    assert entry.audit_id.startswith("audit_")
    ok("TaskStep / AuditLogEntry 序列化与反序列化")

    assert TaskStatus("converted") is TaskStatus.CONVERTED
    assert CollaborationMode("parallel") is CollaborationMode.PARALLEL
    ok("TaskStatus(含 converted) / CollaborationMode 枚举解析")


def test_progress():
    print("\n【测试 2】TaskProgress 进度聚合")
    progress = TaskProgress(task_id="t1", total_steps=5)
    assert progress.overall_progress == 0.0 and not progress.is_complete

    progress.update_step(0, "completed", agent_id="a1")
    progress.update_step(1, "completed", agent_id="a2")
    progress.update_step(2, "running", agent_id="a3")
    assert progress.completed_steps == 2
    assert progress.overall_progress == 40.0, progress.overall_progress
    assert progress.member_progress["a1"] == 100.0
    assert progress.member_progress["a3"] == 50.0
    assert progress.current_step == 2
    ok("completed_steps / overall_progress / member_progress")


def test_agent_group():
    print("\n【测试 3】AgentGroup")
    group = AgentGroup(
        task_id="t1",
        task_type=TaskType.TEMPORARY,
        config={"members": [{"agent_id": "a1", "role": "designer"}, {"agent_id": "a2", "role": "dev"}]},
    )
    assert len(group.members) == 2
    assert group.get_member("a1")["role"] == "designer"
    data = group.to_dict()
    assert data["task_id"] == "t1" and data["task_type"] == "temporary"
    assert group.remove_member("a2") is True and len(group.members) == 1
    assert group.remove_member("a2") is False
    group.add_member("a3", role="reviewer")
    assert len(group.members) == 2
    ok("成员增删查 / to_dict")


def test_task_manager(tmpdir: str):
    print("\n【测试 4】TaskManager")
    tm = TaskManager(storage_dir=tmpdir)
    config = {"members": [{"agent_id": "a1", "role": "designer"}, {"agent_id": "a2", "role": "dev"}]}

    # 创建
    result = tm.create_task(
        topic="分析电网故障", task_type=TaskType.TEMPORARY, description="故障原因分析",
        agent_group_config=config, execution_mode="manual",     # manual：跳过 LLM 推荐，离线可跑
        selected_agents=["a1", "a2"], require_confirmation=True,
    )
    task = result["task"]
    assert task.task_id and task.task_type == TaskType.TEMPORARY
    assert task.status == TaskStatus.DRAFT              # require_confirmation=True
    assert result["approval_url"] and task.steps        # 已按 selected_agents 生成步骤
    assert "agent_id" in result["available_agents"][0]
    ok(f"create_task 返回 task/推荐/可用智能体（task_id={task.task_id}）")

    # 查询 / 列表
    assert tm.get_task(task.task_id).topic == "分析电网故障"
    listed = tm.list_tasks()
    assert listed["count"] == 1 and len(listed["tasks"]) == 1
    assert tm.list_tasks(limit=0)["count"] == 1        # 分页不影响总数
    assert tm.get_task("nope") is None
    ok("get_task / list_tasks(分页) / 不存在返回 None")

    # 状态机
    assert tm.update_task_status(task.task_id, TaskStatus.RUNNING).status == TaskStatus.RUNNING
    assert tm.get_task(task.task_id).started_at is not None
    assert tm.update_task_status(task.task_id, "completed").status == TaskStatus.COMPLETED
    assert tm.get_task(task.task_id).completed_at is not None
    assert tm.update_task_status(task.task_id, "不存在的状态") is not None   # 非法状态不抛错
    ok("update_task_status（含 RUNNING/COMPLETED 时间戳、非法值容错）")

    # 步骤与进度
    tm.update_task_step(task.task_id, 0, "completed")
    progress = tm.get_task_progress(task.task_id)
    assert progress["total_steps"] == len(task.steps)
    assert progress["steps"][0]["status"] == "completed"
    ok("update_task_step / get_task_progress")

    # 字段更新
    updated = tm.update_task(task.task_id, {"topic": "新主题", "task_id": "不允许改写", "progress": 42})
    assert updated.topic == "新主题" and updated.task_id == task.task_id and updated.progress == 42
    ok("update_task 白名单过滤（task_id 不可改写）")

    # 类型转化
    old_id = task.task_id
    new_task = tm.convert_task(old_id, TaskType.PERIODIC, schedule={"cron": "0 9 * * 1"})
    assert new_task is not None and new_task.task_type == TaskType.PERIODIC
    assert new_task.parent_task_id == old_id
    assert tm.get_task(old_id).status == TaskStatus.CONVERTED
    assert tm.convert_task(old_id, TaskType.PERIODIC) is not None      # 原任务已 converted
    ok("convert_task：新建 + 原任务置 converted")

    # 统计
    stats = tm.get_stats()
    assert stats["total"] >= 2
    assert stats["by_type"].get("periodic", 0) >= 1
    ok("get_stats 汇总（by_status / by_type）")

    # 审计联动
    logs = AuditLogger(old_id, storage_dir=str(Path(tmpdir) / "audit")).get_logs(limit=50)
    actions = {entry.action for entry in logs}
    assert {"create", "update", "convert"} <= actions, actions
    ok("create/update/convert 自动落审计")

    # 删除（含定时作业与审计清理）
    assert tm.delete_task(new_task.task_id) is True
    assert tm.get_task(new_task.task_id) is None
    assert tm.delete_task(new_task.task_id) is False
    ok("delete_task 幂等语义")

    # 持久化
    tm2 = TaskManager(storage_dir=tmpdir)
    assert tm2.get_task(old_id).topic == "新主题"
    assert tm2.get_task(old_id).status == TaskStatus.CONVERTED
    ok("重启后从 task_index.json 恢复")


def run_all():
    print("=" * 64)
    print("DFEcrab 任务管理模块 - 单元测试")
    print("=" * 64)
    tmpdir = tempfile.mkdtemp(prefix="dfecrab_tm_test_")
    try:
        test_models()
        test_progress()
        test_agent_group()
        test_task_manager(tmpdir)
        print("\n" + "=" * 64)
        print(f"🎉 全部通过：{len(_PASSED)} 组断言")
        for name in _PASSED:
            print(f"   ✅ {name}")
        print("=" * 64)
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)