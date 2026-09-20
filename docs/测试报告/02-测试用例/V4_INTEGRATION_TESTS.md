# DFEcrab v4.0 集成测试用例

> **文档版本**: 1.0  
> **创建日期**: 2026-04-03  
> **关联测试计划**: `INTEGRATION_TEST_PLAN.md`  

---

## 1. 权限系统测试用例 (8 项)

### T-PERM-001: 权限级别枚举验证

**目标**: 验证 `PermissionLevel` 枚举定义正确

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 导入 `PermissionLevel` 枚举 | 导入成功 |
| 2 | 验证包含 4 个级别 | READ_ONLY, WRITE, SHELL, UNSAFE |
| 3 | 验证每个级别的 value 属性 | 值分别为 "read_only", "write", "shell", "unsafe" |
| 4 | 验证枚举不可变 | 尝试修改抛出 AttributeError |

**通过标准**: 所有步骤预期结果一致

---

### T-PERM-002: AgentPermissions 创建与序列化

**目标**: 验证 `AgentPermissions` 数据类的创建、序列化和反序列化

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 使用默认参数创建实例 | 所有权限为 False，level 为 READ_ONLY |
| 2 | 使用 `from_flags(allow_write=True)` 创建 | allow_file_write=True，level 为 WRITE |
| 3 | 使用 `from_flags(allow_shell=True)` 创建 | allow_shell_commands=True，level 为 SHELL |
| 4 | 使用 `from_flags(unsafe=True)` 创建 | allow_destructive_shell_commands=True，level 为 UNSAFE |
| 5 | 调用 `to_dict()` 序列化 | 返回包含所有权限键的字典 |
| 6 | 使用 `from_dict()` 反序列化 | 恢复原始权限配置 |
| 7 | 验证 frozen=True | 尝试修改字段抛出 FrozenInstanceError |

**通过标准**: 所有步骤预期结果一致

---

### T-PERM-003: 权限级别升级逻辑

**目标**: 验证权限级别按正确逻辑推导

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 仅设置 allow_file_write=True | level == WRITE |
| 2 | 设置 allow_file_write=True, allow_shell_commands=True | level == SHELL |
| 3 | 设置所有权限为 True | level == UNSAFE |
| 4 | 所有权限为 False | level == READ_ONLY |
| 5 | 仅设置 allow_destructive_shell_commands=True | level == UNSAFE（最高权限优先） |

**通过标准**: 所有步骤预期结果一致

---

### T-PERM-004: 被阻止工具列表生成

**目标**: 验证 `get_blocked_tools()` 返回正确的被阻止工具列表

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | READ_ONLY 权限调用 | 返回 ['write_file', 'edit_file', 'create_file', 'delete_file', 'bash', 'shell', 'execute'] |
| 2 | WRITE 权限调用 | 返回 ['bash', 'shell', 'execute'] |
| 3 | SHELL 权限调用 | 返回 [] |
| 4 | UNSAFE 权限调用 | 返回 [] |

**通过标准**: 所有步骤预期结果一致

---

### T-PERM-005: 破坏性命令检测

**目标**: 验证 `is_destructive_command()` 正确识别破坏性命令

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 检测 `rm -rf /tmp/test` | 返回 True |
| 2 | 检测 `rm file.txt` | 返回 True |
| 3 | 检测 `dd if=/dev/zero of=/dev/sda` | 返回 True |
| 4 | 检测 `shutdown -h now` | 返回 True |
| 5 | 检测 `reboot` | 返回 True |
| 6 | 检测 `mkfs.ext4 /dev/sda1` | 返回 True |
| 7 | 检测 `chmod -R 777 /tmp` | 返回 True |
| 8 | 检测 `git reset --hard HEAD` | 返回 True |
| 9 | 检测 `git clean -fd` | 返回 True |
| 10 | 检测 `ls -la` | 返回 False |
| 11 | 检测 `cat file.txt` | 返回 False |
| 12 | 检测 `echo "hello"` | 返回 False |
| 13 | 检测 `pwd` | 返回 False |
| 14 | 检测管道中的破坏命令 `cd /tmp && rm -rf test` | 返回 True |

