# DFEcrab 4.0 改造计划

> 基于 Claude Code 架构分析，对 DFEcrab 进行深度优化

---

## 一、核心改进方向

### 1. 记忆系统升级（高优先级）

**现状**: 3层记忆（永久/长期/短期）
**目标**: 4层优先级记忆体系

```
┌─────────────────────────────────────────┐
│ Level 4: 企业策略 (~/.dfecrab/enterprise.md)  │
│ Level 3: 项目记忆 (./DFECRAB.md)              │
│ Level 2: 自动记忆 (.dfecrab/memory/MEMORY.md) │
│ Level 1: 用户记忆 (~/.dfecrab/user.md)        │
└─────────────────────────────────────────┘
```

**开发任务**:
- [ ] 设计4层记忆的数据结构
- [ ] 实现记忆优先级合并逻辑
- [ ] 添加条件规则支持（glob模式）
- [ ] 实现记忆自动压缩和清理
- [ ] 支持 @引用语法

### 2. 插件系统重构（高优先级）

**现状**: 简单的插件接口
**目标**: Claude Code 风格的插件生态

**插件结构**:
```
plugin-name/
├── .dfecrab-plugin/
│   └── plugin.json       # 元数据
├── commands/             # 斜杠命令
├── agents/               # 专用代理
├── skills/               # 技能定义
├── hooks/                # 事件钩子
│   └── hooks.json
└── README.md
```

**开发任务**:
- [ ] 设计新的插件清单格式
- [ ] 实现命令注册和分发机制
- [ ] 实现钩子系统（session-start, pre-tool, post-tool）
- [ ] 开发插件市场和管理命令
- [ ] 迁移现有技能到新插件格式

### 3. 工具系统增强（中优先级）

**现状**: 基础技能系统
**目标**: 统一的工具调用接口

**新增工具类型**:
| 工具 | 说明 | 状态 |
|------|------|------|
| FileRead | 读取文件 | 需增强 |
| FileEdit | 编辑文件（diff模式） | 新增 |
| FileWrite | 写入文件 | 需增强 |
| Glob | 文件模式匹配 | 新增 |
| Grep | 文本搜索（ripgrep） | 新增 |
| Bash | 执行shell命令 | 需增强 |
| WebFetch | 获取网页 | 新增 |
| WebSearch | 网络搜索 | 新增 |
| Task | 任务管理 | 已有 |

**开发任务**:
- [ ] 统一工具调用接口设计
- [ ] 实现文件操作工具增强
- [ ] 集成 ripgrep 搜索
- [ ] 添加权限控制层
- [ ] 实现工具执行审计日志

### 4. Agent 协作优化（中优先级）

**现状**: 多智能体编排器
**目标**: 灵活的代理协作模式

**协作模式**:
- **chain**: 链式传递
- **parallel**: 并行执行
- **hierarchical**: 层级管理
- **collaborative**: 协作讨论

**开发任务**:
- [ ] 优化 Agent 生命周期管理
- [ ] 实现子代理调用机制
- [ ] 添加代理间通信协议
- [ ] 实现代理池复用
- [ ] 支持异步代理执行

### 5. MCP 协议支持（低优先级）

**现状**: 无
**目标**: 支持 Model Context Protocol

**开发任务**:
- [ ] 研究 MCP 协议规范
- [ ] 实现 MCP 客户端
- [ ] 开发 MCP 服务器适配器
- [ ] 支持常用 MCP 服务器（GitHub、数据库等）

---

## 二、开发阶段规划

### Phase 1: 基础架构（2-3周）

**目标**: 建立核心改进基础

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 设计新的记忆数据结构 | 2天 | - |
| 实现记忆优先级系统 | 3天 | 记忆结构 |
| 设计插件清单格式 | 1天 | - |
| 实现命令注册机制 | 2天 | 插件格式 |
| 统一工具接口设计 | 2天 | - |

### Phase 2: 核心功能（3-4周）

**目标**: 实现主要功能改进

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 实现4层记忆系统 | 5天 | Phase 1 |
| 实现钩子系统 | 3天 | 插件格式 |
| 实现文件操作工具 | 3天 | 工具接口 |
| 集成 ripgrep 搜索 | 2天 | 工具接口 |
| 优化 Agent 协作 | 4天 | - |

### Phase 3: 生态建设（持续）

**目标**: 完善插件和工具生态

| 任务 | 工作量 | 依赖 |
|------|--------|------|
| 迁移现有技能到插件 | 持续 | Phase 2 |
| 开发官方插件库 | 持续 | Phase 2 |
| 实现插件市场 | 3天 | Phase 2 |
| MCP 协议支持 | 5天 | - |
| 文档和示例 | 持续 | - |

---

## 三、详细设计

### 3.1 记忆系统设计

```python
# src/core/memory/v4/hierarchical_memory.py

from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

@dataclass
class MemoryLevel:
    """记忆层级定义"""
    level: int           # 1-4
    name: str            # 层级名称
    path: Path           # 文件路径
    priority: int        # 优先级
    max_lines: int       # 最大行数
    auto_update: bool    # 是否自动更新

class MemoryV4:
    """四层记忆系统"""

    LEVELS = {
        4: MemoryLevel(4, "企业策略", Path("/etc/dfecrab/DFECRAB.md"), 100, False),
        3: MemoryLevel(3, "项目记忆", Path("./DFECRAB.md"), 200, False),
        2: MemoryLevel(2, "自动记忆", Path(".dfecrab/memory/MEMORY.md"), 200, True),
        1: MemoryLevel(1, "用户记忆", Path("~/.dfecrab/user.md"), 150, False),
    }

    def load_all(self) -> str:
        """按优先级合并所有记忆"""
        memories = []
        for level in sorted(self.LEVELS.values(), key=lambda x: -x.priority):
            if content := self._load_level(level):
                memories.append(f"## {level.name}\n{content}")
        return "\n\n".join(memories)

    def update_auto_memory(self, observations: List[str]):
        """更新自动记忆"""
        level = self.LEVELS[2]
        # 实现自动记忆更新逻辑
        pass
```

