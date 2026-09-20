"""
权限系统单元测试
"""

import pytest
from src.core.security import (
    AgentPermissions,
    PermissionLevel,
    PermissionError,
    ToolPermissionContext,
    is_destructive_command,
    check_command_safety,
    ensure_write_permission,
    ensure_shell_permission,
    get_permission_summary,
    parse_permissions_from_args,
)


class TestAgentPermissions:
    """测试 AgentPermissions 类"""
    
    def test_default_permissions(self):
        """测试默认权限（只读）"""
        perms = AgentPermissions()
        assert perms.allow_file_write is False
        assert perms.allow_shell_commands is False
        assert perms.allow_destructive_shell_commands is False
        assert perms.level == PermissionLevel.READ_ONLY
    
    def test_write_permission(self):
        """测试写入权限"""
        perms = AgentPermissions(allow_file_write=True)
        assert perms.level == PermissionLevel.WRITE
    
    def test_shell_permission(self):
        """测试 Shell 权限"""
        perms = AgentPermissions(allow_shell_commands=True)
        assert perms.level == PermissionLevel.SHELL
    
    def test_unsafe_permission(self):
        """测试 Unsafe 权限"""
        perms = AgentPermissions(allow_destructive_shell_commands=True)
        assert perms.level == PermissionLevel.UNSAFE
    
    def test_from_flags(self):
        """测试从标志创建权限"""
        perms = AgentPermissions.from_flags(allow_write=True, allow_shell=True)
        assert perms.allow_file_write is True
        assert perms.allow_shell_commands is True
        assert perms.level == PermissionLevel.SHELL
    
    def test_to_dict(self):
        """测试转换为字典"""
        perms = AgentPermissions(allow_file_write=True)
        d = perms.to_dict()
        assert d['allow_file_write'] is True
        assert d['level'] == PermissionLevel.WRITE.value
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            'allow_file_write': True,
            'allow_shell_commands': False,
        }
        perms = AgentPermissions.from_dict(data)
        assert perms.allow_file_write is True
        assert perms.allow_shell_commands is False
    
    def test_get_blocked_tools(self):
        """测试获取被阻止的工具列表"""
        perms = AgentPermissions()
        blocked = perms.get_blocked_tools()
        assert 'write_file' in blocked
        assert 'bash' in blocked
    
    def test_get_blocked_tools_with_write(self):
        """测试有写入权限时被阻止的工具"""
        perms = AgentPermissions(allow_file_write=True)
        blocked = perms.get_blocked_tools()
        assert 'write_file' not in blocked
        assert 'bash' in blocked
    
    def test_get_permission_hint_readonly(self):
        """测试只读模式的权限提示"""
        perms = AgentPermissions()
        hint = perms.get_permission_hint()
        assert "文件写入被禁用" in hint
        assert "Shell 命令执行被禁用" in hint
    
    def test_get_permission_hint_full(self):
        """测试完整权限的提示"""
        perms = AgentPermissions(
            allow_file_write=True,
            allow_shell_commands=True,
            allow_destructive_shell_commands=True
        )
        hint = perms.get_permission_hint()
        assert "完整权限已启用" in hint


class TestDestructiveCommandDetection:
    """测试破坏性命令检测"""
    
    def test_safe_commands(self):
        """测试安全命令"""
        safe_commands = [
            "ls -la",
            "pwd",
            "cat file.txt",
            "grep 'pattern' file.py",
            "echo 'hello'",
        ]
        for cmd in safe_commands:
            assert not is_destructive_command(cmd), f"命令应该是安全的: {cmd}"
    
    def test_rm_command(self):
        """测试 rm 命令"""
        assert is_destructive_command("rm -rf /tmp/test")
        assert is_destructive_command("rm file.txt")
        assert is_destructive_command("sudo rm -rf /")
    
    def test_mv_command(self):
        """测试 mv 命令"""
        assert is_destructive_command("mv file.txt /tmp/")
        assert is_destructive_command("mv old new")
    
    def test_dd_command(self):
        """测试 dd 命令"""
        assert is_destructive_command("dd if=/dev/zero of=/dev/sda")
        assert is_destructive_command("sudo dd if=image.iso of=/dev/sdb")
    
    def test_shutdown_command(self):
        """测试关机命令"""
        assert is_destructive_command("shutdown now")
        assert is_destructive_command("sudo shutdown -r now")
    
    def test_git_reset(self):
        """测试 Git 重置命令"""
        assert is_destructive_command("git reset --hard HEAD")
        assert is_destructive_command("git clean -fd")
    
    def test_chmod_777(self):
        """测试 chmod 777 命令"""
        assert is_destructive_command("chmod -R 777 /tmp")
    
    def test_chained_commands(self):
        """测试链式命令"""
        assert is_destructive_command("ls && rm -rf /tmp/test")
        assert is_destructive_command("echo 'done'; rm file.txt")


