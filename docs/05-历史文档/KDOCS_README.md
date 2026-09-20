# 📄 金山文档读取功能

## ✅ 功能已实现

小蟹 (DFEcrab) 现在支持读取**金山文档 (WPS Docs)** 在线文档!

### 🎯 功能特性

1. ✅ **支持公开文档** - 无需密码的金山文档分享链接
2. ✅ **支持密码文档** - 可提供访问密码
3. ✅ **多种文档类型** - 支持文档、表格、演示
4. ✅ **自动解析** - 自动提取文档内容和标题
5. ✅ **URL 验证** - 自动验证链接格式

### 📋 使用方法

#### 方法 1: 在智能体中使用工具

```python
# 调用 kdocs_read 工具
result = await tools.kdocs_read(
    url="https://kdocs.cn/l/xxxxx"
)

if result['success']:
    print(f"文档标题：{result['title']}")
    print(f"文档类型：{result['type']}")
    print(f"文档内容：{result['content']}")
else:
    print(f"读取失败：{result['error']}")
```

#### 方法 2: 直接使用 API

```python
from src.utils.kdocs_reader import kdocs_read

# 读取公开文档
result = kdocs_read("https://kdocs.cn/l/xxxxx")

# 读取需要密码的文档
result = kdocs_read(
    url="https://kdocs.cn/l/xxxxx",
    password="1234"
)
```

### 📖 参数说明

**kdocs_read(url, password=None)**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | str | ✅ | 金山文档分享链接 |
| `password` | str | ❌ | 文档访问密码 |

**返回值:**
```python
{
    "success": True,          # 是否成功
    "content": "文档内容...",  # 文档文本内容
    "title": "文档标题",       # 文档标题
    "type": "doc",            # 文档类型：doc, sheet, presentation
    "message": "成功读取文档"   # 成功消息
}
```

### 🌰 使用示例

#### 示例 1: 读取公开文档

```python
result = kdocs_read("https://kdocs.cn/l/abc123xyz")

if result['success']:
    print(f"标题：{result['title']}")
    print(f"内容预览：{result['content'][:100]}...")
```

#### 示例 2: 读取加密文档

```python
result = kdocs_read(
    url="https://kdocs.cn/l/abc123xyz",
    password="secret"
)

if result['success']:
    print(f"内容：{result['content']}")
else:
    print(f"失败：{result['error']}")
```

#### 示例 3: 在智能体对话中

**用户:** 帮我读取这个金山文档 https://kdocs.cn/l/xxxxx

**智能体:** (自动调用 kdocs_read 工具)

**智能体:** 已读取文档《项目计划》，主要内容如下:
- 项目目标...
- 时间安排...
- 人员分工...

### 🔧 技术实现

**文件结构:**
```
src/
├── utils/
│   └── kdocs_reader.py      # 金山文档读取器
└── plugins/
    └── builtin/
        └── builtin_tools_plugin/
            └── __init__.py   # 工具注册
```

**核心类:**
- `KDocsReader` - 异步读取器
- `kdocs_read()` - 同步便捷函数

**依赖:**
- `httpx` - HTTP 客户端
- `beautifulsoup4` - HTML 解析
- `asyncio` - 异步支持

### 📝 支持的链接格式

✅ **有效格式:**
- `https://kdocs.cn/l/xxxxx`
- `https://www.kdocs.cn/l/xxxxx`
- `https://kdocs.cn/office/s/xxxxx`

❌ **无效格式:**
- 非 kdocs.cn 域名
- 不包含 `/l/` 路径

### ⚠️ 注意事项

1. **公开访问**: 文档必须设置为"公开"或"指定人可见"
2. **访问密码**: 如果文档需要密码，必须提供
3. **内容限制**: 只能读取文本内容，无法获取格式、图片等
4. **网络依赖**: 需要网络连接才能访问
5. **权限限制**: 只能访问有权限查看的文档

### 🐛 错误处理

**常见错误:**

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| "无效的金山文档链接" | URL 格式错误 | 检查链接是否正确 |
| "文档需要访问密码" | 文档需要密码 | 提供 password 参数 |
| "HTTP 错误：404" | 文档不存在 | 检查链接是否有效 |
| "读取超时" | 网络问题 | 检查网络连接 |
| "读取失败" | 其他错误 | 查看错误详情 |

### 💡 使用技巧

**技巧 1: 验证链接**

```python
from src.utils.kdocs_reader import KDocsReader

reader = KDocsReader()
is_valid = reader._validate_url("https://kdocs.cn/l/xxxxx")
print(f"链接有效：{is_valid}")
```

**技巧 2: 批量读取**

```python
urls = [
    "https://kdocs.cn/l/doc1",
    "https://kdocs.cn/l/doc2",
    "https://kdocs.cn/l/doc3"
]

for url in urls:
    result = kdocs_read(url)
    if result['success']:
        print(f"{result['title']}: {len(result['content'])} 字")
```

**技巧 3: 内容处理**

```python
result = kdocs_read("https://kdocs.cn/l/xxxxx")

if result['success']:
    content = result['content']
    
    # 统计字数
    print(f"字数：{len(content)}")
    
    # 提取关键词
    # ... 使用 NLP 处理
```

---

**现在可以使用小蟹读取金山文档了!** 🎉

**示例:**
```python
from src.utils.kdocs_reader import kdocs_read

result = kdocs_read("https://kdocs.cn/l/你的文档链接")
print(result['content'])
```
