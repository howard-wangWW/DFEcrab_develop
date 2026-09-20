# 自我反思系统使用指南

## 📋 概述

自我反思系统让智能体能够：
- ✅ 定期回顾对话历史
- ✅ 评估用户满意度
- ✅ 识别服务中的问题
- ✅ 生成并执行改进计划
- ✅ 持续优化服务质量

## 🏗️ 系统架构

```
┌─────────────────────────────────────────┐
│     SelfReflector（自我反思器）          │
├─────────────────────────────────────────┤
│ 1. ConversationAnalyzer（对话分析器）   │
│    - 分析最近 N 次对话                     │
│    - 提取关键指标                        │
│                                         │
│ 2. SatisfactionAnalyzer（满意度分析器） │
│    - AI 评估用户满意度                    │
│    - 识别积极/消极信号                   │
│                                         │
│ 3. IssueDetector（问题检测器）          │
│    - 识别重复回答                        │
│    - 检测知识盲区                        │
│    - 发现回复质量问题                    │
│                                         │
│ 4. ImprovementPlanner（改进计划生成器） │
│    - 生成具体改进措施                    │
│    - 优先级排序                          │
│    - 执行改进                          │
└─────────────────────────────────────────┘
```

## 🚀 功能特性

### 1. 自动定时反思
- **默认频率**：每 24 小时自动执行一次
- **触发条件**：智能体至少有 10 条对话
- **可配置**：可通过 `Gateway._reflection_interval_hours` 调整

### 2. 用户满意度评估
```json
{
  "score": 0.85,           // 满意度得分（0-1）
  "confidence": 0.9,       // 置信度（0-1）
  "positive_signals": [    // 积极信号
    "用户多次表示感谢",
    "用户继续追问显示兴趣"
  ],
  "negative_signals": [    // 消极信号
    "有一次用户重复提问"
  ],
  "summary": "整体满意度较高..."
}
```

### 3. 问题识别
支持识别的问题类型：
- `repetition` - 重复回答相同内容
- `knowledge_gap` - 知识盲区
- `poor_response` - 回复质量差
- `slow_response` - 响应慢
- `other` - 其他问题

### 4. 改进计划
每个改进计划包含：
- **行动类型**：行为调整、记忆更新、技能学习、Bug 修复
- **优先级**：1-5（5 最高）
- **预期影响**：描述改进后的效果
- **实施步骤**：具体的执行步骤
- **预计工作量**：low/medium/high

## 📡 API 接口

### 1. 列出反思历史
```bash
GET /api/reflections?agent_id={agent_id}&limit={limit}

# 示例
curl http://localhost:6789/api/reflections?agent_id=default&limit=10
```

**返回：**
```json
{
  "success": true,
  "count": 5,
  "reflections": [
    {
      "reflection_id": "reflection_20260329_010000",
      "agent_id": "default",
      "timestamp": "2026-03-29T01:00:00",
      "conversations_analyzed": 50,
      "satisfaction_score": 0.85,
      "issues_count": 2,
      "improvement_plan_count": 3,
      "summary": "分析了 50 条对话，整体表现良好..."
    }
  ]
}
```

### 2. 获取反思报告详情
```bash
GET /api/reflections/{reflection_id}

# 示例
curl http://localhost:6789/api/reflections/reflection_20260329_010000
```

**返回：**
```json
{
  "success": true,
  "reflection": {
    "reflection_id": "reflection_20260329_010000",
    "agent_id": "default",
    "timestamp": "2026-03-29T01:00:00",
    "satisfaction": {
      "score": 0.85,
      "confidence": 0.9,
      "positive_signals": [...],
      "negative_signals": [...],
      "summary": "..."
    },
    "issues": [...],
    "improvement_plan": [...],
    "summary": "..."
  }
}
```

### 3. 执行改进计划
```bash
POST /api/reflections/{reflection_id}/implement
Content-Type: application/json

{
  "action_indices": [0, 1]  // 可选，指定要执行的行动索引
}

# 示例
curl -X POST http://localhost:6789/api/reflections/reflection_20260329_010000/implement \
  -H "Content-Type: application/json" \
  -d '{"action_indices": [0, 1]}'
```

**返回：**
```json
{
  "success": true,
  "message": "已执行 2/5 项改进行动",
  "executed": 2
}
```

## 🔧 配置选项

### 修改反思频率
编辑 `src/core/gateway/gateway.py`：

```python
class Gateway:
    def __init__(self, ...):
        self._reflection_interval_hours = 24  # 24 小时（默认）
        # self._reflection_interval_hours = 0.016  # 1 分钟（测试用）
        # self._reflection_interval_hours = 168  # 1 周
        # self._reflection_interval_hours = 720  # 1 个月
```

### 修改触发条件
编辑 `src/core/self_reflector.py`：

```python
class SelfReflector:
    def __init__(self, ...):
        self._analysis_window_days = 7  # 分析最近 7 天的对话
        self._min_conversations_for_reflection = 10  # 最少对话数
        self._auto_implement = False  # 是否自动执行改进
```

## 📊 数据持久化

