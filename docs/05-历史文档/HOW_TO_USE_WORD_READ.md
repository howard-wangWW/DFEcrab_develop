# 📖 如何在小蟹中使用 Word 文档读取功能

## ⚠️ 重要说明

虽然我们已经在代码层面添加了 `word_read` 工具，但是**AI 智能体在对话中还不能自动调用它**。这是因为:

1. 工具已注册到插件系统 ✅
2. 但 AI 智能体需要特殊配置才能看到和调用这些工具 ⏳

## ✅ 当前可用的使用方式

### 方式 1: 通过 Python 代码直接调用

```python
from src.utils.word_reader import read_word

result = read_word("/Users/zhanghanzhi/武林秘籍/2.项目文档/08-ai/麒麟系统安装及环境部署.docx")

if result['success']:
    print(f"标题：{result['title']}")
    print(f"字数：{result['word_count']}")
    print(f"内容：{result['content']}")
```

### 方式 2: 使用插件 API

```python
from src.plugins.builtin.builtin_tools_plugin import BuiltinToolsPlugin

plugin = BuiltinToolsPlugin()
result = plugin.word_read("/path/to/document.docx")

print(result['content'])
```

### 方式 3: 创建自定义技能 (推荐)

创建一个技能文件，让 AI 可以调用:

**文件:** `skills/read_word_doc.py`

```python
"""
读取 Word 文档技能
"""

from src.utils.word_reader import read_word

def execute(file_path: str) -> dict:
    """
    读取 Word 文档并返回内容
    
    Args:
        file_path: Word 文档路径
        
    Returns:
        读取结果
    """
    result = read_word(file_path)
    
    if result['success']:
        return {
            "success": True,
            "content": result['content'],
            "title": result['title'],
            "word_count": result['word_count'],
            "summary": f"文档《{result['title']}》共{result['word_count']}字"
        }
    else:
        return {
            "success": False,
            "error": result['error']
        }
```

然后在对话中:
```
执行技能 read_word_doc，文件路径：/Users/zhanghanzhi/武林秘籍/2.项目文档/08-ai/麒麟系统安装及环境部署.docx
```

## 🔧 让 AI 自动调用工具的配置方法

要让 AI 在对话中自动调用 `word_read` 工具，需要:

### 1. 配置 Agent 使用插件工具

编辑 Agent 配置文件，添加:

```json
{
  "agent_id": "default",
  "tools": [
    "builtin_tools:word_read",
    "builtin_tools:file_read",
    "builtin_tools:kdocs_read"
  ]
}
```

### 2. 使用 Tool Calling 框架

如果使用 Agentscope，需要配置:

```python
from agentscope.agent import Agent

agent = Agent(
    name="assistant",
    tools=["word_read", "file_read", "kdocs_read"]
)
```

### 3. 添加 System Prompt

在 AI 的 system prompt 中添加:

```
你可以使用以下工具:
- word_read: 读取 Word 文档 (.docx 格式)
- file_read: 读取文本文件
- kdocs_read: 读取金山文档

当用户要求读取文件时，使用相应的工具。
```

## 📝 快速测试

**使用 Python 直接测试:**

```bash
cd /Users/zhanghanzhi/DFEcrab
python3 -c "
from src.utils.word_reader import read_word
result = read_word('/Users/zhanghanzhi/武林秘籍/2.项目文档/08-ai/麒麟系统安装及环境部署.docx')
print(f'标题：{result[\"title\"]}')
print(f'字数：{result[\"word_count\"]}')
print(f'内容预览：{result[\"content\"][:200]}...')
"
```

## 💡 建议

### 当前阶段

使用 **方式 1** 或 **方式 2** 直接通过 Python 代码调用:

```python
from src.utils.word_reader import read_word

file_path = "/Users/zhanghanzhi/武林秘籍/2.项目文档/08-ai/麒麟系统安装及环境部署.docx"
result = read_word(file_path)

if result['success']:
    # 处理文档内容
    print(result['content'])
```

### 未来集成

如果你希望 AI 在对话中自动调用这些工具，需要:

1. 修改 Agent 配置
2. 添加工具描述到 System Prompt
3. 可能需要使用 Agentscope 的 Tool Calling 功能

## 🎯 总结

**当前状态:**
- ✅ 工具已实现并可用
- ✅ 可以通过 Python 代码调用
- ✅ 插件已加载到 Gateway
- ⏳ AI 对话中还不能自动调用 (需要额外配置)

**推荐用法:**
```python
from src.utils.word_reader import read_word
result = read_word("/path/to/document.docx")
```

---

**需要帮助配置 AI 自动调用吗？** 

我可以帮你:
1. 创建自定义技能文件
2. 配置 Agent 使用工具
3. 添加 System Prompt 说明

请告诉我你的需求！
