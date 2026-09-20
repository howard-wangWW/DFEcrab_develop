# DFEcrab TUI 风格改造方案

**版本**：v4.5.0  
**创建日期**：2026-03-30  
**参考**：CodeBuddy CLI / QwenCode CLI 极简风格

---

## 1. 目标界面设计

```
┌─────────────────────────────────────────────────────────┐
│  🦀 DFEcrab v3.6.0     │  Tips                        │
│                        │  / for commands, @ for files │
│    ┌─┐  ┌─┐  ┌─┐      │  Ctrl+V to paste paths       │
│    │DF│  │EC│  │RAB│  │  Esc twice to reset input    │
│    └─┘  └─┘  └─┘      ├──────────────────────────────┤
│                        │  Session: default            │
│                        │  Agent: default              │
│                        │  Model: qwen-max             │
│                        ├──────────────────────────────┤
│                        │  Status: 🟢 Connected        │
│                        │  Tokens: 1,234 · $0.0012     │
│                        │  /Users/zhanghanzhi/DFEcrab  │
├─────────────────────────────────────────────────────────┤
│  🦀 你好！我是 DFEcrab，你的智能编程助手。              │
│                                                         │
│  我可以帮你：                                           │
│  • 编写和调试代码                                       │
│  • 解释复杂概念                                         │
│  • 管理项目记忆                                         │
│  • 执行系统命令                                         │
│                                                         │
│  输入 /help 查看可用命令，或直接开始提问。              │
├─────────────────────────────────────────────────────────┤
│  🦀 你：█                                               │
├─────────────────────────────────────────────────────────┤
│  /help 帮助 │ /clear 清屏 │ /status 状态 │ ? 快捷键    │
└─────────────────────────────────────────────────────────┘
```

---

## 2. 核心特性

### 2.1 视觉风格

