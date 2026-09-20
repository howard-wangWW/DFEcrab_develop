"""
BLACKXML Topology MCP 测试脚本
===============================

使用方法:
    1. 启动 MCP 服务 (HTTP 模式):
       cd blackxml-topology-mcp
       node tools/http-mcp-server.js

    2. 运行本脚本 (HTTP 模式，需要先启动 MCP):
       python test_mcp.py

    3. 或者直接 stdio 模式 (自动启动 MCP 子进程，不需要手动启动):
       python test_mcp.py --mode stdio

依赖:
    - Python 3.8+ (仅使用标准库，无需 pip install)
    - Node.js 22+ (用于运行 MCP 服务)
"""

import json
import sys
import os
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path


# ============================================================
# 配置区
# ============================================================

# MCP 服务地址 (HTTP 模式)
MCP_URL = "http://localhost:3100/mcp"

# MCP 目录 (stdio 模式下用于启动子进程)
MCP_DIR = Path(__file__).resolve().parent
MCP_SERVER_JS = MCP_DIR / "tools" / "mcp-server.js"

# 请求超时 (毫秒)
REQUEST_TIMEOUT = 120000


# ============================================================
# MCP 客户端
# ============================================================

class McpClient:
    """MCP 客户端，支持 HTTP 和 stdio 两种模式"""

    def __init__(self, mode="http", mcp_url=None, node_path="node"):
        self.mode = mode
        self.message_id = 0
        self.initialized = False

        if mode == "http":
            self.mcp_url = mcp_url or MCP_URL
        elif mode == "stdio":
            self._proc = subprocess.Popen(
                [node_path, str(MCP_SERVER_JS)],
                cwd=str(MCP_DIR),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )
        else:
            raise ValueError(f"未知模式: {mode}，可选: http, stdio")

    def close(self):
        """关闭 stdio 模式下的子进程"""
        if self.mode == "stdio" and hasattr(self, "_proc"):
            self._proc.terminate()
            self._proc.wait(timeout=5)

    def _next_id(self):
        self.message_id += 1
        return self.message_id

    def _send_http(self, payload):
        """通过 HTTP 发送 JSON-RPC 请求"""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.mcp_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT / 1000) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            return json.loads(body) if body else {"error": {"code": e.code, "message": str(e)}}
        except urllib.error.URLError as e:
            raise ConnectionError(f"无法连接 MCP 服务 {self.mcp_url}: {e.reason}")

    def _send_stdio(self, payload):
        """通过 stdio 发送 JSON-RPC 请求"""
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

        # 读取响应行
        while True:
            raw = self._proc.stdout.readline()
            if not raw:
                raise RuntimeError("MCP 子进程已退出")
            raw = raw.strip()
            if not raw:
                continue
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # 可能是日志行，跳过继续读
                continue

    def _send(self, payload):
        if self.mode == "http":
            return self._send_http(payload)
        else:
            return self._send_stdio(payload)

    def initialize(self):
        """初始化 MCP 会话"""
        resp = self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        self.initialized = True
        return resp.get("result", resp)

    def list_tools(self):
        """列出所有可用工具"""
        resp = self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        })
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name, arguments=None):
        """调用 MCP 工具"""
        if not self.initialized:
            self.initialize()

        resp = self._send({
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
            },
        })

        if "error" in resp:
            return {"error": resp["error"]}

        result = resp.get("result", {})
        # 解析 content 中的文本结果
        if "content" in result:
            for item in result["content"]:
                if item.get("type") == "text":
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, TypeError):
                        return item["text"]
        return result


# ============================================================
# 格式化输出
# ============================================================

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def subsection(title):
    print(f"\n--- {title} ---")


def print_status(client):
    """打印 MCP 服务状态"""
    section("MCP 服务状态")
    data = client.call_tool("get_mcp_status")
    if "error" in data:
        print(f"❌ 错误: {data['error']}")
        return data

    print(f"  服务名称: {data.get('serverInfo', {}).get('name', 'N/A')}")
    print(f"  版本: {data.get('serverInfo', {}).get('version', 'N/A')}")

    scope = data.get("scope", {})
    if isinstance(scope, dict):
        print(f"  数据范围: {scope.get('mode', 'N/A')}")

    switch_status = data.get("switchStatus", {})
    print(f"  开关状态文件: {switch_status.get('switchFiles', 'N/A')} 个")

    switch_current = data.get("switchCurrent", {})
    print(f"  电流数据点数: {switch_current.get('currentCount', 'N/A')}")

    users = data.get("users", {})
    print(f"  用户记录数: {users.get('totalUsers', 'N/A')}")

    tools = data.get("tools", [])
    print(f"  可用工具数: {len(tools)}")
    return data


