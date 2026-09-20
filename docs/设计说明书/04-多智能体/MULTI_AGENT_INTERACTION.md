# 多智能体交互技术方案

**版本**：v4.4.0  
**创建日期**：2026-03-30  
**目标**：实现 QwenCode、CodeBuddy、DFEcrab 三个智能体之间的交互协作

---

## 📋 目录

1. [需求分析](#1-需求分析)
2. [交互模式](#2-交互模式)
3. [技术架构](#3-技术架构)
4. [实施计划](#4-实施计划)

---

## 1. 需求分析

### 1.1 现状

你有 3 个智能体在运行：

| 智能体 | 类型 | 专长 | 当前状态 |
|--------|------|------|---------|
| **QwenCode** | 通用编程助手 | 代码生成、解释、调试 | ✅ 运行中 |
| **CodeBuddy** | 编程伙伴 | 代码审查、建议、配对编程 | ✅ 运行中 |
| **DFEcrab** | 个人智能体 | 记忆管理、任务执行、个性化服务 | ✅ 运行中 |

### 1.2 问题

- ❌ 三个智能体**各自独立运行**，无法互相通信
- ❌ 用户需要在不同智能体之间**手动切换**
- ❌ 无法利用各智能体的**专长协同工作**
- ❌ 重复上下文输入，**效率低下**

### 1.3 用户需求

```
场景 1: 代码开发
👤 用户：帮我开发一个用户管理系统
期望：
  - QwenCode 负责代码生成
  - CodeBuddy 负责代码审查
  - DFEcrab 负责需求分析和进度跟踪
  - 三个智能体自动协作，无需我手动切换

场景 2: 问题诊断
👤 用户：这个 bug 我搞不定，帮帮我
期望：
  - DFEcrab 分析问题并查找相关记忆
  - QwenCode 提供修复方案
  - CodeBuddy 审查修复代码
  - 自动汇总结果给我

场景 3: 学习新知识
👤 用户：我想学习 Rust
期望：
  - DFEcrab 制定学习计划
  - QwenCode 提供代码示例
  - CodeBuddy 检查我的练习代码
  - 学习进度同步到 DFEcrab 记忆
```

---

## 2. 交互模式

### 2.1 交互层级

```
Level 1: 消息转发     - 智能体之间可以互相发送消息
Level 2: 任务委托     - 一个智能体可以将任务委托给另一个智能体
Level 3: 协同工作     - 多个智能体共同完成一个复杂任务
Level 4: 自主协商     - 智能体自主协商任务分配和执行顺序
```

### 2.2 交互模式

#### 模式 1: 链式协作（Chain）

```
用户 → DFEcrab → QwenCode → CodeBuddy → DFEcrab → 用户
       ↓          ↓           ↓           ↓
      分析       编码        审查        汇总
```

**适用场景**：代码开发、文档编写等线性流程任务

#### 模式 2: 并行协作（Parallel）

```
         ┌→ QwenCode（代码生成）────┐
用户 → DFEcrab → CodeBuddy（代码审查）──→ 汇总 → 用户
         └→ 记忆检索（历史参考）───┘
```

**适用场景**：需要多方面输入的任务

#### 模式 3: 专家咨询（Expert）

```
用户 → DFEcrab（分析）→ 识别需要 QwenCode 专长
                     → 调用 QwenCode API
                     → 接收结果并整合
                     → 返回用户
```

**适用场景**：特定领域问题

#### 模式 4: 自主协商（Negotiation）

```
用户：帮我开发一个网站

DFEcrab: 我分析需求，制定计划
QwenCode: 我负责前端和后端代码
CodeBuddy: 我负责代码审查和测试

然后各自执行分配的任务...
```

**适用场景**：复杂多步骤任务

### 2.3 对话示例

#### 场景：开发用户管理系统

```
┌─────────────────────────────────────────────────────────┐
│  👤 用户：帮我开发一个用户管理系统，需要登录注册功能      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  🦀 DFEcrab（协调者）：                                   │
│  收到！我来分析需求并协调开发工作。                      │
│                                                          │
│  📋 需求分析：                                           │
│  - 用户注册（邮箱、密码）                                │
│  - 用户登录（JWT 认证）                                   │
│  - 用户信息管理                                          │
│                                                          │
│  🔄 我将协调以下工作：                                   │
│  - @QwenCode 负责代码实现                                │
│  - @CodeBuddy 负责代码审查                               │
│  - 我负责进度跟踪和记忆                                  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  🤖 QwenCode（开发者）：                                  │
│  好的，我开始实现代码。                                  │
│                                                          │
│  ✅ 已完成：                                             │
│  1. 用户模型（models/user.py）                           │
│  2. 注册接口（api/auth.py）                              │
│  3. 登录接口（api/auth.py）                              │
│                                                          │
│  📝 代码已提交，请@CodeBuddy 审查                         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  🤖 CodeBuddy（审查者）：                                 │
│  收到，我开始代码审查。                                  │
│                                                          │
│  ✅ 审查通过：                                           │
│  - models/user.py - 设计良好                             │
│  - api/auth.py - 整体不错                                │
│                                                          │
│  ⚠️ 建议修改：                                           │
│  - 密码需要加盐哈希（建议使用 bcrypt）                   │
│  - 添加输入验证（邮箱格式、密码强度）                    │
│                                                          │
│  已提交 Code Review 评论，请@QwenCode 修改                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  🤖 QwenCode（开发者）：                                  │
│  收到建议，已修改：                                      │
│  ✅ 添加 bcrypt 密码加密                                   │
│  ✅ 添加输入验证                                         │
│                                                          │
│  代码已更新，请再次审查。                                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  🤖 CodeBuddy（审查者）：                                 │
│  ✅ 所有问题已修复，代码合并！                            │
│                                                          │
│  🎉 项目开发完成！                                       │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  🦀 DFEcrab（协调者）：                                   │
│  🎉 项目完成！我已将本次开发记录到记忆中。               │
│                                                          │
│  📊 项目统计：                                           │
│  - 开发时长：45 分钟                                      │
│  - 代码文件：3 个                                         │
│  - Code Review：2 轮                                      │
│  - 代码行数：320 行                                       │
│                                                          │
│  💾 已保存：                                              │
│  - 项目结构到 memory/projects/                           │
│  - 技术栈到 memory/tech_stack/                           │
│  - 经验教训到 memory/learnings/                          │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 技术架构

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    多智能体协作平台                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Agent Communication Bus            │   │
│  │          （智能体通信总线 - ACB）                │   │
│  │  ┌──────────┬──────────┬──────────┬──────────┐ │   │
│  │  │ Message  │  Event   │  Task    │  State   │ │   │
│  │  │ Channel  │ Channel  │ Channel  │ Channel  │ │   │
│  │  └──────────┴──────────┴──────────┴──────────┘ │   │
│  └─────────────────────────────────────────────────┘   │
│                         ↑↓                              │
│  ┌─────────────┬─────────────┬─────────────┐           │
│  │             │             │             │           │
│  │  QwenCode   │  CodeBuddy  │  DFEcrab    │           │
│  │  Adapter    │  Adapter    │  Adapter    │           │
│  │             │             │             │           │
│  └─────────────┴─────────────┴─────────────┘           │
│                         ↑↓                              │
│  ┌─────────────────────────────────────────────────┐   │
│  │           Agent Orchestrator                    │   │
│  │  - 任务分解                                      │   │
│  │  - 智能体选择                                    │   │
│  │  - 执行协调                                      │   │
│  │  - 结果汇总                                      │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 3.2 核心组件

#### 3.2.1 智能体通信总线（ACB）

```python
# src/core/agent_communication_bus.py

from enum import Enum
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import asyncio
import uuid

class MessageType(Enum):
    """消息类型"""
    CHAT = "chat"              # 聊天消息
    TASK = "task"              # 任务委托
    RESULT = "result"          # 任务结果
    QUERY = "query"            # 查询请求
    RESPONSE = "response"      # 查询响应
    EVENT = "event"            # 事件通知
    BROADCAST = "broadcast"    # 广播消息

class MessagePriority(Enum):
    """消息优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3

@dataclass
class AgentMessage:
    """智能体消息"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.CHAT
    priority: MessagePriority = MessagePriority.NORMAL
    
    sender: Optional[str] = None  # 发送者 Agent ID
    recipient: Optional[str] = None  # 接收者 Agent ID（None 表示广播）
    
    subject: str = ""  # 消息主题
    content: Any = None  # 消息内容
    
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 任务相关
    task_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    
    # 超时
    timeout_seconds: Optional[float] = None

class AgentCommunicationBus:
    """智能体通信总线"""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}  # topic -> callbacks
        self._agents: Dict[str, 'AgentAdapter'] = {}  # agent_id -> adapter
        self._message_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
    
    def register_agent(self, agent_id: str, adapter: 'AgentAdapter') -> None:
        """注册智能体"""
        self._agents[agent_id] = adapter
        adapter.acb = self
    
    def unregister_agent(self, agent_id: str) -> None:
        """注销智能体"""
        if agent_id in self._agents:
            del self._agents[agent_id]
    
    def subscribe(self, topic: str, callback: Callable) -> None:
        """订阅主题"""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)
    
    def unsubscribe(self, topic: str, callback: Callable) -> None:
        """取消订阅"""
        if topic in self._subscribers:
            self._subscribers[topic].remove(callback)
    
    async def send(self, message: AgentMessage) -> None:
        """发送消息"""
        await self._message_queue.put(message)
    
    async def broadcast(self, subject: str, content: Any, sender: str = None) -> None:
        """广播消息"""
        message = AgentMessage(
            type=MessageType.BROADCAST,
            sender=sender,
            subject=subject,
            content=content
        )
        await self.send(message)
    
    async def send_to_agent(self, agent_id: str, subject: str, content: Any, sender: str = None) -> Any:
        """发送消息到指定智能体"""
        message = AgentMessage(
            type=MessageType.CHAT,
            sender=sender,
            recipient=agent_id,
            subject=subject,
            content=content
        )
        await self.send(message)
        
        # 等待响应
        if agent_id in self._agents:
            return await self._agents[agent_id].process_message(message)
        else:
            raise ValueError(f"智能体不存在：{agent_id}")
    
    async def delegate_task(
        self,
        agent_id: str,
        task: str,
        context: Dict[str, Any] = None,
        sender: str = None
    ) -> Any:
        """委托任务给智能体"""
        message = AgentMessage(
            type=MessageType.TASK,
            sender=sender,
            recipient=agent_id,
            subject="task_delegation",
            content={
                "task": task,
                "context": context or {}
            },
            task_id=str(uuid.uuid4())
        )
        await self.send(message)
        
        if agent_id in self._agents:
            return await self._agents[agent_id].process_task(message)
        else:
            raise ValueError(f"智能体不存在：{agent_id}")
    
    async def run(self) -> None:
        """运行消息循环"""
        self._running = True
        
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0
                )
                
                # 分发消息
                await self._dispatch_message(message)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"消息循环错误：{e}")
    
    async def _dispatch_message(self, message: AgentMessage) -> None:
        """分发消息"""
        # 广播消息
        if message.type == MessageType.BROADCAST:
            topic = message.subject
            if topic in self._subscribers:
                for callback in self._subscribers[topic]:
                    try:
                        await callback(message)
                    except Exception as e:
                        logger.error(f"广播回调错误：{e}")
        
        # 点对点消息
        elif message.recipient:
            if message.recipient in self._agents:
                await self._agents[message.recipient].on_message(message)
            else:
                logger.warning(f"消息发送到不存在的智能体：{message.recipient}")
