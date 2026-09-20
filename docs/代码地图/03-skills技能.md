# 03 · `skills/` — 技能目录

> 覆盖范围：**47 个技能目录**（167 个文件：58 md、48 py、14 json、2 sh、1 zip）
> 分层：L4 能力层。**这是系统唯一真正被加载的能力来源。**
>
> 上一页：[02.7-knowledge知识库.md](./02-src核心包/02.7-knowledge知识库.md)　｜　下一页：[04-plugins插件.md](./04-plugins插件.md)

---

## 0. 加载机制回顾

技能能否生效，取决于三件事（依据 `src/skill/loader.py` 与 `src/skill/registry.py` 的实际实现）：

| 环节 | 要求 | 不满足的后果 |
|---|---|---|
| **① 被 `SkillLoader` 识别** | 目录位于 `skills/` 下；有 `SKILL.md`（区分大小写）或 `_meta.json` 或 `execute.py::SKILL_METADATA` 之一 | 无法注入 system prompt（LLM 不知道有这个技能） |
| **② 被 `ToolRegistry` 注册为工具** | 必须有 `execute.py`，且其中定义了 `execute()` 函数 | **无法被 LLM 当作工具调用** |
| **③ 执行时不报错** | `execute.py` 的 import 与逻辑正确 | 调用时抛异常 |

> ⚠️ **Linux 部署注意事项**：`SkillLoader` 用的是 `skill_dir / "SKILL.md"`，**大小写敏感**。
> 本目录中有 1 个技能的文件名是**小写 `skill.md`**（`dm_test`）、1 个是 `SKILL_ALERT_JUDGE.md`（`ft_agent`）——
> 在 Windows 上（大小写不敏感）能侥幸读到，在 Linux 上会**完全失效**。

---

## 1. 技能健康度总览

| 状态 | 数量 | 技能 |
|---|---|---|
| ✅ **有 `execute.py`（可当工具调用）** | **37** | 其中 2 个调用时会崩（`planner`、`self-improving-agent`） |
| ⚠️ **无 `execute.py`（仅提示、不可调用）** | **10** | 只能注入 prompt，不能注册成工具 |
| 🔴 **调用必崩** | 2 | `planner`、`self-improving-agent` |
| ⚪ **完全惰性** | 1 | `ft_agent`（文件名错误 + 无 execute.py） |

**10 个无 `execute.py` 的技能：**

| 技能 | 目录内实际内容 | 说明 |
|---|---|---|
| `clawhub` | SKILL.md（1.0 KB） | 提示词型 |
| `find-skill` | SKILL.md（4.53 KB）、_meta.json、origin.json、.DS_Store | 提示词型 |
| `ft_agent` | **SKILL_ALERT_JUDGE.md**（8.43 KB） | ⚪ 文件名非 `SKILL.md`，Linux 上读不到 |
| `guizang-ppt-skill` | SKILL.md（30.44 KB）+ 模板/JS/文档 16 个文件 | 提示词型（合法设计） |
| `kdocs` | SKILL.md（24.06 KB）+ 3 脚本 + 5 个 api 参考 | 提示词型（合法设计） |
| `nano-pdf` | SKILL.md（1.33 KB） | 提示词型 |
| `summarize` | SKILL.md（1.45 KB） | 提示词型 |
| `video-frames` | SKILL.md（1.58 KB） | 提示词型 |
| `xurl` | SKILL.md（2.99 KB）、_meta.json、origin.json | 提示词型 |
| `dm_test` | dm_test.py、src/config.py、src/query_dm.py、**skill.md（小写）** | 🟠 有 3 个 py，但**没有一个叫 execute.py** |

> 这些技能对 LLM **完全不可见**——因为 `SkillLoader._load_skill_manifest()` 要求目录里至少有 `SKILL.md`/`_meta.json`/`execute.py` 之一，而这些目录确实有 `SKILL.md`……所以它们**能被匹配到并注入 prompt**，但 `ToolRegistry._discover_tools()` 找不到 `execute.py`，**不会注册成工具**。
> **结果：LLM 会在 system prompt 里看到这个技能的说明，却找不到对应工具可调用。**

