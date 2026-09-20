# DFEcrab 未来发展规划

## 版本路线图

| 版本 | 状态 | 预计时间 | 主要目标 |
|------|------|----------|----------|
| **v4.0** | ✅ 已发布 | 2026-04 | 微内核 + 插件化架构基础 |
| **v4.1** | 🔜 计划中 | Q2 2026 | 增强功能完善 |
| **v5.0** | 📍 愿景规划 | 未来 | 企业级特性 |

---

## v4.1 功能规划 (Q2 2026)

### 1. 权限系统 🔜

**目标：** 实现分级权限控制，防止破坏性操作

#### 1.1 四级权限模型

| 级别 | 名称 | 描述 |
|------|------|------|
| Level 0 | Read-only | 只读权限，仅可查询信息 |
| Level 1 | Write | 允许文件读写、代码执行 |
| Level 2 | Shell | 允许执行系统命令 |
| Level 3 | Unsafe | 高风险操作（需二次确认） |

#### 1.2 破坏性命令检测

**高风险模式识别：**
```python
DESTRUCTIVE_PATTERNS = [
    r"rm\s+-rf\s+/",           # 删除根目录
    r"dd\s+if=.*of=/dev",       # 磁盘写入
    r"shutdown\s+-h",           # 关机命令
    r"git\s+reset\s+--hard",    # 强制重置
    r"chmod\s+[0-7]*7",         # 权限修改
]
```

#### 1.3 API 设计

```python
# 权限检查 API
POST /api/permissions/check
{
  "command": "rm -rf /tmp/test",
  "user_level": 2,
  "context": {"agent_id": "default"}
}

# 返回结果
{
  "allowed": false,
  "reason": "Detected destructive command: rm -rf",
  "required_level": 3
}
```

#### 1.4 实现计划

- [ ] `src/core/security/permissions.py` - 权限引擎
- [ ] `src/core/security/command_safety.py` - 命令安全检查
- [ ] AgentService 集成权限检查中间件
- [ ] CLI 二次确认提示

---

### 2. 斜杠命令系统 🔜

**目标：** 提供本地快捷指令，减少模型调用成本

#### 2.1 核心命令列表

| 命令 | 功能 | 说明 |
|------|------|------|
| `/help` | 显示帮助 | 列出所有可用命令 |
| `/agents` | 智能体管理 | list/create/switch/delete |
| `/skills` | 技能管理 | list/install/uninstall |
| `/memory` | 记忆操作 | view/compact/cleanup |
| `/status` | 系统状态 | 显示服务健康信息 |
| `/clear` | 清屏 | 清除对话历史 |
| `/token` | Token 统计 | 当前会话 token 用量 |
| `/session` | 会话管理 | list/save/load |
| `/version` | 版本信息 | DFEcrab 版本号 |
| `/exit` / `quit` | 退出程序 | 优雅关闭服务 |

#### 2.2 处理流程

```
用户输入: "/help"
    │
    ▼
┌──────────────────────────┐
│ SlashCommandProcessor    │
│ 1. parse()               │
│ 2. find_handler()        │
│ 3. check_permission()    │
│ 4. execute()             │
└──────────────────────────┘
    │
    ▼
返回结果 (不经过模型)
```

#### 2.3 API 设计

```python
# 斜杠命令处理器
async def handle_slash_command(
    command: str, 
    args: List[str],
    context: Context
) -> SlashCommandResult:
    """
    Returns:
        SlashCommandResult {
            handled: bool,      # 是否已处理
            should_query: bool, # 是否需要模型查询
            output: str,        # 输出内容
            transcript: List    # 对话记录更新
        }
    """
```

#### 2.4 实现计划

- [ ] `src/core/commands/slash_commands.py` - 命令处理器
- [ ] `/help`, `/status`, `/clear` 基础命令
- [ ] `/agents` 子命令实现
- [ ] `/skills` 子命令实现
- [ ] TUI 集成快捷键处理

---

### 3. Agent 增强循环 🔜

**目标：** 优化对话流程，支持流式输出

#### 3.1 完整编程循环

```python
async def enhanced_agent_loop(
    agent_id: str,
    prompt: str,
    max_turns: int = 12
) -> AgentRunResult:
    """
    增强型 Agent 对话循环
    
    Features:
    - Slash command preprocessing (斜杠命令预处理)
    - Tool permission checking (工具权限检查)
    - Streaming output support (流式输出)
    - Session persistence (会话持久化)
    """
```

