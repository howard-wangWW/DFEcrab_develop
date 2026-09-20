# PDF Reader

读取 PDF 文件，提取文本内容。

## 功能

- 提取 PDF 全文文本
- 提取指定页码的文本
- 提取指定区域的文本
- 同时提取图片（可选）

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file_path | string | 是 | PDF 文件路径 |
| pages | array | 否 | 指定页码列表（从 1 开始） |
| start_page | integer | 否 | 起始页码 |
| end_page | integer | 否 | 结束页码 |
| extract_images | boolean | 否 | 是否提取图片（默认 false） |
| output_dir | string | 否 | 图片输出目录 |

## 示例

```
# 读取全文
/skill pdf-reader file_path="/path/to/document.pdf"

# 读取指定页
/skill pdf-reader file_path="/path/to/document.pdf" pages=[1,2,3]

# 读取页码范围
/skill pdf-reader file_path="/path/to/document.pdf" start_page=1 end_page=10

# 同时提取图片
/skill pdf-reader file_path="/path/to/document.pdf" extract_images=true output_dir="./images"
```

## 返回格式

```json
{
  "status": "SUCCESS",
  "content": {
    "total_pages": 100,
    "extracted_pages": 10,
    "text": "全文文本内容...",
    "pages": [
      {"page_number": 1, "text": "...", "char_count": 1000},
      ...
    ],
    "images": [
      {"page": 1, "index": 0, "path": "/path/to/image.png"},
      ...
    ]
  }
}
```
