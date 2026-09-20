# 变更日志

记录每次的更新内容，最新在最上面。

---

## 2026-09-08（批次 16：默认助手唯一化语义收口 + 删除/取消/模型 3 处修复 + 模型解析冗余合并）

**性质**：修复 + 语义收口。平台默认助手改为"全局唯一且 `agent_type=default` 跟随默认"（切换默认时旧默认自动降级 worker、新默认升级 default），并修复删除默认不回退（缩进 Bug）、取消默认误伤非当前默认、`model_config` 能设不能清 3 个问题；`manager_agent` 禁止设为默认。

**`src/gateway/grpc_server.py`**
- `_fallback_default_agent`：默认回退链（dfecrab → 任一存在且非 manager 的 agent，始终指向存在 agent）；`_default_agent_id` 失效时走该兜底
- `_set_agent_type` / `_normalize_agent_type`：config.json 类型同步 + 读侧归一（default 跟随默认助手，manager 保持，其余 worker，兼容历史脏数据）
- `_reconcile_default_agent_type`：网关启动时对账历史 config（幂等）
- `_persist_default_agent`：切换默认即把旧默认 config.json 降 worker、新默认升 default（内建 manager 拦截）
- `_handle_set_default_agent`：`manager_agent` 设为默认被拒
- `_handle_clear_default_agent`：仅当该 agent 是**当前默认**才回退（修复：此前无条件强制回退 dfecrab，会误伤真默认）；回退目标走兜底链
- `_handle_delete_agent`：修复缩进 Bug——删除默认回退逻辑原误嵌在 `except` 内，正常路径永不执行；现回退到兜底 agent
- `_handle_update_agent`：`model_config` 空串可清空回"跟随全局"（修复：原 `and body.get("model_config")` 让空串被 falsy 吞掉，固定模型后无法改回）
- 冗余清理：`_resolve_model_name` + `_agent_model_context_length` 合并为 `_resolve_agent_model`（一次 provider 查找返回 model_config/model_name/context_length），列表/详情/创建/更新 4 处调用收敛；列表 agent_type 硬编码推断（dfecrab=default）清除，统一 `_normalize_agent_type`；`except` 分支 `print` → `logger.warning`

**`scripts/verify_all_features.py`（回归）**
- `g2_agents` 增补：agent_type 跟随默认断言、manager 拒绝、DELETE 非当前默认 no-op、删除默认 agent 自动回退（独立临时 agent，避免影响 MCP 组对 TEST_AGENT 的依赖）、model_config 先固定再清空
- 新增"能力探测门控"：服务器未部署批次 16 语义（agent_type 未随默认联动）时，将 manager 拒绝 / 取消幂等 / 删除默认回退 用例自动 SKIP，防对旧逻辑误写污染
- 新增 `--only-groups`（聚焦执行指定分组）；Windows GBK 控制台 `reconfigure(errors="replace")` 兜底防 emoji 中断

**文档**
- `前端对接文档/前端对接文档_Agent管理.md` v5.2：默认助手唯一化语义、manager 不可设默认、DELETE /default 幂等收紧、删除默认必回退、model_config 可清空（接口协议零变化，前端无需适配）

**验证**
- py_compile + lint 0
- 服务器 172.20.51.153 部署前基线（`docs/verify_results/全功能回归验证结果_20260908_174437.txt`）：**PASS 15 / FAIL 2 / SKIP 3**——FAIL 恰为批次 16 的两个修复点（model_config 清空未生效、agent_type 未随默认联动），证明**服务器尚未部署新版**；脚本自动回滚干净（默认恢复 dfecrab、临时智能体已清除）

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/gateway/grpc_server.py`（必换）；`scripts/verify_all_features.py`（可选，回归用）
- 重启网关
- 部署后重验：`python scripts/verify_all_features.py --base http://127.0.0.1:6789 --only-groups 2`（预期 PASS 无 FAIL/SKIP）

---

## 2026-09-08（批次 15：Agent 配置字段补齐 + MCP 全局绑定事故修复 + 模型字段对齐）

**性质**：修复 + 接口语义收敛。Agent 详情/列表模型字段与 `GET /api/models` 对齐（`model_config` == 模型接口 `config_name`，透传 `context_length`，空配置=跟随全局）；`welcome_message`/`auto_start` 创建落盘、时间戳兜底；修复 `set_agent_bindings` 把 `*` 全局服务收敛成单 agent、清空后导致现场全局绑定丢失的事故。

**`src/mcp/__init__.py`（事故根修）**
- `set_agent_bindings`：target 命中且该服务 `bound_agents` 含 `"*"` 时跳过——全局服务已对所有 agent 生效，智能体侧禁止"专属化/取消"，根治"给 agent 保存绑定 → `*` 收敛成单 agent → 清空该 agent → 现场全局绑定变 `[]`"的破坏链（2026-09-08 由批次 14 验证脚本触发）

**`src/gateway/grpc_server.py`（字段补齐与对齐）**
- `_resolve_model_name`：`model_config` 为空时返回当前全局模型的 `model_name`（跟随全局可见），列表/详情 `model_name` 不再全空
- 新增 `_agent_model_context_length`：列表/详情透传 `context_length`（`model_config` 有值取该 provider 窗口，空=全局窗口），与 `GET /api/models` 的 provider 字段对齐
- `_handle_create_agent`：config.json 落盘 `welcome_message` / `auto_start`（此前创建即丢弃、仅编辑才生效，`auto_start` 永不可回显）
- `GET /api/agents/{id}`：返回 `auto_start`（老 agent 缺省 true）；`created_at`/`updated_at` 缺失时兜底 config.json 文件 mtime（手建老文件不再空）

**`agents/manager_agent/config.json`**
- 补 `description`（此前 config 与 agents_index 均缺，列表/详情 manager 描述为空；描述为该 agent 唯一的配置层级入口，其余 agent 均已有 description 无需补）

**现场数据修复（批次 14 事故残留）**
- `config/mcporter.json`：`blackxml_topology.bound_agents` 恢复 `["*"]`（验证脚本绑定/清空临时 agent 时被收敛清成 `[]`，所有 agent `recommended_mcp` 全空）；`get_bound_server_names` 实时读盘，恢复后无需重启即生效

**文档**
- `前端对接文档/前端对接文档_Agent管理.md` v5.1：字段语义表（`model_config=""`=跟随全局、`model_config`==模型接口 `config_name`、新增 `context_length`、无 `config_name` 字段、description/时间戳缺失兜底）、全局共享 MCP 服务约束（标"全局共享"、不可取消）、编辑表单须用详情接口回显 + `restart` 热生效

**验证**
- py_compile + lint 0 + `agents/manager_agent/config.json` JSON 校验通过
- 现场复核：dfecrab 详情 `model_name`/`context_length` 非空、`recommended_mcp` 恢复 `['blackxml_topology']`、manager_agent `description` 非空；对 `*` 服务再执行一次智能体保存绑定确认不破坏全局

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/mcp/__init__.py`、`src/gateway/grpc_server.py`、`agents/manager_agent/config.json`
- 手工恢复 `config/mcporter.json`（`blackxml_topology.bound_agents = ["*"]`）
- 重启网关 + Worker（`src/mcp` 被 worker 引用，必须连 worker 一起重启）

---

## 2026-09-08（批次 13：默认智能体 + MCP 绑定收敛到智能体侧 + 列表派生字段）

**性质**：新增功能。平台"默认助手"（部署级全局唯一，仅前端预选/传参用，不接管缺省路由）+ 绑定编辑入口收敛到智能体配置页 + Agent 列表/详情派生字段。

**`src/config/app_config.py`**
- 新增 `update_section(name, data)`：dfecrab.json 顶层段统一写入口（写盘 + `reload_dfecrab()`，失败回滚内存缓存），避免各 handler 散落 open/json

**`config/dfecrab.json`**
- 顶层新增 `default_agent`（缺省 `dfecrab`，含 `_note`，多现场随部署文件差异化）
- `mcp` 段新增 `reserved_bindings`（缺省保护 `alert_judge_tools` 仅限 `alert_judge`，防误绑触发专属研判链路）

**`src/mcp/__init__.py`**
- `MCPClient.set_agent_bindings()`：agent 视角全量绑定收敛——单次读盘/单次写盘；勾选加绑、未勾选解除、`*` 全局收敛为显式列表、保留其它 agent 绑定、未知服务拒绝且不落盘

**`src/gateway/handlers/mcp_handler.py`**
- 新增 `save_agent_mcp`：`PUT /api/agents/{agent_id}/mcp` 全量保存（reserved 白名单校验、disabled 服务放行并 warnings、热刷新工具池）
- 废弃 `POST /api/agents/{agent_id}/mcp` 的提示文案改指新 PUT 接口

**`src/gateway/grpc_server.py`**
- 新增 `_default_agent_id`（读取+存在性兜底 dfecrab）/ `_recommended_mcp_servers`（绑定反向聚合）/ `_persist_default_agent`（单值覆盖）/ `_handle_set_default_agent` / `_handle_clear_default_agent` / `_handle_save_agent_mcp`（网关包装：保存绑定后失效列表缓存）
- 列表：顶层 `default_agent_id`，每项 `is_default` + `recommended_mcp`；详情同步新增，并修复老 agent `description` 不回退 agents_index 的问题
- 路由：`PUT/DELETE /api/agents/{agent_id}/default`、`PUT /api/agents/{agent_id}/mcp`
- 删除 Agent 若为默认助手 → 自动回退默认到 dfecrab

**文档**
- `前端对接文档/前端对接文档_Agent管理.md` v5.0：新字段 + §3.6 设默认 / §3.7 保存绑定 + 对话链路与页面树
- `前端对接文档/前端对接文档_MCP服务管理.md` v4.11：绑定编辑收敛到智能体侧，服务页绑定下拉移除（改只读 chips）

**权限粒度对齐（同批补充 · 依 config/permissions.json 三角色模型）**
- MCP 服务管理 7 接口（列表/启停/同步/绑定/新增/删除/测试）与 `PUT/POST /api/agents/{id}/mcp` 去除 `admin_only` 特判，统一按 level 鉴权：`read`（列表）/ `write`（写操作）——admin/user 均可管理智能体与 MCP，guest 写操作仍 403
- 保持 `admin_only` 不变：用户管理 4 接口（`/api/users`，文档契约）；Agent 管理/设默认本就是 `write` 无需调整
- MCP 服务管理文档 v4.12 同步鉴权说明（前端无需改动）

**验证**
- py_compile 4 文件 0 错 + lint 0 + dfecrab.json JSON 校验通过
- 冒烟断言（临时脚本已自删）：`default_agent` 读取（`_note` 剔除/原始保留）、绑定收敛 7 断言（加绑/解除/`*` 收敛/保留他人/未知拒绝不落盘/清空）全过
- 接口验证（`docs/verify_results/接口验证结果_默认智能体与MCP绑定_20260908_141307.txt`）：对 172.20.51.153 实测——新字段缺失/新端点 404/废弃提示仍为旧文案 = **服务器尚未部署新版**（旧接口行为正常，写测未触达，服务器配置未受影响）；部署替换文件并重启后重验应全 PASS

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/config/app_config.py`、`src/mcp/__init__.py`、`src/gateway/handlers/mcp_handler.py`、`src/gateway/grpc_server.py`、`config/dfecrab.json`
- 前端侧（可选）：`前端对接文档/前端对接文档_Agent管理.md`、`前端对接文档/前端对接文档_MCP服务管理.md`
- 重启网关 + Worker（`app_config` / `src/mcp` 被 worker 侧引用）

---

## 2026-09-08（批次 12 步骤 4：验证收尾 + 冗余修复 + 前端文档）

**性质**：批次 12 收尾。全接口验证 26/26 PASS；顺带修复 3 处收尾检查发现的问题。

**验证（`docs/verify_results/批次12验证结果_20260908_105925.txt`）**
- 接口级全覆盖（handler 层，multipart + JSON 双通道）：上传（含字节数一致）/ 校验拒绝 / 列表 / 下载回读 / 权限（他人拒绝、admin 跨用户）/ 对话注入闭环 / 叉掉即失效 / 删会话联动清附件 / 孤儿 TTL 保留 active——**26 PASS / 0 FAIL**；验证脚本执行后自删

**收尾修复**
- `config/dfecrab.json`：阶段1 遗留死配置 `max_attachments_per_message`（无代码引用）改名 `max_files_per_session`，对齐 `file_handler` 实际引用
- `src/gateway/handlers/file_handler.py`：`_req_user` 缺省身份从硬编码 `"default"` 收敛到 `identity.default_user_id`（对齐 B-2）；`download` MIME 改显式覆盖表（`.csv→text/csv` 等，修复 Windows 注册表把 `.csv` 识别为 `application/vnd.ms-excel` 的问题）

**文档**
- 新增 `前端对接文档/前端对接文档_文件上传.md`（4 接口 + 生命周期 + Checklist）
- 对话接口文档加 v5.6 更新记录：**v5.5 的请求体 `attachments` 字段废弃**，改走文件上传接口；对话自动携带会话附件

**需部署文件（服务器 172.20.51.153）**
- 见下方步骤 1/2/3 汇总，另加：`src/gateway/handlers/file_handler.py`、`前端对接文档/`（前端侧）

---

## 2026-09-08（批次 12 步骤 3：删会话联动清理 + 孤儿 TTL）

**性质**：批次 12 步骤 3。附件生命周期收口——**删除会话时联动清掉该会话全部附件**（注册记录 + 落盘目录，幂等）；后台周期清理孤儿（deleted / 超 TTL / 注册表无记录的落盘文件），避免"会话删了文件还在"与"上传中途失败残留"。

**`src/files/service.py` + `src/gateway/session_handler.py` + `src/gateway/grpc_server.py` + `config/dfecrab.json`**
- `FileService.purge_session(session_id)`：删会话联动一次清——注册表物理移除记录（`remove_by_session`）+ rmtree 会话目录 `data/files/{session_id}/`；幂等、返回清理统计
- `SessionService.delete_session()`（HTTP `DELETE /api/v2/sessions/deleteSession/{id}` + WS `DELETE_SESSION` 两入口共用）：删除成功后调 `purge_session`；best-effort，清理失败不影响会话删除结果，仅记日志
- `_files_orphan_cleanup_loop()`：后台周期清理协程（挂靠 Gateway 常驻 loop），按 `file_upload.cleanup_interval_s` 周期调 `registry.cleanup_orphans(cleanup_ttl_days)`——回收 deleted 记录、超期记录、注册表无记录的落盘孤儿；仅清孤儿不动 active
- `config/dfecrab.json`：`file_upload` 段新增 `cleanup_ttl_days`（默认 30）/ `cleanup_interval_s`（默认 3600，含 `_note`）

**验证**
- py_compile + JSON + lint 0
- 断言脚本（已自删）：静态触点、purge 后记录+落盘全清且他会话不受影响、孤儿落盘回收、deleted 记录回收且 active 保留

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/gateway/grpc_server.py`、`src/gateway/session_handler.py`、`src/files/service.py`、`config/dfecrab.json`；重启网关 + Worker（registry/service 被 worker 引用）

---

## 2026-09-08（批次 12 步骤 2：对话按会话自动注入附件）

**性质**：批次 12 步骤 2。把步骤 1 的附件注册表接入 `_run_chat_pipeline`——**同一会话每轮对话自动带上该会话 active 附件摘要**（模型全程知道附件内容，无需重传）；叉掉/删除后附件 `status=deleted`，下一轮即不再注入（模型自然"忘掉"）。

**`src/gateway/grpc_server.py`**
- `_react_chat_generator`：`enhanced_message` 构造后（非 alert_judge 分支）按 `session_id` 调 `FileService.build_session_context()`，取 active 附件摘要预算截断拼到用户消息前
- 关键设计：**历史/摘要仍按原始 message 落库**（`add_message` 在 prepare 阶段用未注入的 message），附件只注入"发给模型的当前轮"，避免每轮重复累积、摘要被附件文本污染
- 注入日志：`[Pipeline] 会话附件注入 N 字符 (session=...)`

**验证**
- py_compile + lint 0
- 断言脚本（已自删）：静态触点（注入调用 + 历史用原始消息）、上传后注入含摘要、多轮复用不重传、`mark_deleted` 后不再注入、空会话空注入
- 在线验收（部署后）：上传 csv → 连续两问不重传均答对（worker 日志见注入）→ `DELETE /api/files/{fid}` 后再问同一话题 → 模型不再引用台账内容

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/gateway/grpc_server.py`（连同步骤 1 的 `src/files/` 三件 + handler 一起）；重启网关 + Worker