def print_tools(client):
    """列出所有工具"""
    section("可用工具列表")
    tools = client.list_tools()
    for i, tool in enumerate(tools, 1):
        print(f"\n  [{i}] {tool['name']}")
        print(f"      {tool['description']}")
        schema = tool.get("inputSchema", {})
        props = schema.get("properties", {})
        if props:
            print(f"      参数:")
            for pname, pinfo in props.items():
                required = " *" if pname in schema.get("required", []) else ""
                desc = pinfo.get("description", "")
                print(f"        - {pname}{required}: {desc}")
    return tools


def test_search_feeders(client):
    """测试搜索馈线"""
    section("测试 1: 搜索馈线")
    data = client.call_tool("search_feeders", {
        "station": "宝安站",
        "limit": 5,
    })
    if "error" in data:
        print(f"❌ 错误: {data['error']}")
        return data

    print(f"  找到 {data.get('count', 0)} 条馈线:\n")
    for line in data.get("lines", []):
        print(f"  📍 {line.get('stationName', '')} F{line.get('feederNo', '')} {line.get('lineName', '')}")
        print(f"     文件: {line.get('file', '')}")
        print(f"     配电房: {line.get('substationCount', 0)}  连通节点: {line.get('connectivityNodeCount', 0)}")
    return data


def test_feeder_topology(client):
    """测试馈线拓扑查询"""
    section("测试 2: 查询馈线拓扑 (F21 宝润线)")
    data = client.call_tool("get_feeder_topology", {
        "station": "宝安站",
        "feeder": "F21",
        "format": "summary",
        "limit": 10,
    })
    if "error" in data:
        print(f"❌ 错误: {data['error']}")
        return data

    line = data.get("line", {})
    stats = data.get("stats", {})
    coverage = data.get("currentCoverage", {})

    print(f"  线路: {line.get('displayName', 'N/A')}")
    print(f"  XML文件: {line.get('file', 'N/A')}")
    print(f"  配电房数: {line.get('substationCount', 0)}")
    print(f"  连通节点数: {line.get('connectivityNodeCount', 0)}")

    subsection("电源点")
    for src in data.get("sources", []):
        print(f"  ⚡ {src.get('label', '')} (ID: {src.get('id', '')})")

    subsection("统计信息")
    print(f"  总设备数: {stats.get('equipment', 0)}")
    print(f"  开关数: {stats.get('switches', 0)}")
    print(f"  变压器数: {stats.get('transformers', 0)}")
    print(f"  匹配电流的开关: {coverage.get('matchedSwitches', 0)}")

    subsection("开关列表 (前10个)")
    for sw in data.get("switches", []):
        state = "合" if sw.get("closed") else "分"
        current = f", I={sw['current']['amp']}A" if sw.get("current") else ""
        energized = "带电" if sw.get("energized") else ("失电" if sw.get("energized") is False else "未知")
        tie = " [联络点]" if sw.get("tiePoint") else ""
        print(f"  🔘 {sw.get('name', '')} ({state}{current}) [{energized}]{tie}")
    return data


