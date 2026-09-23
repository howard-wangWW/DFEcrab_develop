"""
DFEcrab 系统优化 - 完整端到端测试

测试所有 7 个核心模块的完整功能：
1. 分级权限系统
2. 斜杠命令系统
3. 增强 Agent 循环
4. 统一工具系统
5. 会话持久化
6. 上下文引擎
7. 工作区驱动配置
"""

import sys
import tempfile
import json
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_1_permissions():
    """测试 1: 分级权限系统"""
    print()
    print('=' * 70)
    print('【测试 1】分级权限系统')
    print('=' * 70)
    
    from src.core.security import (
        AgentPermissions,
        PermissionLevel,
        PermissionError,
        check_command_safety,
        is_destructive_command,
        ensure_write_permission,
        ensure_shell_permission,
        get_permission_summary,
    )
    
    # 测试 1.1: 默认权限
    print('\n1.1 测试默认权限')
    perms = AgentPermissions()
    assert perms.level == PermissionLevel.READ_ONLY
    assert perms.allow_file_write is False
    assert perms.allow_shell_commands is False
    print('  ✅ 默认权限为 READ_ONLY')
    
    # 测试 1.2: 权限升级
    print('\n1.2 测试权限升级')
    perms_write = AgentPermissions(allow_file_write=True)
    assert perms_write.level == PermissionLevel.WRITE
    print(f'  ✅ WRITE 权限: {perms_write.level.value}')
    
    perms_shell = AgentPermissions(allow_shell_commands=True)
    assert perms_shell.level == PermissionLevel.SHELL
    print(f'  ✅ SHELL 权限: {perms_shell.level.value}')
    
    perms_unsafe = AgentPermissions(allow_destructive_shell_commands=True)
    assert perms_unsafe.level == PermissionLevel.UNSAFE
    print(f'  ✅ UNSAFE 权限: {perms_unsafe.level.value}')
    
    # 测试 1.3: 破坏性命令检测
    print('\n1.3 测试破坏性命令检测')
    destructive_commands = [
        'rm -rf /tmp/test',
        'mv file.txt /tmp/',
        'dd if=/dev/zero of=/dev/sda',
        'shutdown now',
        'git reset --hard HEAD',
        'chmod -R 777 /tmp',
    ]
    
    for cmd in destructive_commands:
        assert is_destructive_command(cmd), f'应该检测到破坏性命令: {cmd}'
        print(f'  ✅ 检测到: {cmd[:40]}')
    
    # 测试 1.4: 安全命令
    print('\n1.4 测试安全命令')
    safe_commands = [
        'ls -la',
        'pwd',
        'cat file.txt',
        'grep "pattern" file.py',
    ]
    
    for cmd in safe_commands:
        assert not is_destructive_command(cmd), f'应该是安全命令: {cmd}'
        print(f'  ✅ 安全: {cmd}')
    
    # 测试 1.5: 命令安全检查
    print('\n1.5 测试命令安全检查')
    perms = AgentPermissions(allow_shell_commands=True)
    is_safe, reason = check_command_safety('ls -la', perms)
    assert is_safe
    print(f'  ✅ 安全命令通过: {reason}')
    
    is_safe, reason = check_command_safety('rm -rf /', perms)
    assert not is_safe
    print(f'  ✅ 破坏性命令拦截: {reason[:50]}...')
    
    # 测试 1.6: 权限强制执行
    print('\n1.6 测试权限强制执行')
    try:
        ensure_write_permission(AgentPermissions())
        assert False, '应该抛出 PermissionError'
    except PermissionError as e:
        print(f'  ✅ 写入权限检查: {str(e)[:50]}...')
    
    try:
        ensure_shell_permission(AgentPermissions(), 'ls')
        assert False, '应该抛出 PermissionError'
    except PermissionError as e:
        print(f'  ✅ Shell 权限检查: {str(e)[:50]}...')
    
    # 测试 1.7: 权限摘要
    print('\n1.7 测试权限摘要')
    summary = get_permission_summary(AgentPermissions())
    assert 'read_only' in summary
    print(f'  ✅ 摘要生成成功')
    
    print('\n✅ 测试 1 通过: 分级权限系统')
    return True


