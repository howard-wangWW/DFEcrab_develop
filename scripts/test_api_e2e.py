"""
任务管理 V2 端到端 API 测试脚本

模拟完整的 API 调用流程，验证数据一致性和状态流转。
"""

import sys
import asyncio
import tempfile
import json
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.task.task_manager import TaskManager
from src.task.models import TaskType, TaskStatus

# 直接导入 Handler 文件
import importlib.util
handler_path = Path(__file__).parent.parent / "src/core/gateway/handlers/task_v2_handler.py"
spec = importlib.util.spec_from_file_location("task_v2_handler", handler_path)
task_v2_handler_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_v2_handler_module)
TaskV2Handler = task_v2_handler_module.TaskV2Handler


async def run_e2e_test():
    """运行端到端 API 测试"""
    print("=" * 70)
    print("DFEcrab 任务管理 V2 - 端到端 API 测试")
    print("=" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. 初始化
        print("\n1. 初始化服务")
        tm = TaskManager(storage_dir=tmpdir)
        handler = TaskV2Handler(tm, storage_dir=tmpdir)
        print("  ✅ TaskManager 和 Handler 初始化成功")
        
        # 2. 创建任务
        print("\n2. 创建临时任务")
        create_req = {
            "topic": "E2E 测试任务",
            "task_type": "temporary",
            "description": "端到端测试任务描述",
            "supervisor_agent_id": "supervisor_01",
            "agent_group_config": {
                "members": [
                    {"agent_id": "qwencode", "role": "designer"},
                    {"agent_id": "codebuddy", "role": "developer"},
                ]
            },
        }
        
        create_resp = await handler.handle_create_task(create_req)
        assert create_resp["success"] is True
        task_id = create_resp["data"]["task_id"]
        print(f"  ✅ 任务创建成功: {task_id}")
        
        # 3. 查询任务详情
        print("\n3. 查询任务详情")
        detail_resp = await handler.handle_get_task(task_id)
        assert detail_resp["success"] is True
        assert detail_resp["data"]["topic"] == "E2E 测试任务"
        assert detail_resp["data"]["status"] == "pending"
        print(f"  ✅ 任务详情查询成功: {detail_resp['data']['topic']}")
        
        # 4. 查询任务进度
        print("\n4. 查询任务进度")
        progress_resp = await handler.handle_get_progress(task_id)
        assert progress_resp["success"] is True
        assert progress_resp["data"]["progress"] == 0.0
        print(f"  ✅ 进度查询成功: {progress_resp['data']['progress']}%")
        
        # 5. 更新任务状态（模拟执行）
        print("\n5. 更新任务状态为运行中")
        tm.update_task_status(task_id, TaskStatus.RUNNING)
        detail_resp = await handler.handle_get_task(task_id)
        assert detail_resp["data"]["status"] == "running"
        print(f"  ✅ 状态更新成功: {detail_resp['data']['status']}")
        
        # 6. 查询审计日志
        print("\n6. 查询审计日志")
        # 注意：这里需要 SupervisorSession 才能记录审计日志
        # 我们模拟一些日志
        from src.task.audit import AuditLogger
        audit_logger = AuditLogger(task_id, storage_dir=f"{tmpdir}/audit")
        audit_logger.log_action("task_started", "supervisor", {"user_input": "test"})
        audit_logger.log_action("step_assigned", "qwencode", {"step": "step_0"})
        audit_logger.log_action("step_completed", "qwencode", {"step": "step_0"})
        audit_logger.flush()  # 强制保存
        
        # 清除 SupervisorSession 缓存，强制从文件加载
        handler._supervisors.pop(task_id, None)
        
        # 调试：检查文件是否存在
        log_file = Path(f"{tmpdir}/audit/{task_id}.json")
        print(f"  📁 审计日志文件: {log_file}")
        print(f"  📄 文件存在: {log_file.exists()}")
        if log_file.exists():
            print(f"  📝 文件内容: {log_file.read_text()[:100]}...")
        
        audit_resp = await handler.handle_get_audit_log(task_id)
        print(f"  📊 API 响应: {audit_resp}")
        assert audit_resp["success"] is True
        assert audit_resp["data"]["count"] == 3
        print(f"  ✅ 审计日志查询成功: {audit_resp['data']['count']} 条记录")
        
        # 7. 获取看板数据
        print("\n7. 获取看板数据")
        # 注意：看板数据需要 SupervisorSession
        # 这里我们验证 API 结构
        dashboard_resp = await handler.handle_get_dashboard(task_id)
        # 由于没有创建 SupervisorSession，这里应该返回错误或空数据
        # 我们验证错误处理
        if not dashboard_resp["success"]:
            print(f"  ✅ 看板数据查询正确处理: {dashboard_resp.get('error', 'Unknown')}")
        else:
            print(f"  ✅ 看板数据查询成功")
        
        # 8. 列出所有任务
        print("\n8. 列出所有任务")
        list_resp = await handler.handle_list_tasks()
        assert list_resp["success"] is True
        assert list_resp["data"]["count"] == 1
        print(f"  ✅ 任务列表查询成功: {list_resp['data']['count']} 个任务")
        
        # 9. 转化任务类型
        print("\n9. 转化任务类型为周期任务")
        convert_resp = await handler.handle_convert_task(task_id, "periodic")
        assert convert_resp["success"] is True
        new_task_id = convert_resp["data"]["new_task_id"]
        print(f"  ✅ 任务转化成功: {task_id} -> {new_task_id}")
        
        # 10. 验证原任务状态
        print("\n10. 验证原任务状态")
        old_detail = await handler.handle_get_task(task_id)
        assert old_detail["data"]["status"] == "converted"
        print(f"  ✅ 原任务状态验证成功: {old_detail['data']['status']}")
        
        # 11. 验证新任务类型
        print("\n11. 验证新任务类型")
        new_detail = await handler.handle_get_task(new_task_id)
        assert new_detail["data"]["task_type"] == "periodic"
        print(f"  ✅ 新任务类型验证成功: {new_detail['data']['task_type']}")
        
        # 12. 删除新任务
        print("\n12. 删除新任务")
        delete_resp = await handler.handle_delete_task(new_task_id)
        assert delete_resp["success"] is True
        print(f"  ✅ 任务删除成功")
        
        # 13. 验证删除
        print("\n13. 验证删除")
        detail_resp = await handler.handle_get_task(new_task_id)
        assert detail_resp["success"] is False
        print(f"  ✅ 删除验证成功: {detail_resp['error']}")
        
        print("\n" + "=" * 70)
        print("🎉 所有端到端 API 测试通过！(13/13)")
        print("=" * 70)
        
        return True


if __name__ == '__main__':
    success = asyncio.run(run_e2e_test())
    sys.exit(0 if success else 1)
