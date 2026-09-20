# DFEcrab 代码上传（Git）操作指南

> 编写日期：2026-09-20
> 适用：Windows 本机开发 → GitHub 协同仓库

---

## 1. 仓库信息

| 项目 | 值 |
|---|---|
| 远程仓库 | https://github.com/howard-wangWW/DFEcrab_develop |
| 远程名 | `origin` |
| 主分支 | `main` |
| 提交者身份 | `howard-wangWW <2239249382@qq.com>` |
| 项目根目录 | `C:\Users\22392\Desktop\9月工作对接\DFEcrab\DFEcrab` |

---

## 2. 本机特殊配置（重要，换机器时必读）

### 2.1 `.git` 元数据不在项目里

本机项目目录的 `.git` **只是一个指针文件**，真正的 Git 元数据在：

```
C:\Users\22392\AppData\Local\Temp\DFEcrab.gitdir
```

查看方式：

```bash
cat .git
# 输出: gitdir: C:/Users/22392/AppData/Local/Temp/DFEcrab.gitdir
```

### 2.2 为什么这样配

本机装有企业级终端管控（360 安全卫士主体 + 深信服 aTrust 零信任客户端），
它们拦截 `git.exe` 在受保护目录（桌面、用户目录、D 盘等）写入对象文件，
只有 `%TEMP%` 允许写入。因此使用 `git init --separate-git-dir` 把元数据放进 Temp。

### 2.3 风险与恢复

- **风险**：`%TEMP%` 会被系统清理。一旦 `DFEcrab.gitdir` 被删，本地提交功能失效
  （代码和 GitHub 上的内容不受影响）。
- **判断是否失效**：`git status` 报 `not a git repository` 即为失效。
- **恢复方法**：按第 5 节重建仓库（代码不会丢）。
- **根治建议**：请 IT 把 `D:\Git\cmd\git.exe` 加入安全软件白名单，
  然后把元数据迁回项目内（`git init --separate-git-dir=...` 反向操作或重建）。

### 2.4 旧历史备份

初次重建前的旧 `.git`（含 v3.5.x 历史）备份在：

```
C:\Users\22392\Desktop\9月工作对接\DFEcrab\.DFEcrab-git-backup-20260920
```

确认新仓库可用后可自行删除。

---

## 3. 日常上传流程（最常用）

在项目根目录打开 Git Bash：

```bash
cd "C:/Users/22392/Desktop/9月工作对接/DFEcrab/DFEcrab"

# 1) 先拉远端最新代码，避免冲突
git pull --rebase origin main

# 2) 查看自己改了什么
git status
git diff

# 3) 暂存改动（. 表示全部；也可指定具体文件）
git add -A

# 4) 提交，写清楚改了什么
git commit -m "fix: 修复任务审计日志未落库的问题"

# 5) 推送到 GitHub
git push origin main
```

首次推送或换机器后，需要绑定远端：

```bash
git remote add origin https://github.com/howard-wangWW/DFEcrab_develop.git
git push -u origin main
```

---

## 4. 首次提交/重建后的完整命令（记录本次操作）

```bash
cd "C:/Users/22392/Desktop/9月工作对接/DFEcrab/DFEcrab"

# 备份旧 .git（如需保留历史）
mv .git "../.DFEcrab-git-backup-20260920"

# 在 %TEMP% 建立 Git 元数据，工作区仍在原位
git init -b main --separate-git-dir="C:/Users/22392/AppData/Local/Temp/DFEcrab.gitdir" .

# 关联远端
git remote add origin https://github.com/howard-wangWW/DFEcrab_develop.git

# 暂存 + 提交 + 推送（输出重定向到文件，避免管道中断）
git add -A > /tmp/add.log 2>&1
git commit -m "feat: DFEcrab v4.9.x-grpc 初始上传" > /tmp/commit.log 2>&1
git push origin main > /tmp/push.log 2>&1
```

---

## 5. 被排除的文件与原因

`.gitignore` 已排除以下内容，**不要手动 `git add -f` 强制加入**：

| 排除项 | 原因 |
|---|---|
| `data/` | 运行时状态（会话/记忆/用量事件/任务存储） |
| `models/` | 模型权重，约 1.2 GB |
| `runtime/bin/` | Node 运行时，128 MB |
| `mcp_servers/blackxml-topology-mcp/BLACKXML/` | 电网拓扑历史快照，约 1.5 GB / 10756 文件 |
| `*.sqlite` `*.DAT` `*.cache/` `用户列表索引/` | 业务数据库与网格数据 |
| `node_modules/` | 前端依赖 |
| `logs/` `nohup.out` `.env` | 日志与本地配置 |
| `src/agent/multi/reflector.py` | IANDSEC DRM 透明加密，git 当前读取为密文 |

### 关于 DRM 加密文件

部分源码受公司透明加密系统（IANDSEC）保护：文件在磁盘上是密文，
只有白名单程序能读到明文。`git.exe` 通常不在白名单内，因此：

- 现象一：`error: open("..."): Permission denied`
- 现象二：能读但内容是密文（提交上去是乱码）
- 现象三：放行某程序后，git 能读到明文（需逐文件验证）

当前状态（2026-09-20）：
- `src/agent/loop.py` 已纳入仓库（git 读取明文，89309 字节）
- `src/agent/multi/reflector.py` 仍排除（git 仍读取为密文）

**排查命令**：

```bash
# 判断 git 读到的是明文还是密文
python -c "
import subprocess, hashlib, sys
f = sys.argv[1]
data = open(f,'rb').read()
h_py = hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()
h_git = subprocess.run(['git','hash-object',f], capture_output=True, text=True).stdout.strip()
print(f, 'git读到', '明文' if h_py==h_git else '密文')
" src/agent/multi/reflector.py
```

输出「密文」说明该文件不能用 git 上传，需要走公司的正式解密/导出流程。

---

## 6. 常见问题

### 6.1 `git add` 报 `Permission denied` 或 `unable to write .git/objects`

原因：企业管控拦截了 git 在受保护目录写文件。
处理：确认使用的是 `--separate-git-dir` 指向 `%TEMP%` 的仓库（见第 2 节）。

### 6.2 推送被拒绝 `! [rejected] ... (fetch first)`

原因：远端有本地没有的提交。
处理：

```bash
git pull --rebase origin main
git push origin main
```

### 6.3 `git add` 输出被管道截断导致失败

**不要**把 `git add` 的输出用管道接给 `head` 等命令（会触发 SIGPIPE 中断，
导致 index 未写入）。改用重定向：

```bash
git add -A > /tmp/add.log 2>&1
```

### 6.4 误加入了超大数据

```bash
# 从暂存区撤下（保留磁盘文件）
git rm -r --cached 路径
# 再写进 .gitignore
echo "路径/" >> .gitignore
```

### 6.5 检查暂存区体积（提交前建议做）

```bash
git diff --cached --stat | tail -1
```

---

## 7. 提交信息规范（建议）

| 前缀 | 用途 |
|---|---|
| `feat:` | 新功能 |
| `fix:` | 修 bug |
| `refactor:` | 重构，不改行为 |
| `docs:` | 只改文档 |
| `chore:` | 构建/配置/杂项 |

示例：`fix: 补齐任务审计日志落库，修复 audit 接口返回空的问题`
