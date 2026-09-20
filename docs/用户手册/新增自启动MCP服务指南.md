# 新增一个自启动的本地 MCP 服务 —— 操作指南

> **适用对象**：DFEcrab 系统的开发同学
> **适用场景**：要接入一个"自己写代码、自己监听端口"的本地 MCP 服务，并希望它随项目启动脚本 `dfecrab` 一起自动拉起
> **参考版本**：DFEcrab 4.0.0-grpc

---

## 0. 先搞清楚三个概念

| 概念 | 说明 |
|------|------|
| **MCP 服务** | 对外提供工具（Tool）的服务。DFEcrab 是 MCP 的**客户端**，通过 `baseUrl` 连接它 |
| **本地 MCP 服务** | 一个自己写、自己起进程、监听本地端口（如 `127.0.0.1:8602`）的服务 |
| **远程 MCP 服务** | 第三方托管的公网服务（如 `kdocs`、`bing_cn`），不需要本地起进程 |

本指南只讲**本地自启动 MCP 服务**。接入要做三件事：**① 写脚本 → ② 注册配置 → ③ 给智能体开权限**。其中②可用两种方式：**改配置文件** 或 **调用 HTTP 接口**。

---

## 1. 先认识 MCP 服务管理页面

浏览器打开（服务器上已运行）：

```
http://172.20.42.247:6789/mcp-admin
```

![MCP 服务管理页面](images/mcp_admin.png)

> ⚠️ **图片占位**：请把 MCP 管理页的截图保存为 `docs/用户手册/images/mcp_admin.png`（当前为占位，待补充截图）。

页面上能做的事：

- **切换智能体**（右上角下拉）：查看/修改不同 agent 启用的 MCP 服务
- **勾选服务**：勾上 = 该 agent 才能用这个服务的工具（对齐成熟平台"勾选即启用"语义）
- **全启 / 全停用**：批量开关某个服务的工具注入
- **同步工具**：把服务的最新工具列表拉到本地缓存（等价于重启后自动 `sync_tools`）
- **工具收纳**：可选，按 `mcp_tools_whitelist` 进一步收窄工具粒度

> 关键语义：即使服务在 `config/mcporter.json` 里配好了，也**必须**在某个 agent 上勾选，那个 agent 才会真正使用它的工具。

---

## 2. 三步接入一个本地 MCP 服务

### 步骤 1：写服务脚本（新建文件）

在 `mcp_servers/` 目录下新建脚本，参考已有 `mcp_demo.py`：

```python
# mcp_servers/weather.py  （文件名 = 服务名，见步骤 2 的"命名约定"）
from datetime import datetime

from fastmcp import FastMCP

mcp = FastMCP(name="weather")

@mcp.tool
def get_weather(city: str) -> str:
    """查询指定城市当前天气"""
    return f"{city} 今天晴，25℃，数据来自本地天气 MCP 服务，时间 {datetime.now()}"

if __name__ == "__main__":
    # 必须是 streamable-http（DFEcrab 客户端唯一支持的传输），不能改成 sse/stdio
    # 端口从 8602 起，避开已用的 8600/8601
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8602)
```

**注意事项**
- 传输类型必须是 `streamable-http`
- 端口不要和其他服务冲突（当前 8600/8601 已被占用）
- **服务名必须小写字母开头**：系统会校验 `^[a-z][a-z0-9_-]*$`（只允许小写字母、数字、下划线、连字符，**不能用大写字母、中文、空格**）。建议用**纯英文短名**（如 `weather`、`notion`），不要带 `mcp_` 前缀，避免文件名与 `mcporter.json` 的 name 对不上

**首次需要安装依赖**（只需一次）：
```bash
venv/bin/pip install fastmcp
```

---

### 步骤 2：注册配置（二选一）

#### 方式一：改 `config/mcporter.json`

在文件顶部的 `mcpServers` 对象里加一条记录：

```json
{
  "mcpServers": {
    "weather": {
      "baseUrl": "http://127.0.0.1:8602/mcp",
      "transport": "streamable_http",
      "headers": {},
      "tool_cache": [],
      "enabled": true
    }
  }
}
```

