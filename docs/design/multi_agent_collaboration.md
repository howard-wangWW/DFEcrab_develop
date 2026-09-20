# DFEcrab 多智能体组团协作设计方案

## 一、功能设计方案

### 1.1 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    DFEcrab Gateway                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Multi-Agent Collaboration Layer              │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌───────────┐ │  │
│  │  │  Agent Registry │  │  Task Planner   │  │  Result   │ │  │
│  │  │  (智能体注册)   │  │  (任务规划)     │  │  Aggregator│ │  │
│  │  └─────────────────┘  └─────────────────┘  └───────────┘ │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │         Agent Communication Bus (ACB)               │  │  │
│  │  │    消息路由 | 主题订阅 | 点对点通信 | 广播          │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Agent Adapter Layer                          │  │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌────────┐ │  │
│  │  │ DFEcrab   │  │ QwenCode  │  │CodeBuddy  │  │Custom  │ │  │
│  │  │ Adapter   │  │ Adapter   │  │ Adapter   │  │Adapter │ │  │
│  │  │ (本地)    │  │ (CLI)     │  │ (CLI/API) │  │(插件)  │ │  │
│  │  └───────────┘  └───────────┘  └───────────┘  └────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  DFEcrab      │    │  QwenCode     │    │  CodeBuddy    │
│  (本地进程)   │    │  (CLI 工具)   │    │  (CLI/API)    │
└───────────────┘    └───────────────┘    └───────────────┘
```

### 1.2 核心能力

| 能力 | 说明 | 实现方式 |
|------|------|----------|
| **智能体注册发现** | 自动发现和注册可用的智能体 | 适配器模式 + 健康检查 |
| **角色分工** | 设计/实现/测试/审查等角色 | 角色标签 + 能力描述 |
| **任务分配** | 自动分解和分配任务给智能体 | 任务规划器 + 策略引擎 |
| **通信协调** | 智能体之间消息传递 | 发布订阅 + 点对点 |
| **结果聚合** | 汇总多个智能体的输出 | 结果聚合器 |
| **冲突解决** | 处理智能体之间的分歧 | 投票机制 + 仲裁 |

### 1.3 协作模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **链式协作** | 智能体按顺序执行任务 | 需求分析→编码→审查 |
| **并行协作** | 多个智能体同时执行 | 编码 + 测试并行 |
| **专家咨询** | 调用特定智能体的专长 | 代码生成/安全审查 |
| **自主协商** | 智能体自主协商分配 | 复杂任务分解 |
| **投票决策** | 多个智能体投票决定 | 方案选择/代码审查 |

---

## 二、接口设计

### 2.1 RESTful API

```yaml
# 多智能体协作 API

POST /api/multi-agent/chat
  描述：多智能体协作对话
  请求体:
    message: string          # 用户输入
    mode: "chain" | "parallel" | "expert" | "negotiate" | "vote"
    agents: string[]         # 参与的智能体 ID 列表
    roles:                   # 角色分配（可选）
      designer: string
      developer: string
      reviewer: string
      tester: string
    options:
      timeout: number        # 超时时间（秒）
      max_iterations: number # 最大迭代次数
      require_consensus: boolean  # 是否需要一致同意
  响应:
    task_id: string
    status: "pending" | "running" | "completed" | "failed"
    result:
      input: string
      steps: StepResult[]
      final_output: string
      metadata: object

GET /api/multi-agent/tasks/{task_id}
  描述：查询任务状态

POST /api/multi-agent/tasks/{task_id}/cancel
  描述：取消任务

GET /api/multi-agent/agents
  描述：列出所有可用智能体

GET /api/multi-agent/roles
  描述：列出所有可用角色
```

### 2.2 内部接口（Python）

```python
# src/core/multi_agent/orchestrator.py

class MultiAgentOrchestrator:
    """多智能体编排器"""

    async def chat(
        self,
        message: str,
        mode: str = "chain",
        agents: List[str] = None,
        roles: Dict[str, str] = None,
        options: Dict = None
    ) -> TaskResult:
        """发起多智能体协作"""
        pass


# src/core/multi_agent/communication_bus.py

class AgentCommunicationBus:
    """智能体通信总线 (ACB)"""

    async def publish(self, topic: str, message: AgentMessage) -> None:
        """发布消息到主题"""
        pass

    async def subscribe(
        self,
        agent_id: str,
        topics: List[str],
        callback: Callable[[AgentMessage], None]
    ) -> Subscription:
        """订阅主题"""
        pass


