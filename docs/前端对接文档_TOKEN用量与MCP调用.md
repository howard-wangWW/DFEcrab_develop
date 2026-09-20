# 前端对接文档 · TOKEN 用量统计 & MCP 调用

> 适用版本：DFEcrab v4.9.0-grpc
> 更新日期：2026-09-20
> 阅读对象：前端 / 大屏 / 管理后台开发
> 覆盖范围：Token 用量统计接口、MCP 调用统计接口、MCP 服务管理接口、对话中调用 MCP 的入参

---

## 1. 快速开始

### 1.1 服务地址

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| HTTP API | `http://<网关>:6789` | 全部统计/管理接口 |
| 可选前缀 | `http://<网关>:6789/dfecrab/...` | 与不带前缀**完全等价**（如 `/dfecrab/api/stats/tokens`） |
| MCP 管理页 | `http://<网关>:6789/mcp-admin` | 单页管理界面（可热改） |
| 对话（非流式） | `POST /api/v2/chat` | 统计数据的**来源**，对话落库后才产生用量 |
| 对话（流式） | `POST /api/v2/chat/stream` | SSE，事件协议见《前端对接文档_对话接口.md》 |

### 1.2 必带头

| 头 | 必填 | 说明 |
| --- | --- | --- |
| `X-User-Id` | **是** | 登录账号。缺省/未注册 → 按 `guest` 处理 |
| `Content-Type: application/json` | 写接口必填 | 请求体为 JSON |

```bash
# 今日 Token 用量（admin 视角）
curl "http://172.20.51.153:6789/api/stats/tokens" -H "X-User-Id: admin"
```

### 1.3 响应约定（重要）

- 成功与**业务失败都返回 HTTP 200**，靠 `success` 字段区分；权限不足返回 HTTP 403。
- 前端判断必须用 `success === true`，不能只看状态码。

```jsonc
{ "success": true,  ...业务字段 }                  // 成功
{ "success": false, "error": "错误描述" }          // 业务失败（HTTP 200）
{ "success": false, "error": "无权限" }            // 权限不足（HTTP 403）
```

> ⚠️ 两套返回风格并存，前端取值位置不同：
> - **统计类接口**（`/api/stats/*`、`/api/v2/usage/stats`、`/api/v2/sessions/{id}/usage`）：业务字段在**顶层**（与 `success` 平级）。
> - **管理类接口**（`/api/mcp/*`、`/api/agents/{id}/mcp`）：业务字段在 `data` 里。

### 1.4 权限口径

| 接口类型 | 需要的等级 | 说明 |
| --- | --- | --- |
| 全部 GET（统计/列表/详情） | `read` | `guest` 也可读 |
| 全部 POST / PUT / DELETE | `write` | `user` / `admin`；`guest` → 403 |
| 用户管理 `/api/users*` | `admin` | 仅管理员 |

数据隔离：`admin` 可查全部用户，可用 `?user_id=xxx` 指定单个用户；普通用户**强制只看自己**（忽略 `?user_id=`）。

> MCP 管理接口已不再要求 admin（历史文档写"仅 admin"已过期），改由 `config/permissions.json` 的角色等级决定：`admin`/`user` = write，`guest` = read。

---

## 2. Token 用量统计

### 2.1 跨会话用量统计（推荐大屏使用）

**`GET /api/v2/usage/stats`**

数据源：`data/sessions/*_messages.json` 中 assistant 消息落库的 `tokens` + `model` + `timestamp`（纯只读聚合，不调用大模型）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `period` | string | 否 | `month` | `day` = 今天；`week` = 本周一~今天；`month` = 本月 1 号~今天 |
| `start` | string | 否 | - | `YYYY-MM-DD`；与 `end` **同时传**时优先级最高，覆盖 `period` |
| `end` | string | 否 | - | `YYYY-MM-DD` |

```bash
curl "http://172.20.51.153:6789/api/v2/usage/stats?period=week" -H "X-User-Id: admin"
curl "http://172.20.51.153:6789/api/v2/usage/stats?start=2026-09-01&end=2026-09-20" -H "X-User-Id: admin"
```

