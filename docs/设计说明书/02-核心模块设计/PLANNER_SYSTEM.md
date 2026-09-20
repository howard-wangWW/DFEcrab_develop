# DFEcrab 任务规划系统

## 📋 概述

DFEcrab 的任务规划系统采用渐进式改进策略，在现有 ReActAgent 基础上增加任务复杂度检测和规划能力。

### 目标

- 简单任务直接执行
- 复杂任务先规划后执行
- 支持多步骤任务分解
- 与记忆系统集成

---

## 🏗️ 架构设计

### 当前架构（阶段1）

```
用户请求
    ↓
┌─────────────────────────────────────┐
│           ReActAgent                  │
│                                      │
│  1. 接收用户请求                      │
│  2. 调用 planner 技能分析复杂度        │
│  3. 生成执行计划                      │
│  4. 按计划执行步骤                    │
│  5. 调用 project_memory 保存记忆       │
└─────────────────────────────────────┘
    ↓
返回结果
```

### 目标架构（阶段2）

```
用户请求
    ↓
┌─────────────────────────────────────────┐
│           TaskOrchestrator               │
│         （任务编排器）                  │
└──────────────────┬──────────────────────┘
                   │
        ┌──────────┴──────────┐
        ↓                   ↓
┌───────────────┐   ┌───────────────┐
│ Planner Agent │   │ Executor Agent│
│               │   │               │
│ • 分析任务     │   │ • 执行计划步骤 │
│ • 生成计划     │   │ • 调用工具    │
│ • 验证计划     │   │ • 汇报结果    │
└───────────────┘   └───────┬───────┘
                            │
                     ┌──────┴──────┐
                     ↓             ↓
                  成功           失败
                  返回          回滚/
                               重试
```

---

## 🤖 技能列表

### 1. planner 技能

分析任务复杂度，生成执行计划。

**技能参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `task` | string | 用户任务描述 |
| `context` | object | 上下文信息（可选）|

**使用示例：**
```
调用 planner 技能分析：帮我部署一个 Docker 应用
```

**输出示例：**
```
## 任务分析

**复杂度等级**: MEDIUM

## 执行计划

### 步骤 1: 环境检查
- **描述**: 检查当前环境和依赖是否满足
- **使用工具**: []
- **预期结果**: 环境状态报告

### 步骤 2: 准备配置文件
- **描述**: 创建或修改必要的配置文件
- **使用工具**: [file_write]
- **预期结果**: 配置文件就绪

...
```

### 2. 复杂度检测

**关键词权重：**

| 关键词 | 权重 | 说明 |
|--------|------|------|
| 部署、安装、搭建 | +1 | 系统部署类 |
| 开发、创建、编写、实现 | +1 | 开发类 |
| 目录、文件夹、所有文件 | +1 | 多文件类 |
| 分析、了解、理解 | +1 | 分析类 |
| 项目、系统、应用 | +1 | 项目类 |
| 多个、一系列、批量 | +1 | 多步骤类 |

**复杂度阈值：**
- LOW (0-1): 直接执行
- MEDIUM (2-3): 建议规划
- HIGH (4+): 强制规划

---

## 📊 任务类型与计划模板

### 1. 部署类任务

```python
if "部署" in task or "安装" in task or "搭建" in task:
    steps = [
        {"step": 1, "action": "环境检查", "tools": []},
        {"step": 2, "action": "准备配置文件", "tools": ["file_write"]},
        {"step": 3, "action": "执行部署", "tools": ["execute_python", "shell_command"]},
        {"step": 4, "action": "验证结果", "tools": ["file_read", "shell_command"]}
    ]
```

### 2. 开发类任务

```python
if "开发" in task or "创建" in task or "编写" in task:
    steps = [
        {"step": 1, "action": "需求分析", "tools": []},
        {"step": 2, "action": "方案设计", "tools": []},
        {"step": 3, "action": "编写代码", "tools": ["file_write"]},
        {"step": 4, "action": "测试验证", "tools": ["execute_python"]}
    ]
```

### 3. 目录分析类任务

