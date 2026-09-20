# 05 · `scripts/` 与 `services/`

> 覆盖范围：**`scripts/` 15 个 .py（3094 行）+ 2 个 .sh ＋ `services/` 3 个 .py（6017 行）+ 2 个 .sh**
> 分层：运维层（scripts）/ 服务层（services）
>
> 🔑 **阶段 2 遗留待办已解决**：`services/` 两个 gRPC 文件**不是生成代码**，而是手写的两个 3000 行「上帝类」。
>
> 上一页：[04-plugins插件.md](./04-plugins插件.md)　｜　下一页：[06-tests与examples.md](./06-tests与examples.md)

---

## 1. `services/` — gRPC 服务进程

| 项 | 内容 |
|---|---|
| **定位** | gRPC 架构下的**独立服务进程**，与 Gateway 通过网络通信 |
| **规模** | 3 个 .py，共 **6017 行** |
| **启动方式** | `dfecrab start` 拉起，或 Gateway `_auto_start_agents()` 自动管理 |
| **注册方式** | 起在随机端口，通过 Zookeeper 注册，Gateway 通过 ZK 发现 |
| **日志** | `logs/manager_agent.log`、`logs/worker_agents.log`（由 `src/utils/logging_setup.py` 配置） |

### 1.1 文件一览

| 文件 | 行数 | 类 | 方法数 | 说明 |
|---|---|---|---|---|
| `manager_agent/manager_agent_grpc.py` | **3003** | `ManagerAgentServiceImpl` | 58 | Manager Agent 服务 |
| `agent_service/agent_service_grpc.py` | **2938** | `AgentServiceImpl` | 40 | Worker Agent 服务 |
| `agent_service/validate_sql_fields.py` | 76 | — | — | SQL 字段校验工具 |
| `start_microservices.sh` / `stop_microservices.sh` | — | — | — | 批量启停 |

---

### 🔴 1.2 `manager_agent_grpc.py` — 3003 行的上帝服务

| 项 | 内容 |
|---|---|
| 类型 | 服务 · gRPC Servicer |
| 规模 | 3003 行 / 1 个主类 / 58 个方法 |
| 职责 | Manager Agent 的 gRPC 服务实现：接收请求 → 意图识别 → 分派 Worker → 汇总 |
| 核心符号 | `ManagerAgentServiceImpl`（继承 `dfecrab_pb2_grpc.ManagerServiceServicer`） |
| 依赖 | `src.gateway.grpc.dfecrab_pb2_grpc`（生成的存根）、`src.config.config_loader`（第 32、201 行）、`src.utils.logging_setup`（第 39 行） |

**方法按职责分组：**

| 分组 | 方法（行号） |
|---|---|
| **gRPC 端点** | `Chat`(110)、`ChatStream`(165)、`ManagerHealth`(200) |
| **消息处理主流程** | `process_message`(213, **160 行**)、`process_message_stream`(373, **209 行**) |
| **配置加载** | `_load_config`(582)、`_async_load_llm_config`(590)、`_init_llm_service`(605)、`_load_llm_config`(619)、`_load_all_alive_configs`(662) |
| **Agent 描述扫描** | `_scan_agent_descriptions`(686)、`_reload_agent_descriptions`(733)、`_build_agent_list_prompt`(738)、`_build_dynamic_system_prompt`(748) |
| **思考配置** | `_get_current_think_config`(777)、`_get_model_think_config`(822) |
| **LLM 调用** | `_call_llm_async`(847)、`_call_llm_async_stream`(876, **176 行**)、`_call_llm_async_stream_v2`(1052)、`_call_llm`(1071)、`_call_llm_with_fallback`(1083)、`_call_llm_with_config`(1127)、`_call_llm_async_with_config`(1143) |
| **消息清洗** | `_clean_user_message`(1178)、`_extract_user_content`(1201)、`_resolve_time_in_message`(1230)、`_handle_internal_command`(1265) |
| **意图识别** | `_identify_intent`(1342)、`_validate_intent_agents`(1385)、`_call_llm_for_intent`(1429)、`_parse_intent_json`(1607)、`_normalize_intent_aliases`(1718)、`_remap_agent_by_keywords`(1740)、`_extract_intent_fields`(1753)、`_call_llm_for_intent_stream_yield`(1859, **107 行**) |
| **思考标签处理** | `_strip_think_tags`(1524)、`_strip_cot`(1528)、`_extract_think_content`(1977)、`_remove_think_tags`(1999) |
| **其他** | `_auto_check_agent_updates`(1310)、`_async_gen_to_sync`(1803)、`_truncate_agent_list`(1966)、`_build_manager_think_text`(2024) |