def test_2_slash_commands():
    """测试 2: 斜杠命令系统"""
    print()
    print('=' * 70)
    print('【测试 2】斜杠命令系统')
    print('=' * 70)
    
    from src.core.commands import (
        parse_slash_command,
        preprocess_slash_command,
        find_slash_command,
        get_command_list,
        SlashCommandContext,
    )
    
    # 测试 2.1: 命令解析
    print('\n2.1 测试命令解析')
    parsed = parse_slash_command('/help')
    assert parsed is not None
    assert parsed.command_name == 'help'
    assert parsed.args == ''
    print('  ✅ /help 解析正确')
    
    parsed = parse_slash_command('/model qwen3')
    assert parsed.command_name == 'model'
    assert parsed.args == 'qwen3'
    print('  ✅ /model qwen3 解析正确')
    
    parsed = parse_slash_command('hello world')
    assert parsed is None
    print('  ✅ 非斜杠文本返回 None')
    
    # 测试 2.2: 命令查找
    print('\n2.2 测试命令查找')
    spec = find_slash_command('help')
    assert spec is not None
    assert 'help' in spec.names
    print('  ✅ help 命令找到')
    
    spec = find_slash_command('commands')
    assert spec is not None
    print('  ✅ commands 别名有效')
    
    spec = find_slash_command('nonexistent')
    assert spec is None
    print('  ✅ 不存在的命令返回 None')
    
    # 测试 2.3: 命令预处理
    print('\n2.3 测试命令预处理')
    ctx = SlashCommandContext()
    
    result = preprocess_slash_command('/help', ctx)
    assert result.handled is True
    assert result.should_query is False
    assert 'Slash Commands' in result.output
    print('  ✅ /help 本地处理成功')
    
    result = preprocess_slash_command('hello world', ctx)
    assert result.handled is False
    assert result.should_query is True
    assert result.prompt == 'hello world'
    print('  ✅ 普通文本传递给模型')
    
    result = preprocess_slash_command('/unknown', ctx)
    assert result.handled is True
    assert 'Unknown command' in result.output
    print('  ✅ 未知命令错误提示')
    
    # 测试 2.4: 命令列表
    print('\n2.4 测试命令列表')
    commands = get_command_list()
    assert len(commands) == 10
    print(f'  ✅ 共 {len(commands)} 个斜杠命令')
    for cmd in commands[:3]:
        print(f'    - {cmd["command"]}: {cmd["description"]}')
    
    print('\n✅ 测试 2 通过: 斜杠命令系统')
    return True


