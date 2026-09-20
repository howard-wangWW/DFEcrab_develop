#!/usr/bin/env python3
"""
统一记忆管理器的系统集成测试

验证核心功能是否正常工作。
"""

import sys
import asyncio
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.memory.unified_manager import UnifiedMemoryManager
from src.memory.types import MemoryConfig


async def test_initialization():
    """测试初始化"""
    print("1. 测试初始化...")
    config = MemoryConfig(
        keyword_search_enabled=True,
        vector_search_enabled=False,
        hybrid_search_enabled=False,
        enable_monitoring=False
    )
    manager = UnifiedMemoryManager(config)
    # 初始化应该在内置 __init__ 中完成
    assert manager is not None
    assert hasattr(manager, 'modules')
    print(f"  ✅ 初始化成功，加载了 {len(manager.modules)} 个模块")
    return manager


async def test_module_access(manager):
    """测试模块访问"""
    print("\n2. 测试模块访问...")
    daily_module = manager.get_module("daily")
    assert daily_module is not None
    print(f"  ✅ DailyModule: {daily_module}")
    
    agent_module = manager.get_module("agent")
    assert agent_module is not None
    print(f"  ✅ AgentModule: {agent_module}")
    
    global_module = manager.get_module("global")
    assert global_module is not None
    print(f"  ✅ GlobalModule: {global_module}")
    
    return True


async def test_search_functionality(manager):
    """测试搜索功能"""
    print("\n3. 测试搜索功能...")
    
    # 关键词搜索
    results = await manager.search_memory(
        query="编程",
        limit=5
    )
    assert isinstance(results, list)
    print(f"  ✅ 关键词搜索 '编程' 返回 {len(results)} 个结果")
    
    if len(results) > 0:
        for i, r in enumerate(results[:3]):
            print(f"    {i+1}. {r.memory_entry.content[:80]}... (score: {r.score:.3f})")
    
    # 测试空查询
    empty_results = await manager.search_memory(
        query="thisshouldnotmatchanything123",
        limit=2
    )
    assert isinstance(empty_results, list)
    print(f"  ✅ 无匹配查询返回 {len(empty_results)} 个结果（应为 0）")
    
    return True


async def test_stats(manager):
    """测试统计信息"""
    print("\n4. 测试统计信息...")
    
    stats = await manager.get_stats()
    assert stats is not None
    assert hasattr(stats, 'total_memories')
    print(f"  ✅ 统计信息: 总记忆数={stats.total_memories}")
    
    # 打印按类型分布
    if hasattr(stats, 'by_type'):
        for mem_type, count in stats.by_type.items():
            print(f"    - {mem_type}: {count}")
    
    return True


async def test_compatibility_bridges(manager):
    """测试兼容性桥接"""
    print("\n5. 测试兼容性桥接...")
    
    # 测试 HierarchicalMemoryManager 桥接
    hierarchical = manager.get_hierarchical_manager()
    assert hierarchical is not None
    print(f"  ✅ HierarchicalMemoryManager 桥接成功")
    
    # 测试 MarkdownMemoryManager 桥接
    markdown = manager.get_markdown_manager("test_agent")
    assert markdown is not None
    print(f"  ✅ MarkdownMemoryManager 桥接成功")
    
    # 测试 MemoryManager 桥接
    legacy = manager.get_memory_manager()
    assert legacy is not None
    print(f"  ✅ MemoryManager 桥接成功")
    
    return True


async def main():
    """主测试函数"""
    print("=" * 60)
    print("统一记忆管理器系统集成测试")
    print("=" * 60)
    
    try:
        # 测试初始化
        manager = await test_initialization()
        
        tests = [
            (test_module_access, manager),
            (test_search_functionality, manager),
            (test_stats, manager),
            (test_compatibility_bridges, manager)
        ]
        
        passed = 0
        failed = 0
        
        for test_func, arg in tests:
            try:
                success = await test_func(arg)
                if success:
                    passed += 1
                else:
                    failed += 1
                    print(f"  ❌ {test_func.__name__} 失败")
            except Exception as e:
                failed += 1
                print(f"  ❌ {test_func.__name__} 异常: {e}")
                import traceback
                traceback.print_exc()
        
        print("\n" + "=" * 60)
        print(f"测试完成: 通过 {passed}，失败 {failed}")
        print("=" * 60)
        
        if failed == 0:
            print("\n✅ 所有测试通过！")
            return 0
        else:
            print("\n❌ 部分测试失败")
            return 1
            
    except Exception as e:
        print(f"测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    # 运行异步测试
    exit_code = asyncio.run(main())
    sys.exit(exit_code)