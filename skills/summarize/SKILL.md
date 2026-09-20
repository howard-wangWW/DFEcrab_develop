---
name: summarize
description: 当用户请求总结URL、视频、音频或本地文件内容时使用。如"总结这个链接"、"这是什么视频"、"提取YouTube字幕"、或"帮我总结这篇文章"。支持网页、PDF、YouTube视频、播客等。
---

# Summarize 技能

快速总结网页、视频、音频和本地文件内容。

## 使用场景

当用户说：
- "总结这个链接/文章/视频"
- "这是什么内容？"
- "提取这个视频的字幕"
- "帮我总结一下这个文件"
- "这个YouTube视频讲了什么？"

## 使用方式

### 网页总结
```bash
summarize "https://example.com"
```

### YouTube 视频
```bash
summarize "https://youtu.be/xxxxx"
summarize "https://youtube.com/watch?v=xxxxx" --youtube auto
```

### 本地文件
```bash
summarize "/path/to/file.pdf"
summarize "/path/to/file.txt"
```

### 仅提取字幕/文本
```bash
summarize "https://youtu.be/xxxxx" --youtube auto --extract-only
```

## 常用参数

- `--length short|medium|long` - 总结长度
- `--extract-only` - 仅提取原始内容，不总结
- `--json` - JSON 格式输出
- `--firecrawl auto|off|always` - 网站抓取模式

## 安装

如果 summarize 命令不可用，使用 pip 安装：
```bash
pip install summarize-cli
# 或
brew install summarize  # macOS
```

## 注意事项

- YouTube 字幕提取需要网络连接
- PDF 总结效果取决于 PDF 内容结构
- 如果总结结果不满意，可以指定 `--length long` 获取更详细内容