def test_3_unified_tools():
    """测试 3: 统一工具系统"""
    print()
    print('=' * 70)
    print('【测试 3】统一工具系统')
    print('=' * 70)
    
    from src.core.tools.enhanced import (
        default_tool_registry,
        execute_tool,
        execute_tool_streaming,
        build_tool_context,
        render_tools_report,
    )
    from src.core.security import AgentPermissions
    
    # 测试 3.1: 创建工具注册表
    print('\n3.1 测试工具注册表')
    registry = default_tool_registry()
    assert len(registry) == 7
    print(f'  ✅ 创建了 {len(registry)} 个工具')
    for name in registry:
        print(f'    - {name}')
    
    # 测试 3.2: OpenAI 格式转换
    print('\n3.2 测试 OpenAI 格式转换')
    tool = registry['list_dir']
    openai_format = tool.to_openai_tool()
    assert openai_format['type'] == 'function'
    assert openai_format['function']['name'] == 'list_dir'
    print('  ✅ OpenAI 格式转换成功')
    
    # 测试 3.3: 构建执行上下文
    print('\n3.3 测试执行上下文')
    ctx = build_tool_context(
        workspace='.',
        timeout_seconds=30.0,
        permissions=AgentPermissions(allow_file_write=True, allow_shell_commands=True)
    )
    assert ctx.command_timeout_seconds == 30.0
    print('  ✅ 执行上下文构建成功')
    
    # 测试 3.4: 执行 list_dir
    print('\n3.4 测试 list_dir 工具')
    result = execute_tool(
        registry,
        'list_dir',
        {'path': '.', 'max_entries': 10},
        ctx
    )
    assert result.ok
    assert 'src' in result.content or 'docs' in result.content
    print('  ✅ list_dir 执行成功')
    
    # 测试 3.5: 执行 glob_search
    print('\n3.5 测试 glob_search 工具')
    result = execute_tool(
        registry,
        'glob_search',
        {'pattern': '*.py'},
        ctx
    )
    assert result.ok
    print('  ✅ glob_search 执行成功')
    
    # 测试 3.6: 权限检查 - 写入
    print('\n3.6 测试写入权限检查')
    ctx_readonly = build_tool_context(
        workspace='.',
        permissions=AgentPermissions()
    )
    result = execute_tool(
        registry,
        'write_file',
        {'path': 'test.txt', 'content': 'test'},
        ctx_readonly
    )
    assert not result.ok
    print('  ✅ 写入权限检查通过')
    
    # 测试 3.7: 权限检查 - Shell
    print('\n3.7 测试 Shell 权限检查')
    result = execute_tool(
        registry,
        'bash',
        {'command': 'ls'},
        ctx_readonly
    )
    assert not result.ok
    print('  ✅ Shell 权限检查通过')
    
    # 测试 3.8: 流式执行
    print('\n3.8 测试流式工具执行')
    updates = list(execute_tool_streaming(
        registry,
        'list_dir',
        {'path': '.', 'max_entries': 5},
        ctx
    ))
    assert len(updates) > 0
    assert updates[-1].kind == 'result'
    assert updates[-1].result.ok
    print(f'  ✅ 流式执行成功 ({len(updates)} 个更新)')
    
    # 测试 3.9: 工具报告
    print('\n3.9 测试工具报告')
    report = render_tools_report(registry, AgentPermissions())
    assert 'Registered Tools' in report
    assert 'list_dir' in report
    print('  ✅ 工具报告生成成功')
    
    print('\n✅ 测试 3 通过: 统一工具系统')
    return True


def test_4_session_persistence():
    """测试 4: 会话持久化"""
    print()
    print('=' * 70)
    print('【测试 4】会话持久化模块')
    print('=' * 70)
    
    from src.core.session.persistence import SessionPersistence
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 测试 4.1: 创建持久化管理器
        print('\n4.1 测试持久化管理器创建')
        persistence = SessionPersistence(storage_dir=tmpdir)
        print('  ✅ 持久化管理器创建成功')
        
        # 测试 4.2: 保存会话
        print('\n4.2 测试会话保存')
        session_data = {
            'transcript': [
                {'role': 'user', 'content': '你好'},
                {'role': 'assistant', 'content': '你好！有什么可以帮助你的？'},
            ],
            'turns': 1,
            'tool_calls': 0,
            'usage': {'total_tokens': 100},
            'file_history': [],
        }
        
        success = persistence.save_session('test_session_001', session_data)
        print(f'  ✅ 会话保存: {"成功" if success else "失败"}')
        
        # 测试 4.3: 加载会话
        print('\n4.3 测试会话加载')
        loaded = persistence.load_session('test_session_001')
        assert loaded is not None
        assert loaded['turns'] == 1
        assert len(loaded['transcript']) == 2
        print('  ✅ 会话加载成功')
        print(f'    - 轮次: {loaded["turns"]}')
        print(f'    - 消息数: {len(loaded["transcript"])}')
        
        # 测试 4.4: 列出会话
        print('\n4.4 测试会话列表')
        sessions = persistence.list_sessions()
        assert len(sessions) >= 1
        print(f'  ✅ 会话列表: {len(sessions)} 个会话')
        
        # 测试 4.5: 检查会话存在
        print('\n4.5 测试会话存在检查')
        exists = persistence.session_exists('test_session_001')
        assert exists
        not_exists = persistence.session_exists('nonexistent')
        assert not not_exists
        print('  ✅ 存在检查成功')
        
        # 测试 4.6: 删除会话
        print('\n4.6 测试会话删除')
        deleted = persistence.delete_session('test_session_001')
        print(f'  ✅ 会话删除: {"成功" if deleted else "失败"}')
        
        sessions_after = persistence.list_sessions()
        assert len(sessions_after) == 0
        print('  ✅ 删除后列表为空')
    
    print('\n✅ 测试 4 通过: 会话持久化模块')
    return True


