# DFEcrab 技能使用指南

## 📚 技能概述

DFEcrab 的技能（Skills）是一种可扩展的能力模块，智能体可以调用这些技能来完成任务。

### 当前可用技能

| 技能名称 | 功能说明 | 状态 |
|----------|----------|------|
| `planner` | 任务复杂度检测和执行计划生成 | ✅ 已实现 |
| `project_memory` | 分层记忆管理（保存/读取/搜索） | ✅ 已实现 |
| `memory_maintenance` | 记忆维护（每周/每月汇总） | ✅ 已实现 |
| `list_dir` | 列出目录文件和子目录 | ✅ 已实现 |
| `file_read` | 读取文本文件内容 | ✅ 已实现 |
| `word_read` | 读取 Word 文档 (.docx) | ✅ 已实现 |
| `kdocs_read` | 读取金山文档在线内容 | ✅ 已实现 |

---

## 🚀 快速开始

### 方式1：通过对话调用

在 TUI 或 API 对话中，直接描述你的需求：

```
帮我读取 /path/to/file.txt
```

AI 会自动选择合适的技能来执行。

### 方式2：显式调用技能

```
请调用 file_read 技能读取文件：/path/to/file.txt
```

---

## 📋 技能详细说明

### 1. planner - 任务规划

分析任务复杂度，生成执行计划。

**使用场景：**
- 复杂任务需要分步骤执行
- 不确定如何开始一个任务
- 需要了解任务执行流程

**调用示例：**
```
请调用 planner 技能分析：帮我部署一个 Docker 应用
```

**输出示例：**
```
## 任务分析

**复杂度等级**: MEDIUM

## 执行计划

### 步骤 1: 环境检查
- **描述**: 检查服务器环境和 Docker 依赖
- **使用工具**: [shell_command]

### 步骤 2: 准备配置文件
- **描述**: 创建 docker-compose.yml
- **使用工具**: [file_write]

...
```

---

### 2. project_memory - 项目记忆

管理项目相关的长期记忆，支持分层存储。

**操作类型：**

| 操作 | 说明 | 示例 |
|------|------|------|
| `save` | 保存记忆 | 保存工作进度、项目背景等 |
| `load` | 读取记忆 | 查看所有项目记忆 |
| `list` | 查看统计 | 查看记忆数量统计 |
| `search` | 搜索记忆 | 按关键词搜索 |
| `stats` | 查看状态 | 查看记忆系统状态 |

**记忆分类：**

| 分类 | 说明 | 场景 |
|------|------|------|
| `general` | 通用信息 | 一般记录 |
| `background` | 项目背景 | 项目背景信息 |
| `progress` | 工作进度 | 完成的功能 |
| `decision` | 技术决策 | 架构选择、方案确定 |
| `file_location` | 文件位置 | 重要文件路径 |
| `todo` | 待办事项 | 待完成的任务 |

**调用示例：**
```
# 保存记忆
请调用 project_memory 技能保存：完成了分层记忆系统，分类：progress

# 读取记忆
请调用 project_memory 技能读取所有项目记忆

# 查看统计
请调用 project_memory 技能查看统计

# 搜索记忆
请调用 project_memory 技能搜索：记忆系统
```

---

### 3. memory_maintenance - 记忆维护

执行记忆汇总和维护任务。

**操作类型：**

| 操作 | 说明 | 触发方式 |
|------|------|----------|
| `weekly` | 执行每周汇总 | 每周日23:59自动 / 手动 |
| `monthly` | 执行每月汇总 | 每月28-31日23:59自动 / 手动 |
| `extract` | 提取长期记忆 | 每月汇总后自动 |
| `all` | 执行所有维护 | 手动触发 |

**调用示例：**
```
# 执行每周汇总
请调用 memory_maintenance 技能执行每周汇总

# 执行所有维护
请调用 memory_maintenance 技能执行所有维护任务
```

---

### 4. list_dir - 目录列表

列出目录下的文件和子目录。

**参数：**

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `dir_path` | string | 目录路径 | 必填 |
| `pattern` | string | 文件匹配模式 | `*` |
| `recursive` | boolean | 是否递归子目录 | `false` |

**调用示例：**
```
# 列出目录
请调用 list_dir 技能列出目录：/Users/zhanghanzhi/DFEcrab/src

# 递归列出
请调用 list_dir 技能列出目录：/Users/zhanghanzhi/DFEcrab/src，递归：是

# 只看 Python 文件
请调用 list_dir 技能列出目录：/path/to/dir，模式：*.py
```

---

### 5. file_read - 文件读取

读取文本文件内容。

**参数：**

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `file_path` | string | 文件路径 | 必填 |
| `encoding` | string | 文件编码 | `utf-8` |

