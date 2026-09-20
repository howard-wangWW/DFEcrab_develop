# 多CLI并行运行架构设计

## 一、需求分析

### 核心需求

1. **多CLI并行运行** - 多个终端/CLI可以同时运行
2. **共享项目记忆** - 所有CLI共享同一份项目级别的记忆
3. **独立工作记忆** - 每个CLI有自己独立的工作记忆和技能状态
4. **CLI间交互** - CLI之间可以通信和协作

### 记忆层级划分

```
┌─────────────────────────────────────────────────────────┐
│                    共享记忆层                            │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Level 4: 企业策略 (~/.dfecrab/enterprise.md)    │   │
│  │  Level 3: 项目记忆 (./DFECRAB.md)                │   │
│  └─────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│                    独立记忆层                            │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
│  │ CLI-1   │  │ CLI-2   │  │ CLI-3   │  │ CLI-N   │   │
│  │ 工作记忆 │  │ 工作记忆 │  │ 工作记忆 │  │ 工作记忆 │   │
│  │ 自动记忆 │  │ 自动记忆 │  │ 自动记忆 │  │ 自动记忆 │   │
│  │ 会话状态 │  │ 会话状态 │  │ 会话状态 │  │ 会话状态 │   │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## 二、架构设计

### 整体架构

```
                        ┌──────────────────┐
                        │   中央协调器      │
                        │   (Coordinator)  │
                        └────────┬─────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│    CLI-1      │       │    CLI-2      │       │    CLI-N      │
│               │       │               │       │               │
│ ┌───────────┐ │       │ ┌───────────┐ │       │ ┌───────────┐ │
│ │ 会话上下文 │ │       │ │ 会话上下文 │ │       │ │ 会话上下文 │ │
│ └───────────┘ │       └───────────┘ │       │ └───────────┘ │
│ ┌───────────┐ │       │ ┌───────────┐ │       │ ┌───────────┐ │
│ │ 工作记忆   │ │       │ │ 工作记忆   │ │       │ │ 工作记忆   │ │
│ └───────────┘ │       │ └───────────┘ │       │ └───────────┘ │
│ ┌───────────┐ │       │ ┌───────────┐ │       │ ┌───────────┐ │
│ │ 技能状态   │ │       │ │ 技能状态   │ │       │ │ 技能状态   │ │
│ └───────────┘ │       │ └───────────┘ │       │ └───────────┘ │
└───────┬───────┘       └───────┬───────┘       └───────┬───────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │      共享资源层       │
                    │  ┌─────────────────┐  │
                    │  │   项目记忆       │  │
                    │  │   插件注册表     │  │
                    │  │   工具执行器     │  │
                    │  └─────────────────┘  │
                    └───────────────────────┘
```

### 核心组件

1. **CLIContext** - CLI上下文，管理单个CLI实例的所有状态
2. **Coordinator** - 中央协调器，管理CLI间的通信
3. **SharedResourceManager** - 共享资源管理器
4. **WorkMemoryManager** - 工作记忆管理器（每个CLI独立）

---

## 三、详细设计

### 3.1 CLIContext - CLI上下文

```python
@dataclass
class CLIContext:
    """单个CLI实例的上下文"""
    # 标识
    cli_id: str                    # CLI唯一标识
    session_id: str                # 当前会话ID
    created_at: datetime           # 创建时间
    
    # 独立状态
    working_memory: WorkMemory     # 工作记忆（独立）
    skill_state: Dict[str, Any]    # 技能状态（独立）
    conversation_history: List     # 对话历史（独立）
    
    # 共享资源引用
    project_memory: 'SharedMemory' # 项目记忆（共享）
    plugin_registry: 'PluginRegistry'  # 插件注册表（共享）
    tool_executor: 'ToolExecutor'  # 工具执行器（共享）
    
    # 元数据
    metadata: Dict[str, Any]       # 其他元数据