def test_switch_operation(client):
    """测试开关操作评估 (核心功能!)"""
    section("测试 3: 开关操作影响评估 (断开开关)")

    # 先找到一个具体的开关
    print("  先获取 F21 馈线上的开关列表...")
    topo = client.call_tool("get_feeder_topology", {
        "station": "宝安站",
        "feeder": "F21",
        "format": "summary",
        "limit": 5,
    })

    if "error" in topo:
        print(f"❌ 错误: {topo['error']}")
        return topo

    # 取第一个开关进行模拟
    switches = topo.get("switches", [])
    test_switch = None
    for sw in switches:
        if sw.get("closed") and not sw.get("tiePoint"):
            test_switch = sw
            break
    if not test_switch and switches:
        test_switch = switches[0]

    if not test_switch:
        print("  ⚠️  没有找到可用于测试的开关")
        return None

    switch_name = test_switch.get("name", "")
    print(f"\n  模拟操作: 断开 \"{switch_name}\"")
    print(f"  (原状态: {'合' if test_switch.get('closed') else '分'})")

    # 执行评估
    data = client.call_tool("assess_switch_operation", {
        "station": "宝安站",
        "feeder": "F21",
        "switch": switch_name,
        "action": "open",
        "includeUsers": True,
        "userLimit": 10,
        "limit": 5,
    })

    if "error" in data:
        print(f"❌ 错误: {data['error']}")
        return data

    subsection("操作结果")
    ops = data.get("operations", [])
    for op in ops:
        print(f"  开关: {op.get('switch', {}).get('name', 'N/A')}")
        print(f"  状态变化: {op.get('stateBefore', '')} → {op.get('stateAfter', '')}")

    subsection("影响统计")
    steps = data.get("steps", [])
    if steps:
        impact = steps[0].get("impact", {})
        counts = impact.get("counts", {})
        print(f"  ⚠️  失电设备: {counts.get('outagedEquipment', 0)}")
        print(f"  ⚠️  失电变压器: {counts.get('outagedTransformers', 0)}")
        print(f"  ✅ 复电设备: {counts.get('restoredEquipment', 0)}")
        print(f"  ✅ 复电变压器: {counts.get('restoredTransformers', 0)}")
        print(f"  ⚡ 合环设备: {counts.get('newlyLoopedEquipment', 0)}")
        print(f"  🔗 联络点: {counts.get('tiePoints', 0)}")

        subsection("失电设备/变压器")
        for t in impact.get("outagedTransformers", {}).get("items", []):
            print(f"  🔴 {t.get('name', '')}")

    impacted = data.get("impactedUsers", {})
    if impacted:
        outage_raw = impacted.get("outage", [])
        restored_raw = impacted.get("restored", [])
        # outage/restored 可能是 list 或 dict，统一转成 list
        outage_users = list(outage_raw.values()) if isinstance(outage_raw, dict) else list(outage_raw)
        restored_users = list(restored_raw.values()) if isinstance(restored_raw, dict) else list(restored_raw)
        if outage_users:
            subsection(f"失电用户 (前10个，共{len(outage_users)}个)")
            for u in outage_users[:10]:
                if isinstance(u, dict):
                    print(f"  👤 {u.get('consumerName', '')} ({u.get('consumerType', '')})")
                else:
                    print(f"  👤 {u}")
        if restored_users:
            subsection(f"复电用户 (前10个，共{len(restored_users)}个)")
            for u in restored_users[:10]:
                if isinstance(u, dict):
                    print(f"  ✅ {u.get('consumerName', '')} ({u.get('consumerType', '')})")
                else:
                    print(f"  ✅ {u}")

    return data


def test_switch_currents(client):
    """测试电流查询"""
    section("测试 4: 全网电流查询 (>50A)")
    data = client.call_tool("query_switch_currents", {
        "minAmp": 50,
        "sort": "desc",
        "limit": 10,
    })
    if "error" in data:
        print(f"❌ 错误: {data['error']}")
        return data

    print(f"  共找到 {data.get('count', 0)} 个电流超过 50A 的开关\n")
    for sw in data.get("switches", []):
        print(f"  💡 {sw.get('cabinet', 'N/A')} | {sw.get('feederName', 'N/A')} | {sw.get('currentDisplay', 'N/A')}")
    return data


def test_grid_overview(client):
    """测试全网概览"""
    section("测试 5: 全网概览")
    data = client.call_tool("get_grid_overview", {})
    if "error" in data:
        print(f"❌ 错误: {data['error']}")
        return data

    print(f"  馈线数: {data.get('feederCount', 0)}")
    print(f"  XML文件数: {data.get('xmlFileCount', 0)}")
    print(f"  变电站数: {data.get('stationCount', 0)}")
    print(f"  用户总数: {data.get('userCount', 0)}")

    status = data.get("switchStatus", {})
    print(f"  开关状态记录: {status.get('switchCount', 0)}")

    current = data.get("switchCurrent", {})
    print(f"  电流数据点数: {current.get('currentCount', 0)}")

    analytics = data.get("switchUserLoadAnalytics", {})
    if analytics:
        print(f"  负荷分析已构建: {'是' if analytics.get('built') else '否'}")
    return data