---

## 2026-09-08（批次 12 步骤 1：文件实体化——multipart 上传 + 注册表 + 4 接口）

**性质**：对齐 LibreChat「先上传原文件、再本地解析、解析文本才进上下文」的会话级附件模式。文件从「阶段 1 的无状态内联 base64」升级为**有 file_id、有会话归属、有生命周期的实体**；上传即绑定会话、可列表/下载/删除，删除后对话不再注入。为后续「对话按会话自动注入」「删会话联动清理」「叉掉即删」打基础。

**A 新增 `src/files/multipart.py`**
- multipart/form-data 解析（零第三方依赖，标准库按 boundary 切块）——对齐 local-code-api 用标准库实现的思路（其 `cgi.FieldStorage` 已随 Python 3.13 移除，故自研轻量等价实现）
- 仅剥 MIME 分隔 CRLF、保留 payload 本体（含内部换行）；普通字段与文件分离输出

**B 新增 `src/files/registry.py`（附件注册表）**
- 单 JSON 文件落盘（`data/files/registry.json`），原子写（临时文件+replace，对齐 permissions.json 先例）
- 记录：`file_id / session_id / user_id / filename / size / storage / summary_cache / created_at / status`
- 操作：`register / get / list_by_session / list_by_user / mark_deleted / delete_record / remove_by_session / cleanup_orphans`（孤儿=deleted/超期/注册表无记录的落盘文件）
- `_configure()` 支持测试/多现场覆盖存储根目录

**C 重构 `src/files/service.py`（移除阶段1 内联 base64）**
- `store_upload()`：校验清洗 → 落盘 `data/files/{session_id}/` → 解析一次 → 摘要缓存入库
- `build_session_context()`：按会话查 active 附件、取 summary_cache、预算截断组合注入块
- 解析器抽为可复用 `parse_file_by_ext()` / `render_summary()`

**D 新增 `src/gateway/handlers/file_handler.py`（4 接口，owner/admin 权限）**
- `POST /api/files`（multipart：session_id + file；兼容便捷 JSON body）
- `GET /api/files?session_id=`（列表；admin 可 ?user_id= 查他人）
- `DELETE /api/files/{file_id}`（删落盘 + status=deleted，后续对话不再注入）
- `GET /api/files/{file_id}/download`（base64 + 元信息，前端拼 data URL）

**E `src/gateway/grpc_server.py`**
- `_register_routes` 注册 4 条 file 路由（download 全路径正则与 /{file_id} 无冲突）
- 移除 `_run_chat_pipeline` 的 `attachments` 参数及 4 入口内联传参（阶段1 内联不再支持，按用户要求）

**验证**
- py_compile 6 文件 0 错 + lint 0
- 断言脚本（已自删，临时目录已清）：multipart 解析（字段+文件字节精确一致/非 multipart 报错）、registry 登记/列表归属过滤/软删后不注入/孤儿与超期清理、FileService 上传登记与按会话注入、FileHandler upload/list/download/delete 端到端（owner 校验、删除后 404 语义）
- 在线验收（部署后，下一步骤）：`curl -F "session_id=..." -F "file=@台账.csv" http://…/api/files` → list/download/delete 全链路

**需部署文件（服务器 172.20.51.153）**
- 新增：`src/files/multipart.py`、`src/files/registry.py`、`src/gateway/handlers/file_handler.py`
- 替换：`src/files/__init__.py`、`src/files/service.py`、`src/gateway/grpc_server.py`
- 重启网关 + Worker
- 注：对话按会话自动注入 / 删会话联动清理为步骤 2，本次未接（当前会话对话不再带附件注入，属预期中间态）

---
## 2026-09-08（优化批次 11-C3：文件上传阶段1——txt/csv/excel 解析注入）

**性质**：批次 11 步骤 3。对话请求体新增 `attachments` 字段，后端解析后把**摘要注入用户消息前**进 ReAct 上下文（二进制不上行，原文件落盘保留）。阶段 1 刻意从简：txt/md/log/csv 标准库实现、xlsx 需 openpyxl（缺失友好降级）；不做独立 WS 上传事件。

**`src/files/service.py`（新增）+ `src/files/__init__.py`（新增）+ `src/gateway/grpc_server.py` + `config/dfecrab.json`**
- `FileService.resolve(attachments, session_id, context_length)`：数量/大小/扩展名白名单校验（参数非判定逻辑）→ 文件名清洗（防路径穿越）→ 落盘 `data/uploads/{session_id}/`（uuid 前缀）→ 按扩展名解析
- txt/md/log：编码探测（utf-8→gbk→utf-16 兜底 replace）→ 受控截断（头 70% + 尾 25%）
- csv：列名 + 类型推断 + 总行数 + 前 N 行（标准库 csv）
- xlsx：openpyxl 逐 sheet 预览（≤ `max_xlsx_sheets`）；缺依赖返回友好提示
- 预算：注入块 ≤ `context_length × file_upload.budget_ratio`（多现场 16K/32K/100K 自适应），超限外层截断并标注
- `_run_chat_pipeline` 新增 `attachments` 参数：入口解析并把注入块拼到 `message` 前；HTTP 非流式/流式、WS chat/chat_stream 四入口透传
- 配置 `file_upload` 段：`max_file_size_mb=10` / `max_attachments_per_message=5` / `allowed_extensions=[.txt .md .log .csv .xlsx]` / `budget_ratio=0.5` / `summary_rows=10` / `max_xlsx_sheets=10`（含 `_note`）

**验证**
- py_compile 0 错 + lint 0
- 断言脚本（已自删）：txt 中文解析、csv 摘要（列名/类型/前N行）、超预算截断、白名单拒绝、路径穿越清洗、空附件返回空、数量上限拒绝
- 在线验收（部署后）：`curl -X POST /api/v2/chat -d '{"message":"分析台账里负荷最高的线路","attachments":[{"filename":"台账.csv","content_base64":"..."}]}'` → 注入块可见于日志 `[Pipeline] 附件注入完成`

**需部署文件（服务器 172.20.51.153）**
- 新增：`src/files/__init__.py`、`src/files/service.py`
- 替换：`src/gateway/grpc_server.py`、`config/dfecrab.json`；重启网关 + Worker
- 若需 xlsx：`pip install openpyxl`（txt/csv 无需新依赖）

---

## 2026-09-08（优化批次 11-C2：ReAct 进展便签，消除"每轮重新复述任务"）

**性质**：批次 11 步骤 2。F19 转电预案实测三轮 reasoning 都以「好的，用户让我制定…」开头（worker 21433/21453/21461）——ReAct 每轮是独立 LLM 调用、上轮思考不可见，模型只能靠重述任务自我对齐。C-2 给模型一份**权威的"到目前为止"进展便签**（对标 Claude Code scratchpad / OpenHands condenser），让第 N 轮直接接着干。

**`src/agent/loop.py` + `config/dfecrab.json`**
- 新增模块配置 `_SCRATCHPAD_ENABLED` / `_SCRATCHPAD_MAX_CHARS` / `_SCRATCH_MARKER`（读 `react.scratchpad` / `scratchpad_max_chars`）
- 模块级纯函数：`_scratch_compact_args()`（工具参数压一行，供记录"用了什么定位条件"）、`_scratchpad_text()`（便签行组合 + 附"直接继续/收尾，勿复述任务"引导语；超长保留最近轮次）
- `run()` 内三触点：
  - 局部状态 `_scratch_lines`（每请求独立）
  - **轮首注入**：每轮 AutoCompact 之后、LLM 调用前，先移除上一轮旧便签再追加最新版（有内容才注入）
  - **工具回填后记录**：追加 `第N轮 调用 {工具名}({参数}) → {status}`（error 附原因），纯程序化、零关键词
- 与既有机制关系：AutoCompact（85% 阈值 LLM 压缩旧轮）是内存兜底，便签是每轮轻量进度条，互补不冲突；AnswerGate 重试反馈复用同一条 system 注入通道

**验证**
- py_compile 0 错 + lint 0
- 断言脚本（已自删）：静态三触点、`_scratch_compact_args`（紧凑/JSON 还原/截断）、`_scratchpad_text`（组合/超长保最近/空输入）、dfecrab.json 配置
- 在线验收（部署后）：同问"F19 转电预案"，第 3+ 轮 reasoning 不再以"好的，用户让我…"开头，直接接"已确认目标…"；reasoning_len 缩短（复述 token 减少）

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/agent/loop.py`、`config/dfecrab.json`；重启网关 + Worker（loop.py 在 worker/网关进程内共享）

---

## 2026-09-08（优化批次 11-C1：进程级单例化，消除重复初始化）

**性质**：批次 11 步骤 1。日志实证一次请求内出现「记忆管理器初始化 ×2、`长期记忆已加载` ×3、bge 模型/reranker/向量索引加载 ×2」（gateway 57840-57868、57922-57952）。C-1 将跨调用点共享的重型资源收敛为进程级单例，消除重复初始化与内存双份。

**A `src/memory/unified_manager.py`（UnifiedMemoryManager 单例）**
- 新增 `get_unified_manager()`（`_UNIFIED_SINGLETON` + 锁，进程内仅构造一次）
- 安全性：读写方法均显式传 agent_id/user_id，`AgentMemoryModule` 内部按 `(agent_id, user_id)` 缓存 MemoryManager，共享实例无数据串扰
- 调用点替换 5 处：`loop.py`（加载记忆上下文 / 记忆沉淀）、`reflector.py`、`grpc_server.py`（USER_PROFILE 注入）、`memory_handler.py`（检索 API）

**B `src/knowledge/`（embedder / reranker / 向量索引单例）**
- `local_embedder.py`：新增 `get_local_embedder()`；`knowledge_qa` / `knowledge_search` / `knowledge_service` 重建共用同一 bge 实例（原各自 new → 模型加载 ×2）
- `reranker.py`：新增 `get_reranker()`；`retriever.HybridRetriever` 改走单例（原 use_rerank 时每次 new → CrossEncoder ×2）
- `vector_store.py`：`load_default_vector_store()` 加**磁盘签名缓存**（index.faiss/metadata.pkl/config.json 的 mtime_ns+size 为签名，变化自动重载）；新增 `invalidate_default_vector_store()`；`knowledge_service._rebuild_index_async` 重建写盘后主动失效，不破坏"上传后热刷新"

**验证**
- py_compile 12 文件 0 错 + lint 0
- 断言脚本（已自删）：调用点零残留直接构造、单例函数就位、`get_unified_manager()` 同对象、mock 类验证 LocalEmbedder/Reranker **各构造 1 次**
- 在线验收（部署后）：grep 计数 `统一记忆管理器已初始化` 每请求 ≤1（进程首请求后 0）、`加载模型: bge` 进程级 ≤1

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/memory/unified_manager.py`、`src/knowledge/embedding/local_embedder.py`、`src/knowledge/core/reranker.py`、`src/knowledge/core/vector_store.py`、`src/knowledge/core/retriever.py`、`src/knowledge/skills/knowledge_qa.py`、`src/knowledge/skills/knowledge_search.py`、`src/knowledge/knowledge_service.py`、`src/agent/loop.py`、`src/reflection/reflector.py`、`src/gateway/grpc_server.py`、`src/gateway/handlers/memory_handler.py`
- 重启：网关 + Worker + Manager + 知识库进程（knowledge_* 侧单例各自进程内生效）

---
## 2026-09-07（优化批次 10-B/C：user_id 收敛 + agents 缓存收敛）

**性质**：批次 10 步骤 3。B-2 收敛对话入口 user_id 来源（请求体 > 认证头/上下文 > 配置默认），缺省时按来源限频告警（多用户现场避免会话/记忆落到共享默认用户）；C 收敛两处重复日志与重复扫描——`default→dfecrab` 迁移告警同进程仅一次、`GET /api/agents` 结果 TTL 缓存（二次访问 <10ms）。

**B-2 `src/gateway/grpc_server.py` + `config/dfecrab.json`**
- 新增 `_resolve_user_id()`：user_id 解析收敛（declared 请求体 > auth HTTP `X-User-Id` 头 / WS 认证上下文 > `identity.default_user_id`）；仅当两者都缺失才回落默认并打 WARNING（按来源限频 `identity.warn_missing_interval_s`，防刷屏）。纯配置驱动，无名单无关键词
- 4 个对话入口统一接入：WS `handle_chat`/`handle_chat_stream`、HTTP `_handle_chat`/`_handle_chat_stream`
- `config/dfecrab.json` 新增 `identity` 段（`default_user_id` / `warn_missing_user_id` / `warn_missing_interval_s`，含 `_note`）

**C `src/agent/agent_config.py` + `src/gateway/grpc_server.py` + `config/dfecrab.json`**
- `normalize_agent_id()`：同进程内同一旧 ID（如 `default`）的迁移告警只打一次（`_WARNED_AGENT_IDS` 去重），根治"default 已改名"刷屏
- `_handle_list_agents()`：新增 TTL 缓存（`cache.agents_list_ttl_s`，缺省 1.5s）——命中直接返回进程内结果（二次访问 <10ms），TTL 到期自动重建保持 ZK 状态新鲜；命中走 debug、重建走 info，避免轮询刷日志；agent 增/改/删三处主动失效缓存
- `config/dfecrab.json` 新增 `cache` 段（`agents_list_ttl_s`，含 `_note`）