```

### 3.2 WorkMemory - 工作记忆

```python
@dataclass
class WorkMemory:
    """工作记忆（每个CLI独立）"""
    cli_id: str
    
    # 当前任务上下文
    current_task: Optional[str] = None
    task_context: Dict[str, Any] = field(default_factory=dict)
    
    # 临时变量
    variables: Dict[str, Any] = field(default_factory=dict)
    
    # 短期记忆
    short_term: List[str] = field(default_factory=list)
    
    # 自动记忆（独立）
    auto_memory_path: Optional[Path] = None
    
    # 技能调用历史
    skill_history: List[Dict] = field(default_factory=list)
    
    def set(self, key: str, value: Any):
        """设置变量"""
        self.variables[key] = value
    
    def get(self, key: str, default=None) -> Any:
        """获取变量"""
        return self.variables.get(key, default)
    
    def add_observation(self, observation: str):
        """添加观察"""
        self.short_term.append(observation)
```

### 3.3 Coordinator - 中央协调器

```python
class Coordinator:
    """多CLI协调器"""
    
    def __init__(self, project_dir: Path, runtime_dir: Path):
        self.project_dir = project_dir
        self.runtime_dir = runtime_dir
        
        # CLI注册表
        self._cli_contexts: Dict[str, CLIContext] = {}
        
        # 共享资源
        self._shared_memory: Optional[SharedMemory] = None
        self._plugin_registry: Optional[PluginRegistry] = None
        self._tool_executor: Optional[ToolExecutor] = None
        
        # 消息队列（CLI间通信）
        self._message_queue: asyncio.Queue = None
        self._subscriptions: Dict[str, List[str]] = {}  # topic -> [cli_id]
    
    async def create_cli(self, cli_id: str = None) -> CLIContext:
        """创建新的CLI上下文"""
        if cli_id is None:
            cli_id = str(uuid.uuid4())[:8]
        
        context = CLIContext(
            cli_id=cli_id,
            session_id=str(uuid.uuid4()),
            created_at=datetime.now(),
            working_memory=WorkMemory(cli_id=cli_id),
            skill_state={},
            conversation_history=[],
            project_memory=self._shared_memory,
            plugin_registry=self._plugin_registry,
            tool_executor=self._tool_executor
        )
        
        self._cli_contexts[cli_id] = context
        return context
    
    async def send_message(self, from_cli: str, to_cli: str, message: Any):
        """CLI间消息发送"""
        ...
    
    async def broadcast(self, from_cli: str, message: Any):
        """广播消息"""
        ...
    
    async def get_other_clis(self, cli_id: str) -> List[str]:
        """获取其他CLI列表"""
        return [cid for cid in self._cli_contexts if cid != cli_id]
```

---

## 四、实现方案

### 目录结构

```
src/core/multi_cli/
├── __init__.py
├── context.py           # CLIContext, WorkMemory
├── coordinator.py       # Coordinator
├── shared_resources.py  # SharedResourceManager
├── communication.py     # CLI间通信
└── cli_manager.py       # CLI生命周期管理
```

### 文件详解

#### context.py

```python
"""CLI上下文定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import uuid


@dataclass
class WorkMemory:
    """工作记忆（每个CLI独立）"""
    cli_id: str
    current_task: Optional[str] = None
    task_context: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    short_term: List[str] = field(default_factory=list)
    skill_history: List[Dict] = field(default_factory=list)
    
    def set(self, key: str, value: Any):
        self.variables[key] = value
    
    def get(self, key: str, default=None) -> Any:
        return self.variables.get(key, default)
    
    def remember(self, info: str):
        """记录短期记忆"""
        self.short_term.append(f"[{datetime.now().isoformat()}] {info}")
        # 限制大小
        if len(self.short_term) > 100:
            self.short_term = self.short_term[-100:]
    
    def record_skill_call(self, skill_name: str, params: Dict, result: Any):
        """记录技能调用"""
        self.skill_history.append({
            "skill": skill_name,
            "params": params,
            "result": str(result)[:200],
            "time": datetime.now().isoformat()
        })


@dataclass
class CLIContext:
    """CLI上下文"""
    cli_id: str
    session_id: str
    created_at: datetime
    working_memory: WorkMemory
    skill_state: Dict[str, Any] = field(default_factory=dict)
    conversation_history: List[Dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 共享资源引用（运行时注入）
    _shared_memory: Any = None
    _plugin_registry: Any = None
    _tool_executor: Any = None
    
    @classmethod
    def create(cls, cli_id: str = None) -> 'CLIContext':
        """创建新的CLI上下文"""
        if cli_id is None:
            cli_id = f"cli_{uuid.uuid4().hex[:8]}"
        
        return cls(
            cli_id=cli_id,
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            created_at=datetime.now(),
            working_memory=WorkMemory(cli_id=cli_id)
        )
    
    def add_message(self, role: str, content: str):
        """添加对话消息"""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "time": datetime.now().isoformat()
        })
        # 限制历史长度
        if len(self.conversation_history) > 100:
            self.conversation_history = self.conversation_history[-100:]
    
    def get_memory_context(self) -> str:
        """获取完整的记忆上下文"""
        parts = []
        
        # 共享的项目记忆
        if self._shared_memory:
            parts.append("## 项目记忆\n" + self._shared_memory.get_project_memory())
        
        # 独立的工作记忆
        parts.append("## 当前任务")
        parts.append(f"任务: {self.working_memory.current_task or '无'}")
        
        if self.working_memory.short_term:
            parts.append("\n## 短期记忆")
            parts.extend(self.working_memory.short_term[-10:])
        
        return "\n".join(parts)
```

#### coordinator.py

```python
"""中央协调器"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import uuid

