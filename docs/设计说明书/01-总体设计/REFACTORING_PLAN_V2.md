# DFEcrab 架构重构完整方案

**版本**：v3.6.0  
**创建日期**：2026-03-30  
**参考架构**：OpenClaw 微内核 + 插件化架构  
**目标**：将 DFEcrab 重构为插件化、可扩展的智能体平台

---

## 📋 目录

1. [执行摘要](#1-执行摘要)
2. [现状分析](#2-现状分析)
3. [目标架构](#3-目标架构)
4. [重构方案](#4-重构方案)
5. [实施路线图](#5-实施路线图)
6. [风险评估](#6-风险评估)
7. [附录](#7-附录)

---

## 1. 执行摘要

### 1.1 重构目标

将 DFEcrab 从当前的**单体分层架构**重构为**微内核 + 插件化架构**，实现：
- ✅ 核心代码减少 60%
- ✅ 新功能可通过插件扩展（无需修改核心代码）
- ✅ 支持多客户端（TUI、Web、API）
- ✅ 与 OpenClaw 理念对齐但保持扩展性

### 1.2 关键差距

| 维度 | OpenClaw | DFEcrab 当前 | 差距等级 |
|------|----------|-------------|----------|
| 插件系统 | 一等公民，完整生命周期 | 接口不完整，未使用 | 🔴 重大 |
| 会话管理 | 独立对象，多路复用 | 简单会话，单路 | 🟠 严重 |
| 技能系统 | MCP 优先，标准化 | 混合系统，不统一 | 🟡 中等 |
| 记忆系统 | Markdown + 向量 | 4 个不兼容系统 | 🟡 中等 |
| 配置系统 | 分层配置，可验证 | 单层配置，无验证 | 🟢 轻微 |

### 1.3 预期收益

**短期（1-2 个月）：**
- 代码量减少 40-60%
- 新功能开发速度提升 2 倍
- 插件可以热插拔

**长期（6 个月+）：**
- 完整的插件生态
- 支持 Web UI 和多客户端
- 分布式部署能力

---

## 2. 现状分析

### 2.1 当前文件结构

```
DFEcrab/
├── src/
│   ├── core/               # 核心层（偏重，约 20+ 文件）⚠️
│   │   ├── gateway/            # 网关（复杂，含多个 handler）
│   │   ├── tui/                # TUI 界面
│   │   ├── memory/             # 新记忆系统（开发中）
│   │   ├── memory_manager.py   # 传统记忆管理器
│   │   ├── markdown_memory_manager.py
│   │   ├── hierarchical_memory_manager.py
│   │   ├── agent_manager.py
│   │   ├── session_manager.py
│   │   └── ... (各种管理器)
│   │
│   ├── services/           # 服务层（冗余，约 10+ 文件）⚠️
│   │   ├── memory_service.py
│   │   ├── skill_service.py
│   │   ├── agent_service.py
│   │   ├── gateway_service.py
│   │   └── service_registry.py
│   │
│   ├── plugins/            # 插件（不完整，未被核心使用）❌
│   │   └── builtin/
│   │       └── memory_plugin/
│   │
│   ├── skills/             # 技能（混合系统）⚠️
│   │   ├── skill_wrapper.py
│   │   └── ...
│   │
│   ├── config/
│   │   └── config.py       # 单层配置
│   │
│   └── utils/
│
├── tests/
├── docs/
└── data/
```

### 2.2 核心问题分析

#### 问题 1：层次过多，职责不清

```
当前调用链：
TUI -> Gateway -> Service -> Core Manager -> Memory System
       (4-5 层，冗余严重)

理想调用链：
TUI -> Kernel -> Plugin (Memory)
       (2-3 层，简洁高效)
```

#### 问题 2：记忆系统不统一

| 系统 | 文件 | 用途 | 问题 |
|------|------|------|------|
| `MemoryManager` | src/core/memory_manager.py | 传统三层记忆 | 功能重复 |
| `MarkdownMemoryManager` | src/core/markdown_memory_manager.py | Agent 私有记忆 | 格式不统一 |
| `HierarchicalMemoryManager` | src/core/hierarchical_memory_manager.py | 每日/周/月汇总 | 与其他系统不兼容 |
| `UnifiedMemoryManager` | src/core/memory/unified_memory_manager.py | 统一接口（开发中） | 尚未迁移 |

#### 问题 3：插件系统缺失

```python
# 当前 plugins/ 目录存在但未被使用
src/plugins/builtin/memory_plugin/__init__.py  # 定义但未加载

# 核心代码直接调用 Service，而非通过插件系统
from src.services.memory_service import MemoryService  # ❌ 硬编码依赖
```

#### 问题 4：会话系统不完善

```python
# src/core/session.py 已存在但功能简单
class Session:
    # 缺少：
    # - 多客户端支持
    # - 会话状态管理
    # - 会话持久化
    # - 多路复用
```

---

## 3. 目标架构

### 3.1 理想文件结构（DFEcrab V3）

```
DFEcrab/
├── src/
│   ├── core/                   # 微内核（极简，<1000 行）
│   │   ├── kernel.py           # 内核核心（事件循环、插件加载）
│   │   ├── plugin.py           # 插件基类和接口
│   │   ├── event.py            # 事件系统
│   │   ├── session.py          # 会话对象
│   │   ├── session_manager.py  # 会话管理器
│   │   └── exceptions.py       # 核心异常
│   │
│   ├── plugins/                # 插件（一等公民）
│   │   ├── base.py             # 插件基类（导出自 core.plugin）
│   │   ├── loader.py           # 插件加载器
│   │   ├── registry.py         # 插件注册表
│   │   │
│   │   └── builtin/            # 内置插件
│   │       ├── agent_plugin.py     # Agent 服务插件
│   │       ├── memory_plugin.py    # 记忆管理插件
│   │       ├── skill_plugin.py     # 技能管理插件
│   │       ├── mcp_plugin.py       # MCP 工具插件
│   │       └── builtin_tools.py    # 内置工具插件
│   │
│   ├── apps/                   # 应用层
│   │   ├── tui_app.py          # TUI 应用
│   │   ├── web_app.py          # Web 应用（待开发）
│   │   └── gateway_app.py      # Gateway 应用
│   │
│   ├── config/
│   │   ├── config.py           # 配置管理
│   │   └── config_schema.py    # 配置验证（Pydantic）
│   │
│   └── utils/                  # 工具类
│
├── tests/
│   ├── core/
│   ├── plugins/
│   └── apps/
│
├── docs/
└── examples/                   # 示例插件和配置
```

### 3.2 架构分层

```
┌─────────────────────────────────────────────────────────┐
│                    应用层 (Apps)                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │   TUI App   │  │   Web App   │  │  Gateway    │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
├─────────────────────────────────────────────────────────┤
│                    插件层 (Plugins)                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐       │
│  │ Agent   │ │ Memory  │ │ Skill   │ │  MCP    │       │
│  │ Plugin  │ │ Plugin  │ │ Plugin  │ │ Plugin  │       │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘       │
├─────────────────────────────────────────────────────────┤
│                    内核层 (Kernel)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │   Event     │  │   Plugin    │  │   Session   │      │
│  │   System    │  │   Loader    │  │   Manager   │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
└─────────────────────────────────────────────────────────┘
```

### 3.3 核心组件设计

#### 3.3.1 插件接口

```python
# src/core/plugin.py
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

class PluginStatus(Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    ACTIVE = "active"
    STOPPED = "stopped"
    ERROR = "error"

@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    author: str
    dependencies: List[str]
    status: PluginStatus

class PluginContext:
    """插件上下文，提供插件访问核心功能的接口"""
    def __init__(self, kernel: 'Kernel'):
        self.kernel = kernel
        self.config: Dict[str, Any] = {}
        self.data_dir: Path = Path("data/plugins")
    
    def register_command(self, name: str, handler: Callable) -> None:
        pass
    
    def register_tool(self, name: str, handler: Callable) -> None:
        pass
    
    def emit_event(self, event_type: str, data: Any) -> None:
        pass

class BasePlugin(ABC):
    """所有插件的基类"""
    
    name: str = "unnamed"
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    dependencies: List[str] = []
    
    def __init__(self):
        self.context: Optional[PluginContext] = None
        self.status: PluginStatus = PluginStatus.UNLOADED
    
    async def on_load(self, context: PluginContext) -> None:
        """插件加载时调用（最早，用于初始化）"""
        self.context = context
        self.status = PluginStatus.LOADING
    
    async def on_init(self) -> None:
        """插件初始化时调用（加载配置、资源）"""
        pass
    
    async def on_start(self) -> None:
        """系统启动时调用（开始服务）"""
        self.status = PluginStatus.ACTIVE
    
    async def on_stop(self) -> None:
        """系统停止时调用（清理资源）"""
        self.status = PluginStatus.STOPPED
    
    async def on_unload(self) -> None:
        """插件卸载时调用"""
        self.status = PluginStatus.UNLOADED
```

#### 3.3.2 插件加载器

```python
# src/plugins/loader.py
import importlib
from pathlib import Path
from typing import Dict, List, Optional

class PluginLoader:
    """插件加载器，负责发现、加载和卸载插件"""
    
    def __init__(self, plugin_dirs: List[Path]):
        self.plugin_dirs = plugin_dirs
        self.loaded_plugins: Dict[str, BasePlugin] = {}
    
    def discover_plugins(self) -> List[PluginInfo]:
        """扫描插件目录，发现所有可用插件"""
        plugins = []
        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.exists():
                continue
            
            # 扫描目录中的插件
            for item in plugin_dir.iterdir():
                if self._is_plugin(item):
                    info = self._load_plugin_info(item)
                    plugins.append(info)
        
        return plugins
    
    async def load_plugin(self, plugin_name: str) -> BasePlugin:
        """加载单个插件"""
        # 1. 查找插件文件
        plugin_path = self._find_plugin(plugin_name)
        
        # 2. 导入插件模块
        spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # 3. 实例化插件
        plugin_class = getattr(module, 'Plugin')
        plugin = plugin_class()
        
        # 4. 调用生命周期钩子
        context = PluginContext(self.kernel)
        await plugin.on_load(context)
        await plugin.on_init()
        
        self.loaded_plugins[plugin_name] = plugin
        return plugin
    
    async def unload_plugin(self, plugin_name: str) -> bool:
        """卸载插件"""
        if plugin_name not in self.loaded_plugins:
            return False
        
        plugin = self.loaded_plugins[plugin_name]
        await plugin.on_stop()
        await plugin.on_unload()
        
        del self.loaded_plugins[plugin_name]
        return True
```

#### 3.3.3 内核核心

```python
# src/core/kernel.py
class Kernel:
    """微内核核心，负责事件循环和插件管理"""
    
    def __init__(self, config: Config):
        self.config = config
        self.plugin_loader: Optional[PluginLoader] = None
        self.plugin_registry: PluginRegistry = PluginRegistry()
        self.session_manager: SessionManager = SessionManager()
        self.event_bus: EventBus = EventBus()
    
    async def start(self) -> None:
        """启动内核"""
        # 1. 加载插件
        await self._load_plugins()
        
        # 2. 启动所有插件
        await self._start_plugins()
        
        # 3. 启动事件循环
        await self._run_event_loop()
    
    async def stop(self) -> None:
        """停止内核"""
        # 1. 停止所有插件
        await self._stop_plugins()
        
        # 2. 卸载所有插件
        await self._unload_plugins()
    
    async def _load_plugins(self) -> None:
        """加载所有插件"""
        plugin_infos = self.plugin_loader.discover_plugins()
        
        # 按依赖关系排序
        sorted_plugins = self._resolve_dependencies(plugin_infos)
        
        for info in sorted_plugins:
            try:
                plugin = await self.plugin_loader.load_plugin(info.name)
                self.plugin_registry.register(plugin)
            except Exception as e:
                logger.error(f"加载插件 {info.name} 失败：{e}")
    
    async def _start_plugins(self) -> None:
        """启动所有插件"""
        for plugin in self.plugin_registry.list_plugins():
            try:
                await plugin.on_start()
            except Exception as e:
                logger.error(f"启动插件 {plugin.name} 失败：{e}")
```

#### 3.3.4 会话对象

```python
# src/core/session.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
import uuid

class ClientType(Enum):
    TUI = "tui"
    WEB = "web"
    API = "api"

@dataclass
class ClientInfo:
    id: str
    type: ClientType
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Message:
    id: str
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

class Session:
    """独立的会话对象，支持多路复用"""
    
    def __init__(self, agent_id: str, client: ClientInfo):
        self.id = str(uuid.uuid4())
        self.agent_id = agent_id
        self.client = client
        self.messages: List[Message] = []
        self.state: Dict[str, Any] = {}
        self.created_at = datetime.now()
        self.last_active = datetime.now()
    
    async def send(self, message: Message) -> None:
        """发送消息到客户端"""
        # 通过 Gateway 发送到对应客户端
        await self.client.send(message)
    
    async def receive(self) -> Message:
        """从客户端接收消息"""
        # 从客户端接收队列获取
        return await self.client.receive()
    
    def add_message(self, message: Message) -> None:
        """添加消息到会话历史"""
        self.messages.append(message)
        self.last_active = datetime.now()
    
    def get_context(self, limit: int = 20) -> List[Message]:
        """获取最近的消息上下文"""
        return self.messages[-limit:]
```

#### 3.3.5 会话管理器

```python
# src/core/session_manager.py
class SessionManager:
    """会话管理器，负责创建、管理和销毁会话"""
    
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
        self.agent_sessions: Dict[str, Set[str]] = {}  # agent_id -> session_ids
    
    def create_session(self, agent_id: str, client: ClientInfo) -> Session:
        """创建新会话"""
        session = Session(agent_id, client)
        self.sessions[session.id] = session
        
        if agent_id not in self.agent_sessions:
            self.agent_sessions[agent_id] = set()
        self.agent_sessions[agent_id].add(session.id)
        
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self.sessions.get(session_id)
    
    def list_sessions(self, agent_id: Optional[str] = None) -> List[Session]:
        """列出会话"""
        if agent_id:
            session_ids = self.agent_sessions.get(agent_id, set())
            return [self.sessions[sid] for sid in session_ids if sid in self.sessions]
        return list(self.sessions.values())
    
    async def close_session(self, session_id: str) -> None:
        """关闭会话"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            
            # 从 agent 会话列表中移除
            if session.agent_id in self.agent_sessions:
                self.agent_sessions[session.agent_id].discard(session_id)
            
            # 保存会话状态（持久化）
            await self._persist_session(session)
            
            # 删除会话
            del self.sessions[session_id]
```

---

## 4. 重构方案

### 4.1 阶段一：统一记忆管理器迁移（3 天）

#### 任务 1.1：数据迁移工具

**目标**：将现有记忆数据迁移到统一记忆管理器

**工作内容**：
1. 创建迁移脚本
2. 备份现有数据
3. 执行迁移
4. 验证完整性

**文件清单**：
```
scripts/
└── migrate_memory.py          # 新增：迁移脚本
backup/
└── memory_backup_*.tar.gz     # 新增：备份文件
```

**迁移脚本伪代码**：
```python
#!/usr/bin/env python3
"""
记忆数据迁移脚本

将旧记忆系统的数据迁移到 UnifiedMemoryManager
"""

import asyncio
import tarfile
from datetime import datetime
from pathlib import Path

from src.core.memory import UnifiedMemoryManager, MemoryType
from src.core.memory_manager import MemoryManager as LegacyMemoryManager
from src.core.markdown_memory_manager import MarkdownMemoryManager
from src.core.hierarchical_memory_manager import HierarchicalMemoryManager

async def main():
    # 1. 备份现有数据
    backup_path = backup_memory_files()
    print(f"备份完成：{backup_path}")
    
    # 2. 初始化新旧管理器
    legacy_manager = LegacyMemoryManager()
    markdown_manager = MarkdownMemoryManager()
    hierarchical_manager = HierarchicalMemoryManager()
    unified_manager = UnifiedMemoryManager()
    
    # 3. 迁移各类记忆
    report = {
        "daily": await migrate_daily(hierarchical_manager, unified_manager),
        "agent": await migrate_agent(markdown_manager, unified_manager),
        "legacy": await migrate_legacy(legacy_manager, unified_manager),
    }
    
    # 4. 生成报告
    print_migration_report(report)

def backup_memory_files():
    """备份记忆文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(f"backup/memory_backup_{timestamp}.tar.gz")
    backup_path.parent.mkdir(exist_ok=True)
    
    with tarfile.open(backup_path, "w:gz") as tar:
        for memory_dir in [
            Path("data/memory"),
            Path("data/shared_memory"),
        ]:
            if memory_dir.exists():
                tar.add(memory_dir, arcname=memory_dir.name)
    
    return backup_path

if __name__ == "__main__":
    asyncio.run(main())
```

#### 任务 1.2：更新调用点

**目标**：将所有旧记忆管理器的调用点更新为 UnifiedMemoryManager

**需修改的文件**：
```
src/core/gateway/handlers/memory_handler.py    # 更新
src/plugins/builtin/memory_plugin/__init__.py  # 更新
src/services/memory_service.py                 # 更新
src/core/memory_compactor.py                   # 更新
```

**修改示例**：
```python
# 修改前
from src.core.memory_manager import MemoryManager

class MemoryHandler:
    def __init__(self):
        self.memory_manager = MemoryManager()
    
    async def add_memory(self, content: str):
        return await self.memory_manager.add(content)

# 修改后
from src.core.memory import UnifiedMemoryManager, MemoryType

class MemoryHandler:
    def __init__(self):
        self.memory_manager = UnifiedMemoryManager()
    
    async def add_memory(self, content: str, agent_id: str = None):
        return await self.memory_manager.add_memory(
            content=content,
            memory_type=MemoryType.DAILY,
            agent_id=agent_id
        )
```

#### 任务 1.3：性能测试

**目标**：确保新系统性能达标

**测试指标**：
| 指标 | 目标值 | 测量方法 |
|------|--------|----------|
| API 响应时间 | <100ms | 单次 add_memory/get_memory |
| 搜索响应时间 | <200ms | search_memory |
| 缓存命中率 | >80% | cache_hits / (cache_hits + cache_misses) |
| 并发支持 | 100+ | 并发请求测试 |

---

### 4.2 阶段二：插件系统重构（5 天）

#### 任务 2.1：创建核心插件接口

**新增文件**：
```
src/core/plugin.py               # 新增：插件基类
src/core/event.py                # 新增：事件系统
src/plugins/loader.py            # 新增：插件加载器
src/plugins/registry.py          # 新增：插件注册表
src/plugins/context.py           # 新增：插件上下文
```

**src/core/plugin.py**：
```python
"""
插件系统核心接口

定义插件的生命周期、状态和基础接口。
"""

from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path

class PluginStatus(Enum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    ACTIVE = "active"
    STOPPED = "stopped"
    ERROR = "error"

@dataclass
class PluginInfo:
    """插件元信息"""
    name: str
    version: str
    description: str
    author: str
    dependencies: List[str] = field(default_factory=list)
    status: PluginStatus = PluginStatus.UNLOADED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "dependencies": self.dependencies,
            "status": self.status.value
        }

class PluginContext:
    """
    插件上下文
    
    提供插件访问核心功能的接口，是插件与内核之间的桥梁。
    """
    
    def __init__(self, kernel: 'Kernel'):
        self.kernel = kernel
        self.config: Dict[str, Any] = {}
        self.data_dir: Path = Path("data/plugins")
        self._commands: Dict[str, Callable] = {}
        self._tools: Dict[str, Callable] = {}
    
    def register_command(self, name: str, handler: Callable) -> None:
        """注册命令（Slash 命令）"""
        self._commands[name] = handler
    
    def register_tool(self, name: str, handler: Callable) -> None:
        """注册工具"""
        self._tools[name] = handler
    
    def emit_event(self, event_type: str, data: Any) -> None:
        """触发事件"""
        self.kernel.event_bus.emit(event_type, data)
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """获取插件配置"""
        return self.config.get(key, default)
    
    async def get_memory_context(self, agent_id: str) -> 'ContextBundle':
        """获取记忆上下文（代理到记忆插件）"""
        return await self.kernel.plugin_registry.get_plugin("memory").get_context(agent_id)

class BasePlugin(ABC):
    """
    所有插件的基类
    
    插件开发者应继承此类并实现相应的生命周期方法。
    """
    
    name: str = "unnamed"
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    dependencies: List[str] = field(default_factory=list)
    
    def __init__(self):
        self.context: Optional[PluginContext] = None
        self.status: PluginStatus = PluginStatus.UNLOADED
        self.info = PluginInfo(
            name=self.name,
            version=self.version,
            description=self.description,
            author=self.author,
            dependencies=self.dependencies
        )
    
    async def on_load(self, context: PluginContext) -> None:
        """
        插件加载时调用（最早）
        
        在此方法中：
        - 保存上下文引用
        - 加载配置文件
        - 初始化必要资源
        """
        self.context = context
        self.status = PluginStatus.LOADING
        self.info.status = PluginStatus.LOADING
    
    async def on_init(self) -> None:
        """
        插件初始化时调用
        
        在此方法中：
        - 注册命令和工具
        - 订阅事件
        - 初始化服务
        """
        pass
    
    async def on_start(self) -> None:
        """
        系统启动时调用
        
        在此方法中：
        - 启动后台任务
        - 连接外部服务
        """
        self.status = PluginStatus.ACTIVE
        self.info.status = PluginStatus.ACTIVE
    
    async def on_stop(self) -> None:
        """
        系统停止时调用
        
        在此方法中：
        - 停止后台任务
        - 断开连接
        - 保存状态
        """
        self.status = PluginStatus.STOPPED
        self.info.status = PluginStatus.STOPPED
    
    async def on_unload(self) -> None:
        """
        插件卸载时调用
        
        在此方法中：
        - 清理资源
        - 注销命令和工具
        """
        self.status = PluginStatus.UNLOADED
        self.info.status = PluginStatus.UNLOADED
```

#### 任务 2.2：实现插件加载器

**src/plugins/loader.py**：
```python
"""
插件加载器

负责发现、加载和卸载插件。
"""

import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Type
import logging

from src.core.plugin import BasePlugin, PluginInfo, PluginStatus, PluginContext
from src.core.kernel import Kernel

logger = logging.getLogger(__name__)

class PluginLoader:
    """插件加载器"""
    
    def __init__(self, plugin_dirs: List[Path], kernel: Kernel):
        self.plugin_dirs = plugin_dirs
        self.kernel = kernel
        self.loaded_plugins: Dict[str, BasePlugin] = {}
        self._plugin_paths: Dict[str, Path] = {}
    
    def discover_plugins(self) -> List[PluginInfo]:
        """
        扫描插件目录，发现所有可用插件
        
        支持的插件格式：
        1. 单文件插件：plugins/foo_plugin.py
        2. 目录插件：plugins/foo_plugin/__init__.py
        """
        plugins = []
        
        for plugin_dir in self.plugin_dirs:
            if not plugin_dir.exists():
                continue
            
            # 扫描单文件插件
            for file_path in plugin_dir.glob("*_plugin.py"):
                info = self._load_plugin_info(file_path)
                if info:
                    plugins.append(info)
                    self._plugin_paths[info.name] = file_path
            
            # 扫描目录插件
            for dir_path in plugin_dir.iterdir():
                if dir_path.is_dir() and (dir_path / "__init__.py").exists():
                    info = self._load_plugin_info(dir_path / "__init__.py")
                    if info:
                        plugins.append(info)
                        self._plugin_paths[info.name] = dir_path
        
        logger.info(f"发现 {len(plugins)} 个插件")
        return plugins
    
    def _load_plugin_info(self, file_path: Path) -> Optional[PluginInfo]:
        """从文件加载插件信息"""
        try:
            spec = importlib.util.spec_from_file_location("plugin_module", file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # 提取插件元信息
            name = getattr(module, "PLUGIN_NAME", None)
            version = getattr(module, "PLUGIN_VERSION", "1.0.0")
            description = getattr(module, "PLUGIN_DESCRIPTION", "")
            author = getattr(module, "PLUGIN_AUTHOR", "")
            dependencies = getattr(module, "PLUGIN_DEPENDENCIES", [])
            
            if not name:
                logger.warning(f"插件文件 {file_path} 缺少 PLUGIN_NAME")
                return None
            
            return PluginInfo(
                name=name,
                version=version,
                description=description,
                author=author,
                dependencies=dependencies
            )
        
        except Exception as e:
            logger.error(f"加载插件信息失败 {file_path}: {e}")
            return None
    
    async def load_plugin(self, plugin_name: str) -> BasePlugin:
        """加载单个插件"""
        if plugin_name in self.loaded_plugins:
            logger.warning(f"插件 {plugin_name} 已加载")
            return self.loaded_plugins[plugin_name]
        
        if plugin_name not in self._plugin_paths:
            raise ValueError(f"未找到插件：{plugin_name}")
        
        plugin_path = self._plugin_paths[plugin_name]
        
        try:
            # 导入插件模块
            if plugin_path.is_dir():
                # 目录插件
                module_name = f"plugins.{plugin_name}"
                spec = importlib.util.spec_from_file_location(
                    module_name, 
                    plugin_path / "__init__.py"
                )
            else:
                # 单文件插件
                module_name = f"plugins.{plugin_name}"
                spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # 获取插件类
            plugin_class = getattr(module, "Plugin", None)
            if not plugin_class:
                raise ValueError(f"插件 {plugin_name} 缺少 Plugin 类")
            
            # 实例化插件
            plugin: BasePlugin = plugin_class()
            
            # 检查依赖
            await self._check_dependencies(plugin)
            
            # 调用生命周期钩子
            context = PluginContext(self.kernel)
            await plugin.on_load(context)
            await plugin.on_init()
            
            self.loaded_plugins[plugin_name] = plugin
            logger.info(f"插件 {plugin_name} 加载成功")
            
            return plugin
        
        except Exception as e:
            logger.error(f"加载插件 {plugin_name} 失败：{e}")
            raise
    
    async def unload_plugin(self, plugin_name: str) -> bool:
        """卸载插件"""
        if plugin_name not in self.loaded_plugins:
            return False
        
        plugin = self.loaded_plugins[plugin_name]
        
        try:
            await plugin.on_stop()
            await plugin.on_unload()
            
            del self.loaded_plugins[plugin_name]
            logger.info(f"插件 {plugin_name} 卸载成功")
            
            return True
        
        except Exception as e:
            logger.error(f"卸载插件 {plugin_name} 失败：{e}")
            return False
    
    async def _check_dependencies(self, plugin: BasePlugin) -> None:
        """检查插件依赖"""
        for dep in plugin.dependencies:
            if dep not in self.loaded_plugins:
                # 尝试加载依赖
                try:
                    await self.load_plugin(dep)
                except Exception:
                    raise ValueError(
                        f"插件 {plugin.name} 依赖缺失：{dep}"
                    )
```

#### 任务 2.3：重构核心功能为插件

**需创建的插件**：
```
src/plugins/builtin/
├── agent_plugin.py      # 新增：Agent 服务
├── memory_plugin.py     # 新增：记忆管理
├── skill_plugin.py      # 新增：技能管理
├── mcp_plugin.py        # 新增：MCP 工具
└── builtin_tools.py     # 新增：内置工具
```

**示例：memory_plugin.py**：
```python
"""
记忆管理插件

将原有的 MemoryService 重构为插件。
"""

from src.core.plugin import BasePlugin, PluginContext
from src.core.memory import UnifiedMemoryManager, MemoryType, MemoryCategory

PLUGIN_NAME = "memory"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "记忆管理插件"
PLUGIN_AUTHOR = "DFEcrab Team"

class Plugin(BasePlugin):
    """记忆管理插件"""
    
    name = PLUGIN_NAME
    version = PLUGIN_VERSION
    description = PLUGIN_DESCRIPTION
    
    def __init__(self):
        super().__init__()
        self.memory_manager: Optional[UnifiedMemoryManager] = None
    
    async def on_load(self, context: PluginContext) -> None:
        await super().on_load(context)
        
        # 初始化记忆管理器
        self.memory_manager = UnifiedMemoryManager()
    
    async def on_init(self) -> None:
        # 注册命令
        self.context.register_command("memory", self.handle_memory_command)
        self.context.register_command("mem", self.handle_memory_command)
        
        # 注册工具
        self.context.register_tool("add_memory", self.add_memory)
        self.context.register_tool("search_memory", self.search_memory)
        self.context.register_tool("get_context", self.get_context)
    
    async def handle_memory_command(self, args: list) -> str:
        """处理记忆相关命令"""
        if not args:
            return "用法：/memory <add|search|context> [参数]"
        
        cmd = args[0]
        if cmd == "add":
            content = " ".join(args[1:])
            await self.add_memory(content)
            return "记忆已添加"
        elif cmd == "search":
            query = " ".join(args[1:])
            results = await self.search_memory(query)
            return self._format_search_results(results)
        elif cmd == "context":
            context = await self.get_context()
            return self._format_context(context)
        else:
            return f"未知命令：{cmd}"
    
    async def add_memory(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.DAILY,
        category: MemoryCategory = MemoryCategory.GENERAL
    ) -> str:
        """添加记忆"""
        agent_id = self.context.get_config("agent_id")
        memory_id = await self.memory_manager.add_memory(
            content=content,
            memory_type=memory_type,
            agent_id=agent_id,
            category=category
        )
        return memory_id
    
    async def search_memory(self, query: str, limit: int = 10) -> list:
        """搜索记忆"""
        agent_id = self.context.get_config("agent_id")
        return await self.memory_manager.search_memory(
            query=query,
            agent_id=agent_id,
            limit=limit
        )
    
    async def get_context(self, agent_id: str = None) -> 'ContextBundle':
        """获取记忆上下文"""
        if not agent_id:
            agent_id = self.context.get_config("agent_id")
        return await self.memory_manager.get_context(agent_id=agent_id)
    
    def _format_search_results(self, results: list) -> str:
        """格式化搜索结果"""
        if not results:
            return "未找到相关记忆"
        
        lines = [f"找到 {len(results)} 条记忆："]
        for i, result in enumerate(results, 1):
            lines.append(f"{i}. [{result.score:.2f}] {result.memory_entry.content[:100]}...")
        
        return "\n".join(lines)
    
    def _format_context(self, context: 'ContextBundle') -> str:
        """格式化上下文"""
        return context.to_text()
```

#### 任务 2.4：实现内核核心

**src/core/kernel.py**：
```python
"""
微内核核心

负责事件循环、插件管理和系统生命周期。
"""

import asyncio
from pathlib import Path
from typing import List, Optional
import logging

from src.core.plugin import PluginStatus
from src.core.event import EventBus
from src.core.session_manager import SessionManager
from src.config.config import Config
from src.plugins.loader import PluginLoader
from src.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

class Kernel:
    """微内核核心"""
    
    def __init__(self, config: Config):
        self.config = config
        self.event_bus = EventBus()
        self.session_manager = SessionManager()
        self.plugin_registry = PluginRegistry()
        self.plugin_loader: Optional[PluginLoader] = None
        self._running = False
        self._tasks: List[asyncio.Task] = []
    
    async def start(self) -> None:
        """启动内核"""
        logger.info("内核启动中...")
        
        # 1. 初始化插件加载器
        plugin_dirs = [
            Path("src/plugins/builtin"),
            Path("plugins"),  # 用户插件目录
        ]
        self.plugin_loader = PluginLoader(plugin_dirs, self)
        
        # 2. 加载插件
        await self._load_plugins()
        
        # 3. 启动插件
        await self._start_plugins()
        
        # 4. 启动事件循环
        self._running = True
        self._tasks.append(asyncio.create_task(self._run_event_loop()))
        
        logger.info("内核已启动")
    
    async def stop(self) -> None:
        """停止内核"""
        logger.info("内核停止中...")
        
        self._running = False
        
        # 1. 停止所有插件
        await self._stop_plugins()
        
        # 2. 卸载插件
        await self._unload_plugins()
        
        # 3. 等待所有任务完成
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        logger.info("内核已停止")
    
    async def _load_plugins(self) -> None:
        """加载所有插件"""
        plugin_infos = self.plugin_loader.discover_plugins()
        
        # 按依赖关系排序（拓扑排序）
        sorted_plugins = self._resolve_dependencies(plugin_infos)
        
        for info in sorted_plugins:
            try:
                plugin = await self.plugin_loader.load_plugin(info.name)
                self.plugin_registry.register(plugin)
                logger.info(f"插件 {info.name} v{info.version} 加载成功")
            except Exception as e:
                logger.error(f"加载插件 {info.name} 失败：{e}")
    
    async def _start_plugins(self) -> None:
        """启动所有插件"""
        for plugin in self.plugin_registry.list_plugins():
            try:
                await plugin.on_start()
                logger.info(f"插件 {plugin.name} 已启动")
            except Exception as e:
                logger.error(f"启动插件 {plugin.name} 失败：{e}")
    
    async def _stop_plugins(self) -> None:
        """停止所有插件（逆序）"""
        for plugin in reversed(self.plugin_registry.list_plugins()):
            try:
                await plugin.on_stop()
                logger.info(f"插件 {plugin.name} 已停止")
            except Exception as e:
                logger.error(f"停止插件 {plugin.name} 失败：{e}")
    
    async def _unload_plugins(self) -> None:
        """卸载所有插件"""
        for plugin in self.plugin_registry.list_plugins():
            try:
                await self.plugin_loader.unload_plugin(plugin.name)
            except Exception as e:
                logger.error(f"卸载插件 {plugin.name} 失败：{e}")
        
        self.plugin_registry.clear()
    
    def _resolve_dependencies(self, plugins: List['PluginInfo']) -> List['PluginInfo']:
        """
        解析插件依赖，返回正确的加载顺序
        
        使用拓扑排序确保依赖先被加载。
        """
        # 构建依赖图
        graph = {p.name: set(p.dependencies) for p in plugins}
        plugin_map = {p.name: p for p in plugins}
        
        # Kahn 算法
        in_degree = {name: len(deps) for name, deps in graph.items()}
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []
        
        while queue:
            name = queue.pop(0)
            result.append(plugin_map[name])
            
            for other_name, deps in graph.items():
                if name in deps:
                    in_degree[other_name] -= 1
                    if in_degree[other_name] == 0:
                        queue.append(other_name)
        
        if len(result) != len(plugins):
            raise ValueError("存在循环依赖")
        
        return result
    
    async def _run_event_loop(self) -> None:
        """运行事件循环"""
        while self._running:
            try:
                # 处理事件队列
                await self.event_bus.process_pending()
                
                # 短暂休眠，避免 CPU 占用
                await asyncio.sleep(0.01)
            
            except Exception as e:
                logger.error(f"事件循环错误：{e}")
```

---

### 4.3 阶段三：会话系统重构（2 天）

#### 任务 3.1：实现独立 Session 对象

**修改文件**：
```
src/core/session.py          # 重构：增强 Session 类
```

**完整实现**：
```python
"""
会话管理

提供独立的会话对象，支持多路复用和持久化。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional
import uuid
import json
from pathlib import Path
import asyncio

class ClientType(Enum):
    """客户端类型"""
    TUI = "tui"
    WEB = "web"
    API = "api"

@dataclass
class ClientInfo:
    """客户端信息"""
    id: str
    type: ClientType
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 运行时属性（不序列化）
    _send_queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)
    _receive_queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)
    
    async def send(self, message: 'Message') -> None:
        """发送消息到客户端"""
        await self._send_queue.put(message)
    
    async def receive(self) -> 'Message':
        """从客户端接收消息"""
        return await self._receive_queue.get()

@dataclass
class Message:
    """消息对象"""
    id: str
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        return cls(
            id=data["id"],
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {})
        )

class Session:
    """
    独立的会话对象
    
    每个会话代表一个客户端与 Agent 之间的连接。
    支持：
    - 多路复用（一个 Agent 服务多个客户端）
    - 会话状态管理
    - 会话持久化
    """
    
    def __init__(self, agent_id: str, client: ClientInfo):
        self.id = str(uuid.uuid4())
        self.agent_id = agent_id
        self.client = client
        self.messages: List[Message] = []
        self.state: Dict[str, Any] = {}
        self.created_at = datetime.now()
        self.last_active = datetime.now()
        self._lock = asyncio.Lock()
    
    async def send(self, message: Message) -> None:
        """发送消息到客户端"""
        self.add_message(message)
        await self.client.send(message)
    
    async def receive(self) -> Message:
        """从客户端接收消息"""
        message = await self.client.receive()
        self.add_message(message)
        return message
    
    def add_message(self, message: Message) -> None:
        """添加消息到会话历史"""
        self.messages.append(message)
        self.last_active = datetime.now()
    
    def get_context(self, limit: int = 20) -> List[Message]:
        """获取最近的消息上下文"""
        return self.messages[-limit:]
    
    def set_state(self, key: str, value: Any) -> None:
        """设置会话状态"""
        self.state[key] = value
        self.last_active = datetime.now()
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """获取会话状态"""
        return self.state.get(key, default)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "client": {
                "id": self.client.id,
                "type": self.client.type.value,
                "metadata": self.client.metadata
            },
            "messages": [m.to_dict() for m in self.messages],
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        """从字典反序列化"""
        client = ClientInfo(
            id=data["client"]["id"],
            type=ClientType(data["client"]["type"]),
            metadata=data["client"].get("metadata", {})
        )
        
        session = cls(
            agent_id=data["agent_id"],
            client=client
        )
        session.id = data["id"]
        session.messages = [Message.from_dict(m) for m in data["messages"]]
        session.state = data.get("state", {})
        session.created_at = datetime.fromisoformat(data["created_at"])
        session.last_active = datetime.fromisoformat(data["last_active"])
        
        return session
    
    async def save(self, path: Path) -> None:
        """持久化到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    async def load(cls, path: Path) -> 'Session':
        """从文件加载"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return cls.from_dict(data)
```

---

### 4.4 阶段四：技能系统标准化（2 天）

#### 任务 4.1：定义标准化技能接口

**src/skills/base.py**：
```python
"""
技能系统基础接口

定义标准化技能接口，MCP 优先。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime

@dataclass
class SkillParameter:
    """技能参数定义"""
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = False
    default: Any = None
    enum: Optional[List[Any]] = None

@dataclass
class SkillResult:
    """技能执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def ok(cls, data: Any, **metadata) -> 'SkillResult':
        return cls(success=True, data=data, metadata=metadata)
    
    @classmethod
    def fail(cls, error: str) -> 'SkillResult':
        return cls(success=False, error=error)

class BaseSkill(ABC):
    """技能基类"""
    
    name: str = "unnamed"
    version: str = "1.0.0"
    description: str = ""
    
    # 技能参数定义
    parameters: List[SkillParameter] = []
    
    async def validate(self, **kwargs) -> SkillResult:
        """验证参数"""
        for param in self.parameters:
            if param.required and param.name not in kwargs:
                return SkillResult.fail(f"缺少必需参数：{param.name}")
            
            if param.name in kwargs:
                value = kwargs[param.name]
                
                # 类型检查
                if not self._check_type(value, param.type):
                    return SkillResult.fail(f"参数 {param.name} 类型错误，期望 {param.type}")
                
                # 枚举检查
                if param.enum and value not in param.enum:
                    return SkillResult.fail(f"参数 {param.name} 值不在允许范围内")
        
        return SkillResult.ok(None)
    
    def _check_type(self, value: Any, type_name: str) -> bool:
        """检查类型"""
        type_map = {
            "string": str,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict
        }
        expected_type = type_map.get(type_name)
        if expected_type:
            return isinstance(value, expected_type)
        return True
    
    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """执行技能"""
        pass
```

---

### 4.5 阶段五：配置系统重构（1 天）

#### 任务 5.1：分层配置

**src/config/config.py**：
```python
"""
配置管理系统

支持分层配置：全局、项目、用户。
"""

from pathlib import Path
from typing import Dict, Any, Optional
import yaml
import logging

logger = logging.getLogger(__name__)

class Config:
    """配置管理类"""
    
    def __init__(self):
        # 配置层级（优先级从高到低）
        self.user_config: Dict[str, Any] = {}
        self.project_config: Dict[str, Any] = {}
        self.global_config: Dict[str, Any] = {}
        
        # 配置路径
        self.global_config_path = Path("/etc/dfecrab/config.yaml")
        self.project_config_path = Path("./.dfecrab.yaml")
        self.user_config_path = Path.home() / ".dfecrab" / "config.yaml"
        
        # 加载配置
        self._load_configs()
    
    def _load_configs(self) -> None:
        """加载所有层级的配置"""
        # 加载全局配置
        if self.global_config_path.exists():
            self.global_config = self._load_yaml(self.global_config_path)
            logger.info(f"已加载全局配置：{self.global_config_path}")
        
        # 加载项目配置
        if self.project_config_path.exists():
            self.project_config = self._load_yaml(self.project_config_path)
            logger.info(f"已加载项目配置：{self.project_config_path}")
        
        # 加载用户配置
        if self.user_config_path.exists():
            self.user_config = self._load_yaml(self.user_config_path)
            logger.info(f"已加载用户配置：{self.user_config_path}")
    
    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """加载 YAML 文件"""
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值（按优先级）"""
        keys = key.split(".")
        
        # 用户配置（最高优先级）
        value = self._get_nested(self.user_config, keys)
        if value is not None:
            return value
        
        # 项目配置
        value = self._get_nested(self.project_config, keys)
        if value is not None:
            return value
        
        # 全局配置
        value = self._get_nested(self.global_config, keys)
        if value is not None:
            return value
        
        return default
    
    def _get_nested(self, data: Dict[str, Any], keys: List[str]) -> Any:
        """获取嵌套字典的值"""
        for key in keys:
            if isinstance(data, dict) and key in data:
                data = data[key]
            else:
                return None
        return data
    
    def set(self, key: str, value: Any, level: str = "user") -> None:
        """设置配置值"""
        keys = key.split(".")
        
        if level == "user":
            config = self.user_config
        elif level == "project":
            config = self.project_config
        elif level == "global":
            config = self.global_config
        else:
            raise ValueError(f"未知配置层级：{level}")
        
        # 设置嵌套值
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def save(self, level: str = "user") -> None:
        """保存配置到文件"""
        if level == "user":
            config = self.user_config
            path = self.user_config_path
        elif level == "project":
            config = self.project_config
            path = self.project_config_path
        elif level == "global":
            config = self.global_config
            path = self.global_config_path
        else:
            raise ValueError(f"未知配置层级：{level}")
        
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
        
        logger.info(f"已保存 {level} 配置：{path}")
```

---

## 5. 实施路线图

### 5.1 总体时间线

```
Week 1-2:  统一记忆管理器迁移（P0）
Week 3-5:  插件系统重构（P1）
Week 6-7:  会话系统重构（P1）
Week 8:    技能系统标准化（P1）
Week 9:    配置系统重构（P2）
Week 10:   集成测试和文档
```

### 5.2 详细任务分解

| 阶段 | 任务 | 工作量 | 优先级 | 状态 |
|------|------|--------|--------|------|
| 阶段一 | 数据迁移工具 | 0.5 天 | P0 | 待开发 |
| 阶段一 | 更新调用点 | 1.5 天 | P0 | 待开发 |
| 阶段一 | 性能测试 | 1 天 | P0 | 待开发 |
| 阶段二 | 插件接口设计 | 1 天 | P1 | 待开发 |
| 阶段二 | 插件加载器 | 1.5 天 | P1 | 待开发 |
| 阶段二 | 核心功能插件化 | 2 天 | P1 | 待开发 |
| 阶段二 | 插件测试文档 | 0.5 天 | P1 | 待开发 |
| 阶段三 | Session 对象 | 1 天 | P1 | 待开发 |
| 阶段三 | SessionManager | 1 天 | P1 | 待开发 |
| 阶段四 | 技能接口 | 0.5 天 | P1 | 待开发 |
| 阶段四 | MCP 优先 | 1 天 | P1 | 待开发 |
| 阶段四 | 技能迁移 | 0.5 天 | P1 | 待开发 |
| 阶段五 | 分层配置 | 0.5 天 | P2 | 待开发 |
| 阶段五 | 配置验证 | 0.5 天 | P2 | 待开发 |

---

## 6. 风险评估

### 6.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 插件系统破坏现有功能 | 中 | 高 | 渐进式重构，充分测试 |
| 数据迁移丢失 | 低 | 高 | 迁移前全量备份 |
| 性能下降 | 中 | 中 | 性能基准测试，优化 |
| 兼容性破坏 | 低 | 高 | 保留旧 API 桥接 |

### 6.2 组织风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 重构周期过长 | 中 | 高 | 分阶段，快速迭代 |
| 团队学习成本 | 高 | 中 | 文档、培训 |
| 需求变更 | 中 | 中 | 灵活调整优先级 |

---

## 7. 附录

### 7.1 文件变更清单

**新增文件**：
```
src/core/plugin.py
src/core/event.py
src/core/kernel.py
src/plugins/loader.py
src/plugins/registry.py
src/plugins/context.py
src/plugins/builtin/agent_plugin.py
src/plugins/builtin/memory_plugin.py
src/plugins/builtin/skill_plugin.py
src/plugins/builtin/mcp_plugin.py
src/plugins/builtin/builtin_tools.py
src/skills/base.py
src/config/config_schema.py
scripts/migrate_memory.py
```

**修改文件**：
```
src/core/session.py
src/core/session_manager.py
src/core/gateway/handlers/memory_handler.py
src/services/memory_service.py
src/services/skill_service.py
src/config/config.py
```

**废弃文件**：
```
src/core/memory_manager.py         # 迁移后废弃
src/core/markdown_memory_manager.py # 迁移后废弃
src/core/hierarchical_memory_manager.py # 迁移后废弃
```

### 7.2 测试计划

| 测试类型 | 覆盖范围 | 目标覆盖率 |
|----------|----------|------------|
| 单元测试 | 核心模块 | >80% |
| 集成测试 | 插件系统 | 100% |
| 迁移测试 | 数据迁移 | 100% 完整 |
| 性能测试 | API 响应 | <100ms |
| 回归测试 | 现有功能 | 100% 通过 |

### 7.3 成功指标

1. ✅ 所有现有功能正常工作
2. ✅ 插件可以热插拔
3. ✅ 核心代码减少 60%
4. ✅ API 响应时间<100ms
5. ✅ 100% 数据完整迁移
6. ✅ 测试覆盖率>80%

---

**文档版本**：1.0  
**创建时间**：2026-03-30  
**审阅状态**：待审阅
