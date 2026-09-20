"""
BLACKXML Topology MCP — Streamable HTTP 模式测试脚本
=====================================================

模拟小螃蟹平台通过 Streamable HTTP 协议调用 MCP 的完整流程：
  1. POST /mcp {initialize}    → 握手
  2. POST /mcp {tools/list}    → 获取工具列表
  3. POST /mcp {tools/call}    → 调用工具，同步返回结果

协议说明:
  Streamable HTTP 就是普通的 POST 请求，请求体是 JSON-RPC，
  响应体也是 JSON-RPC（直接返回，不需要长连接）。

使用方法:
  先启动 MCP (HTTP 模式):
    cd blackxml-topology-mcp
    node tools/http-mcp-server.js

  然后运行本脚本:
    python test_http.py                           # 测试本机 localhost:3100
    python test_http.py --host 192.168.1.100      # 测试远程虚拟机
    python test_http.py --host 192.168.1.100 --port 3100

  也可以运行单个测试:
    python test_http.py --test status             # 只测状态
    python test_http.py --test search             # 只测搜索馈线
    python test_http.py --test topology           # 只测馈线拓扑
    python test_http.py --test assess             # 只测开关操作评估
    python test_http.py --test currents           # 只测电流查询

依赖:
  - Python 3.8+ (仅使用标准库，无需 pip install)
  - MCP 服务已启动并监听 (node tools/http-mcp-server.js)
"""

import json
import sys
import io
import time
import urllib.request
import urllib.error
import argparse

# 修复 Windows 终端中文编码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ============================================================
#  Streamable HTTP 客户端
# ============================================================
class StreamableHttpMcpClient:
    """
    通过 Streamable HTTP 协议与 MCP 通信。

    流程：
      每次请求都是一个独立的 POST，发到 /mcp
      请求体和响应体都是 JSON-RPC 2.0 格式

    比 SSE 更简单：不需要长连接，不需要线程，不需要 session。
    """

    def __init__(self, host, port, timeout=1200):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.url = f"http://{host}:{port}/mcp"
        self._rpc_seq = 1

    def call(self, method, params=None, read_timeout=None):
        """
        发送 JSON-RPC 请求并等待响应。

        参数:
          method: "initialize" / "tools/list" / "tools/call"
          params: 请求参数字典
          read_timeout: 读取超时（秒），默认使用构造器的 timeout

        返回:
          响应的 result 字段（字典），失败返回 None
        """
        req_id = f"http-{self._rpc_seq}-{int(time.time() % 1000000)}"
        self._rpc_seq += 1

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        data = json.dumps(payload).encode("utf-8")

        try:
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(data)),
                    "Accept": "application/json, text/event-stream"
                },
                method="POST"
            )
            timeout = read_timeout if read_timeout else self.timeout
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

                # Streamable HTTP 可能返回多条 JSON-RPC 消息（逐行）
                # 只取带 result 或 error 的那条
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "result" in msg:
                        return msg["result"]
                    if "error" in msg:
                        print(f"  [MCP错误] {msg['error']}")
                        return None

                # 如果不是多行，尝试直接解析整个响应
                try:
                    msg = json.loads(raw)
                    if "result" in msg:
                        return msg["result"]
                    if "error" in msg:
                        print(f"  [MCP错误] {msg['error']}")
                        return None
                except json.JSONDecodeError:
                    pass

                return None

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            print(f"  [HTTP错误] {e.status} {e.reason}: {err_body[:200]}")
            return None
        except Exception as e:
            print(f"  [错误] 请求失败: {e}")
            return None

    def initialize(self):
        """握手"""
        return self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "streamable-http-test-client", "version": "1.0.0"}
        })

    def list_tools(self):
        """获取工具列表"""
        return self.call("tools/list", {})

    def call_tool(self, name, arguments, read_timeout=600):
        """调用工具"""
        return self.call("tools/call", {"name": name, "arguments": arguments},
                         read_timeout=read_timeout)


# ============================================================
#  提取结构化内容
# ============================================================
def extract_content(result):
    """从 MCP 返回的 result 中提取结构化内容"""
    if not result:
        return None
    if isinstance(result, dict):
        if "structuredContent" in result:
            return result["structuredContent"]
        if "content" in result:
            content = result["content"]
            if isinstance(content, list) and content:
                text = content[0].get("text", "")
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
    return result


