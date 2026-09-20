# 06 · `tests/` 与 `examples/`

> 覆盖范围：**`tests/` 26 个 .py（约 4900 行，70 个测试函数）+ `examples/` 3 个文件**
> 分层：质量层 / 示例
>
> 上一页：[05-scripts与services.md](./05-scripts与services.md)　｜　下一页：[07-docs文档地图.md](./07-docs文档地图.md)

---

## 1. `tests/` 总览

| 项 | 内容 |
|---|---|
| **定位** | 测试集合 |
| **规模** | 26 个 .py：根目录 14 个、`core/` 2 个、`memory/` 2 个、`plugins/` 8 个 |
| **测试函数** | **70 个**（`test_` 前缀） |
| **运行方式** | ⚠️ **无 pytest 配置**（无 `pytest.ini` / `pyproject.toml` / `conftest.py`），多数是 `python xxx.py` 直接执行的**脚本式测试** |
| **CI 集成** | `dfecrab test` **只跑** `tests/test_grpc_architecture.py` 一个文件 |

**⚠️ 这意味着其余 25 个测试文件（约 4600 行）不在任何自动化流程中**——既不进 CI，也不被 `dfecrab test` 覆盖，全靠手动执行。

---

## 2. 按目录分述

### 2.1 `tests/` 根目录（14 个 .py）

| 文件 | 行数 | 测试数 | 测试函数 | 说明 |
|---|---|---|---|---|
| `test_full_integration.py` | 604 | 7 | `test_1_permissions`、`test_2_slash_commands`、`test_3_unified_tools`、`test_4_session_persistence`、`test_5_context_engine`、`test_6_workspace_config`、`test_7_enhanced_agent_loop` | **最大的测试文件**，7 步全集成 |
| `test_permissions.py` | 306 | 7 | 7 个权限测试 | 权限系统 |
| `test_grpc_architecture.py` | 334 | 6 | `test_health_check`、`test_simple_task`、`test_complex_task`、`test_audit_log`、`test_random_ports` | ⭐ **`dfecrab test` 唯一执行的测试** |
| `test_multi_agent_collaboration.py` | 249 | 6 | `test_registry`、`test_cli_adapter`、`test_communication_bus`、`test_task_planner`、`test_chain_collaboration`、`test_parallel_collaboration` | ⚠️ 见下 |
| `test_all_changes.py` | 268 | 1 | 1 个 | v4 变更验证 |
| `test_integration.py` | 127 | 7 | `test_api`、`test_models`、`test_memory`、`test_events`、`test_fallback`、`test_chat` | 基础集成 |
| `test_gateway.py` | 222 | 3 | `test_gateway`、`test_agents`、`test_scheduler` | 网关（async） |
| `test_task_manager.py` | 287 | 3 | `test_models`、`test_agent_group`、`test_task_manager` | 任务管理器 |
| `test_task_integration.py` | 307 | 2 | `test_full_task_lifecycle`、`test_concurrent_tasks` | 任务全生命周期 + 并发 |
| `test_task_api.py` | 238 | 5 | `test_api_create_task`、`test_api_list_tasks`、`test_api_get_task`、`test_api_get_progress`、`test_api_convert_task` | 任务 API |
| `test_multi_agent_real.py` | 187 | 2 | `test_qwen_design_codebuddy_implement`、`test_api_integration` | 真实多智能体 |
| `test_pdf_service.py` | 207 | 2 | `test_pdf_service`、`test_pdf_reader_skill` | PDF 服务 |
| `v298_test.py` | 136 | 2 | 2 个 | **v2.98 遗留测试**，命名不规范 |
| `__init__.py` | 2 | 0 | — | 包声明 |

#### 🔴 `test_multi_agent_collaboration.py` — 跑不起来的测试

```python
tests/test_multi_agent_collaboration.py:120
    planner = TaskPlanner(registry)
```

| 问题 | `src/agent/planner.py` 的 `__init__(self)` **不接受任何参数** |
|---|---|
| 后果 | `TypeError: __init__() takes 1 positional argument but 2 were given` |
| 状态 | 🔴 **该测试必定失败** |

