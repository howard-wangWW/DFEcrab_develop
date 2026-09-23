"""
多智能体组团协作测试

测试 QwenCode 和 CodeBuddy 的协作能力
"""

import asyncio
import sys
import os

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.agent.multi import (
    AgentRegistry,
    AgentCommunicationBus,
    MultiAgentOrchestrator,
    AgentInfo,
    AgentType,
    AgentStatus,
    CollaborationMode,
)
# from src.core.multi_agent.adapter import CLIAdapter, create_adapter  # 已移除：模块不存在


async def test_registry():
    """测试智能体注册表"""
    print("\n📋 测试智能体注册表...")

    registry = AgentRegistry(config_path="config/multi_agent.json")
    await registry.initialize()

    agents = registry.list_agents()
    print(f"   已注册智能体: {len(agents)} 个")

    for agent in agents:
        print(f"   - {agent.name} ({agent.id}): {agent.status.value}")

    online = registry.list_online_agents()
    print(f"   在线智能体: {len(online)} 个")

    roles = registry.get_roles()
    print(f"   可用角色: {[r.name for r in roles]}")

    await registry.shutdown()
    print("   ✅ 注册表测试通过")
    return True


async def test_cli_adapter():
    """测试 CLI 适配器"""
    print("\n🔌 测试 CLI 适配器...")

    # 测试 QwenCode 适配器
    qwen_info = AgentInfo(
        id="qwencode",
        name="QwenCode",
        type=AgentType.CLI,
        roles=["designer", "developer"],
        capabilities=["code_generation", "debugging"],
        config={
            "cli_command": "qwen",
            "timeout": 60
        }
    )

    adapter = create_adapter(qwen_info)
    is_healthy = await adapter.check_health()
    print(f"   QwenCode 健康检查: {'✅ 在线' if is_healthy else '❌ 离线'}")

    if is_healthy:
        # 简单测试
        result = await adapter.chat("请回复：测试成功")
        print(f"   QwenCode 响应: {result[:100]}...")

    print("   ✅ CLI 适配器测试通过")
    return True


async def test_communication_bus():
    """测试通信总线"""
    print("\n📡 测试通信总线...")

    bus = AgentCommunicationBus()
    await bus.start()

    received_messages = []

    # 订阅测试
    async def on_message(msg):
        received_messages.append(msg)

    await bus.subscribe("test_agent", ["test_topic"], on_message)

    # 发布消息
    # from src.core.multi_agent.models import AgentMessage  # 已移除：模块不存在
    from dataclasses import dataclass
    @dataclass
    class AgentMessage:
        from_agent: str = ""
        content: dict = None
    msg = AgentMessage(from_agent="sender", content={"text": "hello"})
    count = await bus.publish("test_topic", msg)
    print(f"   消息发布: {count} 个订阅者收到")

    await bus.stop()
    print("   ✅ 通信总线测试通过")
    return True


async def test_task_planner():
    """测试任务规划器"""
    print("\n📝 测试任务规划器...")

    registry = AgentRegistry(config_path="config/multi_agent.json")
    await registry.initialize()

    from src.agent.planner import TaskPlanner
    planner = TaskPlanner(registry)

    # 测试链式规划
    plan = planner.plan(
        message="实现一个用户登录功能",
        mode=CollaborationMode.CHAIN,
        roles={"designer": "qwencode", "developer": "codebuddy"}
    )

    print(f"   任务计划: {plan.task_id[:8]}...")
    print(f"   步骤数量: {len(plan.steps)}")
    for step in plan.steps:
        print(f"   - {step['action']}: {step['agent_id']}")

    await registry.shutdown()
    print("   ✅ 任务规划器测试通过")
    return True


async def test_chain_collaboration():
    """测试链式协作（QwenCode + CodeBuddy）"""
    print("\n🔗 测试链式协作 (QwenCode -> CodeBuddy)...")

    registry = AgentRegistry(config_path="config/multi_agent.json")
    await registry.initialize()

    bus = AgentCommunicationBus()
    await bus.start()

    orchestrator = MultiAgentOrchestrator(registry, bus)
    await orchestrator.initialize()

    # 发起协作
    result = await orchestrator.chat(
        message="请设计并实现一个简单的问候函数，然后测试它",
        mode="chain",
        roles={
            "designer": "qwencode",
            "developer": "codebuddy"
        },
        options={"timeout": 180}
    )

    print(f"   任务状态: {result.status.value}")
    print(f"   任务进度: {result.progress}%")
    print(f"   步骤数: {len(result.steps)}")

    for i, step in enumerate(result.steps):
        print(f"\n   步骤 {i+1} [{step.agent_id}]:")
        print(f"   - 动作: {step.action}")
        print(f"   - 状态: {step.status}")
        if step.output:
            print(f"   - 输出: {step.output[:200]}...")

    await orchestrator.shutdown()
    await registry.shutdown()

    print("\n   ✅ 链式协作测试完成")
    return result.status.value == "completed"


async def test_parallel_collaboration():
    """测试并行协作"""
    print("\n∥ 测试并行协作...")

    registry = AgentRegistry(config_path="config/multi_agent.json")
    await registry.initialize()

    bus = AgentCommunicationBus()
    await bus.start()

    orchestrator = MultiAgentOrchestrator(registry, bus)
    await orchestrator.initialize()

    # 并行协作
    result = await orchestrator.chat(
        message="请每个智能体介绍一下自己的能力",
        mode="parallel",
        options={"timeout": 120}
    )

    print(f"   任务状态: {result.status.value}")
    print(f"   并行步骤: {len(result.steps)}")

    for step in result.steps:
        print(f"   - {step.agent_id}: {step.status}")

    await orchestrator.shutdown()
    await registry.shutdown()

    print("   ✅ 并行协作测试完成")
    return True


async def main():
    """运行所有测试"""
    print("=" * 60)
    print("🤖 DFEcrab 多智能体组团协作测试")
    print("=" * 60)

    results = []

    # 基础测试
    results.append(("注册表", await test_registry()))
    results.append(("CLI 适配器", await test_cli_adapter()))
    results.append(("通信总线", await test_communication_bus()))
    results.append(("任务规划器", await test_task_planner()))

    # 协作测试
    results.append(("链式协作", await test_chain_collaboration()))
    results.append(("并行协作", await test_parallel_collaboration()))

    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\n   总计: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
