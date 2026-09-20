# 04 · `plugins/` — 插件目录

> 覆盖范围：**35 个子目录**（62 个文件：36 md、25 py、1 pyc）；其中 `builtin/`、`thirdparty/` 为空，实为 **33 个非空插件**
> 分层：L4 能力层（名义）
>
> 🔴 **本目录整体为僵尸代码：未被任何加载器扫描（证据见 [02.5](./02-src核心包/02.5-skill与plugin_framework.md) 第 2.3 节）**
> ✅ **本阶段结论：与 `skills/` 逐文件比对后确认，`plugins/` 无任何独立价值，可安全删除（0 风险）**
>
> 上一页：[03-skills技能.md](./03-skills技能.md)　｜　下一页：[05-scripts与services.md](./05-scripts与services.md)

---

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| `plugins/` 被加载吗？ | **否。** `PluginLoader.load_all()` 硬编码只加载 `DFEcrabAgentPlugin` 一个实例，从不扫描本目录 |
| 有没有 `skills/` 没有的功能？ | **没有。** 唯一「独有」的 `mcp-config` 也是坏的（依赖未安装的 `agentscope`） |
| `plugins/` 与 `skills/` 是什么关系？ | **`plugins/` 是旧版，`skills/` 是修复后的新版。** 迁移时复制过去改了 import，旧的没删 |
| 能删吗？ | **能。0 风险。** 详见第 4 节处置建议 |

---

## 1. 目录结构

| 子目录 | 文件 | 有 execute.py |
|---|---|---|
| `builtin/` | **（空）** | — |
| `thirdparty/` | **（空）** | — |
| `calculate` | execute.py、README.md、plugin.json | ✅ |
| `clawhub` | README.md、plugin.json | ❌ |
| `dfecrab-dev` | README.md、plugin.json、doc.md、review.md、test.md | ❌ |
| `download-install` | execute.py、README.md、plugin.json | ✅ |
| `echo` | execute.py、README.md、plugin.json | ✅ |
| `excel-read` | execute.py、README.md、plugin.json | ✅ |
| `file-manager` | execute.py、README.md、plugin.json | ✅ |
| `file_read` | execute.py、README.md、plugin.json | ✅ |
| `find-skills` | README.md、plugin.json | ❌ |
| `get-time` | execute.py、README.md、plugin.json | ✅ |
| `get-weekday` | execute.py、README.md、plugin.json | ✅ |
| `hello` | execute.py、README.md、plugin.json | ✅ |
| `kdocs` | README.md、plugin.json | ❌ |
| `list_dir` | execute.py、README.md、plugin.json | ✅ |
| `mcp-config` | execute.py、README.md、plugin.json | ✅ |
| `nano-pdf` | README.md、plugin.json | ❌ |
| `pdf-reader` | execute.py、README.md、plugin.json | ✅ |
| `pdf-to-kb` | execute.py、README.md、plugin.json | ✅ |
| `pdf-tools` | execute.py、README.md、plugin.json | ✅ |
| `planner` | execute.py、README.md、plugin.json | ✅ |
| `project_memory` | execute.py、README.md、plugin.json、**execute.cpython-312.pyc** | ✅ |
| `self-improving-agent` | execute.py、README.md、plugin.json | ✅ |
| `skill-creator-dfecrab` | execute.py、README.md、plugin.json | ✅ |
| `skill-validator-dfecrab` | execute.py、README.md、plugin.json | ✅ |
| `summarize` | README.md、plugin.json | ❌ |
| `url-shortener` | execute.py、README.md、plugin.json | ✅ |
| `video-frames` | README.md、plugin.json | ❌ |
| `weather` | execute.py、README.md、plugin.json | ✅ |
| `weather-forecast` | execute.py、README.md、plugin.json | ✅ |
| `web-fetch` | execute.py、README.md、plugin.json | ✅ |
| `web-search` | execute.py、README.md、plugin.json | ✅ |
| `word_read` | execute.py、README.md、plugin.json | ✅ |
| `xurl` | README.md、plugin.json | ❌ |

**统计：** 25 个有 `execute.py`，10 个没有（其中 2 个是空目录）

> 注意：`plugins/` 用 `plugin.json` 描述元信息，而 `skills/` 用 `_meta.json` + `SKILL_METADATA`。
> **但 `src/skill/loader.py` 只读 `_meta.json`，不认 `plugin.json`** —— 这是 `plugins/` 被废弃的又一佐证。

---

## 2. 与 `skills/` 的逐文件比对

对 25 个含 `execute.py` 的插件做 MD5 比对，结果分为 7 类：

### A. MD5 完全相同（12 个，48%）

