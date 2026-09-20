# 自然语言定时任务交互设计方案

**版本**：v4.2.0  
**创建日期**：2026-03-30  
**目标**：通过自然语言交互设置心跳任务和定时任务

---

## 📋 目录

1. [现状分析](#1-现状分析)
2. [设计目标](#2-设计目标)
3. [交互设计](#3-交互设计)
4. [技术架构](#4-技术架构)
5. [实施计划](#5-实施计划)

---

## 1. 现状分析

### 1.1 当前功能

DFEcrab 已有心跳和定时任务功能，但**只能通过代码/配置文件设置**：

```python
# 方式 1: 代码方式
scheduler = get_scheduler()
task = ScheduledTask(
    task_id="test",
    name="测试任务",
    handler=test_func,
    interval_seconds=300
)
scheduler.register_scheduled_task(task)

# 方式 2: 配置文件
# agents/{agent_id}/cron.json
[{"name": "每日备份", "cron": "0 2 * * *"}]
```

### 1.2 问题

- ❌ 需要编写代码
- ❌ 需要理解 Cron 表达式
- ❌ 无法动态添加/修改
- ❌ 没有友好的交互界面

### 1.3 用户需求

```
用户想要：
"帮我设置一个每天早上 9 点的提醒，让我检查项目进度"
"每 30 分钟检查一次系统状态"
"每周五下午 5 点生成周报"
```

---

## 2. 设计目标

### 2.1 核心功能

1. **自然语言解析** - 理解用户的时间表达
2. **动态任务管理** - 运行时添加/修改/删除任务
3. **任务确认** - 执行前向用户确认
4. **任务查询** - 查看已设置的任务列表
5. **任务统计** - 显示任务执行情况

### 2.2 交互方式

| 方式 | 示例 | 状态 |
|------|------|------|
| **自然语言** | "每天早上 9 点提醒我开会" | ✅ 新增 |
| **Slash 命令** | `/schedule add 每天早上 9 点 开会` | ✅ 增强 |
| **TUI 界面** | 图形化任务管理界面 | ✅ 新增 |

### 2.3 支持的时间表达

| 类型 | 示例 | 转换结果 |
|------|------|----------|
| **固定时间** | "每天早上 9 点" | `0 9 * * *` |
| **相对时间** | "每 30 分钟" | `*/30 * * * *` |
| **每周** | "每周一上午 10 点" | `0 10 * * 1` |
| **每月** | "每月 1 号" | `0 0 1 * *` |
| **每年** | "每年元旦" | `0 0 1 1 *` |
| **中文数字** | "每周三下午三点" | `0 15 * * 3` |

---

## 3. 交互设计

### 3.1 自然语言对话示例

#### 场景 1: 创建定时任务

```
👤 用户：帮我设置一个每天早上 9 点的提醒，让我检查项目进度

🤖 AI：好的，我已理解您的需求：
   
   📋 任务确认
   ━━━━━━━━━━━━━━━━━━━━━━━
   任务名称：检查项目进度
   执行时间：每天早上 9:00
   Cron 表达式：0 9 * * *
   时区：Asia/Shanghai
   ━━━━━━━━━━━━━━━━━━━━━━━
   
   是否确认创建此任务？（回复"确认"或"取消"）

👤 用户：确认

🤖 AI：✅ 任务创建成功！
   
   任务 ID: task_20260330_001
   下次执行：2026-03-31 09:00:00
   
   您可以使用以下命令管理任务：
   - /schedule list - 查看任务列表
   - /schedule cancel task_20260330_001 - 取消任务
```

#### 场景 2: 查询任务

```
👤 用户：我有哪些定时任务？

🤖 AI：您目前有 3 个定时任务：
   
   📋 定时任务列表
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   1. 检查项目进度
      ⏰ 每天早上 9:00 (0 9 * * *)
      📅 下次执行：2026-03-31 09:00:00
      ✅ 状态：正常
   
   2. 系统健康检查
      ⏰ 每 30 分钟 (*/30 * * * *)
      📅 下次执行：2026-03-30 15:30:00
      ✅ 状态：正常
   
   3. 生成周报
      ⏰ 每周五 17:00 (0 17 * * 5)
      📅 下次执行：2026-04-04 17:00:00
      ⏸️ 状态：已暂停
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### 场景 3: 修改任务

```
👤 用户：把每天早上 9 点的提醒改成 9 点半

🤖 AI：好的，我已理解您的需求：
   
   📋 任务修改确认
   ━━━━━━━━━━━━━━━━━━━━━━━
   任务名称：检查项目进度
   原执行时间：每天早上 9:00
   新执行时间：每天早上 9:30
   新 Cron 表达式：30 9 * * *
   ━━━━━━━━━━━━━━━━━━━━━━━
   
   是否确认修改？（回复"确认"或"取消"）

👤 用户：确认

🤖 AI：✅ 任务修改成功！
   
   下次执行：2026-03-31 09:30:00
```

#### 场景 4: 删除任务

```
👤 用户：取消每天早上 9 点半的提醒

🤖 AI：您确认要取消以下任务吗？
   
   📋 任务删除确认
   ━━━━━━━━━━━━━━━━━━━━━━━
   任务名称：检查项目进度
   执行时间：每天早上 9:30
   已执行次数：15 次
   ━━━━━━━━━━━━━━━━━━━━━━━
   
   回复"确认"删除，此操作不可恢复。

👤 用户：确认

🤖 AI：✅ 任务已删除
```

### 3.2 Slash 命令

```bash
# 创建任务
/schedule add <时间表达> <任务描述>
  /schedule add 每天早上 9 点 检查项目进度
  /schedule add 每 30 分钟 系统健康检查
  /schedule add 每周五下午 5 点 生成周报

# 查看任务
/schedule list
/schedule ls

# 查看任务详情
/schedule show <task_id>
/schedule show task_20260330_001

# 修改任务
/schedule modify <task_id> <新时间表达>
  /schedule modify task_20260330_001 每天早上 9 点半

# 暂停/恢复任务
/schedule pause <task_id>
/schedule resume <task_id>

# 删除任务
/schedule cancel <task_id>
/schedule delete <task_id>

# 立即执行任务
/schedule run <task_id>
  /schedule run task_20260330_001

# 查看任务统计
/schedule stats
```

### 3.3 TUI 界面

```
┌─────────────────────────────────────────────────────────┐
│  📋 定时任务管理                                  [×]   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  [+ 新建任务]  [刷新]  [批量操作 ▼]                    │
│                                                         │
│  ┌───────────────────────────────────────────────────┐ │
│  │ ✓ 检查项目进度                                    │ │
│  │   ⏰ 每天早上 9:00  │ 📅 下次：03-31 09:00 │ ✅   │ │
│  ├───────────────────────────────────────────────────┤ │
│  │ ✓ 系统健康检查                                    │ │
│  │   ⏰ 每 30 分钟     │ 📅 下次：今天 15:30  │ ✅   │ │
│  ├───────────────────────────────────────────────────┤ │
│  │ ☐ 生成周报                                        │ │
│  │   ⏰ 每周五 17:00   │ 📅 下次：04-04 17:00 │ ⏸️   │ │
│  └───────────────────────────────────────────────────┘ │
│                                                         │
│  共 3 个任务 | 运行中：2 | 已暂停：1                    │
│                                                         │
│  [编辑] [暂停/恢复] [删除] [立即执行] [统计]            │
└─────────────────────────────────────────────────────────┘
```

---

## 4. 技术架构

### 4.1 架构图

```
┌─────────────────────────────────────────────────────────┐
│                    用户输入层                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ 自然语言 │  │  Slash   │  │   TUI    │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
└───────┼─────────────┼─────────────┼────────────────────┘
        │             │             │
┌───────┴─────────────┴─────────────┴────────────────────┐
│                   自然语言解析器                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  时间表达式识别  │  意图识别  │  实体抽取        │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────┬───────────────────────────────┘
                         │
┌────────────────────────┴───────────────────────────────┐
│                   任务管理器                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │ 任务创建    │  │ 任务查询    │  │ 任务修改    │    │
│  └─────────────┘  └─────────────┘  └─────────────┘    │
└────────────────────────┬───────────────────────────────┘
                         │
┌────────────────────────┴───────────────────────────────┐
│                   任务调度器                            │
│              (TaskScheduler - 已有)                     │
└─────────────────────────────────────────────────────────┘
```

### 4.2 核心模块

#### 4.2.1 自然语言解析器

```python
# src/core/nlp/time_parser.py

import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

class TimeExpressionParser:
    """时间表达式解析器"""
    
    # 中文数字映射
    CHINESE_NUMS = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '零': 0, '半': 30
    }
    
    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        """解析时间表达式
        
        Args:
            text: 用户输入的时间表达式
            
        Returns:
            包含 cron 表达式和人类可读描述的字典
        """
        text = text.lower().strip()
        
        # 尝试各种模式匹配
        patterns = [
            (self._parse_every_minute, "每分钟"),
            (self._parse_every_hour, "每小时"),
            (self._parse_every_day, "每天"),
            (self._parse_every_week, "每周"),
            (self._parse_every_month, "每月"),
            (self._parse_fixed_time, "固定时间"),
            (self._parse_relative, "相对时间"),
        ]
        
        for parser, description in patterns:
            result = parser(text)
            if result:
                result['pattern_type'] = description
                return result
        
        return None
    
    def _parse_every_minute(self, text: str) -> Optional[Dict]:
        """解析"每 X 分钟"模式"""
        match = re.search(r'每 (\d+) 分钟', text)
        if match:
            minutes = int(match.group(1))
            return {
                'cron': f'*/{minutes} * * * *',
                'human_readable': f'每{minutes}分钟',
                'interval_seconds': minutes * 60
            }
        
        match = re.search(r'每半小时', text)
        if match:
            return {
                'cron': '*/30 * * * *',
                'human_readable': '每 30 分钟',
                'interval_seconds': 1800
            }
        
        return None
    
    def _parse_fixed_time(self, text: str) -> Optional[Dict]:
        """解析固定时间模式"""
        # "每天早上 9 点"
        match = re.search(r'每天早上 (\d+)[点时]', text)
        if match:
            hour = int(match.group(1))
            return {
                'cron': f'0 {hour} * * *',
                'human_readable': f'每天早上{hour}:00',
            }
        
        # "每天早上 9 点半"
        match = re.search(r'每天早上 (\d+)[点时] 半', text)
        if match:
            hour = int(match.group(1))
            return {
                'cron': f'30 {hour} * * *',
                'human_readable': f'每天早上{hour}:30',
            }
        
        # "每周一上午 10 点"
        match = re.search(r'每周 ([一二三四五六日天]) 上午 (\d+)[点时]', text)
        if match:
            weekday = self._chinese_to_weekday(match.group(1))
            hour = int(match.group(2))
            return {
                'cron': f'0 {hour} * * {weekday}',
                'human_readable': f'每周{match.group(1)}上午{hour}:00',
            }
        
        return None
    
    def _chinese_to_weekday(self, char: str) -> int:
        """中文星期转换为数字"""
        mapping = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '日': 0, '天': 0
        }
        return mapping.get(char, 1)
```

#### 4.2.2 意图识别器

```python
# src/core/nlp/intent_parser.py

from enum import Enum
from typing import Optional, Dict, Any, List

class IntentType(Enum):
    CREATE_SCHEDULE = "create_schedule"
    QUERY_SCHEDULE = "query_schedule"
    MODIFY_SCHEDULE = "modify_schedule"
    DELETE_SCHEDULE = "delete_schedule"
    PAUSE_SCHEDULE = "pause_schedule"
    RESUME_SCHEDULE = "resume_schedule"
    RUN_SCHEDULE = "run_schedule"
    UNKNOWN = "unknown"

class IntentParser:
    """意图解析器"""
    
    def __init__(self):
        self.keywords = {
            IntentType.CREATE_SCHEDULE: ['设置', '创建', '添加', '提醒', '计划'],
            IntentType.QUERY_SCHEDULE: ['查看', '查询', '列表', '哪些', '任务'],
            IntentType.MODIFY_SCHEDULE: ['修改', '更改', '调整', '改成', '改为'],
            IntentType.DELETE_SCHEDULE: ['删除', '取消', '移除', '不要'],
            IntentType.PAUSE_SCHEDULE: ['暂停', '停止', '暂缓'],
            IntentType.RESUME_SCHEDULE: ['恢复', '继续', '启用'],
            IntentType.RUN_SCHEDULE: ['立即执行', '马上运行', '现在执行'],
        }
    
    def parse(self, text: str) -> Dict[str, Any]:
        """解析用户意图
        
        Returns:
            {
                'intent': IntentType,
                'confidence': float,
                'entities': Dict
            }
        """
        # 基于关键词匹配意图
        intent_scores = {}
        for intent, keywords in self.keywords.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                intent_scores[intent] = score
        
        if not intent_scores:
            return {
                'intent': IntentType.UNKNOWN,
                'confidence': 0.0,
                'entities': {}
            }
        
        # 选择得分最高的意图
        best_intent = max(intent_scores, key=intent_scores.get)
        confidence = min(intent_scores[best_intent] / 3.0, 1.0)
        
        # 提取实体
        entities = self._extract_entities(text, best_intent)
        
        return {
            'intent': best_intent,
            'confidence': confidence,
            'entities': entities
        }
    
    def _extract_entities(self, text: str, intent: IntentType) -> Dict[str, Any]:
        """提取实体信息"""
        entities = {}
        
        if intent == IntentType.CREATE_SCHEDULE:
            # 提取时间表达式
            from .time_parser import TimeExpressionParser
            parser = TimeExpressionParser()
            time_info = parser.parse(text)
            if time_info:
                entities['time_expression'] = time_info
            
            # 提取任务描述（时间表达式之后的内容）
            # 简化处理：移除时间相关词汇后的文本
            task_desc = text
            for kw in ['设置', '创建', '添加', '提醒', '计划']:
                task_desc = task_desc.replace(kw, '')
            if time_info:
                task_desc = task_desc.replace(time_info['human_readable'], '')
            entities['task_description'] = task_desc.strip()
        
        elif intent in [IntentType.MODIFY_SCHEDULE, IntentType.DELETE_SCHEDULE]:
            # 提取任务 ID 或任务名称
            # 简化：查找类似"task_xxx"的模式
            import re
            match = re.search(r'task_\w+', text)
            if match:
                entities['task_id'] = match.group()
        
        return entities
```

#### 4.2.3 任务管理插件

```python
# src/plugins/builtin/scheduler_plugin/__init__.py

from src.core.plugin import BasePlugin, PluginContext
from src.core.nlp.intent_parser import IntentParser
from src.core.nlp.time_parser import TimeExpressionParser
from src.core.task_scheduler import get_scheduler, ScheduledTask

PLUGIN_NAME = "scheduler"
PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "定时任务管理插件"

class Plugin(BasePlugin):
    """定时任务管理插件"""
    
    name = PLUGIN_NAME
    version = PLUGIN_VERSION
    description = PLUGIN_DESCRIPTION
    
    def __init__(self):
        super().__init__()
        self.intent_parser = IntentParser()
        self.time_parser = TimeExpressionParser()
        self.scheduler = None
    
    async def on_load(self, context: PluginContext) -> None:
        await super().on_load(context)
        self.scheduler = get_scheduler()
    
    async def on_init(self) -> None:
        # 注册命令
        self.context.register_command("schedule", self.handle_schedule_command)
        
        # 注册工具
        self.context.register_tool("create_schedule", self.create_schedule)
        self.context.register_tool("query_schedule", self.query_schedule)
        self.context.register_tool("modify_schedule", self.modify_schedule)
        self.context.register_tool("delete_schedule", self.delete_schedule)
        
        # 订阅消息事件（用于自然语言处理）
        self.context.event_bus.subscribe("user.message", self.handle_natural_language)
    
    async def handle_natural_language(self, event: dict) -> None:
        """处理自然语言输入"""
        message = event.get('content', '')
        
        # 解析意图
        result = self.intent_parser.parse(message)
        
        if result['intent'] == IntentType.UNKNOWN:
            return  # 不是定时任务相关意图
        
        # 根据意图执行相应操作
        if result['intent'] == IntentType.CREATE_SCHEDULE:
            await self._handle_create_schedule(result['entities'])
        elif result['intent'] == IntentType.QUERY_SCHEDULE:
            await self._handle_query_schedule()
        # ... 其他意图
    
    async def _handle_create_schedule(self, entities: dict) -> None:
        """处理创建定时任务"""
        time_info = entities.get('time_expression')
        task_desc = entities.get('task_description')
        
        if not time_info:
            await self._send_response("❌ 未识别到时间表达式，请再说清楚一点")
            return
        
        # 生成任务名称
        task_name = task_desc or "定时任务"
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 创建任务
        task = ScheduledTask(
            task_id=task_id,
            name=task_name,
            handler=self._execute_task,
            cron_expression=time_info['cron']
        )
        
        self.scheduler.register_scheduled_task(task)
        
        # 发送确认消息
        response = f"""
✅ 任务创建成功！

📋 任务信息
━━━━━━━━━━━━━━━━━━━━━━━
任务 ID: {task_id}
任务名称：{task_name}
执行时间：{time_info['human_readable']}
Cron 表达式：{time_info['cron']}
下次执行：{task.next_run}
━━━━━━━━━━━━━━━━━━━━━━━
"""
        await self._send_response(response)
```

### 4.3 数据库设计

```python
# src/storage/schedule_db.py

import sqlite3
from datetime import datetime
from typing import List, Optional, Dict, Any

class ScheduleDatabase:
    """定时任务数据库"""
    
    def __init__(self, db_path: str = "data/schedules.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                task_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                human_readable TEXT,
                description TEXT,
                agent_id TEXT,
                created_at TEXT,
                last_run TEXT,
                next_run TEXT,
                status TEXT DEFAULT 'active',
                run_count INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedule_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                run_time TEXT,
                status TEXT,
                result TEXT,
                FOREIGN KEY (task_id) REFERENCES schedules(task_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_schedule(self, task: Dict[str, Any]) -> None:
        """添加定时任务"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO schedules (
                task_id, name, cron_expression, human_readable,
                description, agent_id, created_at, next_run, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task['task_id'],
            task['name'],
            task['cron_expression'],
            task['human_readable'],
            task.get('description', ''),
            task.get('agent_id', 'default'),
            datetime.now().isoformat(),
            task.get('next_run'),
            'active'
        ))
        
        conn.commit()
        conn.close()
    
    def get_all_schedules(self, agent_id: str = None) -> List[Dict]:
        """获取所有定时任务"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if agent_id:
            cursor.execute('SELECT * FROM schedules WHERE agent_id = ?', (agent_id,))
        else:
            cursor.execute('SELECT * FROM schedules')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def update_schedule(self, task_id: str, updates: Dict[str, Any]) -> None:
        """更新定时任务"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        set_clause = ', '.join(f'{k} = ?' for k in updates.keys())
        values = list(updates.values()) + [task_id]
        
        cursor.execute(f'''
            UPDATE schedules SET {set_clause} WHERE task_id = ?
        ''', values)
        
        conn.commit()
        conn.close()
    
    def delete_schedule(self, task_id: str) -> None:
        """删除定时任务"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM schedules WHERE task_id = ?', (task_id,))
        cursor.execute('DELETE FROM schedule_logs WHERE task_id = ?', (task_id,))
        
        conn.commit()
        conn.close()
    
    def log_execution(self, task_id: str, status: str, result: str) -> None:
        """记录执行日志"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO schedule_logs (task_id, run_time, status, result)
            VALUES (?, ?, ?, ?)
        ''', (task_id, datetime.now().isoformat(), status, result))
        
        # 更新任务的最后执行时间和执行次数
        cursor.execute('''
            UPDATE schedules 
            SET last_run = ?, run_count = run_count + 1 
            WHERE task_id = ?
        ''', (datetime.now().isoformat(), task_id))
        
        conn.commit()
        conn.close()
```

---

## 5. 实施计划

### 5.1 阶段划分

| 阶段 | 任务 | 版本 | 工作量 |
|------|------|------|--------|
| 阶段 1 | NLP 解析器开发 | v4.2.0 | 2 天 |
| 阶段 2 | 任务管理插件 | v4.2.0 | 2 天 |
| 阶段 3 | 数据库持久化 | v4.2.0 | 1 天 |
| 阶段 4 | TUI 界面集成 | v4.2.0 | 2 天 |
| 阶段 5 | 测试和文档 | v4.2.0 | 1 天 |

### 5.2 每日任务清单

#### Day 1: NLP 解析器

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 时间表达式解析器 | `nlp/time_parser.py` |
| 10:00-12:00 | 意图识别器 | `nlp/intent_parser.py` |
| 13:00-15:00 | 实体抽取器 | `nlp/entity_extractor.py` |
| 15:00-17:00 | 单元测试 | `tests/nlp/` |
| 17:00-18:00 | 集成测试 | 解析准确率>90% |

#### Day 2: 任务管理插件

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 插件骨架 | `plugins/scheduler_plugin/` |
| 10:00-12:00 | 自然语言处理 | `handle_natural_language()` |
| 13:00-15:00 | Slash 命令 | `handle_schedule_command()` |
| 15:00-17:00 | 工具函数 | create/modify/delete/query |
| 17:00-18:00 | 集成测试 | 插件可正常工作 |

#### Day 3: 数据库持久化

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 数据库设计 | `storage/schedule_db.py` |
| 10:00-12:00 | CRUD 操作 | add/get/update/delete |
| 13:00-15:00 | 执行日志 | log_execution() |
| 15:00-17:00 | 数据迁移 | 迁移现有 cron.json |
| 17:00-18:00 | 性能优化 | 查询优化 |

#### Day 4: TUI 界面集成

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 任务列表界面 | `tui/screens/schedules.py` |
| 10:00-12:00 | 新建任务界面 | 表单输入 |
| 13:00-15:00 | 任务详情界面 | 查看/编辑 |
| 15:00-17:00 | 批量操作 | 多选/批量删除 |
| 17:00-18:00 | 集成测试 | TUI 界面正常 |

#### Day 5: 测试和文档

| 时间 | 任务 | 交付物 |
|------|------|--------|
| 08:00-10:00 | 单元测试 | 覆盖率>80% |
| 10:00-12:00 | 集成测试 | 端到端测试 |
| 13:00-15:00 | 用户文档 | `docs/schedules/user_guide.md` |
| 15:00-17:00 | 开发文档 | `docs/schedules/dev_guide.md` |
| 17:00-18:00 | 发布准备 | v4.2.0 发布 |

### 5.3 成功指标

- [ ] ✅ 支持 10+ 种时间表达模式
- [ ] ✅ 意图识别准确率>90%
- [ ] ✅ 自然语言交互流畅
- [ ] ✅ Slash 命令完整
- [ ] ✅ TUI 界面友好
- [ ] ✅ 数据持久化可靠
- [ ] ✅ 测试覆盖率>80%

---

## 6. 附录

### 6.1 支持的时间表达模式

| 模式 | 示例 | Cron 表达式 |
|------|------|------------|
| 每分钟 | "每分钟" | `* * * * *` |
| 每 X 分钟 | "每 5 分钟" | `*/5 * * * *` |
| 每半小时 | "每半小时" | `*/30 * * * *` |
| 每小时 | "每小时" | `0 * * * *` |
| 每天 X 点 | "每天 9 点" | `0 9 * * *` |
| 每天 X 点半 | "每天 9 点半" | `30 9 * * *` |
| 每周 X X 点 | "周一 9 点" | `0 9 * * 1` |
| 每月 X 日 | "每月 1 号" | `0 0 1 * *` |
| 每年 X 月 X 日 | "每年元旦" | `0 0 1 1 *` |

### 6.2 文件变更清单

**新增文件**：
```
src/core/nlp/
├── __init__.py
├── time_parser.py       # 时间表达式解析
├── intent_parser.py     # 意图识别
└── entity_extractor.py  # 实体抽取

src/plugins/builtin/scheduler_plugin/
├── __init__.py          # 插件主文件
└── README.md

src/storage/
└── schedule_db.py       # 数据库管理

src/tui/screens/
└── schedules.py         # 定时任务管理界面

docs/schedules/
├── user_guide.md        # 用户指南
└── dev_guide.md         # 开发指南
```

---

**文档版本**：1.0  
**创建时间**：2026-03-30  
**审阅状态**：待审阅