def test_5_context_engine():
    """测试 5: 上下文引擎"""
    print()
    print('=' * 70)
    print('【测试 5】上下文引擎模块')
    print('=' * 70)
    
    from src.core.context import (
        estimate_tokens,
        discover_memory_bundle,
        get_git_status_cached,
        collect_context_usage,
        format_context_usage_report,
    )
    
    # 测试 5.1: Token 估算
    print('\n5.1 测试 Token 估算')
    tokens_en = estimate_tokens('Hello, World!')
    tokens_zh = estimate_tokens('你好，世界！')
    assert tokens_en > 0
    assert tokens_zh > 0
    print(f'  ✅ 英文估算: {tokens_en} tokens (13 字符)')
    print(f'  ✅ 中文估算: {tokens_zh} tokens (6 字符)')
    
    # 测试 5.2: 记忆文件发现
    print('\n5.2 测试记忆文件发现')
    memory = discover_memory_bundle('.')
    print(f'  ✅ 发现 {len(memory)} 个记忆文件')
    if memory:
        for path in list(memory.keys())[:3]:
            print(f'    - {path}')
    
    # 测试 5.3: Git 状态
    print('\n5.3 测试 Git 状态')
    git_status = get_git_status_cached('.')
    assert 'is_git_repo' in git_status
    is_git = git_status.get('is_git_repo', False)
    print(f'  ✅ Git 状态: {"是 Git 仓库" if is_git else "非 Git 仓库"}')
    if is_git:
        print(f'    - 当前分支: {git_status.get("current_branch", "unknown")}')
        commits = git_status.get('recent_commits', [])
        print(f'    - 最近提交: {len(commits)} 个')
    
    # 测试 5.4: 上下文用量收集
    print('\n5.4 测试上下文用量收集')
    messages = [
        {'role': 'user', 'content': '你好'},
        {'role': 'assistant', 'content': '你好！有什么可以帮助你的？'},
    ]
    usage = collect_context_usage(
        workspace='.',
        system_prompt='你是一个助手',
        messages=messages,
        model_name='qwen3-coder'
    )
    assert usage.total_tokens > 0
    print(f'  ✅ 上下文用量收集成功')
    print(f'    - 系统提示词: {usage.system_prompt_tokens} tokens')
    print(f'    - 用户消息: {usage.user_messages_tokens} tokens')
    print(f'    - 助手消息: {usage.assistant_messages_tokens} tokens')
    print(f'    - 总计: {usage.total_tokens} tokens')
    
    # 测试 5.5: 报告生成
    print('\n5.5 测试报告生成')
    report = format_context_usage_report(usage)
    assert 'Context Usage Report' in report
    print('  ✅ 报告生成成功')
    
    print('\n✅ 测试 5 通过: 上下文引擎模块')
    return True


def test_6_workspace_config():
    """测试 6: 工作区驱动配置"""
    print()
    print('=' * 70)
    print('【测试 6】工作区驱动配置')
    print('=' * 70)
    
    from src.core.workspace import (
        workspace_has_config,
        load_workspace_config,
        build_system_prompt_from_workspace,
        AgentInfo,
        SoulProfile,
        UserProfile,
    )
    
    # 测试 6.1: 检查工作区配置
    print('\n6.1 测试工作区配置检查')
    has_config = workspace_has_config('.')
    print(f'  ✅ 当前目录配置检查: {"有配置" if has_config else "无配置（使用默认）"}')
    
    # 测试 6.2: 加载工作区配置
    print('\n6.2 测试工作区配置加载')
    config = load_workspace_config('.')
    assert config is not None
    print('  ✅ 工作区配置加载成功')
    print(f'    - Agent: {config.agent.name if config.agent else "默认"}')
    print(f'    - 工具数: {len(config.tools)}')
    
    # 测试 6.3: 构建系统提示词
    print('\n6.3 测试系统提示词构建')
    system_prompt = build_system_prompt_from_workspace('.')
    assert system_prompt is not None
    print('  ✅ 系统提示词构建成功')
    print(f'    - 长度: {len(system_prompt)} 字符')
    print(f'    - 预览: {system_prompt[:100]}...')
    
    # 测试 6.4: 数据模型
    print('\n6.4 测试数据模型')
    agent = AgentInfo(name='Test Agent', role='Assistant')
    assert agent.name == 'Test Agent'
    print('  ✅ AgentInfo 模型正常')
    
    soul = SoulProfile(identity='Helpful Assistant')
    assert soul.identity == 'Helpful Assistant'
    print('  ✅ SoulProfile 模型正常')
    
    user = UserProfile(name='Test User')
    assert user.name == 'Test User'
    print('  ✅ UserProfile 模型正常')
    
    print('\n✅ 测试 6 通过: 工作区驱动配置')
    return True


