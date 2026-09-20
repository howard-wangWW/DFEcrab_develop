# 07 · 文档地图

> 覆盖范围：**`docs/` 101 篇 .md + `前端对接文档/` 10 篇 = 111 篇**
> 本文件为每篇文档标注「讲什么 / 给谁看 / 对应哪些代码」，并**重点标出已与实现不一致的文档**。
>
> 上一页：[06-tests与examples.md](./06-tests与examples.md)　｜　下一页：[08-配置与数据资产.md](./08-配置与数据资产.md)

---

## 0. 总览

| 目录 | 篇数 | 定位 |
|---|---|---|
| `设计说明书/` | 29 | 最完整的技术文档（架构 + 核心模块 + 交互 + 多智能体） |
| `用户手册/` | 17 | 面向使用者 |
| `05-历史文档/` | 13 | 已归档 |
| `集成分析/` | 9 | 阶段性整合报告 |
| `代码地图/` | **15** | **本套文档** |
| `测试报告/` | 5 | 测试计划/用例/结果 |
| `docs/` 根目录 | 5 | 启动、接口、迁移、变更、沙箱规划 |
| `design/` | 2 | 专题设计 |
| `plugins/` | 2 | 插件开发 |
| `开发计划/` | 2 | V4 计划与迁移报告 |
| `验收手册/` | 2 | 验收说明与用例 |
| `test/` | 0 | **空目录** |
| `{设计说明书，用户手册，测试报告，验收手册}/` | 0 | **空目录（全角逗号命名事故）** |
| `前端对接文档/`（独立目录） | 10 | 前后端联调权威依据 |

### 0.1 阅读路径建议

| 你是谁 | 建议顺序 |
|---|---|
| **新入职开发** | 根 `README.md` → [本套代码地图 CODEMAP.md](./CODEMAP.md) → `设计说明书/01-总体设计/PROJECT_OVERVIEW.md` → `用户手册/01-基础篇/QUICKSTART.md` |
| **接手某模块** | [CODEMAP.md](./CODEMAP.md) → 对应的 `02-src核心包/02.x-*.md` → `设计说明书/02-核心模块设计/<对应>.md` |
| **前端联调** | `前端对接文档/` 全部 10 篇 |
| **部署运维** | `docs/启动文档.md` → `docs/MIGRATION.md` → `docs/CHANGELOG.md` |
| **写技能** | [03-skills技能.md](./03-skills技能.md) → `用户手册/02-使用篇/SKILLS_USAGE.md` → `docs/plugins/dev_guide.md` |

> ⚠️ **注意**：`docs/` 下**没有文档中心索引**（无 `docs/README.md`）。新人进入 `docs/` 后没有导航入口，只能靠目录名猜。

---

## 1. `docs/` 根目录（5 篇）

| 文件 | 行数 | 讲什么 | 给谁看 | 对应代码 |
|---|---|---|---|---|
| `code_sandbox_artifact_plan.md` | 403 | 代码沙箱产物的规划文档 | 开发 | `skills/code_executor/` |
| `API接口文档.md` | 378 | HTTP 接口总说明 | 开发/前端 | `src/gateway/grpc_server.py` |
| `MIGRATION.md` | 187 | 从旧机器迁移到新机器的完整步骤（环境准备→建 venv→装依赖→配置→启动） | 运维 | — |
| `CHANGELOG.md` | 63 | 变更日志，**最新 2026-08-28**，每条都带「需部署文件」清单 | 全员 | — |
| `启动文档.md` | 114 | 部署与启动步骤（解压→改配置→补权限→启动） | 运维 | `config/gateway.yaml`、`config/dfecrab.json` |

> ✅ **`CHANGELOG.md` 写得最好**：每条变更都标注「需部署文件」，这是运维友好设计的典范。
> ⚠️ **阶段 6 更正**：阶段 1 记录的 `docs/README.md`、`docs/Session管理文档.md` **实际不存在**；`PERMISSION_GUIDE.md` 在 `用户手册/01-基础篇/` 下。详见 [01-顶层目录总览.md](./01-顶层目录总览.md)。