| 备注 | ⚠️ **单类 3003 行，与 `GatewayV2GRPC`（5305 行）同级的上帝类**。职责混杂了：gRPC 端点、配置加载、LLM 调用、意图识别、提示词构建、文本清洗 |

---

### 🔴 1.3 `agent_service_grpc.py` — 2938 行，含 627 行单方法

| 项 | 内容 |
|---|---|
| 类型 | 服务 · gRPC Servicer |
| 规模 | 2938 行 / 1 个主类 / 40 个方法 |
| 职责 | Worker Agent 的 gRPC 服务实现：接收分派 → 执行技能 → 返回结果 |
| 核心符号 | `AgentServiceImpl`（继承 `dfecrab_pb2_grpc.AgentServiceServicer`）、`serve()`(2844)、`_worker_watchdog()`(2893)、`main()`(2927) |

**超长方法（本文件最突出的问题）：**

| 方法 | 起止行 | **行数** |
|---|---|---|
| 🔴 `_execute_kunming_skills` | 489 – 1116 | **627** |
| 🟠 `_execute_sql_generator_skills` | 1782 – 2002 | **220** |
| 🟠 `_execute_analyst_skills` | 2300 – 2490 | **190** |
| 🟠 `_code_assist_kunming_classifier` | 1400 – 1557 | **157** |
| 🟠 `_extract_params_via_llm` | 1645 – 1782 | **137** |
| 🟡 `_execute_reporter_skills` | 2535 – 2637 | 102 |
| 🟡 `_execute_single_skill` | 1306 – 1400 | 94 |
| 🟡 `_llm_refine_kunming_params` | 1557 – 1645 | 88 |
| 🟡 `_execute_generic_skills` | 1162 – 1239 | 77 |
| 🟡 `_execute_dm_skills` | 2002 – 2079 | 77 |

> ### 🔴 极端案例：`_execute_kunming_skills` 单方法 627 行
>
> 这一个方法占了全文件的 21%，覆盖了昆明业务的全部技能分发逻辑。
> 对比之下，同类方法 `_execute_generic_skills` 只有 77 行、`_execute_dm_skills` 只有 77 行——
> 说明**其余技能类型都用「分发 + 通用执行」的写法，只有昆明业务把全部逻辑内联堆在了一个方法里**。
>
> 这是本项目**最需要重构的单个函数**。

**其他方法：**

| 分组 | 方法 |
|---|---|
| gRPC 端点 | `Execute`(309)、`Health`(416) |
| 配置 | `_load_config`(111)、`_load_tools`(140)、`_async_load_llm_config`(148)、`_load_llm_config`(160) |
| LLM | `_call_llm_async`(200)、`_call_llm`(280)、`_trim_session_history`(269) |
| 技能执行 | `_execute_skills`(438)、`_execute_default_skills`(463)、`_execute_kunming_skills`(489)、`_execute_generic_skills`(1162)、`_execute_single_skill`(1306)、`_execute_sql_generator_skills`(1782)、`_execute_dm_skills`(2002)、`_execute_analyst_skills`(2300)、`_execute_reporter_skills`(2535)、`_execute_file_manager_skills`(2709) |
| 数据处理 | `_summarize_data_for_llm`(1239)、`_format_template_output`(2138)、`_generate_dm_summary`(2245)、`_execute_single_dm_query`(2079) |
| 兜底生成 | `_generate_data_fallback`(2490)、`_generate_fallback_flowchart`(2637)、`_generate_file_summary`(2744) |
| 其他 | `_clean_llm_reasoning`(1116)、`_extract_intent_tags`(2769)、`_learn_from_execution`(2806) |

| 备注 | ① `_learn_from_execution`(2806) 说明 Worker 具备「从执行中学习」的能力；② `_worker_watchdog`(2893) 是进程看门狗 |

---

### 🔴 1.4 思考标签剥离逻辑 —— 三处重复实现

