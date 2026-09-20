# DFEcrab 迁移指南

> 从旧电脑 / 旧服务器迁移到新机器（或重新部署）的完整步骤

---

## 📦 迁移包说明

项目以「源码 + `requirements.txt`」方式交付，**不打包、不发布到 PyPI**。
迁移时只需拷贝源码目录，`venv/` 不计入传输；目标机再建 `venv/` 并 `pip install -r requirements.txt` 即可还原环境。

---

## 🚀 新机器部署步骤

### 1. 环境准备

```bash
# 确认 Python 版本 (需要 3.10+，当前线上运行环境为 Python 3.12.7)
python3 --version

# 如果没有 Python，先安装
# macOS:
brew install python@3.10

# Ubuntu/Debian:
sudo apt install python3 python3-venv python3-pip
```

### 2. 创建虚拟环境

```bash
cd DFEcrab
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# 或
venv\Scripts\activate     # Windows
```

> 项目启动脚本 `dfecrab` 内部固定使用 `venv/bin/python3` 启动所有子服务，
> 因此环境目录必须命名为 `venv`（不要改成 `.venv` 或 `py310env`）。

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

> 依赖由 `requirements.txt` 统一管理，无需 `pip install -e .`（项目无打包配置 setup.py / pyproject.toml）。
> 国内镜像: `pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

### 4. 创建必要目录

```bash
mkdir -p logs runs pids
```

### 5. 配置 LLM

编辑 `config/dfecrab.json`，修改模型配置（注意 `enabled` 与 `api_base` 指向新环境的模型服务）。

示例（openai 兼容接口）：

```json
{
  "model": {
    "provider": "openai_compatible",
    "model_name": "你的模型名称",
    "api_base": "http://localhost:11434/v1",
    "enabled": true,
    "timeout": 300,
    "max_tokens": 4096,
    "context_length": 8192
  }
}
```

> 实际文件还包含 `model_providers`、`think_config`、`agent_defaults` 等字段，
> 多模型切换在 `model_providers` 中配置，详见 `config/dfecrab.json`。

### 6. 启动 / 停止服务

```bash
# 启动全部服务 (Gateway + Agent + 知识库 + MCP)
./dfecrab start

# 查看运行状态
./dfecrab status

# 命令行对话
./dfecrab chat "你好"

# 停止全部主服务
# （知识库 API 与本地 MCP 为独立服务，不随主服务停止，需单独 stop）
./dfecrab stop
```

> 其它常用子命令：
> - `./dfecrab start-knowledge` / `./dfecrab stop-knowledge` —— 单独启停知识库 API（端口 6788）
> - `./dfecrab start-mcp` / `./dfecrab stop-mcp` —— 单独启停本地 MCP 服务
> - `./dfecrab kb upload/search/chat/list/stats/health` —— 知识库管理
> - `./dfecrab test` —— 运行集成测试（`tests/test_grpc_architecture.py`）
> - `./dfecrab --version` —— 查看版本（当前 4.0.0-grpc）
>
> 说明：`./dfecrab` 是项目根目录的启动脚本（shebang 指向 `venv/bin/python3`）。
> Windows 下改用 `python dfecrab ...`；若未把 `venv` 加入 PATH，先 `source venv/bin/activate`。

### 7. 验证安装

```bash
./dfecrab --version
./dfecrab status
```

---

## 🔧 关于可选依赖

项目依赖已尽量收敛进 `requirements.txt`（含 AI/LLM、gRPC、向量检索、MCP 等全部运行所需）。
如个别功能仍需补充包，请直接加入 `requirements.txt` 后重装，不要再单独 `pip install`。

```bash
# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 📋 传输前检查清单

- [x] 删除 `logs/*` (日志)
- [x] 删除 `venv/` (虚拟环境，目标机重建)
- [x] 删除 `.pytest_cache/` (测试缓存)
- [x] 删除 `runs/` (运行记录)
- [x] 删除 `pids/` (进程文件)
- [x] 删除 `__pycache__/` (编译缓存)
- [ ] 检查 `data/reports/` (如需保留报告则不删)
- [ ] 检查 `agents/*/memory/` (如需保留记忆则不删)

---

## ⚠️ 注意事项

1. **配置文件**: `config/dfecrab.json` 中的 LLM 地址 (`api_base`) 需根据新环境修改
2. **端口冲突**: 若 Gateway 端口被占用，修改 `config/gateway.yaml` 的 `gateway.port`（默认 6789）
3. **模型服务**: 如使用本地模型，需先在新环境启动对应模型服务
4. **Zookeeper**: 服务依赖 Zookeeper（默认 `localhost:2181`），迁移后需确保其可用
5. **环境目录名**: 必须为 `venv/`，否则 `dfecrab` 启动脚本找不到 python
6. **权限问题**: 如遇权限错误，检查文件或目录权限

---

## 🐛 常见问题

### Gateway 启动失败

```bash
# 检查端口占用
lsof -i :6789  # macOS
netstat -ano | findstr :6789  # Windows

# 查看日志
tail -f logs/gateway_grpc.log
```

### 依赖安装失败

```bash
# 升级 pip
pip install --upgrade pip

# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### LLM 连接失败

```bash
# 测试 API 连接
curl http://<你的模型服务地址>/v1/models
```

---

## 📞 需要帮助？

查看完整文档: [docs/README.md](./README.md)
