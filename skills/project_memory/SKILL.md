# Project Memory Skill

项目记忆技能，用于管理项目相关的长期记忆。

## 功能

- **保存记忆** (save): 将重要信息保存到长期记忆
- **读取记忆** (load): 读取所有项目记忆
- **列出统计** (list): 查看记忆统计信息
- **搜索记忆** (search): 按关键词搜索记忆

## 记忆分类

- `general`: 通用信息
- `background`: 项目背景
- `progress`: 工作进度
- `decision`: 技术决策
- `file_location`: 文件位置
- `todo`: 待办事项

## 使用方式

```
执行技能 project_memory，操作：save，内容：要保存的记忆，分类：progress
执行技能 project_memory，操作：load
执行技能 project_memory，操作：list
执行技能 project_memory，操作：search，内容：关键词
```

## 重要提示

AI 应该主动使用此技能：
1. 完成重要任务后，主动保存到记忆
2. 开始新任务前，先读取项目记忆了解上下文
3. 发现用户项目相关信息时，主动询问是否保存