# DFEcrab API 接口文档（后端对接版）

> 更新日期：2026-09-04  
> 适用版本：DFEcrab v4.9.0-grpc  
> 阅读对象：后端 / 集成开发人员  
> 后端技术：Python（自定义 HTTP Server + gRPC + Zookeeper）

---

## 📌 更新记录

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v4.9 | 2026-09-04 | **新增可选 URL 前缀 `/dfecrab`**：全部 HTTP 接口两种地址等价（`/api/...` 与 `/dfecrab/api/...`）；本文档重写为面向后端的现状版，接口总览以代码注册表为准更新 |
| v4.0 | 2026-04-06 | 初版 |

---

## 1. 快速开始

```bash
# 1) 健康检查（连通性验证）
curl http://172.20.51.153:6789/health

# 2) 带鉴权头的对话（所有业务接口都必须带 X-User-Id）
curl -X POST http://172.20.51.153:6789/api/v2/chat \
  -H "Content-Type: application/json" \
  -H "X-User-Id: admin" \
  -d '{"message": "你好"}'

# 3) 与上面等价的新地址（可选前缀，v4.9 起）
curl -X POST http://172.20.51.153:6789/dfecrab/api/v2/chat \
  -H "Content-Type: application/json" \
  -H "X-User-Id: admin" \
  -d '{"message": "你好"}'
```

> 约定：本文所有路径均为“旧路径”。**每条路径都可选在前面加 `/dfecrab`**，如 `GET /dfecrab/api/v2/sessions`，效果与 `GET /api/v2/sessions` 完全一致。

---

## 2. 服务地址

| 服务 | 地址 | 说明 |
|------|------|------|
| **HTTP API** | `http://<网关>:6789` | 主 API 端口；v4.9 起支持可选 `/dfecrab` 前缀 |
| **健康检查** | `http://<网关>:6789/health` | 等价：`/dfecrab/health` |
| **WebSocket（对话）** | `ws://<网关>:6790/ws` | 路径不敏感，`/dfecrab/ws` 亦可 |
| **知识库 API** | `http://<网关>:6788/knowledge/...` | 独立进程，前缀固定为 `/knowledge`（不受本次变更影响） |
| **内部 gRPC** | `localhost:2181`（Zookeeper） | 服务发现与负载均衡，后端一般不需要直接调用 |

### 架构说明

```
用户 -> HTTP(6789, 可选 /dfecrab 前缀) -> Gateway -> gRPC -> Manager(随机端口)
                                                     ↓
                                                Zookeeper(2181)
                                                     ↓
                                                Workers(随机端口)
```

---

## 3. 认证与鉴权（必读）

### 3.1 身份头 `X-User-Id`

**每个请求都必须携带 `X-User-Id` 头**，值为登录账号字符串：

- 不传 / 传未注册账号 → 按 `guest`（访客）处理：读操作正常，写操作返回 `403`
- 角色：`admin`（全权限+系统管理）、`user`（可读写自己数据）、`guest`（只读）
- 数据隔离：`user`/`guest` 只能访问自己账号产生的数据（`data_scope=own`），`admin` 可访问全部（`all`）
- 用户管理接口（`/api/users*`）与 MCP 管理接口仅 `admin` 可调（非 admin 连读都返回 `403`）

### 3.2 权限速查

| 操作 | 需要的角色 |
| --- | --- |
| 读接口（GET 查询类） | 任意角色（guest 也可） |
| 写接口（POST / PUT / DELETE / PATCH） | `user` 或 `admin`（guest → 403） |
| 用户管理、MCP 服务管理 | 仅 `admin` |
| WebSocket 对话 | 消息体带 `user_id` 字段 |

### 3.3 响应约定

成功与业务失败**都返回 HTTP 200**，通过 `success` 字段区分；权限不足返回 HTTP 403：

```json
{ "success": true, "data": { ... } }          // 成功
{ "success": false, "error": "错误描述" }      // 业务失败（HTTP 200）
{ "success": false, "error": "无权限" }        // 权限不足（HTTP 403）
```

> ⚠️ 判断成功与否必须同时看 `success === true`，不能只看 HTTP 状态码。

---

## 4. URL 前缀兼容说明（v4.9）

HTTP 入口对以 `/dfecrab` 开头的路径自动剥离该段后再匹配路由，因此：