class TestCommandSafetyCheck:
    """测试命令安全检查"""
    
    def test_no_shell_permission(self):
        """测试无 Shell 权限"""
        perms = AgentPermissions()
        is_safe, reason = check_command_safety("ls", perms)
        assert not is_safe
        assert "Shell 命令执行权限未启用" in reason
    
    def test_safe_command_with_shell_permission(self):
        """测试有 Shell 权限的安全命令"""
        perms = AgentPermissions(allow_shell_commands=True)
        is_safe, reason = check_command_safety("ls -la", perms)
        assert is_safe
        assert "安全检查通过" in reason
    
    def test_destructive_command_without_unsafe(self):
        """测试无 Unsafe 权限的破坏性命令"""
        perms = AgentPermissions(allow_shell_commands=True)
        is_safe, reason = check_command_safety("rm -rf /tmp", perms)
        assert not is_safe
        assert "检测到破坏性命令" in reason
    
    def test_destructive_command_with_unsafe(self):
        """测试有 Unsafe 权限的破坏性命令"""
        perms = AgentPermissions(
            allow_shell_commands=True,
            allow_destructive_shell_commands=True
        )
        is_safe, reason = check_command_safety("rm -rf /tmp", perms)
        assert is_safe
        assert "Unsafe 模式已启用" in reason


class TestPermissionEnforcement:
    """测试权限强制执行"""
    
    def test_ensure_write_permission_success(self):
        """测试确保写入权限 - 成功"""
        perms = AgentPermissions(allow_file_write=True)
        ensure_write_permission(perms)  # 不应抛出异常
    
    def test_ensure_write_permission_failure(self):
        """测试确保写入权限 - 失败"""
        perms = AgentPermissions()
        with pytest.raises(PermissionError) as exc_info:
            ensure_write_permission(perms)
        assert "文件写入权限未启用" in str(exc_info.value)
        assert exc_info.value.required_level == PermissionLevel.WRITE
    
    def test_ensure_shell_permission_success(self):
        """测试确保 Shell 权限 - 成功"""
        perms = AgentPermissions(allow_shell_commands=True)
        ensure_shell_permission(perms, "ls")  # 不应抛出异常
    
    def test_ensure_shell_permission_no_permission(self):
        """测试确保 Shell 权限 - 无权限"""
        perms = AgentPermissions()
        with pytest.raises(PermissionError) as exc_info:
            ensure_shell_permission(perms, "ls")
        assert "Shell 执行权限未启用" in str(exc_info.value)
        assert exc_info.value.required_level == PermissionLevel.SHELL
    
    def test_ensure_shell_permission_destructive(self):
        """测试确保 Shell 权限 - 破坏性命令"""
        perms = AgentPermissions(allow_shell_commands=True)
        with pytest.raises(PermissionError) as exc_info:
            ensure_shell_permission(perms, "rm -rf /")
        assert "检测到破坏性命令" in str(exc_info.value)


class TestToolPermissionContext:
    """测试工具权限上下文"""
    
    def test_blocks_by_name(self):
        """测试按名称阻止"""
        ctx = ToolPermissionContext.from_iterables(deny_names=['bash', 'rm'])
        assert ctx.blocks('bash')
        assert ctx.blocks('rm')
        assert not ctx.blocks('ls')
    
    def test_blocks_by_prefix(self):
        """测试按前缀阻止"""
        ctx = ToolPermissionContext.from_iterables(deny_prefixes=['dangerous_'])
        assert ctx.blocks('dangerous_operation')
        assert ctx.blocks('DANGEROUS_test')  # 不区分大小写
        assert not ctx.blocks('safe_operation')
    
    def test_case_insensitive(self):
        """测试不区分大小写"""
        ctx = ToolPermissionContext.from_iterables(deny_names=['Bash'])
        assert ctx.blocks('bash')
        assert ctx.blocks('BASH')


class TestPermissionSummary:
    """测试权限摘要"""
    
    def test_readonly_summary(self):
        """测试只读权限摘要"""
        perms = AgentPermissions()
        summary = get_permission_summary(perms)
        assert "read_only" in summary
        assert "❌" in summary
    
    def test_full_permission_summary(self):
        """测试完整权限摘要"""
        perms = AgentPermissions(
            allow_file_write=True,
            allow_shell_commands=True,
            allow_destructive_shell_commands=True
        )
        summary = get_permission_summary(perms)
        assert "unsafe" in summary
        assert "✅" in summary


class TestParsePermissionsFromArgs:
    """测试从参数解析权限"""
    
    def test_no_flags(self):
        """测试无标志"""
        args = {}
        perms = parse_permissions_from_args(args)
        assert perms.level == PermissionLevel.READ_ONLY
    
    def test_allow_write(self):
        """测试允许写入"""
        args = {'allow_write': True}
        perms = parse_permissions_from_args(args)
        assert perms.allow_file_write is True
    
    def test_allow_shell(self):
        """测试允许 Shell"""
        args = {'allow_shell': True}
        perms = parse_permissions_from_args(args)
        assert perms.allow_shell_commands is True
    
    def test_unsafe(self):
        """测试 Unsafe"""
        args = {'unsafe': True}
        perms = parse_permissions_from_args(args)
        assert perms.allow_destructive_shell_commands is True
    
    def test_all_flags(self):
        """测试所有标志"""
        args = {'allow_write': True, 'allow_shell': True, 'unsafe': True}
        perms = parse_permissions_from_args(args)
        assert perms.level == PermissionLevel.UNSAFE


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