---

## 2. 逐技能清单

### 2.1 电网业务类（10 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `dm_query` | execute.py（8.5 KB） | `execute(sql_query: str = "")` | 执行达梦数据库查询 | ⚠️ 无 SKILL.md；🔴 明文密码 |
| `dm_meta` | execute.py、_meta.json | `execute()`（无参数） | 查达梦数据库的表结构元数据 | ⚠️ 无 SKILL.md、无 SKILL_METADATA；🔴 明文密码 |
| `dm_test` | dm_test.py、src/config.py、src/query_dm.py、**skill.md（小写）** | 无 `execute.py` | 达梦查询测试 | 🟠 文件名小写 + 无 execute.py |
| `kunming_api` | execute.py、SKILL.md、_meta.json | `execute(endpoint="", params=None, **kwargs)` | 调昆明配网数据 API（12 个接口） | ✅ |
| `kunming_classifier` | execute.py、SKILL.md、_meta.json | `execute(query="", category=14, startTime="", endTime="", personName="", date="", bureau="", mode="", area="", days=3, load_threshold=80, **kwargs)` | 查询意图分类（类别 5–14） | ✅ |
| `kunming_theory_qa` | execute.py、SKILL.md、_meta.json | `execute(query="", top_k=3, min_score=0.2, **kwargs)` | 理论题本地检索（第X题 + 语义近似） | ✅ |
| `load_analysis` | execute.py、_meta.json | `execute(api_url=None, **kwargs)` | 负载率分析：过载 >100%、高负载 80–100% | ⚠️ 无 SKILL.md |
| `power_transfer_strategy` | execute.py、_meta.json | `execute(analysis_result: str, **kwargs)` | 根据过载情况生成转电策略 | ⚠️ 无 SKILL.md |
| `ft_agent` | **SKILL_ALERT_JUDGE.md**（8.4 KB） | — | 电力告警信号研判（ReAct 文本式） | 🔴 **完全惰性** |
| `asr_corrector` | execute.py、SKILL.md | `execute(text="", use_model=True, **kwargs)` | ASR 拼音纠错，同音字纠正 + 模型兜底 | ✅ |

#### 🔴 `ft_agent` — 完全惰性的技能

| 项 | 内容 |
|---|---|
| 问题 | 目录里**只有 `SKILL_ALERT_JUDGE.md`**，而 `SkillLoader` 找的是 `SKILL.md` |
| 后果 | ① 在 Linux 上**完全读不到**（大小写敏感）；② 即使在 Windows 读到了，也**没有 `execute.py`**，无法注册成工具 |
| 说明 | 文件内容本身很完整（8.4 KB，描述了完整的 ReAct 告警研判流程 + System Prompt），是一份**写好了但没接上**的技能 |
| 建议 | 改名为 `SKILL.md`，并补充 `execute.py`；或明确废弃并删除 |

#### 🔴 数据库密码明文硬编码（3 处）

| 位置 | 代码 |
|---|---|
| `skills/dm_query/execute.py:36` | `password="ytdf000000"` |
| `skills/dm_meta/execute.py:16` | `password="ytdf000000"` |
| `skills/dm_test/dm_test.py:9` | `password='ytdf000000',    # 替换成真实密码` |
| `skills/dm_test/src/config.py:10` | `PASSWORD = os.getenv("DM_PASSWORD", "ytdf000000")` ⚠️ **看似从环境变量读，实际默认值就是明文密码** |

> 这是本项目**第二个 P0 安全问题**（第一个是 `src/config/config.py:72` 的智谱 API Key）。
> 建议：改用环境变量且**不设默认值**，或接入配置中心。

**内网 IP 硬编码（4 处）：**
`dm_query/dm_meta` → `172.20.42.247:5236`（达梦）
`kunming_api` → `http://192.168.113.15:8088`
`asr_corrector:200` → `http://172.20.41.86:8124/v1`
`get-http:59` → `http://172.20.42.72:8080/database`

---

