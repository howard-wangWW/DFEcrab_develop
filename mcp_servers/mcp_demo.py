from fastmcp import FastMCP
import time

mcp = FastMCP("Demo Server")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers together"""
    return a + b

@mcp.tool()
def get_current_time() -> str:
    """Get current time"""
    return time.strftime("%Y-%m-%d %H:%M:%S")

@mcp.tool()
def echo(message: str) -> str:
    """Echo a message"""
    return f"Echo: {message}"

@mcp.tool()
def multiply(a: int, b: int) -> int:
    """Multiply two numbers"""
    return a * b

if __name__ == "__main__":
    import sys
    from pathlib import Path
    # 让脚本支持单独运行也能读取 config/gateway.yaml
    # config 是真正的 Python 包（src/config），需把 src 也加入 sys.path
    _root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_root / "src"))
    sys.path.insert(0, str(_root))
    from config.port_loader import mcp_port
    port = mcp_port("demo", default=8600)
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
