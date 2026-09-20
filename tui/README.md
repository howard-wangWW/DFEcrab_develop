# DFEcrab TUI (Ink + TypeScript)

基于 Ink (React) 的现代化终端 UI，使用 TypeScript 编写，参考 Claude Code 和 Qwen Code 的实现。

## 技术栈

- **Ink** - React for Terminal
- **React** - UI 框架
- **TypeScript** - 类型安全
- **ws** - WebSocket 客户端

## 安装

```bash
cd tui
npm install
```

## 开发

```bash
# 编译 TypeScript
npm run build

# 监听模式
npm run dev
```

## 运行

```bash
# 本地模式（连接本地 Gateway）
npm start

# 远程模式（连接远程 Gateway）
npm start -- --host 192.168.1.100 --port 6789
```

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Enter` | 发送消息 |
| `↑` / `↓` | 浏览历史记录 |
| `Ctrl+C` | 清空输入 |
| `Ctrl+Q` | 退出应用 |

## 项目结构

```
tui/
├── src/
│   ├── cli.tsx             # 主入口
│   ├── websocket.ts        # WebSocket 客户端
│   ├── types.ts            # 类型定义
│   └── components/
│       ├── InputPrompt.tsx # 输入组件
│       ├── MessageList.tsx # 消息列表
│       └── StatusBar.tsx   # 状态栏
├── dist/                   # 编译输出
├── package.json
├── tsconfig.json
└── README.md
```

## 类型定义

```typescript
interface Message {
  type: 'user' | 'assistant' | 'system' | 'error';
  content: string;
  timestamp?: number;
}
```

## 参考

- [Ink GitHub](https://github.com/vadimdemedes/ink)
- [Claude Code](https://github.com/anthropics/claude-code)
- [Qwen Code](https://github.com/QwenLM/qwen-code)
