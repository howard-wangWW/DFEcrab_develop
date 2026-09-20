---
name: excel-read
description: MUST be used when user asks to "read Excel", "open Excel file", "view xlsx", "读取 Excel". This is the primary skill for handling Excel files.
---

# Excel Read

Read Excel (.xlsx, .xls) files using Python openpyxl.

## IMPORTANT: You MUST Use This Skill

When user asks to:
- "read Excel file"
- "open/read xlsx"
- "view Excel content"
- "读取 Excel 文件"

You MUST call: `skill_excel-read_execute(file_path="...")`

## Parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| file_path | string | Yes | Full path to Excel file |
| sheet_name | string | No | Sheet name (default: first sheet) |
| max_rows | integer | No | Max rows to read (default: 100) |

## Examples

```python
# Read a file
skill_excel-read_execute(file_path="/Users/zhanghanzhi/test.xlsx")

# Read specific sheet
skill_excel-read_execute(file_path="/Users/zhanghanzhi/test.xlsx", sheet_name="Sheet2")
```

## Requirements

```bash
pip install openpyxl
```