```

#### 3.2.2 智能体适配器

```python
# src/core/agent_adapter.py

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class AgentAdapter(ABC):
    """智能体适配器基类"""
    
    def __init__(self, agent_id: str, config: Dict[str, Any]):
        self.agent_id = agent_id
        self.config = config
        self.acb: Optional['AgentCommunicationBus'] = None
        self.connected = False
    
    @abstractmethod
    async def connect(self) -> bool:
        """连接到智能体"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass
    
    @abstractmethod
    async def process_message(self, message: 'AgentMessage') -> Any:
        """处理接收到的消息"""
        pass
    
    @abstractmethod
    async def process_task(self, message: 'AgentMessage') -> Any:
        """处理任务委托"""
        pass
    
    @abstractmethod
    async def chat(self, message: str, context: Dict[str, Any] = None) -> str:
        """与智能体对话"""
        pass
    
    async def on_message(self, message: 'AgentMessage') -> None:
        """消息到达时的回调"""
        # 默认实现：异步处理
        asyncio.create_task(self.process_message(message))
    
    async def send_message(self, recipient: str, subject: str, content: Any) -> None:
        """发送消息"""
        if self.acb:
            await self.acb.send_to_agent(
                agent_id=recipient,
                subject=subject,
                content=content,
                sender=self.agent_id
            )
    
    async def broadcast(self, subject: str, content: Any) -> None:
        """广播消息"""
        if self.acb:
            await self.acb.broadcast(
                subject=subject,
                content=content,
                sender=self.agent_id
            )
    
    async def delegate_task(self, agent_id: str, task: str, context: Dict = None) -> Any:
        """委托任务"""
        if self.acb:
            return await self.acb.delegate_task(
                agent_id=agent_id,
                task=task,
                context=context,
                sender=self.agent_id
            )
```

#### 3.2.3 QwenCode 适配器

```python
# src/core/adapters/qwencode_adapter.py

from src.core.agent_adapter import AgentAdapter
import httpx

class QwenCodeAdapter(AgentAdapter):
    """QwenCode 智能体适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("qwencode", config)
        self.api_url = config.get("api_url", "http://localhost:8080")
        self.api_key = config.get("api_key")
        self._client = None
    
    async def connect(self) -> bool:
        """连接到 QwenCode API"""
        try:
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            )
            
            # 健康检查
            response = await self._client.get("/health")
            if response.status_code == 200:
                self.connected = True
                return True
            return False
        except Exception as e:
            logger.error(f"连接 QwenCode 失败：{e}")
            return False
    
    async def disconnect(self) -> None:
        """断开连接"""
        if self._client:
            await self._client.aclose()
        self.connected = False
    
    async def process_message(self, message: 'AgentMessage') -> Any:
        """处理消息"""
        if message.type == MessageType.CHAT:
            return await self.chat(message.content)
        elif message.type == MessageType.TASK:
            return await self.process_task(message)
        return None
    
    async def process_task(self, message: 'AgentMessage') -> Any:
        """处理任务委托"""
        task_info = message.content
        task = task_info.get("task")
        context = task_info.get("context", {})
        
        # 调用 QwenCode API 执行任务
        response = await self._client.post(
            "/api/v1/task/execute",
            json={
                "task": task,
                "context": context
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("result")
        else:
            raise Exception(f"QwenCode 任务执行失败：{response.text}")
    
    async def chat(self, message: str, context: Dict[str, Any] = None) -> str:
        """与 QwenCode 对话"""
        response = await self._client.post(
            "/api/v1/chat",
            json={
                "message": message,
                "context": context or {}
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "")
        else:
            raise Exception(f"QwenCode 对话失败：{response.text}")
    
    async def generate_code(self, prompt: str, language: str = "python") -> str:
        """生成代码"""
        response = await self._client.post(
            "/api/v1/code/generate",
            json={
                "prompt": prompt,
                "language": language
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("code", "")
        else:
            raise Exception(f"代码生成失败：{response.text}")
```

#### 3.2.4 CodeBuddy 适配器

```python
# src/core/adapters/codebuddy_adapter.py

from src.core.agent_adapter import AgentAdapter
import httpx

class CodeBuddyAdapter(AgentAdapter):
    """CodeBuddy 智能体适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("codebuddy", config)
        self.api_url = config.get("api_url", "http://localhost:8081")
        self.api_key = config.get("api_key")
        self._client = None
    
    async def connect(self) -> bool:
        """连接到 CodeBuddy API"""
        try:
            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            )
            
            # 健康检查
            response = await self._client.get("/health")
            if response.status_code == 200:
                self.connected = True
                return True
            return False
        except Exception as e:
            logger.error(f"连接 CodeBuddy 失败：{e}")
            return False
    
    async def process_message(self, message: 'AgentMessage') -> Any:
        """处理消息"""
        if message.type == MessageType.CHAT:
            return await self.chat(message.content)
        elif message.type == MessageType.TASK:
            return await self.process_task(message)
        return None
    
    async def process_task(self, message: 'AgentMessage') -> Any:
        """处理任务委托"""
        task_info = message.content
        task = task_info.get("task")
        context = task_info.get("context", {})
        
        # 根据任务类型调用不同 API
        if task.startswith("review"):
            return await self.review_code(context.get("code", ""))
        elif task.startswith("suggest"):
            return await self.suggest_improvements(context.get("code", ""))
        else:
            return await self.chat(task)
    
    async def chat(self, message: str, context: Dict[str, Any] = None) -> str:
        """与 CodeBuddy 对话"""
        response = await self._client.post(
            "/api/v1/chat",
            json={
                "message": message,
                "context": context or {}
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "")
        else:
            raise Exception(f"CodeBuddy 对话失败：{response.text}")
    
    async def review_code(self, code: str, language: str = "python") -> Dict:
        """代码审查"""
        response = await self._client.post(
            "/api/v1/code/review",
            json={
                "code": code,
                "language": language
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            return {
                "approved": result.get("approved", False),
                "comments": result.get("comments", []),
                "suggestions": result.get("suggestions", [])
            }
        else:
            raise Exception(f"代码审查失败：{response.text}")
    
    async def suggest_improvements(self, code: str) -> List[str]:
        """建议改进"""
        response = await self._client.post(
            "/api/v1/code/suggest",
            json={"code": code}
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("suggestions", [])
        else:
            raise Exception(f"获取建议失败：{response.text}")
```

#### 3.2.5 DFEcrab 适配器

```python
# src/core/adapters/dfecrab_adapter.py

from src.core.agent_adapter import AgentAdapter
from src.core.gateway.gateway_v2 import GatewayV2

class DFECrabAdapter(AgentAdapter):
    """DFEcrab 智能体适配器"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__("dfecrab", config)
        self.gateway = None
        self.agent_id = config.get("agent_id", "default")
    
    async def connect(self) -> bool:
        """连接 DFEcrab"""
        try:
            self.gateway = GatewayV2()
            await self.gateway.initialize()
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"连接 DFEcrab 失败：{e}")
            return False
    
    async def disconnect(self) -> None:
        """断开连接"""
        if self.gateway:
            await self.gateway.shutdown()
        self.connected = False
    
    async def process_message(self, message: 'AgentMessage') -> Any:
        """处理消息"""
        if message.type == MessageType.CHAT:
            return await self.chat(message.content)
        elif message.type == MessageType.TASK:
            return await self.process_task(message)
        elif message.type == MessageType.QUERY:
            return await self.query(message.content)
        return None
    
    async def process_task(self, message: 'AgentMessage') -> Any:
        """处理任务委托"""
        task_info = message.content
        task = task_info.get("task")
        context = task_info.get("context", {})
        
        # DFEcrab 擅长分析和协调
        if "analyze" in task.lower():
            return await self.analyze_requirement(context)
        elif "coordinate" in task.lower():
            return await self.coordinate_task(context)
        elif "track" in task.lower():
            return await self.track_progress(context)
        else:
            return await self.chat(task)
    
    async def chat(self, message: str, context: Dict[str, Any] = None) -> str:
        """与 DFEcrab 对话"""
        if self.gateway:
            response = await self.gateway.route(
                message=message,
                agent_id=self.agent_id,
                context=context
            )
            return response.get("response", "")
        else:
            raise Exception("DFEcrab 未连接")
    
    async def analyze_requirement(self, context: Dict) -> Dict:
        """分析需求"""
        requirement = context.get("requirement", "")
        
        # 使用 DFEcrab 的分析能力
        analysis_prompt = f"""
请分析以下需求，并输出：
1. 功能列表
2. 技术栈建议
3. 任务分解

需求：{requirement}
"""
        analysis = await self.chat(analysis_prompt)
        
        return {
            "analysis": analysis,
            "task_list": self._extract_tasks(analysis)
        }
    
    async def coordinate_task(self, context: Dict) -> Dict:
        """协调任务"""
        # 记录到记忆
        await self.gateway.memory_manager.add_memory(
            content=f"任务协调：{context}",
            category="task_coordination"
        )
        
        return {
            "status": "coordinating",
            "message": "任务已记录，开始协调执行"
        }
    
    async def track_progress(self, context: Dict) -> Dict:
        """跟踪进度"""
        # 从记忆中获取进度
        progress = await self.gateway.memory_manager.search_memory(
            query="task progress",
            limit=10
        )
        
        return {
            "progress": progress,
            "summary": self._summarize_progress(progress)
        }
    
    def _extract_tasks(self, analysis: str) -> List[str]:
        """从分析中提取任务"""
        # 简化实现
        return []
    
    def _summarize_progress(self, progress: List) -> str:
        """汇总进度"""
        # 简化实现
        return ""
```

### 3.3 编排器（Orchestrator）

```python
# src/core/agent_orchestrator.py

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class Task:
    """任务"""
    id: str
    description: str
    assigned_to: Optional[str] = None  # Agent ID
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    dependencies: List[str] = field(default_factory=list)

class AgentOrchestrator:
    """智能体编排器"""
    
    def __init__(self, acb: 'AgentCommunicationBus'):
        self.acb = acb
        self.tasks: Dict[str, Task] = {}
        self.agents: Dict[str, 'AgentAdapter'] = {}
    
    def register_agent(self, agent_id: str, adapter: 'AgentAdapter') -> None:
        """注册智能体"""
        self.agents[agent_id] = adapter
        self.acb.register_agent(agent_id, adapter)
    
    async def execute_complex_task(
        self,
        description: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """执行复杂任务（自动分解和协调）"""
        
        # Step 1: 让 DFEcrab 分析需求
        analysis = await self.acb.delegate_task(
            agent_id="dfecrab",
            task="analyze_requirement",
            context={"requirement": description}
        )
        
        # Step 2: 分解任务
        tasks = self._decompose_tasks(analysis)
        
        # Step 3: 分配任务
        for task in tasks:
            if "code" in task.description.lower() or "implement" in task.description.lower():
                task.assigned_to = "qwencode"
            elif "review" in task.description.lower() or "check" in task.description.lower():
                task.assigned_to = "codebuddy"
            else:
                task.assigned_to = "dfecrab"
        
        # Step 4: 执行任务（考虑依赖关系）
        results = {}
        for task in self._topological_sort(tasks):
            task.status = TaskStatus.RUNNING
            
            try:
                result = await self.acb.delegate_task(
                    agent_id=task.assigned_to,
                    task=task.description,
                    context=context
                )
                
                task.result = result
                task.status = TaskStatus.COMPLETED
                results[task.id] = result
                
            except Exception as e:
                task.status = TaskStatus.FAILED
                results[task.id] = {"error": str(e)}
        
        # Step 5: 汇总结果
        summary = await self.acb.delegate_task(
            agent_id="dfecrab",
            task="summarize_results",
            context={"results": results}
        )
        
        return {
            "tasks": tasks,
            "results": results,
            "summary": summary
        }
    
    def _decompose_tasks(self, analysis: Dict) -> List[Task]:
        """分解任务"""
        # 简化实现
        return []
    
    def _topological_sort(self, tasks: List[Task]) -> List[Task]:
        """拓扑排序（考虑依赖）"""
        # 简化实现
        return tasks
```

---

## 4. 实施计划

### 4.1 阶段划分

| 阶段 | 任务 | 版本 | 工作量 |
|------|------|------|--------|
| 阶段 1 | 通信总线（ACB） | v4.4.0 | 3 天 |
| 阶段 2 | 智能体适配器 | v4.4.0 | 4 天 |
| 阶段 3 | 编排器 | v4.4.0 | 3 天 |
| 阶段 4 | TUI/Web 集成 | v4.4.0 | 3 天 |
| 阶段 5 | 测试和文档 | v4.4.0 | 2 天 |

### 4.2 每日任务清单

#### Day 1-3: 通信总线

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 消息格式设计 | `agent_message.py` |
| 10:00-12:00 | 消息队列实现 | `message_queue.py` |
| 13:00-15:00 | 主题订阅机制 | `pubsub.py` |
| 15:00-17:00 | 点对点通信 | `direct_message.py` |
| 17:00-18:00 | 单元测试 | `tests/test_acb.py` |

#### Day 4-7: 智能体适配器

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 适配器基类 | `agent_adapter.py` |
| 10:00-12:00 | QwenCode 适配器 | `qwencode_adapter.py` |
| 13:00-15:00 | CodeBuddy 适配器 | `codebuddy_adapter.py` |
| 15:00-17:00 | DFEcrab 适配器 | `dfecrab_adapter.py` |
| 17:00-18:00 | 集成测试 | 三个适配器连通 |

#### Day 8-10: 编排器

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 任务分解逻辑 | `task_decomposer.py` |
| 10:00-12:00 | 任务分配策略 | `task_allocator.py` |
| 13:00-15:00 | 依赖管理 | `dependency_resolver.py` |
| 15:00-17:00 | 结果汇总 | `result_aggregator.py` |
| 17:00-18:00 | 集成测试 | 端到端测试 |

#### Day 11-13: TUI/Web 集成

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | TUI 多智能体视图 | `tui/multi_agent_view.py` |
| 10:00-12:00 | 智能体状态显示 | `agent_status.py` |
| 13:00-15:00 | 任务进度可视化 | `task_progress.py` |
| 15:00-17:00 | Web 界面 | `web/multi_agent.html` |
| 17:00-18:00 | 集成测试 | UI 测试 |

#### Day 14-15: 测试和文档

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 单元测试 | 覆盖率>80% |
| 10:00-12:00 | 集成测试 | 端到端测试 |
| 13:00-15:00 | 用户文档 | `docs/multi_agent/user_guide.md` |
| 15:00-17:00 | 开发文档 | `docs/multi_agent/dev_guide.md` |
| 17:00-18:00 | 发布准备 | v4.4.0 发布 |

### 4.3 成功指标

- [ ] ✅ 三个智能体可以互相通信
- [ ] ✅ 支持任务委托
- [ ] ✅ 支持协同工作
- [ ] ✅ TUI 显示多智能体状态
- [ ] ✅ 端到端延迟<5 秒
- [ ] ✅ 测试覆盖率>80%

---

## 5. 附录

### 5.1 配置文件示例

```yaml
# config/multi_agent.yaml

agents:
  dfecrab:
    enabled: true
    type: "local"
    agent_id: "default"
  
  qwencode:
    enabled: true
    type: "remote"
    api_url: "http://localhost:8080"
    api_key: "your-api-key"
  
  codebuddy:
    enabled: true
    type: "remote"
    api_url: "http://localhost:8081"
    api_key: "your-api-key"

orchestrator:
  default_mode: "chain"  # chain/parallel/expert/negotiation
  timeout_seconds: 300
  max_retries: 3

communication:
  message_queue_size: 1000
  broadcast_enabled: true
  logging_enabled: true
```

### 5.2 文件变更清单

**新增文件**：
```
src/core/
├── agent_communication_bus.py   # 通信总线
├── agent_adapter.py             # 适配器基类
├── agent_orchestrator.py        # 编排器
└── adapters/
    ├── qwencode_adapter.py
    ├── codebuddy_adapter.py
    └── dfecrab_adapter.py

src/tui/
└── screens/
    └── multi_agent.py           # 多智能体视图

config/
└── multi_agent.yaml             # 多智能体配置

docs/multi_agent/
├── user_guide.md
└── dev_guide.md
```

---

**文档版本**：1.0  
**创建时间**：2026-03-30  
**审阅状态**：待审阅
