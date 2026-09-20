# DFEcrab 设计说明书

## 📚 文档说明

本目录包含 DFEcrab 项目的所有设计文档，涵盖系统架构、模块设计、交互设计、多智能体设计等内容。

## 📋 文档列表

### 1. 总体设计

- [项目概览](./01-总体设计/PROJECT_OVERVIEW.md) - 项目整体介绍
- [架构设计](./01-总体设计/ARCHITECTURE_V2.md) - 系统架构设计
- **[gRPC 架构设计](./01-总体设计/GRPC_ARCHITECTURE.md)** ⭐ 新增 - Gateway → Manager → Workers gRPC 通信
- [网关架构](./01-总体设计/GATEWAY_ARCHITECTURE.md) - Gateway 架构设计
- [单节点网关](./01-总体设计/SINGLE_NODE_GATEWAY.md) - 单节点 Gateway 部署
- [重构计划](./01-总体设计/REFACTORING_PLAN.md) - 重构路线图
- [重构计划 V2](./01-总体设计/REFACTORING_PLAN_V2.md) - 重构路线图 V2

### 2. 核心模块设计

- [记忆系统设计](./02-核心模块设计/MEMORY_SYSTEM.md) - 记忆系统架构
- **[大模型集成设计](./02-核心模块设计/LLM_INTEGRATION.md)** ⭐ 新增 - llama.cpp server 集成
- [规划系统](./02-核心模块设计/PLANNER_SYSTEM.md) - Planner 系统设计
- [会话类型](./02-核心模块设计/SESSION_TYPES.md) - 会话类型设计
- [任务调度系统设计](./02-核心模块设计/TASK_SCHEDULER_SYSTEM.md) - 任务执行管理
- [自我反思系统设计](./02-核心模块设计/SELF_REFLECTION_SYSTEM.md) - 自我优化机制
- [权限系统设计](./02-核心模块设计/PERMISSION_SYSTEM.md) - 四级权限控制架构
- [工具系统设计](./02-核心模块设计/TOOL_SYSTEM.md) - 统一工具系统架构
- [上下文引擎设计](./02-核心模块设计/CONTEXT_ENGINE.md) - 上下文管理与优化

### 3. 交互设计

#### 3.1 CLI 交互

- [CLI 管理与通信](./03-交互设计/CLI_MANAGEMENT_AND_COMMUNICATION.md) - CLI 管理与通信机制
- [多 CLI 架构](./03-交互设计/MULTI_CLI_ARCHITECTURE.md) - 多 CLI 架构设计

#### 3.2 TUI 设计

- [TUI 重构计划](./03-交互设计/TUI_REFACTORING_PLAN.md) - TUI 重构方案
- [TUI 样式重构](./03-交互设计/TUI_STYLE_REFACTORING.md) - TUI 样式优化

#### 3.3 调度交互

- [自然语言调度器](./03-交互设计/NATURAL_LANGUAGE_SCHEDULER.md) - 自然语言调度交互
- [调度器增强](./03-交互设计/SCHEDULER_ENHANCEMENTS.md) - 调度器功能增强

### 4. 多智能体设计

- [多智能体交互](./04-多智能体/MULTI_AGENT_INTERACTION.md) - 多智能体交互协议
- [Group 运行时模型](./04-多智能体/GROUP_RUNTIME_MODELS.md) - Group 运行时模型
- [Session-Agent-Group 架构](./04-多智能体/SESSION_AGENT_GROUP_ARCHITECTURE.md) - 会话-智能体-组架构
- [MVP 测试计划](./04-多智能体/MVP_TEST_PLAN.md) - MVP 测试方案

## 📁 文档结构

```
设计说明书/
├── 01-总体设计/
│   ├── PROJECT_OVERVIEW.md          # 项目概览
│   ├── ARCHITECTURE_V2.md           # 架构设计
│   ├── GATEWAY_ARCHITECTURE.md      # 网关架构
│   ├── SINGLE_NODE_GATEWAY.md       # 单节点网关
│   ├── REFACTORING_PLAN.md          # 重构计划
│   └── REFACTORING_PLAN_V2.md       # 重构计划 V2
├── 02-核心模块设计/
│   ├── MEMORY_SYSTEM.md             # 记忆系统
│   ├── PLANNER_SYSTEM.md            # 规划系统
│   ├── SESSION_TYPES.md             # 会话类型
│   ├── TASK_SCHEDULER_SYSTEM.md     # 任务调度系统
│   ├── SELF_REFLECTION_SYSTEM.md    # 自我反思系统
│   ├── PERMISSION_SYSTEM.md         # 权限系统
│   ├── TOOL_SYSTEM.md               # 工具系统
│   └── CONTEXT_ENGINE.md            # 上下文引擎
├── 03-交互设计/
│   ├── CLI_MANAGEMENT_AND_COMMUNICATION.md  # CLI 管理与通信
│   ├── MULTI_CLI_ARCHITECTURE.md    # 多 CLI 架构
│   ├── TUI_REFACTORING_PLAN.md      # TUI 重构计划
│   ├── TUI_STYLE_REFACTORING.md     # TUI 样式重构
│   ├── NATURAL_LANGUAGE_SCHEDULER.md# 自然语言调度器
│   └── SCHEDULER_ENHANCEMENTS.md    # 调度器增强
└── 04-多智能体/
    ├── MULTI_AGENT_INTERACTION.md   # 多智能体交互
    ├── GROUP_RUNTIME_MODELS.md      # Group 运行时模型
    ├── SESSION_AGENT_GROUP_ARCHITECTURE.md  # Session-Agent-Group 架构
    └── MVP_TEST_PLAN.md             # MVP 测试计划
```

## 🎯 设计原则

1. **微内核架构** - 核心精简，功能插件化
2. **模块化设计** - 高内聚，低耦合
3. **可扩展性** - 易于添加新功能
4. **可维护性** - 代码清晰，文档完善
5. **智能化** - AI 驱动，自优化

## 📊 系统架构

```
┌─────────────────────────────────────────┐
│           应用层（Application）          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐ │
│  │  TUI    │  │  CLI    │  │  API    │ │
│  └─────────┘  └─────────┘  └─────────┘ │
├─────────────────────────────────────────┤
│           网关层（Gateway）              │
│  ┌─────────────────────────────────┐   │
│  │   路由 | 会话 | 插件 | 任务      │   │
│  └─────────────────────────────────┘   │
├─────────────────────────────────────────┤
│           核心层（Core）                 │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐      │
│  │插件 │ │记忆 │ │会话 │ │任务 │      │
│  │管理 │ │管理 │ │管理 │ │调度 │      │
│  └─────┘ └─────┘ └─────┘ └─────┘      │
├─────────────────────────────────────────┤
│           服务层（Services）             │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐      │
│  │智能 │ │记忆 │ │技能 │ │发现 │      │
│  │体   │ │服务 │ │服务 │ │服务 │      │
│  └─────┘ └─────┘ └─────┘ └─────┘      │
└─────────────────────────────────────────┘
```

## 📝 版本信息

- **版本**: 4.0
- **文档数量**: 22 个设计文档
- **更新日期**: 2026-04-03
- **状态**: 已完成

---

**文档维护**: DFEcrab Team
**文档索引**: [三书一册](../README.md)
