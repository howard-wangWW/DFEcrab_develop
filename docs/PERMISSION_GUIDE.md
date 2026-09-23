# DFEcrab 权限管理说明

## 🎯 快速解决权限问题

如果你的 DFEcrab 没有权限读取本地路径，请按以下步骤操作：

### 方法 1: 一键设置（推荐）

```bash
cd /Users/zhanghanzhi/DFEcrab
./setup_permissions.sh
```

### 方法 2: 运行检查工具

```bash
python3 -m src.utils.permission_checker
```

### 方法 3: 手动设置

```bash
# 设置目录权限
chmod -R 755 logs pids workspace skills agents

# 设置文件权限
chmod 644 dfecrab.json
chmod 755 dfecrab
```

## 📋 已创建的权限管理工具

### 1. setup_permissions.sh
- 自动创建必要目录
- 设置正确的权限（755/644）
- 验证权限设置
- 测试写入权限

### 2. permission_checker.py
- 诊断权限问题
- 提供修复建议
- 自动修复权限

### 3. 权限配置文档
- 详细的使用说明
- 故障排除指南
- 最佳实践建议

## 🔍 权限问题原因

### macOS 系统限制
- **SIP（系统完整性保护）**: 限制访问系统目录
- **隐私权限**: 需要完全磁盘访问权限
- **文件所有者**: 非文件所有者无法写入

### 权限设置不当
- **目录权限**: 应该是 755（rwxr-xr-x）
- **文件权限**: 应该是 644（rw-r--r--）
- **可执行文件**: 应该是 755（rwxr-xr-x）

## ✅ 权限配置

### 目录权限（755）

```
drwxr-xr-x  logs/           # 日志目录
drwxr-xr-x  pids/           # PID 文件目录
drwxr-xr-x  runs/           # 运行记录目录
drwxr-xr-x  workspace/      # 工作空间
drwxr-xr-x  skills/         # 技能目录
drwxr-xr-x  agents/         # 智能体目录
```

### 文件权限

```
-rwxr-xr-x  dfecrab         # 主入口脚本（可执行）
-rw-r--r--  dfecrab.json    # 配置文件
-rw-r--r--  src/**/*.py     # Python 源文件
-rw-r--r--  logs/*.log      # 日志文件
```

## 🐛 常见问题

### Q1: 无法写入日志
```bash
# 解决
chmod 755 logs
chown -R $(whoami) logs
```

### Q2: 无法创建智能体
```bash
# 解决
chmod 755 agents
chown -R $(whoami) agents
```

### Q3: macOS 隐私限制
1. 系统偏好设置 → 安全性与隐私 → 隐私
2. 完全磁盘访问权限
3. 添加终端或 IDE
4. 重启终端

### Q4: 权限设置后仍然不行
```bash
# 检查当前权限
ls -ld logs agents workspace

# 修复所有者
sudo chown -R $(whoami) logs agents workspace

# 重新设置权限
./setup_permissions.sh
```

## 📖 详细文档

完整的使用说明和故障排除指南请查看：
- [权限配置指南](./docs/用户手册/01-基础篇/PERMISSION_SETUP.md)

## 🎯 最佳实践

### 1. 定期检查和修复

```bash
# 每月运行一次
./setup_permissions.sh
```

### 2. 使用正确的安装位置

✅ **推荐**:
- `/Users/username/Projects/DFEcrab`
- `/Users/username/DFEcrab`

❌ **不推荐**:
- `/usr/local/DFEcrab`
- `/opt/DFEcrab`

### 3. 版本控制

```bash
git add setup_permissions.sh
git commit -m "Add permission setup script"
```

## 🔧 维护命令

### 检查权限
```bash
python3 -m src.utils.permission_checker
```

### 设置权限
```bash
./setup_permissions.sh
```

### 验证权限
```bash
ls -ld logs pids workspace skills agents
```

### 测试写入
```bash
touch logs/test && rm logs/test && echo "✅ 可写"
```

---

**更新日期**: 2026-03-29
**版本**: 1.0
**维护者**: DFEcrab Team