**验证**
- 本地：py_compile + lint 0 + JSON 校验 + 断言（六入口收敛、旧式解析清零、CRUD 缓存失效 3 处）+ `normalize_agent_id` 运行时去重（2 次调用 1 条告警）
- 在线：`scripts/verify_b10bc_user_agents.py`（执行后自删），结果存 `docs/verify_results/批次10BC验证结果_20260907_174309.txt`——PASS=14 / WARN=1（TTL<10ms 待部署后复跑）/ FAIL=0；接口覆盖 /health、/api/agents×2、chat、chat/stream、sessions、users、WS auth（本机缺 websockets 库 SKIP）

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/gateway/grpc_server.py`、`src/agent/agent_config.py`、`config/dfecrab.json`，重启网关 + Worker + Manager（agent_config 三进程共享）

---

## 2026-09-07（优化批次 10-A：intent 收敛为 chat/task 两档，complex 退役）

**性质**：基于 14:50-14:58 实测日志决策——`complex`（自动拆步 Plan）在弱模型现场是负收益（Planner 幻想步骤 / 分级不稳定 / Plan×AnswerGate 耗时放大 / Plan 收尾必崩 bug）。批次 10-A 将 intent 收敛为 `chat/task` 两档，多步骤复杂度由 task 工具循环消化；Plan 执行器代码**保留不删**，作 `plan_mode=explicit` 显式触发与未来多智能体编排的底座。complex 语义将来移入"编排维度"，不再占用 intent。

**A `agents/manager_agent/config.json`（Manager 提示词）**
- intent 定义改为两档：`chat=闲聊问候、无需工具；task=所有任务/查询（含多步骤复杂任务，一律 task，由智能体在工具循环内自主连续完成）`；显式"禁止输出 complex"

**B `src/gateway/grpc_server.py`**
- 新增 `_resolve_plan_use()`：Plan 执行器开关（读 `react.plan_mode`）——`off`(默认)恒不拆步；`explicit` 仅请求体 `use_plan:true` 启用（预留）
- `_run_chat_pipeline` else 分支：intent 防御性归一（残留 complex/未知值 → task，打日志观察），`use_plan` 不再由 `intent=="complex"` 推导
- `_handle_chat` / `_handle_chat_stream` 提取并透传请求体 `use_plan`
- **Bug 修复**：`_react_chat_generator` Plan 分支此前未初始化 `tool_calls_made/matched_skills`（只在非 Plan 分支初始化）→ 任何 Plan 收尾 `UnboundLocalError`；现于函数顶部统一初始化，删除 else 重复声明
- `_resolve_agent_tool_choice` docstring 同步（task 含原 complex）

**C `src/agent/intent_classifier.py`（LLM 降级分类同步两档）**
- LLM prompt / 规则模式 / 文档注释收敛为 chat/task；新增 `_normalize()` classmethod：输出统一归一（chat 保持、complex/未知 → task），防御旧调用方残留
- `COMPLEX` 常量 / `complex_patterns` 参数保留仅为外部旧调用兼容（已不产生 complex 输出）

**D `config/dfecrab.json`**
- `react` 段新增 `plan_mode: "off"`（含 `_note` 说明）；`markdown_output_hint: true`（用户已现场开启）保留未动

**E 验证**
- py_compile + lint 0 + JSON 校验 + 行为断言通过：manager prompt 无 complex 输出词、classifier `_normalize('complex')=='task'`、grpc 无旧 `use_plan = (intent == "complex")`、`_resolve_plan_use` 与顶部统一初始化存在
- 在线验收（部署后）：同问三遍 `manager_decision.intent ∈ {chat, task}` 且均直跑成功；复杂问题不再出现 `plan_created` 事件

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/gateway/grpc_server.py`、`src/agent/intent_classifier.py`、`agents/manager_agent/config.json`、`config/dfecrab.json`，重启网关 + Manager Agent
- 说明：批次 10-B/C/D（部署补齐、user_id、单例化/缓存、测试件清理）另行成条

---

## 2026-09-07（优化批次 9：路由语义化 + AnswerGate 回复质检 + 写工具收敛 + ZK 命名统一 + app_config 单点加载）

**性质**：基于 F19 转电预案实测（路由误入 knowledge_agent / 拿错馈线 / "约127户需调用工具确认"占位 / 工具注入含写操作）的闭环修复。判定逻辑全部**语义化或 schema 驱动，零关键词表、零名单**（对齐 CodeBuddy Craft「规划→执行→验证→修复」、LibreChat serverInstructions、MCP annotations 规范意图）。

**A `agents/manager_agent/config.json`（路由语义化，仅提示词文本）**
- 路由规则从"关键词→agent 映射表"改为"意图域语义判断 + 拿不准一律 dfecrab（主智能体，可装配 MCP 工具）"；knowledge_agent 收窄为"查看/引用已有文档内容本身"
- 不改 `agents/dfecrab/config.json`、不改 `mcp_servers/blackxml-topology-mcp/`（按约束跳过）

**B `src/agent/loop.py` + `src/agent/multi/assessor.py`（AnswerGate 回复质检门控）**
- assessor 新增 `Verification` 数据类 + `verify()`：纯 LLM 语义判定三项（量化结论是否有工具结果支撑 / 是否残留"待调用工具确认"占位 / 分析对象是否与用户请求一致），零关键词表；无适配器/异常一律放行（fail-open）
- loop 新增 `_verify_final_answer()`；run() 中**已调用过工具**的候选最终回复正文先缓存不外发，验证通过才流式补发；不通过带 feedback 注入 system 重试（`react.answer_gate_max_retry`，默认 1 次，防死循环）；验证超时（`answer_gate_timeout`，默认 60s）默认放行；工具轮丢弃缓存；纯聊天/首轮直答不门控（保持逐 token 实时）
- 新增 `react.markdown_output_hint`（默认关）：开启后在系统提示追加一句通用 Markdown 输出要求（前端 GFM 渲染就绪后按现场开启）

**C `src/skill/registry.py` + `config/dfecrab.json`（写工具收敛，schema 驱动零名单）**
- 新增 `_is_mcp_write_tool_schema()`：按服务端自我声明判定（`required` 含 `confirm` / `confirm.enum` 含 `APPLY` / 预留 annotations.destructiveHint），新增工具/服务零维护
- `list_tools_for_agent` MCP 装配后默认过滤写工具（`mcp.exclude_write_tools`，默认 true，日志打印被过滤清单）；数据更新类对话置 false 恢复

**D ZK 命名统一（根治 `default→dfecrab` 告警刷屏，源头修复非缓存遮掩）**
- `services/agent_service/agent_service_grpc.py`：worker 注册 `service_type` 恒为 `worker_agent`（dfecrab 不再注册 `default_agent`；agent 身份由 `metadata.agent_id` 标识）
- `src/gateway/grpc_server.py`：新增静态方法 `_zk_instance_agent_id()`（网关所有 ZK 实例解析点收敛单点：metadata 优先；旧 `default_agent` 节点无 metadata 一律归 dfecrab），替换 5 处散落 split 解析；worker 健康检查同时探测 `worker_agent`（新）+ `default_agent`（兼容旧节点）
- `src/task/manager_agent.py`：`_get_default_agents()` 兜底清单 `default_agent` 条目改为 `dfecrab`

**E `src/config/app_config.py`（新增，配置单点加载，步骤6 收敛）**
- dfecrab.json 唯一读取口：路径锚定 PROJECT_ROOT、进程内缓存 + `reload_dfecrab()`、`_clean()` 自动剔除 `_` 前缀说明键（react/mcp 段的 `_note` 注释不进运行时视图）
- `loop.py` 顶部两段重复读合并为一次 app_config 读取；`registry.py` mcp 段改走 app_config；`model_manager.py` 等历史直读点本次未动（读同文件同值，行为一致，后续增量迁移）

**F `config/dfecrab.json`**
- `react` 段新增 `answer_gate: true` / `answer_gate_max_retry: 1` / `answer_gate_timeout: 60` / `markdown_output_hint: false`；`mcp` 段新增 `exclude_write_tools: true`；react/mcp 段新增 `_note` 字段说明键（JSON 标准不支持行尾注释，以 `_` 前缀键承载，读取方自动忽略）

**G 验证**
- py_compile 全部改动文件 + lint 0 + import 冒烟（app_config 剔除 `_note`、常量取值正确）+ JSON 校验通过
- 单元冒烟：assessor.verify 三分支（fail/pass/无适配器放行）；`_is_mcp_write_tool_schema` 写/只读四例判定；`_zk_instance_agent_id` 待部署后在线回归
- 行为验收（部署后）：不传 agent_id 问"制定F19地王一线的转电预案"→ Manager 决策 `target_agent=dfecrab`；日志出现 `[AnswerGate]` 与 `[ToolRegistry] 已过滤写工具`；`[ChatRequest]`/agent 列表无 `default` 残留
- 前端对接文档：对话接口 v5.2、Agent管理 v4.10（均零改动，1 项 Markdown 渲染待前端确认）

**需部署文件（服务器 172.20.51.153）**
- 新增：`src/config/app_config.py`
- 替换：`src/agent/loop.py`、`src/agent/multi/assessor.py`、`src/skill/registry.py`、`src/gateway/grpc_server.py`、`src/task/manager_agent.py`、`services/agent_service/agent_service_grpc.py`、`agents/manager_agent/config.json`、`config/dfecrab.json`
- 重启：网关 + 全部 worker agent（让 dfecrab 按 `worker_agent` 重新注册）；建议随后清理 ZK 遗留 `default_agent`/`default_*` 孤儿节点

---

## 2026-09-07（收尾：清理(1-5)+优化(6-8)+配置收敛 汇总 + 前端对接文档 v5.1）

**性质**：本日批次 1-8 + 配置收敛的收尾汇总。各批明细见下方对应条目（批次 1-8 各自独立成条，含改动/验证/部署清单），此处不再重复。本条目仅补充本次收尾动作。

**收尾动作**
- 代码自查：`loop.py` 无旧截断残留、`context_engine` 仅剩兼容双读、插件体系残留为零（grep 证据）——无重复/冲突
- `src/agent/loop.py`、`grpc_server.py`、`think.py` 复编译 + import 冒烟 + `test_api_base_normalize` 9 passed
- 前端文档：《前端对接文档_对话接口.md》新增 **v5.1（2026-09-07）**——跨轮上下文增强/工具结果多现场动态预算/MCP instructions/`/api/plugins` 下线，均标注**前端零改动**（前端对比用，勿删旧版记录）

---

## 2026-09-07（批次 8 + 配置收敛：工具结果去包装/动态预算 + context_engine 并入 react）

**性质**：① 批次 8——工具结果回填给模型前**展平四层协议包装**（模型只见服务端数据本体，前端展示不变），并把固定 12000 截断改为**按当前模型窗口动态预算**（多现场自适应：昆明 16K / 烟台 32K / 深圳 100K+，现场差异只在 provider 的 context_length，代码零分支）；② 配置收敛——`context_engine` 段并入 `react`（对话上下文工程一处管理），删除 `think_config` 遗留占位词 `"思考标签"`。mcp-server.js 不动（SOP 不写进服务端）。

**A `src/agent/loop.py`**
- 新增 `_flatten_tool_result`：剥 `ToolResult → execute_cached_tool{status,content,server,tool} → MCP result{content[].text/structuredContent}`；isError 信号在替换前取出并保留为 `_isError`
- 新增 `_tool_result_budget(ctx)`（= min(max_tool_result_chars, 窗口×0.25)）、`_tool_round_budget(ctx)`（= 窗口×0.4，单轮事前配额）
- run()：回填改为「展平 → 三层预算截断（单条基础 / 轮内剩余配额 / 剩余上下文空间，token 估算每轮缓存一次）」；`_tool_result_budget_ratio`/`_tool_round_budget_ratio` 读取
- 段合并兼容：AutoCompact 阈值/保留轮数先读 `react` 段、回落旧 `context_engine` 段（下个大版本移除回落）

**B `src/gateway/grpc_server.py`**
- `_context_engine_conf`：改读 `react` 段（回落旧 `context_engine`），docstring 同步

**C `config/dfecrab.json`**
- `context_engine` 并入 `react`（`auto_compact_threshold`/`compact_keep_recent`）
- `react` 新增 `tool_result_budget_ratio: 0.25` / `tool_round_budget_ratio: 0.4`
- `think_config.end_tags` 移除占位词 `"思考标签"`

**D `src/agent/llm/think.py`**
- 默认 `end_tags` 同步移除 `"思考标签"` 占位词（配置/默认一致）

**E 验证**
- `py_compile` + JSON 校验 + import 冒烟通过；lint 0；`test_api_base_normalize` 9 passed
- 行为断言（脚本已自删）：预算 16384→4096 / 32768→8192 / 100000→12000；展平三分支（成功→structuredContent 本体 / isError→`_isError` 保留 / 无 structured→text 解析）；轮内配额 3 条 = 4096/2457/1500

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/agent/loop.py`、`src/gateway/grpc_server.py`、`src/agent/llm/think.py`
- `config/dfecrab.json`：**用迁移脚本原地改，勿整文件覆盖**（见下），或至少保证 react 段含新键且 context_engine 删除
  ```bash
  python3 - <<'EOF'
  import json
  p = 'config/dfecrab.json'
  d = json.load(open(p, encoding='utf-8'))
  ce = d.pop('context_engine', {})
  react = d.setdefault('react', {})
  for k in ('auto_compact_threshold', 'compact_keep_recent'):
      if k in ce and k not in react:
          react[k] = ce[k]
  react.setdefault('tool_result_budget_ratio', 0.25)
  react.setdefault('tool_round_budget_ratio', 0.4)
  tags = d.get('think_config', {}).get('end_tags', [])
  d['think_config']['end_tags'] = [t for t in tags if t != '思考标签']
  json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
  print('ok')
  EOF
  ```
- 重启网关；兼容双读保证：未迁移的旧配置（context_engine）也能正常运行

---

## 2026-09-07（优化批次 7：MCP instructions 通道 + 配网查询 SOP，对齐 LibreChat serverInstructions）

**性质**：把 LibreChat 的 `serverInstructions: true` 机制引入 DFECrab——MCP 服务端在 `initialize` 声明的 `instructions`（工具调用 SOP）会被注入 agent 系统提示，让本地弱模型（Qwen3-32B-Q4）也遵守"先 `search_feeders` 定位唯一 file → 再 `get_feeder_topology` 取拓扑"的收敛链，而不是一次 `get_feeder_topology` 撞 254 条模糊就让用户去选。

**A `src/mcp/http_client.py`**
- `initialize()` 握手后记录服务端声明的 `instructions`（`result.instructions`）到 `self._instructions`
- 新增 `get_instructions()`：返回服务端 instructions（未声明返回空串）

**B `src/mcp/__init__.py`**
- `MCPClient` 新增 `get_server_instructions(name)`：取 client → 触发 initialize → 返回 instructions；任何异常返回空串不抛（Gateway 对话链路安全）

**C `src/gateway/grpc_server.py`**
- `_react_chat_generator`：当请求显式传了 `mcp_servers` 时，逐个取其 instructions，以 `【{server} MCP 使用须知】` 分段拼进 `system_prompt`（在 Manager 参数注入之后）——仅在装配 MCP 的对话生效，零行为影响

**D `mcp_servers/blackxml-topology-mcp/tools/mcp-server.js`**
- 服务端 `instructions` 升级为**配网查询 SOP**（保留原有中文图表规范）：
  1. 查馈线前先 `search_feeders`（station + feeder）精确定位，多候选时结合上下文自动收敛，**不要直接把候选清单丢给用户**
  2. 锁定后按其 `file` 调 `get_feeder_topology(file=...)`
  3. 开关评估：先取拓扑拿开关名，再用 `assess_switch_operation`/`simulate_operations` 推演并汇报影响范围/用户数
  4. 仅当上下文确实无法推断目标时才向用户确认一次
- 注：`http-mcp-server.js` 是 wrapper（spawn mcp-server.js），instructions 随子进程生效，部署替换后重启 MCP 服务即可

**E 验证**
- `py_compile` + import 冒烟通过；`get_mcp_client().get_server_instructions` 方法存在；lint 0；`tests/test_api_base_normalize.py` 9 passed
- JS 文件改动仅为字符串内容（引号配对未破坏结构），本机无 node 无法 `--check`，服务器 MCP 服务启动时自动解析验证

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/mcp/http_client.py`、`src/mcp/__init__.py`、`src/gateway/grpc_server.py`、`mcp_servers/blackxml-topology-mcp/tools/mcp-server.js`
- 部署后重启网关 + 重启 blackxml_topology MCP 服务（`dfecrab restart-mcp` 或等价），新指令随 initialize 返回
- 端到端验收：对话传 `mcp:["blackxml_topology"]` 问"制定F19地王一线的转电预案"，观察模型先走 `search_feeders` 再 `get_feeder_topology` 的调用链

---

## 2026-09-07（优化批次 6：HistoryFilter 持续上下文修复，治跨轮追问断链）

**性质**：对齐 LibreChat「完整对话持续在上下文」语义，修复 HistoryFilter 的硬 bug——旧 L1 逻辑"当前消息不含查历史指代词 → 丢弃全部历史"，导致省略/指代式追问（实测："请你制定F19地王一线的转电预案" → 用户补充"红岭变电站的"）完全接不住上一轮任务锚点（该场景旧逻辑过滤结果为 **0 条**）。

