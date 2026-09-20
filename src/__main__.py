"""
DFEcrab v3 主入口
支持 TUI 模式、Server 模式（gRPC/plugin）和远程 TUI 模式
"""

import sys
import argparse
import subprocess
from pathlib import Path


def run_mcp_server():
    """运行 MCP Server 模式"""
    parser = argparse.ArgumentParser(description='MCP Server 管理')
    parser.add_argument('action', nargs='?', choices=['start', 'status'], default='status', help='操作')
    parser.add_argument('--transport', choices=['stdio', 'sse', 'streamable-http'], default='stdio', help='MCP transport')
    parser.add_argument('--host', default='127.0.0.1', help='监听地址（HTTP/SSE 模式有效）')
    parser.add_argument('--port', type=int, default=8000, help='监听端口（HTTP/SSE 模式有效）')
    parser.add_argument('--include-external-mcp', action='store_true', help='同时暴露已缓存的外部 MCP 工具')
    parser.add_argument('--exclude-tool', action='append', default=[], help='排除指定工具，可重复传入')
    args = parser.parse_args()

    from src.mcp import create_mcp_server

    server = create_mcp_server(
        host=args.host,
        port=args.port,
        include_external_mcp=args.include_external_mcp,
        exclude_tools=args.exclude_tool,
    )

    if args.action == 'status':
        tool_names = server.list_exposed_tool_names()
        print("MCP Server 状态:")
        print(f"  transport: {args.transport}")
        if args.transport != 'stdio':
            print(f"  endpoint: http://{args.host}:{args.port}")
        print(f"  exposed tools: {len(tool_names)}")
        if tool_names:
            preview = ", ".join(tool_names[:15])
            if len(tool_names) > 15:
                preview += ", ..."
            print(f"  tools: {preview}")
        return

    if args.action == 'start':
        print("正在启动 MCP Server...")
        if args.transport == 'stdio':
            print("  transport: stdio")
        else:
            print(f"  endpoint: http://{args.host}:{args.port}")
            print(f"  transport: {args.transport}")
        print(f"  exposed tools: {len(server.list_exposed_tool_names())}")
        server.run_transport(args.transport)


def run_gateway():
    """运行 Gateway Server 模式（默认使用 gRPC 版本，支持 WebSocket）"""
    import asyncio

    parser = argparse.ArgumentParser(description='Gateway 服务管理')
    parser.add_argument('action', nargs='?', choices=['start', 'stop', 'restart', 'status'], default='status', help='操作')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址')
    parser.add_argument('--port', type=int, default=6789, help='HTTP 监听端口')
    parser.add_argument('--ws-port', type=int, default=6790, help='WebSocket 监听端口')
    args = parser.parse_args()

    if args.action == 'status':
        try:
            from src.gateway.grpc_server import GatewayV2GRPC
            print("Gateway 模式: grpc")
            print(f"HTTP 监听: http://{args.host}:{args.port}")
            print(f"WebSocket 监听: ws://{args.host}:{args.ws_port}")
            print(f"状态: 请通过日志文件确认运行状态")
        except Exception as e:
            print(f"Gateway 状态查询失败: {e}")
        return

    if args.action == 'start':
        async def do_start():
            try:
                # gRPC 版本（支持 WebSocket）
                from src.gateway.grpc_server import GatewayV2GRPC
                from src.config.config_loader import config

                gw = GatewayV2GRPC(
                    host=args.host,
                    port=args.port,
                    ws_port=args.ws_port,
                    zk_hosts=config.zk_hosts
                )

                print("正在初始化 Gateway...")
                if not await gw.initialize():
                    print("❌ Gateway 初始化失败")
                    return
                print("Gateway 初始化成功，正在启动...")
                if not await gw.start():
                    print("❌ Gateway 启动失败")
                    return
                print("✅ Gateway 已启动")
                print(f"   HTTP: http://{args.host}:{args.port}")
                print(f"   WebSocket: ws://{args.host}:{args.ws_port}")
                print(f"\n按 Ctrl+C 停止")
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\n正在停止 Gateway...")
                await gw.stop()
                print("✅ Gateway 已停止")
            except Exception as e:
                print(f"❌ Gateway 运行错误: {e}")
                import traceback
                traceback.print_exc()

        asyncio.run(do_start())

    elif args.action == 'stop':
        print("请使用对应的启动脚本停止服务，或通过 kill 命令")
        print("  - gRPC 版本: scripts/start_gateway_grpc.py")

    elif args.action == 'restart':
        print("重启功能暂未实现，请先 stop 再 start")
        print("  start_gateway_grpc.py 管理: kill <PID> && python start_gateway_grpc.py")


def run_tui():
    """运行 TUI 模式（当前使用仓库内 Ink CLI）"""
    _run_node_tui()


def run_tui_remote(host: str, port: int):
    """运行远程 TUI 模式（连接到远程 Gateway）"""
    _run_node_tui(host=host, port=port)


def _run_node_tui(host: str = "localhost", port: int = 6789):
    tui_entry = Path(__file__).resolve().parent.parent / "tui" / "cli.js"
    if not tui_entry.exists():
        print("❌ TUI 入口不存在：tui/cli.js")
        sys.exit(1)

    try:
        subprocess.run(
            ["node", str(tui_entry), "--host", host, "--port", str(port)],
            check=True,
        )
    except FileNotFoundError:
        print("❌ 未找到 node，可先安装 Node.js 后再运行 tui")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 再见！")
        sys.exit(0)
    except subprocess.CalledProcessError as exc:
        print(f"❌ TUI 启动失败，退出码: {exc.returncode}")
        sys.exit(exc.returncode)


def main():
    """主入口函数"""
    import argparse
    parser = argparse.ArgumentParser(description='DFEcrab v3.0 - 智能体平台', add_help=False)
    parser.add_argument('command', nargs='?', choices=['gateway', 'tui', 'mcp-server'], help='命令')
    parser.add_argument('--host', default='localhost', help='Gateway 主机地址')
    parser.add_argument('--port', type=int, default=6789, help='Gateway 端口')
    parser.add_argument('--version', action='store_true', help='显示版本信息')
    parser.add_argument('--help', '-h', action='store_true', help='显示帮助')

    args, unknown = parser.parse_known_args()

    if args.help or not args.command:
        print("用法:")
        print("  dfecrab gateway start   # 启动 Gateway")
        print("  dfecrab gateway stop   # 停止 Gateway")
        print("  dfecrab gateway restart # 重启 Gateway")
        print("  dfecrab gateway status # 查看状态")
        print("  dfecrab tui           # 启动 TUI（连接到本地 Gateway）")
        print("  dfecrab tui --host 192.168.1.1 --port 6789  # 连接到远程 Gateway")
        print("  dfecrab mcp-server status # 查看 MCP Server 暴露的工具")
        print("  dfecrab mcp-server start --transport stdio # 启动 MCP Server")
        sys.exit(0)

    if args.version:
        print("DFEcrab v3.0.0 - 重构版")
        print("架构：微内核 + 服务化")
        print("支持：多 TUI 客户端连接同一个 Gateway")
        sys.exit(0)

    if args.command == 'gateway':
        # 修改 sys.argv 让 run_gateway 能正确解析子命令
        sys.argv = [sys.argv[0]] + unknown
        run_gateway()
    elif args.command == 'tui':
        run_tui_remote(args.host, args.port)
    elif args.command == 'mcp-server':
        sys.argv = [sys.argv[0]] + unknown
        run_mcp_server()


if __name__ == "__main__":
    main()
