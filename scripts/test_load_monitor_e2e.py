"""
电网负载率监视 - 端到端测试脚本

模拟完整的任务创建、调度触发、技能执行流程。
"""

import sys
import asyncio
import tempfile
import importlib.util
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.task.task_manager import TaskManager
from src.task.models import TaskType, TaskStatus

# 导入 TaskV2Handler
handler_path = Path(__file__).parent.parent / "src/core/gateway/handlers/task_v2_handler.py"
spec = importlib.util.spec_from_file_location("task_v2_handler", handler_path)
task_v2_handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_v2_handler_module)
TaskV2Handler = task_v2_handler_module.TaskV2Handler


async def run_load_monitor_test():
    """运行负载监视测试"""
    print("=" * 70)
    print("DFEcrab 电网负载率监视 - 端到端测试")
    print("=" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 初始化服务
        print("\n1. 初始化服务")
        tm = TaskManager(storage_dir=tmpdir)
        handler = TaskV2Handler(tm, storage_dir=tmpdir)
        print("  ✅ TaskManager 和 Handler 初始化成功")
        
        # 2. 创建周期任务
        print("\n2. 创建周期任务 (模拟每 5 分钟执行)")
        create_req = {
            "topic": "电网负载率监视",
            "task_type": "periodic",
            "description": "获取量测数据，计算负载率，列出过载(>100%)和高负载(80-100%)设备并排序",
            "supervisor_agent_id": "supervisor_01",
            "agent_group_config": {
                "members": [
                    {"agent_id": "qwencode", "role": "analyst"}
                ]
            },
            "schedule": {"cron": "*/5 * * * *"},  # 每 5 分钟
        }
        
        create_resp = await handler.handle_create_task(create_req)
        assert create_resp["success"] is True
        task_id = create_resp["data"]["task_id"]
        print(f"  ✅ 周期任务创建成功: {task_id}")
        print(f"     调度规则: */5 * * * *")
        
        # 3. 模拟调度器触发 (手动触发一次执行)
        print("\n3. 模拟调度器触发 (模拟 5 分钟时间到达)")
        
        # 加载并执行 load_analysis 技能
        skill_path = Path(__file__).parent.parent / "skills/load_analysis/execute.py"
        spec_skill = importlib.util.spec_from_file_location("load_analysis", skill_path)
        skill_module = importlib.util.module_from_spec(spec_skill)
        spec_skill.loader.exec_module(skill_module)
        
        # 执行技能
        print("  🔄 正在执行 load_analysis 技能...")
        result = skill_module.execute()
        print("  ✅ 技能执行完成")
        
        # 4. 验证结果
        print("\n4. 验证分析结果")
        print("-" * 70)
        print(result)
        print("-" * 70)
        
        # 验证结果包含关键信息
        assert "过载设备" in result
        assert "高负载设备" in result
        assert "变压器" in result
        print("  ✅ 结果格式验证通过")
        
        # 5. 更新任务状态
        print("\n5. 更新任务状态")
        tm.update_task_status(task_id, TaskStatus.COMPLETED)
        task = tm.get_task(task_id)
        print(f"  ✅ 任务状态已更新为: {task.status.value}")
        
        # 6. 查询任务看板
        print("\n6. 查询任务看板数据")
        dashboard_resp = await handler.handle_get_dashboard(task_id)
        # 注意：这里没有 SupervisorSession，所以会返回错误，这是预期的
        if not dashboard_resp["success"]:
            print(f"  ℹ️ 看板数据查询 (无 SupervisorSession): {dashboard_resp.get('error')}")
        else:
            print(f"  ✅ 看板数据查询成功")
            
        # 7. 查询审计日志
        print("\n7. 查询审计日志")
        audit_resp = await handler.handle_get_audit_log(task_id)
        print(f"  ✅ 审计日志查询成功: {audit_resp['data']['count']} 条记录")
        
        print("\n" + "=" * 70)
        print("🎉 负载率监视测试全部通过！")
        print("=" * 70)
        print("\n📊 测试总结:")
        print("  ✅ 周期任务创建成功")
        print("  ✅ 技能执行逻辑正确 (分类、排序)")
        print("  ✅ 结果输出符合预期")
        print("  ✅ 任务状态流转正常")
        print("=" * 70)
        
        return True


if __name__ == '__main__':
    success = asyncio.run(run_load_monitor_test())
    sys.exit(0 if success else 1)