`calculate`、`echo`、`get-time`、`get-weekday`、`hello`、`pdf-reader`、`pdf-to-kb`、`planner`、`self-improving-agent`、`skill-creator-dfecrab`、`skill-validator-dfecrab`、`weather-forecast`

→ **纯复制，零差异。**

### 🔴 B. 仅 import 行不同（5 个）—— 这是决定性证据

| 插件 | plugins 版（旧·坏） | skills 版（新·好） |
|---|---|---|
| `download-install` | `from agentscope.service import ServiceResponse, ServiceExecStatus` | `from src.agentscope_compat import ServiceResponse, ServiceExecStatus` |
| `excel-read` | 同上 | 同上（缩进不同） |
| `list_dir` | 同上 | 同上 |
| `weather` | 同上 | 同上 |
| `word_read` | 同上 | 同上 |

**这 5 个文件都是「差 3 字节、行数完全相同」。原因就在这唯一一行：**

```
from agentscope.service import ...      （19 字符）
from src.agentscope_compat import ...   （22 字符）  ← +3
```

| 事实 | 说明 |
|---|---|
| `agentscope` **不在 `requirements.txt` 中**，环境里也没装 | 所以 `plugins/` 这两个版本的 import **必然 ImportError** |
| `src/agentscope_compat.py` 是项目自带的兼容层（20 行） | 它就是专门为了替代 `agentscope` 而写的 |

> ### 🔑 这解释了整个 `plugins/` 的来历
>
> 迁移过程是这样的：
> 1. 早期用 AgentScope 框架 → 技能写在 `plugins/`，import `agentscope.service`
> 2. 后来**移除 AgentScope 依赖**（requirements.txt 里已无此包）→ 写了个 `src/agentscope_compat.py` 兜底
> 3. 把 `plugins/` 复制到 `skills/`，逐个把 import 改成 `src.agentscope_compat`
> 4. **改完后忘记删掉 `plugins/`**
>
> 所以：`plugins/` 是**迁移前的旧快照**，且**在新环境下跑不起来**。

### C. 仅命名不同，内容相同（2 个）

| plugins | skills | 大小对比 |
|---|---|---|
| `file-manager`（连字符） | `file_manager`（下划线） | 均为 2191 B / 71 行 |
| `url-shortener`（连字符） | `url_shortener`（下划线） | 均为 1118 B / 39 行 |

→ 同一个文件，只是目录命名风格不同（`skills/` 统一用下划线）。

### D. `skills/` 已演进、`plugins/` 停留在旧版（3 个）

| 插件 | plugins 版 | skills 版 | 差异 |
|---|---|---|---|
| `file_read` | 1566 B / 58 行 | **2056 B / 75 行** | skills 多 490 B / 17 行 |
| `web-fetch` | 5030 B / 140 行 | **6791 B / 190 行** | skills 多 1761 B / 50 行 |
| `web-search`（连字符） | 1490 B / 49 行 | `web_search` **2880 B / 88 行** | skills 多 1390 B / 39 行 |

→ 这三个在迁移后**又被继续开发过**，所以 `plugins/` 里的版本明显更简陋。**进一步证明 `plugins/` 是废弃快照。**

### 🔴 E. `plugins/` 多了一个坏的 import（1 个）

`pdf-tools`：plugins 版 1651 B / 63 行，skills 版 1605 B / 62 行。

```python
# plugins/pdf-tools/execute.py:6  ← skills 版已删掉这行
from agentscope.service import ServiceToolkit
```

| 说明 | `ServiceToolkit` 在文件中**根本没被使用**；且 `agentscope` 未安装 → 这行是纯粹的坏代码 |
|---|---|
| 结论 | skills 版把无用的坏 import 删了，plugins 版留着 |

### 🔴 F. `plugins/` 是完全不同的坏版本（1 个）

`project_memory`：plugins 版 7982 B / 228 行，skills 版 7757 B / 223 行。

**plugins 版独有的内容（全部是坏的）：**

```python
from agentscope.service import ServiceResponse, ServiceExecStatus   # ← 包未安装
    manager = MarkdownMemoryManager(agent_id)                        # ← 类不存在
    success = manager.add_memory_entry(memory_entry, memory_type="long_term")
    context = global_manager.load_all_context()
```

**skills 版对应的修复后写法：**

```python
from src.agentscope_compat import ServiceResponse, ServiceExecStatus  # ← 改成兼容层
from src.memory.long_term import MemoryManager                        # ← 改成真实类
def _map_memory_category(category: str) -> str: ...                   # ← 新增映射逻辑
    manager = MemoryManager(agent_id)
    manager.add_to_long_term(_map_memory_category(category), content, tags=[category])
```