**字段说明**

| 字段 | 说明 |
|------|------|
| `weather`（键） | 服务唯一标识，**必须等于步骤 1 的脚本文件名**（`weather` ↔ `mcp_servers/weather.py`） |
| `baseUrl` | 本地服务端点，格式 `http://127.0.0.1:<端口>/mcp`；`baseUrl` 以 `127.0.0.1`/`localhost` 开头的服务，`dfecrab` 会在启动时自动拉起 |
| `transport` | 固定 `streamable_http` |
| `headers` | 需要鉴权时填，本地服务一般留 `{}` |
| `tool_cache` | 留 `[]` 即可，系统启动时会自动同步填充 |
| `enabled` | `true`（启用）/ `false`（停用） |

> ⚠️ **命名约定（最关键）**：`mcporter.json` 的**键名 = 脚本文件名**。
> ```
> mcporter.json:  "weather": { "baseUrl": "http://127.0.0.1:8602/mcp", ... }
>                          └──→  dfecrab 启动时去找  mcp_servers/weather.py
> ```
> 如果对不上，`dfecrab start` 会打印 `⚠️ MCP[xxx] 脚本缺失` 并跳过该服务。

#### 方式二：用 HTTP 接口直接添加

不手动改 `mcporter.json`，直接调管理接口（会自动写盘 + 自动同步工具）：

```bash
curl -X POST http://127.0.0.1:6789/api/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "weather",
    "url": "http://127.0.0.1:8602/mcp",
    "transport": "streamable_http",
    "headers": {},
    "enabled": true,
    "auto_sync": true
  }'
```

**body 字段**：`name`（必填，小写开头）、`url`（必填，即 `baseUrl`）、`transport`（默认 `streamable_http`）、`headers`、`enabled`（默认 `true`）、`auto_sync`（默认 `true`，是否自动同步工具列表）。

> ⚠️ **重要提醒**：接口只会把服务**注册进 `mcporter.json`**，它**不会**替你创建 `mcp_servers/weather.py` 脚本！所以方式二之前，步骤 1 的脚本仍然要你自己写好、且文件名 = `name`。否则注册成功后，`dfecrab start` 依旧会报"脚本缺失"而无法自启动。

---

### 步骤 3：给智能体开权限（二选一）

#### 方式 A：在管理页面勾选（推荐）
1. 打开 `http://172.20.42.247:6789/mcp-admin`
2. 右上角选择要开放的智能体
3. 找到新服务 `weather`，**勾选**它
4. 点"同步工具"，再点页面底部"保存"

#### 方式 B：直接改 `agents/<智能体>/tools.json`
给对应智能体（比如新建的 `agents/my_agent/tools.json`）的 `enabled_mcp_servers` 数组加上服务名：

```json
{
  "enabled_mcp_servers": ["weather"],
  "enabled_skills": []
}
```

> ⚠️ `enabled_mcp_servers` 是**主开关**，不加这个服务名，即使服务注册成功、工具同步成功，该 agent 也**不会**调用它的工具。

---

## 3. 启动 / 停止 / 查看状态

改完 `mcporter.json` 后，**重启主服务**（`registry.py` 会在启动时自动对健康服务 `sync_tools` 并把工具注册给勾选的 agent）。

```bash
./dfecrab start     # 本地 MCP 服务：未运行则自动拉起，已运行则检测端口；不阻塞 Gateway
./dfecrab status    # 会额外显示本地 MCP 的运行状态，如：🔌 MCP[weather]: ✅ 运行中 (端口 8602)
./dfecrab stop      # 只停主服务；MCP 为独立服务，不会被杀掉
```

**MCP 是独立服务**，与知识库一样：
- `dfecrab stop` **不会**停止 MCP 服务
- 如需手动停止某个本地 MCP 服务：
```bash
pkill -f mcp_servers/weather.py
```
- 手动启动（不依赖 `dfecrab` 时）：
```bash
nohup venv/bin/python mcp_servers/weather.py > logs/mcp_weather.log 2>&1 &
```


## 4. 接口速查（MCP HTTP API）