**调用示例：**
```
请调用 file_read 技能读取文件：/path/to/file.txt
```

---

### 6. word_read - Word 文档读取

读取 Word 文档 (.docx) 内容。

**参数：**

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `file_path` | string | Word 文档路径 | 必填 |

**调用示例：**
```
请读取 /Users/zhanghanzhi/文档.docx 文件
```

---

### 7. kdocs_read - 金山文档读取

读取金山文档（kdocs.cn）在线内容。

**参数：**

| 参数 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `url` | string | 金山文档分享链接 | 必填 |
| `password` | string | 访问密码（如需要） | `null` |

**调用示例：**
```
请读取 https://kdocs.cn/l/xxxxx 金山文档
```

---

## 🔄 技能组合使用

### 场景1：分析项目结构

```
请先调用 list_dir 技能列出 /Users/zhanghanzhi/DFEcrab/src 目录
然后调用 planner 技能分析：分析这个项目的代码结构
最后调用 project_memory 技能保存：项目代码结构分析完成，分类：background
```

### 场景2：复杂部署任务

```
请调用 planner 技能分析：帮我部署一个 Docker 应用到服务器
然后按计划执行
完成后调用 project_memory 技能保存：完成了 Docker 部署，分类：progress
```

### 场景3：文档分析并保存

```
请列出 /Users/zhanghanzhi/武林秘籍/2.项目文档/08-ai/ 目录
读取其中的 Word 文档
然后调用 project_memory 技能保存分析结果，分类：background
```

---

## 📊 记忆分层结构

```
data/shared_memory/
├── GLOBAL.md           # 全局配置 + 人格定义
├── LONG_TERM.md       # 长期记忆
├── WEEKLY/            # 每周汇总
├── MONTHLY/           # 每月汇总
└── DAILY/            # 每日记忆
```

| 文件/目录 | 说明 | 维护方式 |
|-----------|------|----------|
| `GLOBAL.md` | 全局共享，项目配置 | 手动编辑 |
| `LONG_TERM.md` | 长期重要记忆 | 每月自动提取 |
| `WEEKLY/*.md` | 每周工作汇总 | 每周日23:59自动 |
| `MONTHLY/*.md` | 每月工作汇总 | 每月末23:59自动 |
| `DAILY/*.md` | 每日工作记录 | 每次保存时追加 |

---

## ⚙️ 配置文件

技能启用配置在 `agents/default/tools.json`：

```json
{
  "enabled_skills": [
    "planner",
    "project_memory",
    "memory_maintenance",
    "list_dir",
    "file_read",
    "word_read",
    "kdocs_read"
  ],
  "custom_tools": [],
  "builtin_tools": [
    "planner",
    "project_memory",
    "memory_maintenance",
    "list_dir",
    "file_read",
    "word_read",
    "kdocs_read"
  ]
}
```

---

## 💡 使用技巧

### 1. 隐式调用 vs 显式调用

**隐式调用**（AI 自动选择）：
```
帮我读取 /path/to/file.txt
```

**显式调用**（明确指定技能）：
```
请调用 file_read 技能读取文件：/path/to/file.txt
```

### 2. 结合记忆系统

重要任务完成后，记得保存记忆：

```
完成了 XX 功能开发，请调用 project_memory 技能保存：分类：progress
```

### 3. 使用规划技能

遇到复杂任务时，让 AI 先规划：

```
请先调用 planner 技能分析这个任务
```

### 4. 热加载技能

技能文件支持热加载，修改 `skills/` 目录下的技能文件后，约 5 秒后自动生效。

**新增技能步骤：**
1. 在 `skills/` 目录下创建新技能（如 `my_skill/execute.py`）
2. 在 `agents/default/tools.json` 中添加技能名称
3. 约 5 秒后自动加载生效

**修改技能步骤：**
1. 直接修改 `skills/` 目录下对应的 `execute.py` 文件
2. 约 5 秒后自动热加载生效

**验证热加载：**
```bash
tail -f logs/gateway.log | grep "热加载"
```

---

## 🔧 热加载原理

```
修改 skills/my_skill/execute.py
        ↓
SkillPlugin 检测到文件变化（每5秒检查）
        ↓
重新加载技能到 SkillPlugin
        ↓
通知 AgentPlugin 同步 toolkit
        ↓
技能立即可用
```

**注意事项：**
- 新增技能需要添加到 `tools.json` 配置
- 如果热加载后仍不可用，请重启 Gateway
- 技能执行函数修改后自动生效

### 5. 定期维护记忆

每周日、每月末系统会自动汇总，也可以手动触发：

```
请调用 memory_maintenance 技能执行所有维护任务
```

---

**文档版本：** 1.0
**更新时间：** 2026-03-29
**状态：** ✅ 完整