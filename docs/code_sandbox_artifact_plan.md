# DFEcrab 代码沙箱产物展示方案

> 范围：**仅后台改造 + 协议约定**，前端渲染、动画、折叠 UI 由前端人员实现。  
> 基于代码：`skills/code_executor/execute.py`、`src/skill/registry.py`、`src/agent/loop.py`、`src/gateway/grpc_server.py`、`src/gateway/http/server.py`、`src/core/event_types.py`。  
> 目标：让 `code_writer` 智能体调用 `code_executor` 执行 Python 后，生成的文件（图表、csv、代码文件等）能被前端通过相对路径下载/预览。

---

## 1. 现状（基于真实代码）

### 1.1 代码执行链路

```
WS chat_stream  / HTTP /api/v2/chat/stream
  → src/gateway/grpc_server.py handle_chat_stream()
    → _run_chat_pipeline(session_id=...)
      → _react_chat_generator(session_id=...)
        → ReActLoop.run(agent_id="code_writer", ...)
          → tool_registry.execute_tool("code_executor", code="...")
            → skills/code_executor/execute.py::execute()
              → _sync_execute() 在临时文件跑代码 → 执行完 os.unlink(tmp_path)
```

**问题**：`code_executor` 执行后立刻删除临时文件，产物没有任何落盘机会。

### 1.2 事件链路（已具备）

`src/agent/loop.py` 已经emit这些事件：

- `tool_call`：LLM 决定调用工具（含 tool_name、tool_args）
- `tool_start`：工具实际开始执行
- `tool_progress`：长耗时工具进度
- `tool_result`：工具执行结果
- `message_end`：最终回复

`src/gateway/grpc_server.py` 的 `_react_chat_generator()` 会把这些事件透传给前端。

**结论**：工具调用"显示哪个工具、参数、运行中/完成"所需的事件骨架已经存在，前端只需要做渲染。**本次后台只需补齐：产物落盘 + 文件 URL 传递。**

### 1.3 网关 HTTP 路由

`src/gateway/http/server.py` 使用 `RouteRule` + `add_route()` 注册路由，路径参数通过 `{session_id}` 解析。当前没有 `/artifacts/...` 静态文件路由。

---

## 2. 总体设计

```
┌─────────────────────────────────────────────────────────────────────┐
│  前端 (Web)                                                          │
│  · 接收 WS event_type=tool_result                                    │
│  · 读取 data.artifacts[] 拿到相对路径 /artifacts/{sid}/{file}         │
│  · 用当前 host + 该相对路径显示下载链接 / 右侧预览                     │
└─────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ WS: tool_result / tool_call / tool_start
┌───────────────────────────────────┼─────────────────────────────────┐
│  网关                                                              │
│  · WS 入口：handle_chat_stream()                                   │
│  · 路由执行：_react_chat_generator() → ReActLoop.run()              │
│  · HTTP 路由：GET /artifacts/{session_id}/{filename}                │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │ 调用
┌───────────────────────────────────┼─────────────────────────────────┐
│  Skill 框架                                                        │
│  · ToolRegistry.execute_tool(tool_name, session_id=..., **kwargs)  │
│  · ReActLoop.run(session_id=...) 透传 session_id                   │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
┌───────────────────────────────────▼─────────────────────────────────┐
│  code_executor                                                     │
│  · workspace = runtime/artifacts/{session_id}/                     │
│  · 在 workspace 内写脚本、执行代码                                  │
│  · 执行后扫描新增文件 → 生成 files[]                                │
│  · 返回 {success, stdout, stderr, files:[{name,url,mime,size}]      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 后台改造清单

### 3.1 新增产物管理模块 `src/runtime/artifacts.py`

唯一落盘入口，避免 `code_executor` 与 `file_manager` 重复实现。

```python
from pathlib import Path
import mimetypes, hashlib, time
from typing import List, Dict, Any

ARTIFACT_ROOT = Path(__file__).resolve().parent.parent.parent / "runtime" / "artifacts"