- **旧地址**：`http://网关:6789/api/v2/chat` —— 不变，继续可用
- **新地址**：`http://网关:6789/dfecrab/api/v2/chat` —— 等价，可选
- 作用范围：**全部 HTTP 接口**（含 `/health`、`/mcp-admin` 等非 `/api` 路径）
- WebSocket（6790）握手不校验路径，任意路径均可连接

---

## 5. 接口总览（以代码注册表为准）

图例：🔒 = 仅 admin；✍ = 写操作（user/admin，guest 403）；其余 GET 为读接口（任意角色）。

### 5.0 系统 / 健康

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（含 Manager/Worker 状态） |
| GET | `/mcp-admin` | MCP 管理 Web 页面 |

### 5.1 对话（核心）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v2/chat` | ✍ | 非流式对话（阻塞返回完整结果） |
| POST | `/api/v2/chat/stream` | ✍ | SSE 流式对话（逐事件推送，事件协议见《前端对接文档_对话接口.md》） |

> 支持 `knowledge_base`、`mcp`、`agent_id` 分支路由；详细协议见对话接口文档 v4.8。

### 5.2 会话与用量

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/v2/sessions` | 读 | 列出会话（`?limit=N`；仅自己数据，admin 可看全部） |
| POST | `/api/v2/sessions` | ✍ | 创建会话 `{ topic }` |
| GET | `/api/v2/sessions/{session_id}` | 读 | 会话详情 |
| GET | `/api/v2/sessions/{session_id}/messages` | 读 | 会话内消息（含思考/工具调用/结构化输出） |
| GET | `/api/v2/sessions/{session_id}/usage` | 读 | 会话 token 占用统计 |
| GET | `/api/v2/usage/stats` | 读 | 全局 token 用量统计 |
| DELETE | `/api/v2/sessions/deleteSession/{session_id}` | ✍ | **删除会话**（注意 `deleteSession` 是路径固定段，不是参数） |

### 5.3 任务管理（V2）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/api/v2/tasks` | ✍ | 创建任务（临时/定时） |
| GET | `/api/v2/tasks` | 读 | 任务列表（`?task_type=&status=&limit=&offset=`） |
| GET | `/api/v2/tasks/{task_id}` | 读 | 任务详情 |
| DELETE | `/api/v2/tasks/{task_id}` | ✍ | 删除任务 |
| GET | `/api/v2/tasks/{task_id}/progress` | 读 | 任务执行进度 |
| GET | `/api/v2/tasks/{task_id}/audit` | 读 | 任务审计日志 |
| GET | `/api/v2/tasks/{task_id}/dashboard` | 读 | 任务看板数据 |
| POST | `/api/v2/tasks/{task_id}/execute` | ✍ | 执行任务 |
| POST | `/api/v2/tasks/{task_id}/convert` | ✍ | 任务类型转化 |
| POST | `/api/v2/tasks/{task_id}/approve` | ✍ | 审批/确认任务（V1 兼容端点） |
| POST | `/api/v2/tasks/{task_id}/pause` | ✍ | 暂停定时任务（V1 兼容端点） |
| POST | `/api/v2/tasks/{task_id}/resume` | ✍ | 恢复定时任务（V1 兼容端点） |
| POST | `/api/v2/tasks/{task_id}/trigger` | ✍ | 手动触发（V1 兼容端点） |
| POST | `/api/v2/tasks/preview` | ✍ | 预览 Manager 推荐（不创建） |

### 5.4 Agent / Worker

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/agents` | 读 | Agent 列表（含图标/配色/技能） |
| POST | `/api/agents` | ✍ | 创建 Agent |
| GET | `/api/agents/{agent_id}` | 读 | Agent 详情 |
| PUT | `/api/agents/{agent_id}` | ✍ | 更新 Agent |
| DELETE | `/api/agents/{agent_id}` | ✍ | 删除 Agent |
| GET | `/api/agents/{agent_id}/mcp` | 读 | 某 Agent 绑定的 MCP 服务 |
| POST | `/api/agents/{agent_id}/mcp` | 🔒 | 设置 Agent 的 MCP 绑定 |
| GET | `/api/v2/workers` | 读 | Worker Agent 列表（Zookeeper 发现） |
| GET | `/api/services` | 读 | 服务注册健康状态 |
| GET | `/api/invariants` | 读 | 系统不变量检查 |

### 5.5 模型管理

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/models` | 读 | 模型供应商列表（含参数配置） |
| GET | `/api/models/current` | 读 | 当前模型信息 |
| POST | `/api/models/switch` | ✍ | 切换当前模型供应商 `{ provider }` |
| POST | `/api/models` | ✍ | 新增模型配置 |
| PUT | `/api/models/{config_name}` | ✍ | 编辑模型配置 |
| DELETE | `/api/models/{config_name}` | ✍ | 删除模型配置 |
| POST | `/api/models/{config_name}/toggle` | ✍ | 启用/停用模型 |
| POST | `/api/models/{config_name}/discover` | ✍ | 自动发现上下文窗口 |
| GET | `/api/fallback/status` | 读 | 模型容错/降级状态 |