```python
if "目录" in task or "所有文件" in task:
    steps = [
        {"step": 1, "action": "列出目录文件", "tools": ["list_dir"]},
        {"step": 2, "action": "筛选目标文件", "tools": []},
        {"step": 3, "action": "逐个读取文件", "tools": ["file_read", "word_read"]},
        {"step": 4, "action": "综合分析", "tools": []}
    ]
```

### 4. 简单任务

```python
# 复杂度 LOW
steps = [
    {"step": 1, "action": "理解任务", "tools": []},
    {"step": 2, "action": "执行", "tools": ["file_read"]}
]
```

---

## 🔧 技术实现

### Planner 技能入口

```python
# skills/planner/execute.py
from agentscope.service import ServiceResponse, ServiceExecStatus

def execute(task: str, context: dict = None) -> ServiceResponse:
    """
    分析任务并生成执行计划
    """
    complexity_score = _calculate_complexity(task)
    plan = _generate_plan(task, context)

    if complexity_score >= COMPLEXITY_THRESHOLD:
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=_format_complex_plan(task, plan)
        )
    else:
        return ServiceResponse(
            status=ServiceExecStatus.SUCCESS,
            content=_format_simple_plan(task)
        )
```

---

## 📈 阶段规划

### 阶段1：渐进式改进 ✅ 已完成

- [x] 创建 planner 技能
- [x] 实现复杂度检测
- [x] 生成执行计划
- [x] 支持多种任务类型
- [x] 与记忆系统集成

### 阶段2：Orchestrator 重构 🔄 待开发

- [ ] 实现 TaskOrchestrator 编排器
- [ ] 创建 PlannerAgent
- [ ] 创建 ExecutorAgent
- [ ] 支持计划审核（用户确认）
- [ ] 支持计划调整

### 阶段3：高级能力 📋 规划中

- [ ] 支持嵌套子任务
- [ ] 支持任务并行执行
- [ ] 支持任务回滚
- [ ] 支持执行监控

---

## 🚀 实际演示

### 演示 1：复杂任务规划

```bash
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请调用 planner 技能分析：帮我部署一个 Docker 应用到服务器"}'
```

**响应：**
```
## 任务分析

**复杂度等级**: MEDIUM

## 执行计划

### 步骤 1: 环境检查
- **描述**: 检查服务器环境和 Docker 依赖
- **使用工具**: [shell_command]
- **预期结果**: 环境状态报告

...
```

### 演示 2：目录分析任务

```bash
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请调用 planner 技能分析：帮我分析 /Users/zhanghanzhi/DFEcrab/src 目录下的所有 Python 文件"}'
```

**响应：**
```
## 执行计划

### 步骤 1: 列出目录文件
- **使用工具**: [list_dir]

### 步骤 2: 筛选目标文件
- **使用工具**: []

### 步骤 3: 逐个读取文件
- **使用工具**: [file_read]

### 步骤 4: 综合分析
- **使用工具**: []
```

---

## 💡 使用建议

### 1. 触发规划

AI 会自动检测任务复杂度并决定是否调用 planner。你也可以显式要求：

```
请先调用 planner 技能分析这个任务：...
```

### 2. 结合记忆

复杂任务完成后，记得让 AI 保存记忆：

```
请调用 project_memory 技能保存：完成了 XX 功能开发，分类：progress
```

### 3. 查看计划

如果想看完整的执行计划，可以问：

```
请返回这个任务的执行计划
```

---

## 📊 与 OpenClaw 对比

| 功能 | OpenClaw | DFEcrab | 状态 |
|------|----------|---------|------|
| **任务复杂度检测** | ❌ | ✅ | ✅ 已实现 |
| **执行计划生成** | ❌ | ✅ | ✅ 已实现 |
| **步骤分解** | ❌ | ✅ | ✅ 已实现 |
| **Planner Agent** | ✅ | ❌ | ⏳ 待开发 |
| **Executor Agent** | ✅ | ❌ | ⏳ 待开发 |
| **计划审核** | ✅ | ❌ | ⏳ 待开发 |
| **子任务嵌套** | ✅ | ❌ | ⏳ 待开发 |

---

**文档版本：** 1.0
**更新时间：** 2026-03-29
**状态：** 阶段1已完成，阶段2待开发