def workspace(session_id: str) -> Path:
    """按会话隔离的工作目录"""
    path = ARTIFACT_ROOT / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path

def snapshot(dir_path: Path) -> Dict[str, tuple]:
    """目录文件指纹快照 {relative_path: (mtime_ns, size)}"""
    result = {}
    if not dir_path.exists():
        return result
    for p in dir_path.rglob("*"):
        if p.is_file():
            rel = p.relative_to(dir_path).as_posix()
            if rel.startswith(".") or "__pycache__" in rel.split("/"):
                continue
            result[rel] = (p.stat().st_mtime_ns, p.stat().st_size)
    return result

def scan_new_files(session_id: str, before: Dict[str, tuple]) -> List[Dict[str, Any]]:
    """扫描会话工作区新增/变更文件"""
    ws = workspace(session_id)
    after = snapshot(ws)
    files = []
    for rel, sig in after.items():
        if before.get(rel) == sig:
            continue
        p = ws / rel
        mime, _ = mimetypes.guess_type(str(p))
        files.append({
            "name": p.name,
            "rel_path": rel,
            "mime": mime or "application/octet-stream",
            "size": p.stat().st_size,
            "url": f"/artifacts/{session_id}/{rel}",
        })
    return files

def safe_resolve(session_id: str, filename: str) -> Path:
    """安全解析文件路径，防目录穿越"""
    base = workspace(session_id).resolve()
    target = (base / filename).resolve()
    target.relative_to(base)  # 越界抛 ValueError
    return target
```

### 3.2 改造 `skills/code_executor/execute.py`

1. `execute(*args, **kwargs)` 增加读取 `session_id`（从 kwargs 取）。
2. 不再使用 `tempfile.NamedTemporaryFile`，改为：
   - `ws = artifacts.workspace(session_id)`
   - 把脚本写到 `ws / "__script__.py"`
   - `subprocess.Popen(["python3", str(script_path)], cwd=str(ws), ...)`
3. 执行前 `before = artifacts.snapshot(ws)`，执行后 `files = artifacts.scan_new_files(session_id, before)`。
4. 清理 `__script__.py`（可选）和临时目录，但保留产物文件。
5. 返回结构扩展：

```python
return {
    "success": returncode == 0,
    "stdout": stdout,
    "stderr": stderr,
    "returncode": returncode,
    "timed_out": timed_out,
    "files": files,          # 新增
}
```

**注意**：`FORBIDDEN_MODULES` 黑名单保持不变，`matplotlib` 等库的内部 `import os/sys` 不会被静态拦截（只检查用户代码字符串），不影响画图。

### 3.3 把 `session_id` 传到工具执行层

当前链路中 `session_id` 在 `_react_chat_generator` 手里，但 `ReActLoop.run()` 和 `ToolRegistry.execute_tool()` 没有该参数。需要改三处：

1. **`src/skill/registry.py` `execute_tool`**

```python
async def execute_tool(self, tool_name: str, session_id: str = "", **kwargs) -> ToolResult:
    ...
    raw_result = await fn(session_id=session_id, **kwargs)
    # 同步技能
    raw_result = await asyncio.to_thread(fn, session_id=session_id, **kwargs)
```

2. **`src/agent/loop.py` `ReActLoop.run`**

```python
async def run(
    self,
    messages: List[Dict],
    agent_id: str = "dfecrab",
    session_id: str = "",      # 新增
    ...
):
```

在工具调用处：

```python
tool_result = await self.tool_registry.execute_tool(tc_name, session_id=session_id, **arguments)
```

3. **`src/gateway/grpc_server.py` `_react_chat_generator`**

两处 `react_loop.run(...)` 都增加 `session_id=session_id`。

### 3.4 网关新增 HTTP 产物路由

在 `src/gateway/http/server.py` 的 `HTTPServer.__init__` 中注册：

```python
self.add_route(HTTPMethod.GET, "/artifacts/{session_id}/{filename}",
               self._serve_artifact, required_level="read")