| 结论 | `MarkdownMemoryManager` 在 `src/memory/` 中**完全不存在**。plugins 版的 `project_memory` **整体是坏的**，skills 版才是对的 |
|---|---|

### 🔴 G. `plugins/` 唯一"独有"的插件，但也是坏的（1 个）

`mcp-config` —— **唯一在 `skills/` 中找不到对应物的插件。**

| 项 | 内容 |
|---|---|
| 职责 | 用 `mcporter` CLI 连接 MCP 服务器并调用工具 |
| 实现 | `subprocess.run(["mcporter"] + args, ...)`；`mcporter` 不存在时自动 `npm install -g mcporter` |
| 大小 | 约 4 KB |
| **致命问题** | 第 11 行 `from agentscope.service import ServiceResponse, ServiceExecStatus` —— **`agentscope` 未安装，`requirements.txt` 中也没有** |
| **次要问题** | 依赖外部 `mcporter` CLI 与 `npm`，且**启动时会自行全局安装 npm 包**（副作用较大） |
| 结论 | **即使把它迁到 `skills/`，也必须先修 import 才能用。目前是死的** |

---

## 3. 无 `execute.py` 的 10 个插件

| 插件 | 内容 | 说明 |
|---|---|---|
| `builtin/` | **空目录** | 本应是内置插件位置，但加载机制已移除 |
| `thirdparty/` | **空目录** | 本应是第三方插件位置，但 `examples/hello_plugin/README.md` 仍在教人往这里放 |
| `clawhub` | README.md、plugin.json | 与 `skills/clawhub` 对应 |
| `dfecrab-dev` | README.md、plugin.json、doc.md、review.md、test.md | **开发辅助插件，纯文档，无代码** |
| `find-skills` | README.md、plugin.json | 对应 `skills/find-skill`（注意单复数差异） |
| `kdocs` | README.md、plugin.json | 对应 `skills/kdocs` |
| `nano-pdf` | README.md、plugin.json | 对应 `skills/nano-pdf` |
| `summarize` | README.md、plugin.json | 对应 `skills/summarize` |
| `video-frames` | README.md、plugin.json | 对应 `skills/video-frames` |
| `xurl` | README.md、plugin.json | 对应 `skills/xurl` |

> 这些连 `execute.py` 都没有，**在 plugins 体系下也是死的**（既不能被调用，也不被扫描）。

---

## 4. 处置建议

### 4.1 可以安全删除（0 风险）

| 依据 | 说明 |
|---|---|
| ① 无加载器扫描 | `PluginLoader.load_all()` 硬编码，从不读本目录 |
| ② 无代码引用 | 全仓库 grep `plugins` 路径的引用，只在 `src/__init__.py`（`get_plugins_path()` 已无调用方）、`grpc_server.py`、`legacy.py`、`check_system_health.py`、`tests/` 中出现，且都不是加载逻辑 |
| ③ 内容全是旧版或损坏版 | 见第 2 节的 7 类比对结论 |
| ④ 唯一独有插件是坏的 | `mcp-config` 依赖未安装的 `agentscope` |
| ⑤ git 可追溯 | 删了也能从版本历史找回 |

### 4.2 删除前建议做的 2 件事

| 步骤 | 动作 | 理由 |
|---|---|---|
| 1 | **单独保留 `mcp-config`** 或先把它的 import 改成 `src.agentscope_compat` 后迁到 `skills/` | 它是唯一有独立功能的插件（通过 `mcporter` 操作 MCP），虽然现在坏了，但可能是当初想做而没做完的功能 |
| 2 | **修正 `examples/hello_plugin/README.md`** | 它指导用户把插件放到 `plugins/thirdparty/`，而该目录为空且无加载机制。要么改文档，要么重建插件目录加载机制 |

### 4.3 建议的清理命令（仅供参考，未执行）

```bash
# 先归档，观察一段时间再彻底删
git mv plugins docs/_archive/plugins_20260829

# 或直接删（保留 mcp-config）
git rm -r plugins/ && git checkout HEAD -- plugins/mcp-config
```

### 4.4 连带要清理的

| 项 | 位置 | 说明 |
|---|---|---|
| `get_plugins_path()` | `src/__init__.py` | 已无调用方，可一并删除 |
| `plugins/project_memory/execute.cpython-312.pyc` | — | 编译缓存，随目录一起删 |
| `src/plugins/` | — | ⚠️ **不要删！** 那是 `src/plugin_framework/` 的向后兼容壳，正在使用中 |

---

## 5. 本阶段发现汇总