反思报告保存在：
```
reflections/
└── {agent_id}/
    ├── 2026-03-29.json
    ├── 2026-03-30.json
    └── ...
```

每个 JSON 文件包含完整的反思报告数据。

## 💡 使用场景

### 场景 1：定期自我优化
系统每天自动反思，识别问题并改进：
```
每天凌晨 2 点 → 分析昨天的对话 → 生成反思报告 → 执行改进计划
```

### 场景 2：问题诊断
当发现服务质量下降时，查看反思历史：
```bash
# 查看最近的反思报告
curl http://localhost:6789/api/reflections?agent_id=default&limit=5

# 查看具体报告详情
curl http://localhost:6789/api/reflections/reflection_20260329_010000
```

### 场景 3：手动执行改进
审查反思报告后，手动执行改进计划：
```bash
# 执行优先级最高的 3 个改进
curl -X POST http://localhost:6789/api/reflections/reflection_20260329_010000/implement \
  -H "Content-Type: application/json" \
  -d '{"action_indices": [0, 1, 2]}'
```

## 🎯 示例反思报告

```json
{
  "reflection_id": "reflection_20260329_010000",
  "agent_id": "default",
  "timestamp": "2026-03-29T01:00:00",
  "conversations_analyzed": 50,
  "satisfaction": {
    "score": 0.78,
    "confidence": 0.85,
    "positive_signals": [
      "用户多次表示感谢",
      "用户主动分享个人信息",
      "对话持续时间较长"
    ],
    "negative_signals": [
      "3 次重复回答相似内容",
      "1 次用户明确表示不满意"
    ],
    "summary": "整体表现良好，用户对大部分回答满意，但存在回答重复问题"
  },
  "issues": [
    {
      "issue_type": "repetition",
      "severity": "medium",
      "description": "在 3 次对话中重复了相似的回答",
      "evidence": [
        "对话 5 和对话 12 回答相似",
        "对话 20 和对话 25 回答相似"
      ],
      "occurrence_count": 3
    }
  ],
  "improvement_plan": [
    {
      "action_type": "adjust_behavior",
      "priority": 4,
      "description": "增加回答的多样性，避免重复",
      "expected_impact": "提升用户体验，减少重复感",
      "implementation_steps": [
        "维护回答历史避免重复",
        "从不同角度回答相似问题",
        "使用同义词替换"
      ],
      "estimated_effort": "medium",
      "status": "pending"
    }
  ]
}
```

## 🔍 监控和调试

### 查看反思日志
```bash
# 查看 Gateway 日志中的反思相关信息
grep -i "反思\|reflection" /tmp/gateway.log

# 查看反思文件
ls -la reflections/
cat reflections/default/2026-03-29.json
```

### 手动触发反思（测试用）
创建测试脚本 `test_manual_reflection.py`：
```python
import asyncio
from src.core.self_reflector import get_self_reflector, ConversationSample
from src.plugins.registry import get_plugin_registry
from src.core.session_manager import get_session_manager

async def manual_reflect():
    registry = get_plugin_registry()
    agent_plugin = registry.get("agent")
    reflector = get_self_reflector(agent_plugin)
    
    # 收集对话
    sessions = get_session_manager().list_sessions(agent_id="default")
    conversations = []
    for session in sessions:
        messages = session.get_context()
        for i in range(0, len(messages) - 1, 2):
            if messages[i]["role"] == "user" and messages[i+1]["role"] == "assistant":
                conversations.append({
                    "user_message": messages[i]["content"],
                    "assistant_response": messages[i+1]["content"],
                    "session_id": session.id
                })
    
    # 生成反思报告
    if len(conversations) >= 10:
        samples = [ConversationSample(**conv) for conv in conversations]
        report = await reflector.generate_reflection_report("default", samples)
        print(f"满意度：{report.satisfaction.score:.2f}")
        print(f"问题数：{len(report.issues)}")
        print(f"改进计划：{len(report.improvement_plan)}")

asyncio.run(manual_reflect())
```

## 📈 最佳实践

1. **调整反思频率**
   - 开发环境：1 小时或更短（快速迭代）
   - 生产环境：24 小时或更长（减少开销）

2. **审查改进计划**
   - 定期查看反思报告
   - 手动审核高优先级改进
   - 记录改进效果

3. **结合记忆系统**
   - 反思结果写入长期记忆
   - 形成学习闭环

4. **监控满意度趋势**
   - 跟踪满意度分数变化
   - 识别满意度下降的原因
   - 及时干预

## 🎓 技术细节

### AI 分析提示词
系统使用 AI 分析对话，提示词包含：
- 对话样本（最近 50 条）
- 分析任务说明
- 输出格式要求（JSON）
- 注意事项

### 降级策略
如果 AI 分析失败，系统会：
- 使用简单统计分析
- 返回基础指标
- 记录错误日志

### 性能优化
- 异步处理，不阻塞主服务
- 定时任务在后台运行
- 反思结果持久化到文件系统

---

**文档版本**：1.0
**创建时间**：2026-03-29
**状态**：已实现并测试通过