### 2.2 知识库类（3 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `knowledge_qa` | execute.py（5.99 KB） | `execute(question="", top_k=5, **kwargs)` | 知识库问答 | ⚠️ 无 SKILL.md |
| `knowledge_search` | execute.py（1.33 KB） | `execute(query="", top_k=5, category=None, knowledge_base=None, **kwargs)` | 知识库检索 | ⚠️ 无 SKILL.md |
| `pdf-to-kb` | execute.py、SKILL.md、_meta.json | `execute(...)` | PDF 导入知识库 | ✅ |

> ✅ **正确分层范例**：`knowledge_qa` / `knowledge_search` 的实现在 `src/knowledge/skills/`，这里只是薄封装。
> 实测 `knowledge_search/execute.py` 只有 35 行，核心是 `from src.knowledge.skills.knowledge_search import KnowledgeSearchSkill, SKILL_METADATA` + 转发。

---

### 2.3 文档处理类（6 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `pdf-reader` | execute.py、SKILL.md、_meta.json | `execute(...)` | PDF 文本提取 | ✅ |
| `pdf-tools` | execute.py、rotate.py、SKILL.md | `execute(toolkit=None, **kwargs)` | PDF 工具（含旋转） | ✅ |
| `word_read` | execute.py、SKILL.md | `execute(file_path: str)` | 读取 .docx | ✅ |
| `excel-read` | execute.py、SKILL.md | `execute(file_path="", sheet_name="", max_rows=100)` | 读取 .xlsx/.xls | ✅ |
| `nano-pdf` | SKILL.md（1.33 KB） | — | PDF 处理（提示词型） | ⚠️ 仅提示 |
| `guizang-ppt-skill` | SKILL.md（30.4 KB）+ 模板/JS/文档 16 个文件 | — | PPT 生成（提示词型，含 HTML 模板） | ⚠️ 仅提示 |

> `guizang-ppt-skill` 是**提示词驱动型技能**：没有代码，靠 30 KB 的 SKILL.md（含 layout/themes/components 规范 + HTML 模板）指导 LLM 生成 PPT。这是一种合法的设计模式，不是缺陷。

---

### 2.4 文件与系统类（5 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `file_read` | execute.py、SKILL.md | `execute(file_path: str, encoding="utf-8")` | 读文件 | ✅ |
| `file_manager` | execute.py、SKILL.md | `execute(action: str, path: str, content: str = None)` | 文件增删改查 | ✅ |
| `list_dir` | execute.py、SKILL.md | `execute(dir_path: str, pattern="*", recursive=False)` | 列目录 | ✅ |
| `code_executor` | execute.py（6.2 KB）、SKILL.md、_meta.json | `execute(...)` | **沙箱执行 Python 代码** | ✅（安全性见下） |
| `download-install` | execute.py（5.0 KB）、SKILL.md | `execute(action: str, **kwargs)` | 下载与安装 | ✅ |

#### ⚠️ `code_executor` — 沙箱强度评估

| 机制 | 实现 |
|---|---|
| 进程隔离 | `subprocess.Popen(["python3", tmp_path], start_new_session=True)` |
| CPU 限制 | `RLIMIT_CPU = (timeout, timeout+1)`，默认 5 秒 |
| 内存限制 | `RLIMIT_AS = 256MB` |
| 文件限制 | `RLIMIT_FSIZE = 1MB` |
| 模块黑名单 | `{"os","subprocess","sys","socket","importlib","__import__","pty"}` |
| 超时处理 | `os.killpg()` 杀整个进程组 |
| 输出限制 | `MAX_OUTPUT_LENGTH = 10000` |

| 评价 | 说明 |
|---|---|
| ✅ 做得好 | 子进程隔离 + rlimit + 进程组 kill + 非阻塞（`asyncio.to_thread` 不卡事件循环） |
| ⚠️ 局限 | 代码第 19 行**自己承认**：「简单静态检查，仅第一层 import 拦截，**不是完整沙箱防御**」 |
| 风险 | 黑名单可被绕过（如 `importlib` 的变形、`__builtins__` 操作、间接 import）；且以**当前用户权限**运行，未做用户隔离 |

#### 🔴 `calculate` — 使用 `eval()`

