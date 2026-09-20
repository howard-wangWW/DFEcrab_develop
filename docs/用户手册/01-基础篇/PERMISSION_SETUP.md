# DFEcrab 权限配置指南

## 🔍 问题诊断

### 常见权限问题

1. **无法写入日志文件**
   ```
   ❌ PermissionError: [Errno 13] Permission denied: 'logs/gateway.log'
   ```

2. **无法创建智能体**
   ```
   ❌ PermissionError: [Errno 13] Permission denied: 'agents/'
   ```

3. **无法加载技能**
   ```
   ❌ PermissionError: [Errno 13] Permission denied: 'skills/'
   ```

4. **无法写入工作空间**
   ```
   ❌ PermissionError: [Errno 13] Permission denied: 'workspace/'
   ```

### 问题原因

- **macOS 系统限制**: SIP（系统完整性保护）
- **文件系统权限**: 目录/文件权限设置不当
- **用户权限**: 非文件所有者
- **沙箱限制**: 某些环境下的沙箱限制

## 🔧 解决方案

### 方案 1: 使用权限设置脚本（推荐）

```bash
# 进入项目目录
cd /Users/zhanghanzhi/DFEcrab

# 运行权限设置脚本
chmod +x setup_permissions.sh
./setup_permissions.sh
```

**脚本功能**:
- ✅ 创建必要的目录
- ✅ 设置正确的权限（755/644）
- ✅ 验证权限设置
- ✅ 测试写入权限

### 方案 2: 手动设置权限

```bash
# 设置目录权限
chmod 755 logs pids runs workspace skills agents docs tests src

# 设置文件权限
chmod 644 dfecrab.json
chmod 755 dfecrab

# 设置 Python 文件权限
find src -name "*.py" -exec chmod 644 {} \;
```

### 方案 3: 使用权限检查工具

```bash
# 运行权限检查
python3 -m src.utils.permission_checker

# 自动修复权限（在检查工具中）
# 当检测到问题时，选择 'y' 自动修复
```

### 方案 4: macOS 特殊处理

如果是 macOS 系统，可能需要授予完全磁盘访问权限：

1. 打开 **系统偏好设置** → **安全性与隐私**
2. 选择 **隐私** 标签页
3. 选择 **完全磁盘访问权限**
4. 点击 **+** 添加终端或你的 IDE
5. 重启终端

## 📋 权限配置说明

### 目录权限

| 目录 | 权限 | 说明 |
|------|------|------|
| `logs/` | 755 | 日志目录，需要写入 |
| `pids/` | 755 | PID 文件目录，需要写入 |
| `runs/` | 755 | 运行记录目录，需要写入 |
| `workspace/` | 755 | 工作空间，需要写入 |
| `skills/` | 755 | 技能目录，需要读取 |
| `agents/` | 755 | 智能体目录，需要写入 |
| `docs/` | 755 | 文档目录，只读 |
| `tests/` | 755 | 测试目录，只读 |
| `src/` | 755 | 源代码目录，只读 |

### 文件权限

| 文件类型 | 权限 | 说明 |
|----------|------|------|
| 可执行脚本 | 755 | `dfecrab`, shell 脚本 |
| 配置文件 | 644 | `dfecrab.json` |
| Python 源文件 | 644 | `.py` 文件 |
| 日志文件 | 644 | `.log` 文件 |
| 文档文件 | 644 | `.md` 文件 |

### 权限含义

```
755 = rwxr-xr-x
- 所有者：读 + 写 + 执行
- 组用户：读 + 执行
- 其他用户：读 + 执行

644 = rw-r--r--
- 所有者：读 + 写
- 组用户：读
- 其他用户：读

755 = rwxr-xr-x (可执行文件)
- 所有者：读 + 写 + 执行
- 组用户：读 + 执行
- 其他用户：读 + 执行
```

## 🔍 验证权限

### 检查目录权限

```bash
# 查看目录权限
ls -ld logs pids workspace skills agents

# 示例输出
drwxr-xr-x  2 user  staff  logs
drwxr-xr-x  2 user  staff  pids
drwxr-xr-x  4 user  staff  workspace
```

### 检查文件权限

```bash
# 查看文件权限
ls -l dfecrab dfecrab.json

# 示例输出
-rwxr-xr-x  1 user  staff  dfecrab
-rw-r--r--  1 user  staff  dfecrab.json
```