# ============================================================
#  测试用例
# ============================================================
def test_status(client):
    """测试 1: 查看 MCP 状态"""
    print("\n" + "=" * 60)
    print("测试 1: get_mcp_status — 查看服务状态")
    print("=" * 60)

    result = client.call_tool("get_mcp_status", {})
    data = extract_content(result)

    if data:
        scope = data.get("scope", {})
        print(f"  数据模式:          {scope.get('mode', '?')}")
        print(f"  馈线索引数:        {data.get('lineCount', '?')}")
        print(f"  索引生成时间:      {str(data.get('indexGeneratedAt', '?'))[:19]}")

        sw_status = data.get("switchStatus", {})
        if isinstance(sw_status, dict):
            count_or_ver = sw_status.get('fileCount') or sw_status.get('count') or sw_status.get('version', '?')
            print(f"  开关状态:          {count_or_ver}")

        sw_current = data.get("switchCurrent", {}) or data.get("switchCurrentCatalog", {})
        if isinstance(sw_current, dict):
            fc = sw_current.get('fileCount') or sw_current.get('count') or sw_current.get('catalogCount') or '?'
            cc = sw_current.get('count') or sw_current.get('catalogCount') or sw_current.get('entryCount') or '?'
            print(f"  开关电流:          {fc} 个文件, {cc} 条记录")

        users = data.get("users", {})
        if isinstance(users, dict):
            total = users.get("totalUsers", users.get("total", 0))
            print(f"  总用户数:          {total:,}")

        tools = data.get("tools", [])
        print(f"  工具数量:          {len(tools)}")
        return True
    else:
        print("  [失败] 未获取到状态")
        return False


def test_search_feeders(client):
    """测试 2: 搜索馈线"""
    print("\n" + "=" * 60)
    print("测试 2: search_feeders — 搜索宝安站的馈线")
    print("=" * 60)

    result = client.call_tool("search_feeders", {"station": "宝安站", "limit": 5})
    data = extract_content(result)

    if data and "lines" in data:
        lines = data["lines"]
        print(f"  搜索到 {data.get('count', len(lines))} 条馈线:")
        for i, line in enumerate(lines, 1):
            print(f"    {i}. {line.get('displayName', '?')}")
            print(f"       变电站: {line.get('stationName', '?')}, "
                  f"线路: {line.get('lineName', '?')}, "
                  f"F编号: {line.get('feederNo', '?')}")
        return True
    else:
        print(f"  [失败] 返回: {data}")
        return False


def test_feeder_topology(client):
    """测试 3: 查询馈线拓扑"""
    print("\n" + "=" * 60)
    print("测试 3: get_feeder_topology — 查询宝安站F21宝润线拓扑")
    print("=" * 60)

    result = client.call_tool("get_feeder_topology", {
        "station": "宝安站",
        "feeder": "F21",
        "format": "summary"
    })
    data = extract_content(result)

    if data:
        stats = data.get("stats", {})
        energized = data.get("energized", {})
        line = data.get("line", {})
        print(f"  馈线: {line.get('displayName', '?')}")
        print(f"  变电站: {line.get('stationName', '?')}")
        print(f"  设备总数:       {stats.get('equipment', '?')}")
        print(f"  开关数:         {stats.get('switches', '?')}")
        print(f"  变压器数:       {stats.get('transformers', '?')}")
        print(f"  有电流数据的开关: {stats.get('liveSwitchCurrent', '?')}")
        print(f"  带电设备数:     {energized.get('equipment', '?')}")
        print(f"  联络点数:       {energized.get('tiePoints', '?')}")
        print(f"  合环设备数:     {energized.get('loopedEquipment', '?')}")
        return True
    else:
        print(f"  [失败] 返回: {data}")
        return False


def test_assess_switch(client):
    """测试 4: 评估开关操作（核心功能）"""
    print("\n" + "=" * 60)
    print("测试 4: assess_switch_operation — 模拟断开804开关")
    print("=" * 60)

    result = client.call_tool("assess_switch_operation", {
        "station": "宝安站",
        "feeder": "F21",
        "switch": "804",
        "action": "open"
    })
    data = extract_content(result)

    if data:
        line = data.get("line", {})
        operations = data.get("operations", [])
        final_impact = data.get("finalImpact", {})
        impacted_users = data.get("impactedUsers", {})

        print(f"  馈线: {line.get('displayName', '?')}")

        if operations:
            op = operations[0]
            print(f"  操作: 断开开关 {op.get('switchName', '?')} (ID: {op.get('switchId', '?')})")

        counts = final_impact.get("counts", {})
        print(f"\n  【停电影响】")
        print(f"    失电设备数:     {counts.get('outagedEquipment', 0)}")
        print(f"    复电设备数:     {counts.get('restoredEquipment', 0)}")
        print(f"    失电变压器数:   {counts.get('outagedTransformers', 0)}")

        outaged_trans = final_impact.get("outagedTransformers", {})
        if isinstance(outaged_trans, dict):
            trans_items = outaged_trans.get("items", [])
            if trans_items:
                print(f"    失电变压器:")
                for t in trans_items[:5]:
                    if isinstance(t, dict):
                        print(f"      • {t.get('name', '?')} (柜: {t.get('cabinet', '?')})")

        print(f"\n  【用户影响】")
        if isinstance(impacted_users, dict):
            total = impacted_users.get("total", 0)
            counts_u = impacted_users.get("counts", {})
            print(f"    停电用户数:     {total}")
            if isinstance(counts_u, dict):
                print(f"      专变(ZY):    {counts_u.get('ZY', 0)}")
                print(f"      公变(DY):    {counts_u.get('DY', 0)}")
            users = impacted_users.get("users", [])
            if isinstance(users, dict):
                users = list(users.values())
            if users:
                print(f"    停电用户清单 (前5个):")
                for u in users[:5]:
                    if isinstance(u, dict):
                        print(f"      • {u.get('consumerName', '?')} "
                              f"({u.get('consumerType', '?')}) "
                              f"{u.get('consumerAddress', '')}")
                    else:
                        print(f"      • {u}")

        print(f"\n  【风险提示】")
        print(f"    联络点数:       {counts.get('tiePoints', 0)}")
        print(f"    新增合环:       {counts.get('newlyLoopedEquipment', 0)}")
        has_risk = counts.get('newlyLoopedEquipment', 0) > 0
        print(f"    是否有风险:     {'是' if has_risk else '否'}")
        return True
    else:
        print(f"  [失败] 返回: {data}")
        return False


