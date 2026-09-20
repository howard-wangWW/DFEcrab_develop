"""alert_judge 专属服务：MCP 启动 + 项目接入 + 研判链路适配

职责划分（本文件不含任何业务/研判逻辑）：
1. 启动 —— 以 alert_judge_tools 名义注册 src/alert_judge/tools.py 的 4 个查询工具，
   提供 Streamable HTTP MCP 服务（前端 mcp 参数路由 / MCP 服务管理页依赖此服务名）
2. 接入 —— sys.path 与端口配置（src/config/port_loader）
3. 适配 —— run()：调用标准 agent_caller2 的 sse_event_generator，
   把 SSE 文本事件还原成 dict 事件流，供 grpc_server 直接透传

研判逻辑本体在 src/alert_judge/ 三件套（config.py / tools.py / agent_caller2.py），
与现场标准文件一一对应；现场更新逻辑时直接覆盖该目录并补几行 import diff，
本文件无需改动。

注意：fastmcp 只在 main() 内按需引入，模块被 import（供 run() 使用）时
不依赖 fastmcp，避免 grpc_server 进程缺包即崩。

用法（247 服务器）：
    cd /home/e8900/DFEcrab
    nohup venv/bin/python mcp_servers/mcp_alert_judge.py > logs/mcp/mcp_alert_judge_tools.log 2>&1 &

默认监听 127.0.0.1:8601，端点 = http://127.0.0.1:8601/mcp
"""
import json
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Dict

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


# ══════════════════════════════════════════════════════════════════════════════
# 适配层：grpc_server 的 alert_judge 专属链路入口
# ══════════════════════════════════════════════════════════════════════════════

async def run(alert_json: str, correlation_id: str = "") -> AsyncGenerator[Dict[str, Any], None]:
    """调用标准 agent_caller2 的 SSE 事件流，解析回 dict 事件后逐条透传。

    grpc_server._alert_judge_direct_react 期望的事件结构与 sse_event_generator
    的 SSE data 载荷完全一致（type / id / data / timestamp / correlation_id），
    这里只做 文本→dict 的还原，不含任何业务逻辑。
    """
    from src.alert_judge.agent_caller2 import sse_event_generator

    async for sse_text in sse_event_generator(alert_json, correlation_id=correlation_id):
        for line in sse_text.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                yield json.loads(line[len("data: "):])
            except json.JSONDecodeError:
                continue


# ══════════════════════════════════════════════════════════════════════════════
# MCP 服务启动（仅 __main__ 使用，fastmcp 按需引入）
# ══════════════════════════════════════════════════════════════════════════════

def _build_mcp():
    """创建并注册 alert_judge_tools MCP 服务（工具实现来自标准三件套 tools.py）。"""
    from fastmcp import FastMCP

    from src.alert_judge.tools import (
        search_taizhang,
        search_diaodulog,
        search_caozuotickets,
        search_livework_ticket,
    )

    mcp = FastMCP(name="alert_judge_tools")
    for _fn in (search_taizhang, search_diaodulog, search_caozuotickets, search_livework_ticket):
        mcp.tool(_fn)
    return mcp


if __name__ == "__main__":
    from src.config.port_loader import mcp_port

    mcp = _build_mcp()
    # streamable-http 是 DFEcrab 客户端唯一支持的传输，不能改成 sse/stdio
    port = mcp_port("alert_judge_tools", default=8601)
    mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
