"""
多智能体组团协作 - 真实协作测试

测试场景：qwen 设计 -> codebuddy 开发 -> qwen 测试确认
"""

import asyncio
import sys
import os
import json

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.agent.multi import (
    AgentRegistry,
    AgentCommunicationBus,
    MultiAgentOrchestrator,
    CollaborationMode,
)


async def test_qwen_design_codebuddy_implement():
    """
    测试真实协作场景：
    1. qwen 设计方案
    2. codebuddy 实现代码
    3. qwen 测试确认
    """
    print("\n" + "=" * 60)
    print("🤝 真实协作测试: QwenCode 设计 -> CodeBuddy 实现 -> QwenCode 测试")
    print("=" * 60)

    # 初始化
    registry = AgentRegistry(config_path="config/multi_agent.json")
    await registry.initialize()

    bus = AgentCommunicationBus()
    await bus.start()

    orchestrator = MultiAgentOrchestrator(registry, bus)
    await orchestrator.initialize()

    # 显示可用智能体
    agents = orchestrator.get_available_agents()
    print(f"\n📋 可用智能体 ({len(agents)} 个):")
    for agent in agents:
        print(f"   - {agent.name} ({agent.id}): {agent.status.value}")
        print(f"     角色: {agent.roles}")
        print(f"     能力: {agent.capabilities}")

    # 发起协作任务
    task_message = """
请设计并实现一个简单的 Python 工具函数：

功能：计算两个日期之间的工作日数量（排除周末）

要求：
1. 函数签名：def count_workdays(start_date: str, end_date: str) -> int
2. 输入格式：YYYY-MM-DD
3. 返回工作日数量
4. 包含简单的错误处理

请按以下流程协作：
1. 设计：分析需求，设计函数结构
2. 实现：编写代码
3. 测试：验证功能
"""

    print(f"\n📝 任务: {task_message.strip()[:100]}...")

    # 使用链式协作模式
    result = await orchestrator.chat(
        message=task_message,
        mode="chain",
        roles={
            "designer": "qwencode",
            "developer": "codebuddy",
            "reviewer": "qwencode"
        },
        options={"timeout": 300}
    )

    # 输出结果
    print(f"\n📊 任务结果:")
    print(f"   状态: {result.status.value}")
    print(f"   进度: {result.progress}%")
    print(f"   步骤数: {len(result.steps)}")

    for i, step in enumerate(result.steps):
        print(f"\n{'='*50}")
        print(f"📌 步骤 {i+1}: {step.action}")
        print(f"   执行者: {step.agent_id}")
        print(f"   状态: {step.status}")
        print(f"   耗时: {step.duration:.2f}秒")

        if step.error:
            print(f"   ❌ 错误: {step.error}")

        if step.output:
            output = step.output[:500] + "..." if len(step.output) > 500 else step.output
            print(f"\n   输出:\n   {output}")

    if result.final_output:
        print(f"\n{'='*60}")
        print("📄 最终输出:")
        print(result.final_output[:1000])

    # 清理
    await orchestrator.shutdown()
    await registry.shutdown()

    print("\n" + "=" * 60)
    print(f"✅ 测试完成: {'成功' if result.status.value == 'completed' else '失败'}")
    print("=" * 60)

    return result.status.value == "completed"


async def test_api_integration():
    """测试 API 集成"""
    print("\n" + "=" * 60)
    print("🔌 API 集成测试")
    print("=" * 60)

    from src.gateway.handlers.multi_agent_handler import (
        ensure_initialized,
        list_agents,
        list_modes,
        health_check,
    )

    # 确保初始化
    await ensure_initialized()

    # 模拟请求对象
    class MockRequest:
        path_params = {}

        async def json(self):
            return {}

    # 测试列出智能体
    agents_result = await list_agents(MockRequest())
    print(f"\n📋 智能体列表:")
    print(f"   成功: {agents_result.get('success')}")
    print(f"   数量: {agents_result.get('count')}")

    for agent in agents_result.get("agents", []):
        print(f"   - {agent['name']} ({agent['status']})")

    # 测试列出协作模式
    modes_result = await list_modes(MockRequest())
    print(f"\n🔄 协作模式:")
    for mode in modes_result.get("modes", []):
        print(f"   - {mode['id']}: {mode['description']}")

    # 测试健康检查
    health_result = await health_check(MockRequest())
    print(f"\n💚 健康检查:")
    print(f"   状态: {health_result.get('status')}")
    print(f"   在线智能体: {health_result.get('agents', {}).get('online')}/{health_result.get('agents', {}).get('total')}")

    print("\n✅ API 集成测试完成")
    return True


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("🚀 DFEcrab 多智能体组团协作 - 真实测试")
    print("=" * 60)

    results = []

    # 测试 1: API 集成
    results.append(("API 集成", await test_api_integration()))

    # 测试 2: 真实协作
    results.append(("真实协作", await test_qwen_design_codebuddy_implement()))

    # 汇总
    print("\n" + "=" * 60)
    print("📊 测试汇总")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {name}: {status}")

    print(f"\n   总计: {passed}/{len(results)} 通过")
    print("=" * 60)

    return passed == len(results)


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