```

实现：

```python
async def _serve_artifact(self, request, session_id: str, filename: str):
    from src.runtime import artifacts
    try:
        path = artifacts.safe_resolve(session_id, filename)
        if not path.is_file():
            return HTTPResponse(404).text("file not found")
        data = path.read_bytes()
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"
        resp = HTTPResponse(200)
        resp.headers["Content-Type"] = mime
        if mime.startswith("image/") or mime == "text/html":
            resp.headers["Content-Disposition"] = "inline"
        else:
            resp.headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
        resp.body = data
        return resp
    except (ValueError, FileNotFoundError):
        return HTTPResponse(404).text("file not found")
    except Exception as e:
        logger.error(f"artifact serve error: {e}")
        return HTTPResponse(500).text("internal error")
```

### 3.5 改造事件透传，把 `artifacts` 塞进 `tool_result`

在 `src/gateway/grpc_server.py` 的 `_react_chat_generator()` `tool_result` 分支（约 L2842），读取 `result.content.files` 并写入事件：

```python
elif event_type == "tool_result":
    result = event_data.get("result", {})
    content = result.get("content", {}) if isinstance(result, dict) else {}
    artifact_files = content.get("files", []) if isinstance(content, dict) else []

    _status = "done"
    _summary = ""
    if isinstance(result, dict):
        _status = result.get("status", "unknown")
        _inner = result.get("content", {})
        if isinstance(_inner, dict):
            _summary = _inner.get("stdout", "") or _inner.get("stderr", "")
        if not _summary:
            _summary = result.get("error", "") or ""
    _summary = str(_summary).strip()[:200]
    _content = f"技能执行完成: {_status}"
    if _summary:
        _content += f" | {_summary}"

    yield {
        "type": mapped_type,
        "data": {
            "tool_name": event_data.get("tool_name", ""),
            "result": result,
            "success": event_data.get("success", True),
            "tool_call_id": event_data.get("tool_call_id", ""),
            "iteration": event_data.get("iteration", 0),
            "elapsed_ms": event_data.get("elapsed_ms", 0),
            "corrected": event_data.get("corrected", False),
            "content": _content,
            "agent_id": agent_id,
            "artifacts": artifact_files,        # 新增：产物列表
        }
    }