| 实现位置 | 函数 |
|---|---|
| `src/agent/llm/think.py`（316 行，专用模块） | `remove_think_tags`、`extract_think_content`、`strip_cot`、`find_first_tag_position`、`check_split_tag`、`extract_thinking_and_content` |
| `src/gateway/grpc_server.py:82` | `_strip_think_tags` |
| `services/manager_agent/manager_agent_grpc.py:1524–2023` | `_strip_think_tags`(1524)、`_strip_cot`(1528)、`_extract_think_content`(1977)、`_remove_think_tags`(1999) |
| `services/agent_service/agent_service_grpc.py:1116` | `_clean_llm_reasoning` |

| 问题 | 说明 |
|---|---|
| **同一件事写了 4 遍** | `think.py` 是最完整的专用模块，但另外 3 处各写各的 |
| **维护风险** | 修改思考标签策略时，需要同步改 4 个地方，漏改就会出现「Gateway 剥离了、Manager 没剥离」的诡异现象 |
| 建议 | 统一收敛到 `src/agent/llm/think.py` |

---

### 1.5 `agent_service/validate_sql_fields.py`

| 项 | 内容 |
|---|---|
| 类型 | 工具类 · 校验 |
| 规模 | 76 行 |
| 职责 | SQL 字段校验（防止生成的 SQL 引用不存在的字段） |
| 备注 | 被 `agent_service_grpc.py` 的 `_execute_dm_skills` 链路使用 |

### 1.6 两个 Shell 脚本

| 文件 | 大小 | 说明 |
|---|---|---|
| `start_microservices.sh` | 1968 B | 批量启动微服务 |
| `stop_microservices.sh` | 864 B | 批量停止微服务 |

| 备注 | 这两个脚本与根 `dfecrab` 的 start/stop 功能重叠——`dfecrab` 已经内置了 ZK 清理、端口检测、健康检查，**脚本版本更简单但能力更弱**。需确认是否还在用 |

---

## 2. `scripts/` — 启动与运维脚本

| 项 | 内容 |
|---|---|
| **定位** | `dfecrab` CLI 的实际执行层 + 运维工具 |
| **规模** | 15 个 .py，共 3094 行 + 2 个 .sh |
| **统一约定** | 用 `_resolve_venv_python()` 返回的 venv 解释器启动子服务，避免跑到系统 python |

### 2.1 文件一览

| 脚本 | 行数 | 分类 | 职责 |
|---|---|---|---|
| `check_system_health.py` | **996** | 体检 | 系统健康检查（最大脚本） |
| `concurrency_test.py` | 406 | 测试 | 并发压测 |
| `knowledge_api.py` | 276 | 服务 | 知识库 API（FastAPI） |
| `import_knowledge.py` | 264 | 运维 | 知识库导入 |
| `test_api_e2e.py` | 160 | 测试 | API 端到端测试 |
| `knowledge_health_check.py` | 145 | 体检 | 知识库健康检查 |
| `start_gateway_grpc.py` | 130 | 启动 | Gateway 启动器 |
| `start_knowledge_api.py` | 128 | 启动 | 知识库 API 启动器 |
| `test_load_monitor_e2e.py` | 117 | 测试 | 负载监控测试 |
| `rebuild_knowledge_chunks.py` | 116 | 运维 | 重切片 + 重建索引 |
| `test_knowledge_full.py` | 101 | 测试 | 知识库全量测试 |
| `rebuild_knowledge_index.py` | 95 | 运维 | 重建索引（含维度诊断） |
| `rebuild_index.py` | 94 | 运维 | 重建索引（基础版） |
| `backfill_agent_model.py` | 91 | 运维 | Agent 模型配置回填 |
| `cleanup_duplicate_memories.py` | 61 | 运维 | 重复记忆清理 |
| `package.sh` / `start_knowledge_api.sh` | — | 打包/启动 | Shell 脚本 |

---

### 2.2 `scripts/check_system_health.py` — 系统体检（996 行）

