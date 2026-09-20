#!/usr/bin/env python3
"""
统一记忆管理器性能测试

测量关键 API 的性能指标：
1. 搜索延迟
2. 上下文加载时间
3. 记忆添加吞吐量
"""

import asyncio
import time
import statistics
from pathlib import Path

# 添加项目根目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory.unified_manager import UnifiedMemoryManager
from src.memory.types import MemoryConfig


async def measure_search_latency(manager, query: str, iterations: int = 10):
    """测量搜索延迟"""
    latencies = []
    
    for i in range(iterations):
        start = time.perf_counter()
        results = await manager.search_memory(query=query, limit=5)
        end = time.perf_counter()
        latencies.append((end - start) * 1000)  # 转换为毫秒
    
    return {
        "query": query,
        "iterations": iterations,
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else None,
        "results_count": len(results) if i > 0 else 0
    }


async def measure_context_loading(manager, agent_id: str, iterations: int = 5):
    """测量上下文加载时间"""
    latencies = []
    
    for i in range(iterations):
        start = time.perf_counter()
        context = await manager.get_context(agent_id=agent_id, recent_days=1)
        end = time.perf_counter()
        latencies.append((end - start) * 1000)
    
    return {
        "operation": "get_context",
        "iterations": iterations,
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies)
    }


async def measure_memory_addition(manager, iterations: int = 20):
    """测量记忆添加吞吐量"""
    latencies = []
    
    for i in range(iterations):
        content = f"性能测试记忆条目 {i} - {time.time()}"
        start = time.perf_counter()
        entry = await manager.add_memory(
            content=content,
            memory_type="agent_private",
            agent_id="perf_test_agent",
            category="general"
        )
        end = time.perf_counter()
        latencies.append((end - start) * 1000)
    
    # 计算吞吐量（操作数/秒）
    total_time = sum(latencies) / 1000  # 秒
    throughput = iterations / total_time if total_time > 0 else 0
    
    return {
        "operation": "add_memory",
        "iterations": iterations,
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "throughput_ops_per_sec": throughput
    }


async def run_performance_tests():
    """运行性能测试套件"""
    print("=" * 60)
    print("统一记忆管理器性能测试")
    print("=" * 60)
    
    config = MemoryConfig(
        keyword_search_enabled=True,
        vector_search_enabled=False,
        hybrid_search_enabled=False,
        enable_monitoring=False
    )
    
    manager = UnifiedMemoryManager(config)
    
    results = {}
    
    # 测试1: 搜索延迟
    print("\n1. 搜索延迟测试...")
    search_results = await measure_search_latency(manager, "编程", iterations=10)
    results["search_latency"] = search_results
    print(f"   查询: '{search_results['query']}'")
    print(f"   平均延迟: {search_results['mean_ms']:.2f} ms")
    print(f"   最小延迟: {search_results['min_ms']:.2f} ms")
    print(f"   最大延迟: {search_results['max_ms']:.2f} ms")
    print(f"   结果数量: {search_results['results_count']}")
    
    # 测试2: 上下文加载
    print("\n2. 上下文加载测试...")
    context_results = await measure_context_loading(manager, "dfecrab", iterations=5)
    results["context_loading"] = context_results
    print(f"   平均延迟: {context_results['mean_ms']:.2f} ms")
    print(f"   最小延迟: {context_results['min_ms']:.2f} ms")
    print(f"   最大延迟: {context_results['max_ms']:.2f} ms")
    
    # 测试3: 记忆添加吞吐量
    print("\n3. 记忆添加吞吐量测试...")
    addition_results = await measure_memory_addition(manager, iterations=10)
    results["memory_addition"] = addition_results
    print(f"   平均延迟: {addition_results['mean_ms']:.2f} ms")
    print(f"   吞吐量: {addition_results['throughput_ops_per_sec']:.2f} 操作/秒")
    
    # 成功指标检查
    print("\n" + "=" * 60)
    print("性能指标检查")
    print("=" * 60)
    
    # 检查是否满足性能目标（API响应时间<100ms）
    search_pass = search_results["mean_ms"] < 100
    context_pass = context_results["mean_ms"] < 100
    addition_pass = addition_results["mean_ms"] < 100
    
    print(f"搜索延迟 <100ms: {'✅' if search_pass else '❌'} ({search_results['mean_ms']:.2f} ms)")
    print(f"上下文加载 <100ms: {'✅' if context_pass else '❌'} ({context_results['mean_ms']:.2f} ms)")
    print(f"记忆添加 <100ms: {'✅' if addition_pass else '❌'} ({addition_results['mean_ms']:.2f} ms)")
    
    all_pass = search_pass and context_pass and addition_pass
    
    # 生成报告
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "performance_goals_met": all_pass,
        "results": results,
        "summary": {
            "search_mean_ms": search_results["mean_ms"],
            "context_mean_ms": context_results["mean_ms"],
            "addition_mean_ms": addition_results["mean_ms"],
            "addition_throughput": addition_results["throughput_ops_per_sec"]
        }
    }
    
    # 保存报告
    report_dir = Path("data/memory/performance_reports")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / f"performance_{time.strftime('%Y%m%d_%H%M%S')}.json"
    
    import json
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n性能报告已保存: {report_file}")
    
    if all_pass:
        print("\n✅ 所有性能指标满足要求！")
        return 0
    else:
        print("\n⚠️  部分性能指标未达到目标")
        return 1


async def main():
    """主函数"""
    try:
        return await run_performance_tests()
    except Exception as e:
        print(f"性能测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)