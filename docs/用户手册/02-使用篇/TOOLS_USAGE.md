# 工具系统使用指南

> 本文档介绍 DFEcrab 的统一工具系统，包括 7 个核心工具的使用说明、权限要求和最佳实践。

## 目录

- [概述](#概述)
- [工具架构设计](#工具架构设计)
- [7 个核心工具说明](#7-个核心工具说明)
- [工具权限要求](#工具权限要求)
- [使用示例](#使用示例)
- [最佳实践](#最佳实践)
- [常见问题解答](#常见问题解答)

---

## 概述

DFEcrab 的统一工具系统参考了 Claude Code 的工具架构设计，提供标准化的工具接口和执行机制。工具系统的核心特点：

- **统一接口**：所有工具遵循相同的调用和返回格式
- **权限控制**：每个工具都有明确的权限要求
- **执行审计**：所有工具执行都会被记录和审计
- **结果标准化**：工具返回统一的結果格式
- **流式支持**：部分工具支持流式输出（如 Shell 命令实时输出）

工具系统核心位于 `src/core/tools/__init__.py` 和 `src/core/tools/unified_tools.py`。

---

## 工具架构设计

### 工具类别

工具按功能分为以下类别：

| 类别 | 说明 | 示例工具 |
|------|------|---------|
| `FILE` | 文件操作 | read_file, write_file, edit |
| `SEARCH` | 搜索相关 | grep_search, glob |
| `EXECUTION` | 命令执行 | bash, shell |
| `NETWORK` | 网络功能 | （扩展工具） |
| `TASK` | 任务管理 | （扩展工具） |
| `MEMORY` | 记忆操作 | （扩展工具） |
| `AGENT` | Agent 相关 | （扩展工具） |

### 工具执行流程

```
用户请求
    ↓
Agent 解析工具调用
    ↓
权限检查（Permission Check）
    ↓
参数验证（Validation）
    ↓
工具执行（Execution）
    ↓
结果标准化（Result）
    ↓
审计日志（Audit Log）
    ↓
返回给用户
```

### 工具结果格式

所有工具返回标准化的结果：

```python
@dataclass
class ToolResult:
    success: bool                    # 是否成功
    status: ToolStatus               # 状态（SUCCESS/ERROR/TIMEOUT/PERMISSION_DENIED）
    output: Any                      # 输出内容
    error: Optional[str] = None      # 错误信息
    execution_time_ms: float = 0.0   # 执行时间（毫秒）
    metadata: Dict[str, Any]         # 元数据
```

---

## 7 个核心工具说明

### 1. list_dir - 列出目录

**类别**: FILE  
**最低权限**: Read-only

**描述**: 列出指定目录下的文件和子目录。

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `path` | string | 是 | 相对于工作区的路径 |
| `max_entries` | integer | 否 | 最大条目数量限制 |

**使用示例**:

```python
# 列出当前目录
list_dir(path=".")

# 列出 src 目录，最多 50 个条目
list_dir(path="src", max_entries=50)
```

**返回示例**:

```
目录内容:
- src/
- docs/
- tests/
- README.md
- dfecrab.json
```

**适用场景**:
- 探索项目结构
- 查找特定文件的位置
- 了解目录组织

---

### 2. read_file - 读取文件

**类别**: FILE  
**最低权限**: Read-only

**描述**: 读取文件内容，支持行号偏移和数量限制。

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `file_path` | string | 是 | 文件路径 |
| `offset` | number | 否 | 起始行号（从 0 开始） |
| `limit` | number | 否 | 读取行数限制（默认 2000） |

**使用示例**:

```python
# 读取整个文件
read_file(file_path="src/core/kernel.py")

# 从第 100 行开始读取，最多读取 50 行
read_file(file_path="src/core/kernel.py", offset=100, limit=50)
```

**返回示例**:

```
     1	import asyncio
     2	from pathlib import Path
     3	
     4	class Kernel:
     5	    """微内核实现"""
     6	    ...
```

**适用场景**:
- 查看源代码
- 读取配置文件
- 检查日志文件
- 审查文档内容

**注意事项**:
- 大文件请使用 offset 和 limit 参数
- 不支持读取二进制文件
- 文件不存在时返回错误

---

### 3. write_file - 写入文件

**类别**: FILE  
**最低权限**: Write

**描述**: 创建新文件或覆盖现有文件内容。

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `file_path` | string | 是 | 文件路径 |
| `content` | string | 是 | 文件内容 |

**使用示例**:

```python
# 创建新文件
write_file(
    file_path="docs/new_feature.md",
    content="# 新功能说明\n\n这是新功能的文档..."
)

# 覆盖现有文件
write_file(
    file_path="config.json",
    content='{"key": "value"}'
)
```

**适用场景**:
- 创建新文件
- 生成报告
- 导出数据
- 创建配置文件

**注意事项**:
- 会覆盖现有文件内容
- 需要 Write 权限
- 确保目录存在

---

### 4. edit_file - 编辑文件

**类别**: FILE  
**最低权限**: Write

**描述**: 精确替换文件中的文本内容，支持单次或全局替换。

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `file_path` | string | 是 | 文件路径 |
| `old_string` | string | 是 | 要替换的原始文本 |
| `new_string` | string | 是 | 替换后的新文本 |
| `replace_all` | boolean | 否 | 是否替换所有匹配项（默认 false） |

**使用示例**:

```python
# 单次替换
edit_file(
    file_path="src/core/kernel.py",
    old_string="    def start(self):\n        pass",
    new_string="    def start(self):\n        self.initialize()\n        self.run()"
)

# 全局替换
edit_file(
    file_path="config.py",
    old_string="DEBUG = True",
    new_string="DEBUG = False",
    replace_all=True
)
```

**返回示例**:

```
已编辑文件: src/core/kernel.py (1 处替换)
```

**适用场景**:
- 修复代码 Bug
- 更新函数实现
- 修改配置值
- 重构代码

**注意事项**:
- `old_string` 必须精确匹配（包括缩进和换行）
- 建议使用较小的替换字符串以提高准确性
- 需要 Write 权限

---

### 5. glob_search - 文件模式匹配搜索

**类别**: SEARCH  
**最低权限**: Read-only

**描述**: 使用 glob 模式搜索匹配的文件路径。

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `pattern` | string | 是 | glob 模式（如 `**/*.py`） |
| `path` | string | 否 | 搜索目录（默认当前目录） |
| `limit` | number | 否 | 结果数量限制（默认 100） |

**常用 glob 模式**:

| 模式 | 说明 | 示例匹配 |
|------|------|---------|
| `*.py` | 当前目录的 Python 文件 | `main.py` |
| `**/*.py` | 递归所有 Python 文件 | `src/core/kernel.py` |
| `**/test_*.py` | 所有测试文件 | `tests/test_kernel.py` |
| `**/*.{ts,tsx}` | TypeScript 文件 | `src/app.tsx` |
| `docs/**/*.md` | 文档目录的 Markdown | `docs/guide/README.md` |

**使用示例**:

```python
# 查找所有 Python 文件
glob_search(pattern="**/*.py")

# 查找测试文件
glob_search(pattern="**/test_*.py", limit=50)

# 在 docs 目录查找 Markdown 文件
glob_search(pattern="**/*.md", path="docs")
```

**返回示例**:

```
找到 15 个匹配:
- src/core/kernel.py
- src/core/memory/__init__.py
- src/services/auth_service.py
- tests/test_kernel.py
...
```

**适用场景**:
- 查找特定类型的文件
- 定位测试文件
- 探索项目结构
- 批量文件操作前确认目标

---

### 6. grep_search - 文本正则搜索

**类别**: SEARCH  
**最低权限**: Read-only

**描述**: 使用正则表达式在文件中搜索文本模式，支持上下文行显示。

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `pattern` | string | 是 | 正则表达式模式 |
| `path` | string | 否 | 搜索路径 |
| `glob` | string | 否 | 文件过滤模式（如 `*.py`） |
| `case_sensitive` | boolean | 否 | 是否区分大小写（默认 true） |
| `context` | number | 否 | 上下文行数（默认 0） |

**使用示例**:

```python
# 搜索函数定义
grep_search(pattern=r"def\s+\w+\s*\(", glob="**/*.py")

# 搜索类定义，显示 2 行上下文
grep_search(pattern=r"class\s+\w+", glob="**/*.py", context=2)

# 不区分大小写搜索
grep_search(pattern="TODO", case_sensitive=False)

# 在特定目录搜索
grep_search(pattern="permission", path="src/core/security")
```

**返回示例**:

```
>>> src/core/security/permissions.py:45: class AgentPermissions:
       """Agent 权限配置"""
       ...

>>> src/core/security/permissions.py:120: def check_command_safety(command, permissions):
       """检查命令安全性"""
```

**适用场景**:
- 查找函数或类定义
- 搜索特定代码模式
- 定位 TODO/FIXME 注释
- 查找 API 端点定义
- 审计安全相关代码

**注意事项**:
- 使用有效的正则表达式
- 大项目搜索可能需要一些时间
- 使用 glob 参数可以显著提高搜索效率

---

### 7. bash - Shell 命令执行

**类别**: EXECUTION  
**最低权限**: Shell

**描述**: 执行 Shell 命令，支持流式输出和超时控制。

**参数**:

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `command` | string | 是 | 要执行的 Shell 命令 |
| `timeout` | number | 否 | 超时时间（毫秒，默认 120000） |
| `cwd` | string | 否 | 工作目录 |

**使用示例**:

```python
# 查看文件列表
bash(command="ls -la")

# 查看 Git 状态
bash(command="git status")

# 运行测试
bash(command="pytest tests/ -v", timeout=300000)

# 安装依赖
bash(command="pip install -e .")

# 在特定目录执行
bash(command="npm run build", cwd="frontend")
```

**返回示例**:

```
$ git status
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

**适用场景**:
- 运行测试和构建
- 查看 Git 状态
- 安装依赖
- 执行脚本
- 系统信息查询

**安全限制**:
- 破坏性命令被阻止（如 `rm -rf`、`shutdown` 等）
- 需要 Shell 权限
- 破坏性命令需要 Unsafe 模式
- 有超时限制防止无限运行

**被阻止的破坏性命令**:
```bash
rm -rf /           # 强制递归删除
dd if=/dev/zero    # 磁盘写入
shutdown           # 关机
reboot             # 重启
mkfs               # 格式化
chmod -R 777       # 递归 777 权限
git reset --hard   # Git 硬重置
git clean -fd      # Git 清理未跟踪文件
sudo rm            # sudo 删除
```

---

## 工具权限要求

### 权限与工具映射

| 工具 | Read-only | Write | Shell | Unsafe |
|------|:---------:|:-----:|:-----:|:------:|
| `list_dir` | ✅ | ✅ | ✅ | ✅ |
| `read_file` | ✅ | ✅ | ✅ | ✅ |
| `write_file` | ❌ | ✅ | ✅ | ✅ |
| `edit_file` | ❌ | ✅ | ✅ | ✅ |
| `glob_search` | ✅ | ✅ | ✅ | ✅ |
| `grep_search` | ✅ | ✅ | ✅ | ✅ |
| `bash` | ❌ | ❌ | ✅ | ✅ |

### 权限不足时的行为

当工具调用权限不足时，会抛出 `ToolPermissionError` 或 `PermissionError`：

```python
# 没有 Write 权限时尝试写入
write_file(file_path="test.txt", content="hello")
# 抛出: ToolPermissionError("文件写入权限未启用，请使用 --allow-write 标志")

# 没有 Shell 权限时尝试执行命令
bash(command="ls -la")
# 抛出: ToolPermissionError("Shell 命令执行权限未启用，请使用 --allow-shell 标志")
```

### 权限检查流程

```
工具调用
    ↓
检查 AgentPermissions
    ↓
权限不足 -> 抛出 PermissionError
    ↓
权限足够 -> 执行工具
    ↓
对于 bash 工具: 检查命令安全性
    ↓
破坏性命令 -> 检查 Unsafe 模式
    ↓
执行并返回结果
```

---

## 使用示例

### 示例 1：项目分析（只读权限）

```bash
# 启动只读模式
./dfecrab
```

```python
# 探索项目结构
list_dir(path=".")

# 查找所有 Python 文件
glob_search(pattern="**/*.py")

# 搜索主入口
grep_search(pattern="if __name__", glob="**/*.py")

# 读取主文件
read_file(file_path="src/core/kernel.py")
```

### 示例 2：代码修改（Write 权限）

```bash
# 启动带写入权限
./dfecrab --allow-write
```

```python
# 读取现有代码
read_file(file_path="src/core/kernel.py")

# 修改函数实现
edit_file(
    file_path="src/core/kernel.py",
    old_string="    def initialize(self):\n        pass",
    new_string="    def initialize(self):\n        self.load_config()\n        self.setup_logging()"
)

# 创建新文件
write_file(
    file_path="src/core/utils/helper.py",
    content="def format_output(data):\n    return str(data)\n"
)
```

### 示例 3：自动化测试（Shell 权限）

```bash
# 启动带 Shell 执行权限
./dfecrab --allow-write --allow-shell
```

```python
# 查看 Git 状态
bash(command="git status")

# 运行测试
bash(command="pytest tests/ -v --tb=short", timeout=300000)

# 查看测试结果
read_file(file_path="tests/test_results.xml")

# 如果有失败，搜索失败原因
grep_search(pattern="FAILED", glob="**/test_*.py", context=3)
```

### 示例 4：代码重构（组合使用）

```python
# 1. 找到所有使用旧函数的地方
grep_search(pattern="old_function_name", glob="**/*.py")

# 2. 读取相关文件确认上下文
read_file(file_path="src/module/file1.py")

# 3. 逐个编辑替换
edit_file(
    file_path="src/module/file1.py",
    old_string="old_function_name(args)",
    new_string="new_function_name(args)"
)

# 4. 运行测试验证
bash(command="pytest tests/test_module.py -v")
```

### 示例 5：依赖管理

```python
# 查看当前依赖
read_file(file_path="requirements.txt")

# 安装新依赖
bash(command="pip install requests")

# 验证安装
bash(command="python -c 'import requests; print(requests.__version__)'")

# 更新 requirements.txt
edit_file(
    file_path="requirements.txt",
    old_string="# 网络请求库",
    new_string="# 网络请求库\nrequests>=2.28.0"
)
```

---

## 最佳实践

### 1. 选择合适的工具

| 场景 | 推荐工具 | 原因 |
|------|---------|------|
| 查看目录结构 | `list_dir` | 快速了解文件组织 |
| 读取小文件 | `read_file` | 简单直接 |
| 读取大文件 | `read_file` + offset/limit | 避免加载全部内容 |
| 精确修改 | `edit_file` | 安全、可追溯 |
| 创建文件 | `write_file` | 直接创建 |
| 查找文件 | `glob_search` | 模式匹配高效 |
| 查找代码 | `grep_search` | 正则搜索强大 |
| 运行命令 | `bash` | 灵活执行 |

### 2. 搜索优化

```python
# 不推荐：搜索整个项目
grep_search(pattern="function_name")

# 推荐：限定文件类型
grep_search(pattern="function_name", glob="**/*.py")

# 推荐：限定目录
grep_search(pattern="function_name", path="src/core")
```

### 3. 安全编辑

```python
# 不推荐：大段替换容易出错
edit_file(
    file_path="large_file.py",
    old_string="... 100 lines ...",
    new_string="... 100 new lines ..."
)

# 推荐：小段精确替换
edit_file(
    file_path="large_file.py",
    old_string="    return old_value",
    new_string="    return new_value"
)
```

### 4. 命令执行安全

```python
# 不推荐：使用破坏性命令
bash(command="rm -rf build/")  # 被阻止

# 推荐：使用安全替代方案
bash(command="rm -rf build/*")  # 清空内容而非目录
# 或使用 trash 而非 rm
bash(command="trash build/")
```

### 5. 超时设置

```python
# 不推荐：不设置超时（可能无限等待）
bash(command="python long_running_script.py")

# 推荐：设置合理超时
bash(command="python long_running_script.py", timeout=600000)  # 10 分钟
```

### 6. 结果处理

```python
# 工具返回结果后，先检查结果状态
result = execute_tool(...)
if result.success:
    # 处理成功结果
    process_output(result.output)
else:
    # 处理错误情况
    handle_error(result.error)
```

### 7. 流式输出

对于长时间运行的命令（如测试、构建），使用流式输出可以实时查看进度：

```python
# bash 工具支持流式执行
for update in execute_tool_streaming(..., name="bash", ...):
    if update.kind == 'output':
        print(update.content, end='')
    elif update.kind == 'result':
        print(f"\n执行完成: {update.result.ok}")
```

---

## 常见问题解答

### Q1: 工具调用失败怎么办？

检查以下几点：
1. **权限是否足够**：使用 `/permissions` 查看当前权限
2. **参数是否正确**：检查必需参数是否提供
3. **路径是否存在**：确认文件或目录存在
4. **错误信息**：查看返回的 error 字段

### Q2: edit_file 替换失败怎么办？

`edit_file` 要求 `old_string` 精确匹配。如果失败：
1. 使用 `read_file` 查看文件实际内容
2. 确认缩进、换行符完全匹配
3. 考虑使用更小的替换字符串
4. 对于大量修改，考虑使用 `write_file` 覆盖

### Q3: bash 命令执行超时怎么办？

1. 增加 timeout 参数
2. 检查命令是否卡住或进入死循环
3. 在后台运行长时间任务
4. 使用流式输出监控进度

### Q4: 如何查看工具的执行历史？

工具执行会被记录到审计日志中。可以通过以下方式查看：

```python
# 访问工具的审计日志
tool = BashTool()
for log in tool._audit_logs:
    print(log.to_dict())
```

### Q5: glob_search 和 grep_search 有什么区别？

- **glob_search**：搜索**文件路径**，使用 glob 模式匹配文件名
- **grep_search**：搜索**文件内容**，使用正则表达式匹配文本

```python
# 找所有 .py 文件 -> glob_search
glob_search(pattern="**/*.py")

# 找包含 "permission" 的代码行 -> grep_search
grep_search(pattern="permission", glob="**/*.py")
```

### Q6: 工具执行是否支持并发？

当前工具执行是顺序的。对于需要并发的场景，建议：
1. 将任务分解为多个独立步骤
2. 使用 bash 命令执行并行操作
3. 未来版本可能支持并发工具调用

### Q7: 如何扩展自定义工具？

继承 `BaseTool` 类并实现必要方法：

```python
from src.core.tools import BaseTool, ToolResult, ToolCategory

class MyCustomTool(BaseTool):
    @property
    def name(self) -> str:
        return "MyTool"

    @property
    def description(self) -> str:
        return "我的自定义工具"

    @property
    def category(self) -> ToolCategory:
        return ToolCategory.FILE

    async def execute(self, params, context) -> ToolResult:
        # 实现工具逻辑
        return ToolResult(
            success=True,
            status=ToolStatus.SUCCESS,
            output="工具执行成功"
        )
```

### Q8: 工具的最大输出限制是多少？

默认情况下，工具输出限制为 12,000 字符。超出部分会被截断。对于大量输出：
1. 使用 limit 参数限制输出
2. 将输出重定向到文件
3. 使用流式输出处理

---

## 相关文档

- [权限配置指南](../01-基础篇/PERMISSION_GUIDE.md) - 了解权限系统
- [斜杠命令使用指南](../01-基础篇/SLASH_COMMANDS.md) - 了解 `/tools` 等命令
- [工作区配置指南](../02-使用篇/WORKSPACE_CONFIG.md) - 了解工作区配置

---

**文档版本**: 1.0  
**最后更新**: 2026-04-04  
**维护者**: DFEcrab Team