| 项 | 内容 |
|---|---|
| 类型 | 脚本 · 体检 |
| 规模 | 996 行 / 1 类 / 15+ 函数 |
| 职责 | 全系统健康检查，支持 `--json`（机器可读）与 `--deep`（深度检查） |
| 核心符号 | `CheckResult`（dataclass, 35）、`_python_snippet`(43)、`_run_snippet`(60)、`_classify_failure`(99)、`check_project_layout`(136)、`check_config`(164)、`check_ports`(191)、`taken`(213)、`looks_like_dfecrab_http`(221)、`check_runtime_dependencies`(291) |
| 依赖 | `src.config.config_loader`（第 168、201、625、811 行） |
| 关键行为 | ① 用**独立的 Python 子进程**跑检查片段（`_run_snippet`），避免检查代码本身崩溃拖垮体检；② `_classify_failure()` 对失败原因分类；③ `check_ports` 会检测端口是否被**真正的 DFEcrab 服务**占用（`looks_like_dfecrab_http`）而非任意进程 |
| 关联文件 | `dfecrab` CLI（健康检查引用它） |

| 备注 | 这是**写得最规范的脚本**：有 dataclass 结果类型、子进程隔离、失败分类。可作为其他脚本的范例 |

### 2.3 `scripts/knowledge_api.py` — 知识库 API（FastAPI）

| 项 | 内容 |
|---|---|
| 类型 | 服务 · API |
| 规模 | 276 行 / 2 个 Pydantic 模型 + 10 个端点 |
| 职责 | 端口 6788 的知识库 HTTP API |
| 核心符号 | `SearchRequest`(44)、`ChatRequest`(50)、`health_check`(59)、`upload_document`(75)、`search`(105)、`chat`(124)、`list_documents`(143)、`get_document_chunks`(158)、`list_knowledge_bases`(182)、`list_categories`(197) |
| 依赖 | **FastAPI**、`src.config.port_loader`（第 249、271 行） |
| 关联文件 | `scripts/start_knowledge_api.py`、`dfecrab kb` 子命令 |

> ⚠️ **技术栈冲突**：本文件用 FastAPI，而 `src/gateway/http/server.py` 用 **aiohttp**，`src/task/api_routes.py` 也用 FastAPI。
> 项目里同时存在 aiohttp 与 FastAPI 两套 Web 栈（详见发现 #118）。

---

### 🟠 2.4 三个重建索引脚本 —— 功能重叠分析

| 脚本 | 行数 | 重切片 | 维度诊断 | 重建索引 |
|---|---|---|---|---|
| `rebuild_index.py` | 94 | ❌ | ❌ | ✅ |
| `rebuild_knowledge_index.py` | 95 | ❌ | ✅ **是** | ✅ |
| `rebuild_knowledge_chunks.py` | 116 | ✅ **是** | ❌ | ✅ |

**结论：这不是三个完全相同的脚本，而是三个功能递增的脚本。**

| 脚本 | 入口函数 | 独有价值 |
|---|---|---|
| `rebuild_index.py` | `rebuild_index(batch_size=100)` | **无**——功能被 `rebuild_knowledge_index.py` 完全覆盖 |
| `rebuild_knowledge_index.py` | `main()` | **维度诊断**（先打印当前嵌入方案与旧索引 dim，再决定重建） |
| `rebuild_knowledge_chunks.py` | `rebuild(chunk_size, overlap)` | **重新切片**（读原文 → 按新参数切 → 覆写 chunks） |

| 建议 | `rebuild_index.py` 可删除（`rebuild_knowledge_index.py` 完全覆盖它，且更好）；另两个保留 |
|---|---|

> ### ✅ 交叉验证：脚本注释证实了「知识库跑在 TF-IDF 上」
>
> `rebuild_knowledge_index.py` 的 docstring 原文：
> > 修复「建索引时用了 TF-IDF(300维)、检索时用了 bge-small(512维)」造成的维度不一致，从而消除 faiss 检索时的维度不匹配报错。
>
> 这与我阶段 2.7 从 `knowledge_base/index/config.json` 的 `"dim": 300` 得出的结论**完全一致**——**代码库自己承认了这个问题**。

### 2.5 其余脚本速览