| # | 级别 | 发现 | 位置 |
|---|---|---|---|
| 105 | 🔴 P0 | **`plugins/` 全部 25 个 `execute.py` 中，至少 8 个引用了未安装的 `agentscope` 包** —— 即便加载了也会 ImportError | `download-install`、`excel-read`、`list_dir`、`weather`、`word_read`、`pdf-tools`、`project_memory`、`mcp-config` |
| 106 | 🔴 P0 | **5 个文件与 `skills/` 的差异仅为一行 import**（`agentscope.service` → `src.agentscope_compat`），定量证明 `plugins/` 是迁移前旧快照 | 见第 2 节 B 类 |
| 107 | 🔴 P0 | **`plugins/project_memory` 引用了不存在的 `MarkdownMemoryManager`**，是整体坏掉的版本 | `plugins/project_memory/execute.py` |
| 108 | 🟠 P1 | **`mcp-config` 是唯一独有插件，但已损坏**，且会自行 `npm install -g mcporter`（副作用大） | `plugins/mcp-config/execute.py:11` |
| 109 | 🟠 P1 | **`builtin/` 与 `thirdparty/` 均为空目录**，但示例文档仍指导往 `thirdparty/` 放插件 | — |
| 110 | 🟡 P2 | 命名风格不一致：`plugins/` 混用连字符（`file-manager`）与下划线（`file_read`），`skills/` 已统一 | — |
| 111 | 🟡 P2 | 元信息格式不一致：`plugins/` 用 `plugin.json`，`skills/` 用 `_meta.json` + `SKILL_METADATA`，而加载器只读后者 | — |
| 112 | 🟡 P2 | `plugins/project_memory/` 内含 `execute.cpython-312.pyc` 编译缓存，误提交 | — |
| 113 | 🟡 P2 | `plugins/find-skills`（复数）对应 `skills/find-skill`（单数），命名不一致 | — |

---

## 6. `plugins/` 与 `skills/` 对照总表

| # | plugins 目录 | skills 对应 | 比对结果 | 处置 |
|---|---|---|---|---|
| 1 | `calculate` | `calculate` | 相同 | 删 |
| 2 | `echo` | `echo` | 相同 | 删 |
| 3 | `get-time` | `get-time` | 相同 | 删 |
| 4 | `get-weekday` | `get-weekday` | 相同 | 删 |
| 5 | `hello` | `hello` | 相同 | 删 |
| 6 | `pdf-reader` | `pdf-reader` | 相同 | 删 |
| 7 | `pdf-to-kb` | `pdf-to-kb` | 相同 | 删 |
| 8 | `planner` | `planner` | 相同（**两者都坏**） | 删 |
| 9 | `self-improving-agent` | `self-improving-agent` | 相同（**两者都坏**） | 删 |
| 10 | `skill-creator-dfecrab` | `skill-creator-dfecrab` | 相同 | 删 |
| 11 | `skill-validator-dfecrab` | `skill-validator-dfecrab` | 相同 | 删 |
| 12 | `weather-forecast` | `weather-forecast` | 相同 | 删 |
| 13 | `download-install` | `download-install` | 差 1 行 import | 删 |
| 14 | `excel-read` | `excel-read` | 差 1 行 import | 删 |
| 15 | `list_dir` | `list_dir` | 差 1 行 import | 删 |
| 16 | `weather` | `weather` | 差 1 行 import | 删 |
| 17 | `word_read` | `word_read` | 差 1 行 import | 删 |
| 18 | `file-manager` | `file_manager` | 内容相同，命名不同 | 删 |
| 19 | `url-shortener` | `url_shortener` | 内容相同，命名不同 | 删 |
| 20 | `file_read` | `file_read` | skills 已演进 | 删 |
| 21 | `web-fetch` | `web-fetch` | skills 已演进 | 删 |
| 22 | `web-search` | `web_search` | skills 已演进，命名不同 | 删 |
| 23 | `pdf-tools` | `pdf-tools` | plugins 多了坏 import | 删 |
| 24 | `project_memory` | `project_memory` | plugins 是坏版本 | 删 |
| 25 | **`mcp-config`** | **无** | **唯一独有，但已损坏** | **⚠️ 评估后决定** |
| 26–33 | `clawhub`/`dfecrab-dev`/`find-skills`/`kdocs`/`nano-pdf`/`summarize`/`video-frames`/`xurl` | 同名存在 | 无 execute.py | 删 |
| 34–35 | `builtin`/`thirdparty` | — | 空目录 | 删 |

---

<div align="center">

**04 · plugins 插件 完**　（35 / 35 个目录，其中 33 个非空）

上一页：[03-skills技能.md](./03-skills技能.md)　｜　下一页：[05-scripts与services.md](./05-scripts与services.md)

</div>