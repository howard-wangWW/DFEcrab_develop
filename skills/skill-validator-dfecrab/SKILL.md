---
name: skill-validator-dfecrab
description: 技能格式审查工具，检查技能是否符合 OpenClaw 标准，不符合标准的技能无法安装
version: "1.0.0"
author: DFEcrab
triggers:
  - 技能审查
  - 技能验证
  - validate skill
  - skill check
  - 检查技能格式
---

# Skill Validator

审查技能是否符合 OpenClaw 标准格式，确保只有符合标准的技能才能被安装。

## 使用方法

```
检查 [技能名] 格式
验证技能 [技能目录]
```

## 必需字段

- `name`: 技能名称
- `description`: 技能描述
- `version`: 版本号
- `author`: 作者
- `triggers`: 触发关键词列表

## 可选字段

- `requires`: 依赖项（非标准）
- `emoji`: 表情符号（非标准）