| 脚本 | 核心函数 | 说明 |
|---|---|---|
| `start_gateway_grpc.py` | `shutdown()`(40)、`signal_handler()`(53)、`main()`(60) | Gateway 启动器，安装 3 条日志链路（`src/utils/logging_setup.py`） |
| `start_knowledge_api.py` | `start_knowledge_api()`(15)、`stop_knowledge_api()`(109) | 知识库启停，用 `port_loader.knowledge_api_port` |
| `import_knowledge.py` | `process_document()`(33)、`rebuild_vector_index()`(105)、`main()`(171) | 文档导入 + 索引重建 |
| `knowledge_health_check.py` | `_read_index_dim()`(21)、`check_knowledge_base()`(57) | 索引维度检查 |
| `backfill_agent_model.py` | `resolve_agents_dir()`(27)、`backfill()`(42)、`main()`(78) | 批量回填 Agent 的 model 配置 |
| `cleanup_duplicate_memories.py` | `cleanup_daily_file()`(10)、`backup_daily_files()`(29)、`main()`(40) | 清理重复记忆（**带备份**，设计谨慎） |
| `concurrency_test.py` | `ReqResult`(36)、`_one_chat`(77)、`_one_stream`(124)、`_summarize`(189)、`run_concurrency`(259)、`main()`(370) | httpx 异步并发压测，支持 chat/stream 两模式 |
| `test_api_e2e.py` | `run_e2e_test()`(29) | API 端到端 |
| `test_knowledge_full.py` | `test_knowledge_base()`(19) | 知识库全量测试（直接 import `src.knowledge.skills`） |
| `test_load_monitor_e2e.py` | `run_load_monitor_test()`(28) | 配合 `src/monitoring/metrics.py` 的负载监控测试 |

| 备注 | `start_knowledge_api.sh` 与 `start_knowledge_api.py` 同名，**功能重叠**（一个是 shell 封装，一个是 Python 实现） |

---

## 3. 本阶段发现汇总

| # | 级别 | 发现 | 位置 |
|---|---|---|---|
| 114 | 🔴 P0 | **`services/` 两个 gRPC 服务是手写的 3003 / 2938 行上帝类**（阶段 2 待办已解决：不是生成代码） | `services/*_grpc.py` |
| 115 | 🔴 P0 | **`_execute_kunming_skills` 单方法 627 行**，占文件 21%，是本项目最需重构的单个函数 | `agent_service_grpc.py:489-1116` |
| 116 | 🟠 P1 | **思考标签剥离逻辑重复实现 4 处**：`src/agent/llm/think.py`、`grpc_server.py:82`、`manager_agent_grpc.py:1524-2023`、`agent_service_grpc.py:1116` | — |
| 117 | 🟠 P1 | `agent_service_grpc.py` 有 **10 个方法超过 77 行**，其中 3 个超过 150 行 | — |
| 118 | 🟠 P1 | **aiohttp 与 FastAPI 两套 Web 栈并存**：`gateway/http/server.py` 用 aiohttp，`scripts/knowledge_api.py` 与 `src/task/api_routes.py` 用 FastAPI | — |
| 119 | 🟡 P2 | **`rebuild_index.py` 功能被 `rebuild_knowledge_index.py` 完全覆盖**，可删 | `scripts/` |
| 120 | 🟡 P2 | `start_knowledge_api.sh` 与 `start_knowledge_api.py` **功能重叠** | `scripts/` |
| 121 | 🟡 P2 | `services/start_microservices.sh` 与根 `dfecrab` 的 start/stop **功能重叠**，且能力更弱（无 ZK 清理、无端口检测） | — |
| 122 | 🟡 P2 | `services/` 下散落 4 个 `.pyc` 文件（含 144 KB 的 `manager_agent_grpc.cpython-312.pyc`） | — |
| 123 | ✅ 确认 | **`rebuild_knowledge_index.py` 的 docstring 明确记载了「建索引 TF-IDF 300 维 vs 检索 bge 512 维」的维度不一致问题**，与我阶段 2.7 的判断完全一致 | `scripts/rebuild_knowledge_index.py:2-8` |
| 124 | ✅ 澄清 | 三个 rebuild 脚本**不是纯重复**，功能递增：`rebuild_index` ⊂ `rebuild_knowledge_index` + 诊断；`rebuild_knowledge_chunks` = 重切片 + 重建 |

---

<div align="center">

**05 · scripts 与 services 完**　（20 个 .py，9111 行 + 4 个 .sh）

上一页：[04-plugins插件.md](./04-plugins插件.md)　｜　下一页：[06-tests与examples.md](./06-tests与examples.md)

</div>