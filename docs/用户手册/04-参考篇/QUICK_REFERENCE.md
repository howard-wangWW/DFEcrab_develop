# DFEcrab 快速参考指南

## 常用命令

### 启动
```bash
# TUI 模式（默认）
./dfecrab

# Server 模式
./dfecrab server

# Gateway 管理
./dfecrab gateway start
./dfecrab gateway stop
./dfecrab gateway restart
```

### 智能体管理
```bash
# 在 TUI 内
/agents              # 列出所有智能体
/use <agent_id>      # 切换智能体
/create <agent_id>    # 创建新智能体
/delete <agent_id>    # 删除智能体
```

---

## 目录结构速查

```
DFEcrab/
├── src/                    # 源代码
│   ├── core/              # 核心组件
│   │   ├── gateway/       # 网关
│   │   └── tui/          # 终端界面
│   ├── services/         # 服务层
│   ├── plugins/          # 插件系统
│   └── routing/          # 路由系统
├── agents/               # 智能体数据
│   ├── 阿蟹/
│   ├── 孝蟹/
│   └── default/
├── skills/               # 技能
├── tests/                # 测试
└── logs/                 # 日志
```

---

## 核心文件速查

| 功能 | 文件 |
|------|------|
| 网关入口 | `src/core/gateway/gateway_v2.py` |
| 智能体管理 | `src/services/agent_service.py` |
| 技能服务 | `src/services/skill_service.py` |
| 记忆服务 | `src/services/memory_service.py` |
| 消息总线 | `src/services/message_bus.py` |
| 配置管理 | `src/config/config.py` |

---

## API 端点

```bash
# 健康检查
curl http://localhost:6789/health

# 聊天对话 (v2版本)
curl -X POST http://localhost:6789/api/v2/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 查看所有会话
curl http://localhost:6789/api/v2/sessions

# 查看任务列表
curl http://localhost:6789/api/v2/tasks
```

---

## 新增功能（V2）

### 1. 服务发现
```python
from src.services.discovery_service import discovery_service

# 发现节点
nodes = await discovery_service.discover_nodes()

# 发现服务
services = await discovery_service.discover_services()

# 按能力查找
services = await discovery_service.find_services_by_capability("agent_management")
```

### 2. 插件系统
```python
from src.plugins import get_plugin_registry, get_plugin_loader

# 获取插件注册中心
registry = get_plugin_registry()

# 加载所有插件
loader = get_plugin_loader()
await loader.load_all()

# 列出已加载插件
plugins = registry.list_plugins()
```

### 3. 消息路由
```python
from src.routing import get_message_router, RouteRule, ChannelType

router = get_message_router()

# 添加渠道
router.add_channel(local_channel)

# 添加规则
rule = RouteRule(
    name="测试规则",
    priority=10,
    agent_id="target_agent",
    channel_type=ChannelType.LOCAL
)
router.add_rule(rule)
```

### 4. 会话管理
```python
from src.services.session_manager import session_manager

# 创建会话
session = await session_manager.create_session("agent_id")

# 添加消息
await session_manager.add_message(session_id, "user", "你好", tokens=10)

# 检查是否需要压缩
needs_compaction = await session_manager.check_compaction_needed(session_id)
```

### 5. 记忆压缩
```python
from src.services.memory_compaction import memory_compaction_service

# 添加记忆
entry_id = await memory_compaction_service.add_memory(
    agent_id="agent1",
    content="重要信息",
    memory_type="short_term",
    importance=0.8
)

# 搜索记忆
results = await memory_compaction_service.search_memory("agent1", "关键词")
```

---

## 配置示例

### dfecrab.json
```json
{
  "gateway": {
    "host": "0.0.0.0",
    "http_port": 6789,
    "ws_port": 6790
  },
  "models": {
    "default": {
      "model_type": "openai",
      "model_name": "gpt-4"
    }
  }
}
```

### 智能体配置 (agents/{id}/config.json)
```json
{
  "name": "阿蟹",
  "model": "default",
  "personality": "helpful",
  "tools": ["web_search", "calculator"]
}
```

---

## 测试命令

```bash
# 架构测试
python3 test_architecture.py

# Gateway 核心测试
python3 test_gateway_core.py

# 插件系统测试
python3 test_plugins.py

# 路由系统测试
python3 test_routing.py

# 会话记忆测试
python3 test_session_memory.py

# 服务发现测试
python3 test_discovery.py
```

---

## 日志位置

```bash
# Gateway 日志
tail -f logs/gateway.log

# TUI 历史
cat .tui_history
```

---

## 常见问题

### Q: Gateway 无法启动？
```bash
# 检查端口占用
lsof -i :6789

# 查看日志
tail -f logs/gateway.log
```

### Q: 智能体之间无法通信？
```bash
# 检查服务发现
python3 test_discovery.py

# 检查消息总线
curl http://localhost:6789/api/services
```

### Q: 如何添加新技能？
1. 在 `skills/` 目录创建技能文件夹
2. 编写 `SKILL.md` 定义技能
3. 编写 `execute.py` 实现技能
4. 重启 Gateway

---

## 联系方式

- 项目: https://github.com/your-repo/dfecrab
- 文档: 参见 PROJECT_OVERVIEW.md