### 5.6 技能 / 插件

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/skills` | 读 | 技能列表 |
| GET | `/api/skills/search` | 读 | 搜索技能 |
| POST | `/api/skills/reload` | ✍ | 重新加载技能 |

### 5.7 记忆 / 事件 / 规划

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/memory/stats` | 读 | 记忆统计（按用户隔离） |
| GET | `/api/memory/recent` | 读 | 最近每日记忆 |
| GET | `/api/memory/search` | 读 | 记忆检索 `?q=&scope=` |
| GET | `/api/memory/files` | 读 | 记忆文件列表 |
| GET | `/api/memory/storage` | 读 | 存储路径 |
| GET | `/api/memory/index_health` | 读 | 索引健康 |
| GET | `/api/memory/agents/{agent_id}` | 读 | Agent 私有记忆 |
| GET | `/api/memory/agents` | 读 | Agent 私有记忆摘要 |
| GET | `/api/memory/users` | 读 | 用户级记忆列表 |
| POST | `/api/memory/users/{user_id}` | ✍ | 写入用户记忆 |
| PUT | `/api/memory/users/{user_id}/{mem_id}` | ✍ | 更新用户记忆 |
| DELETE | `/api/memory/users/{user_id}/{mem_id}` | ✍ | 删除用户记忆 |
| GET | `/api/events/search` | 读 | 事件检索 |
| GET | `/api/events/recent` | 读 | 最近事件 |
| GET | `/api/events/stats` | 读 | 事件统计 |
| POST | `/api/events/add` | ✍ | 写入事件 |
| GET | `/api/plan/current` | 读 | 当前计划详情 |
| GET | `/api/plan/list` | 读 | 计划列表 |
| GET | `/api/plan/progress` | 读 | 当前计划进度 |
| GET | `/api/plan/steps` | 读 | 计划步骤及结果 |
| POST | `/api/plan/next` | ✍ | 执行下一步 |
| POST | `/api/plan/skip` | ✍ | 跳过当前步 |
| POST | `/api/plan/cancel` | ✍ | 取消计划 |
| POST | `/api/plan/step/execute` | ✍ | 手动执行某一步 |

### 5.8 用户管理（全部仅 admin）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/users` | 🔒 | 列出账号 → 角色 |
| POST | `/api/users` | 🔒 | 新增账号 `{ user_id, role }` |
| PUT | `/api/users/{user_id}` | 🔒 | 修改账号角色 `{ role }` |
| DELETE | `/api/users/{user_id}` | 🔒 | 删除账号 |

### 5.9 MCP 服务管理（管理操作全部仅 admin）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/mcp/servers` | 🔒 | MCP 服务列表 |
| POST | `/api/mcp/servers` | 🔒 | 新增 MCP 服务 |
| POST | `/api/mcp/servers/{name}/toggle` | 🔒 | 启停服务 |
| POST | `/api/mcp/servers/{name}/sync` | 🔒 | 同步服务 |
| POST | `/api/mcp/servers/{name}/binding` | 🔒 | 配置绑定 Agent |
| POST | `/api/mcp/servers/test` | 🔒 | 测试服务连通 |
| DELETE | `/api/mcp/servers/{name}` | 🔒 | 删除服务 |