# src/core/multi_agent/adapter.py

class BaseAgentAdapter(ABC):
    """智能体适配器基类"""

    @abstractmethod
    async def chat(self, message: str, context: Dict = None) -> str:
        """与智能体对话"""
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        """健康检查"""
        pass
```

---

## 三、数据结构设计

### 3.1 核心数据模型

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime


class AgentType(str, Enum):
    """智能体类型"""
    LOCAL = "local"      # 本地进程（DFEcrab）
    CLI = "cli"          # CLI 工具（QwenCode, CodeBuddy）
    API = "api"          # HTTP API
    PLUGIN = "plugin"    # 插件


class AgentStatus(str, Enum):
    """智能体状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CollaborationMode(str, Enum):
    """协作模式"""
    CHAIN = "chain"           # 链式
    PARALLEL = "parallel"     # 并行
    EXPERT = "expert"         # 专家咨询
    NEGOTIATE = "negotiate"   # 自主协商
    VOTE = "vote"             # 投票决策


@dataclass
class AgentInfo:
    """智能体信息"""
    id: str
    name: str
    type: AgentType
    description: str = ""
    roles: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.OFFLINE
    adapter: str = ""  # 适配器类名
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentMessage:
    """智能体消息"""
    id: str
    from_agent: str
    to_agent: Optional[str]  # None 表示广播
    topic: str
    content: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: str
    agent_id: str
    action: str
    input: str
    output: str
    status: str  # success, failed, skipped
    error: Optional[str] = None
    duration: float = 0.0


@dataclass
class TaskResult:
    """任务结果"""
    task_id: str
    input: str
    mode: CollaborationMode
    status: TaskStatus
    steps: List[StepResult] = field(default_factory=list)
    final_output: str = ""
    error: Optional[str] = None
    progress: int = 0  # 0-100
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
```

---

## 四、实现步骤

### 阶段一：基础架构

1. **创建模块目录结构**
   ```
   src/core/multi_agent/
   ├── __init__.py
   ├── orchestrator.py        # 编排器
   ├── communication_bus.py   # 通信总线
   ├── adapter.py             # 适配器基类
   ├── registry.py            # 智能体注册表
   ├── task_planner.py        # 任务规划器
   ├── result_aggregator.py   # 结果聚合器
   └── models.py              # 数据模型
   ```

2. **实现数据模型**（`models.py`）

3. **实现适配器基类**（`adapter.py`）

4. **实现智能体注册表**（`registry.py`）

5. **实现通信总线**（`communication_bus.py`）

6. **集成到 Gateway**

### 阶段二：核心功能

7. **实现任务规划器**（`task_planner.py`）

8. **实现编排器**（`orchestrator.py`）

9. **实现结果聚合器**（`result_aggregator.py`）

10. **实现投票决策机制**

11. **实现自主协商模式**

12. **实现任务持久化**

13. **实现消息历史**

### 阶段三：接口和 UI

14. **实现 RESTful API**

15. **实现 WebSocket 支持**

16. **实现 TUI 多智能体视图**

17. **实现 CLI 命令**

### 阶段四：测试和文档

18. **编写单元测试**

19. **编写集成测试**

20. **编写文档**

21. **性能优化**

22. **发布**

---

## 五、配置文件示例

```yaml
# config/multi_agent.yaml

agents:
  dfecrab:
    enabled: true
    type: local
    name: "DFEcrab"
    roles: ["coordinator", "memory_manager"]
    capabilities: ["task_planning", "memory_management"]

  qwencode:
    enabled: true
    type: cli
    name: "QwenCode"
    roles: ["developer", "coder"]
    capabilities: ["code_generation", "debugging"]
    cli_command: "qwen"
    timeout: 120

  codebuddy:
    enabled: true
    type: cli
    name: "CodeBuddy"
    roles: ["reviewer", "tester"]
    capabilities: ["code_review", "testing"]
    cli_command: "codebuddy"
    timeout: 120

roles:
  designer:
    name: "设计师"
    skills: ["architecture", "design_pattern"]

  developer:
    name: "开发者"
    skills: ["coding", "debugging"]

  reviewer:
    name: "审查者"
    skills: ["code_review", "security"]

  tester:
    name: "测试者"
    skills: ["testing", "qa"]

orchestrator:
  default_timeout: 300
  max_iterations: 10
  retry_on_failure: true
```
