# DFEcrab Docker 部署指南

## 📋 概述

本文档介绍如何使用 Docker 和 Docker Compose 部署 DFEcrab。

## 🚀 快速开始

### 1. 准备环境

确保已安装：
- Docker 20.10+
- Docker Compose 2.0+

```bash
# 检查版本
docker --version
docker-compose --version
```

### 2. 下载/克隆项目

```bash
git clone <dfecrab-repo-url> dfecrab
cd dfecrab
```

### 3. 配置

DFEcrab 的配置通过项目内的配置文件管理，无需 `.env`：

- 服务端口 / 监听地址：编辑 `config/gateway.yaml` 的 `gateway.port` / `gateway.host`
- 模型地址 / 模型名：编辑 `config/dfecrab.json` 的 `model.api_base` / `model.model_name`
- 各本地服务端口：见 `config/gateway.yaml` 的 `local_ports`

> 注：原 `.env.example` 模板已移除，其变量（`DFECRAB_PORT` / `OLLAMA_BASE_URL` / `OLLAMA_MODEL` / `LOG_LEVEL`）与 `config/` 重复且未被代码读取。

### 4. 启动服务

```bash
# 启动（后台运行）
docker-compose -f docker-compose.prod.yml up -d

# 查看状态
docker-compose -f docker-compose.prod.yml ps

# 查看日志
docker-compose -f docker-compose.prod.yml logs -f
```

### 5. 验证部署

```bash
# 健康检查
curl http://localhost:6789/health

# API 测试
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'
```

---

## 📁 目录结构

部署后的目录结构：

```
dfecrab/
├── data/shared_memory/    # 共享记忆（持久化）
│   ├── GLOBAL.md
│   ├── LONG_TERM.md
│   ├── DAILY/
│   ├── WEEKLY/
│   └── MONTHLY/
├── logs/                  # 日志文件
│   └── gateway.log
├── skills/               # 技能目录（挂载为只读）
├── agents/               # Agent 配置（挂载为只读）
├── dfecrab.json          # 主配置文件
├── dfecrab.prod.json     # 生产配置
└── docker-compose.prod.yml
```

---

## ⚙️ 配置说明

### 配置项（对应 config/ 文件）

| 配置项 | 说明 | 默认值 | 所在文件 |
|--------|------|--------|----------|
| 服务端口 | 网关 HTTP 端口 | `6789` | `config/gateway.yaml` → `gateway.port` |
| 模型地址 | Ollama / 模型 API 地址 | — | `config/dfecrab.json` → `model.api_base` |
| 模型名称 | 使用的模型 | — | `config/dfecrab.json` → `model.model_name` |
| 日志级别 | 日志级别 | `INFO` | 代码默认（可在启动参数指定） |

### Ollama 地址说明

将下方地址填写到 `config/dfecrab.json` 的 `model.api_base`（或对应 `model_providers.*.api_base`）：

**macOS/Windows（Docker Desktop）：**
```
http://host.docker.internal:11434
```

**Linux（无 Docker Desktop）：**
```bash
# 查看宿主机的 Ollama IP
ip addr show docker0
# 假设宿主机 IP 是 172.17.0.1，则填写：
http://172.17.0.1:11434
```

**远程服务器：**
```
http://192.168.1.100:11434
```

---

## 🔧 高级配置

### 使用自定义配置文件

创建 `dfecrab.json`：

```json
{
  "version": "1.0.0",
  "model": {
    "provider": "ollama",
    "model_name": "deepseek-v3.1:671b",
    "api_base": "http://your-ollama:11434",
    "timeout": 60
  },
  "gateway": {
    "host": "0.0.0.0",
    "port": 6789
  },
  "skills": {
    "auto_reload": true
  }
}
```

挂载到容器内：

```yaml
# docker-compose.prod.yml 中已配置
volumes:
  - ./dfecrab.json:/app/dfecrab.json:ro
```

### 添加自定义技能

```bash
# 创建自定义技能目录
mkdir -p my_skills

# 在 docker-compose.yml 中添加挂载
volumes:
  - ./my_skills:/app/my_skills:ro
```

### 数据持久化

| 宿主机目录 | 容器内目录 | 说明 |
|-----------|-----------|------|
| `./data/shared_memory` | `/app/data/shared_memory` | 共享记忆（重要！） |
| `./logs` | `/app/logs` | 日志文件 |
| `./skills` | `/app/skills` | 技能（只读） |
| `./agents` | `/app/agents` | Agent 配置（只读） |

---

## 🛠️ 运维命令

### 启动/停止

```bash
# 启动
docker-compose -f docker-compose.prod.yml up -d

# 停止
docker-compose -f docker-compose.prod.yml down

# 重启
docker-compose -f docker-compose.prod.yml restart
```

### 查看日志

```bash
# 实时日志
docker-compose -f docker-compose.prod.yml logs -f

# 最近 100 行
docker-compose -f docker-compose.prod.yml logs --tail=100

# 指定服务
docker-compose -f docker-compose.prod.yml logs -f dfecrab
```

### 进入容器

```bash
# 进入容器
docker-compose -f docker-compose.prod.yml exec dfecrab bash

# 查看进程
docker-compose -f docker-compose.prod.yml exec dfecrab ps aux
```

### 更新版本

```bash
# 1. 拉取新代码
git pull

# 2. 重新构建
docker-compose -f docker-compose.prod.yml build

# 3. 重启服务
docker-compose -f docker-compose.prod.yml up -d
```

---

## 🔒 安全建议

### 1. 网络隔离

```yaml
networks:
  dfecrab-net:
    driver: bridge
    internal: true  # 禁止访问外网
```

### 2. 只读文件系统

```yaml
services:
  dfecrab:
    read_only: true
    tmpfs:
      - /tmp
```

### 3. 资源限制

```yaml
services:
  dfecrab:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
```

---

## 🐛 故障排查

### 容器无法启动

```bash
# 查看详细日志
docker-compose -f docker-compose.prod.yml logs

# 检查配置
docker-compose -f docker-compose.prod.yml config
```

### Ollama 连接失败

```bash
# 进入容器测试
docker-compose -f docker-compose.prod.yml exec dfecrab curl http://host.docker.internal:11434

# 检查防火墙
iptables -L -n | grep 11434
```

### 端口已被占用

```bash
# 查找占用进程
lsof -i :6789

# 修改端口：编辑 config/gateway.yaml 的 gateway.port 为 6788
```

---

## 📦 打包分发

如需在没有源码的环境中部署：

```bash
# 运行打包脚本
./scripts/package.sh 1.0.0

# 输出: dist/dfecrab-1.0.0.tar.gz
```

解压后只需：
```bash
# 1. 按现场修改 config/gateway.yaml 与 config/dfecrab.json
# 2. 启动
docker-compose -f docker-compose.prod.yml up -d
```

---

**文档版本：** 1.0
**更新时间：** 2026-03-29