**通过标准**: 所有步骤预期结果一致

---

### T-PERM-006: 命令安全性检查

**目标**: 验证 `check_command_safety()` 综合安全检查逻辑

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | READ_ONLY 权限执行 `ls` | (False, "Shell 命令执行权限未启用") |
| 2 | SHELL 权限执行 `ls` | (True, "命令安全检查通过") |
| 3 | SHELL 权限执行 `rm -rf /tmp` | (False, "检测到破坏性命令") |
| 4 | UNSAFE 权限执行 `rm -rf /tmp` | (True, "检测到破坏性命令，但 Unsafe 模式已启用") |
| 5 | SHELL 权限执行 `echo hello` | (True, "命令安全检查通过") |

**通过标准**: 所有步骤预期结果一致

---

### T-PERM-007: 工具权限上下文

**目标**: 验证 `ToolPermissionContext` 工具级别权限控制

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 创建 deny_names=['bash'] 的上下文 | 创建成功 |
| 2 | 调用 `blocks('bash')` | 返回 True |
| 3 | 调用 `blocks('read_file')` | 返回 False |
| 4 | 创建 deny_prefixes=['admin_'] 的上下文 | 创建成功 |
| 5 | 调用 `blocks('admin_delete')` | 返回 True |
| 6 | 调用 `blocks('admin_create')` | 返回 True |
| 7 | 调用 `blocks('user_list')` | 返回 False |
| 8 | 验证大小写不敏感 | `blocks('BASH')` 返回 True |

**通过标准**: 所有步骤预期结果一致

---

### T-PERM-008: 权限辅助函数

**目标**: 验证权限相关的辅助函数

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | `ensure_write_permission()` 在 READ_ONLY 下调用 | 抛出 PermissionError |
| 2 | `ensure_write_permission()` 在 WRITE 下调用 | 无异常 |
| 3 | `ensure_shell_permission()` 在 READ_ONLY 下调用 | 抛出 PermissionError |
| 4 | `ensure_shell_permission()` 在 SHELL 下调用安全命令 | 无异常 |
| 5 | `ensure_shell_permission()` 在 SHELL 下调用破坏命令 | 抛出 PermissionError |
| 6 | `get_permission_summary()` 调用 | 返回包含权限状态的字符串 |
| 7 | `get_permission_hint()` 在 READ_ONLY 下调用 | 返回包含所有权限限制的提示 |
| 8 | `get_permission_hint()` 在 UNSAFE 下调用 | 返回 "完整权限已启用" |
| 9 | `parse_permissions_from_args()` 解析参数字典 | 返回正确的 AgentPermissions 实例 |

**通过标准**: 所有步骤预期结果一致

---

## 2. 斜杠命令系统测试用例 (4 项)

### T-CMD-001: 斜杠命令解析

**目标**: 验证 `parse_slash_command()` 正确解析斜杠命令

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 解析 `/help` | command_name="help", args="" |
| 2 | 解析 `/model qwen-max` | command_name="model", args="qwen-max" |
| 3 | 解析 `/permissions` | command_name="permissions", args="" |
| 4 | 解析 `/status` | command_name="status", args="" |
| 5 | 解析非斜杠文本 `hello world` | 返回 None |
| 6 | 解析仅斜杠 `/` | 返回 None |
| 7 | 解析 `/help extra args here` | command_name="help", args="extra args here" |
| 8 | 验证大小写不敏感 | `/HELP` 解析为 command_name="HELP"（后续查找时转小写） |

**通过标准**: 所有步骤预期结果一致

---

### T-CMD-002: 命令预处理与路由

**目标**: 验证 `preprocess_slash_command()` 正确路由命令

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 处理 `/help` | handled=True, should_query=False |
| 2 | 处理 `/unknown_cmd` | handled=True, should_query=False, output 包含 "Unknown command" |
| 3 | 处理普通文本 `请帮我写代码` | handled=False, should_query=True |
| 4 | 处理 `/context` | handled=True, should_query=False |
| 5 | 处理 `/clear` | handled=True, should_query=False |
| 6 | 验证 transcript 包含用户和助手消息 | transcript 长度为 2 |