def run_all_tests(client):
    """运行所有测试"""
    print("╔══════════════════════════════════════════════╗")
    print("║  BLACKXML Topology MCP 测试套件               ║")
    print("╚══════════════════════════════════════════════╝")

    print_status(client)
    print_tools(client)
    test_search_feeders(client)
    test_feeder_topology(client)
    test_switch_operation(client)
    test_switch_currents(client)
    test_grid_overview(client)

    section("✅ 所有测试完成!")
    print("\n  提示: 你可以修改脚本中的参数来测试不同的变电站、馈线和开关。")
    print("  常用参数示例:")
    print('    - {"station": "盐田站"}')
    print('    - {"station": "罗湖站", "feeder": "F14"}')
    print('    - {"station": "宝安站", "feeder": "F51", "switch": "开关名", "action": "open"}')


# ============================================================
# 入口
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="BLACKXML Topology MCP 测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # HTTP 模式 (先手动启动 MCP: node tools/http-mcp-server.js)
  python test_mcp.py

  # stdio 模式 (自动启动 MCP 子进程)
  python test_mcp.py --mode stdio

  # 指定 MCP 地址
  python test_mcp.py --url http://192.168.1.100:3100/mcp
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["http", "stdio"],
        default="stdio",
        help="连接模式: http (默认) 或 stdio",
    )
    parser.add_argument(
        "--url",
        default=None,
        help=f"HTTP 模式下的 MCP 地址 (默认: {MCP_URL})",
    )
    parser.add_argument(
        "--node",
        default="node",
        help="Node.js 可执行文件路径 (stdio 模式下使用)",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="仅列出所有工具，不运行测试",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="仅查看服务状态",
    )
    parser.add_argument(
        "--search",
        metavar="KEYWORD",
        help="搜索馈线",
    )
    parser.add_argument(
        "--topo",
        nargs=2,
        metavar=("STATION", "FEEDER"),
        help="查询拓扑 (例: --topo 宝安站 F21)",
    )
    parser.add_argument(
        "--assess",
        nargs=3,
        metavar=("STATION", "FEEDER", "SWITCH"),
        help="评估开关操作 (action 默认 open)",
    )
    parser.add_argument(
        "--current",
        type=float,
        metavar="AMP",
        help="查询电流超过指定值的开关",
    )

    args = parser.parse_args()

    # 创建客户端
    if args.mode == "stdio":
        print(f"正在以 stdio 模式启动 MCP 子进程...")
        client = McpClient(mode="stdio", node_path=args.node)
    else:
        url = args.url or MCP_URL
        print(f"正在连接 MCP 服务: {url}")
        try:
            client = McpClient(mode="http", mcp_url=url)
        except Exception as e:
            print(f"❌ 无法连接: {e}")
            print("\n请确保 MCP 服务已启动:")
            print("  cd blackxml-topology-mcp")
            print("  node tools/http-mcp-server.js")
            print("\n或使用 stdio 模式: python test_mcp.py --mode stdio")
            sys.exit(1)

    # 初始化
    try:
        init_result = client.initialize()
        print(f"✅ MCP 已连接: {init_result.get('serverInfo', {}).get('name', 'N/A')}")
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        client.close()
        sys.exit(1)

    try:
        if args.list_tools:
            print_tools(client)
        elif args.status:
            print_status(client)
        elif args.search:
            data = client.call_tool("search_feeders", {"query": args.search, "limit": 10})
            if "error" in data:
                print(f"❌ 错误: {data['error']}")
            else:
                print(f"找到 {data.get('count', 0)} 条馈线:")
                for line in data.get("lines", []):
                    print(f"  {line.get('stationName', '')} F{line.get('feederNo', '')} {line.get('lineName', '')}")
        elif args.topo:
            station, feeder = args.topo
            test_feeder_topology(client)
        elif args.assess:
            station, feeder, switch_name = args.assess
            data = client.call_tool("assess_switch_operation", {
                "station": station,
                "feeder": feeder,
                "switch": switch_name,
                "action": "open",
                "includeUsers": True,
            })
            if "error" in data:
                print(f"❌ 错误: {data['error']}")
            else:
                print(json.dumps(data, indent=2, ensure_ascii=False))
        elif args.current:
            data = client.call_tool("query_switch_currents", {
                "minAmp": args.current,
                "sort": "desc",
                "limit": 20,
            })
            if "error" in data:
                print(f"❌ 错误: {data['error']}")
            else:
                print(f"电流 > {args.current}A 的开关 (前20个):")
                for sw in data.get("switches", []):
                    print(f"  {sw.get('cabinet', 'N/A')} | {sw.get('feederName', 'N/A')} | {sw.get('currentDisplay', 'N/A')}")
        else:
            run_all_tests(client)
    finally:
        client.close()


if __name__ == "__main__":
    main()