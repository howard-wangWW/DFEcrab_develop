"""
MCP 配置管理工具
使用 mcporter CLI 连接 MCP 服务器并调用工具
"""

import subprocess
import json
import os
from typing import Optional

from agentscope.service import ServiceResponse, ServiceExecStatus


def run_mcporter(args: list, timeout: int = 30) -> tuple:
    """
    运行 mcporter 命令

    Returns:
        (success, output)
    """
    try:
        result = subprocess.run(
            ["mcporter"] + args,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except FileNotFoundError:
        install_result = subprocess.run(
            ["npm", "install", "-g", "mcporter"],
            capture_output=True,
            text=True,
            timeout=120
        )
        if install_result.returncode == 0:
            result = subprocess.run(
                ["mcporter"] + args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout, result.stderr
        else:
            return False, "", "mcporter 安装失败，请手动运行: npm install -g mcporter"
    except subprocess.TimeoutExpired:
        return False, "", "命令执行超时"
    except Exception as e:
        return False, "", str(e)


def add_mcp_server(name: str, url: str, **kwargs) -> ServiceResponse:
    """
    添加 MCP 服务器配置

    Args:
        name: 服务器名称
        url: 服务器 URL
        token: Bearer Token (可选)

    Returns:
        添加结果
    """
    try:
        headers = []
        token = kwargs.get("token")
        if token:
            headers.append(f"Authorization=Bearer {token}")
        headers.append("accept=application/json, text/event-stream")

        cmd = ["config", "add", name, url, "--transport", "http"]
        for header in headers:
            cmd.extend(["--header", header])

        success, stdout, stderr = run_mcporter(cmd)

        if success:
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content=f"MCP 服务器已添加: {name}\nURL: {url}\n\n可以使用以下命令测试:\n  mcporter call {name}.search_files keyword=\"测试\" type=\"all\""
            )
        else:
            return ServiceResponse(
                status=ServiceExecStatus.ERROR,
                content=f"添加 MCP 服务器失败: {stderr or stdout}"
            )

    except Exception as e:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"添加 MCP 服务器失败: {str(e)}"
        )


def remove_mcp_server(name: str, **kwargs) -> ServiceResponse:
    """
    移除 MCP 服务器配置

    Args:
        name: 服务器名称

    Returns:
        移除结果
    """
    success, stdout, stderr = run_mcporter(["config", "remove", name])

    if success:
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=f"MCP 服务器已移除: {name}"
        )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"移除 MCP 服务器失败: {stderr or stdout}"
        )


def list_mcp_servers(**kwargs) -> ServiceResponse:
    """
    列出所有 MCP 服务器配置

    Returns:
        服务器列表
    """
    success, stdout, stderr = run_mcporter(["config", "list"])

    if success:
        content = stdout or "没有配置任何 MCP 服务器"

        content += "\n\n=== 可用的 MCP Skills ==="
        content += "\n这些 skill 需要通过 mcporter 调用（无需 execute.py）:\n"

        from pathlib import Path
        import os
        skills_dir = Path(os.getcwd()) / "skills"
        if not skills_dir.exists():
            skills_dir = Path(__file__).parent.parent.parent / "skills"

        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir() and not skill_dir.name.startswith('.'):
                execute_file = skill_dir / "execute.py"
                skill_md_file = skill_dir / "SKILL.md"
                if not execute_file.exists() and skill_md_file.exists():
                    content += f"  📦 {skill_dir.name}\n"

        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=content
        )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"列出 MCP 服务器失败: {stderr or stdout}"
        )


def test_mcp_server(name: str, **kwargs) -> ServiceResponse:
    """
    测试 MCP 服务器连接

    Args:
        name: 服务器名称
        tool: 测试工具名 (默认 search_files)
        keyword: 测试关键词

    Returns:
        测试结果
    """
    tool = kwargs.get("tool", "search_files")
    keyword = kwargs.get("keyword", "测试")

    success, stdout, stderr = run_mcporter([
        "call", f"{name}.{tool}",
        f"keyword={keyword}", "type=all", "page_size=3",
        "--output", "json"
    ])

    if success:
        try:
            result = json.loads(stdout)
            if result.get("code") == 0:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content=f"✅ MCP 服务器连接成功: {name}\n\n{json.dumps(result, ensure_ascii=False, indent=2)[:500]}"
                )
            else:
                return ServiceResponse(
                    status=ServiceExecStatus.ERROR,
                    content=f"❌ MCP 服务器返回错误: {result.get('message', result)}"
                )
        except json.JSONDecodeError:
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content=f"✅ MCP 服务器连接成功: {name}\n\n{stdout[:500]}"
            )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"❌ MCP 服务器连接失败: {stderr or stdout}"
        )


def call_mcp_tool(name: str, tool: str, **kwargs) -> ServiceResponse:
    """
    调用 MCP 工具

    Args:
        name: 服务器名称
        tool: 工具名称
        **kwargs: 工具参数

    Returns:
        调用结果
    """
    args = [f"{name}.{tool}"]
    for key, value in kwargs.items():
        if isinstance(value, str) and " " in value:
            args.append(f'{key}="{value}"')
        else:
            args.append(f"{key}={value}")

    success, stdout, stderr = run_mcporter(args + ["--output", "json"])

    if success:
        try:
            result = json.loads(stdout)
            if result.get("code") == 0:
                return ServiceResponse(
                    status=ServiceExecStatus.SUCCESS,
                    content=json.dumps(result, ensure_ascii=False, indent=2)
                )
            else:
                return ServiceResponse(
                    status=ServiceExecStatus.ERROR,
                    content=f"工具调用失败: {result.get('message', result)}"
                )
        except json.JSONDecodeError:
            return ServiceResponse(
                status=ServiceExecStatus.SUCCESS,
                content=stdout
            )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"工具调用失败: {stderr or stdout}"
        )


def execute(action: str, **kwargs) -> ServiceResponse:
    """
    主入口

    Args:
        action: 操作类型
            - add: 添加服务器
            - remove: 移除服务器
            - list: 列出服务器
            - test: 测试连接
            - call: 调用工具
        **kwargs: 操作参数

    Returns:
        操作结果
    """
    if action == "add":
        return add_mcp_server(
            kwargs.get("name", ""),
            kwargs.get("url", ""),
            token=kwargs.get("token")
        )
    elif action == "remove":
        return remove_mcp_server(kwargs.get("name", ""))
    elif action == "list":
        return list_mcp_servers()
    elif action == "test":
        return test_mcp_server(
            kwargs.get("name", ""),
            tool=kwargs.get("tool"),
            keyword=kwargs.get("keyword")
        )
    elif action == "call":
        return call_mcp_tool(
            kwargs.get("name", ""),
            kwargs.get("tool", ""),
            **{k: v for k, v in kwargs.items() if k not in ("name", "tool")}
        )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.ERROR,
            content=f"未知操作: {action}\n支持的操作: add, remove, list, test, call"
        )