**通过标准**: 所有步骤预期结果一致

---

### T-CMD-003: 命令处理器执行

**目标**: 验证各命令处理器正确执行

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 执行 `/help` | 输出包含所有可用命令列表 |
| 2 | 执行 `/context-raw` | 输出包含 Workspace、Agent ID、Session ID |
| 3 | 执行 `/permissions` | 输出包含权限配置说明 |
| 4 | 执行 `/model` 无参数 | 输出说明当前模型配置管理方式 |
| 5 | 执行 `/model qwen-plus` | 输出说明模型切换尚未实现 |
| 6 | 执行 `/tools` | 输出说明工具列表需要集成 skill 插件 |
| 7 | 执行 `/memory` | 输出说明内存报告需要集成 memory 插件 |
| 8 | 执行 `/status` | 输出包含 Agent ID、Session ID、Workspace、Messages 数量 |
| 9 | 执行 `/clear` | 输出包含 "Cleared ephemeral Python agent state" |

**通过标准**: 所有步骤预期结果一致

---

### T-CMD-004: 命令列表与帮助

**目标**: 验证 `get_command_list()` 返回正确的命令列表

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 调用 `get_command_list()` | 返回包含 10 个命令的列表 |
| 2 | 验证每个命令包含 command 字段 | 格式为 "/命令名" |
| 3 | 验证每个命令包含 aliases 字段 | 别名为数组格式 |
| 4 | 验证每个命令包含 description 字段 | 描述为非空字符串 |
| 5 | 验证 `/help` 的别名为 `['/commands']` | 正确 |
| 6 | 验证 `/status` 的别名为 `['/session']` | 正确 |
| 7 | 验证 `/context` 的别名为 `['/usage']` | 正确 |

**通过标准**: 所有步骤预期结果一致

---

## 3. 工具系统测试用例 (9 项)

### T-TOOL-001: AgentTool 接口验证

**目标**: 验证 `AgentTool` 数据类接口正确

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 创建 AgentTool 实例 | 包含 name, description, parameters, handler |
| 2 | 验证 parameters 为 JSON Schema 格式 | 包含 type, properties 等字段 |
| 3 | 验证 handler 为可调用对象 | callable(handler) 返回 True |
| 4 | 验证 frozen=True | 尝试修改字段抛出异常 |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-002: OpenAI 格式转换

**目标**: 验证 `to_openai_tool()` 正确转换为 OpenAI function calling 格式

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 调用 `to_openai_tool()` | 返回包含 type 和 function 的字典 |
| 2 | 验证 type 为 "function" | 正确 |
| 3 | 验证 function 包含 name, description, parameters | 与原始工具定义一致 |
| 4 | 验证输出可直接用于 OpenAI API | 格式符合 OpenAI 规范 |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-003: 工具执行（成功路径）

**目标**: 验证工具在正常情况下的执行

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 执行 `list_dir` 工具 | 返回目录内容列表 |
| 2 | 执行 `read_file` 工具读取现有文件 | 返回文件内容 |
| 3 | 执行 `write_file` 工具（需写入权限） | 返回成功消息 |
| 4 | 执行 `edit_file` 工具（需写入权限） | 返回成功编辑消息 |
| 5 | 执行 `glob_search` 工具 | 返回匹配文件列表 |
| 6 | 执行 `grep_search` 工具 | 返回匹配行列表 |
| 7 | 执行 `bash` 工具执行 `echo hello` | 返回 "hello" |
| 8 | 验证所有结果包含 ok=True | 正确 |
| 9 | 验证结果可序列化为 JSON | `to_json()` 返回有效 JSON |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-004: 工具执行（错误路径）

**目标**: 验证工具在异常情况下的错误处理

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 执行不存在的工具 | 返回 ok=False，包含 "Unknown tool" |
| 2 | `read_file` 读取不存在的文件 | 抛出 ToolExecutionError |
| 3 | `read_file` 读取目录而非文件 | 抛出 ToolExecutionError |
| 4 | `list_dir` 列出不存在的路径 | 抛出 ToolExecutionError |
| 5 | `edit_file` 使用不存在的 old_text | 抛出 ToolExecutionError |
| 6 | `bash` 执行无效命令 | 返回 ok=False，包含错误信息 |
| 7 | 验证错误结果包含 ok=False | 正确 |
| 8 | 验证错误信息包含详细描述 | 非空字符串 |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-005: 流式工具执行