> 这与 [02.1](./02-src核心包/02.1-agent与LLM.md) 发现的 `TaskPlanner.create_plan()` 不存在是同一处设计漂移的两种表现——
> 说明 `TaskPlanner` 的构造方式曾改过，但 `skills/planner`、`plugins/planner`、本测试**三处调用方都没跟着改**。

---

### 2.2 `tests/core/`（2 个 .py）

| 文件 | 行数 | 测试数 | 说明 |
|---|---|---|---|
| `test_kernel.py` | 380 | 3 | 内核测试 |
| `__init__.py` | **0** | 0 | ⚠️ **空文件** |

### 2.3 `tests/memory/`（2 个 .py）

| 文件 | 行数 | 测试数 | 测试函数 | 说明 |
|---|---|---|---|---|
| `test_unified_memory.py` | 169 | 5 | `test_initialization`、`test_module_access`、`test_search_functionality`、`test_stats`、`test_compatibility_bridges` | `UnifiedMemoryManager` 测试 |
| `performance_test.py` | 191 | 0 | — | 记忆性能压测（脚本式，无 `test_` 函数） |

| 备注 | ⚠️ `tests/memory/` **没有 `__init__.py`**（靠命名空间包工作），而 `tests/core/` 与 `tests/plugins/` 都有 |

---

### 2.4 `tests/plugins/`（8 个 .py）

> ℹ️ **重要澄清**：这个目录测试的是 **`src/plugin_framework/` 的插件加载器**，
> 与顶层 `plugins/` 目录**毫无关系**（[02.5](./02-src核心包/02.5-skill与plugin_framework.md) 已说明顶层 `plugins/` 从未被加载）。

| 文件 | 行数 | 测试数 | 说明 |
|---|---|---|---|
| `test_agent_plugin.py` | 288 | 1 | `DFEcrabAgentPlugin` 测试 |
| `test_plugin_integration.py` | 257 | 1 | 插件集成测试 |
| `test_loader.py` | 184 | 2 | `PluginLoader` 测试 |
| `test_loader_topological.py` | 178 | 2 | 插件加载的**拓扑排序**测试 |
| `test_memory_plugin.py` | 206 | 1 | 记忆插件 |
| `test_skill_plugin.py` | 156 | 1 | 技能插件 |
| `test_mcp_plugin.py` | 127 | 1 | MCP 插件 |
| `__init__.py` | 1 | 0 | 包声明 |

---

## 3. `examples/`

| 项 | 内容 |
|---|---|
| **定位** | 插件开发示例 |
| **规模** | 3 个文件：`__init__.py`（10.5 KB）、`config.json`、`README.md`（5.72 KB） |
| **唯一示例** | `hello_plugin/` |

### 3.1 `examples/hello_plugin/__init__.py`

| 项 | 内容 |
|---|---|
| 类型 | 示例 |
| 规模 | 10.5 KB |
| 职责 | 演示插件全生命周期 |
| 演示内容 | `on_load` / `on_start` / `on_stop` 生命周期钩子、工具注册、事件订阅与发布、配置管理、后台任务、运行统计 |

### 3.2 🔴 `examples/hello_plugin/README.md` — 文档已过时（三处）

| # | 问题 | 现状 |
|---|---|---|
| ① | 指导把插件复制到 `~/.dfecrab/plugins/thirdparty/` | **该目录不存在**（`plugins/thirdparty/` 为空目录），且**无加载器扫描**任何 plugins 目录 |
| ② | 示例 API 端口写 **8000** | 实际 Gateway 端口是 **6789** |
| ③ | 引用 `src.plugins.registry` | 该模块现已是**向后兼容壳**（re-export `src/plugin_framework`），不是推荐路径 |

| 影响 | 新开发者照着这份文档做插件，**一定做不出来**——放进 `thirdparty/` 后不会被加载，而文档没说真正该放哪 |
|---|---|
| 建议 | 要么改写文档（指向 `skills/` + `src.plugin_framework`），要么重建插件目录加载机制 |

---

## 4. 测试覆盖度分析