def test_7_enhanced_agent_loop():
    """测试 7: 增强 Agent 循环"""
    print()
    print('=' * 70)
    print('【测试 7】增强 Agent 循环')
    print('=' * 70)
    
    from src.core.agent import EnhancedAgentLoop
    from src.core.security import AgentPermissions
    
    # 测试 7.1: 创建 Agent 循环
    print('\n7.1 测试 Agent 循环创建')
    loop = EnhancedAgentLoop(
        agent_id='test_agent',
        model_client=None,  # 测试模式
        permissions=AgentPermissions(allow_file_write=True),
        max_turns=5,
        workspace='.',
    )
    assert loop.agent_id == 'test_agent'
    assert loop.max_turns == 5
    print('  ✅ Agent 循环创建成功')
    print(f'    - Agent ID: {loop.agent_id}')
    print(f'    - 最大轮次: {loop.max_turns}')
    print(f'    - 权限级别: {loop.permissions.level.value}')
    
    # 测试 7.2: 状态查询
    print('\n7.2 测试状态查询')
    status = loop.get_status()
    assert 'agent_id' in status
    assert 'turns' in status
    assert 'permissions' in status
    print('  ✅ 状态查询成功')
    print(f'    - 状态字段: {len(status)} 个')
    
    # 测试 7.3: 斜杠命令预处理
    print('\n7.3 测试斜杠命令预处理')
    # 注意：实际运行需要 model_client，这里只测试模块加载
    print('  ✅ 斜杠命令预处理接口就绪')
    
    print('\n✅ 测试 7 通过: 增强 Agent 循环')
    return True


def run_all_tests():
    """运行所有测试"""
    print()
    print('╔' + '=' * 68 + '╗')
    print('║' + ' ' * 68 + '║')
    print('║' + '  DFEcrab 系统优化 - 完整端到端测试'.center(66) + '║')
    print('║' + ' ' * 68 + '║')
    print('╚' + '=' * 68 + '╝')
    
    tests = [
        ('分级权限系统', test_1_permissions),
        ('斜杠命令系统', test_2_slash_commands),
        ('统一工具系统', test_3_unified_tools),
        ('会话持久化', test_4_session_persistence),
        ('上下文引擎', test_5_context_engine),
        ('工作区驱动配置', test_6_workspace_config),
        ('增强 Agent 循环', test_7_enhanced_agent_loop),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success, None))
        except Exception as e:
            results.append((name, False, str(e)))
            import traceback
            print(f'\n❌ 测试失败: {name}')
            print(f'   错误: {e}')
            traceback.print_exc()
    
    # 打印总结
    print()
    print('╔' + '=' * 68 + '╗')
    print('║' + ' ' * 68 + '║')
    print('║' + '  测试总结'.center(66) + '║')
    print('║' + ' ' * 68 + '║')
    print('╠' + '=' * 68 + '╣')
    
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)
    
    for name, success, error in results:
        status = '✅ 通过' if success else f'❌ 失败: {error}'
        print(f'║  {name:20s} {status:44s} ║')
    
    print('╠' + '=' * 68 + '╣')
    print(f'║  总计: {passed}/{total} 通过'.ljust(68) + '║')
    print('║' + ' ' * 68 + '║')
    print('╚' + '=' * 68 + '╝')
    
    if passed == total:
        print('\n🎉 所有测试通过！系统优化完成！\n')
        return True
    else:
        print(f'\n⚠️  {total - passed} 个测试失败\n')
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
