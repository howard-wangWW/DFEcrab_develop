# DFEcrab 测试套件

## 📋 概述

本目录包含 DFEcrab 项目的所有测试脚本，涵盖：
- 单元测试
- 集成测试
- API 测试
- 功能测试

## 🗂️ 测试文件分类

### 核心功能测试
- `test_architecture.py` - 架构测试
- `test_invariants.py` - 不变量测试
- `test_plugins.py` - 插件系统测试
- `test_memory.py` - 记忆系统测试
- `test_session_memory.py` - 会话记忆测试

### 集成测试
- `test_agentscope_integration.py` - AgentScope 集成测试
- `test_simple_integration.py` - 简单集成测试
- `test_deepseek_integration.py` - DeepSeek 集成测试
- `test_distributed_architecture.py` - 分布式架构测试

### API 测试
- `test_task_api.py` - 任务管理 API 测试
- `test_reflection_api.py` - 自我反思 API 测试
- `test_routing.py` - 路由 API 测试
- `test_gateway_core.py` - Gateway 核心测试

### 功能测试
- `test_manual_reflection.py` - 手动反思测试
- `test_complete_todo.py` - 待办任务完成测试
- `test_model_config.py` - 模型配置测试
- `test_model_support.py` - 模型支持测试

### 技能测试
- `test_find_skill.py` - 技能查找测试
- `test_find_skill_demo.py` - 技能查找演示测试
- `test_weather_skill_auto_install.py` - 天气技能自动安装测试
- `test_clawhub_weather_install.py` - ClawHub 天气技能安装测试

### 其他测试
- `test_discovery.py` - 服务发现测试
- `test_reflection.py` - 反思系统测试
- `check_prompt.py` - 提示检查
- `debug_toolkit.py` - 调试工具包

## 🚀 运行测试

### 前置条件

1. 确保项目已安装
```bash
cd /Users/zhanghanzhi/DFEcrab
pip install -e .
```

2. 启动 Gateway 服务
```bash
python3 -m src gateway start
```

3. 安装测试依赖
```bash
pip install pytest pytest-asyncio requests
```

### 运行单个测试

```bash
# 运行任务管理 API 测试
cd tests
python3 test_task_api.py

# 运行手动反思测试
python3 test_manual_reflection.py

# 运行记忆系统测试
python3 test_memory.py
```

### 运行所有测试

```bash
# 使用 pytest 运行所有测试
pytest tests/ -v

# 运行特定类型的测试
pytest tests/test_api*.py -v
pytest tests/test_integration*.py -v
```

### 运行测试并生成报告

```bash
# 生成 HTML 报告
pytest tests/ --html=report.html

# 生成覆盖率报告
pytest tests/ --cov=src --cov-report=html
```

## 📊 测试用例说明

### test_task_api.py
测试任务管理系统的 API 接口：
- ✅ 获取任务统计
- ✅ 查看心跳任务
- ✅ 查看定时任务
- ✅ 添加待办任务
- ✅ 完成待办任务

**运行条件：** Gateway 服务必须运行

### test_manual_reflection.py
测试自我反思系统：
- ✅ 手动触发反思
- ✅ 分析对话历史
- ✅ 生成反思报告

**运行条件：** Gateway 服务必须运行

### test_complete_todo.py
测试待办任务完成功能：
- ✅ 获取待办列表
- ✅ 完成任务
- ✅ 验证状态更新

**运行条件：** Gateway 服务必须运行

### test_memory.py
测试记忆系统：
- ✅ 创建记忆
- ✅ 读取记忆
- ✅ 记忆压缩
- ✅ 记忆检索

**运行条件：** Gateway 服务必须运行

### test_plugins.py
测试插件系统：
- ✅ 插件加载
- ✅ 插件注册
- ✅ 插件生命周期

**运行条件：** 无需运行服务

## 🔧 调试测试

### 启用详细日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 使用调试工具包

```bash
python3 tests/debug_toolkit.py
```

提供以下功能：
- 检查服务状态
- 清理测试数据
- 重置测试环境

## 📝 编写新测试

### 测试模板

```python
"""测试模块说明"""
import pytest
from pathlib import Path
import sys

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_example():
    """测试用例"""
    assert True

@pytest.mark.asyncio
async def test_async_example():
    """异步测试用例"""
    assert True
```

### 测试规范

1. **命名规范**
   - 文件名：`test_<功能>.py`
   - 函数名：`test_<功能描述>()`

2. **断言规范**
   - 使用 `assert` 进行断言
   - 提供清晰的错误信息

3. **异步测试**
   - 使用 `@pytest.mark.asyncio` 装饰器
   - 使用 `async/await` 语法

## 🎯 测试覆盖率

查看测试覆盖率：

```bash
# 生成覆盖率报告
coverage run -m pytest tests/
coverage report

# 生成 HTML 报告
coverage html
open htmlcov/index.html
```

## 🐛 常见问题

### Q: 测试失败 "ModuleNotFoundError"
**A:** 确保已添加项目根目录到 Python 路径

```python
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
```

### Q: Gateway 连接失败
**A:** 确保 Gateway 服务正在运行

```bash
# 检查 Gateway 状态
curl http://localhost:6789/health

# 启动 Gateway
python3 -m src gateway start
```

### Q: 异步测试不执行
**A:** 确保安装了 `pytest-asyncio`

```bash
pip install pytest-asyncio
```

## 📚 相关文档

- [任务调度系统文档](../TASK_SCHEDULER_SYSTEM.md)
- [自我反思系统文档](../SELF_REFLECTION_SYSTEM.md)
- [记忆系统文档](../MEMORY_SYSTEM.md)
- [项目概览](../PROJECT_OVERVIEW.md)

## 🔄 持续集成

测试会自动在以下场景运行：
- 代码提交前
- Pull Request 创建时
- 每日构建时

## 💡 最佳实践

1. **隔离测试**
   - 每个测试独立
   - 不依赖其他测试的状态
   - 使用临时数据

2. **快速失败**
   - 测试应该快速执行
   - 失败时提供清晰的错误信息

3. **覆盖边界条件**
   - 测试正常流程
   - 测试异常流程
   - 测试边界值

4. **保持测试更新**
   - 代码变更时更新测试
   - 删除过时的测试
   - 添加新功能的测试

---

**文档版本**: 1.0
**更新时间**: 2026-03-29
**维护者**: DFEcrab Team