### 5.10 自反思 / 任务调度辅助

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/api/reflections` | 读 | 反思历史 |
| GET | `/api/reflections/{reflection_id}` | 读 | 反思报告详情 |
| POST | `/api/reflections/{reflection_id}/implement` | ✍ | 执行改进计划 |
| GET | `/api/tasks/heartbeats` | 读 | 心跳任务状态 |
| GET | `/api/tasks/scheduled` | 读 | 定时任务列表 |
| GET | `/api/tasks/stats` | 读 | 任务统计 |
| GET | `/api/tasks/todos` | 读 | 待办列表 |
| POST | `/api/tasks/todos` | ✍ | 添加待办 |
| POST | `/api/tasks/todos/{task_id}/complete` | ✍ | 完成待办 |

---

## 6. 常用接口调用示例

### 6.1 健康检查

```bash
curl http://172.20.51.153:6789/health
curl http://172.20.51.153:6789/dfecrab/health   # v4.9 前缀地址，等价
```

### 6.2 会话列表（读）

```bash
curl "http://172.20.51.153:6789/api/v2/sessions?limit=10" -H "X-User-Id: admin"
```

> 响应结构（`success / count / sessions[]` 及每条会话字段）以《前端对接文档_会话历史.md》§4.1 为准。

### 6.3 非流式对话（写）

```bash
curl -X POST http://172.20.51.153:6789/dfecrab/api/v2/chat \
  -H "Content-Type: application/json" \
  -H "X-User-Id: admin" \
  -d '{
    "message": "昆明电网今日负荷情况",
    "knowledge_base": true,
    "session_id": "session_xxx"
  }'
```

> `knowledge_base` / `mcp` / `agent_id` 均为可选；`message` 支持 dict（如告警 JSON）。完整事件协议见《前端对接文档_对话接口.md》。

### 6.4 新增用户（仅 admin）

```bash
curl -X POST http://172.20.51.153:6789/api/users \
  -H "Content-Type: application/json" -H "X-User-Id: admin" \
  -d '{"user_id": "zhangsan", "role": "user"}'
```

---

## 7. Python 调用示例

```python
import requests

API_BASE = "http://172.20.51.153:6789"   # v4.9 可选：http://172.20.51.153:6789/dfecrab
HEADERS = {"X-User-Id": "admin", "Content-Type": "application/json"}


def health():
    return requests.get(f"{API_BASE}/health", timeout=10).json()


def chat(message: str, session_id: str = ""):
    resp = requests.post(
        f"{API_BASE}/api/v2/chat",
        headers=HEADERS,
        json={"message": message, "session_id": session_id},
        timeout=300,
    )
    return resp.json()


def list_sessions():
    return requests.get(f"{API_BASE}/api/v2/sessions", headers=HEADERS, timeout=30).json()


def get_messages(session_id: str):
    return requests.get(
        f"{API_BASE}/api/v2/sessions/{session_id}/messages",
        headers=HEADERS,
        timeout=30,
    ).json()


if __name__ == "__main__":
    print("health:", health())
    print("chat:", chat("你好"))
```

---

## 8. 详细字段说明（文档索引）

本文件为**路径 / 鉴权 / 调用总览**；逐接口的请求参数字段、响应 JSON 结构、事件流协议、错误样例，见更详细的文档（位置：`前端对接文档/`）：

| 模块 | 详细文档 |
|------|----------|
| 对话（含 SSE 事件协议） | 前端对接文档_对话接口.md（v4.8） |
| 会话与历史 | 前端对接文档_会话历史.md |
| 任务管理 | 前端对接文档_任务管理.md |
| 用户管理与权限模型 | 前端对接文档_用户管理.md |
| 记忆管理 | 前端对接文档_记忆管理.md |
| 模型管理 | 前端对接文档_模型管理.md |
| 技能管理 | 前端对接文档_技能管理.md |
| Agent 管理 | 前端对接文档_Agent管理.md |
| MCP 服务管理 | 前端对接文档_MCP服务管理.md |
| 知识库 API | 前端对接文档_知识库.md |
| URL 前缀兼容说明 | 前端对接文档_URL前缀兼容说明.md（v4.9） |

---

## 9. 配置与数据存储（后端/运维）

- 主配置：`config/dfecrab.json`（模型、Agent、服务端口）
- 网关配置：`config/gateway.yaml`（端口 6789/6790、Zookeeper、本地服务端口）
- 权限配置：`config/permissions.json`（角色 level/data_scope、账号 → 角色映射）
- 审计日志：`data/tasks/audit/`（任务执行审计）
- 变更历史：见 `docs/CHANGELOG.md`

---

*文档更新日期: 2026-09-04*  
*后端负责人: DFEcrab Team*