from .context import CLIContext, WorkMemory


@dataclass
class CLIMessage:
    """CLI间消息"""
    id: str
    from_cli: str
    to_cli: Optional[str]  # None 表示广播
    topic: str
    content: Any
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "from_cli": self.from_cli,
            "to_cli": self.to_cli,
            "topic": self.topic,
            "content": self.content,
            "timestamp": self.timestamp.isoformat()
        }


class Coordinator:
    """多CLI协调器"""
    
    def __init__(self, project_dir: Path, runtime_dir: Path):
        self.project_dir = Path(project_dir)
        self.runtime_dir = Path(runtime_dir)
        
        # CLI注册表
        self._cli_contexts: Dict[str, CLIContext] = {}
        
        # 共享资源（延迟初始化）
        self._shared_memory = None
        self._plugin_registry = None
        self._tool_executor = None
        
        # 消息系统
        self._message_queue: asyncio.Queue = None
        self._cli_queues: Dict[str, asyncio.Queue] = {}  # 每个CLI的消息队列
        self._subscriptions: Dict[str, List[str]] = {}  # topic -> [cli_id]
        
        # 状态
        self._running = False
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """初始化协调器"""
        # 初始化共享资源
        await self._init_shared_resources()
        
        # 创建消息队列
        self._message_queue = asyncio.Queue()
        
        # 启动消息处理
        self._running = True
        asyncio.create_task(self._process_messages())
        
        print(f"[Coordinator] 已初始化: project={self.project_dir}")
    
    async def _init_shared_resources(self):
        """初始化共享资源"""
        # 导入并初始化共享资源
        from src.core.memory.v4 import FourLayerMemoryManager
        from src.core.plugins.v2 import PluginManagerV2
        from src.core.tools import ToolExecutor
        
        # 共享记忆
        self._shared_memory = FourLayerMemoryManager(
            base_dir=self.project_dir,
            runtime_dir=self.runtime_dir
        )
        
        # 共享插件注册表
        self._plugin_registry = PluginManagerV2(
            plugins_dir=self.project_dir / "plugins"
        )
        await self._plugin_registry.load_all_plugins()
        
        # 共享工具执行器
        self._tool_executor = ToolExecutor()
    
    async def create_cli(self, cli_id: str = None) -> CLIContext:
        """创建新的CLI上下文"""
        async with self._lock:
            context = CLIContext.create(cli_id)
            
            # 注入共享资源
            context._shared_memory = self._shared_memory
            context._plugin_registry = self._plugin_registry
            context._tool_executor = self._tool_executor
            
            # 创建CLI专用消息队列
            self._cli_queues[context.cli_id] = asyncio.Queue()
            
            self._cli_contexts[context.cli_id] = context
            
            print(f"[Coordinator] 创建CLI: {context.cli_id}")
            return context
    
    async def destroy_cli(self, cli_id: str):
        """销毁CLI上下文"""
        async with self._lock:
            if cli_id in self._cli_contexts:
                del self._cli_contexts[cli_id]
            if cli_id in self._cli_queues:
                del self._cli_queues[cli_id]
            print(f"[Coordinator] 销毁CLI: {cli_id}")
    
    async def get_cli(self, cli_id: str) -> Optional[CLIContext]:
        """获取CLI上下文"""
        return self._cli_contexts.get(cli_id)
    
    async def list_clis(self) -> List[str]:
        """列出所有CLI"""
        return list(self._cli_contexts.keys())
    
    # ==================== CLI间通信 ====================
    
    async def send_message(
        self,
        from_cli: str,
        to_cli: str,
        topic: str,
        content: Any
    ) -> str:
        """发送点对点消息"""
        message = CLIMessage(
            id=str(uuid.uuid4()),
            from_cli=from_cli,
            to_cli=to_cli,
            topic=topic,
            content=content,
            timestamp=datetime.now()
        )
        
        if to_cli in self._cli_queues:
            await self._cli_queues[to_cli].put(message)
            return message.id
        return None
    
    async def broadcast(
        self,
        from_cli: str,
        topic: str,
        content: Any
    ) -> List[str]:
        """广播消息给所有其他CLI"""
        message_ids = []
        
        for cli_id in self._cli_contexts:
            if cli_id != from_cli:
                msg_id = await self.send_message(from_cli, cli_id, topic, content)
                if msg_id:
                    message_ids.append(msg_id)
        
        return message_ids
    
    async def publish(self, from_cli: str, topic: str, content: Any):
        """发布消息（订阅模式）"""
        subscribers = self._subscriptions.get(topic, [])
        for cli_id in subscribers:
            if cli_id != from_cli:
                await self.send_message(from_cli, cli_id, topic, content)
    
    async def subscribe(self, cli_id: str, topic: str):
        """订阅主题"""
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
        if cli_id not in self._subscriptions[topic]:
            self._subscriptions[topic].append(cli_id)
    
    async def receive_message(self, cli_id: str, timeout: float = 1.0) -> Optional[CLIMessage]:
        """接收消息（非阻塞）"""
        if cli_id not in self._cli_queues:
            return None
        
        try:
            message = await asyncio.wait_for(
                self._cli_queues[cli_id].get(),
                timeout=timeout
            )
            return message
        except asyncio.TimeoutError:
            return None
    
    async def _process_messages(self):
        """后台消息处理"""
        while self._running:
            await asyncio.sleep(0.1)
    
    # ==================== 协作功能 ====================
    
    async def ask_other_cli(
        self,
        from_cli: str,
        question: str,
        target_cli: str = None
    ) -> Optional[str]:
        """向其他CLI提问"""
        if target_cli:
            targets = [target_cli]
        else:
            # 选择一个空闲的CLI
            targets = [c for c in self._cli_contexts if c != from_cli]
            if not targets:
                return None
            targets = [targets[0]]
        
        # 发送问题
        for target in targets:
            await self.send_message(
                from_cli, target, "question", question
            )
        
        # 等待回答
        # TODO: 实现回答机制
        return None
    
    async def share_knowledge(self, from_cli: str, knowledge: str):
        """共享知识到项目记忆"""
        if self._shared_memory:
            self._shared_memory.observe(f"[{from_cli}] {knowledge}")
            await self._shared_memory.update_auto_memory()
    
    async def get_status(self) -> Dict[str, Any]:
        """获取协调器状态"""
        return {
            "running": self._running,
            "cli_count": len(self._cli_contexts),
            "clis": {
                cli_id: {
                    "session_id": ctx.session_id,
                    "created_at": ctx.created_at.isoformat(),
                    "message_count": len(ctx.conversation_history),
                    "task": ctx.working_memory.current_task
                }
                for cli_id, ctx in self._cli_contexts.items()
            }
        }