**目标**: 验证 `execute_tool_streaming()` 流式输出

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 流式执行 `bash` 工具 | 产生多个 ToolStreamUpdate |
| 2 | 验证流式输出包含 kind='output' 的更新 | 正确 |
| 3 | 验证流式输出最终以 kind='result' 结束 | 正确 |
| 4 | 验证 stdout 流正确标记 | stream='stdout' |
| 5 | 验证 stderr 流正确标记 | stream='stderr' |
| 6 | 流式执行非 bash 工具 | 产生 output 更新后跟 result |
| 7 | 流式执行不存在的工具 | 直接返回 result，ok=False |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-006: 路径安全验证

**目标**: 验证路径解析防止目录逃逸

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 解析相对路径 `file.txt` | 解析为工作区根目录下的路径 |
| 2 | 解析 `../secret.txt` | 抛出 ToolExecutionError（逃逸工作区） |
| 3 | 解析 `../../etc/passwd` | 抛出 ToolExecutionError（逃逸工作区） |
| 4 | 解析绝对路径（在工作区内） | 正确解析 |
| 5 | 解析绝对路径（在工作区外） | 抛出 ToolExecutionError |
| 6 | 验证 `allow_missing=True` 时不检查存在性 | 路径不存在也不报错 |
| 7 | 验证 `allow_missing=False` 时检查存在性 | 路径不存在抛出异常 |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-007: 权限过滤集成

**目标**: 验证工具执行受权限控制

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | READ_ONLY 权限执行 `write_file` | 抛出 ToolPermissionError |
| 2 | READ_ONLY 权限执行 `edit_file` | 抛出 ToolPermissionError |
| 3 | READ_ONLY 权限执行 `bash` | 抛出 ToolPermissionError |
| 4 | WRITE 权限执行 `write_file` | 成功执行 |
| 5 | SHELL 权限执行安全 bash 命令 | 成功执行 |
| 6 | SHELL 权限执行破坏性 bash 命令 | 抛出 ToolPermissionError |
| 7 | 验证权限错误包含清晰提示 | 包含 "Enable --allow-write" 等提示 |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-008: 工具注册表

**目标**: 验证 `default_tool_registry()` 创建正确的工具注册表

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 调用 `default_tool_registry()` | 返回包含 7 个工具的字典 |
| 2 | 验证包含 `list_dir` | 正确 |
| 3 | 验证包含 `read_file` | 正确 |
| 4 | 验证包含 `write_file` | 正确 |
| 5 | 验证包含 `edit_file` | 正确 |
| 6 | 验证包含 `glob_search` | 正确 |
| 7 | 验证包含 `grep_search` | 正确 |
| 8 | 验证包含 `bash` | 正确 |
| 9 | 验证所有工具名称为键 | 可通过名称直接访问 |

**通过标准**: 所有步骤预期结果一致

---

### T-TOOL-009: 工具报告生成

**目标**: 验证 `render_tools_report()` 生成正确的工具报告

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 在 READ_ONLY 权限下生成报告 | 写入/编辑/bash 工具标记为 ❌ |
| 2 | 在 WRITE 权限下生成报告 | 写入/编辑工具标记为 ✅，bash 标记为 ❌ |
| 3 | 在 SHELL 权限下生成报告 | 所有工具标记为 ✅ |
| 4 | 验证报告包含工具总数 | "Total: 7 tools" |
| 5 | 验证报告包含权限提示 | 包含权限提示字符串 |
| 6 | 验证报告为 Markdown 格式 | 包含 Markdown 语法 |

**通过标准**: 所有步骤预期结果一致

---

## 4. 会话持久化测试用例

### T-SESS-001: 会话保存与恢复