以下接口都由 Gateway 提供，**端口 = 管理页端口（6789）**，无需额外鉴权。方便你写脚本批量管理服务。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/mcp-admin` | MCP 管理页（HTML） |
| GET | `/api/mcp/servers?check=true` | 服务列表（`check=true` 会并发 ping 存活/延迟） |
| POST | `/api/mcp/servers` | **新增服务**（body: `name`,`url`,`transport?`,`headers?`,`enabled?`,`auto_sync?`） |
| POST | `/api/mcp/servers/{name}/toggle` | 启停服务（body: `{"enabled": true/false}`） |
| POST | `/api/mcp/servers/{name}/sync` | 同步该服务的工具列表 |
| DELETE | `/api/mcp/servers/{name}` | 删除服务（联动清理各 agent 的悬空引用） |
| POST | `/api/mcp/servers/test` | 测试连通性，**不写盘**（body: `url`,`transport?`,`headers?`） |
| GET | `/api/agents/{agent_id}/mcp` | 查询某 agent 勾选的 MCP 服务 |
| POST | `/api/agents/{agent_id}/mcp` | 保存某 agent 的 MCP 勾选（body: `enabled_mcp_servers`,`mcp_tools_whitelist`） |

**常用示例**

新增服务并自动同步：
```bash
curl -X POST http://127.0.0.1:6789/api/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{"name":"weather","url":"http://127.0.0.1:8602/mcp","enabled":true,"auto_sync":true}'
```

测试服务连通性（不落盘，适合先验一下再添加）：
```bash
curl -X POST http://127.0.0.1:6789/api/mcp/servers/test \
  -H "Content-Type: application/json" \
  -d '{"url":"http://127.0.0.1:8602/mcp"}'
```

给智能体勾选服务：
```bash
curl -X POST http://127.0.0.1:6789/api/agents/my_agent/mcp \
  -H "Content-Type: application/json" \
  -d '{"enabled_mcp_servers":["weather"]}'
```

> 提示：`POST /api/mcp/servers/test` 适合"先测试、后添加"的流程；`POST /api/mcp/servers` 适合"直接添加 + 自动同步"。两者都不创建脚本文件，脚本仍需自己写。

---

## 6. 常见问题排查

| 现象 | 原因与处理 |
|------|-----------|
| `start` 打印 `⚠️ MCP[weather] 脚本缺失` | `mcporter.json` 的键名与 `mcp_servers/` 下脚本文件名不一致，改成一致即可 |
| `start` 打印 `⚠️ MCP[weather] 端口未监听` | 服务启动失败，看日志 `logs/mcp_weather.log`；多半是端口被占或 fastmcp 未安装 |
| 管理页已勾选，但对话里模型不用它的工具 | 改完配置后**未重启主服务**，或该服务不健康被自动降级；先 `./dfecrab restart` 再看 |
| 工具数量为 0 | 服务进程没起（健康检查不到）或没点"同步工具"；确认 `ps aux \| grep mcp_servers` 能看到进程 |
| 报 `transport 不支持` | 脚本里 `mcp.run` 的 transport 必须是 `streamable-http` |
| 用接口添加时报"name 只能包含小写字母..." | 服务名必须以**小写字母开头**，且只能是小写字母、数字、下划线、连字符 |

> 容错设计：本地 MCP 服务不健康时，系统会**自动降级跳过**，不会拖垮主服务启动。

---

## 7. 接入检查清单

- [ ] `mcp_servers/<服务名>.py` 已创建，`transport="streamable-http"`，端口不冲突
- [ ] 服务名**小写字母开头**（`^[a-z][a-z0-9_-]*$`）
- [ ] 服务已注册：改 `config/mcporter.json` 或用 `POST /api/mcp/servers` 添加，`enabled: true`，键名 = 脚本文件名
- [ ] `mcp-admin` 页面已给目标 agent 勾选该服务（或 `tools.json` 的 `enabled_mcp_servers` 已加）
- [ ] `./dfecrab restart` 后，`./dfecrab status` 能看到 `✅ 运行中`
- [ ] 发一条对话验证工具能被模型调用