### 测试写入权限

```bash
# 测试日志目录
touch logs/test_write && rm logs/test_write && echo "✅ 日志目录可写"

# 测试工作空间
touch workspace/test_write && rm workspace/test_write && echo "✅ 工作空间可写"

# 测试智能体目录
touch agents/test_write && rm agents/test_write && echo "✅ 智能体目录可写"
```

## ⚙️ 环境变量配置

### 可选的环境变量

```bash
# 设置 DFEcrab 根目录
export DFECRAB_HOME=/Users/zhanghanzhi/DFEcrab

# 设置日志目录
export DFECRAB_LOGS=/Users/zhanghanzhi/DFEcrab/logs

# 添加到 ~/.bashrc 或 ~/.zshrc
echo 'export DFECRAB_HOME=/Users/zhanghanzhi/DFEcrab' >> ~/.zshrc
echo 'export DFECRAB_LOGS=/Users/zhanghanzhi/DFEcrab/logs' >> ~/.zshrc
source ~/.zshrc
```

### 在配置文件中设置

编辑 `dfecrab.json`:

```json
{
  "directories": {
    "skills": "skills",
    "logs": "logs",
    "memory": "memory",
    "workspace": "workspace",
    "agents": "agents"
  }
}
```

## 🐛 故障排除

### 问题 1: 仍然无法写入

**症状**: 运行脚本后仍然提示权限错误

**解决**:
```bash
# 检查文件所有者
ls -ld logs

# 如果不是当前用户，修改所有者
sudo chown -R $(whoami) logs pids workspace

# 再次尝试写入
touch logs/test && rm logs/test
```

### 问题 2: macOS SIP 限制

**症状**: 系统目录相关权限问题

**解决**:
- DFEcrab 不应该安装在系统目录
- 确保安装在用户目录（如 `~/Projects/` 或 `/Users/username/`）
- 如果必须访问系统目录，需要禁用 SIP（不推荐）

### 问题 3: Docker 或虚拟机

**症状**: 在容器中权限问题

**解决**:
```bash
# Docker 中运行
docker run -v $(pwd):/app -w /app python:3.9 python3 -m src

# 或者在 Dockerfile 中设置
USER root
RUN chown -R appuser:appuser /app
USER appuser
```

### 问题 4: 网络文件系统（NFS）

**症状**: NFS 挂载目录权限问题

**解决**:
```bash
# 检查 NFS 挂载选项
mount | grep nfs

# 可能需要调整 NFS 服务器配置
# 或使用本地目录
```

## 📝 最佳实践

### 1. 使用正确的安装位置

✅ **推荐**:
```
/Users/username/Projects/DFEcrab
/Users/username/DFEcrab
/home/username/DFEcrab
```

❌ **不推荐**:
```
/usr/local/DFEcrab
/opt/DFEcrab
/System/Volumes/Data/DFEcrab
```

### 2. 定期检查和修复权限

```bash
# 添加到 crontab（每月一次）
0 0 1 * * cd /Users/zhanghanzhi/DFEcrab && ./setup_permissions.sh
```

### 3. 使用版本控制

```bash
# 权限脚本应该提交到版本控制
git add setup_permissions.sh
git commit -m "Add permission setup script"
```

### 4. 文档化权限要求

在项目文档中说明权限要求：
- README.md 中添加权限说明
- 安装指南中包含权限设置步骤

## 🎯 快速参考

### 一键设置

```bash
cd /Users/zhanghanzhi/DFEcrab
./setup_permissions.sh
```

### 快速检查

```bash
python3 -m src.utils.permission_checker
```

### 手动修复

```bash
# 修复目录权限
chmod -R 755 logs pids workspace skills agents

# 修复文件权限
chmod 644 dfecrab.json
find src -name "*.py" -exec chmod 644 {} \;

# 修复所有者
chown -R $(whoami) logs pids workspace
```

## 📞 获取帮助

如果以上方法都无法解决问题：

1. 查看详细日志：
   ```bash
   tail -f logs/gateway.log
   ```

2. 运行诊断工具：
   ```bash
   python3 -m src.utils.permission_checker
   ```

3. 提交 Issue：
   - 包含错误信息
   - 包含操作系统版本
   - 包含权限检查结果

---

**文档版本**: 1.0
**更新日期**: 2026-03-29
**维护者**: DFEcrab Team