#### 3.2 流式输出接口

```python
async def chat_stream(
    agent_id: str, 
    message: str
) -> AsyncGenerator[str, None]:
    """
    流式对话
    
    输出格式：
    - Text chunks (文本片段)
    - Tool call events (工具调用事件)
    - Final result (最终结果)
    """
```

#### 3.3 API 设计

```bash
# 流式对话端点
curl -N http://localhost:6789/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "default", "message": "分析电网故障"}'

# 输出格式 (Server-Sent Events)
event: text
data: "正在分析电网故障..."

event: tool_call
data: {"name": "file_read", "args": {"path": "logs/fault.log"}}

event: result
data: {"status": "success", "output": "..."}
```

#### 3.4 实现计划

- [ ] `src/core/agent/enhanced_loop.py` - 增强循环引擎
- [ ] Stream output handler (流式输出处理器)
- [ ] Tool execution streaming (工具执行流式)
- [ ] WebSocket/SSE支持

---

### 4. 统一工具系统 🔜

**目标：** 标准化核心能力，提供元能力框架

#### 4.1 7 个核心元能力

| 元能力 | 功能 | 用途场景 |
|--------|------|----------|
| `execute_python` | Python 代码执行 | 数据处理、算法计算 |
| `file_read` | 文件读取 | 查看配置、日志、文档 |
| `file_write` | 文件写入 | 创建/修改配置文件 |
| `file_list` | 目录列表 | 项目结构探索 |
| `file_delete` | 删除文件 | 清理临时资源 |
| `skill_create` | 技能创建 | 动态扩展能力 |
| `shell_command` | Shell 命令执行 | 系统操作 |

#### 4.2 Tool Definition 标准化

```python
@dataclass
class ToolDefinition:
    name: str                      # 工具名称
    description: str               # 功能描述  
    parameters: Dict[str, Any]     # 参数定义 (JSON Schema)
    handler: Callable              # 执行函数
    permission_level: int = 1      # 所需权限级别
    is_streaming: bool = False     # 是否支持流式输出
```

#### 4.3 实现计划

- [ ] `src/core/tools/unified_tools.py` - 工具注册中心
- [ ] ToolDefinition dataclass 定义
- [ ] 7 个核心元能力实现
- [ ] 动态工具发现机制

---

## v5.0 愿景规划 (未来)

### 1. 会话完整持久化 📍

**目标：** 支持会话快照、回放与分享

#### 功能特性

```python
class SessionPersistence:
    """会话持久化管理"""
    
    def save_session(
        self, 
        session_id: str,
        transcript: List[Turn],
        file_history: Dict[str, FileEntry]
    ) -> Path
    
    def load_session(self, session_id: str) -> SessionSnapshot
    
    def replay_session(
        self, 
        session_id: str,
        on_chunk: Callable[[str], None]
    ) -> AsyncGenerator[str, None]
    
    def export_session(
        self, 
        session_id: str, 
        format: Literal["json", "markdown"]
    ) -> Path
```

#### 存储结构

```
data/sessions/
├── {session_id}.json              # 完整快照
├── {session_id}_transcript.json   # 纯对话记录  
├── {session_id}_history.json      # 文件访问历史
└── {session_id}.md                # Markdown 导出
```

---

### 2. 上下文引擎 📍

**目标：** 智能上下文管理、Token 用量控制

#### 功能特性