### 3.2 插件系统设计

```python
# src/core/plugin/v2/plugin_interface.py

from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from enum import Enum

class HookType(Enum):
    SESSION_START = "session_start"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    SESSION_END = "session_end"

class CommandSpec(BaseModel):
    name: str
    description: str
    template: str  # 命令模板文件路径

class AgentSpec(BaseModel):
    name: str
    description: str
    capabilities: List[str]

class HookSpec(BaseModel):
    type: HookType
    handler: str  # 处理函数路径

class PluginManifest(BaseModel):
    """插件清单"""
    name: str
    version: str
    description: str
    author: Optional[str] = None

    commands: List[CommandSpec] = []
    agents: List[AgentSpec] = []
    skills: List[str] = []
    hooks: List[HookSpec] = []

    # 条件规则
    applies_to: Optional[List[str]] = None  # glob 模式

class PluginV2:
    """插件管理器"""

    def __init__(self):
        self.plugins: Dict[str, PluginManifest] = {}
        self.commands: Dict[str, CommandSpec] = {}
        self.hooks: Dict[HookType, List[HookSpec]] = {}

    async def load_plugin(self, path: Path):
        """加载插件"""
        manifest = self._parse_manifest(path)
        self.plugins[manifest.name] = manifest

        # 注册命令
        for cmd in manifest.commands:
            self.commands[f"/{cmd.name}"] = cmd

        # 注册钩子
        for hook in manifest.hooks:
            if hook.type not in self.hooks:
                self.hooks[hook.type] = []
            self.hooks[hook.type].append(hook)

    async def execute_hook(self, hook_type: HookType, context: Dict[str, Any]):
        """执行钩子"""
        for hook in self.hooks.get(hook_type, []):
            await self._run_hook(hook, context)
```

### 3.3 工具系统设计

```python
# src/core/tools/base.py

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel

class ToolResult(BaseModel):
    success: bool
    output: Any
    error: Optional[str] = None

class BaseTool(ABC):
    """工具基类"""

    name: str
    description: str

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        """执行工具"""
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        """验证参数"""
        return True

# src/core/tools/file_tools.py

class FileReadTool(BaseTool):
    name = "FileRead"
    description = "读取文件内容"

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        path = Path(params["file_path"])
        if not path.exists():
            return ToolResult(success=False, output=None, error="文件不存在")

        content = path.read_text()
        return ToolResult(success=True, output=content)

class FileEditTool(BaseTool):
    name = "FileEdit"
    description = "编辑文件（支持 diff 模式）"

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        # 实现 diff 编辑逻辑
        pass

# src/core/tools/search_tools.py

class GlobTool(BaseTool):
    name = "Glob"
    description = "文件模式匹配"

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        import glob
        pattern = params["pattern"]
        matches = glob.glob(pattern, recursive=True)
        return ToolResult(success=True, output=matches)

class GrepTool(BaseTool):
    name = "Grep"
    description = "文本搜索（使用 ripgrep）"

    async def execute(self, params: Dict[str, Any]) -> ToolResult:
        # 调用 ripgrep 进行搜索
        pass
```

---

## 四、迁移策略

### 4.1 兼容性保障

1. **向后兼容**: 新版本支持旧版配置和技能
2. **渐进迁移**: 提供迁移脚本和文档
3. **双轨运行**: 新旧系统可并行

### 4.2 迁移步骤

```bash
# 1. 备份现有数据
dfecrab backup create

# 2. 运行迁移脚本
dfecrab migrate --to v4

# 3. 验证迁移结果
dfecrab migrate --verify

# 4. 启动新版本
dfecrab start --version 4
```

---

## 五、测试计划

### 5.1 单元测试

- [ ] 记忆系统测试
- [ ] 插件系统测试
- [ ] 工具系统测试
- [ ] Agent 协作测试

### 5.2 集成测试

- [ ] 端到端流程测试
- [ ] 多 Agent 协作测试
- [ ] 插件加载测试
- [ ] 记忆持久化测试

### 5.3 性能测试

- [ ] 记忆加载性能
- [ ] 工具执行性能
- [ ] 并发处理能力

---

## 六、文档计划

### 6.1 用户文档

- [ ] 快速开始指南
- [ ] 记忆系统使用手册
- [ ] 插件开发指南
- [ ] 工具参考文档

### 6.2 开发者文档

- [ ] 架构设计文档
- [ ] API 参考文档
- [ ] 贡献指南
- [ ] 发布流程

---

## 七、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 破坏现有功能 | 高 | 完整的测试覆盖 |
| 迁移数据丢失 | 高 | 自动备份机制 |
| 性能下降 | 中 | 性能基准测试 |
| 用户学习成本 | 中 | 详细文档和示例 |

---

## 八、里程碑

- **M1 (Week 2)**: 基础架构完成
- **M2 (Week 5)**: 核心功能可用
- **M3 (Week 8)**: Beta 版本发布
- **M4 (Week 10)**: 正式版本发布

---

**创建时间**: 2026-04-02
**创建者**: CodeBuddy (GLM-5.0)
**参考**: Claude Code 架构分析（by Qwen）
