---
name: nano-pdf
description: 当用户需要编辑PDF文件时使用，如"修改PDF的标题"、"编辑PDF内容"、"给PDF添加文字"、"合并PDF"、"拆分PDF"、"压缩PDF"等。nano-pdf使用自然语言指令来编辑PDF。
---

# nano-pdf 技能

使用自然语言指令编辑 PDF 文件。

## 使用场景

当用户说：
- "帮我修改这个PDF"
- "编辑PDF的标题"
- "从这个PDF中提取文字"
- "合并这两个PDF"
- "压缩这个PDF"
- "给PDF添加水印"

## 使用方式

### 编辑 PDF 内容
```bash
nano-pdf edit document.pdf 1 "将标题改为 'Q3 报告'"
```

### 提取 PDF 文本
```bash
nano-pdf extract document.pdf
```

### 合并 PDF
```bash
nano-pdf merge file1.pdf file2.pdf --out merged.pdf
```

### 压缩 PDF
```bash
nano-pdf compress document.pdf --out compressed.pdf
```

## 常用命令

| 命令 | 功能 |
|------|------|
| `nano-pdf edit <file> <page> <instruction>` | 编辑指定页面 |
| `nano-pdf extract <file>` | 提取文本 |
| `nano-pdf merge <files...>` | 合并多个 PDF |
| `nano-pdf split <file>` | 拆分 PDF |
| `nano-pdf compress <file>` | 压缩 PDF |

## 安装

如果 nano-pdf 命令不可用，使用 pip 安装：
```bash
pip install nano-pdf
# 或
uv pip install nano-pdf
```

## 注意事项

- 页码从 1 开始
- 编辑前建议备份原文件
- 复杂编辑可能需要多次尝试
