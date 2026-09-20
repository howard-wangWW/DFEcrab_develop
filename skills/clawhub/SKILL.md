---
name: clawhub
description: 使用 ClawHub CLI 搜索、安装、更新和发布技能。当需要动态获取新技能、同步已安装技能到最新版本、或发布新技能时使用。
---

# ClawHub CLI

使用 clawhub 命令管理技能。

## 前提条件

安装 ClawHub CLI：
```bash
npm i -g clawhub
```

登录（发布技能需要）：
```bash
clawhub login
clawhub whoami
```

## 常用命令

### 搜索技能
```bash
clawhub search "excel"
clawhub search "pdf"
clawhub search "天气"
```

### 安装技能
```bash
clawhub install 技能名称
clawhub install 技能名称 --version 1.2.3
```

### 更新技能
```bash
clawhub update 技能名称
clawhub update --all
clawhub update 技能名称 --force
```

### 列出已安装
```bash
clawhub list
```

### 发布技能
```bash
clawhub publish ./my-skill --slug my-skill --name "My Skill" --version 1.0.0
```

## 注意事项

- 默认 registry: https://clawhub.com
- 默认工作目录: ./skills
- 需要先登录才能发布技能