- **CLAUDE.md 自动发现**
  - 当前目录 CLAUDE.md
  - .claude/CLAUDE.md  
  - CLAUDE.local.md
  - .claude/rules/*.md

```python
async def discover_memory_bundle() -> ContextBundle:
    """
    发现并加载上下文配置文件
    
    Returns:
        ContextBundle {
            project_rules: str,     # 项目规则
            git_status: GitStatus,  # Git 状态快照
            token_usage: TokenUsage # Token 用量统计
        }
    """
```

- **Token 用量估算**
  ```python
  class TokenEstimator:
      def estimate(self, text: str) -> int: ...
      def remaining_budget(self) -> int: ...
      def truncate_if_needed(self, messages: List) -> List: ...
  ```

---

### 3. 工作区配置驱动 📍

**目标：** Markdown 配置文件驱动智能体行为

#### 支持的文件

| 文件 | 用途 | 说明 |
|------|------|------|
| `AGENTS.md` | 智能体定义 | 多智能体角色与能力 |
| `SOUL.md` | 智能体灵魂 | 人格设定、价值观 |
| `TOOLS.md` | 工具配置 | 可用工具列表说明 |
| `USER.md` | 用户画像 | 用户偏好与习惯 |
| `HEARTBEAT.md` | 心跳任务 | 定期自动执行任务 |

#### 示例：AGENTS.md

```markdown
# DFEcrab Agents

## default - 主助手
- **角色**: 电网运维智能助手
- **能力**: 故障分析、配置查询、报告生成
- **技能**: file_read, execute_python, grid_query

## analyst - 数据分析专家  
- **角色**: 电力数据分析师
- **能力**: 数据统计、趋势预测、异常检测
- **技能**: execute_python, data_visualization
```

#### 实现计划

- [ ] `src/core/workspace/config.py` - 配置解析器
- [ ] AGENTS.md 解析与智能体初始化
- [ ] SOUL.md 人格注入机制
- [ ] HEARTBEAT 任务自动调度

---

### 4. 自我反思与持续改进 📍

**目标：** AI 驱动的自优化能力

#### 功能特性

```python
class SelfReflector:
    """智能体自我反思引擎"""
    
    async def periodic_reflection(self, agent_id: str) -> ReflectionReport:
        """
        定期自动反思 (每 24 小时)
        
        分析维度：
        - 用户满意度评估
        - 常见问题分析
        - 改进建议生成
        """
    
    async def analyze_interaction(
        self, 
        transcript: List[Turn]
    ) -> InteractionAnalysis:
        """单次对话反思"""
```

#### 输出示例

```markdown
## 🤔 自我反思报告 (2026-04-15)

### 用户满意度评分：8.5/10

**优点：**
- ✅ 故障分析响应速度快
- ✅ 配置查询准确率高

**待改进：**
- ⚠️ 复杂场景下理解不够深入
- ⚠️ 建议提供更多可视化选项

**行动计划：**
1. 学习更多电网专业知识
2. 集成数据可视化工具
3. 优化长上下文理解能力
```

---

## 🏗️ 架构演进规划

### v4.1 架构调整

```
src/
├── core/
│   ├── security/           # [新增] 权限系统
│   ├── commands/           # [新增] 斜杠命令
│   ├── tools/              # [新增] 统一工具
│   └── agent/              # [重构] Agent 核心
```

### v5.0 架构升级

```
src/
├── core/
│   ├── context/            # [新增] 上下文引擎
│   ├── workspace/          # [新增] 工作区配置
│   └── reflection/         # [新增] 自我反思
├── persistence/            # [重构] 会话持久化层
└── models/                 # [新增] 领域模型
```

---

## 📊 开发进度跟踪

### v4.1 里程碑

| 里程碑 | 状态 | 预计完成 |
|--------|------|----------|
| M1: 权限系统基础框架 | 🔜 待开始 | 2026-05-01 |
| M2: 斜杠命令实现 | 🔜 待开始 | 2026-05-15 |
| M3: Agent 增强循环 | 🔜 待开始 | 2026-06-01 |
| M4: 统一工具系统 | 🔜 待开始 | 2026-06-15 |
| **v4.1 Release** | 📅 计划中 | 2026-06-30 |

### v5.0 探索方向

- [ ] 分布式部署支持 (多节点)
- [ ] 实时协作功能
- [ ] 可视化监控仪表盘
- [ ] 第三方插件市场

---

## 🤝 贡献指南

欢迎参与 DFEcrab 的未来开发！

### 如何参与

1. **选择目标版本** - v4.1 (近期) / v5.0 (远期)
2. **认领功能模块** - 查看 issue 列表或自行创建
3. **实现与测试** - 遵循项目代码规范
4. **提交 PR** - 等待 Code Review

### 开发环境设置

```bash
git clone https://github.com/DFEcrab/DFEcrab.git
cd DFEcrab
pip install -e ".[dev]"

# 运行测试
pytest tests/
```

---

## 📝 更新日志

- **2026-04-06**: 创建未来规划文档，梳理 v4.1/v5.0 功能蓝图
- **2026-04-03**: v4.0 架构重构完成

---

**维护者：** DFEcrab Team  
**最后更新:** 2026-04-06  
**状态：** 开放规划中，欢迎社区参与