```

#### cli_manager.py

```python
"""CLI生命周期管理"""

import asyncio
from pathlib import Path
from typing import Optional

from .coordinator import Coordinator
from .context import CLIContext


class CLIManager:
    """CLI管理器 - 管理CLI的启动和交互"""
    
    _instance = None
    _coordinator = None
    
    @classmethod
    def get_instance(cls) -> 'CLIManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def get_coordinator(cls) -> Coordinator:
        return cls._coordinator
    
    def __init__(self):
        if CLIManager._instance is not None:
            raise RuntimeError("Use get_instance()")
    
    async def initialize(
        self,
        project_dir: str = None,
        runtime_dir: str = None
    ):
        """初始化管理器"""
        project_dir = Path(project_dir) if project_dir else Path.cwd()
        runtime_dir = Path(runtime_dir) if runtime_dir else Path.home() / ".dfecrab"
        
        CLIManager._coordinator = Coordinator(project_dir, runtime_dir)
        await CLIManager._coordinator.initialize()
    
    async def create_cli(self, cli_id: str = None) -> CLIContext:
        """创建新CLI"""
        return await CLIManager._coordinator.create_cli(cli_id)
    
    async def get_cli(self, cli_id: str) -> Optional[CLIContext]:
        """获取CLI"""
        return await CLIManager._coordinator.get_cli(cli_id)
    
    async def list_clis(self):
        """列出所有CLI"""
        return await CLIManager._coordinator.list_clis()


