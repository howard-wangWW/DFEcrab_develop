# PDF to Knowledge Base Skill

将 PDF 文档内容保存为 DFEcrab 的知识库（记忆系统）。

## 功能

- 读取 PDF 文件内容
- 自动提取文档结构和关键信息
- 保存到共享记忆或指定智能体的记忆中

## 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file_path | string | 是 | PDF 文件路径 |
| title | string | 否 | 文档标题（默认从文件名提取） |
| agent_id | string | 否 | 目标智能体 ID（默认保存到共享记忆） |
| memory_type | string | 否 | 记忆类型：daily/long_term（默认 long_term） |
| pages | array | 否 | 指定保存的页码（默认全部） |

## 示例

```
# 保存到共享记忆
/skill pdf-to-kb file_path="/path/to/document.pdf"

# 保存到特定智能体的记忆
/skill pdf-to-kb file_path="/path/to/document.pdf" agent_id="default"

# 只保存指定页面
/skill pdf-to-kb file_path="/path/to/document.pdf" pages=[1,2,3,4,5]
```

## 保存位置

- 共享记忆：`data/shared_memory/MEMORY.md`
- 智能体记忆：`agents/{agent_id}/MEMORY.md`

## 返回格式

```json
{
  "status": "SUCCESS",
  "content": {
    "title": "文档标题",
    "total_pages": 39,
    "saved_pages": 39,
    "saved_to": "data/shared_memory/MEMORY.md",
    "char_count": 20704
  }
}
```