**A `src/session/history.py`**
- 过滤语义重写：**默认保留最近 `DEFAULT_RECENT_KEEP=6` 条完整上下文**（user + assistant 都保留）；L1 仅用于判断"是否显式查历史"（含这些/刚才/上次…），命中时才做 L3 语义**扩展**（把更早相关历史并入），不再有"丢弃全部"分支
- L3 语义判断覆盖 role 扩展：不再 `role != "user"` 跳过，assistant 追问同样参与相关性判断（assistant 的"请补充变电站"正是承接追问的关键）
- 结果 = 语义相关 ∪ 最近窗口，原顺序去重返回

**B `src/gateway/grpc_server.py`**
- ReAct 历史注入条数：`_hist_num` `2/4` → `4/6`（普通场景注入最近 6 条完整轮，充分使用 HistoryFilter 带回的上下文；AutoCompact 触发后仍收 4 条，摘要承担老上下文）

**C 验证**
- 行为验证（复现真实场景）：history 含 [F16老二线问题/回答/F19预案/追问(请补充变电站)/红岭变电站的] → `filter_history("红岭变电站的", …)` 现保留 **5/5 条含 assistant**（旧逻辑 0 条）
- `py_compile` + import 冒烟通过；lint 0；`tests/test_api_base_normalize.py` 9 passed
- 后续端到端验收：第 2 轮"红岭变电站的"应能结合 F19 任务直接 `get_feeder_topology(station=红岭变电站, feeder=F19地王一线)` 闭环

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/session/history.py`、`src/gateway/grpc_server.py`，重启网关后生效（新对话即用新上下文策略）

---

## 2026-09-07（代码清理批次 5：memory 统一化收尾——删半成品件 + 门面收口）

**性质**：memory 层收尾。**先核实**：当前 `long_term.MemoryManager` 是 15KB 真实现（非代码地图旧报告所称"4 行空壳"），且被 `grpc_server`（plan 经验沉淀/成功模式/教训写入）、`memory_handler`（Agent 记忆 API）、`unified.modules.agent_module` 使用——真实架构已是「单一门面 `UnifiedMemoryManager` + 分层引擎（Global/LongTerm/User/Search）」，非"三套并行"。本次删除**确实零引用的半成品件**并收口门面导出。

**A 删除 · 零引用半成品**
- `src/memory/config.py`（`MemoryConfigManager`，176 行）：配置实际由 `types.MemoryConfig` 承载，此管理器全仓零引用
- `src/memory/storage/`（`base_adapter`/`filesystem_adapter`/`json_adapter`）：未作为存储层接入（Unified 直接文件读写），零引用
- `src/memory/utils/`（仅空 `__init__`）

**B 收口 · `src/memory/__init__.py`**
- 重写 docstring：明确「单一门面 + 分层引擎」架构与统一入口建议（`from src.memory import UnifiedMemoryManager`）
- 移除过时的 `LongTermMemoryManager` 别名（全仓 grep 零引用，移除避免"第三套管理器"误解）；保留 `UnifiedMemoryManager` / `get_global_memory_manager` / `MemoryConfig` 懒导出

**C 去留结论（记录在案）**
- `long_term.MemoryManager` **保留**：作为 Unified 的 Agent 长期记忆引擎（grpc/memory_handler/unified.modules 在用），只是不再经 `__init__` 重复导出别名
- `modules/`（agent/global/base）在用，保留

**D 验证**
- `compileall src/memory` 通过；import 冒烟通过（`src.memory` 门面 + unified_manager/long_term/global_manager/user_manager/modules + grpc_server + memory_handler）
- 全仓 grep（`memory.config/storage/utils`/`LongTermMemoryManager`/`MemoryConfigManager`）零命中
- `tests/test_api_base_normalize.py` 9 passed

**需部署文件（服务器 172.20.51.153）**
- 删除（服务器同步）：`src/memory/config.py`、`src/memory/storage/`、`src/memory/utils/`
- 替换：`src/memory/__init__.py`

---

## 2026-09-07（代码清理批次 4：去插件系统，收敛到 skills 单一工具体系）

**性质**：执行四分类框架「③ 未接线」的 A 路线（对齐 LibreChat 单一工具体系先例）——顶层 `plugins/`（35 目录）与 `src/plugin_framework/` 整套插件抽象退役，工具统一由 `skills/`（SkillLoader 扫描）+ MCP 承载。

**事实依据**：顶层 `plugins/` 运行时**零加载**——SkillLoader 只扫 `skills/`；PluginLoader 硬编码只注册 `DFEcrabAgentPlugin` 不扫目录；`.dfecrab-plugin`/`commands/` 无任何消费方；`grpc_server` 的 `/api/plugins` 接口查询的 PluginRegistry 永远只有 1 项。35 目录中 ≥19 个 execute.py 与 `skills/` 同名重复（10 个字节一致）。

**A 删除**
- 顶层 `plugins/`（整目录，35 个子目录）：技能 execute.py 副本（正本在 `skills/`）+ `.dfecrab-plugin` 命令插件目录 + `self-improving-agent`（已损坏副本）+ 空容器 `builtin/`/`thirdparty/`
- `src/plugin_framework/`（4 文件：`__init__`/`agent`/`loader`/`registry`）

**B 代码清理（引用方）**
- `src/gateway/grpc_server.py`：移除 import、`_plugin_loader`/`_agent_plugin` 字段、initialize 插件初始化块、`/api/plugins` 三条路由、stop 关闭块、`_handle_list_plugins`/`_handle_get_plugin`/`_handle_reload_plugin` 三个 handler、`_handle_list_services` 的插件分支
- `scripts/check_system_health.py`：删除 `check_plugin` 检查项（函数+常量+注册）与 gateway 初始化 snippet 的 plugin loader Step
- `scripts/verify_url_prefix_deploy.py`：`/api/plugins` 从检查端点列表移除
- `docs/API接口文档.md`：移除 plugins 三行接口

**C 验证**
- `py_compile` + import 冒烟（grpc_server/skill.registry/agent.loop）通过；lint 0；`tests/test_api_base_normalize.py` 9 passed
- 全仓 grep（py）`plugin_framework/plugin_loader/get_plugin_registry/DFEcrabAgentPlugin/plugins/` 零命中（tui/docs 除外）
- 确认无外部调用方：tui 前端不调 `/api/plugins`；残留命中仅为 docs 历史文档与 LibreChat 自带 branding（无关）

**需部署文件（服务器 172.20.51.153）**
- 删除（服务器同步）：顶层 `plugins/`、`src/plugin_framework/`
- 替换：`src/gateway/grpc_server.py`、`scripts/check_system_health.py`、`scripts/verify_url_prefix_deploy.py`
- 重启网关后 `/api/plugins` 返回 404 属预期

---

## 2026-09-07（代码清理批次 3：失效技能与命名事故空目录清理）

**性质**：四分类框架的「④ 失效待修」+ 命名事故清理——两个技能已损坏且**无任何 agent 启用**（`agents/*/tools.json` 零命中），按"不修（被取代/与自研重叠）"删除；同时清 `docs/` 下两个命名事故空目录。

**A 删除 · 失效技能（实跑验证确认崩）**
- `skills/planner/`：实跑 `execute('部署任务')` → `'TaskPlanner' object has no attribute 'create_plan'`（依赖的 `src.agent.planner` API 已变；规划能力由 grpc 内置 Plan 模式承接）；无 agent 启用
- `skills/self-improving-agent/`（12 项含 `src/{agent,hooks,memory}.py`）：import 3 个 src 重构后不存在的符号（`SelfImprovingAgent`/`src.hooks.HookManager`/`LearningMemory`），调用即崩；能力与自研记忆体系重叠；无 agent 启用
- 注：`plugins/self-improving-agent/`（顶层 plugins 副本，含 try/except 降级不会崩）**保留**——属「③ 未接线」资产，随批次 4（plugins 收敛）统一处理

**B 删除 · 命名事故空目录**
- `docs/{设计说明书，用户手册，测试报告，验收手册}/`（全角/半角逗号命名事故，空）
- `docs/test/`（空）

**C 验证**
- `import grpc_server / skill.registry / agent.planner` 冒烟通过；`tests/test_api_base_normalize.py` 9 passed
- 残留 grep 命中仅剩顶层 `plugins/self-improving-agent/`（保留待批次 4）
- 核对保留项：`docs/测试报告`、`docs/验收手册`、`docs/design`、`docs/plugins` 均有内容，未动

**需部署文件（服务器 172.20.51.153）**
- 删除（服务器同步）：`skills/planner/`、`skills/self-improving-agent/`、`docs/{设计说明书，用户手册，测试报告，验收手册}/`、`docs/test/`

---

## 2026-09-07（代码清理批次 2：legacy 网关下线，~122KB）

**性质**：按四分类框架，legacy 属「已取代」——部署唯一入口 `./dfecrab start` → `scripts/start_gateway_grpc.py` → `GatewayV2GRPC`（gRPC）全链零 plugin 依赖；`--mode plugin` 仅存在于无人使用的 `python -m src gateway` 路径。整组下线。

**A 删除**
- `src/gateway/legacy.py`（103.6KB，HTTP/WS 旧网关）：外部仅 `__main__.py` plugin 分支引用
- `src/agent/multi/help_seeker.py`（12.6KB）：仅 legacy 调用（loop.py 只剩注释）
- `src/monitoring/hooks.py`（2.8KB）：仅 legacy 用 `get_hook_manager`
- `src/services/service_registry.py`：仅 legacy + `__main__` plugin 分支
- `src/plugins/`（4 文件兼容层）：仅 legacy.py:238 引用

**B 连带修改**
- `src/__main__.py`：移除 `--mode plugin` 参数与分支，`python -m src gateway` 恒走 gRPC（GatewayV2GRPC）
- `src/agent/multi/__init__.py`：移除 help_seeker 导出（保留 confirmation/assessor）
- `src/monitoring/__init__.py`：hooks 删除后清空导出（invariants 经 `src.monitoring.invariants` 直接模块引用，不受影响）

**C 白名单确认（被 legacy 引用但保留）**
`reflection/`、`monitoring/invariants.py`、`gateway/plan_router.py`、`agent/multi/assessor.py`、`agent/multi/confirmation.py`、`agent/llm/{retry,fallback}.py`、`plugin_framework/`（grpc_server:48 在用）

**D 验证**
- `py_compile` 通过；`import __main__/grpc_server/agent.multi/loop/monitoring.invariants/plugin_framework.loader/plan_router/reflection` 冒烟通过
- 全仓 grep 残留（`legacy/help_seeker/src.plugins/service_registry/get_hook_manager/monitoring.hooks`）零命中
- `tests/test_api_base_normalize.py` **9 passed**

**需部署文件（服务器 172.20.51.153）**
- 删除（服务器同步）：`src/gateway/legacy.py`、`src/agent/multi/help_seeker.py`、`src/monitoring/hooks.py`、`src/services/service_registry.py`、`src/plugins/`
- 替换：`src/__main__.py`、`src/agent/multi/__init__.py`、`src/monitoring/__init__.py`

---

## 2026-09-07（代码清理批次 1：取代/真死代码 + 僵尸测试，按四分类框架执行）

**性质**：按「已取代 / 真死 / 未接线（保留待接）/ 失效」四分类框架执行第一批清理——只删**有明确继任者**与**零引用且无规划**的代码，不动「未接线」资产（顶层 plugins/、memory 重构件等后续单独处理）。

**A 删除 · 已取代（有继任者在跑）**
- `src/task/backup/`（6 文件，~40KB）：`src/task` 现行版在跑，此为备份副本，全仓零引用
- `src/agent/multi/agent_group.py`（17.6KB）：零外部引用，真身在 `src/task/agent_group.py`（`task_v2_handler` 在用）
- `src/monitoring/metrics.py`（4KB）：`get_tracker`/`PerformanceTracker`/`LLMMetrics` 全仓无消费方 → 连带清理 `monitoring/__init__.py` 导出（保留 hooks/invariants）

**B 删除 · 僵尸测试/示例（import 即崩）**
- `tests/plugins/`（8 文件）、`tests/core/test_kernel.py`、`tests/test_full_integration.py`：import 不存在的旧版 `plugin_framework.base/builtin` 与 `context_usage.collect_context_usage` 等
- `examples/hello_plugin/`：同引旧 API
- 空目录 `src/memory/v4/`、`tests/plugins/`、`src/task/backup/`、`examples/`

**C 验证**
- `py_compile` 关键文件通过；`import grpc_server/legacy/task_manager/agent.multi/loop` 冒烟通过；全仓 grep 残留（`metrics/get_tracker/agent_group/backup/hello_plugin`）零命中
- `tests/test_api_base_normalize.py` **9 passed**（零回归）
- 顺手发现 2 个既有失效测试（非本次范围，列入后续批次）：`tests/test_permissions.py`（引用不存在 `src.core.security`）、`tests/memory/test_unified_memory.py`（缺 pytest-asyncio 环境）

**需部署文件（服务器 172.20.51.153）**
- 删除（服务器同步）：`src/task/backup/`、`src/agent/multi/agent_group.py`、`src/monitoring/metrics.py`
- 替换：`src/monitoring/__init__.py`（去掉 metrics 导出）

---

## 2026-09-04（修复 GET /api/models 未返回 temperature / max_tokens / timeout）

**性质**：v4.5 契约声明 `GET /api/models` 每个 provider 返回 `temperature` / `max_tokens` / `timeout`（供前端编辑弹窗回填），但实际接口返回的 providers 仅含 10 个固定字段，三个生成参数在接口层组装时被过滤丢失（数据源 `get_all_providers()` 早已包含）。本次在 HTTP 响应组装处透传补齐，与《前端对接文档_模型管理.md》v4.5 一致。

**A 代码**
- `src/gateway/handlers/model_handler.py`：`list_models` 组装 `providers` 时补透传 `temperature`（默认 0.7）/ `max_tokens`（默认 2048）/ `timeout`（默认 120），取值沿用 `get_all_providers()` 的实际配置值（本地实测 `qwen3_32b_q4` → `0.7 / 8192 / 300`）

**B 验证**
- lint 0 错误；本地 `get_all_providers()` 字段校验通过
- 部署后：`curl http://172.20.51.153:6789/api/models -H "X-User-Id: admin"`，每个 provider 应含 `temperature/max_tokens/timeout`

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/gateway/handlers/model_handler.py`（可与 `src/gateway/http/server.py` 一并部署），重启网关后生效

---

## 2026-09-04（alert 短期会话：type=alert 不落库历史，解决会话列表刷屏）

**性质**：告警研判调用 `POST /api/v2/chat/stream` 新增 `type: "alert"` 参数——强制走 alert_judge 三件套专属链路，且跳过 session_mgr 全套（不创建会话 / 不写 user+assistant 消息 / 不持久化），SSE 事件流照常透传、但不进入左侧会话列表。不传 `type` 的调用行为零变化（向后兼容），`mcp` 参数照常有效。

**A 代码**
- `src/gateway/grpc_server.py` `_handle_chat_stream`：提取 `request_type = body.get("type", "chat")`；`type=="alert"` 时跳过 `_run_chat_pipeline`，改走新增的 `_alert_ephemeral_stream`
- `src/gateway/grpc_server.py` 新增 `_alert_ephemeral_stream`：yield `meta`（`ephemeral=true`、`session_id=""`）→ 透传 `_alert_judge_direct_react` 事件流（异常兜底 error 事件）

**B 文档**
- 《前端对接文档_对话接口.md》：§4 参数表新增 `type` 行 + 顶部更新记录 v4.9（ephemeral 语义、历史不可回看说明）

**需部署文件**
- `src/gateway/grpc_server.py`
- 《前端对接文档_对话接口.md》（文档，前端参考）

---

## 2026-09-04（ReAct 上下文工程修复：思考重启 + 执行超时）

**性质**：参考成熟平台（LibreChat `maxToolResultChars` / `recursionLimit` / LangGraph State、Claude Code AutoCompact）修复真实运行案例「查询 F16老二线接地跳闸影响用户」暴露的两个问题——工具结果无截断全量回填 + “超 12 条丢最老消息”导致模型失忆（思考每轮重启）、大输入撞 60s 硬超时。

**A 工具结果智能截断（对标 LibreChat maxToolResultChars）**
- `src/agent/loop.py`：工具结果回填前超长截断。新增 `_smart_truncate_json_text`：可解析 JSON 保留结构/关键字段（stats），超大数组保留前 50 项，超长字符串截断；不可解析退化为硬切。上限 `react.max_tool_result_chars`（默认 12000 字符）

**B 上下文裁剪保锚点（对标 LangGraph State 完整历史）**
- `src/agent/loop.py`：替换原“超 12 条丢最老非 system”为“**system 与第一条 user（原始任务）永不丢**，优先丢最老 tool 结果、其次中间轮 assistant”，避免思考重启式失忆；上限 `react.context_msg_limit`（默认 16 条）

**C ReAct 内 AutoCompact（对标 Claude Code AutoCompact / LibreChat summarization）**
- `src/agent/loop.py`：每轮开头若估算占用超 `context_engine.auto_compact_threshold`（默认 0.85），把『原始任务之后、最近 `compact_keep_recent` 轮之前』的旧轮用 LLM 压缩为一条“先前调查进展”摘要消息替换（每请求至多一次，失败静默降级）

**D 宽松轮次 + 超时配置化**
- `config/dfecrab.json`：`agent_defaults.max_iterations` 3→8（对齐 LibreChat recursionLimit 哲学）；新增 `agent_defaults.llm_timeout: 180`（单轮 LLM 超时，agent 级可覆盖）
- `src/agent/agent_config.py`：AgentConfig 支持 `llm_timeout`（默认 180，agent 级 config.json 可覆盖）
- `src/agent/loop.py`：单轮 60s / 外层 300s 硬编码 → 读 `llm_timeout`（单轮 180s、外层 max(单轮×3, 300s)）

**E 参数收敛**
- `config/dfecrab.json`：`qwen3_32b_q4.max_tokens` 32768→8192

**需部署文件（服务器 172.20.51.153）**
- `config/dfecrab.json`、`src/agent/loop.py`、`src/agent/agent_config.py`
- ⚠️ 部署后建议 `POST /api/models/qwen3_32b_q4/discover` 校准 `context_length` 为 vLLM 真实窗口
- 验证脚本：`scripts/verify_react_context_arch.py`（部署后运行，全过自动删除，结果存 `docs/verify_results/`）

**P2（同日，已实现）**
- `src/agent/loop.py`：`_smart_truncate_json_text` 升级为**语义投影**——长列表元素只保留标识/状态/数值字段（如开关保留 `id/name/closed/current.amp`），实测 1.5MB 拓扑 JSON 压缩至约 6KB，仍保留 `stats` 统计与关键电流字段，去掉长文本
- `src/agent/loop.py`：新增 `_defer_tools_schema`（对标 LibreChat deferred_tools，**默认关闭**）：工具总数 > `react.deferred_keep` 阈值时按「用户消息 2-gram × 工具名/描述」重叠打分，只下发 top `react.deferred_keep`(15) 个工具，剪枝列表打日志便于观察误剪；`run()` 在装配 tools_schema 后应用
- `config/dfecrab.json`：`react` 段新增 `deferred_tools: false` / `deferred_keep: 15`（默认关闭，行为零变化；如需试点开启即可）
- 影响：defer 默认关 + 截断仅作用于超长回填 → 对现有全量行为无回归

---

## 2026-09-04（HTTP 接口新增可选 `/dfecrab` URL 前缀，新旧地址完全兼容）

**性质**：服务端路由增强——为 6789 网关**全部** HTTP 接口新增可选的 `/dfecrab` 命名空间前缀（`/dfecrab/api/...`）；旧地址 `/api/...` 完全不变、继续可用。前端**零改动**即可继续使用；后续外部接入可统一走带命名空间的新地址，方便与其它系统在代理层区分。对齐成熟平台"网关统一命名空间"的惯例。

**A 变更**
- `src/gateway/http/server.py`：新增模块级常量 `DFECRAB_URL_PREFIX = "/dfecrab"` 与 `_normalize_api_path()`（请求以 `/dfecrab` 开头时剥离该段后再匹配路由表）；`_handle_request` 在路由遍历前对 `request.path` 归一化；`start()` 增加前缀启用日志提示
- 机制层面**一次性覆盖全部路由**（约 100 条 `/api/*`：grpc_server / legacy 手动注册 + FastAPI 自动注册的 task_router），无需逐条改路径、不产生重复注册
- WebSocket（6790）握手不校验请求路径，天然兼容，无改动

**B 验证**
- `scripts/verify_url_prefix_deploy.py`（新增）：本地文件校验（server.py 已含新代码）+ 网关各模块只读接口在「旧路径 `/api/...`」与「新路径 `/dfecrab/api/...`」下逐一对比，验证前缀剥离生效、新旧等价；执行成功且全过时自删（`--keep` 保留），结果存 `docs/verify_results/`
- 执行前置条件：先部署 `src/gateway/http/server.py` 并重启网关；服务器仍为旧代码时脚本会明确提示"未部署"并保留脚本供重跑

**C 文档**
- 《前端对接文档_URL前缀兼容说明.md》（新增，v4.9 · 2026-09-04）：新旧地址对照、兼容行为、前端行动项（无需改动）

**需部署文件（服务器 172.20.51.153）**
- 替换：`src/gateway/http/server.py`（整文件覆盖，其余文件无需改动）
- 重启网关后运行：`python scripts/verify_url_prefix_deploy.py --base http://172.20.51.153:6789`
- 冒烟验证：`curl http://172.20.51.153:6789/dfecrab/health` 与 `curl http://172.20.51.153:6789/health` 均应返回 200 healthy

---

## 2026-09-03（think 配置收敛 + 全局思考配置生效修复 + 模型列表补参数字段）

**性质**：对齐成熟平台（vLLM/DeepSeek 标准 reasoning 字段 + Dify 单一配置点）——思考解析由“每模型重复配置”收敛为**全局一份**；修复全局 `think_config` 从未生效的 bug；模型列表接口补模型级参数供前端编辑弹窗回填。

- `config/dfecrab.json`：删除全部模型级 `think_config`（`qwen3_32b` 的是坏配置——`end_tags` 用“思考标签”占位词会导致 `<think>` 拆分失败；`qwen3_32b_q4` 与全局冗余）；顶层 `think_config` 删死字段 `think_mode`（无代码消费）；思考解析统一由顶层一份管理，保留模型级按需覆盖能力
- `src/agent/llm/think.py`：修复 `_cfg.config_data` → `_cfg.raw_config`（属性名写错导致读全局配置的异常被吞、**全局 `think_config` 从未真正生效**，一直回退代码默认）
- `src/services/model_manager.py`：`get_all_providers`（`GET /api/models` 数据源）补 `temperature` / `max_tokens` / `timeout` 字段，供前端编辑弹窗回填当前值并配置“生成温度”

**文档**
- 《前端对接文档_模型管理.md》：更新记录 v4.5（`GET /api/models` 新增 3 字段、编辑弹窗需加“生成温度”并回填“最大输出”）

**需部署文件（服务器 172.20.51.153）**
- `src/agent/llm/think.py`、`src/services/model_manager.py`：整文件覆盖 + 重启
- `config/dfecrab.json`：⚠️ 服务器可能有现场参数值，请原地执行以下命令清理（勿整文件覆盖）：
  ```bash
  python3 - <<'EOF'
  import json
  p = 'config/dfecrab.json'
  d = json.load(open(p, encoding='utf-8'))
  for m in d['model_providers'].values():
      m.pop('think_config', None)
  d.get('think_config', {}).pop('think_mode', None)
  json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
  print('ok')
  EOF
  ```
- 重启后 `GET /api/models` 应看到每个 provider 含 `temperature/max_tokens/timeout`

---

## 2026-09-03（alert_judge 告警研判链路迁移至现场标准三件套）

**性质**：把 DFEcrab 内 alert_judge 专属研判逻辑（自研 `src/skill/alert_react_pipeline.py` 500+ 行 + MCP 内重复工具实现约 150 行）整体替换为现场标准三件套（`config.py` / `tools.py` / `agent_caller2.py`），对外事件协议与触发方式零变化；现场更新逻辑时直接覆盖 `src/alert_judge/` 三件套并补少量 import diff 即可，便于与标准文件逐行对比维护。

**A 结构**
- `src/alert_judge/`（新增包）：标准三件套工作副本。`config.py` 与现场标准 0 差异；`tools.py` 仅去无用 `tavily` 导入 + 包内相对导入（2 行）；`agent_caller2.py` 仅相对导入 + `sse_event_generator` 增 `correlation_id` 可选参数（4 行），保证 grpc_server 透传的关联 ID 一致
- `mcp_servers/mcp_alert_judge.py`（重写，约 90 行）：只保留「启动 + 接入 + 适配」——MCP 服务注册标准 `tools.py` 的 4 工具（fastmcp 在 `main()` 内按需引入，模块被 import 供 `run()` 时不依赖 fastmcp）；`run()` 适配器把标准 `sse_event_generator` 的 SSE 文本还原为 dict 事件流
- `src/skill/alert_react_pipeline.py`（删除，519 行旧逻辑退役）
- `src/gateway/grpc_server.py`：alert_judge 链路 import 由 `src.skill.alert_react_pipeline.run` 改为 `mcp_servers.mcp_alert_judge.run`（懒加载，位置不变）

**B 行为变化（对前端可见，详见《对话接口.md》v4.8）**
- 新增「事故总」短路：`alert_content` 含"事故总"→ 跳过 LLM，延迟约 2s 后按固定文案流式输出（thought → task_complete → task_finish），结论固定"事故总信号 → 正常信号"
- 两阶段研判：规则预分类（操作告警 = 含线路 + 正向词 事故分闸/合闸/动作 且不含 负向词 母线失压/全站失压/重合闸/母线馈线保护）→ 操作告警 / 非操作告警分别走不同微调模型
- 工具执行改为标准 `tools.py` 直连后端 HTTP（不再经 MCP 中转）；Observation 格式化（操作票 / 调度日志 / 台账）按标准逻辑组装后回传模型
- 事件协议不变：`thought` / `chat_stream` / `tool_start` / `tool_end` / `task_complete` / `task_finish` / `error`

**C 清理冗余**
- 删除 MCP 服务内重复的 4 工具实现（`_post_json` / `_normalize_station_name` / 批量查询分支等）
- 删除旧 pipeline 的 `_StreamThoughtSplitter` / MCP 执行包装 / 重复 `TOOL_NAME_MAPPING` / `_fix_mojibake` 等
- 根目录 `config.py` / `tools.py` / `agent_caller2.py` 保留为**标准参考副本**（只读对照、不参与运行），运行副本以 `src/alert_judge/` 为准

**D 文档**
- 《前端对接文档_对话接口.md》更新记录 v4.8（协议不变、行为差异说明），并修正 §6.5 中已迁移的 `alert_react_pipeline` 旧描述

**E 验证**
- `scripts/verify_alert_judge_arch.py`（新增）：本地文件/三件套 import 校验 + alert_judge 专属链路（普通告警 + 事故总短路固定文案）+ MCP 服务列表 + Agent 列表 + 会话清理，执行后自删，结果存 `docs/verify_results/`

**需部署文件（服务器 172.20.51.153）**
- 新增：`src/alert_judge/__init__.py`、`src/alert_judge/config.py`（⚠️ 部署前需按该机实际可达地址配置 `DEEPSEEK_BASE_URL`/`DEEPSEEK_MODEL`/`DEEPSEEK_MODEL2` 与 4 个查询服务 URL，默认值为现场标准文件值）、`src/alert_judge/tools.py`、`src/alert_judge/agent_caller2.py`
- 替换：`mcp_servers/mcp_alert_judge.py`、`src/gateway/grpc_server.py`
- 删除（服务器同步）：`src/skill/alert_react_pipeline.py`
- 验证脚本：`scripts/verify_alert_judge_arch.py`（部署完成后运行 `python scripts/verify_alert_judge_arch.py --base http://172.20.51.153:6789`，全过即自动删除，结果存 `docs/verify_results/`）
- 文档：《前端对接文档_对话接口.md》v4.8

---

## 2026-09-03（api_base 容错规范化：误填完整接口地址不再 404）

**性质**：修复深圳现场"配置完整接口地址（如 `http://10.176.174.28:8080/apis/ais-v2/chat/completions`）→ 代码再拼一层 `/chat/completions` → 404 → 模型误判不可达"的故障（网络通但探活失败）。对齐成熟平台（LiteLLM / Dify）"api_base 填根地址 + 框架自动拼端点"的约定，并**对误填完整地址自动容错**（比 Dify/LiteLLM 更宽容，因现场直接手改 json 无 UI 校验）。

**A 新增工具函数（唯一收口）**
- `src/utils/api_base.py`（新增）：`normalize_api_base()`——去空白/尾斜杠、循环剥误填端点后缀（`/chat/completions`、`/completions`、`/embeddings`、`/models`、`/responses`、`/rerank`）、合并重复版本段（`/v1/v1` → `/v1`）；大小写不敏感、幂等（`/v1` 结尾等合法根地址保持不变）、剥离时打日志警告

**B 防线 A（配置源头清洗，主防线）**
- `src/services/model_manager.py`：`_load_config`（手改 dfecrab.json 场景）、`_normalize_provider`（新增模型 CRUD）、`update_provider`（编辑 CRUD）统一清洗 api_base；`_check_alive` 探活前兜底清洗

**C 防线 B（绕过 ModelManager 直接读配置的散点兜底）**
- `src/agent/llm/adapter.py`：`__init__` 清洗（所有 LLM 调用统一走这里）
- `src/knowledge/llm/openai_client.py`：原 `rstrip("/")` 升级为 `normalize_api_base`（清理冗余旧逻辑）
- `src/plugin_framework/agent.py`、`src/knowledge/knowledge_service.py`（直接读 dfecrab.json）
- `src/skill/alert_react_pipeline.py`（env `FINETUNED_BASE_URL` → AsyncOpenAI SDK）
- `src/gateway/grpc_server.py`（display think 独立流）
- `src/gateway/handlers/model_handler.py`（`_check_alive_async`）

**D 探活 404 人话提示**
- `model_handler.py`：探活 POST 404 时 `last_error` 返回可行动提示（提醒 api_base 应填根地址）；GET /models 失败不再直接判 offline，落入 chat 探测兜底（部分网关不支持 /models 属正常）
- `model_manager.py`：`_check_alive` POST 404 打 error 日志带修复指引

**E 验证**
- `tests/test_api_base_normalize.py`（新增）：9 个单测（深圳完整地址回归、昆明 /v1 保持、/v1/v1 合并、双重后缀、大小写、空值、幂等）
- `scripts/verify_api_base_deploy.py`（新增，部署验证用）：本地 normalize/model_manager 冒烟 + `GET /api/models`（探活/规范化）、`GET /api/models/current`、`POST/PUT/DELETE /api/models`（新增/编辑/删除临时模型，校验完整地址剥成根地址、`/v1/v1` 合并为 `/v1`）。在 `172.20.51.153` 网关部署**新代码后**运行 `python scripts/verify_api_base_deploy.py --base http://172.20.51.153:6789`，全过即自动删除，结果存 `docs/verify_results/`。⚠️ 服务器未部署新代码前 CRUD 规范化用例会 FAIL（旧代码原样落盘），属预期

**需部署文件**
- `src/utils/api_base.py`（新增）
- `src/services/model_manager.py`
- `src/agent/llm/adapter.py`
- `src/knowledge/llm/openai_client.py`
- `src/plugin_framework/agent.py`
- `src/knowledge/knowledge_service.py`
- `src/skill/alert_react_pipeline.py`
- `src/gateway/grpc_server.py`
- `src/gateway/handlers/model_handler.py`
- 《前端对接文档_模型管理.md》v4.4（文档，前端参考）

---

## 2026-09-03（昆明技能强制调工具 + 知识库上传/解析/索引修复）

**性质**：① 修复 kunming（及各技能型 Agent）在小模型 auto 模式下"不调技能直接编造数据"；② 修复知识库 docx 解析不全、大文件传不上、上传后须重启才能检索、日志不可见等现场问题；③ 清理已下线死技能 `kunming_theory_qa`。

**A 技能调用强制化（tool_choice 配置化）**
- `grpc_server.py`：删除意图硬编码 `"none" if chat else "auto"`，新增 `_resolve_agent_tool_choice`——agent config.json `tool_choice` 最高优先，否则默认策略 `chat→none / task+有技能→required / 其它→auto`
- `agent_config.py`：既有 `tool_choice` 字段正式接线（原为死配置）
- `loop.py`：`required` 仅约束第 1 轮（防拿结果后仍被强制调工具）；首轮正文缓冲不转发（防"幻觉直答先展示再重试"双重输出）；首轮无工具调用追加"必须先调工具"重试；`required` 不被后端支持(400)时降级 auto+强提示；修复"带 tool_calls 但 finish_reason=stop 被误判为最终回复"（以 tool_calls 为准）
- `agents/kunming/config.json`：`tool_choice: required`；system_prompt 重写为"先 classifier 分类 → 再 api 取数"两步强制流程，明令禁止编造数据
- 新增后端行为影响前端可见性：见《对话接口.md》v4.7 更新记录

**B 知识库修复**
- `document_loader.py`：docx 深度解析（文本框/嵌套表格/合并单元格去重/页眉页脚 + 图片计数）；`print`→`logger`
- `document_processor.py`：短尾块并入前一片不再静默丢弃
- `knowledge_service.py`：上传改"临时文件路径"入参、0 文本/0 切片明确报错；`search()` finally NameError 修复；索引重建完成后**内存热刷新**（无需重启即可检索新文档）；`_load_llm_config` 路径锚定
- `paths.py`（新增）：`PROJECT_ROOT/KNOWLEDGE_BASE/INDEX_DIR/LLM_CONFIG_FILE`，消除 CWD 依赖；`document_repo.py`、`vector_store.py`（新增 `load_default_vector_store`）、`knowledge_qa.py`、`knowledge_search.py` 统一锚定并消除重复加载逻辑
- `knowledge_api.py`：补 logging 配置（此前 src.knowledge 日志全被吞）；上传改**流式分块落盘**（防 OOM）+ 大小上限配置化（`gateway.yaml knowledge.upload_max_mb` 默认 50MB），超限 413
- `port_loader.py`：新增 `knowledge_upload_max_mb` 读取函数

**C 死技能清理（kunming_theory_qa）**
- 删除 `skills/kunming_theory_qa/`；`agents/kunming/tools.json`、`agents_index.json`、`registry.py` 不可替代工具对同步移除
- `kunming_classifier`：类别 14（理论题）移除，未命中兜底改类别 5（其他对话）——execute.py / SKILL.md / _meta.json 同步
- legacy worker `services/agent_service/agent_service_grpc.py`：删除引用已删技能的类别 14 理论题分支与 `VALID_CATEGORIES`/默认分类修正（14→5），消除部署后崩溃隐患

**D 文档**
- 《对话接口.md》更新记录 v4.7、《知识库.md》更新记录 v1.3.0（字段/状态/413/热刷新说明）

**E 验证**
- `scripts/verify_kb_kunming_20260903.py`（新增）：本地配置校验 + 网关 kunming 技能调用链路 + 知识库全部接口（含上传→不重启即检索热刷新），执行后自删，结果存 `docs/verify_results/`

**需部署文件**
- 代码：`src/gateway/grpc_server.py`、`src/agent/loop.py`、`src/agent/agent_config.py`、`src/skill/registry.py`、`src/knowledge/paths.py`（新增）、`src/knowledge/{core/vector_store.py, core/document_processor.py, storage/document_loader.py, storage/document_repo.py, skills/knowledge_qa.py, skills/knowledge_search.py, knowledge_service.py}`、`scripts/knowledge_api.py`、`src/config/port_loader.py`、`services/agent_service/agent_service_grpc.py`、`skills/kunming_classifier/{execute.py, SKILL.md, _meta.json}`
- 配置：`config/gateway.yaml`（新增 knowledge 段）、`agents/kunming/config.json`、`agents/kunming/tools.json`、`config/agents_index.json`
- 删除（服务器同步）：`skills/kunming_theory_qa/`
- 文档：《对话接口.md》《知识库.md》（前端参考）

---

## 2026-09-02（配置一致性修复：LLM 参数配置化 + 发前 clamp + 死代码清理）

**性质**：对齐成熟平台（Dify 三层参数链路 + vLLM 发前防护）。把散落在调用点的写死 LLM 参数收口到 `config/dfecrab.json`，三个模型统一管理，清理废弃配置与死代码。

**A LLM 参数配置化（temperature / max_tokens / timeout）**
- `config/dfecrab.json`：模型统一在 `model_providers`（三个 provider 平等）；每个 provider 新增 `temperature`；`timeout`/`max_tokens`/`context_length` 均配置化
- `src/services/model_manager.py`：移除顶层 `model` 段读取，`current_provider` 默认取第一个 enabled
- `src/gateway/grpc_server.py`：`_get_gateway_llm_config` / `_resolve_agent_llm_config` 补 temperature 透传；timeout 不再写死 600（改读配置）
- `src/agent/loop.py`：ReAct 调用不再写死 0.7/4096（默认 None → 随 adapter 的配置值）
- `src/agent/multi/agent_group.py`、`src/plugin_framework/agent.py`：去写死、接配置

**B vLLM 发前 clamp（防 400）**
- `src/agent/llm/adapter.py`：新增 `_estimate_input_tokens` / `_clamp_max_tokens`，发送前把 max_tokens 钳到「context_length − 输入 − 8% 预算」内（vLLM 对超限直接 400 不自动截断，见 vllm#42474）

**C 死配置 / 死代码清理**
- 删：`config/group_ops_example.json`、`config/multi_agent.json`、`src/config/config.py`（含明文 API Key）、`src/gateway/handlers/multi_agent_handler.py`（引用不存在的 AgentRegistry 类）
- `config/gateway.yaml`：删 `gateway.id` / `gateway.name`
- `src/config/__init__.py`、`src/gateway/legacy.py`、`src/plugin_framework/loader.py`：移除旧 config / `default_agent` 空转引用
- `grpc_server.py`：删死方法 `_load_config` 与 `/api/multi-agent/*` 坏路由
- 其它：`skills/asr_corrector/execute.py` 删顶层 model 冗余读取；`agent_defaults.model_name`（无实际作用）移除

**需部署文件**
- 配置：`config/dfecrab.json`、`config/gateway.yaml`
- 代码：`src/services/model_manager.py`、`src/gateway/grpc_server.py`、`src/gateway/legacy.py`、`src/agent/loop.py`、`src/agent/multi/agent_group.py`、`src/agent/llm/adapter.py`、`src/plugin_framework/agent.py`、`src/plugin_framework/loader.py`、`src/config/__init__.py`、`skills/asr_corrector/execute.py`
- 验证脚本：`scripts/verify_config_param_arch.py`（部署后运行，通过后自删，结果存 `docs/verify_results/`）
- 删除（服务器同步）：`src/config/config.py`、`config/group_ops_example.json`、`config/multi_agent.json`、`src/gateway/handlers/multi_agent_handler.py`

---

## 2026-09-02（技能/工具装配重构：MCP 仅传参 + Fix-4 修复 + 全量流式）

**性质**：架构对齐成熟平台（Claude/Cursor）——工具可用性由「Agent 配置 + 显式传参」决定，不再运行时按消息关键词砍工具；MCP 改为显式传参才装配。

**A 配置**
- `config/mcporter.json`：三个服务（`demo` / `alert_judge_tools` / `blackxml_topology`）`bound_agents` 全部清空为 `[]`，MCP 不再隐式绑定 agent
- `agents/dfecrab/tools.json`：清理废弃字段（`enabled_mcp_servers` / `builtin_tools` / `custom_tools`），只保留 `enabled_skills`
- `agents/alert_judge/tools.json`：空壳化，只留 `enabled_skills: []`（alert_judge 走专属微调模型旁路，靠 `mcp:["alert_judge_tools"]` 触发）

**B 代码**
- `src/skill/registry.py`：`list_tools_for_agent` 的 MCP 装配改为「仅显式传参（`bound_servers_override`）才装配」，移除 `get_bound_server_names` 隐式派生
- `src/gateway/grpc_server.py`：`_react_chat_generator` 中 alert_judge 放行（空壳智能体不依赖通用工具装配判断），P0 自动兜底保留
- `src/agent/loop.py`：
  - Fix-4 工具注入筛选 v4.2→v4.4：本地技能按 `enabled_skills` 白名单全量保留，不再按 skill_match/消息关键词误杀（修复 `code_executor` 等本地技能"无工具可用/假装执行"故障）
  - `tool_constraint` 移到筛选后（模型被告知的工具 = 实际下发 Schema，消除幻觉调用）
  - 无工具分支补 `message_start` + 逐 token `message` 流式（纯聊也流式，与工具分支同构）
  - 清理死导入 `import re`、删除重复的 enabled_skills 过滤块

**文档**
- 《前端对接文档_对话接口.md》：更新记录 v4.6（工具注入策略、MCP 仅传参、无工具分支流式）
- 《前端对接文档_MCP服务管理.md》：更新记录 v4.6（`bound_agents` 降级为管理视图、对话装配以请求体 `mcp` 为准）

**验证脚本**
- `scripts/verify_skill_mcp_arch.py`（新增）：覆盖对话（本地技能 / 传参 MCP / alert_judge 专属链路）+ MCP 服务列表 + 技能列表，执行后自删，结果存 `docs/verify_results/`

**需部署文件**
- `config/mcporter.json`、`agents/dfecrab/tools.json`、`agents/alert_judge/tools.json`
- `src/skill/registry.py`、`src/gateway/grpc_server.py`、`src/agent/loop.py`
- `scripts/verify_skill_mcp_arch.py`（可选）
- 《对话接口.md》《MCP服务管理.md》（文档，前端参考）

---

## 2026-09-01（对话链路 Bug 修复：三批）

**性质**：修复对话核心体验 + 参数配置化 + 清理冗余。基于 8 轮测试 + 日志实证定位（message 事件缺失、60s 超时截断、工具全量注入等）。

**批次一（P0 体验）**
- `src/gateway/grpc_server.py`：`_react_chat_generator` 非 Plan 分支补 `message` 事件透传——此前 ReAct 路径不产逐 token 正文（T2 复现：`message_start→message_end` 间零 chunk），前端"生成中"白屏
- `src/agent/loop.py`：ReAct 超时由「整循环 60s」改为「每轮 LLM 独立 60s + 整体 300s 兜底」，消除长回复被 60s 腰斩（测试7 代码执行成功仍截断）

**批次二（P1 性能 / 稳定性）**
- `grpc_server.py`：时间上下文移入 system_prompt（不再混入用户消息，修复"你好"被误解为问当前时间）
- `loop.py`：工具按意图筛选注入——本地技能按 skill_match 命中、MCP 按领域词/关键词；纯聊请求不再全量注入 31 个工具（T1 实测 tools=4916 tokens → 大幅下降）
- `grpc_server.py`：Manager 编排加 `response_format={"type":"json_object"}`（决策输出更稳定）；ReAct 最大轮数改读 `dfecrab.json agent_defaults.max_iterations`（消除 `min(...,3)` 硬限制）

**批次三（P2 清理）**
- `src/skill/registry.py`：`MAX_MCP_TOOLS_PER_AGENT` 配置化（读 `dfecrab.json mcp.max_tools_per_agent`）
- `src/mcp/http_client.py`：MCP 初始化日志降为 debug（避免重复握手刷屏）
- `grpc_server.py`：Manager 决策失败日志单行化；显式指定 agent_id 时不再误报"LLM 配置不可用"
- `config/dfecrab.json`：新增 `mcp.max_tools_per_agent=30`；`agent_defaults.max_iterations` 建议调为 3~5

**需部署文件**
- `src/gateway/grpc_server.py`、`src/agent/loop.py`、`src/skill/registry.py`、`src/mcp/http_client.py`、`config/dfecrab.json`
- 前端对接文档《对话接口.md》v4.5

---

## 2026-09-01（阶段 D：收尾验收批次）

**性质**：验收批次（无功能改动）。对上一批「上下文占比 / 模型管理 / 用户管理 / WS 心跳」改动做代码审查、文档核对、验证脚本核对。

- **代码审查**：13 个相关 `.py` 文件 `py_compile` + lint 全过；无冲突——`DEFAULT_CONTEXT_LENGTH` 常量全局统一（`16384` 无散落硬编码）；`build_context_usage` 各调用点均已适配新签名（history/current/tool_results）；usage 构建收敛于 `src/utils/context_usage.py` 单点。
  - 提示（历史遗留，非本次引入，未改动）：`model_manager._load_config` 主/备两段 dict 构造与 `_normalize_provider` 结构相似（可复用）；`adapter.call/call_stream` 与 `chat_with_tools*` 存在历史大段重复，涉及多调用方，建议单独排期重构。
- **问题3收尾**：清理 `legacy.py` 旧模式（`--mode=plugin`）的应用层 `{"type":"heartbeat"}` 循环（每 5s），使 WS 心跳统一走协议层 Ping/Pong，与文档 §2.1 一致。
- **文档核对**：前端对接文档已完备（对话接口 v4.2/4.3/4.4、会话历史 v4.2、模型管理 v4.2、用户管理 v4.2），均含「更新记录」便于前端对比。
- **验证脚本核对**：`scripts/verify_context_usage.py` 覆盖 chat / chat_stream / 会话 usage / 模型 CRUD / 用户 CRUD / WS 心跳 / usage/stats / discover / 自动压缩 / 历史 token，执行后自删，结果存 `docs/verify_results/`。

**完善度评估**
- 上下文占比相关（usage 7 类 + 自动压缩 85% + 窗口自动发现 + 会话回看 + 全局用量统计 + 按模型统计）已对齐成熟平台（CodeBuddy / Claude Code），较完善。
- 用户管理**权限模型完善**，但整个系统缺**真正的身份认证**（当前仅 `X-User-Id` 身份声明，WS 为"任何 token 都通过"），见后续方案（本次未改代码）。

---

## 2026-09-01（阶段 C：WebSocket 心跳监控）

**功能**：为 WS 网关（6790）启用心跳监控，及时回收异常连接，防止连接数被拖死。

- `src/gateway/websocket/connection.py`：`handle_message` 新增应用层 **PING → PONG 免认证应答**（`{"type":"ping"}` → `{"type":"pong"}`）。
- `src/gateway/websocket/server.py`：
  - 新增 `heartbeat_interval`（默认 30s）/ `idle_timeout`（默认 90s）参数；
  - 启动时创建 **心跳后台任务**：每 30s 向所有连接发标准 WS `Ping` 帧探测活性；连续 90s 无任何消息（含 `Pong` 应答）的连接调用 `cleanup_idle_connections` 断开（close code `1001`）；
  - 协议层 **Pong 帧现在刷新 `last_message_at`**（此前收到客户端 Pong 不更新活动时间，无法证明存活）；
  - `stop()` 正常取消心跳任务。
- `src/gateway/grpc_server.py`：创建 `WebSocketServer` 时透传心跳配置（从 `dfecrab.json` 的 `ws` 段读取，缺省 30s/90s）。

**文档**
- 《对话接口.md》：更新 §2.1 心跳说明 + 新增 §2.13 心跳与断连（协议层 Ping/Pong、应用层 `ping`/`pong` 免认证、超时断连与前端重连建议）。

**需部署文件**
- `src/gateway/websocket/connection.py`
- `src/gateway/websocket/server.py`
- `src/gateway/grpc_server.py`
- 《对话接口.md》（文档，前端参考）

---

## 2026-09-01（阶段 B：用户管理增强）

**功能**：补齐用户管理（账号 CRUD）的健壮性——原子写回 + 自我保护。
（用户管理 4 个接口此前已实现并全部 `admin_only`；本次为健壮性增强。）

- `src/gateway/user_service.py`：`_write_config` 改为**原子写回**（写前备份 `.bak` + 临时文件替换），防 `permissions.json` 损坏；`update_user`/`delete_user` 增加 `current_user` 保护——不能把当前登录账号降级、不能删除当前登录账号（避免误操作锁死自己）。
- `src/gateway/grpc_server.py`：`_handle_update_user`/`_handle_delete_user` 透传 `X-User-Id` 到 service 做自我保护。
- 权限模型不变：`roles`（level + data_scope）与 `users`（账号→角色）**解耦**，数据与权限分开。

**文档**
- 《用户管理.md》：加更新记录段（自我保护 + 原子写回）。

**需部署文件**
- `src/gateway/user_service.py`
- `src/gateway/grpc_server.py`
- 《用户管理.md》（文档，前端参考）

---

## 2026-09-01（阶段 A：上下文窗口自动发现）

**功能**：模型上下文窗口 `context_length` 不再依赖人工填写（此前易配错，如 32k 模型配 8192 导致 `used_percent` 虚高），改为「显式配置 > 自动发现 > 安全默认」三层。

- `src/utils/context_usage.py`：定义共享常量 `DEFAULT_CONTEXT_LENGTH = 16384`（收口此前散落 19 处的默认值）。
- `src/services/model_manager.py`：新增 `discover_context_length(name)`——调 `/models` 读 `max_model_len`，写回 `dfecrab.json`（原子写 + 备份）并热更新；`_load_config`/`_normalize_provider`/`update_provider`/`get_all_providers` 默认值改用常量。
- `src/gateway/handlers/model_handler.py`：`create`/`update` 未传 `context_length` 时自动探测；新增 `discover` handler（手动触发）。
- `src/gateway/grpc_server.py`：注册 `POST /api/models/{config_name}/discover` 路由；`list_models` 返回各模型 `context_length`；10 处 `16384` fallback 收敛为 `DEFAULT_CONTEXT_LENGTH`。
- `src/agent/loop.py` / `src/agent/llm/adapter.py`：默认值改用 `DEFAULT_CONTEXT_LENGTH`。

**验证脚本**
- `verify_context_usage.py` 新增 `case_discover_context`（调 discover 接口，校验返回 context_length）。

**文档**
- 《模型管理.md》：更新记录补「上下文窗口自动发现」；新增 §3.6、接口总览补 discover 行。

**需部署文件**
- `src/utils/context_usage.py`
- `src/services/model_manager.py`
- `src/gateway/handlers/model_handler.py`
- `src/gateway/grpc_server.py`
- `src/agent/loop.py`
- `src/agent/llm/adapter.py`
- `scripts/verify_context_usage.py`（可选）
- 《模型管理.md》（文档，前端参考）

---

## 2026-09-01（模型管理 CRUD + 全局 token 用量统计）

**功能**：① 模型管理补齐「新增/编辑/删除/启停」CRUD（持久化到 `dfecrab.json` + 热生效，免重启）；
② 新增全局 token 用量统计接口（对齐成熟平台用量看板，纯 token 维度，本地模型无费用）。

- `src/services/model_manager.py`：新增 `add_provider / update_provider / remove_provider / toggle_provider`，
  `_update_config_provider`（原子写回 + 写前备份 `.bak`）、`_rebuild_fallback`（重建降级链）、`_normalize_provider`；
  删除保护（不能删当前全局 / 被 Agent `model_config` 引用的模型）、禁用当前时自动切换。
- `src/gateway/handlers/model_handler.py`：新增 `create / update / delete / toggle` 四个 handler（含必填校验、Agent 引用检查）。
- `src/gateway/grpc_server.py`：注册 `POST/PUT/DELETE /api/models`、`POST /api/models/{config_name}/toggle` 路由 + 新增
  `GET /api/v2/usage/stats`（handler `_handle_usage_stats`）。
- `src/utils/usage_aggregator.py`（新增）：跨会话 token 聚合（时间窗口 / 按模型 / 每日趋势 / 较上期对比），纯只读；
  `_handle_usage_stats` 按用户隔离（admin 看全部、普通 user 只看自己的用量），与历史/记忆接口数据范围一致。

**验证脚本**
- `verify_context_usage.py` 新增 `case_model_crud`（新增→列表→编辑→删除，测试模型用 disabled 避免污染全局）、
  `case_usage_stats`（校验 totals / by_model / by_day）。

**文档**
- 《模型管理.md》：接口总览补 CRUD + usage/stats；新增 3.4 模型 CRUD、3.5 全局 token 用量统计。

**需部署文件**
- `src/services/model_manager.py`
- `src/gateway/handlers/model_handler.py`
- `src/gateway/grpc_server.py`
- `src/utils/usage_aggregator.py`（新增）
- `scripts/verify_context_usage.py`（可选）
- 《模型管理.md》（文档，前端参考）

---

## 2026-09-01（v4.1：ReAct 正文实时流式输出 + 回复评估后台化）

**背景**：排查流式对话卡顿，发现两处延迟：① think 最后 chunk 到 think_end 之间 5.4s+ 静默（正文 token 只累加不转发，前端要等 message_end 一次性收完整内容）；② think_end 后 message_start 又延迟 30s+（Assessor 同步调用独立 LLM 评估阻塞）。

**修复 / 实现**
- `src/agent/loop.py`：
  - 正文 token 实时转发：token 事件不再只累加，逐 token yield `message` 事件；首个 token 时先发 `think_end`（思考结束标记提前）再发 `message_start` + `message`；
  - 新增 `_think_end_sent` / `_message_started` 标志，保证 `think_end` / `message_start` 每轮仅发一次、顺序正确；无正文输出轮兜底补发 `message_start`；
  - Assessor + Reflector 合并为后台任务（新增 `_assess_in_background`），不再同步阻塞 message_end；
  - 清理失效的 HelpSeeker 死代码块（评估后台化后恒不执行）。
- `src/core/event_types.py`：新增 `MESSAGE = "message"` 事件枚举与 `MessageEvent`（流式正文 chunk）。
- `src/gateway/grpc_server.py`：`EVENT_TYPE_MAP` 补充 `message` 类型；非流式模式跳过 `message_start`/`message` 增量，保持 JSON 响应只含 `message_end` 完整内容。

**效果**：事件流由「think_start → think → 静默 5.4s+ → think_end → message_start → message_end（一次性）」变为「think_start → think → think_end → message_start → message（实时逐 token）→ message_end」；message_end 不再等待 30s 评估。整体首字响应从 ~35s+ 降至 ~5s（仅剩模型自身思考 + 首 token 延迟）。

**验证**
- mock LLM 驱动 `ReActLoop` 实测事件流顺序断言通过（think_end 在正文前、message_start 仅一次且早于 message）。

**文档**
- 《前端对接文档_对话接口.md》：更新记录 v4.3、事件清单新增 `message`、§6.5 MCP 分支事件流补充。

**需部署文件**
- `src/agent/loop.py`
- `src/core/event_types.py`
- `src/gateway/grpc_server.py`
- 《前端对接文档_对话接口.md》（文档，前端参考）

---

## 2026-09-01（历史消息接口附带每轮上下文占用）

**功能**：`GET /api/v2/sessions/{id}/messages` 现在为每条 assistant 消息附带 `context_usage`
（该轮上下文占比/水位），看历史消息即可直接看到每轮的上下文占用，无需单独调 usage 接口。

- `src/gateway/session_handler.py`：`SessionService.get_session_messages` 遍历 assistant 消息，
  用已落库的 `tokens.prompt` + `metadata.context_length` + `model` 计算并附加 `context_usage`
  （`prompt_tokens` / `completion_tokens` / `total_tokens` / `context_length` / `used_percent` / `free_space` / `model`）。
  旧数据（无 `context_length`）不附加，前端空值兜底；HTTP / WebSocket 共用此服务，统一生效。

**验证脚本**
- `verify_context_usage.py`：`case_session_usage` 顺带校验 assistant 消息含 `context_usage.used_percent`。

**文档**
- 《会话历史.md》§4.4：消息字段表补充 `context_usage` 及其子字段说明。

**需部署文件**
- `src/gateway/session_handler.py`
- `scripts/verify_context_usage.py`（可选）
- 《会话历史.md》（文档，前端参考）

---

## 2026-08-31（模型选择体系：Agent 级模型优先 + 全局跟随）

**机制**：模型优先级「Agent 配置的 `model_config`（最高优先级，固定不变）→ 全局 `current_provider`（`/api/models/switch` 切换即生效，只影响未配置的 Agent）」。与 P3 多模型统计闭环。

**修复 / 实现**
- `src/gateway/grpc_server.py`：
  - 新增 `_resolve_agent_llm_config(agent_id)`：读 `agents/{agent_id}/config.json` 的 `model_config`，配置且启用则用该模型（含 context_length / think_config / max_tokens）；否则跟随全局；
  - 接入 3 处执行点：`_react_chat_generator`（worker）、chat 直答、上下文压缩判断（按 agent 模型窗口）；
  - **修复全局切换失效 bug**：`_get_gateway_llm_config` 硬编码 provider `"qwen3"` → 改用 `current_provider`，`/api/models/switch` 真正生效；
  - Agent 创建缺省 `model_config` 存空（跟随全局），不再写死当前全局模型。
- `src/services/model_manager.py`：`_load_config` 补 `max_tokens`、`think_config` 字段透传（agent 级模型需要）。
- `agents/*/config.json`：6 个内置 Agent 的 `model_config` 统一清空为空字符串（跟随全局，当前无需要锁定特定模型的 Agent）。

**验证脚本**
- `verify_context_usage.py`：`_check_usage` 校验 `usage.model` 字段（模型解析生效的间接验证）。

**文档**
- 《模型管理.md》：补充执行链路说明（Agent 级优先、全局跟随、当前内置 Agent 全部跟随全局）。
- 《对话接口.md》：`usage.model` 标注实际模型（多模型场景占比口径）。

**需部署文件**
- `src/gateway/grpc_server.py`
- `src/services/model_manager.py`
- `agents/*/config.json`（6 个 Agent 配置）
- `scripts/verify_context_usage.py`（可选）
- 《模型管理.md》《对话接口.md》《会话历史.md》（文档，前端参考）

---

## 2026-08-31（P3：多模型 token 成本统计）

**背景**：特殊 worker 可能用特殊模型、普通 agent 用通用模型，同一对话可能参与多个模型。此前 `Message.model` 落库为空，无法按模型统计消耗。

**改动**
- `src/utils/context_usage.py`：`build_context_usage` 新增 `model` 参数，返回 `usage.model`（标注该条回复实际用的模型与占比口径）。
- `src/agent/loop.py`：`_compose_usage` / `_make_usage` 传 `model`（来自 `llm_adapter.model_name`）。
- `src/gateway/grpc_server.py`：
  - chat 直答 / knowledge_base / alert_judge 分支 `usage.model` 标注模型；
  - assistant 消息落库补 `model` + `metadata.context_length`（该模型窗口，供按模型算水位）；
  - 会话 usage 接口支持 `?group_by=model`，按模型分组返回累计 token（对齐 CodeBuddy `/cost`）。

**效果**：同一会话若跨多个模型，`GET /api/v2/sessions/{id}/usage?group_by=model` 可分别看到每个模型的 `total_prompt_tokens` / `total_completion_tokens` / `total_tokens` / `context_length` / `last_used_percent`。

**验证脚本**
- `verify_context_usage.py` 新增 `case_group_by_model`；`_check_usage` 校验 `model` 字段。

**文档**
- 《对话接口.md》§8：`usage` 补充 `model` 字段。
- 《会话历史.md》：§4.6 补充 `group_by=model` 与 `by_model` 说明；消息 `model` 字段说明更新。

**需部署文件**
- `src/utils/context_usage.py`
- `src/agent/loop.py`
- `src/gateway/grpc_server.py`
- `scripts/verify_context_usage.py`（可选）
- 《对话接口.md》《会话历史.md》（文档，前端参考）

---

## 2026-08-31（上下文占用：历史回看接口 + 分类细分 + 短路分支）

**功能**：在「上下文占用统计 + 自动压缩」基础上，完善 P1 / P2。

**P1 - 会话上下文占用回看接口**
- 新增 `GET /api/v2/sessions/{session_id}/usage`：聚合已落库 `Message.tokens`，返回累计用量 + 每轮水位（`total_tokens` / `last_used_percent` / `peak_used_percent` / `rounds`）。纯只读、无 LLM 调用，权限与历史消息一致。

**P2a - 分类细分 + 归一化**
- `src/utils/context_usage.py`：`build_context_usage` 的 `categories` 由 5 类细分为 **7 类**（`history` / `current` / `tool_results` 拆分原 `messages`）；
  LLM 返回 usage 时各分类**按估算比例归一化到 `prompt_tokens`**（分类之和 = `prompt_tokens`，对齐 CodeBuddy "Estimated" 口径）。
- `src/agent/loop.py` / `grpc_server.py`（chat 直答分支）适配新签名，拆分传入 history / current / tool_results。

**P2b - 短路分支补 usage**
- `knowledge_base` 分支：`message_end.usage` + assistant 落库 `tokens`，本地估算（`source=local_estimate`）。
- `alert_judge` 分支：终止事件 `task_complete.data.usage`，本地估算。

**验证脚本**
- `verify_context_usage.py` 新增 `case_session_usage`（P1 接口）、`case_knowledge_base_usage`（KB 分支 usage）。

**文档**
- 《对话接口.md》§8：categories 更新为 7 类 + 归一化说明 + 短路分支 usage 说明。
- 《会话历史.md》：新增 §4.6 获取会话上下文占用统计接口。

**需部署文件**
- `src/utils/context_usage.py`
- `src/agent/loop.py`
- `src/gateway/grpc_server.py`
- `scripts/verify_context_usage.py`（可选）
- 《对话接口.md》《会话历史.md》（文档，前端参考）

---

## 2026-08-31（上下文自动压缩 AutoCompact）

**功能**：在「上下文占用统计」基础上，新增自动压缩能力（参考 Claude Code AutoCompact / CodeBuddy Autocompact）。
当上一轮上下文占用达到阈值（默认 85%）时，在下一轮对话开始前同步将「旧摘要 + 老历史」用 LLM 合并为新摘要，
本次注入的原始历史条数相应减少，老上下文由摘要承担，避免上下文耗尽。**无损**：会话消息不删除，历史接口仍可查全量。

- `src/utils/context_usage.py`：新增 `should_compact()`（占用达阈值判断）、`compact_buffer()`（压缩预留空间）；
  `build_context_usage` 输出新增 `auto_compact_buffer`
- `src/memory/summarizer.py`：`SessionSummarizer` 新增 `compact_session()`（按占用触发的同步压缩，复用 `_llm_roll`）
- `src/gateway/grpc_server.py`：
  - `_prepare_stream_context` 读取会话上一轮 `tokens.prompt`，达阈值时同步触发压缩；压缩成功后减少本次历史注入条数
  - `_react_chat_generator` 支持 `compact_context`：触发压缩时历史由 4 条减到 2 条
  - `message_end.usage` 透传 `compacted` 标记
  - 新增 `_context_engine_conf()` 读取 `dfecrab.json` 的 `context_engine` 配置
- `config/dfecrab.json`：新增 `context_engine` 配置段（`auto_compact_threshold` / `compact_keep_recent` / `compact_buffer_ratio`）

**验证脚本**
- `scripts/verify_context_usage.py` 新增 `case_auto_compact`：连发多轮观察 `used_percent` 增长，达阈值时断言 `compacted=true`

**文档**
- 《对话接口.md》§8 补充 `compacted` / `auto_compact_buffer` 字段；修正章节编号重复（原 §8 智能体路由顺延为 §9，后续章节依次顺延）

**需部署文件**
- `src/utils/context_usage.py`
- `src/memory/summarizer.py`
- `src/gateway/grpc_server.py`
- `config/dfecrab.json`
- `scripts/verify_context_usage.py`（可选）

---

## 2026-08-31（对话上下文占用统计 / token 占比）

**功能**：对话接口新增「上下文占用」统计（参考 CodeBuddy `/context` / Claude Code / Antigravity），
`message_end` 事件携带 `usage`，前端可展示「已用 / 总量（百分比）+ 分类明细」。

- 新增 `src/utils/context_usage.py`：上下文统计模块（分类估算、占比、token 落库折算）
- `src/agent/llm/adapter.py`：
  - 流式请求加 `stream_options.include_usage`，解析 LLM 返回的 `usage`（vLLM/OpenAI 兼容）
  - `call()` 支持 `with_usage=True`；`call_stream` / `chat_with_tools_stream` 新增 `usage` 事件
  - 修复流式 usage 块 `choices` 为空导致的 IndexError 隐患
  - 新增 `context_length` 读取（来自 `config/dfecrab.json`）
- `src/agent/loop.py`：`message_end` 事件携带 `usage`（system / tools / memory / skills / messages 分类，LLM 返回为准、本地估算兜底）
- `src/gateway/grpc_server.py`：chat 直答 / ReAct 路径 `message_end` 透传 `usage`；assistant 消息落库 `tokens`（自动累计到 `Session.total_tokens`）；`_get_gateway_llm_config` 透传 `context_length`
- `src/services/model_manager.py`：修复 `context_length` 在模型配置加载时被丢弃的 bug（换模型后占比分母错误），provider 配置补传 `context_length`

**验证脚本**
- 新增 `scripts/verify_context_usage.py`：覆盖对话接口（非流式 / SSE 流式）+ 会话历史 tokens，结果存 `docs/verify_results/`，执行后清理测试会话并删除脚本自身

**文档**
- 《对话接口.md》新增 §8 上下文占用（usage），§5 / §7 补充 `usage` 字段
- 《会话历史.md》补充消息 `tokens` 字段说明

**需部署文件**
- `src/utils/context_usage.py`（新增）
- `src/agent/llm/adapter.py`
- `src/agent/loop.py`
- `src/gateway/grpc_server.py`
- `src/services/model_manager.py`
- `scripts/verify_context_usage.py`（新增，可选）

---

## 2026-08-31（对话链路性能优化 + 检索引擎 Bug 修复）

**问题**：每轮对话 120~264 秒超时、后期轮次 400、记忆写入 `index_memory` AttributeError。

**性能精简（32B Q4 模型长 prompt 慢）**
- `grpc_server.py`：注入历史消息 10→4 条；ReAct 最大轮数限制 ≤3
- `unified_manager.py`：`build_context_text` 注入精简（画像 10→3、经验 5+3→2+1、日志 200→80 字）
- `loop.py`：单轮超时 120s→60s；超时后不再调 LLM（直接拼贴已有内容，省 30-60s）；消息 >12 条滑动窗口丢最老的非 system，防 prompt 超长 400

**Bug 修复**
- `keyword_search.py`：`MemorySearchEngine` 补 `index_memory`（no-op），修复 `unified_manager.add_memory` 每次调 `index_memory` 抛 AttributeError 导致记忆写入失败
- `unified_manager.py:250`：`index_memory` 调用加 `hasattr` + try/except 防御

**配置**
- `dfecrab.json`：`qwen3_32b_q4` 的 `context_length` 8192→16384（配合 llama.cpp 启动 `-c 16384`）

**验证脚本**
- `verify_memory_system.py`：自动提取检查等待 3s→30s（匹配 LLM 实际提取耗时）

**文档**
- 《记忆管理.md》8.3 补充性能优化说明

---

## 2026-08-31（记忆体系自动闭环：阶段 A / B / C 综合）

**一句话**：记忆从「只存不用」变为「自动沉淀 → 自动提取 → 对话自动注入」的闭环。

- **阶段 A** 记忆检索引擎：BM25 关键词检索（用户记忆 / Agent 经验 / 每日日志），对话注入三段式记忆上下文
- **阶段 B** 用户事实自动提取：对话后用 LLM 提取高置信度用户事实（常驻地/职业/偏好）→ `memories.json`（`source=conversation`）
- **阶段 C** 会话滚动摘要：每 10 轮将「旧摘要 + 新增对话」合并 → 更新 `session.summary`，修复摘要每轮漂移
- 新增验证脚本 `scripts/verify_memory_system.py`：全量记忆接口验证，结果存 `docs/verify_results/`，执行后自动清理测试数据并删除脚本自身

详细条目见下方「阶段 A / 阶段 B / 阶段 C」三节。

---

## 2026-08-31（记忆系统重构 + 用户维度 + 知识库清理）

**记忆接口修复（Phase 1）**
- 修复路由冲突：`/api/agents/memory` 被 `/api/agents/{agent_id}` 通配路由劫持，Agent 记忆接口迁移到 `/api/memory/agents/{agent_id}`、`/api/memory/agents`
- 补全 `GlobalMemoryManager` 缺失的 `list_daily_files` / `get_storage_info` / `load_recent_daily`，修复 `/api/memory/files`、`/storage`、`/recent` 三个必挂接口
- 记忆结构兼容 V3.0 新格式（`long_term.patterns/lessons/facts`）与旧格式（`experience.*`）
- 修复 `UnifiedMemoryManager` 构造时因导入缺失搜索引擎模块而崩溃；修复 `/api/memory/search` 缺 `await` 的 bug

**default 孤儿 Agent 修复（Phase 2）**
- `/api/agents` 过滤 ZK 中本地不存在的孤儿注册（如残留 default 进程）
- 同一 agent 多实例按 `registered_at` 取最新，避免返回死进程地址
- Gateway 启动时新增 ZK 孤儿注册扫描告警

**记忆按用户隔离（Phase 3）**
- `ExecuteRequest` 新增 `user_id` 字段，重新生成 `dfecrab_pb2`（补齐 `ChatStream` RPC）
- `MemoryManager` / `save_daily_memory` 支持 `user_id`，存储迁移到 `data/memory/users/{user_id}/`
- Agent 进程按 `request.user_id` 隔离读写记忆；Manager 通过线程局部变量透传 `user_id` 到 Worker
- API 按用户隔离：普通用户只能看自己，admin 可通过 `?user_id=` 查所有用户
- 修复 `/api/memory/agents/{agent_id}` handler 未接收路径参数导致 `agent_memory()` 报 500 的问题（HTTP server 以关键字方式传入路径参数）
- 全局接口按用户化：`/api/memory/stats|recent|files|storage` 新增 `?user_id=` 参数，改为读 `data/memory/users/{user_id}/global/DAILY/`（不带 `user_id` 兼容旧路径）
- 新增 `scripts/test_memory_api.py`：记忆接口全量测试脚本，结果存文件并自动清理测试写入的数据
- 修复 `/api/memory/recent` 解析错位（日期块/条目用正则解析）、`/api/memory/agents` 摘要计数恒为 0（改为读取完整的 memory.json 结构）
- 修复 `test_memory_api.py` 中文 query 未 URL 编码导致 `search` 报 ascii 错误

**数据迁移（Phase 4）**
- 新增 `scripts/migrate_memory_to_users.py`：旧路径数据迁移到用户目录，自动备份，支持 `--dry-run`

**清理冗余（Phase 5）**
- 删除死代码 `handlers/agent_handler.py` 与 4 个 Stub（`search/semantic.py`、`search/keyword_search.py`、`legacy_manager.py`、`compactor.py`）
- 删除空目录 `data/memory/filesystem`、`data/memory/metadata`、`data/shared_memory/WEEKLY`、`data/shared_memory/MONTHLY`
- `search` / `index_health` 接口改为诚实返回「未启用」
- 修复 `UnifiedMemoryManager` 引用未导入类型（`BaseStorageAdapter`/`BaseSearchEngine`）导致的实例化失败

**用户级记忆 CRUD（Phase 6）**
- 新增 `src/memory/user_manager.py`：`data/memory/users/{user_id}/memories.json` 结构化 KV
- 新增 `/api/memory/users` 系列接口（GET 列表 / POST 新增 / PUT 更新 / DELETE 删除）
- `get_user_profile` 优先读取用户级记忆，用于 Manager `{{USER_PROFILE}}` 注入

**移除旧知识库**
- 删除 `data/shared_memory/knowledge/`（`grid_knowledge.json`、`kunming_theory_qa.json`），与新知识库系统冲突，已备份到 `data/backup/knowledge_removed_20260831/`
- 清理引用：`GlobalMemoryManager`（移除 `load_library` / `library_dir_exists` / `library_path`）、`long_term`（shared_memory 置空）、`GlobalMemoryModule`、`skills/project_memory`；`skills/kunming_theory_qa` 数据缺失时友好降级

**接口文档**
- 重写《记忆管理.md》（新路径、用户隔离、用户级记忆 CRUD、知识库移除）
- 更新《Agent管理.md》（孤儿过滤说明）

**需部署文件**
- `src/gateway/grpc_server.py`、`src/gateway/legacy.py`
- `src/gateway/handlers/memory_handler.py`、`src/gateway/handlers/__init__.py`
- `src/memory/`：`unified_manager.py`、`long_term.py`、`global_manager.py`、`user_manager.py`（新增）、`modules/agent_module.py`、`modules/global_module.py`、`__init__.py`、`search/__init__.py`
- `src/agent/loop.py`、`src/task/executor.py`
- `services/agent_service/agent_service_grpc.py`、`services/manager_agent/manager_agent_grpc.py`
- `proto/dfecrab.proto`、`src/gateway/grpc/dfecrab_pb2.py`（重新生成）、`src/gateway/grpc/dfecrab_pb2_grpc.py`（重新生成）
- `skills/project_memory/execute.py`、`skills/kunming_theory_qa/execute.py`
- `scripts/migrate_memory_to_users.py`（新增）

---

## 2026-08-31（阶段 A：记忆检索引擎 + 注入重构）

**记忆检索引擎**
- 新增 `src/memory/search/keyword_search.py`：BM25 关键词检索引擎（纯标准库，中文 bigram 分词），按用户隔离检索用户记忆 / Agent 经验 / 每日日志，支持 `scope`（all/user_memory/agent_memory/daily）
- `unified_manager`：`_initialize_search` 启用检索引擎；`search_memory` 支持 `user_id` / `scope`
- `/api/memory/search` 接入真实检索（带 `user_id` 权限），`/api/memory/index_health` 返回 healthy

**对话记忆注入**
- 新增 `build_context_text`：构建三段式记忆上下文（用户画像 + 相关经验 + 近期日志）
- `loop.py` 对话注入改为使用 `build_context_text`（替代原来的"前 3 条过程日志"）

**文档**
- `前端对接文档_记忆管理.md` 更新检索 / 健康接口说明

---

## 2026-08-31（阶段 B：用户事实自动提取）

- 新增 `src/memory/extractor.py`：`UserFactExtractor`，对话结束后用 LLM 提取高置信度用户事实（常驻地 / 职业 / 偏好 / 称呼等）→ 写入用户级记忆 `memories.json`（`scope=user, source=conversation`）
- `grpc_server.py` 对话沉淀后异步触发自动提取（fire-and-forget，不阻塞主流程，失败静默）
- 同 key 自动更新（复用 `UserMemoryManager.add_memory`），自动提取的事实会进入 `{{USER_PROFILE}}` 用户画像注入

---

## 2026-08-31（阶段 C：长对话滚动摘要）

- 新增 `src/memory/summarizer.py`：`SessionSummarizer`，每 N 轮（默认 10 轮）用 LLM 将「旧摘要 + 新增对话」合并为滚动摘要 → 写入 `session.summary`，下一轮对话自动注入（`_build_enhanced_message` 已支持）
- `grpc_server.py` 对话沉淀后异步触发滚动摘要（fire-and-forget，不阻塞主流程，失败静默）
- 修复原摘要每轮被 `message[:50]` 覆盖导致的摘要漂移问题：非新会话时保留已有摘要，由滚动摘要异步更新
- 滚动摘要同时持久化到每日记忆 `category=session_summary`（跨会话可查对话脉络）

---

## 2026-08-28（知识库直答历史修复）

**对话接口 `grpc_server.py`**
- 修复知识库直答（`knowledge_base`）的 assistant 消息没保存：保存历史时误传了 `Message` 不存在的 `matched_skills` 参数导致报错被吞；已移除并挪进 `metadata`，同时消息标记为 `completed`
- 修复 user 消息重复保存：KB 分支不再单独保存 user（标准流程已统一保存）
- `kb_top_k` 默认值统一为 **5**（对话接口 5 处入口 + pipeline 签名；知识库 `search`/`chat` 默认值同步为 5）

**接口文档**
- 《对话接口.md》6.4 节更新「历史保存」说明：user 由标准流程保存，assistant 以 `task_type=knowledge_base` 保存（含 `sources`/`source_titles`/`matched_skills`），失败时不存 assistant
- 《对话接口.md》《知识库.md》的 `top_k` / `kb_top_k` 默认值统一标注为 5

**需部署文件**
- `src/gateway/grpc_server.py`
- `src/knowledge/knowledge_service.py`

---

## 2026-08-28（启动脚本）

**启动脚本 `dfecrab`**
- 新增 `stopall` 命令：一次停止全部服务（Gateway + Agent + 知识库 + MCP），并清理 ZK 残留节点
- 修复 MCP 启动误报失败：原来固定等 2 秒就检测端口，MCP 冷启动慢会误判；改为轮询等待（最长 15 秒），端口就绪立刻报成功

---

## 2026-08-28

**知识库问答**
- `chat` 接口接入 LLM，回答改为模型综合生成（原来是片段拼接，和 `search` 一样）；LLM 不可用时自动降级为拼接
- `search` 改为纯检索，只返回片段，不再生成回答
- 修复长回答被截断问题（提高回答长度上限，截断时打日志告警）
- 文档切片粒度 300 → 800，默认召回数 5 → 8
- 新增同文档去重，避免单个文档占满召回结果
- 新增重建切片脚本 `scripts/rebuild_knowledge_chunks.py`

**对话接口**
- 知识库直答（`knowledge_base`）现在会保存会话历史，之前不保存

**服务恢复**
- 重启后 ZK 启动失败，清理数据后恢复（建议后续把数据目录迁出 `/tmp` 并配置开机自启）

**日志**
- 知识库 `search`/`chat`、LLM 调用、MCP 工具调用均补充了入参 / 出参 / 耗时日志

**接口文档**
- 更新《知识库.md》《对话接口.md》《MCP服务管理.md》，修正参数默认值和示例

**需部署的文件**
- `src/knowledge/llm/openai_client.py`（新增）
- `src/knowledge/rag/prompt_builder.py`
- `src/knowledge/knowledge_service.py`
- `src/knowledge/core/retriever.py`
- `src/knowledge/skills/knowledge_qa.py`
- `scripts/rebuild_knowledge_chunks.py`（新增）
- `src/gateway/grpc_server.py`
- `src/mcp/http_client.py`

部署：停服务 → 跑重建切片脚本 → 覆盖文件 → 启动。

---

## 2026-08-27

- 初始化变更日志