def test_switch_currents(client):
    """测试 5: 查询电流超限开关"""
    print("\n" + "=" * 60)
    print("测试 5: query_switch_currents — 查询电流>500A的开关")
    print("=" * 60)

    result = client.call_tool("query_switch_currents", {
        "minCurrent": 500,
        "limit": 5,
        "sort": "desc"
    })
    data = extract_content(result)

    if data and "switches" in data:
        switches = data["switches"]
        print(f"  电流 > 500A 的开关共 {data.get('count', len(switches))} 个，前 {len(switches)} 个:")
        for i, sw in enumerate(switches, 1):
            print(f"    {i}. {sw.get('switchName', '?')} "
                  f"— {sw.get('station', '?')}{sw.get('feederName', '?')} "
                  f"— {sw.get('currentDisplay', '?')} "
                  f"(柜: {sw.get('cabinet', '?')})")
        return True
    else:
        print(f"  [失败] 返回: {data}")
        return False


# ============================================================
#  主程序
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="MCP Streamable HTTP 模式测试脚本")
    parser.add_argument("--host", default="localhost", help="MCP 服务器地址 (默认 localhost)")
    parser.add_argument("--port", type=int, default=3100, help="MCP 服务器端口 (默认 3100)")
    parser.add_argument("--test", choices=["status", "search", "topology", "assess", "currents", "all"],
                        default="all", help="运行哪个测试 (默认 all)")
    args = parser.parse_args()

    print("=" * 60)
    print("  BLACKXML Topology MCP — Streamable HTTP 模式测试")
    print("=" * 60)
    print(f"  服务器: {args.host}:{args.port}")
    print(f"  协议:   Streamable HTTP (POST /mcp, JSON-RPC)")
    print(f"  测试:   {args.test}")

    # ---------- 连接 MCP ----------
    print(f"\n[1] 测试连通性: GET http://{args.host}:{args.port}/health ...")
    client = StreamableHttpMcpClient(args.host, args.port)

    # 先做健康检查
    try:
        req = urllib.request.Request(f"http://{args.host}:{args.port}/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        print(f"  [成功] 服务在线: {info.get('service', '?')}")
    except Exception as e:
        print(f"  [失败] 无法连接 MCP 服务: {e}")
        print(f"  请确认:")
        print(f"    1. MCP 服务已启动 (node tools/http-mcp-server.js)")
        print(f"    2. 地址和端口正确: {args.host}:{args.port}")
        print(f"    3. 防火墙已开放 {args.port} 端口")
        sys.exit(1)

    # ---------- 握手 ----------
    print(f"\n[2] MCP 握手 (initialize) ...")
    init_result = client.initialize()
    if init_result:
        server_info = init_result.get("serverInfo", {})
        print(f"  [成功] 服务器: {server_info.get('name', '?')} v{server_info.get('version', '?')}")
        print(f"  协议版本: {init_result.get('protocolVersion', '?')}")
    else:
        print(f"  [失败] 握手失败")
        sys.exit(1)

    # ---------- 获取工具列表 ----------
    print(f"\n[3] 获取工具列表 (tools/list) ...")
    tools_result = client.list_tools()
    if tools_result and "tools" in tools_result:
        tools = tools_result["tools"]
        print(f"  [成功] 共 {len(tools)} 个工具:")
        for t in tools:
            print(f"    - {t['name']}")
    else:
        print(f"  [失败] 获取工具列表失败")
        sys.exit(1)

    # ---------- 运行测试 ----------
    results = {}

    if args.test in ("status", "all"):
        results["status"] = test_status(client)

    if args.test in ("search", "all"):
        results["search"] = test_search_feeders(client)

    if args.test in ("topology", "all"):
        results["topology"] = test_feeder_topology(client)

    if args.test in ("assess", "all"):
        results["assess"] = test_assess_switch(client)

    if args.test in ("currents", "all"):
        results["currents"] = test_switch_currents(client)

    # ---------- 汇总 ----------
    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    for name, passed in results.items():
        status = "通过" if passed else "失败"
        mark = "✅" if passed else "❌"
        print(f"  {mark} {name:15s} {status}")
    print("=" * 60)

    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    print(f"  总计: {passed_count}/{total_count} 通过")

    sys.exit(0 if passed_count == total_count else 1)


if __name__ == "__main__":
    main()
