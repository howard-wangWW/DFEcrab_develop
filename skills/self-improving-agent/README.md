# Self-Improving Agent for DFEcrab

这个技能让 DFEcrab 智能体能够从交互中持续学习和自我优化。

## 功能特性

- 📊 **会话学习** - 从每次对话中学习成功模式
- ❌ **错误学习** - 从错误中学习，避免重复犯错
- ✅ **恢复学习** - 记录成功的恢复模式
- 📈 **性能学习** - 追踪性能指标，优化响应

## 存储位置

```
/Users/zhanghanzhi/workspace/DFEcrab/learnings/
├── sessions.json      # 会话学习记录
├── errors.json        # 错误学习记录
├── recoveries.json    # 恢复学习记录
└── performance.json   # 性能学习记录
```

## 测试技能

```bash
cd /Users/zhanghanzhi/workspace/DFEcrab/skills/self-improving-agent
python3 test.py
```

## 与 DFEcrab 集成

### 1. 存储对比

| 系统 | 位置 | 用途 |
|------|------|------|
| DFEcrab 记忆 | `memory/` | 对话历史、用户偏好、知识库 |
| Self-Improving | `learnings/` | 错误模式、性能优化、成功模式 |

### 2. 互补关系

- **DFEcrab 记忆**: 记住"用户说什么"和"偏好"
- **Self-Improving**: 学习"如何做得更好"和"避免错误"

### 3. 使用建议

当前版本技能独立运行，测试通过。未来可以：

1. 在 DFEcrab 的 agent 中集成 Hook 系统
2. 自动记录错误、性能数据
3. 定期应用学习到的优化建议

## 手动使用

```python
from pathlib import Path
from skills.self_improving_agent.src.agent import SelfImprovingAgent

# 初始化
workspace = Path("/Users/zhanghanzhi/workspace/DFEcrab")
agent = SelfImprovingAgent(workspace)

# 开始会话
agent.start_session()
agent.track_interaction(success=True)
agent.end_session()

# 记录错误
agent.log_error("ValueError", "Invalid parameter", {"param": "age"})

# 记录恢复
agent.log_recovery("validation_check", {"action": "added validation"})

# 记录性能
agent.log_performance("response_time", 150, {"op": "query"}, ["Add caching"])

# 查看学习记录
agent.review_learnings()
```

## 数据格式示例

### sessions.json
```json
{
  "timestamp": "2026-03-25T10:38:23",
  "session_id": "session-20260325-103823",
  "duration": 120,
  "interactions": 5,
  "success_patterns": ["successful_interaction"]
}
```

### errors.json
```json
{
  "timestamp": "2026-03-25T10:38:23",
  "error_type": "ValueError",
  "error_message": "Invalid parameter",
  "context": {"param": "age", "value": -1}
}
```

## 文件结构

```
self-improving-agent/
├── SKILL.md              # 技能定义
├── execute.py            # CLI 入口点
├── README.md             # 本文件
├── test.py              # 测试脚本
├── src/
│   ├── __init__.py
│   ├── agent.py         # Agent 主类
│   ├── hooks.py         # Hook 管理器
│   └── memory.py        # 学习记忆系统
└── hooks/
    └── __init__.py
```

## 测试结果

✅ 所有测试通过
- 会话跟踪 ✓
- 错误学习 ✓
- 恢复学习 ✓
- 性能学习 ✓
- 数据持久化 ✓
- 导出功能 ✓
