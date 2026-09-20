# DFEcrab 记忆与自优化系统

## 📚 记忆系统架构

### 1. 分层记忆结构

```
┌─────────────────────────────────────────────────────────┐
│                    全局共享记忆                          │
│  GLOBAL.md - 项目配置 + 人格定义 + 智能体定义            │
│  （所有智能体共享，永久不变）                           │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                    工作记忆（分层）                      │
│                                                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │
│  │   DAILY/    │  │   WEEKLY/   │  │   MONTHLY/   │   │
│  │ YYYY-MM-DD  │  │ YYYY-Wnn.md │  │ YYYY-MM.md   │   │
│  │   每日      │  │   每周      │  │   每月      │   │
│  └─────────────┘  └─────────────┘  └─────────────┘   │
│         ↓                ↓                ↓             │
│    自动保存          每周汇总        每月汇总           │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│                    长期记忆                              │
│  LONG_TERM.md - 重要信息提取                            │
│  （从月度记忆中提取的关键信息）                          │
└─────────────────────────────────────────────────────────┘
```

### 2. 记忆文件布局

```
data/shared_memory/
├── GLOBAL.md           # 全局配置（永久）
│   # 全局共享记忆
│   ## 项目背景
│   ## 智能体人格定义
│
├── LONG_TERM.md       # 长期记忆
│   # 长期记忆
│   最后更新：2026-03-29
│   ## 重要信息
│
├── WEEKLY/            # 每周汇总
│   └── 2026-W13.md
│
├── MONTHLY/           # 每月汇总
│   └── 2026-03.md
│
└── DAILY/            # 每日记忆
    └── 2026-03-29.md
        📊 [PROGRESS] 2026-03-29 12:25
        分层记忆系统测试记录
```

### 3. 记忆分类

| 分类 | 说明 | 示例 |
|------|------|------|
| `general` | 通用信息 | 📝 |
| `background` | 项目背景 | 🏢 |
| `progress` | 工作进度 | 📊 |
| `decision` | 技术决策 | ⚖️ |
| `file_location` | 文件位置 | 📁 |
| `todo` | 待办事项 | ✅ |

---

## 🤖 记忆技能

### 1. project_memory 技能

管理项目记忆，支持分层存储。

**技能参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `action` | string | save/load/list/search/stats |
| `content` | string | 记忆内容（save时需要） |
| `category` | string | general/background/progress/decision/file_location/todo |

**使用示例：**
```
# 保存记忆
调用 project_memory 技能，操作：save，内容：完成了分层记忆系统，分类：progress

# 读取记忆
调用 project_memory 技能，操作：load

# 查看统计
调用 project_memory 技能，操作：list

# 搜索记忆
调用 project_memory 技能，操作：search，内容：记忆系统
```

### 2. memory_maintenance 技能

执行记忆维护任务。

**技能参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| `action` | string | weekly/monthly/extract/all |

**使用示例：**
```
# 执行每周汇总
调用 memory_maintenance 技能，操作：weekly

# 执行每月汇总
调用 memory_maintenance 技能，操作：monthly

# 提取长期记忆
调用 memory_maintenance 技能，操作：extract

# 执行所有维护
调用 memory_maintenance 技能，操作：all
```

---

## ⏰ 定时任务

### 1. 每周汇总

- **时间**：每周日 23:59
- **操作**：将 DAILY/ 目录下的每日记忆汇总到 WEEKLY/YYYY-Wnn.md
- **触发**：自动 + 手动（memory_maintenance skill）

### 2. 每月汇总

- **时间**：每月28-31日 23:59
- **操作**：将 WEEKLY/ 目录下的周记忆汇总到 MONTHLY/YYYY-MM.md
- **触发**：自动 + 手动（memory_maintenance skill）

### 3. 长期记忆提取

- **触发**：每月汇总后自动执行
- **操作**：从月度记忆中提取重要信息到 LONG_TERM.md

---

## 🔧 技术实现

### 分层记忆管理器

```python
from src.core.hierarchical_memory_manager import HierarchicalMemoryManager

manager = HierarchicalMemoryManager()

# 保存每日记忆
manager.save_daily_memory("完成了XX功能", category="progress")

# 加载所有上下文
context = manager.load_all_context()

# 每周汇总
manager.weekly_summary()

# 每月汇总
manager.monthly_summary()

# 提取长期记忆
manager.extract_long_term_memory()

# 获取统计
stats = manager.get_stats()
```

### 全局记忆管理器

```python
from src.core.hierarchical_memory_manager import get_global_memory_manager

manager = get_global_memory_manager()
```

---

## 📊 记忆工作流程

```
用户对话
    ↓
project_memory.save()
    ├─→ 私有记忆（agents/{agent_id}/memory/）
    └─→ 全局分层记忆
            ↓
    ┌──────┴──────┐
    ↓              ↓
DAILY/         系统启动时
YYYY-MM-DD.md      ↓
              _load_memory_context()
                    ↓
            注入到 System Prompt
                    ↓
            AI 自动获得记忆

定时触发（周日/月未）
    ↓
memory_maintenance
    ├─→ weekly_summary()
    ├─→ monthly_summary()
    └─→ extract_long_term_memory()
```

---

## 🚀 实际演示

### 演示 1：保存记忆

```bash
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请调用 project_memory 技能保存：完成了分层记忆系统开发，分类：progress"}'
```

### 演示 2：读取记忆

```bash
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请调用 project_memory 技能读取所有项目记忆"}'
```

### 演示 3：手动汇总

```bash
curl -X POST http://localhost:6789/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "请调用 memory_maintenance 技能执行每周汇总"}'
```

### 演示 4：查看记忆文件

```bash
# 查看今日记忆
cat data/shared_memory/DAILY/2026-03-29.md

# 查看本周汇总
cat data/shared_memory/WEEKLY/2026-W13.md

# 查看全局配置
cat data/shared_memory/GLOBAL.md
```

---

## 📊 记忆系统对比

| 功能 | OpenClaw | DFEcrab V3 | 状态 |
|------|----------|------------|------|
| **每日记忆** | ✅ | ✅ DAILY/ | ✅ 已实现 |
| **每周汇总** | ❌ | ✅ WEEKLY/ | ✅ 已实现 |
| **每月汇总** | ❌ | ✅ MONTHLY/ | ✅ 已实现 |
| **长期记忆** | ✅ | ✅ LONG_TERM.md | ✅ 已实现 |
| **全局共享** | ❌ | ✅ GLOBAL.md | ✅ 已实现 |
| **人格定义** | ❌ | ✅ GLOBAL.md | ✅ 已实现 |
| **定时汇总** | ❌ | ✅ 每周/每月 | ✅ 已实现 |
| **记忆技能** | ❌ | ✅ project_memory | ✅ 已实现 |

---

## 💡 使用建议

### 1. 推荐的记忆分类使用

| 场景 | 推荐分类 |
|------|----------|
| 完成一个功能开发 | `progress` |
| 确定技术方案 | `decision` |
| 了解项目背景 | `background` |
| 重要文件路径 | `file_location` |
| 待完成的任务 | `todo` |

### 2. 记忆保存时机

- **重要任务完成后**：主动保存工作进度
- **发现项目信息时**：保存关键背景
- **做技术决策时**：保存决策理由
- **用户明确要求时**：按要求保存

### 3. 记忆维护

- 系统自动在每周日、每月末进行汇总
- 可以手动触发：`调用 memory_maintenance 技能，操作：all`
- 定期检查 LONG_TERM.md 确保信息准确

---

**文档版本：** 2.0
**更新时间：** 2026-03-29
**状态：** ✅ 已实现完整分层记忆系统