```

> 协议约定：前端在 `tool_result.data.artifacts` 中取文件列表。

### 3.6 MCP 工具展示（可选增强）

现状：`tool_call` 事件已经带 `tool_name`、`arguments`。对于 MCP 工具，如果需要前端显示"来自哪个 MCP 服务"，可在 `src/agent/loop.py` 的 `TOOL_CALL` 事件里增加 `server_name`。

实现：在 `ToolRegistry` 的 `_discover_mcp_tools()` 中 `ToolInfo` 已记录 `server_name`，`execute_tool` 处可通过 `tool_info.server_name` 获取。但展示参数/运行特效不需要 server_name，所以本次可不做。

---

## 4. 前端协议约定（给前端人员）

### 4.1 入口

- WebSocket：`{type:"chat_stream", data:{message:"...", session_id:"...", agent_id:"code_writer"}}`
- HTTP SSE：`POST /api/v2/chat/stream`（与现有接口一致）

### 4.2 相关事件

| event_type | 用途 | 前端表现 |
|---|---|---|
| `meta` | 会话元信息，含 `session_id` | 记录当前会话 ID |
| `tool_call` | LLM 决定调用工具 | 展开工具条，显示 `tool_name` + `arguments` |
| `tool_start` | 工具开始执行 | 给该工具条加波动/转圈动画 |
| `tool_result` | 工具执行完成 | 停止动画；显示结果摘要；读取 `artifacts` 列表 |
| `message_end` | 最终回复 | 显示 LLM 总结文本 |

### 4.3 产物 URL 规则

相对路径：

```
/artifacts/{session_id}/{filename}
```

前端拼接：

```js
const base = `${window.location.protocol}//${window.location.hostname}:6789`; // HTTP 端口
const url = `${base}/artifacts/${session_id}/${encodeURIComponent(filename)}`;
```

> 注意：WS 端口是 `6790`，HTTP 端口是 `6789`，产物走 HTTP 下载。

### 4.4 `tool_result.data.artifacts` 字段

```json
[
  {
    "name": "chart.png",
    "rel_path": "chart.png",
    "mime": "image/png",
    "size": 15234,
    "url": "/artifacts/sid_xxx/chart.png"
  },
  {
    "name": "output.csv",
    "rel_path": "output.csv",
    "mime": "text/csv",
    "size": 890,
    "url": "/artifacts/sid_xxx/output.csv"
  }
]
```

前端渲染建议：

- `image/*`：右侧预览面板内嵌 `<img src={url} />`
- `text/plain`、`text/csv`、`application/json`：可预览文本或提供下载
- 其他：提供下载链接

### 4.5 代码沙箱卡片

用 `tool_result.data.result` 中的字段：

```json
{
  "stdout": "...",
  "stderr": "...",
  "returncode": 0,
  "files": [...]
}
```

- 正常：`stdout` 显示为运行结果
- 报错：`stderr` 标红显示，`returncode != 0` 为失败

---

## 5. 文件改动汇总

| 文件 | 改动点 |
|---|---|
| 新增 `src/runtime/artifacts.py` | 产物目录、快照、扫描、安全路径解析 |
| `skills/code_executor/execute.py` | 改为 workspace 执行、扫描产物、返回 files |
| `src/skill/registry.py` `execute_tool` | 增加 `session_id` 参数并透传给 execute_fn |
| `src/agent/loop.py` `ReActLoop.run` | 增加 `session_id` 参数，透传给 execute_tool |
| `src/gateway/grpc_server.py` `_react_chat_generator` | 传入 `session_id`；`tool_result` 事件补 `artifacts` |
| `src/gateway/http/server.py` | 注册 `/artifacts/{session_id}/{filename}` 路由并提供文件 |
| `前端对接文档/` | 新增一篇《产物与工具调用事件协议.md》（由后端人员交付前端） |

---

## 6. 实施顺序建议

1. **先做 `src/runtime/artifacts.py` + `code_executor` 改造**：让 skill 单独跑起来就能落盘。
2. **再做 `registry.py` / `loop.py` / `grpc_server.py` 的 session_id 透传**：让完整链路能拿到会话 ID。
3. **然后加 HTTP `/artifacts` 路由**：让前端能下载。
4. **最后补 `tool_result.artifacts` 和前端协议文档**。

---

## 7. 顺带处理的代码质量问题

1. **`config/mcporter.json` 编码损坏**：`alert_judge_tools` 下 description 出现乱码（如 `æ¥è¯¢ç«ç¹...`），建议从 `mcp_servers/mcp_alert_judge.py` 的 tools 定义重新生成 tool_cache。
2. **落盘逻辑统一**：`file_manager` 与 `code_executor` 不要各自实现目录/文件操作，统一使用 `src/runtime/artifacts.py`。
3. **`blackxml-topology-mcp` 双通道问题**：该 MCP 自带 `public/app.js` 独立页面（旁路 8602），与网关 artifact 预览是两套展示通道。后续可让它生成 SVG 后同样落盘走 `/artifacts`，前端统一组件。

---

## 8. 验收标准

- [ ] `POST /api/v2/chat/stream` 用 `agent_id=code_writer` 发送 `"用 matplotlib 画正弦曲线并保存为 sin.png"`
- [ ] 响应事件流中出现 `tool_result`，且 `data.artifacts` 包含 `{"name":"sin.png","url":"/artifacts/{sid}/sin.png"}`
- [ ] 浏览器访问 `http://host:6789/artifacts/{sid}/sin.png` 能直接看到图片
- [ ] 生成 CSV/TXT 文件时返回 `application/octet-stream` 并带 `Content-Disposition: attachment`
- [ ] 代码报错时 `stderr` 正常返回，前端能显示错误信息