# 便捷函数
async def create_cli_session(cli_id: str = None) -> CLIContext:
    """创建CLI会话"""
    manager = CLIManager.get_instance()
    if CLIManager._coordinator is None:
        await manager.initialize()
    return await manager.create_cli(cli_id)
```

---

## 五、使用示例

### 启动多个CLI

```python
import asyncio
from src.core.multi_cli import CLIManager, create_cli_session

async def main():
    # 初始化管理器
    manager = CLIManager.get_instance()
    await manager.initialize(
        project_dir="/path/to/project",
        runtime_dir="~/.dfecrab"
    )
    
    # 创建多个CLI
    cli1 = await manager.create_cli("dev-cli")
    cli2 = await manager.create_cli("test-cli")
    cli3 = await manager.create_cli("doc-cli")
    
    # 每个CLI有独立的工作记忆
    cli1.working_memory.set("current_file", "main.py")
    cli2.working_memory.set("current_file", "test_main.py")
    
    # 共享项目记忆
    await CLIManager.get_coordinator().share_knowledge(
        "dev-cli", 
        "项目使用 Python 3.8+ 和 FastAPI"
    )

asyncio.run(main())
```

### CLI间通信

```python
# 发送消息
await coordinator.send_message(
    from_cli="dev-cli",
    to_cli="test-cli",
    topic="file_change",
    content={"file": "main.py", "action": "modified"}
)

# 接收消息
message = await coordinator.receive_message("test-cli")
if message:
    print(f"收到来自 {message.from_cli} 的消息: {message.content}")

# 广播
await coordinator.broadcast(
    from_cli="dev-cli",
    topic="notification",
    content="新功能已开发完成"
)
```

---

## 六、与现有系统集成

### 修改入口点

```python
# src/__main__.py

import asyncio
from src.core.multi_cli import CLIManager

async def main():
    # 初始化多CLI管理器
    manager = CLIManager.get_instance()
    await manager.initialize()
    
    # 创建当前CLI会话
    cli_context = await manager.create_cli()
    
    print(f"CLI ID: {cli_context.cli_id}")
    print(f"Session ID: {cli_context.session_id}")
    
    # 进入REPL或TUI
    # ...

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 七、后续优化

1. **持久化** - CLI状态的持久化和恢复
2. **负载均衡** - 多CLI任务的负载均衡
3. **协作模式** - 定义更丰富的CLI协作模式
4. **Web界面** - 提供Web界面管理多CLI
