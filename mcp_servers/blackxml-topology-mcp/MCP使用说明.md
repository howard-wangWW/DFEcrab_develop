# BLACKXML 拓扑 MCP 服务

这个 MCP 服务通过 stdio 提供 BLACKXML 拓扑查询、开关状态、停电影响和模拟操作能力。

## MCP 客户端配置

推荐使用下面这个配置。不要加 `cwd`，部分 MCP 客户端会因此校验失败。

```json
{
  "mcpServers": {
    "blackxml-topology": {
      "command": "F:\\Node\\node.exe",
      "args": [
        "C:\\Users\\60333\\Desktop\\blackxml-topology-mcp\\tools\\mcp-server.js"
      ]
    }
  }
}
```

如果客户端能正常识别 `node`，也可以写成：

```json
{
  "mcpServers": {
    "blackxml-topology": {
      "command": "node",
      "args": [
        "C:\\Users\\60333\\Desktop\\blackxml-topology-mcp\\tools\\mcp-server.js"
      ]
    }
  }
}
```

## Cherry Studio 使用注意

在 Cherry Studio 里，MCP Server 页面显示绿色只代表服务已连接；聊天时还需要启用工具调用。

1. `Settings` -> `MCP Servers` 中打开 `blackxml-topology`。
2. 点服务卡片右侧的工具/滑杆按钮，确认能看到 `search_feeders`、`get_feeder_topology` 等工具。
3. 回到聊天窗口，打开输入框附近的 MCP/工具按钮，选择或启用 `blackxml-topology`。
4. 使用支持 Function Calling / Tool Calling 的模型。
5. 提问时可以明确写：“请使用 MCP 工具查询，不要凭常识回答。”

可以先用这个问题测试：

```text
请使用 MCP 工具 get_mcp_status，告诉我 BLACKXML 数量、开关状态文件数量和用户数量。
```

再测试业务查询：

```text
请使用 MCP 工具 get_cabinet_topology，查询宝安站 F21 上黄金台4#公用三遥环网柜的相邻开关。
```

手工测试命令：

```powershell
npm run mcp
```

## 提供的工具

- `search_feeders`：搜索馈线，支持按变电站、F 编号、线路名或关键字检索 BLACKXML 索引。
- `get_feeder_topology`：查询某条馈线的拓扑结构，包含电源、图模文本、开关状态、联络点和统计信息。
- `get_cabinet_topology`：查询某个环网柜/开关柜在馈线中的局部拓扑，返回柜内开关状态和相邻设备。
- `search_devices`：搜索柜子、开关、变压器、线路设备。
- `assess_switch_operation`：评估单个开关分/合后的停电、复电、合环影响。
- `simulate_operations`：按顺序模拟多个开关操作。
- `query_impacted_users`：按变压器 ID 查询中压/低压用户。
- `get_grid_overview`：查询全配网馈线、XML、变电站、用户、开关状态和电流数据统计。
- `query_switch_user_loads`：按完整关联图模和多电源供电路径，查询开关下带的 ZY/DY 用户数。
- `query_switch_currents`：按实际电流升序/降序查询全网开关，支持安培阈值、变电站、馈线和柜名过滤，并返回三相电流。
- `get_mcp_status`：查看 XML、开关状态、用户索引加载状态。

馈线拓扑中的开关会显示实时状态和电流，例如 `602(合,I=91.7A)`；电流文件无该设备数据时不显示电流。

当 BLACKXML、用户列表、开关状态或电流文件更新后，重新构建全网开关用户数索引：

```powershell
F:\Node\node.exe tools\build-grid-analytics.js --min-users 2000 --quiet
F:\Node\node.exe tools\build-current-catalog.js --quiet
```

## 示例问法

- 查询宝安站 F21 的馈线拓扑。
- 黄金台 4# 公用三遥环网柜在宝安站 F21 上的相邻开关有哪些？
- 模拟断开黄金台 4# 公用三遥环网柜 602，影响哪些变压器和用户？
- 合上某个联络开关后是否合环，涉及哪几个电源？
- 配网一共有多少条唯一馈线？
- 哪些开关下带用户数超过 2000 户？请列出柜名、开关号、当前电流和 ZY/DY 用户数。
- 全网电流最大的 20 个开关有哪些？请按电流降序返回柜名、馈线和三相电流。
- 查询实际电流超过 200A 的开关。