---

## 2. `docs/设计说明书/`（29 篇）

### 2.1 `01-总体设计/`（7 篇）

| 文件 | 讲什么 | 对应代码 |
|---|---|---|
| `PROJECT_OVERVIEW.md` | 项目总览 | 全局 |
| `ARCHITECTURE_V2.md` | V2 架构 | `src/gateway/` |
| `GRPC_ARCHITECTURE.md` | gRPC 架构设计 | `src/gateway/grpc/`、`services/` |
| `GATEWAY_ARCHITECTURE.md` | Gateway 架构 | `src/gateway/grpc_server.py` |
| `SINGLE_NODE_GATEWAY.md` | 单节点 Gateway 方案 | `src/gateway/` |
| `REFACTORING_PLAN.md` | 重构计划 | — |
| `REFACTORING_PLAN_V2.md` | 重构计划 V2 | — |

### 2.2 `02-核心模块设计/`（11 篇，含 README）

| 文件 | 行数 | 讲什么 | 对应代码 |
|---|---|---|---|
| `TOOL_SYSTEM.md` | **1739**（最大） | 工具系统 | `src/skill/registry.py`、`src/skill/loader.py` |
| `TASK_MANAGEMENT_SYSTEM.md` | 589 | 任务管理 | `src/task/task_manager.py` |
| `TASK_SCHEDULER_SYSTEM.md` | 555 | 任务调度 | `src/task/scheduler.py` |
| `MEMORY_SYSTEM.md` | — | 记忆系统 | `src/memory/` |
| `SESSION_TYPES.md` | 331 | 会话类型 | `src/session/` |
| `PERMISSION_SYSTEM.md` | — | 权限系统 | `src/gateway/permission.py` |
| `CONTEXT_ENGINE.md` | — | 上下文引擎 | — |
| `LLM_INTEGRATION.md` | — | LLM 集成 | `src/agent/llm/` |
| `PLANNER_SYSTEM.md` | — | 规划器 | `src/agent/planner.py` |
| `SELF_REFLECTION_SYSTEM.md` | — | 自反思 | `src/reflection/` |
| `README.md` | 360 | 本目录索引 | — |

### 2.3 `03-交互设计/`（6 篇）

| 文件 | 行数 | 讲什么 |
|---|---|---|
| `NATURAL_LANGUAGE_SCHEDULER.md` | 757 | 自然语言调度 |
| `TUI_REFACTORING_PLAN.md` | 722 | TUI 重构计划 |
| `MULTI_CLI_ARCHITECTURE.md` | 658 | 多 CLI 架构 |
| `SCHEDULER_ENHANCEMENTS.md` | 605 | 调度增强 |
| `TUI_STYLE_REFACTORING.md` | 402 | TUI 样式重构 |
| `CLI_MANAGEMENT_AND_COMMUNICATION.md` | 163 | CLI 管理与通信 |

### 2.4 `04-多智能体/`（4 篇）

| 文件 | 行数 | 讲什么 | 对应代码 |
|---|---|---|---|
| `MULTI_AGENT_INTERACTION.md` | 927 | 多智能体交互 | `src/agent/multi/` |
| `MVP_TEST_PLAN.md` | 555 | MVP 测试计划 | — |
| `SESSION_AGENT_GROUP_ARCHITECTURE.md` | 333 | 会话-Agent 组架构 | `src/task/agent_group.py`、`src/agent/multi/agent_group.py` |
| `GROUP_RUNTIME_MODELS.md` | 236 | 群组运行时模型 | `src/agent/multi/agent_group.py` |

---

## 3. `docs/用户手册/`（17 篇）

