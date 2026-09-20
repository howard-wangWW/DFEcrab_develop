# DFEcrab 用户手册

## 📚 文档说明

本手册为 DFEcrab 用户提供完整的安装、配置、使用指南。

**当前版本**: 4.0.0  
**更新日期**: 2026-04-03

---

## 🎉 v4.0 新增功能

### 核心增强

- ✅ **分级权限系统** - 四级权限控制（Read-only/Write/Shell/Unsafe），保障系统安全
- ✅ **斜杠命令系统** - 10 个本地命令（/help, /status, /tools 等），无需模型调用即可响应
- ✅ **统一工具系统** - 10 个核心工具（FileRead, FileEdit, Bash, Grep 等），支持流式执行
- ✅ **四层记忆系统** - 企业/项目/自动/用户四层记忆，参考 Claude Code 架构设计
- ✅ **插件系统 V2** - 支持斜杠命令、专用代理、技能定义、事件钩子
- ✅ **会话持久化** - 完整 transcript 持久化与恢复
- ✅ **上下文引擎** - CLAUDE.md/DFECRAB.md 自动发现，Token 用量估算
- ✅ **工作区配置** - AGENTS.md/SOUL.md 驱动的配置系统

### 性能提升

- 权限检查延迟 < 1ms
- 斜杠命令处理延迟 < 5ms
- 工具流式输出支持
- 会话序列化/恢复 < 20ms

---

## 📋 快速开始

### 1. 安装

```bash
# 克隆项目
git clone <repository-url>
cd DFEcrab

# 安装依赖
pip install -e .

# 验证安装
dfecrab --version
```

### 2. 配置

```bash
# 编辑配置文件
vim dfecrab.json

# 配置模型
# 配置技能目录
# 配置记忆存储路径
```

### 3. 启动

```bash
# 启动 Gateway
dfecrab gateway start

# 启动 TUI
dfecrab tui start
```

### 4. 使用

```bash
# 命令行对话
dfecrab chat "你好"

# API 调用 (v2版本)
curl -X POST http://localhost:6789/api/v2/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

---

## 📖 详细指南

### 基础篇

- [快速入门](./01-基础篇/QUICKSTART.md) - 5 分钟快速上手
- [权限配置](./01-基础篇/PERMISSION_SETUP.md) - 权限系统配置
- [权限系统指南](./01-基础篇/PERMISSION_GUIDE.md) - 四级权限系统详解
- [斜杠命令](./01-基础篇/SLASH_COMMANDS.md) - 斜杠命令系统使用指南

### 使用篇

- [API 调用](./02-使用篇/API_USAGE.md) - REST API 调用
- [技能使用](./02-使用篇/SKILLS_USAGE.md) - 技能管理使用
- [Docker 部署](./02-使用篇/DOCKER_DEPLOYMENT.md) - Docker 部署指南
- [工具使用](./02-使用篇/TOOLS_USAGE.md) - 统一工具系统使用指南
- [工作区配置](./02-使用篇/WORKSPACE_CONFIG.md) - AGENTS.md/SOUL.md 驱动的配置系统

### 进阶篇

- [V4 升级指南](./03-进阶篇/V4_UPGRADE_GUIDE.md) - V4 版本改进说明

### 参考篇

- [快速参考](./04-参考篇/QUICK_REFERENCE.md) - 快速参考卡片
- [API 参考 V4](./04-参考篇/API_REFERENCE_V4.md) - V4 API 详细说明

---

## 🎯 使用场景

### 场景 1：个人智能助手

```bash
# 创建个人智能体
dfecrab agent create my_assistant

# 对话
dfecrab chat -a my_assistant "今天天气如何？"
```

### 场景 2：技能开发

```bash
# 创建技能
dfecrab skill create my_skill

# 测试技能
dfecrab skill test my_skill

# 发布技能
dfecrab skill publish my_skill
```

### 场景 3：企业部署

```bash
# 配置生产环境
dfecrab config production

# 启动服务
dfecrab gateway start --production

# 监控状态
dfecrab monitor status
```

---

## 📁 手册结构

```
用户手册/
├── README.md                      # 本文件
├── 01-基础篇/
│   ├── QUICKSTART.md              # 快速入门
│   ├── PERMISSION_SETUP.md        # 权限配置
│   ├── PERMISSION_GUIDE.md        # 权限系统指南
│   └── SLASH_COMMANDS.md          # 斜杠命令
├── 02-使用篇/
│   ├── API_USAGE.md               # API 调用
│   ├── SKILLS_USAGE.md            # 技能使用
│   ├── DOCKER_DEPLOYMENT.md       # Docker 部署
│   ├── TOOLS_USAGE.md             # 工具使用
│   └── WORKSPACE_CONFIG.md        # 工作区配置
├── 03-进阶篇/
│   └── V4_UPGRADE_GUIDE.md        # V4 升级指南
└── 04-参考篇/
    ├── QUICK_REFERENCE.md         # 快速参考
    └── API_REFERENCE_V4.md        # V4 API 参考
```

---

## 🔧 工具使用

### 命令行工具

```bash
# 查看所有命令
dfecrab --help

# 查看子命令帮助
dfecrab gateway --help
dfecrab agent --help
dfecrab skill --help
```

### 斜杠命令

```bash
# 查看帮助
/help

# 查看系统状态
/status

# 查看工具列表
/tools

# 查看权限
/permissions

# 查看记忆
/memory

# 查看上下文
/context
```

### API 工具

```bash
# 健康检查
curl http://localhost:6789/health

# 查看统计
curl http://localhost:6789/api/stats

# 查看会话
curl http://localhost:6789/api/sessions
```

---

## 🐛 故障排除

### 常见问题

**Q: 启动失败**
```bash
# 检查端口占用
lsof -i :6789

# 查看日志
tail -f logs/gateway.log
```

**Q: 技能无法加载**
```bash
# 检查技能目录
ls -la skills/

# 验证技能格式
dfecrab skill validate <skill_name>
```

**Q: 记忆丢失**
```bash
# 检查记忆目录
ls -la agents/<agent_id>/memory/

# 恢复记忆备份
dfecrab memory restore
```

**Q: 权限问题**
```bash
# 运行权限检查
python3 -m src.utils.permission_checker

# 自动修复权限
./setup_permissions.sh
```

---

## 📞 获取帮助

- **文档**: [官方文档](../README.md)
- **问题**: 提交 Issue
- **讨论**: 加入社区

---

**版本**: 4.0.0
**文档数量**: 10 个用户指南
**更新日期**: 2026-04-03
**状态**: 已发布
