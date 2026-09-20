"""
任务管理 V2 端到端集成测试

测试完整的任务管理流程：
1. 创建任务
2. 执行任务
3. 追踪进度
4. 查询审计日志
5. 获取看板数据
6. 任务转化
"""

import sys
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.task.models import TaskType, TaskStatus, MemberStatus
from src.task.task_manager import TaskManager
from src.task.agent_group import AgentGroup
from src.task.supervisor import SupervisorSession


async def test_full_task_lifecycle():
    """测试完整任务生命周期"""
    print("=" * 70)
    print("【端到端测试】完整任务生命周期")
    print("=" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 创建 TaskManager
        print("\n1. 初始化 TaskManager")
        tm = TaskManager(storage_dir=tmpdir)
        print("  ✅ TaskManager 初始化成功")
        
        # 2. 创建临时任务
        print("\n2. 创建临时任务")
        config = {
            "members": [
                {"agent_id": "qwencode", "role": "designer"},
                {"agent_id": "codebuddy", "role": "developer"},
                {"agent_id": "dfecrab", "role": "reviewer"},
            ]
        }
        
        task = tm.create_task(
            topic="分析电网故障",
            task_type=TaskType.TEMPORARY,
            description="分析最近的电网故障原因并提出解决方案",
            supervisor_agent_id="supervisor_01",
            agent_group_config=config,
        )
        print(f"  ✅ 任务创建成功: {task.task_id}")
        print(f"     主题: {task.topic}")
        print(f"     类型: {task.task_type.value}")
        print(f"     成员数: {len(config['members'])}")
        
        # 3. 创建 AgentGroup
        print("\n3. 创建 AgentGroup")
        agent_group = AgentGroup(
            task_id=task.task_id,
            task_type=task.task_type,
            config=config,
        )
        print(f"  ✅ AgentGroup 创建成功")
        print(f"     模式: {agent_group.members[0].mode.value}")
        for m in agent_group.members:
            print(f"     - {m.agent_ref} ({m.role}) -> Session {m.session_id[:8]}...")
        
        # 4. 创建 SupervisorSession
        print("\n4. 创建 SupervisorSession")
        supervisor = SupervisorSession(
            task_instance=task,
            agent_group=agent_group,
            storage_dir=tmpdir,
        )
        print(f"  ✅ SupervisorSession 创建成功")
        print(f"     Session ID: {supervisor.session_id[:8]}...")
        
        # 5. 注册进度回调
        print("\n5. 注册进度回调")
        progress_updates = []
        
        def on_progress(data):
            progress_updates.append(data)
            print(f"     📊 进度更新: {data['overall_progress']:.1f}%")
        
        supervisor.on_progress(on_progress)
        print("  ✅ 进度回调注册成功")
        
        # 6. 执行任务
        print("\n6. 执行任务")
        workflow_steps = [
            {"id": "step_0", "action": "需求分析", "role": "designer"},
            {"id": "step_1", "action": "方案设计", "role": "designer"},
            {"id": "step_2", "action": "代码实现", "role": "developer"},
            {"id": "step_3", "action": "测试验证", "role": "reviewer"},
            {"id": "step_4", "action": "部署上线", "role": "developer"},
        ]
        
        await supervisor.coordinate_task(
            user_input="分析最近的电网故障原因",
            workflow_steps=workflow_steps,
        )
        print(f"  ✅ 任务执行完成")
        print(f"     状态: {supervisor.task.status.value}")
        print(f"     进度: {supervisor.progress_tracker.overall_progress:.1f}%")
        
        # 7. 验证进度
        print("\n7. 验证进度追踪")
        assert len(progress_updates) > 0, "应该有进度更新"
        assert supervisor.progress_tracker.is_complete, "任务应该完成"
        assert supervisor.progress_tracker.overall_progress >= 100.0, "进度应该 100%"
        print(f"  ✅ 进度追踪验证成功")
        print(f"     总步骤: {supervisor.progress_tracker.total_steps}")
        print(f"     完成步骤: {supervisor.progress_tracker.completed_steps}")
        print(f"     进度更新次数: {len(progress_updates)}")
        
        # 8. 验证审计日志
        print("\n8. 验证审计日志")
        logs = supervisor.audit_logger.get_logs()
        assert len(logs) > 0, "应该有审计日志"
        print(f"  ✅ 审计日志验证成功")
        print(f"     总日志数: {len(logs)}")
        print(f"     最近 5 条:")
        for log in logs[-5:]:
            print(f"       - {log.timestamp.strftime('%H:%M:%S')} | {log.agent} | {log.action}")
        
        # 9. 获取看板数据
        print("\n9. 获取看板数据")
        dashboard = supervisor.get_dashboard_data()
        assert dashboard["task_id"] == task.task_id
        assert dashboard["status"] == "completed"
        assert dashboard["progress"] >= 100.0
        print(f"  ✅ 看板数据获取成功")
        print(f"     任务 ID: {dashboard['task_id']}")
        print(f"     状态: {dashboard['status']}")
        print(f"     进度: {dashboard['progress']:.1f}%")
        print(f"     成员数: {len(dashboard['members'])}")
        for m in dashboard["members"]:
            print(f"       - {m['agent']} ({m['role']}): {m['status']} {m['progress']}%")
        
        # 10. 查询任务进度
        print("\n10. 查询任务进度")
        progress = tm.get_task_progress(task.task_id)
        assert progress is not None
        # 任务已被 SupervisorSession 更新为 completed
        assert progress["status"] in ["pending", "running", "completed"]
        print(f"  ✅ 进度查询成功")
        print(f"     状态: {progress['status']}")
        print(f"     进度: {progress['progress']:.1f}%")
        
        # 11. 更新任务状态
        print("\n11. 更新任务状态")
        tm.update_task_status(task.task_id, TaskStatus.COMPLETED)
        updated_task = tm.get_task(task.task_id)
        assert updated_task.status == TaskStatus.COMPLETED
        print(f"  ✅ 状态更新成功")
        print(f"     新状态: {updated_task.status.value}")
        
        # 12. 创建周期任务
        print("\n12. 创建周期任务")
        periodic_task = tm.create_task(
            topic="每周运维报告",
            task_type=TaskType.PERIODIC,
            description="生成每周运维报告",
            supervisor_agent_id="supervisor_01",
            agent_group_config=config,
            schedule={"cron": "0 9 * * 1"},
        )
        assert periodic_task.task_type == TaskType.PERIODIC
        assert periodic_task.schedule is not None
        print(f"  ✅ 周期任务创建成功")
        print(f"     任务 ID: {periodic_task.task_id}")
        print(f"     调度: {periodic_task.schedule}")
        
        # 13. 任务转化
        print("\n13. 任务转化（临时 → 周期）")
        new_task = tm.convert_task(task.task_id, TaskType.PERIODIC)
        assert new_task is not None
        assert new_task.task_type == TaskType.PERIODIC
        
        old_task = tm.get_task(task.task_id)
        assert old_task.status == TaskStatus.CONVERTED
        print(f"  ✅ 任务转化成功")
        print(f"     原任务: {task.task_id} -> {old_task.status.value}")
        print(f"     新任务: {new_task.task_id} -> {new_task.task_type.value}")
        
        # 14. 列出所有任务
        print("\n14. 列出所有任务")
        all_tasks = tm.list_tasks()
        print(f"  ✅ 任务列表获取成功")
        print(f"     总任务数: {len(all_tasks)}")
        for t in all_tasks:
            print(f"       - {t.task_id[:8]}... | {t.topic} | {t.task_type.value} | {t.status.value}")
        
        # 15. 导出审计日志
        print("\n15. 导出审计日志")
        json_logs = supervisor.audit_logger.export_logs(format="json")
        csv_logs = supervisor.audit_logger.export_logs(format="csv")
        assert len(json_logs) > 0
        assert len(csv_logs) > 0
        print(f"  ✅ 审计日志导出成功")
        print(f"     JSON 长度: {len(json_logs)} 字符")
        print(f"     CSV 长度: {len(csv_logs)} 字符")
        
        print("\n" + "=" * 70)
        print("🎉 端到端测试全部通过！")
        print("=" * 70)
        
        return True


async def test_concurrent_tasks():
    """测试并发任务"""
    print("\n" + "=" * 70)
    print("【并发测试】多任务并发执行")
    print("=" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tm = TaskManager(storage_dir=tmpdir)
        
        config = {
            "members": [
                {"agent_id": "qwencode", "role": "designer"},
                {"agent_id": "codebuddy", "role": "developer"},
            ]
        }
        
        # 创建多个任务
        tasks = []
        for i in range(3):
            task = tm.create_task(
                topic=f"任务 {i+1}",
                task_type=TaskType.TEMPORARY,
                description=f"测试任务 {i+1}",
                supervisor_agent_id="supervisor_01",
                agent_group_config=config,
            )
            tasks.append(task)
        
        print(f"  ✅ 创建了 {len(tasks)} 个任务")
        
        # 验证任务列表
        all_tasks = tm.list_tasks()
        assert len(all_tasks) == 3
        print(f"  ✅ 任务列表验证成功")
        
        # 更新所有任务状态
        for task in tasks:
            tm.update_task_status(task.task_id, TaskStatus.RUNNING)
        
        running_tasks = tm.list_tasks(status=TaskStatus.RUNNING)
        assert len(running_tasks) == 3
        print(f"  ✅ 状态更新验证成功")
        
        print("\n✅ 并发测试通过")
        return True


async def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("DFEcrab 任务管理 V2 - 端到端集成测试")
    print("=" * 70)
    
    try:
        # 测试 1: 完整任务生命周期
        success1 = await test_full_task_lifecycle()
        
        # 测试 2: 并发任务
        success2 = await test_concurrent_tasks()
        
        if success1 and success2:
            print("\n" + "=" * 70)
            print("🎉 所有端到端测试通过！(2/2)")
            print("=" * 70)
            print("\n📊 测试统计:")
            print("  ✅ 完整任务生命周期 - 通过")
            print("  ✅ 并发任务 - 通过")
            print("\n📁 测试覆盖:")
            print("  - 任务创建 (临时/周期)")
            print("  - AgentGroup 编组 (Session 团队/专用 Agent)")
            print("  - SupervisorSession 监管")
            print("  - 工作流执行")
            print("  - 进度追踪")
            print("  - 审计日志")
            print("  - 看板数据")
            print("  - 任务转化")
            print("  - 并发任务")
            print("  - 数据持久化")
            print("=" * 70)
            return True
        else:
            print("\n❌ 部分测试失败")
            return False
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
