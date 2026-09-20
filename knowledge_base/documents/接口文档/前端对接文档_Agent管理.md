# Agent 管理 - 前端对接文档

## 一、核心概念

Agent（智能体）是本平台的"人设 + 工具能力"载体。一个 Agent 通过 `agent_id` 唯一标识，对话时传 `agent_id` → 系统加载该 Agent 的人设与可用工具（本地技能 + 绑定的 MCP 服务）。

**Agent 分类（`agent_type`）：**

| 类型 | 含义 |
|------|------|
| `manager` | 管理型 Agent（负责任务编排、意图分发） |
| `default` | 默认 Agent（`dfecrab`），兜底对话入口 |
| `worker` | 工作型 Agent（业务处理、专项能力） |

**`status` 说明：**
- 本地 `agents/` 目录扫描出来的 Agent 只有 `agent_id`/`agent_type`/`icon`/`name`/`skills` 等静态信息；
- `status`/`address`/`service_id` 由 **Zookeeper 运行期注册**补充：注册了才是 `active`，未注册则不带 `status` 或视为离线。前端据此展示"在线/离线"。

---

## 二、Agent 管理接口

### 2.1 获取 Agent 列表

**GET** `/api/agents`

**响应示例：**
```json
{
  "success": true,
  "agents": [
    {
      "agent_id": "default",
      "agent_type": "default",
      "icon": "🤖",
      "iconColor": "#FF6B6B",
      "bgColor": "#FFE5E5",
      "name": "默认助手",
      "skills": ["file_manager", "summarize"],
      "status": "active",
      "address": "192.168.1.50:7801",
      "service_id": "worker_agent_xxx"
    },
    {
      "agent_id": "kunming",
      "agent_type": "worker",
      "icon": "⚡",
      "iconColor": "#2196F3",
      "bgColor": "#E3F2FD",
      "name": "昆明电网助手",
      "skills": ["load_analysis", "power_transfer_strategy"]
    }
  ]
}
```

**字段说明：**
| 字段 | 类型 | 说明 |
|------|------|------|
| agent_id | string | Agent 唯一标识（目录名） |
| agent_type | string | `manager` / `default` / `worker` |
| name | string | 展示名（来自 `config.json`） |
| icon | string | 头像 emoji |
| iconColor / bgColor | string | 前端配色（同类 Agent 统一着色） |
| skills | string[] | 该 Agent 启用的本地技能 |
| status | string | **仅在线时出现**：`active`（来自 ZK 注册） |
| address | string | **仅在线时出现**：`host:port` |
| service_id | string | **仅在线时出现**：ZK 服务 ID |

**注意：**
- 返回的 `skills` 是本地技能，不含 MCP 工具；MCP 工具请查 `/api/agents/{agent_id}/mcp`。
- 前端不用自己算配色，`iconColor`/`bgColor` 后端已按 `agent_type` 统一填好。

### 2.2 创建 Agent

**POST** `/api/agents`

**请求体：**
```json
{ "agent_id": "kunming" }
```

**说明：**
- 仅需 `agent_id`，创建后会在 `agents/` 下生成对应的配置目录；
- 创建后 Agent 的完整人设/技能需要后续在配置层补充，此处仅建骨架；
- 权限：需要 `write` 等级。

### 2.3 删除 Agent

**DELETE** `/api/agents/{agent_id}`

**说明：**
- 删除 `agents/` 目录 + 停止对应进程；
- 权限：需要 `write` 等级；
- 前端删除前应做二次确认（该 Agent 的私有记忆、会话历史也会随之清理）。

### 2.4 查询某 Agent 的 MCP 可用服务（只读）

**GET** `/api/agents/{agent_id}/mcp`

**响应示例：**
```json
{
  "success": true,
  "data": {
    "agent_id": "alert_judge",
    "enabled_mcp_servers": ["alert_judge_tools"],
    "mcp_tools_whitelist": null,
    "available_servers": [
      { "name": "alert_judge_tools", "enabled": true, "tool_count": 5, "bound_agents": ["alert_judge"] },
      { "name": "kdocs", "enabled": true, "tool_count": 249, "bound_agents": [] }
    ]
  }
}
```

**字段说明：**
- `enabled_mcp_servers`：**只读**，该 Agent 实际能用的 MCP 服务（由服务级绑定派生，非手动配置）；
- `mcp_tools_whitelist`：恒为 `null`（细粒度工具白名单已废弃）；
- `available_servers`：所有 MCP 服务 + 各自绑定状态，前端可据此判断"某服务绑定到哪个 Agent"。

### 2.5 保存 Agent 的 MCP 配置（已废弃）

**POST** `/api/agents/{agent_id}/mcp` — **不再支持**。

调用会返回迁移提示：
```json
{
  "success": false,
  "error": "per-agent MCP 配置已迁移：请在服务级配置绑定，使用 POST /api/mcp/servers/{name}/binding"
}
```

前端应改用 `POST /api/mcp/servers/{name}/binding`（详见《前端对接文档_MCP服务管理.md》）。

---

## 三、Agent 对话

对话统一走 `/api/v2/chat` 或 `/api/v2/chat/stream`，请求体里传 `agent_id` 决定走哪个人设。详见《前端对接文档_对话接口.md》。

```
选择 Agent → GET /api/agents（拿列表+状态）
    ↓
对话 → POST /api/v2/chat { message, agent_id }
    ↓
Agent 人设 + 本地技能 + 绑定 MCP 工具注入 → LLM 回复
```

---

## 四、前端页面实现建议

```
Agent 管理页
├── Agent 卡片列表（2.1）
│   ├── 头像 emoji + 名称 + agent_type 标签
│   ├── 在线/离线状态（status 有无）
│   └── 本地技能 tags
├── 新建 Agent（2.2）：输入 agent_id → 创建
├── 删除 Agent（2.3）：确认弹窗
└── MCP 绑定入口（2.4）：跳转 MCP 服务管理页
```

**交互流程：**
1. 进入页面 → `GET /api/agents` 渲染卡片；
2. 新建 → 弹窗输入 `agent_id` → `POST /api/agents` → 刷新；
3. 删除 → 确认弹窗 → `DELETE /api/agents/{id}` → 刷新；
4. 绑定 MCP → 到 MCP 服务管理页操作（Agent 文档不提供写入口）。

---

## 五、API 错误响应

所有接口统一格式：
```json
{ "success": false, "error": "错误信息描述" }
```

---

## 六、测试命令（开发调试用）

```bash
# 列出所有 Agent
curl http://172.20.42.247:6789/api/agents

# 创建 Agent
curl -X POST http://172.20.42.247:6789/api/agents \
  -H "Content-Type: application/json" -d '{"agent_id":"kunming"}'

# 删除 Agent
curl -X DELETE http://172.20.42.247:6789/api/agents/kunming

# 查询某 Agent 可用 MCP（只读）
curl http://172.20.42.247:6789/api/agents/alert_judge/mcp
```

---

## 七、注意事项

1. **`agent_id` 是唯一主键**：对话、会话、记忆、MCP 绑定都以此关联，创建后不建议改名。

2. **`status` 只反映运行期在线**：静态配置的 Agent 若进程未注册到 ZK，列表里没有 `status` 字段；前端展示"离线"。

3. **MCP 绑定不在 Agent 侧配置**：Agent 能用的 MCP 工具由服务级 `bound_agents` 派生（单一事实源在 `mcporter.json` 服务项上），Agent 文档只读、不写。

4. **权限**：创建（POST）/ 删除（DELETE）需要 `write` 等级；列表（GET）仅需登录；`POST /api/agents/{id}/mcp` 已废弃返回迁移提示。
