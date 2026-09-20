# DFEcrab TUI 系统重构技术方案

**版本**：v3.10.0  
**创建日期**：2026-03-30  
**参考架构**：OpenClaw / Qwen Code TUI  
**目标**：重构 TUI 系统，实现现代化终端用户界面

---

## 📋 目录

1. [现状分析](#1-现状分析)
2. [竞品对比](#2-竞品对比)
3. [目标架构](#3-目标架构)
4. [重构方案](#4-重构方案)
5. [实施计划](#5-实施计划)
6. [风险评估](#6-风险评估)

---

## 1. 现状分析

### 1.1 当前 TUI 架构

```
DFEcrab TUI (v3.5.0)
├── src/core/tui/
│   ├── __init__.py
│   ├── tui_remote.py      # 远程 TUI 客户端（1259 行）
│   └── tui_layout.py      # Layout 版本（203 行）
└── 依赖：prompt_toolkit>=3.0.0
```

### 1.2 核心问题

| 问题 | 描述 | 影响 |
|------|------|------|
| **架构混乱** | `tui_remote.py` 1259 行，单文件过大 | 难以维护，难以测试 |
| **功能缺失** | 无代码高亮、无 Markdown 渲染、无进度条 | 用户体验差 |
| **无状态栏** | 状态栏信息简陋，无实时 Token 统计 | 用户感知弱 |
| **无快捷键系统** | 硬编码快捷键，不可配置 | 交互效率低 |
| **无主题支持** | 固定颜色，无主题切换 | 视觉体验差 |
| **流式输出不完整** | 流式接收但显示不流畅 | 首字延迟感知高 |
| **无输入历史** | 无命令历史记录功能 | 重复输入困难 |
| **无自动补全** | 无命令/路径/技能补全 | 输入效率低 |

### 1.3 技术债务

```python
# 问题 1: WebSocket 和 HTTP 客户端混在一起
class DFECrabTUIRemote:
    def __init__(self):
        self.client: Optional[RemoteGatewayClient] = None      # HTTP
        self.ws_client: Optional[WebSocketClient] = None       # WebSocket
        # 职责不清

# 问题 2: 命令处理硬编码
self._commands: Dict[str, Callable] = {
    self.CMD_HELP: self._print_help,
    self.CMD_CLEAR: self._clear_screen,
    # 扩展困难
}

# 问题 3: 异步处理不规范
asyncio.create_task(self._async_print_status())  # 无错误处理
```

---

## 2. 竞品对比

### 2.1 OpenClaw TUI

**架构特点**：
```
OpenClaw TUI
├── pi-tui/                    # 极简 TUI 框架
│   ├── renderer.py            # 差异化渲染
│   ├── components/            # UI 组件
│   └── theme.py               # 主题系统
└── 依赖：textual / rich
```

**核心优势**：
- ✅ 极简设计（<500 行核心代码）
- ✅ 差异化渲染（只更新变化部分）
- ✅ 组件化（Header/Footer/Chat/Input 独立）
- ✅ 主题系统（支持亮/暗/自定义）
- ✅ Markdown 渲染
- ✅ 代码高亮（Pygments）

### 2.2 Qwen Code TUI

**架构特点**：
```
Qwen Code TUI
├── textual 框架
├── 完整的事件系统
├── 组件树结构
└── 响应式布局
```

**核心优势**：
- ✅ 基于 Textual（现代 TUI 框架）
- ✅ 完整组件系统
- ✅ CSS 样式支持
- ✅ 响应式布局
- ✅ 实时 Token 统计
- ✅ 进度条/Spinner
- ✅ 完整的快捷键系统
- ✅ 输入历史/自动补全

### 2.3 差距对比

| 功能 | DFEcrab | OpenClaw | Qwen Code | 差距 |
|------|---------|----------|-----------|------|
| 框架 | prompt_toolkit | 自研 (pi-tui) | Textual | 🔴 大 |
| 代码行数 | 1259 | <500 | ~800 | 🟡 中 |
| Markdown 渲染 | ❌ | ✅ | ✅ | 🔴 大 |
| 代码高亮 | ❌ | ✅ | ✅ | 🔴 大 |
| 主题系统 | ❌ | ✅ | ✅ | 🔴 大 |
| 快捷键系统 | ❌ | ✅ | ✅ | 🔴 大 |
| 自动补全 | ❌ | ✅ | ✅ | 🔴 大 |
| 输入历史 | ❌ | ✅ | ✅ | 🔴 大 |
| Token 统计 | ❌ | ✅ | ✅ | 🔴 大 |
| 进度条 | ❌ | ✅ | ✅ | 🔴 大 |
| 响应式布局 | ❌ | ✅ | ✅ | 🔴 大 |

---

## 3. 目标架构

### 3.1 技术选型

**推荐方案：Textual**

理由：
1. ✅ 现代化 TUI 框架（基于 Rich）
2. ✅ 完整组件系统
3. ✅ CSS 样式支持
4. ✅ 响应式布局
5. ✅ 活跃维护（2026 年仍在更新）
6. ✅ 与 OpenClaw/Qwen Code 对齐

**备选方案：prompt_toolkit + Rich**

理由：
1. ✅ 保持现有技术栈
2. ✅ Rich 提供 Markdown/代码高亮
3. ⚠️ 需要自行实现组件系统

### 3.2 目标架构

```
DFEcrab TUI V4 (Textual)
├── src/core/tui/
│   ├── __init__.py
│   ├── app.py                 # TUI 应用主类
│   ├── components/            # UI 组件
│   │   ├── __init__.py
│   │   ├── header.py          # 顶部状态栏
│   │   ├── footer.py          # 底部快捷键
│   │   ├── chat_display.py    # 聊天显示
│   │   ├── input_area.py      # 输入区域
│   │   ├── sidebar.py         # 侧边栏
│   │   └── token_bar.py       # Token 统计栏
│   ├── screens/               # 屏幕
│   │   ├── __init__.py
│   │   ├── main.py            # 主聊天屏
│   │   ├── help.py            # 帮助屏
│   │   ├── settings.py        # 设置屏
│   │   └── agent_manager.py   # Agent 管理屏
│   ├── widgets/               # 可复用小组件
│   │   ├── __init__.py
│   │   ├── markdown.py        # Markdown 渲染
│   │   ├── code_block.py      # 代码块高亮
│   │   ├── progress.py        # 进度条
│   │   └── spinner.py         # 加载动画
│   ├── themes/                # 主题
│   │   ├── __init__.py
│   │   ├── dark.tcss          # 暗色主题
│   │   ├── light.tcss         # 亮色主题
│   │   └── monokai.tcss       # Monokai 主题
│   └── utils/                 # 工具类
│       ├── __init__.py
│       ├── syntax_highlight.py # 语法高亮
│       └── markdown_renderer.py # Markdown 渲染
```

### 3.3 组件设计

#### 3.3.1 主应用

```python
# src/core/tui/app.py
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer
from textual.containers import Container

from .components.chat_display import ChatDisplay
from .components.input_area import InputArea
from .components.sidebar import SideBar
from .components.token_bar import TokenBar

class DFECrabTUI(App):
    """DFEcrab TUI 应用"""
    
    CSS_PATH = "themes/default.tcss"
    
    BINDINGS = [
        ("ctrl+q", "quit", "退出"),
        ("ctrl+h", "show_help", "帮助"),
        ("ctrl+s", "show_settings", "设置"),
        ("ctrl+a", "toggle_sidebar", "侧边栏"),
        ("ctrl+n", "new_chat", "新对话"),
        ("ctrl+p", "command_palette", "命令面板"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SideBar(id="sidebar")
        with Container(id="main-container"):
            yield ChatDisplay(id="chat-display")
            yield InputArea(id="input-area")
        yield TokenBar(id="token-bar")
        yield Footer()
    
    def on_mount(self) -> None:
        """应用挂载时"""
        self.title = "DFEcrab"
        self.sub_title = "v4.0.0"
```

#### 3.3.2 聊天显示组件

```python
# src/core/tui/components/chat_display.py
from textual.widget import Widget
from textual.reactive import reactive
from rich.markdown import Markdown
from rich.syntax import Syntax

class ChatDisplay(Widget):
    """聊天显示组件"""
    
    # 响应式属性
    messages = reactive([])
    streaming_content = reactive("")
    is_streaming = reactive(False)
    
    def render(self) -> RenderableType:
        """渲染聊天内容"""
        content = []
        
        # 历史消息
        for msg in self.messages:
            if msg["role"] == "user":
                content.append(Panel(msg["content"], title="👤 你", style="blue"))
            else:
                # Markdown 渲染
                md = Markdown(msg["content"])
                content.append(md)
        
        # 流式输出中
        if self.is_streaming and self.streaming_content:
            content.append(
                Panel(self.streaming_content, title="🦀 AI", style="green")
            )
        
        return Group(*content)
    
    def watch_messages(self, new_messages: list) -> None:
        """消息变化时自动滚动到底部"""
        self.scroll_end(animate=False)
    
    def append_message(self, role: str, content: str) -> None:
        """添加消息"""
        self.messages.append({"role": role, "content": content})
    
    def start_streaming(self) -> None:
        """开始流式输出"""
        self.is_streaming = True
        self.streaming_content = ""
    
    def append_stream(self, chunk: str) -> None:
        """追加流式内容"""
        self.streaming_content += chunk
        self.scroll_end(animate=True)
    
    def end_streaming(self) -> None:
        """结束流式输出"""
        self.is_streaming = False
        # 将流式内容转为正式消息
        self.messages.append({"role": "assistant", "content": self.streaming_content})
```

#### 3.3.3 输入区域组件

```python
# src/core/tui/components/input_area.py
from textual.widget import Widget
from textual.widgets import TextArea
from textual.binding import Binding
from textual.autocomplete import Autocomplete, Completion

class InputArea(Widget):
    """输入区域组件"""
    
    BINDINGS = [
        Binding("enter", "send", "发送", show=True),
        Binding("alt+enter", "newline", "换行", show=True),
        Binding("ctrl+up", "history_prev", "上一条历史"),
        Binding("ctrl+down", "history_next", "下一条历史"),
    ]
    
    def compose(self) -> ComposeResult:
        yield TextArea(id="input-textarea")
        yield Autocomplete(
            suggestions=self._get_suggestions,
            target=self.query_one("#input-textarea", TextArea)
        )
    
    def action_send(self) -> None:
        """发送消息"""
        text = self.query_one("#input-textarea", TextArea).text
        if text.strip():
            self.post_message(InputArea.Submitted(text))
            self.query_one("#input-textarea", TextArea).text = ""
            self._add_history(text)
    
    def action_newline(self) -> None:
        """换行"""
        self.query_one("#input-textarea", TextArea).insert("\n")
    
    def _get_suggestions(self, prefix: str) -> list[Completion]:
        """获取自动补全建议"""
        suggestions = []
        
        # 命令补全
        if prefix.startswith("/"):
            commands = ["/help", "/status", "/agents", "/skills", "/memory", "/plan"]
            for cmd in commands:
                if cmd.startswith(prefix):
                    suggestions.append(Completion(cmd))
        
        # 文件路径补全
        if prefix.startswith("~/") or prefix.startswith("/"):
            # 文件系统补全
            ...
        
        # 技能补全
        if prefix.startswith("@"):
            # 技能列表补全
            ...
        
        return suggestions
    
    class Submitted(Message):
        """输入提交消息"""
        def __init__(self, text: str):
            super().__init__()
            self.text = text
```

#### 3.3.4 Token 统计栏

```python
# src/core/tui/components/token_bar.py
from textual.widget import Widget
from textual.reactive import reactive

class TokenBar(Widget):
    """Token 统计栏"""
    
    # 响应式属性
    total_tokens = reactive(0)
    prompt_tokens = reactive(0)
    completion_tokens = reactive(0)
    cost = reactive(0.0)
    
    def render(self) -> RenderableType:
        """渲染 Token 栏"""
        return (
            f"💰 Token: {self.total_tokens:,} "
            f"(提示：{self.prompt_tokens:,} | 完成：{self.completion_tokens:,}) "
            f"│ 费用：¥{self.cost:.4f}"
        )
    
    def update_tokens(self, total: int, prompt: int, completion: int, cost: float) -> None:
        """更新 Token 统计"""
        self.total_tokens = total
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.cost = cost
```

#### 3.3.5 侧边栏组件

```python
# src/core/tui/components/sidebar.py
from textual.widget import Widget
from textual.widgets import Static, Button
from textual.binding import Binding

class SideBar(Widget):
    """侧边栏组件"""
    
    BINDINGS = [
        Binding("escape", "close", "关闭"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Static("📚 会话历史", id="sessions-title")
        yield Static("", id="sessions-list")
        
        yield Static("🤖 Agent", id="agent-title")
        yield Static("default", id="current-agent")
        
        yield Static("🔧 技能", id="skills-title")
        yield Static("", id="skills-list")
        
        yield Button("新对话", id="new-chat-btn")
        yield Button("导出对话", id="export-btn")
    
    def on_mount(self) -> None:
        """挂载时加载数据"""
        self._load_sessions()
        self._load_agent()
        self._load_skills()
    
    def action_close(self) -> None:
        """关闭侧边栏"""
        self.display = False
```

### 3.4 主题系统

```css
/* src/core/tui/themes/dark.tcss */

/* 全局样式 */
Screen {
    background: #1a1a2e;
    color: #eaeaea;
}

/* 头部 */
Header {
    background: #16213e;
    color: #00d9ff;
}

/* 聊天显示 */
#chat-display {
    background: #1a1a2e;
    color: #eaeaea;
}

/* 用户消息 */
.user-message {
    background: #0f3460;
    color: #ffffff;
}

/* AI 消息 */
.assistant-message {
    background: #1a1a2e;
    color: #00d9ff;
}

/* 输入区域 */
#input-area {
    background: #16213e;
    color: #ffffff;
}

/* Token 栏 */
#token-bar {
    background: #0f3460;
    color: #00d9ff;
}

/* 按钮 */
Button {
    background: #e94560;
    color: #ffffff;
}

Button:hover {
    background: #ff6b6b;
}

/* 滚动条 */
ScrollBar {
    background: #16213e;
    color: #0f3460;
}

ScrollBarCorner {
    background: #16213e;
}
```

---

## 4. 重构方案

### 4.1 阶段划分

| 阶段 | 任务 | 版本 | 工作量 |
|------|------|------|--------|
| 阶段 1 | Textual 框架集成 | v3.10.0 | 2 天 |
| 阶段 2 | 核心组件实现 | v3.11.0 | 3 天 |
| 阶段 3 | 功能增强 | v3.12.0 | 2 天 |
| 阶段 4 | 主题和配置 | v3.13.0 | 1 天 |
| 阶段 5 | 测试和文档 | v3.14.0 | 2 天 |

### 4.2 阶段 1: Textual 框架集成（2 天）

#### Day 1: 环境准备

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 安装 Textual 依赖 | `requirements.txt` 更新 |
| 10:00-12:00 | 创建基础应用结构 | `tui/app.py` |
| 13:00-15:00 | 实现 Hello World | 可运行的 TUI |
| 15:00-17:00 | 迁移 WebSocket 客户端 | `tui/utils/ws_client.py` |
| 17:00-18:00 | 迁移 HTTP 客户端 | `tui/utils/http_client.py` |

**代码示例**：
```python
# requirements.txt
textual>=0.47.0
rich>=13.0.0
```

```python
# src/core/tui/app.py
from textual.app import App

class DFECrabTUI(App):
    """DFEcrab TUI 应用"""
    
    async def on_mount(self) -> None:
        self.title = "DFEcrab"
        self.sub_title = "v4.0.0"

if __name__ == "__main__":
    app = DFECrabTUI()
    app.run()
```

#### Day 2: 基础布局

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 实现 Header/Footer | `components/header.py` |
| 10:00-12:00 | 实现主容器布局 | `containers.py` |
| 13:00-15:00 | 实现简单输入框 | `components/input.py` |
| 15:00-17:00 | 实现简单显示区 | `components/display.py` |
| 17:00-18:00 | 集成测试 | 可运行的基础 TUI |

### 4.3 阶段 2: 核心组件实现（3 天）

#### Day 3: 聊天显示组件

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 实现消息列表渲染 | `components/chat_display.py` |
| 10:00-12:00 | 集成 Markdown 渲染 | `widgets/markdown.py` |
| 13:00-15:00 | 集成代码高亮 | `widgets/code_block.py` |
| 15:00-17:00 | 实现流式输出 | `components/chat_display.py` |
| 17:00-18:00 | 自动滚动优化 | 流畅的滚动体验 |

#### Day 4: 输入区域组件

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 实现多行输入 | `components/input_area.py` |
| 10:00-12:00 | 实现命令补全 | `autocomplete.py` |
| 13:00-15:00 | 实现输入历史 | `history.py` |
| 15:00-17:00 | 实现快捷键绑定 | `bindings.py` |
| 17:00-18:00 | 集成测试 | 完整的输入体验 |

#### Day 5: 状态栏和 Token 统计

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 实现状态栏 | `components/status_bar.py` |
| 10:00-12:00 | 实现 Token 统计 | `components/token_bar.py` |
| 13:00-15:00 | 集成 Gateway API | `utils/token_tracker.py` |
| 15:00-17:00 | 实时更新优化 | 实时 Token 显示 |
| 17:00-18:00 | 集成测试 | 完整的状态显示 |

### 4.4 阶段 3: 功能增强（2 天）

#### Day 6: 侧边栏和会话管理

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 实现侧边栏 | `components/sidebar.py` |
| 10:00-12:00 | 实现会话列表 | `screens/sessions.py` |
| 13:00-15:00 | 实现 Agent 切换 | `screens/agent_manager.py` |
| 15:00-17:00 | 实现技能列表 | `screens/skills.py` |
| 17:00-18:00 | 集成测试 | 完整的侧边栏功能 |

#### Day 7: 命令面板和帮助系统

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 实现命令面板 | `widgets/command_palette.py` |
| 10:00-12:00 | 实现帮助屏 | `screens/help.py` |
| 13:00-15:00 | 实现设置屏 | `screens/settings.py` |
| 15:00-17:00 | 实现进度条/Spinner | `widgets/progress.py` |
| 17:00-18:00 | 集成测试 | 完整的帮助系统 |

### 4.5 阶段 4: 主题和配置（1 天）

#### Day 8: 主题系统

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 实现暗色主题 | `themes/dark.tcss` |
| 10:00-12:00 | 实现亮色主题 | `themes/light.tcss` |
| 13:00-15:00 | 实现主题切换 | `utils/theme_manager.py` |
| 15:00-17:00 | 实现配置系统 | `config/tui_config.py` |
| 17:00-18:00 | 集成测试 | 主题切换正常 |

### 4.6 阶段 5: 测试和文档（2 天）

#### Day 9: 测试

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 编写单元测试 | `tests/tui/test_components.py` |
| 10:00-12:00 | 编写集成测试 | `tests/tui/test_app.py` |
| 13:00-15:00 | 性能测试 | 性能报告 |
| 15:00-17:00 | Bug 修复 | 稳定的 TUI |
| 17:00-18:00 | 回归测试 | 所有测试通过 |

#### Day 10: 文档和发布

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 编写用户文档 | `docs/tui/user_guide.md` |
| 10:00-12:00 | 编写开发文档 | `docs/tui/dev_guide.md` |
| 13:00-15:00 | 更新 README | README.md |
| 15:00-17:00 | 发布准备 | CHANGELOG + 发布说明 |
| 17:00-18:00 | 正式发布 | v3.14.0 |

---

## 5. 实施计划

### 5.1 时间线

```
Week 1:  阶段 1-2（框架集成 + 核心组件）→ v3.11.0
Week 2:  阶段 3-4（功能增强 + 主题配置）→ v3.13.0
Week 3:  阶段 5（测试文档）→ v3.14.0
```

### 5.2 里程碑

| 里程碑 | 版本 | 日期 | 交付物 |
|--------|------|------|--------|
| M1: Textual 框架集成 | v3.10.0 | Week 1 Day 2 | 可运行的基础 TUI |
| M2: 核心组件完成 | v3.11.0 | Week 1 Day 5 | 聊天/输入/状态栏 |
| M3: 功能增强完成 | v3.12.0 | Week 2 Day 7 | 侧边栏/命令面板 |
| M4: 主题配置完成 | v3.13.0 | Week 2 Day 8 | 主题切换 |
| M5: 测试文档完成 | v3.14.0 | Week 3 Day 10 | 正式发布 |

### 5.3 成功指标

- [ ] ✅ Markdown 渲染正常
- [ ] ✅ 代码高亮正常
- [ ] ✅ 流式输出流畅（首字<100ms）
- [ ] ✅ Token 统计实时显示
- [ ] ✅ 快捷键系统工作
- [ ] ✅ 主题切换正常
- [ ] ✅ 自动补全工作
- [ ] ✅ 输入历史工作
- [ ] ✅ 测试覆盖率>80%
- [ ] ✅ 所有现有功能正常

---

## 6. 风险评估

### 6.1 技术风险

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|----------|
| Textual 学习曲线 | 中 | 中 | 提前学习，参考官方文档 |
| 性能问题 | 低 | 中 | 性能测试，优化渲染 |
| 兼容性问题 | 低 | 高 | 保留旧 TUI，渐进迁移 |
| 依赖冲突 | 低 | 中 | 虚拟环境，锁定版本 |

### 6.2 组织风险

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|----------|
| 开发延期 | 中 | 中 | 按天细分任务 |
| 需求变更 | 低 | 高 | 冻结需求，分阶段实施 |
| 人员变动 | 低 | 高 | 文档完善，知识共享 |

---

## 7. 附录

### 7.1 文件变更清单

**新增文件**：
```
src/core/tui/
├── app.py
├── components/
│   ├── header.py
│   ├── footer.py
│   ├── chat_display.py
│   ├── input_area.py
│   ├── sidebar.py
│   └── token_bar.py
├── screens/
│   ├── main.py
│   ├── help.py
│   ├── settings.py
│   └── agent_manager.py
├── widgets/
│   ├── markdown.py
│   ├── code_block.py
│   ├── progress.py
│   └── spinner.py
├── themes/
│   ├── dark.tcss
│   ├── light.tcss
│   └── monokai.tcss
└── utils/
    ├── ws_client.py
    ├── http_client.py
    ├── token_tracker.py
    └── theme_manager.py
```

**废弃文件**：
```
src/core/tui/tui_remote.py      # 迁移后废弃
src/core/tui/tui_layout.py      # 迁移后废弃
```

### 7.2 依赖变更

```diff
# requirements.txt
- prompt_toolkit>=3.0.0
+ textual>=0.47.0
+ rich>=13.0.0
```

### 7.3 迁移指南

**从旧 TUI 迁移**：
1. 备份现有配置
2. 安装新依赖：`pip install textual rich`
3. 运行新 TUI：`./dfecrab tui --new`
4. 测试现有功能
5. 反馈问题

---

**文档版本**：1.0  
**创建时间**：2026-03-30  
**审阅状态**：待审阅