**目标**: 验证会话可以正确保存和恢复

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 创建新会话并添加消息 | 会话包含消息列表 |
| 2 | 保存会话到持久化存储 | 保存成功，文件存在 |
| 3 | 从存储加载会话 | 恢复的会话与原始会话一致 |
| 4 | 验证消息完整性 | 消息数量和内容一致 |
| 5 | 验证会话元数据 | ID、创建时间等元数据一致 |
| 6 | 修改会话后再次保存 | 更新后的内容正确保存 |
| 7 | 重新加载验证修改 | 加载的会话包含最新修改 |
| 8 | 测试并发保存/加载 | 无数据损坏 |
| 9 | 测试损坏数据的恢复 | 优雅处理，不崩溃 |
| 10 | 测试不存在的会话 ID 加载 | 返回 None 或抛出明确异常 |

**通过标准**: 所有步骤预期结果一致

---

## 5. 上下文引擎测试用例

### T-CTX-001: 上下文管理与快照

**目标**: 验证上下文引擎正确管理和快照上下文信息

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 创建上下文引擎实例 | 初始化成功 |
| 2 | 添加工作区信息 | 工作区路径正确存储 |
| 3 | 添加 Agent 信息 | Agent ID 正确存储 |
| 4 | 添加会话信息 | Session ID 正确存储 |
| 5 | 获取上下文快照 | 包含所有已添加的信息 |
| 6 | 验证上下文更新 | 更新后快照反映最新状态 |
| 7 | 验证上下文大小估算 | 返回合理的估算值 |
| 8 | 验证上下文清理 | 清理后上下文重置 |

**通过标准**: 所有步骤预期结果一致

---

## 6. 工作区配置测试用例

### T-WKS-001: 工作区配置加载与验证

**目标**: 验证工作区配置正确加载和验证

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 从 `dfecrab.json` 加载配置 | 配置加载成功 |
| 2 | 验证配置包含必要字段 | workspace, model, permissions 等 |
| 3 | 验证配置验证 | 无效配置抛出验证错误 |
| 4 | 测试默认配置 | 使用默认值填充缺失字段 |
| 5 | 测试配置覆盖 | 环境变量覆盖配置文件 |
| 6 | 验证工作区路径解析 | 路径正确解析为绝对路径 |
| 7 | 测试配置热重载 | 修改配置后重新加载生效 |
| 8 | 验证配置持久化 | 修改后保存配置 |

**通过标准**: 所有步骤预期结果一致

---

## 7. Agent 循环测试用例

### T-AGT-001: 增强 Agent 循环

**目标**: 验证增强 Agent 循环正确处理工具调用和斜杠命令

| 步骤 | 操作 | 预期结果 |
|-----|------|---------|
| 1 | 启动 Agent 循环 | 循环正常初始化 |
| 2 | 输入普通文本查询 | 进入模型查询流程 |
| 3 | 输入斜杠命令 | 本地处理，不查询模型 |
| 4 | 模型返回工具调用 | 执行工具并返回结果 |
| 5 | 工具执行成功 | 结果传递给模型继续处理 |
| 6 | 工具执行失败 | 错误信息传递给模型 |
| 7 | 权限阻止工具执行 | 返回权限错误，不执行工具 |
| 8 | 多轮工具调用 | 循环正确处理多轮交互 |
| 9 | 最大迭代次数限制 | 达到限制后停止循环 |
| 10 | 会话状态正确维护 | 消息历史正确维护 |
| 11 | 流式输出正确处理 | 流式更新正确传递 |
| 12 | 异常处理 | 异常不导致循环崩溃 |

**通过标准**: 所有步骤预期结果一致

---

## 附录：测试用例统计

| 模块 | 测试用例数 | P0 | P1 |
|-----|-----------|-----|-----|
| 权限系统 | 8 | 6 | 2 |
| 斜杠命令系统 | 4 | 3 | 1 |
| 工具系统 | 9 | 6 | 3 |
| 会话持久化 | 1 | 1 | 0 |
| 上下文引擎 | 1 | 0 | 1 |
| 工作区配置 | 1 | 0 | 1 |
| Agent 循环 | 1 | 1 | 0 |
| **总计** | **25** | **17** | **8** |

---

*文档结束*
