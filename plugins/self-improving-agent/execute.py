#!/usr/bin/env python3
"""
Self-Improving Agent - Main CLI Entry Point

A self-improving agent system for OpenClaw that learns from interactions
and continuously improves its performance.
"""

import argparse
import sys
import os
from pathlib import Path

# 添加当前目录到 Python 路径
skill_dir = Path(__file__).parent
sys.path.insert(0, str(skill_dir))

# 使用绝对导入替代相对导入
try:
    from src.agent import SelfImprovingAgent
    from src.hooks import HookManager
    from src.memory import LearningMemory
except ImportError as e:
    # 如果导入失败，记录错误但不中断
    import logging
    logging.warning(f"self-improving-agent 导入警告: {e}")
    SelfImprovingAgent = None
    HookManager = None
    LearningMemory = None


def execute(command: str = "run", workspace: str = None, verbose: bool = False) -> str:
    """
    执行自我改进代理的操作
    
    Args:
        command: 命令 (run/learn/review/export)
        workspace: 工作目录路径
        verbose: 是否启用详细输出
        
    Returns:
        执行结果
    """
    try:
        # 初始化组件
        workspace_path = Path(workspace) if workspace else Path.home() / '.openclaw' / 'workspace'
        agent = SelfImprovingAgent(workspace=str(workspace_path))
        hooks = HookManager(workspace=str(workspace_path))
        memory = LearningMemory(workspace=str(workspace_path))
        
        # 执行命令
        if command == 'run':
            return run_agent(agent, hooks, memory, verbose=verbose)
        elif command == 'learn':
            return learn_from_session(agent, memory, verbose=verbose)
        elif command == 'review':
            return review_learnings(memory, verbose=verbose)
        elif command == 'export':
            return export_learnings(memory, verbose=verbose)
        else:
            return "未知命令，可用命令: run, learn, review, export"
    except Exception as e:
        return f"执行失败: {str(e)}"


def run_agent(agent, hooks, memory, verbose=False):
    """Run the self-improving agent."""
    result = ["🧤 启动自我改进代理..."]
    
    # 加载学习内容
    memory.load()
    result.append("📚 加载学习内容完成")
    
    # 应用钩子
    hooks.apply_all()
    result.append("🔗 应用钩子完成")
    
    # 运行代理
    agent.run()
    result.append("✅ 代理运行成功")
    
    return "\n".join(result)


def learn_from_session(agent, memory, verbose=False):
    """Learn from the last session."""
    result = ["📚 分析上一个会话..."]
    
    # 提取学习内容
    learnings = agent.extract_learnings()
    
    # 存储学习内容
    memory.store(learnings)
    
    result.append(f"✅ 存储了 {len(learnings)} 条学习内容")
    return "\n".join(result)


def review_learnings(memory, verbose=False):
    """Review all stored learnings."""
    result = ["📖 查看学习内容..."]
    
    learnings = memory.get_all()
    
    for i, learning in enumerate(learnings, 1):
        result.append(f"\n{i}. {learning['title']}")
        result.append(f"   类别: {learning['category']}")
        result.append(f"   日期: {learning['date']}")
        if verbose:
            result.append(f"   内容: {learning['content']}")
    
    result.append(f"\n✅ 总计: {len(learnings)} 条学习内容")
    return "\n".join(result)


def export_learnings(memory, verbose=False):
    """Export learnings to a file."""
    result = ["📤 导出学习内容..."]
    
    output_file = Path.cwd() / 'learnings_export.md'
    memory.export(output_file)
    
    result.append(f"✅ 导出到 {output_file}")
    return "\n".join(result)


def main():
    """Main entry point for the self-improving-agent CLI."""
    parser = argparse.ArgumentParser(
        description='Self-Improving Agent - Continuous learning agent for OpenClaw'
    )
    
    parser.add_argument(
        'command',
        choices=['run', 'learn', 'review', 'export'],
        help='Command to execute'
    )
    
    parser.add_argument(
        '--workspace',
        type=str,
        default=Path.home() / '.openclaw' / 'workspace',
        help='Path to OpenClaw workspace'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    args = parser.parse_args()
    
    result = execute(
        command=args.command,
        workspace=args.workspace,
        verbose=args.verbose
    )
    print(result)


if __name__ == '__main__':
    main()
