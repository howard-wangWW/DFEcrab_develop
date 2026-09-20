#!/usr/bin/env python3
"""
DFEcrab Gateway 测试脚本

测试:
1. Gateway启动
2. Session调度
3. 事件触发
4. 故障分析流程
"""

import asyncio
import sys
import os
from pathlib import Path
import logging
import importlib.util

# 添加项目路径
project_root = Path(__file__).parent.parent  # DFEcrab--
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# 直接加载模块
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# 加载session_base
session_base = load_module("session_base", project_root / "src" / "cli" / "session_base.py")
SessionBase = session_base.SessionBase

# 加载agents
fault_analyzer = load_module("fault_analyzer", project_root / "src" / "agents" / "fault_analyzer.py")
FaultAnalyzerSession = fault_analyzer.FaultAnalyzerSession

grid_monitor = load_module("grid_monitor", project_root / "src" / "agents" / "grid_monitor.py")
GridMonitorSession = grid_monitor.GridMonitorSession

# 加载scheduler
scheduler_mod = load_module("scheduler", project_root / "src" / "core" / "multi_cli" / "scheduler.py")
SessionScheduler = scheduler_mod.SessionScheduler
CronParser = scheduler_mod.CronParser

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_gateway():
    """测试Gateway"""
    print("\n" + "="*60)
    print("测试 Gateway")
    print("="*60)
    
    # 加载gateway模块
    gateway_mod = load_module("gateway", project_root / "src" / "gateway" / "__init__.py")
    DFEcrabGateway = gateway_mod.DFEcrabGateway
    
    # 简化配置
    config = {
        "gateway": {
            "host": "0.0.0.0",
            "port": 8080
        },
        "agents": [
            {"id": "fault_analyzer", "name": "故障分析", "module": "src.agents.fault_analyzer"},
            {"id": "grid_monitor", "name": "电网监视", "module": "src.agents.grid_monitor"},
        ],
        "sessions": [
            {
                "id": "test_scheduled",
                "agent": "grid_monitor",
                "type": "scheduled",
                "schedule": [{"cron": "*/5 * * * *", "task": "health_check"}]
            },
            {
                "id": "test_triggered",
                "agent": "fault_analyzer",
                "type": "triggered",
                "trigger": {"events": ["alert", "test_event"]}
            }
        ]
    }
    
    gateway = DFEcrabGateway(config)
    
    print("\n1. 启动Gateway...")
    await gateway.start()
    
    print("\n2. 查看状态:")
    status = gateway.get_status()
    print(f"   - Sessions: {len(gateway.sessions)}")
    print(f"   - Agents: {len(gateway.agents)}")
    
    print("\n3. 触发事件:")
    await gateway.scheduler.trigger_event("test_event", {"test": True})
    print("   - test_event 已触发")
    
    print("\n4. 等待3秒...")
    await asyncio.sleep(3)
    
    print("\n5. 停止Gateway...")
    await gateway.stop()
    
    print("\n测试完成!")


async def test_agents():
    """测试Agent"""
    print("\n" + "="*60)
    print("测试 Agent")
    print("="*60)
    
    # 测试故障分析
    print("\n1. 测试故障分析:")
    fault_session = FaultAnalyzerSession(
        session_id="test_fault",
        agent_id="fault_analyzer",
        context={"config": {}}
    )
    
    result = await fault_session.execute({
        "type": "triggered",
        "event": "alert",
        "data": {
            "source": "scada",
            "voltage_level": 110,
            "message": "110kV线路电压异常"
        }
    })
    
    print(f"   - 报告ID: {result.get('id')}")
    print(f"   - 故障类型: {result.get('fault_type')}")
    print(f"   - 严重程度: {result.get('severity')}")
    
    # 测试电网监视
    print("\n2. 测试电网监视:")
    monitor_session = GridMonitorSession(
        session_id="test_monitor",
        agent_id="grid_monitor",
        context={"config": {}}
    )
    
    result = await monitor_session.execute({
        "task": "health_check"
    })
    
    print(f"   - 检查结果: {result.get('status')}")
    print(f"   - 异常数: {result.get('anomalies', 0)}")
    
    print("\n测试完成!")


async def test_scheduler():
    """测试调度器"""
    print("\n" + "="*60)
    print("测试 Scheduler")
    print("="*60)
    
    # 测试Cron解析
    print("\n1. 测试Cron解析:")
    test_crons = [
        "0 * * * *",      # 每小时
        "*/15 * * * *",   # 每15分钟
        "0 6 * * *",      # 每天6点
    ]
    
    for cron in test_crons:
        parser = CronParser(cron)
        next_run = parser.get_next_run()
        print(f"   - {cron} -> 下次: {next_run.strftime('%H:%M:%S')}")
    
    # 测试调度器
    print("\n2. 测试调度器:")
    scheduler = SessionScheduler()
    await scheduler.start()
    
    # 注册Session
    scheduler.register_session(
        session_id="test_session",
        agent_id="test_agent",
        session_type="triggered",
        trigger_config={"events": ["test_event"]}
    )
    
    # 触发事件
    await scheduler.trigger_event("test_event", {"data": "test"})
    
    # 查看状态
    status = scheduler.get_status()
    print(f"   - 总Sessions: {status['total_sessions']}")
    print(f"   - 状态: {status['sessions']}")
    
    await scheduler.stop()
    
    print("\n测试完成!")


async def main():
    print("\n" + "="*60)
    print("DFEcrab Gateway 测试套件")
    print("="*60)
    
    # 测试Agent
    await test_agents()
    
    # 测试调度器
    await test_scheduler()
    
    # 测试Gateway (需要端口未被占用)
    try:
        await test_gateway()
    except Exception as e:
        print(f"\nGateway测试跳过: {e}")
    
    print("\n" + "="*60)
    print("所有测试完成!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