| 被测模块 | 对应测试 | 覆盖情况 |
|---|---|---|
| `src/agent/` | `test_all_changes.py`、`test_full_integration.py`（`test_7_enhanced_agent_loop`） | ⚠️ 薄弱 |
| `src/agent/planner.py` | `test_multi_agent_collaboration.py::test_task_planner` | 🔴 **该测试跑不起来** |
| `src/gateway/` | `test_gateway.py`、`test_grpc_architecture.py`、`test_integration.py` | ⚠️ 中等 |
| `src/memory/` | `test_unified_memory.py`、`performance_test.py` | ✅ 较好（含性能） |
| `src/task/` | `test_task_manager.py`、`test_task_api.py`、`test_task_integration.py` | ✅ 较好 |
| `src/permission.py` | `test_permissions.py`（7 个测试） | ✅ 最好 |
| `src/plugin_framework/` | `tests/plugins/` 8 个文件 | ✅ 较好 |
| `src/knowledge/` | `test_knowledge_full.py`（在 `scripts/`）、`test_pdf_service.py` | ⚠️ 分散在 scripts/ 里 |
| `src/skill/` | 无直接测试 | ❌ **无** |
| `src/session/` | 无直接测试 | ❌ **无** |
| `src/monitoring/` | `test_load_monitor_e2e.py`（在 `scripts/`） | ⚠️ 分散 |
| `src/reflection/` | 无测试 | ❌ **无** |
| `src/mcp/` | `test_mcp_plugin.py`（间接） | ⚠️ 间接 |

| 结论 | `src/skill/`（Agent 能力的核心来源）、`src/session/`（会话）、`src/reflection/`（反思）**三个模块零测试**；且测试文件分散在 `tests/` 与 `scripts/` 两处 |
|---|---|

---

## 5. 本阶段发现汇总

| # | 级别 | 发现 | 位置 |
|---|---|---|---|
| 125 | 🔴 P0 | **`test_multi_agent_collaboration.py:120` 用 `TaskPlanner(registry)`，但 `__init__` 不接受参数** → 该测试必定失败 | `tests/test_multi_agent_collaboration.py:120` |
| 126 | 🟠 P1 | **无 pytest 配置**，25 个测试文件（约 4600 行）不在任何自动化流程中；`dfecrab test` 只跑 1 个文件 | — |
| 127 | 🟠 P1 | `src/skill/` / `src/session/` / `src/reflection/` **三个核心模块零测试** | — |
| 128 | 🟠 P1 | **测试文件分散两处**：`tests/` 与 `scripts/`（后者含 `test_api_e2e.py`、`test_knowledge_full.py`、`test_load_monitor_e2e.py`、`concurrency_test.py`） | — |
| 129 | 🟠 P1 | **`examples/hello_plugin/README.md` 三处过时**：目标目录不存在、端口写成 8000（实际 6789）、引用兼容壳模块 | `examples/hello_plugin/README.md` |
| 130 | 🟡 P2 | `tests/core/__init__.py` 是 **0 字节空文件**；`tests/memory/` **缺 `__init__.py`** | — |
| 131 | 🟡 P2 | `tests/v298_test.py` 命名不规范（版本号混入文件名），且是 v2.98 遗留 | — |
| 132 | 🟡 P2 | `tests/test_sse_frontend.html`（非 .py）是前端联调用页面，混在测试目录里 | — |
| 133 | ℹ️ 澄清 | `tests/plugins/` 测的是 `src/plugin_framework/` 加载器，**与顶层 `plugins/` 目录无关** | — |

---

## 6. 阶段 5 小结

本阶段覆盖 **`scripts/`(15 py) + `services/`(3 py) + `tests/`(26 py) + `examples/`(1 py) = 45 个 .py，约 14000 行**，新发现 20 条（编号 114–133）。

**三个最重要的结论：**

1. **`services/` 的两个 3000 行 gRPC 服务是手写上帝类**（阶段 2 待办已解决），其中 `_execute_kunming_skills` 单方法 627 行，是本项目最需重构的函数。
2. **思考标签剥离逻辑在 4 处重复实现**——这是「同一个坑踩了四遍」的典型。
3. **测试体系实际是失效的**：无 CI、无 pytest 配置、70 个测试里只有 6 个被 `dfecrab test` 覆盖，且已知的 1 个测试跑不起来。

---

<div align="center">

**06 · tests 与 examples 完**　（27 / 27 个文件）

上一页：[05-scripts与services.md](./05-scripts与services.md)　｜　下一页：[07-docs文档地图.md](./07-docs文档地图.md)

</div>