```python
def execute(expr: str):
    result = eval(expr)      # skills/calculate/execute.py:16
```

| 风险 | 说明 |
|---|---|
| **任意代码执行** | `eval()` 未做任何限制，`__import__('os').system('...')` 即可执行任意命令 |
| 缓解因素 | 输入来自 LLM 生成的参数，不是直接来自用户；且需先经过意图识别与工具匹配 |
| 建议 | 改用 `ast.literal_eval()` 或实现一个安全的表达式解析器（只允许数学运算符与数学函数） |

---

### 2.5 网络类（5 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `web_search` | execute.py、SKILL.md | `execute(query: str, max_results: int = 5)` | 网络搜索 | ✅ |
| `web-fetch` | execute.py（6.8 KB）、SKILL.md、_meta.json | `execute(...)` | 网页抓取 | ✅ |
| `get-http` | execute.py（17.8 KB，最大）、SKILL.md、**execute.pybak0514** | `execute(...)` | 重过载数据查询（`reload_data_query`） | 🟠 有备份文件 |
| `xurl` | SKILL.md、_meta.json、origin.json | — | 短链/URL 服务（提示词型） | ⚠️ 仅提示 |
| `url_shortener` | execute.py（1.1 KB）、SKILL.md | `execute(url: str, action="shorten")` | 短链生成 | ✅ |

> 🟠 `get-http/execute.pybak0514` 是手工备份文件（与 `execute.py` 内容重复），**应删除**。
> 注意 `get-http` 的 `SKILL_METADATA.name` 是 **`reload_data_query`**，与目录名 `get-http` **不一致**——这会让技能匹配时产生偏差。

---

### 2.6 元技能（4 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `skill-creator-dfecrab` | execute.py（5.2 KB）、SKILL.md | `execute(toolkit=None, **kwargs)` | 创建新技能 | 🟠 **3 个 `execute` 定义** |
| `skill-validator-dfecrab` | execute.py（6.8 KB）、SKILL.md | `execute(toolkit=None, **kwargs)` | 校验技能 | ✅ |
| `find-skill` | SKILL.md（4.5 KB）、_meta.json、origin.json、.DS_Store | — | 查找技能（提示词型） | ⚠️ 仅提示 |
| `self-improving-agent` | execute.py + `src/`(agent.py, hooks.py, memory.py) + test.py、README.md（共 7 py / 23.8 KB） | `execute(command="run", workspace=None, verbose=False)` | 自我改进 | 🔴 **已损坏** |

#### 🟠 `skill-creator-dfecrab` — 三个 `execute` 定义

```python
skills/skill-creator-dfecrab/execute.py
   103: def execute(        # ← 死代码：被后面的定义覆盖
   131: def execute(        # ← 死代码：被后面的定义覆盖
   182: def execute(toolkit=None, **kwargs) -> str:   # ← 真正生效的
```

| 问题 | 前两个 `execute` 定义（约 78 行）**永远不会被调用**，Python 后定义覆盖前定义 |
|---|---|
| 风险 | 维护者可能改了前面那个，发现不生效，浪费时间 |
| 建议 | 删除前两个定义，或重命名为 `_execute_v1` / `_execute_v2` 并保留一个入口 |

#### 🔴 `self-improving-agent` — 已损坏（4 处引用不存在）

| 引用位置 | 引用内容 | 实际情况 |
|---|---|---|
| `execute.py:22` | `from src.memory import LearningMemory` | ❌ `src/memory/` 中**不存在** `LearningMemory` |
| `src/agent.py:11` | `from src.memory import LearningMemory` | ❌ 同上 |
| `src/hooks.py:13` | `from src.memory import LearningMemory` | ❌ 同上 |
| `test.py:15` | `from src.memory import LearningMemory` | ❌ 同上 |

> 全仓库搜索确认：`src/memory/` 只有 `UnifiedMemoryManager`、`long_term.MemoryManager`、`legacy_manager.MemoryManager`（空类）、`compactor.MemoryCompactor`（空壳）、`GlobalMemoryManager` —— **没有任何 `LearningMemory`**。
> 结论：这个技能**一调用就 `ImportError`**。

---