| 子目录 | 文件 | 讲什么 |
|---|---|---|
| （根） | `README.md` | 用户手册索引 |
| （根） | `新增自启动MCP服务指南.md` | MCP 服务自启动配置 → `config/mcporter.json`、`dfecrab start-mcp` |
| `01-基础篇/` | `QUICKSTART.md` | 快速开始 |
| | `SLASH_COMMANDS.md` | 斜杠命令（`/skill_id` → `SkillLoader` 的 +100 分匹配） |
| | `PERMISSION_GUIDE.md`（12 KB） | 权限使用 |
| | `PERMISSION_SETUP.md` | 权限配置 → `config/permissions.json` |
| `02-使用篇/` | `API_USAGE.md` | API 使用 |
| | `SKILLS_USAGE.md` | 技能使用 |
| | `TOOLS_USAGE.md` | 工具使用 |
| | `TASK_USAGE_GUIDE.md` | 任务使用 |
| | `TASK_API_V2.md` | 任务 API V2 → `handlers/task_v2_handler.py` |
| | `WEBSOCKET_PUSH.md` | WebSocket 推送 → `src/gateway/websocket/` |
| | `WORKSPACE_CONFIG.md` | 工作区配置 |
| | `DOCKER_DEPLOYMENT.md` | ⚠️ Docker 部署（**项目中未见 Dockerfile**，需核实） |
| `03-进阶篇/` | `V4_UPGRADE_GUIDE.md` | V4 升级指南 |
| `04-参考篇/` | `API_REFERENCE_V4.md` | V4 API 参考 |
| | `QUICK_REFERENCE.md` | 速查表 |

---

## 4. `docs/05-历史文档/`（13 篇）

**已归档，仅供参考，不保证与现状一致。**

| 文件 | 行数 | 原主题 |
|---|---|---|
| `FEATURE_DESIGN.md` | 710 | 特性设计 |
| `API.md` | 368 | 旧版 API |
| `WORD_README.md` | 202 | Word 技能 |
| `KDOCS_README.md` | 194 | 金山文档技能 |
| `HOW_TO_USE_WORD_READ.md` | 180 | Word 读取 |
| `SCHEME3_COMPLETE.md` | 180 | 方案三完成 |
| `KDOCS_IMPLEMENTATION.md` | 165 | KDocs 实现 |
| `SKILLS_COMPLETE.md` | 168 | 技能体系完成 |
| `SKILLS_DEBUG_STATUS.md` | 118 | 技能调试状态 |
| `WORD_IMPLEMENTATION.md` | 110 | Word 实现 |
| `CLEANUP_REPORT.md` | 102 | 清理报告 |
| `FILE_OPERATIONS_STATUS.md` | 96 | 文件操作状态 |
| `SKILLS_INTEGRATION_COMPLETE.md` | 96 | 技能集成完成 |

> 这些文档对应的技能现在都还在（`skills/word_read/`、`skills/kdocs/`），**但文档已被新的 `03-skills技能.md` 取代**。

---

## 5. `docs/集成分析/`（9 篇）

阶段性整合与优化报告，属**过程性文档**。

| 文件 | 行数 | 主题 |
|---|---|---|
| `INTEGRATION_ANALYSIS.md` | 453 | 集成分析 |
| `FINAL_COMPLETION_REPORT.md` | 364 | 最终完成报告 |
| `OPTIMIZATION_SUMMARY.md` | 351 | 优化总结 |
| `SYSTEM_OPTIMIZATION_PROGRESS.md` | 321 | 系统优化进度 |
| `PHASE1_COMPLETION.md` | 312 | 阶段一完成 |
| `DOCUMENTATION_FINAL_REPORT.md` | 242 | 文档最终报告 |
| `TASK_V2_IMPLEMENTATION_SUMMARY.md` | 216 | 任务 V2 实现总结 |
| `DOCUMENTATION_UPDATE_REPORT.md` | 158 | 文档更新报告 |
| `TASK_V2_DOCUMENTATION_REPORT.md` | 91 | 任务 V2 文档报告 |

---

## 6. `docs/测试报告/`（5 篇）与 `验收手册/`（2 篇）