响应：

```json
{
  "success": true,
  "period": "week",
  "user_id": "*",
  "range": { "start": "2026-09-14", "end": "2026-09-20" },
  "totals": {
    "prompt_tokens": 128430,
    "completion_tokens": 51220,
    "total_tokens": 179650,
    "api_calls": 316
  },
  "comparison": { "vs_last_period_percent": 12.4 },
  "by_model": {
    "qwen3_32b_q4": { "prompt_tokens": 120000, "completion_tokens": 48000, "total_tokens": 168000, "api_calls": 300 },
    "qwen3_32b":    { "prompt_tokens": 8430,   "completion_tokens": 3220,  "total_tokens": 11650,  "api_calls": 16 }
  },
  "by_day": [
    { "date": "2026-09-14", "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "api_calls": 0 },
    { "date": "2026-09-15", "prompt_tokens": 20110, "completion_tokens": 8010, "total_tokens": 28120, "api_calls": 52 }
  ]
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `user_id` | `"*"` = 全部用户（admin）；否则为被统计的用户 ID |
| `range.start/end` | 实际生效的时间窗口（含首尾） |
| `totals` | 窗口内合计：输入/输出/总量 token + 调用次数（一条 assistant 回复 = 1 次） |
| `comparison.vs_last_period_percent` | 与**等长上一期**的 total_tokens 环比；上期为 0 时返回 `null` |
| `by_model` | 按模型拆分（多模型对话时看各模型消耗） |
| `by_day` | 逐日趋势，**窗口内每天补 0** 便于画连续折线 |

> 前端建议：`by_day` 画折线/柱状，`by_model` 画占比环图，`totals.total_tokens` 做大数字卡片，`comparison` 做涨跌标签（`null` 时显示"—"）。

### 2.2 单会话上下文占用（对话页右侧「上下文」面板）

**`GET /api/v2/sessions/{session_id}/usage`**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `group_by` | string | 否 | - | 传 `model` 时额外返回 `by_model`（多模型会话成本） |

```bash
curl "http://172.20.51.153:6789/api/v2/sessions/session_xxx/usage?group_by=model" -H "X-User-Id: admin"
```

响应：

```json
{
  "success": true,
  "session_id": "session_xxx",
  "summary": {
    "turns": 6,
    "total_prompt_tokens": 31200,
    "total_completion_tokens": 7400,
    "total_tokens": 38600,
    "context_length": 16384,
    "last_prompt_tokens": 5120,
    "last_used_percent": 31.3,
    "peak_used_percent": 64.8
  },
  "rounds": [
    {
      "message_id": "msg_abc",
      "timestamp": "2026-09-20 10:24:31",
      "prompt": 5120,
      "completion": 860,
      "total": 5980,
      "model": "qwen3_32b_q4",
      "used_percent": 31.3
    }
  ],
  "by_model": {
    "qwen3_32b_q4": {
      "total_prompt_tokens": 31200,
      "total_completion_tokens": 7400,
      "total_tokens": 38600,
      "context_length": 16384,
      "last_used_percent": 31.3
    }
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `summary.turns` | 有效轮次（有 token 消耗的 assistant 消息数） |
| `summary.context_length` | 当前模型上下文窗口（由模型配置/自动发现决定） |
| `summary.last_used_percent` | **最近一轮**输入 token 占窗口百分比（"当前占用"） |
| `summary.peak_used_percent` | 历史峰值占用百分比（提示用户何时该压缩/新开会话） |
| `rounds[]` | 每轮明细（倒序=按落库顺序），`used_percent` 为该轮输入占用 |
| `by_model` | 仅 `?group_by=model` 时返回 |

### 2.3 某天 Token 用量（事件流口径）

**`GET /api/stats/tokens`**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `date` | string | 否 | 今天 | `YYYY-MM-DD` |
| `user_id` | string | 否 | - | 仅 admin 生效；指定单个用户 |

```bash
curl "http://172.20.51.153:6789/api/stats/tokens?date=2026-09-20" -H "X-User-Id: admin"
```

响应：

```json
{
  "success": true,
  "date": "2026-09-20",
  "user_id": "*",
  "scope": { "current_user": "admin", "is_admin": true },
  "token_source": "event_stream",
  "tokens": {
    "prompt_tokens": 40210,
    "completion_tokens": 15330,
    "total_tokens": 55540,
    "llm_calls": 88,
    "avg_tokens_per_call": 631.1,
    "by_model": {
      "qwen3_32b_q4": { "prompt_tokens": 40210, "completion_tokens": 15330, "total_tokens": 55540, "llm_calls": 88 }
    },
    "by_source": {
      "chat": { "total_tokens": 55540, "llm_calls": 88 }
    }
  },
  "hint": null
}
```

| 字段 | 说明 |
| --- | --- |
| `token_source` | `event_stream`＝事件流埋点（准）；`legacy_session_scan`＝回落扫历史会话；`empty`＝当天无数据 |
| `tokens.avg_tokens_per_call` | 单次调用平均 token（`total_tokens / llm_calls`） |
| `tokens.by_source` | 按来源拆分（chat / task / plan 等） |
| `hint` | 非 admin 且当天无数据时的**提示文案**（引导改用 admin 查询），前端可直接 toast 展示；正常为 `null` |

> 与 §2.1 的差异：本节按**天**聚合、含 MCP/图片/活跃度一整套（§2.4），口径为事件流；`/api/v2/usage/stats` 按**任意窗口**聚合、只算 token，且逐日补 0。大屏建议用 `/api/stats/*`，成本分析建议用 `/api/v2/usage/stats`。

### 2.4 某天总览（Token + MCP + 图片 + 活跃度）

**`GET /api/stats/daily`**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `date` | string | 否 | 今天 | `YYYY-MM-DD` |
| `user_id` | string | 否 | - | 仅 admin 生效 |

```json
{
  "success": true,
  "scope": { "current_user": "admin", "is_admin": true },
  "hint": null,
  "date": "2026-09-20",
  "user_id": "*",
  "token_source": "event_stream",
  "totals": {
    "events": 512,
    "mcp_calls": 74,
    "mcp_failed": 3,
    "llm_calls": 88,
    "prompt_tokens": 40210,
    "completion_tokens": 15330,
    "total_tokens": 55540,
    "images": 12,
    "image_requests": 9,
    "active_sessions": 21,
    "active_users": 5
  },
  "mcp": {
    "calls": 74,
    "success": 71,
    "failed": 3,
    "success_rate": 95.9,
    "avg_elapsed_ms": 812,
    "by_server": {
      "blackxml_topology": { "calls": 60, "success": 58, "failed": 2 },
      "alert_judge_tools":  { "calls": 14, "success": 13, "failed": 1 }
    },
    "by_tool": [
      { "server_name": "blackxml_topology", "tool_name": "query_topology", "calls": 40, "success": 40, "failed": 0, "avg_elapsed_ms": 640 }
    ],
    "errors": [
      { "ts": "2026-09-20 11:02:13", "server_name": "blackxml_topology", "tool_name": "query_topology", "error": "timeout" }
    ]
  },
  "tokens": { "...": "同 §2.3 tokens 结构" },
  "images": {
    "requests": 9,
    "images": 12,
    "success": 9,
    "failed": 0,
    "by_provider": { "comfyui": { "requests": 9, "success": 9, "failed": 0 } },
    "by_size": { "1024x1024": 12 }
  },
  "activity": {
    "events": 512,
    "active_sessions": 21,
    "active_users": 5,
    "active_agents": 3,
    "first_event": "2026-09-20 08:31:02",
    "last_event": "2026-09-20 19:45:11",
    "by_hour": { "00": 0, "01": 0, "08": 12, "09": 48, "10": 96 }
  }
}
```

> `activity.by_hour` **24 小时全量补齐**（缺失小时为 0），前端可直接画柱状图不断档。

### 2.5 最近 N 天趋势

**`GET /api/stats/trend`**

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `days` | int | 否 | `30` | 1~365（越界自动夹取） |
| `date` | string | 否 | 今天 | 趋势**终点**日期 `YYYY-MM-DD` |
| `user_id` | string | 否 | - | 仅 admin 生效 |

```json
{
  "success": true,
  "scope": { "current_user": "admin", "is_admin": true },
  "range": { "start": "2026-08-22", "end": "2026-09-20", "days": 30 },
  "user_id": "*",
  "totals": {
    "mcp_calls": 1420,
    "mcp_failed": 37,
    "prompt_tokens": 1204300,
    "completion_tokens": 421000,
    "total_tokens": 1625300,
    "llm_calls": 2680,
    "images": 96
  },
  "days": [
    {
      "date": "2026-09-20",
      "mcp_calls": 74,
      "mcp_failed": 3,
      "prompt_tokens": 40210,
      "completion_tokens": 15330,
      "total_tokens": 55540,
      "llm_calls": 88,
      "images": 12
    }
  ]
}
```

### 2.6 今日看板（含昨日环比 + 近 7 日）

**`GET /api/stats/overview`**

```json
{
  "success": true,
  "scope": { "current_user": "admin", "is_admin": true },
  "today": { "...": "同 §2.4 一整天结构" },
  "yesterday": { "...": "同 §2.4 一整天结构" },
  "vs_yesterday": {
    "mcp_calls_percent": 18.5,
    "total_tokens_percent": -6.2,
    "images_percent": null
  },
  "recent_7d": [
    { "date": "2026-09-14", "mcp_calls": 0, "total_tokens": 0 }
  ]
}
```

> 环比字段在上期为 0 时返回 `null`（前端显示"—"）。

---

## 3. MCP 调用统计

**`GET /api/stats/mcp`**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `date` | string | 否 | `YYYY-MM-DD`，默认今天 |
| `server` | string | 否 | 只保留该 MCP 服务（过滤 `mcp.by_tool`） |
| `tool` | string | 否 | 只保留该工具名（过滤 `mcp.by_tool`，可与 `server` 组合） |
| `user_id` | string | 否 | 仅 admin 生效 |

```bash
curl "http://172.20.51.153:6789/api/stats/mcp?date=2026-09-20&server=blackxml_topology" -H "X-User-Id: admin"
```

响应：

```json
{
  "success": true,
  "date": "2026-09-20",
  "user_id": "*",
  "scope": { "current_user": "admin", "is_admin": true },
  "filter": { "server": "blackxml_topology", "tool": null },
  "mcp": {
    "calls": 60,
    "success": 58,
    "failed": 2,
    "success_rate": 96.7,
    "avg_elapsed_ms": 780,
    "by_server": {
      "blackxml_topology": { "calls": 60, "success": 58, "failed": 2 }
    },
    "by_tool": [
      { "server_name": "blackxml_topology", "tool_name": "query_topology", "calls": 40, "success": 40, "failed": 0, "avg_elapsed_ms": 640 },
      { "server_name": "blackxml_topology", "tool_name": "get_device", "calls": 20, "success": 18, "failed": 2, "avg_elapsed_ms": 1060 }
    ],
    "errors": [
      { "ts": "2026-09-20 11:02:13", "server_name": "blackxml_topology", "tool_name": "get_device", "error": "timeout" }
    ]
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `mcp.calls / success / failed` | 调用总数 / 成功 / 失败（`failed = calls - success`） |
| `mcp.success_rate` | 成功率百分比（保留 1 位；无调用为 `0.0`） |
| `mcp.avg_elapsed_ms` | 平均耗时（毫秒，整数） |
| `mcp.by_server` | 按服务：`{calls, success, failed}` |
| `mcp.by_tool` | 按「服务+工具」：含 `avg_elapsed_ms`，**按调用次数降序**，最多返回前 N 组 |
| `mcp.errors` | 最近失败明细（`ts/server_name/tool_name/error`），`error` 截断 300 字符，最多保留最近 N 条 |
| `filter` | 回显本次过滤条件，便于前端高亮 |

> 注意：`server` / `tool` 过滤**只影响 `by_tool`**，`calls/success/failed/by_server` 仍是当天全量。

---

## 4. MCP 服务管理接口

响应统一为 `{ "success": true, "data": { ... } }`。

### 4.1 服务列表

**`GET /api/mcp/servers?check=true`**

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `check` | string | 否 | 传 `true` 时对每个**已启用**服务并发 ping，附加 `alive` / `latency_ms` |

```json
{
  "success": true,
  "data": {
    "total": 2,
    "servers": [
      {
        "name": "blackxml_topology",
        "url": "http://127.0.0.1:8602/mcp",
        "transport": "streamable_http",
        "enabled": true,
        "bound_agents": ["*"],
        "tool_count": 6,
        "tools": ["query_topology", "get_device"],
        "alive": true,
        "latency_ms": 42
      },
      {
        "name": "alert_judge_tools",
        "url": "http://127.0.0.1:8601/mcp",
        "transport": "streamable_http",
        "enabled": false,
        "bound_agents": ["alert_judge"],
        "tool_count": 3,
        "tools": ["judge_alert"],
        "alive": false,
        "latency_ms": null,
        "error": "connection refused"
      }
    ]
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `bound_agents` | 绑定范围：`["*"]` = 全局共享；否则为 agent_id 列表 |
| `tool_count` / `tools` | 已缓存的工具数与工具名（`tools` 为该服务工具名数组） |
| `alive` / `latency_ms` / `error` | 仅 `?check=true` 时出现；未启用服务不参与探测 |
| `Authorization` | **永不返回**，脱敏为 `"***"`（列表接口一律脱敏） |

### 4.2 新增服务（含鉴权 Token）

**`POST /api/mcp/servers`**

请求体：

```json
{
  "name": "kdocs",
  "url": "http://172.20.51.180:8603/mcp",
  "transport": "streamable_http",
  "headers": { "Authorization": "Bearer <TOKEN>" },
  "enabled": true,
  "auto_sync": true,
  "bound_agents": "*"
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | string | **是** | - | 小写字母开头，仅小写字母/数字/下划线/连字符（`^[a-z][a-z0-9_-]*$`） |
| `url` | string | **是** | - | MCP 服务地址（streamable_http 一般以 `/mcp` 结尾） |
| `transport` | string | 否 | `streamable_http` | 传输协议 |
| `headers` | object | 否 | `{}` | 自定义请求头；**鉴权 Token 放这里**：`{"Authorization": "Bearer xxx"}` |
| `enabled` | bool | 否 | `true` | 是否启用（启用即参与工具池） |
| `auto_sync` | bool | 否 | `true` | 保存后立即拉取工具列表并热刷新工具池 |
| `bound_agents` | string \| array | 否 | `"*"` | `"*"` = 全局共享；`["alert"]` = 仅绑定指定 agent |

响应：

```json
{
  "success": true,
  "data": {
    "name": "kdocs",
    "url": "http://172.20.51.180:8603/mcp",
    "transport": "streamable_http",
    "enabled": true,
    "bound_agents": ["*"],
    "tool_count": 5,
    "tools": ["read_doc", "create_doc"],
    "registry": { "local_tools": 18, "mcp_tools": 11 },
    "sync_error": "连接超时（可选，同步失败时出现）"
  }
}
```

| 场景 | HTTP | body |
| --- | --- | --- |
| 缺少 name/url | 200 | `{"success": false, "error": "name 和 url 为必填项"}` |
| name 非法 | 200 | `{"success": false, "error": "name 只能包含小写字母、数字、下划线和连字符，且以小写字母开头"}` |
| 重名 | 200 | `{"success": false, "error": "MCP 服务已存在: xxx"}` |

> `data.sync_error` 出现时表示服务已存盘但工具未拉到（地址/Token 有误），前端应提示"已保存但连接失败"。

### 4.3 连通性测试（不写盘）

**`POST /api/mcp/servers/test`**

```json
// 请求
{ "url": "http://172.20.51.180:8603/mcp", "transport": "streamable_http",
  "headers": { "Authorization": "Bearer <TOKEN>" } }

// 响应
{
  "success": true,
  "data": {
    "url": "http://172.20.51.180:8603/mcp",
    "transport": "streamable_http",
    "alive": true,
    "latency_ms": 88,
    "tool_count": 5,
    "tools": [ { "name": "read_doc", "description": "读取文档（截断 100 字符）" } ]
  }
}
```

### 4.4 启停

**`POST /api/mcp/servers/{name}/toggle`** — body `{ "enabled": true }`

```json
{
  "success": true,
  "data": {
    "server": "kdocs",
    "enabled": true,
    "registry": { "local_tools": 18, "mcp_tools": 16 },
    "auto_disabled": false,
    "note": "工具池已热刷新；enabled 变更立即生效于后续对话"
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `enabled` | **最终**状态（服务不健康时可能被自动降级） |
| `auto_disabled` | `true` 表示请求启用但被健康检查自动关停，前端需提示 |
| body 缺布尔 `enabled` | `{"success": false, "error": "body 需含布尔字段 enabled"}` |

### 4.5 同步工具列表

**`POST /api/mcp/servers/{name}/sync`**

```json
{ "success": true,
  "data": { "server": "kdocs", "tool_count": 5, "registry": { "local_tools": 18, "mcp_tools": 16 } } }
```

### 4.6 配置绑定范围

**`POST /api/mcp/servers/{name}/binding`** — body `{ "bound_agents": ["alert"] }` 或 `{ "bound_agents": "*" }`

```json
{ "success": true, "data": { "server": "kdocs", "bound_agents": ["alert"] } }
```

非法值：`{"success": false, "error": "bound_agents 必须是字符串数组或 '*'"}`

### 4.7 删除服务

**`DELETE /api/mcp/servers/{name}`**

```json
{
  "success": true,
  "data": {
    "server": "kdocs",
    "registry": { "local_tools": 18, "mcp_tools": 11 },
    "cleaned_agents": ["alert"]
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `cleaned_agents` | 被联动清理了悬空引用的 agent 列表 |
| 服务不存在 | `{"success": false, "error": "MCP 服务不存在: xxx"}` |

### 4.8 管理页

**`GET /mcp-admin`** → 返回单文件 HTML（`Content-Type: text/html; charset=utf-8`），可直接 iframe 内嵌或新窗口打开。

---

## 5. Agent ↔ MCP 绑定

### 5.1 查询某 Agent 的 MCP 绑定

**`GET /api/agents/{agent_id}/mcp`**

```json
{
  "success": true,
  "data": {
    "agent_id": "dfecrab",
    "enabled_mcp_servers": ["blackxml_topology", "kdocs"],
    "mcp_tools_whitelist": null,
    "available_servers": [
      { "name": "blackxml_topology", "enabled": true, "tool_count": 6, "bound_agents": ["*"] },
      { "name": "alert_judge_tools", "enabled": true, "tool_count": 3, "bound_agents": ["alert_judge"] }
    ]
  }
}
```

> 绑定关系以**服务配置**为单一事实源（`bound_agents`），本接口是只读视图。`mcp_tools_whitelist` 为历史字段，恒为 `null`。

### 5.2 保存某 Agent 的绑定（以 Agent 为中心全量覆盖）

**`PUT /api/agents/{agent_id}/mcp`** — body `{ "mcp_servers": ["blackxml_topology", "kdocs"] }`（空数组 = 清空绑定）

```json
{
  "success": true,
  "data": {
    "agent_id": "dfecrab",
    "mcp_servers": ["blackxml_topology", "kdocs"],
    "changed": { "added": ["kdocs"], "removed": [] },
    "warnings": ["已绑定但服务当前未启用（启用后生效）: kdocs"],
    "registry": { "local_tools": 18, "mcp_tools": 16 }
  }
}
```

| 场景 | 返回 |
| --- | --- |
| Agent 不存在 | `{"success": false, "error": "Agent 不存在: xxx"}`（HTTP 200） |
| 绑定保留服务 | `{"success": false, "error": "MCP 服务 [alert_judge_tools] 是保留绑定（仅限 alert_judge），不能绑到智能体 [xxx]"}` |
| 绑定未启用服务 | 成功 + `warnings` 提示（绑定是元数据，启停是全局开关） |

**`POST /api/agents/{agent_id}/mcp`** — 已废弃，返回迁移提示（不再 404）：

```json
{ "success": false,
  "error": "POST /api/agents/{agent_id}/mcp 已废弃：绑定编辑已收敛到智能体配置页，请改用 PUT /api/agents/{agent_id}/mcp（body: {\"mcp_servers\": [\"kdocs\"]}, 空数组=清空绑定）" }
```

---

## 6. 对话中调用 MCP（`mcp` 入参）

`POST /api/v2/chat`、`/api/v2/chat/stream`、WebSocket 对话均支持 `mcp` 参数：**运行时临时指定本轮使用的 MCP 服务**（不修改持久化绑定）。

| 值 | 行为 |
| --- | --- |
| 不传 / `null` | 走默认编排（Manager 决策 + Agent 绑定的 MCP 服务） |
| 字符串 `"blackxml_topology"` | 单服务直连 |
| 数组 `["blackxml_topology","kdocs"]` | 多服务直连 |
| `[]` / `true` / `{}` 等 | **报错**：`mcp 参数必须是非空的 MCP 服务名字符串或字符串数组` |

```bash
curl -X POST http://172.20.51.153:6789/api/v2/chat \
  -H "Content-Type: application/json" -H "X-User-Id: admin" \
  -d '{"message":"查询F19线路拓扑","mcp":["blackxml_topology"]}'
```

规则与约束：

1. **与 `knowledge_base` 互斥**：同时传 → `knowledge_base 与 agent_id/mcp 参数互斥`。
2. 指定 `mcp` 时**跳过 Manager LLM 编排**，直接路由到 `agent_id`（缺省 `dfecrab`），减少一轮推理开销。
3. `mcp` 数组中含 `alert_judge_tools` → 无论 `agent_id` 为何，**强制路由到 `alert_judge`** 研判链路。
4. `agent_id` 与 `mcp` 可共存（`agent_id` 决定工具装配上下文，`mcp` 决定可用服务）。

---

## 7. 错误与排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `success: false` + `hint` 文案 | 非 admin 查询了他人产生的数据 | 改用 `X-User-Id: admin`，或 `?user_id=xxx` 指定 |
| 统计全为 0 | 当天无数据 / 事件流未产生 | 用 `?date=` 换一天；`token_source: legacy_session_scan` 表示走了历史回落 |
| HTTP 403 `{"success": false, "error": "无权限"}` | 角色等级不足（写接口用 guest） | 换 `user`/`admin` 身份 |
| `auto_disabled: true` | 服务不健康被自动关停 | 用 `/test` 或 `?check=true` 查 `alive`/`error` |
| `sync_error` | 保存成功但工具未拉到 | 校验 `url` 与 `Authorization` Token |
| MCP 列表无 `Authorization` | 接口固定脱敏为 `"***"` | Token 不回显，前端编辑时留空=不修改 |

---

## 8. 前端接入建议

1. **大屏**：`/api/stats/overview`（今日卡片 + 环比 + 近 7 日）为主，`/api/stats/trend?days=30` 画趋势。
2. **用量明细页**：`/api/stats/daily`（四象限：Token/MCP/图片/活跃度）+ `/api/stats/mcp`（工具排行）。
3. **成本分析**：`/api/v2/usage/stats?period=month`（按模型拆分 + 环比）。
4. **对话页上下文条**：`/api/v2/sessions/{id}/usage`，用 `last_used_percent` 显示占用、`peak_used_percent` 做预警。
5. **管理后台 MCP**：`/mcp-admin` 直接内嵌；自研页面用 §4 接口，Token 输入框只提交不回显（列表脱敏为 `***`，留空表示不修改）。

---

*文档更新日期: 2026-09-20*