### 2.7 时间与天气（4 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `get-time` | execute.py（216 B）、SKILL.md | `execute()` | 获取当前时间 | ✅ |
| `get-weekday` | execute.py、SKILL.md | `execute(date_str=None)` | 获取星期几 | ✅ |
| `weather` | execute.py、SKILL.md、_meta.json、origin.json | `execute(city="北京", format_type="compact")` | 当前天气（wttr.in） | ✅ |
| `weather-forecast` | execute.py、get_weather.py、SKILL.md、_meta.json、origin.json、api_response_format.md | `execute(city="大理", days=1)` | 天气预报 | ✅ |

> `weather` 内置 23 个中文城市名 → 英文的映射表（北京/上海/广州/昆明等），用 `wttr.in` 无需 API Key。

---

### 2.8 记忆与规划（3 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `memory_maintenance` | execute.py（4.4 KB） | `execute(action: str)` | 记忆维护（weekly/monthly/提取长期） | ⚠️ 无 SKILL.md；🟠 依赖 cwd |
| `project_memory` | execute.py（11.9 KB）、SKILL.md | `execute(...)` | 项目长期记忆（DAILY/WEEKLY/MONTHLY/LONG_TERM.md） | 🟠 依赖 cwd |
| `planner` | execute.py（9.6 KB）、SKILL.md | `execute(task: str, context: dict = None)` | 任务规划 | 🔴 **已损坏** |

#### 🔴 `planner` — 调用不存在的方法

```python
skills/planner/execute.py:221
    plan = planner.create_plan(task, plan_data["steps"], complexity)
```

`src/agent/planner.py` 的 `TaskPlanner` **只有 `plan()`，没有 `create_plan()`**（详见 [02.1](./02-src核心包/02.1-agent与LLM.md) 第 2.4 节）。
→ 调用时 `AttributeError`。

#### 🟠 `memory_maintenance` / `project_memory` — 依赖当前工作目录

两者都 `from src.memory.global_manager import get_global_memory_manager`，而 `global_manager.py:22-23` 用的是**相对路径**：
```python
_DAILY_DIR  = Path("data/shared_memory/DAILY")
_LIBRARY_DIR = Path("data/shared_memory/knowledge")
```
→ **只有 cwd 为项目根时才正确**（详见 [02.3](./02-src核心包/02.3-memory与session.md) 第 1.7 节）。

---

### 2.9 基础与示例（6 个）

| 技能 | 组成 | `execute()` 签名 | 职责 | 状态 |
|---|---|---|---|---|
| `calculate` | execute.py（314 B）、SKILL.md | `execute(expr: str)` | 数学表达式计算 | 🔴 用了 `eval()` |
| `echo` | execute.py（210 B）、SKILL.md | `execute(message: str)` | 回显（测试用） | ✅ |
| `hello` | execute.py（200 B）、SKILL.md | `execute(name="朋友")` | 打招呼（示例） | ✅ |
| `summarize` | SKILL.md（1.45 KB） | — | 文本总结（提示词型） | ⚠️ 仅提示 |
| `clawhub` | SKILL.md（1.0 KB） | — | ClawHub 相关（提示词型） | ⚠️ 仅提示 |
| `kdocs` | SKILL.md（24 KB）+ 3 个 sh/ps1 脚本 + 5 个 api 参考文档 | — | 金山文档操作（提示词型） | ⚠️ 仅提示 |

### 2.10 媒体（1 个）

| 技能 | 组成 | 职责 | 状态 |
|---|---|---|---|
| `video-frames` | SKILL.md（1.58 KB） | 视频抽帧（提示词型） | ⚠️ 仅提示 |

> `asr_corrector` 已在 2.1 归入电网业务类（它是为电力调度 ASR 场景定制的）。

---

## 3. 统计与分布

### 3.1 按完整性分类

| 类别 | 数量 | 占比 |
|---|---|---|
| 有 `execute.py`（可调用） | **37** | 79% |
| 无 `execute.py`（仅提示） | **10** | 21% |
| 有 `SKILL.md` | 39 | 83% |
| 无 `SKILL.md` | 8 | 17% |
| 有 `_meta.json` | 14 | 30% |
| 有 `SKILL_METADATA` 常量 | 20 | 43% |