| 文件 | 讲什么 |
|---|---|
| `测试报告/README.md` | 测试报告索引 |
| `测试报告/01-测试计划/INTEGRATION_TEST_PLAN.md` | 集成测试计划 |
| `测试报告/02-测试用例/README.md` | 用例索引 |
| `测试报告/02-测试用例/V4_INTEGRATION_TESTS.md` | V4 集成测试用例 |
| `测试报告/03-测试结果/test_results_20260403.md` | 2026-04-03 测试结果 |
| `测试报告/04-问题跟踪/` | **空目录** |
| `验收手册/README.md` | 验收索引（313 行） |
| `验收手册/02-验收用例/V4_FUNCTIONAL_TESTS.md` | V4 功能验收用例（659 行） |

> ⚠️ 实测结果只有 1 份（2026-04-03），而 [06-tests与examples.md](./06-tests与examples.md) 已确认**测试体系实际失效**（无 CI、无 pytest 配置、70 个测试中只有 6 个被 `dfecrab test` 覆盖）。这份测试报告的时效性存疑。

---

## 7. `docs/design/`（2）、`plugins/`（2）、`开发计划/`（2）

| 文件 | 行数 | 讲什么 |
|---|---|---|
| `design/multi_agent_collaboration.md` | 324 | 多智能体协作设计 → `src/agent/multi/` |
| `design/pdf_reader_design.md` | 36 | PDF 阅读器设计 → `skills/pdf-reader/` |
| `plugins/api.md` | 437 | 插件 API → `src/plugin_framework/` |
| `plugins/dev_guide.md` | 526 | 插件开发指南 |
| `开发计划/DFECRAB_V4_DEVELOPMENT_PLAN.md` | — | V4 开发计划 |
| `开发计划/migration_report.md` | — | 迁移报告 |

> ⚠️ `plugins/api.md` 与 `plugins/dev_guide.md` 描述的是 **`src/plugin_framework/`** 的插件体系。
> 但经 [04-plugins插件.md](./04-plugins插件.md) 核实，**顶层 `plugins/` 目录从未被加载**。
> 若这两篇文档指导用户「把插件放进 `plugins/` 目录」，则该指导是无效的——需与 `examples/hello_plugin/README.md` 一并核查修正。

---

## 8. `前端对接文档/`（10 篇）

| 项 | 内容 |
|---|---|
| **定位** | 前后端联调的**权威依据** |
| **规模** | 10 篇 |
| **统一约定** | 前缀 `/api`，鉴权走 `X-User-Id` 请求头 |

| 文件 | 大小 | 对应后端模块 |
|---|---|---|
| `前端对接文档_对话接口.md` | 27.78 KB | `handlers/agent_handler.py`、`events_handler.py`；WS 6790 / HTTP 6789 |
| `前端对接文档_知识库.md` | 22.95 KB | `src/knowledge/`、`knowledge_service.py` |
| `前端对接文档_MCP服务管理.md` | 15.55 KB | `handlers/mcp_handler.py`、`src/mcp/` |
| `前端对接文档_会话历史.md` | 12.47 KB | `handlers/session_handler.py`、`src/session/` |
| `前端对接文档_用户管理.md` | 10.11 KB | `src/gateway/user_service.py` |
| `前端对接文档_任务管理.md` | 9.76 KB | `handlers/task_v2_handler.py`、`src/task/` |
| `前端对接文档_Agent管理.md` | 9.61 KB | `handlers/agent_handler.py`、`src/agent/` |
| `前端对接文档_记忆管理.md` | 7.85 KB | `handlers/memory_handler.py`、`src/memory/` |
| `前端对接文档_技能管理.md` | 5.86 KB | `handlers/skill_handler.py`、`src/skill/` |
| `前端对接文档_模型管理.md` | 5.12 KB | `handlers/model_handler.py`、`src/services/model_manager.py` |

> ### ✅ 这一组文档是**最新的**
>
> 实测《对话接口》第 40 行写的是：
> > 持续接收服务端 `event` 系列推送事件，**`message_end` 为对话结束唯一有效标记**
>
> 这与 `src/core/event_types.py` 的 v4.0 协议**完全一致**。
> 且全部 10 篇文档中**未出现**过时的 `8000` 端口（都用 6789/6790/6788）。
>
> **结论：前端对接文档维护得比 `README.md` 好得多，可信度高。**

---

## 9. 🔴 文档与实现一致性核查

