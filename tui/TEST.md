# DFEcrab 自动化测试

## 测试脚本

### 完整测试
```bash
npm test
```
- 自动启动 Gateway
- 测试 HTTP 连接
- 测试 WebSocket 连接和消息收发
- 自动停止 Gateway

### 简单 WebSocket 测试
```bash
npm run test:ws
```
- 仅测试 WebSocket 连接（需要 Gateway 已运行）

## 测试结果

### ✅ 通过的测试
- Gateway 启动
- HTTP API: `http://localhost:6789`
- WebSocket 连接：`ws://localhost:6789/ws`
- CLI 注册协议

### ⚠️ 已知问题
1. **CLI 连接失败**: Gateway 内部的 CLI 客户端连接时使用 `extra_headers` 参数与新版 websockets 库不兼容
   - 不影响 TUI 使用
   - 修复方法：更新 `src/cli/runner.py` 中的 WebSocket 连接代码

2. **AI 回复未收到**: 因为没有配置 Agent 后端（如 Ollama）
   - 正常现象
   - 需要配置 LLM 后端才能收到 AI 回复

## 手动测试 Gateway

```bash
# 1. 启动 Gateway
cd /Users/zhanghanzhi/DFEcrab--
source venv/bin/activate
./dfecrab start

# 2. 在另一个终端测试 WebSocket
cd /Users/zhanghanzhi/DFEcrab--/tui
node -e "
import WebSocket from 'ws';
const ws = new WebSocket('ws://localhost:6789/ws');
ws.on('open', () => {
  ws.send(JSON.stringify({
    type: 'register',
    cli_id: 'manual-test',
    agent_id: 'default'
  }));
});
ws.on('message', (d) => console.log('收到:', d.toString()));
"
```

## TUI 运行

```bash
# 需要先启动 Gateway
cd /Users/zhanghanzhi/DFEcrab--/tui
npm start
```

注意：Ink TUI 需要在真实终端运行（不支持后台执行）
