# 📄 Word 文档读取功能

## ✅ 功能已实现

小蟹 (DFEcrab) 现在支持读取**Word 文档 (.docx 格式)**!

### 🎯 功能特性

1. ✅ **支持 .docx 格式** - 现代 Word 文档格式
2. ✅ **提取文本内容** - 完整提取文档文字
3. ✅ **保留段落结构** - 按段落组织内容
4. ✅ **统计信息** - 字数、段落数等
5. ✅ **错误处理** - 友好的错误提示

### 📋 使用方法

#### 方法 1: 在智能体中使用工具

```python
# 调用 word_read 工具
result = await tools.word_read(
    file_path="/path/to/document.docx"
)

if result['success']:
    print(f"标题：{result['title']}")
    print(f"字数：{result['word_count']}")
    print(f"内容：{result['content']}")
else:
    print(f"读取失败：{result['error']}")
```

#### 方法 2: 直接使用 API

```python
from src.utils.word_reader import read_word

result = read_word("/path/to/document.docx")

if result['success']:
    print(f"内容：{result['content']}")
```

###  参数说明

**word_read(file_path)**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file_path` | str | ✅ | Word 文档路径 |

**返回值:**
```python
{
    "success": True,           # 是否成功
    "content": "文档内容...",   # 完整文本内容
    "title": "文档标题",        # 文档标题
    "word_count": 4480,        # 字数统计
    "paragraphs": [...],       # 段落列表
    "page_count": 3,           # 估计页数
    "message": "成功读取..."    # 成功消息
}
```

### 🌰 实际示例

**用户:** 读取"/Users/zhanghanzhi/武林秘籍/2.项目文档/08-ai/麒麟系统安装及环境部署.docx"

**智能体:** (自动调用 `word_read` 工具)

**智能体:** 
```
已成功读取文档《一、麒麟操作系统安装》

📊 文档信息:
- 字数：4480 字
- 段落：142 段
- 页数：约 3 页

📝 内容摘要:
一、麒麟操作系统安装
注：需准备一个 U 盘，且刻录会将 U 盘格式化，注意备份 U 盘中重要数据

1. 下载 iso 镜像文件到本地
2. 解压 ultraISO 文件夹到本地
3. 打开 ultraISO.exe 文件
4. 进入 ultraISO 后，左上角文件选择需要刻录的 ISO 镜像文件
5. 将 U 盘插入主机，开机，按 F12，选择 U 盘作为启动盘
...
```

### 🔧 技术实现

**文件结构:**
```
src/
├── utils/
│   └── word_reader.py         # Word 文档读取器
└── plugins/
    └── builtin/
        └── builtin_tools_plugin/
            └── __init__.py     # 工具注册
```

**核心功能:**
- `read_docx()` - 读取 .docx 文件
- `read_doc()` - 读取 .doc 文件 (需要 antiword)
- `read_word()` - 自动识别格式

**依赖:**
- `python-docx` - Word 文档处理
- `antiword` - .doc 格式支持 (可选)

### 📝 支持的格式

✅ **原生支持:**
- `.docx` - Word 2007+ 文档

⚠️ **需要额外工具:**
- `.doc` - Word 97-2003 文档
  - 安装：`brew install antiword`

❌ **不支持:**
- `.pdf` - PDF 文档
- `.wps` - WPS 文档
- `.rtf` - RTF 文档

### ⚠️ 注意事项

1. **文件路径**: 必须是绝对路径或相对于项目根目录的路径
2. **文件格式**: 推荐使用 .docx 格式
3. **内容限制**: 只能读取文本，无法获取:
   - 图片
   - 表格格式
   - 样式信息
   - 批注/修订
4. **编码**: 自动处理编码，无需手动指定
5. **权限**: 需要有文件读取权限

### 🐛 错误处理

**常见错误:**

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| "文件不存在" | 路径错误 | 检查文件路径是否正确 |
| "不支持的文件格式" | 非 docx 文件 | 转换为 .docx 格式 |
| "缺少依赖" | 未安装 python-docx | `pip install python-docx` |
| "读取失败" | 文件损坏或加密 | 检查文件完整性 |

### 💡 使用技巧

**技巧 1: 获取文档统计**

```python
result = tools.word_read("/path/to/document.docx")

if result['success']:
    print(f"字数：{result['word_count']}")
    print(f"段落数：{len(result['paragraphs'])}")
    print(f"页数：~{result['page_count']}")
```

**技巧 2: 分段处理**

```python
result = tools.word_read("/path/to/document.docx")

if result['success']:
    for i, para in enumerate(result['paragraphs'][:10]):
        print(f"段落{i+1}: {para[:100]}...")
```

**技巧 3: 内容搜索**

```python
result = tools.word_read("/path/to/document.docx")

if result['success']:
    content = result['content']
    
    # 搜索关键词
    if "麒麟" in content:
        print("文档包含'麒麟'相关内容")
    
    # 统计词频
    print(f"'安装'出现次数：{content.count('安装')}")
```

### 📊 测试结果

**测试文件:** `/Users/zhanghanzhi/武林秘籍/2.项目文档/08-ai/麒麟系统安装及环境部署.docx`

**测试结果:**
```
成功：True
标题：一、麒麟操作系统安装
字数：4480
段落数：142

内容预览:
一、麒麟操作系统安装
注：需准备一个 U 盘，且刻录会将 U 盘格式化，注意备份 U 盘中重要数据
下载 iso 镜像文件到本地，解压 ultraISO 文件夹...
```

---

**现在小蟹可以读取 Word 文档了!** 🎉

**快速开始:**
```python
from src.utils.word_reader import read_word

result = read_word("/path/to/document.docx")
print(result['content'])
```

**或在智能体中:**
```python
result = await tools.word_read(file_path="/path/to/document.docx")
```