这是本阶段的核心价值。以下为**已实测确认**的不一致之处：

| # | 位置 | 文档写的 | 实际情况 |
|---|---|---|---|
| 1 | `README.md:168` | 事件流类型：`thinking` / `tool_call` / `tool_result` / `plan_created` / `plan_step` / **`final`** / `error` | v4.0 实际为 `think_start`/`think`/`think_end`/`tool_start`/`tool_progress`/`tool_call`/`tool_result`/`skill_match`/`plan_created`/`plan_step`/`confirmation`/`message_start`/**`message_end`**/`error`。**`thinking` 与 `final` 均已被取代** |
| 2 | `README.md:220,225,229` | 用 `final` 作为终止事件 | 终止事件是 **`message_end`** |
| 3 | `README.md:236,399` | `max_iterations` 默认 **10** | ✅ **README 是对的。** 经核实 `config/dfecrab.json` 的 `agent_defaults.max_iterations = 10`，且 `agents/*/config.json` 均未覆盖，实际生效值就是 10。代码内的 3/5 只是兜底值。**（阶段 7 更正了阶段 2 的误判）** |
| 4 | `README.md` | Python **3.10+** | `requirements.txt` 与线上实际为 **3.12.7** |
| 5 | `examples/hello_plugin/README.md` | 插件放 `plugins/thirdparty/`；API 端口 **8000**；引用 `src.plugins.registry` | 该目录不存在且无加载器；端口是 **6789**；`src.plugins` 已是兼容壳 |
| 6 | `docs/plugins/dev_guide.md`（待核实） | 疑指导往 `plugins/` 放插件 | `plugins/` 从未被加载 |
| 7 | `docs/用户手册/02-使用篇/DOCKER_DEPLOYMENT.md` | Docker 部署 | 项目中**未见 Dockerfile** |

**建议优先修正 #1–#5**，因为它们会直接误导新人或联调方。

---

## 10. 本阶段发现汇总

| # | 级别 | 发现 | 位置 |
|---|---|---|---|
| 134 | 🔴 P0 | **`README.md` 事件类型已过时**：仍写 `thinking`/`final`，实际是 `think` 三段式 + `message_end` | `README.md:168,220,225,229` |
| 135 | ✅ 更正 | **`README.md` 的 `max_iterations` 默认 10 是正确的**。阶段 2 曾误判为「实际是 3」，阶段 7 核实 `config/dfecrab.json` 后确认生效值为 10，已在 [02.1](./02-src核心包/02.1-agent与LLM.md) 更正 | — |
| 136 | 🟠 P1 | **`README.md` 声明 Python 3.10+，实际要求 3.12.7** | `README.md` |
| 137 | 🟠 P1 | **`docs/` 无文档中心索引**（无 `docs/README.md`），新人无导航入口 | — |
| 138 | 🟠 P1 | `DOCKER_DEPLOYMENT.md` 存在但**项目中未见 Dockerfile** | `docs/用户手册/02-使用篇/` |
| 139 | 🟡 P2 | 又发现 1 个空目录：`docs/测试报告/04-问题跟踪/` | — |
| 140 | 🟡 P2 | `docs/plugins/` 两篇文档可能指导无效的插件放置方式（待核实） | `docs/plugins/` |
| 141 | 🟡 P2 | `05-历史文档/`（13 篇）已被 `03-skills技能.md` 等新文档取代，但未标注废弃 | — |
| 142 | ✅ 确认 | **`前端对接文档/`（10 篇）是最新且准确的**——事件协议用 `message_end`、端口用 6789/6790，可信度高 | — |
| 143 | 🔧 更正 | 阶段 1 记录的 `docs/README.md`、`docs/Session管理文档.md` **不存在**；`PERMISSION_GUIDE.md` 实为 `用户手册/01-基础篇/` 下。已在 01 号文档更正 | — |

---

<div align="center">

**07 · 文档地图 完**　（111 篇文档）

上一页：[06-tests与examples.md](./06-tests与examples.md)　｜　下一页：[08-配置与数据资产.md](./08-配置与数据资产.md)

</div>