| 元素 | CodeBuddy | DFEcrab |
|------|-----------|---------|
| **主色调** | 青绿色 (#4FD1C5) | 蟹壳红 (#E53E3E) |
| **Logo** | 像素风机器人 | 像素风螃蟹 |
| **提示符** | `> ` | `🦀 你：` |
| **分隔线** | 细线 | 细线 |
| **字体** | 等宽字体 | 等宽字体 |

### 2.2 布局结构

```
Header (状态栏)
├── Logo + 版本
├── Tips (快捷键提示)
├── Session 信息
└── 状态信息

Content (聊天内容)
├── 欢迎消息
├── 功能介绍
└── 使用提示

Input (输入区域)
└── 提示符 + 输入框

Footer (底部栏)
└── 常用命令快捷提示
```

### 2.3 快捷键设计

| 快捷键 | 功能 | 来源 |
|--------|------|------|
| `/` | 打开命令面板 | CodeBuddy |
| `@` | 提及文件 | CodeBuddy |
| `Ctrl+V` | 粘贴路径/URL | CodeBuddy |
| `Esc×2` | 重置输入框 | CodeBuddy |
| `?` | 显示快捷键 | CodeBuddy |
| `Ctrl+C` | 中断当前操作 | 通用 |
| `Ctrl+Q` | 退出 | 通用 |

---

## 3. 实施计划

### 3.1 阶段划分

| 阶段 | 任务 | 版本 | 工作量 |
|------|------|------|--------|
| 阶段 1 | ASCII Logo 设计 | v4.5.0 | 0.5 天 |
| 阶段 2 | 状态栏重构 | v4.5.0 | 1 天 |
| 阶段 3 | 输入区优化 | v4.5.0 | 1 天 |
| 阶段 4 | 快捷键系统 | v4.5.0 | 1 天 |
| 阶段 5 | 主题配色 | v4.5.0 | 0.5 天 |

### 3.2 文件变更

**新增文件**：
```
src/core/tui/
├── styles/
│   ├── theme.py          # 主题配色
│   └── ascii_art.py      # ASCII Logo
├── widgets/
│   ├── header.py         # 状态栏
│   ├── input_box.py      # 输入框
│   └── footer.py         # 底部栏
└── keybindings.py        # 快捷键绑定
```

**修改文件**：
```
src/core/tui/tui_remote.py   # 重构为主界面
```

---

## 4. 代码实现

### 4.1 ASCII Logo

```python
# src/core/tui/styles/ascii_art.py

DFECRAB_LOGO = """
    ┌─┐  ┌─┐  ┌─┐
    │DF│  │EC│  │RAB│
    └─┘  └─┘  └─┘
"""

# 或者像素风螃蟹
CRAB_LOGO = """
    🦀🦀
   🦀🦀🦀
    🦀🦀
"""
```

### 4.2 状态栏组件

```python
# src/core/tui/widgets/header.py

from prompt_toolkit.formatted_text import FormattedText

class Header:
    """状态栏组件"""
    
    def __init__(self):
        self.version = "3.6.0"
        self.session_id = "default"
        self.agent_id = "default"
        self.model = "qwen-max"
        self.token_count = 0
        self.cost = 0.0
    
    def render(self) -> FormattedText:
        """渲染状态栏"""
        return FormattedText([
            ("class:title", f" 🦀 DFEcrab v{self.version} "),
            ("class:separator", " │ "),
            ("class:tips", " Tips "),
            ("class:text", " / for commands, @ for files "),
            ("class:separator", " │ "),
            ("class:session", f" Session: {self.session_id} "),
            ("class:agent", f" Agent: {self.agent_id} "),
            ("class:model", f" Model: {self.model} "),
        ])
```

### 4.3 输入框组件

```python
# src/core/tui/widgets/input_box.py

from prompt_toolkit.widgets import TextArea
from prompt_toolkit.buffer import Buffer

class InputBox:
    """输入框组件"""
    
    def __init__(self):
        self.buffer = Buffer(
            multiline=False,
            on_submit=self.on_submit
        )
        
        self.text_area = TextArea(
            buffer=self.buffer,
            prompt="🦀 你：",
            style="class:input"
        )
    
    def on_submit(self, buffer):
        """用户提交输入"""
        text = buffer.text.strip()
        if text:
            # 处理输入
            self.handle_input(text)
            buffer.text = ""  # 清空输入框
    
    def handle_input(self, text: str):
        """处理用户输入"""
        # 发送到 Gateway 处理
        pass
```

### 4.4 快捷键绑定

```python
# src/core/tui/keybindings.py

from prompt_toolkit.key_binding import KeyBindings

def create_keybindings():
    """创建快捷键绑定"""
    kb = KeyBindings()
    
    @kb.add('/')
    def show_commands(event):
        """显示命令面板"""
        # 打开命令选择器
        pass
    
    @kb.add('@')
    def mention_file(event):
        """提及文件"""
        # 打开文件选择器
        pass
    
    @kb.add('c-v')
    def paste_path(event):
        """粘贴路径"""
        # 从剪贴板粘贴路径
        pass
    
    @kb.add('escape', 'escape')
    def reset_input(event):
        """重置输入框"""
        event.app.current_buffer.text = ""
    
    @kb.add('?')
    def show_shortcuts(event):
        """显示快捷键"""
        # 显示快捷键帮助
        pass
    
    return kb
```

### 4.5 主题配色

```python
# src/core/tui/styles/theme.py

from prompt_toolkit.styles import Style

DFECRAB_THEME = Style.from_dict({
    # 顶部状态栏
    'title': 'bg:#E53E3E #ffffff bold',
    'separator': 'bg:#E53E3E #ffffff',
    'tips': 'bg:#E53E3E #ffffff italic',
    'session': 'bg:#C53030 #ffffff',
    'agent': 'bg:#C53030 #ffffff',
    'model': 'bg:#C53030 #ffffff',
    
    # 聊天内容
    'chat.user': 'bg:#2D3748 #ffffff',
    'chat.assistant': 'bg:#1A202C #E53E3E',
    'chat.system': 'bg:#1A202C #A0AEC0 italic',
    
    # 输入框
    'input': 'bg:#1A202C #ffffff',
    'input.prompt': 'bg:#1A202C #E53E3E bold',
    
    # 底部栏
    'footer': 'bg:#2D3748 #A0AEC0',
    'footer.shortcut': 'bg:#2D3748 #E53E3E bold',
    
    # 滚动条
    'scrollbar.background': 'bg:#1A202C',
    'scrollbar.button': 'bg:#E53E3E',
    'scrollbar.arrow': 'bg:#E53E3E #ffffff',
})
```

---

## 5. 完整示例

```python
# src/core/tui/app.py

from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, Window
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.formatted_text import FormattedText

from .styles.theme import DFECRAB_THEME
from .styles.ascii_art import DFECRAB_LOGO
from .keybindings import create_keybindings

class DFECrabTUI:
    """DFEcrab TUI 应用"""
    
    def __init__(self):
        # 状态栏
        self.header = Window(
            content=FormattedTextControl(
                text=self.render_header
            ),
            height=5
        )
        
        # 聊天内容区
        self.chat_buffer = TextArea(
            text=self.render_welcome(),
            read_only=True,
            style="class:chat"
        )
        
        # 输入框
        self.input_box = TextArea(
            prompt="🦀 你：",
            multiline=False,
            on_submit=self.on_submit
        )
        
        # 底部栏
        self.footer = Window(
            content=FormattedTextControl(
                text=" /help 帮助 │ /clear 清屏 │ /status 状态 │ ? 快捷键 "
            ),
            height=1,
            style="class:footer"
        )
        
        # 布局
        self.layout = Layout(
            HSplit([
                self.header,
                self.chat_buffer,
                self.input_box,
                self.footer
            ])
        )
        
        # 应用
        self.app = Application(
            layout=self.layout,
            key_bindings=create_keybindings(),
            style=DFECRAB_THEME,
            full_screen=True
        )
    
    def render_header(self):
        """渲染状态栏"""
        return FormattedText([
            ("class:title", f" 🦀 DFEcrab v3.6.0 "),
            ("class:separator", " │ "),
            ("class:tips", " Tips "),
            ("class:text", " / for commands, @ for files "),
        ])
    
    def render_welcome(self):
        """渲染欢迎消息"""
        return f"""
{DFECRAB_LOGO}
🦀 你好！我是 DFEcrab，你的智能编程助手。

我可以帮你：
• 编写和调试代码
• 解释复杂概念
• 管理项目记忆
• 执行系统命令

输入 /help 查看可用命令，或直接开始提问。
"""
    
    def on_submit(self, buffer):
        """处理用户输入"""
        text = buffer.text.strip()
        if text:
            # 添加到聊天历史
            self.add_to_chat(f"🦀 你：{text}", "user")
            
            # 发送到 Gateway 处理
            # ... 处理逻辑
            
            # 清空输入框
            buffer.text = ""
    
    def add_to_chat(self, text: str, role: str):
        """添加到聊天历史"""
        current = self.chat_buffer.text
        self.chat_buffer.text = current + f"\n{text}\n"
    
    def run(self):
        """运行 TUI"""
        self.app.run()


if __name__ == "__main__":
    tui = DFECrabTUI()
    tui.run()
```

---

## 6. 对比效果

### 改造前（当前）

```
╔══════════════════════════════════════════════════════════╗
║  🦀 DFEcrab v3 - 远程 TUI 客户端                          ║
║  连接到：http://localhost:6789                             ║
╚══════════════════════════════════════════════════════════╝

  版本：v3.5.0  │  Agent: 1  │  技能：14  │  WebSocket: 🟢

[聊天内容...]

👤 你：[输入框]

[q/quit] 退出 │ [/help] 帮助 │ [/status] 状态
```

### 改造后（参考 CodeBuddy）

```
┌─────────────────────────────────────────────────────────┐
│  🦀 DFEcrab v3.6.0     │  Tips                        │
│                        │  / for commands, @ for files │
│    ┌─┐  ┌─┐  ┌─┐      │  Ctrl+V to paste paths       │
│    │DF│  │EC│  │RAB│  │  Esc twice to reset input    │
│    └─┘  └─┘  └─┘      ├──────────────────────────────┤
│                        │  Session: default            │
│                        │  Agent: default              │
│                        │  Model: qwen-max             │
│                        ├──────────────────────────────┤
│                        │  Status: 🟢 Connected        │
│                        │  Tokens: 1,234 · $0.0012     │
├─────────────────────────────────────────────────────────┤
│  🦀 你好！我是 DFEcrab...                               │
│                                                         │
│  [聊天内容...]                                          │
├─────────────────────────────────────────────────────────┤
│  🦀 你：█                                               │
├─────────────────────────────────────────────────────────┤
│  /help 帮助 │ /clear 清屏 │ /status 状态 │ ? 快捷键    │
└─────────────────────────────────────────────────────────┘
```

---

## 7. 实施建议

### 优先级

1. **高优先级** - 输入框优化（提示符 + 快捷键）
2. **中优先级** - 状态栏重构
3. **低优先级** - ASCII Logo

### 技术选型

| 方案 | 优点 | 缺点 |
|------|------|------|
| **prompt_toolkit** | 现有框架，易迁移 | 样式定制有限 |
| **textual** | 现代化，样式丰富 | 需要重写 |
| **rich** | 简单快速 | 交互能力弱 |

**推荐**：继续使用 `prompt_toolkit`， incremental 改进

---

**文档版本**：1.0  
**创建时间**：2026-03-30  
**审阅状态**：待审阅