### 3.2 代码规模 Top 5

| 技能 | 字节 | 说明 |
|---|---|---|
| `self-improving-agent` | 23.8 KB（7 py） | 结构最复杂，但已损坏 |
| `get-http` | 17.8 KB | 含重过载查询全逻辑 |
| `project_memory` | 11.9 KB | 分层记忆管理 |
| `planner` | 9.6 KB | 已损坏 |
| `kunming_classifier` | 6.5 KB | 意图分类 |

### 3.3 文档规模 Top 3（提示词型技能）

| 技能 | SKILL.md | 说明 |
|---|---|---|
| `guizang-ppt-skill` | 30.44 KB | PPT 生成规范 + 模板 |
| `kdocs` | 24.06 KB | 金山文档 API 参考 |
| `self-improving-agent` | 8.43 KB | 自我改进流程 |

---

## 4. 本阶段发现汇总

| # | 级别 | 发现 | 位置 |
|---|---|---|---|
| 90 | 🔴 **安全** | **数据库密码明文硬编码**（3 处）+ `dm_test/src/config.py` 用环境变量但**默认值就是明文密码** | `dm_query:36`、`dm_meta:16`、`dm_test:9`、`dm_test/src/config.py:10` |
| 91 | 🔴 安全 | **`calculate` 使用 `eval()`**，可任意代码执行 | `skills/calculate/execute.py:16` |
| 92 | 🔴 P0 | **`self-improving-agent` 已损坏**：4 处引用不存在的 `LearningMemory` | `skills/self-improving-agent/` |
| 93 | 🔴 P0 | **`planner` 已损坏**：调用不存在的 `TaskPlanner.create_plan()` | `skills/planner/execute.py:221` |
| 94 | 🔴 P0 | **`ft_agent` 完全惰性**：文件名是 `SKILL_ALERT_JUDGE.md` 而非 `SKILL.md`，且无 `execute.py` | `skills/ft_agent/` |
| 95 | 🟠 P1 | **9 个技能无 `execute.py`**，只能注入 prompt 不能当工具调用，LLM 会看到说明却找不到工具 | 见第 1 节 |
| 96 | 🟠 P1 | **`dm_test/skill.md` 是小写字面量**，Linux 上大小写敏感会导致技能失效 | `skills/dm_test/skill.md` |
| 97 | 🟠 P1 | **`skill-creator-dfecrab` 有 3 个 `execute` 定义**，前 2 个是死代码（约 78 行） | `skills/skill-creator-dfecrab/execute.py:103,131,182` |
| 98 | 🟠 P1 | **`get-http` 的 `SKILL_METADATA.name` 是 `reload_data_query`**，与目录名 `get-http` 不一致 | `skills/get-http/execute.py:33` |
| 99 | 🟠 P1 | `memory_maintenance` / `project_memory` 依赖 `global_manager` 的**相对路径**，cwd 不对就失效 | — |
| 100 | 🟡 P2 | **`get-http/execute.pybak0514` 备份文件未清理** | `skills/get-http/` |
| 101 | 🟡 P2 | **4 处内网 IP 硬编码**（达梦、昆明 API、ASR 模型、重过载接口） | 见 2.1 节 |
| 102 | 🟡 P2 | **`find-skill` 目录含 `.DS_Store`**（macOS 系统文件，误提交） | `skills/find-skill/` |
| 103 | 🟡 P2 | `code_executor` 沙箱为**黑名单机制**，代码注释自承「不是完整沙箱防御」 | `skills/code_executor/execute.py:19` |
| 104 | 🟡 P2 | 8 个技能无 `SKILL.md`，完全依赖 `SKILL_METADATA` 或 `_meta.json` 提供元信息 | 见第 1 节 |

---

<div align="center">

**03 · skills 技能 完**　（47 / 47 个技能目录）

上一页：[02.7-knowledge知识库.md](./02-src核心包/02.7-knowledge知识库.md)　｜　下一页：[04-plugins插件.md](./04-plugins插件.md)

</div>