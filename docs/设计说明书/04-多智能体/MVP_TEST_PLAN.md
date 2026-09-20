# 多智能体交互 MVP 测试方案

**目标**：验证 QwenCode、CodeBuddy、DFEcrab 三个智能体能否实际交互
**时间**：2 小时
**风险**：低（不影响现有系统）

---

## 1. 现状调查

首先需要确认三个智能体的**实际接入方式**：

### 1.1 调查清单

| 智能体 | 需要确认的问题 |
|--------|--------------|
| **QwenCode** | 1. 是否有 API 接口？<br>2. 是否有 CLI 命令行工具？<br>3. 是否支持 WebSocket？<br>4. 运行在哪个端口？ |
| **CodeBuddy** | 1. 是否有 API 接口？<br>2. 是否有 CLI 命令行工具？<br>3. 是否支持 WebSocket？<br>4. 运行在哪个端口？ |
| **DFEcrab** | 1. 当前 Gateway 端口？<br>2. 是否有 HTTP API？<br>3. 是否有 WebSocket？ |

### 1.2 快速调查命令

```bash
# 检查 DFEcrab Gateway
curl http://localhost:6789/health

# 检查 QwenCode（假设端口 8080）
curl http://localhost:8080/health

# 检查 CodeBuddy（假设端口 8081）
curl http://localhost:8081/health

# 检查进程
ps aux | grep -E "qwencode|codebuddy|dfecrab"

# 检查监听端口
lsof -i -P -n | grep LISTEN
```

---

## 2. MVP 测试方案

### 方案 A：如果三个智能体都有 HTTP API

**架构**：
```
┌─────────────────────────────────────────────────────────┐
│              简单编排器（Python 脚本）                   │
│                                                         │
│  用户输入 → DFEcrab 分析 → QwenCode 编码 → CodeBuddy 审查 │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**测试脚本**：
```python
# test_multi_agent_mvp.py
# 多智能体交互 MVP 测试

import asyncio
import httpx

# 配置
AGENT_CONFIG = {
    "dfecrab": {"url": "http://localhost:6789/api/chat"},
    "qwencode": {"url": "http://localhost:8080/api/v1/chat"},
    "codebuddy": {"url": "http://localhost:8081/api/v1/chat"},
}

async def chat_with_agent(agent: str, message: str, context: dict = None) -> str:
    """与智能体对话"""
    config = AGENT_CONFIG.get(agent)
    if not config:
        return f"❌ 智能体 {agent} 未配置"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                config["url"],
                json={"message": message, "context": context or {}}
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("response", "")
            else:
                return f"❌ {agent} 返回错误：{response.status_code}"
    
    except Exception as e:
        return f"❌ {agent} 连接失败：{e}"

async def test_chain_collaboration():
    """测试链式协作"""
    print("=" * 60)
    print("🧪 多智能体交互 MVP 测试 - 链式协作")
    print("=" * 60)
    
    user_input = "帮我写一个 Python 函数，计算两个数的和"
    print(f"\n👤 用户：{user_input}\n")
    
    # Step 1: DFEcrab 分析需求
    print("🦀 DFEcrab 分析需求...")
    analysis = await chat_with_agent(
        "dfecrab",
        f"请分析这个需求，并输出技术要点：{user_input}"
    )
    print(f"🦀 DFEcrab: {analysis}\n")
    
    # Step 2: QwenCode 生成代码
    print("🤖 QwenCode 生成代码...")
    code = await chat_with_agent(
        "qwencode",
        f"请根据以下需求生成 Python 代码：\n需求：{user_input}\n分析：{analysis}"
    )
    print(f"🤖 QwenCode: {code}\n")
    
    # Step 3: CodeBuddy 审查代码
    print("🤖 CodeBuddy 审查代码...")
    review = await chat_with_agent(
        "codebuddy",
        f"请审查以下代码，指出问题和改进建议：\n{code}"
    )
    print(f"🤖 CodeBuddy: {review}\n")
    
    # Step 4: DFEcrab 汇总
    print("🦀 DFEcrab 汇总结果...")
    summary = await chat_with_agent(
        "dfecrab",
        f"请汇总本次协作的结果：\n需求：{user_input}\n分析：{analysis}\n代码：{code}\n审查：{review}"
    )
    print(f"🦀 DFEcrab: {summary}\n")
    
    print("=" * 60)
    print("✅ 测试完成")
    print("=" * 60)

async def main():
    try:
        await test_chain_collaboration()
    except KeyboardInterrupt:
        print("\n❌ 测试中断")
    except Exception as e:
        print(f"\n❌ 测试失败：{e}")

if __name__ == "__main__":
    asyncio.run(main())
```

**运行测试**：
```bash
# 1. 确保三个智能体都在运行
# 2. 安装依赖
pip install httpx asyncio

# 3. 运行测试
python test_multi_agent_mvp.py
```

---

### 方案 B：如果智能体只有 CLI 命令行

**架构**：
```
┌─────────────────────────────────────────────────────────┐
│              编排器（调用 CLI 命令）                      │
│                                                         │
│  用户输入 → DFEcrab → QwenCode → CodeBuddy → 汇总       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**测试脚本**：
```python
# test_multi_agent_cli.py
# 多智能体交互 MVP 测试（CLI 版本）

import asyncio
import subprocess

async def run_cli_command(command: list) -> str:
    """运行 CLI 命令"""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            return stdout.decode('utf-8')
        else:
            return f"❌ 命令失败：{stderr.decode('utf-8')}"
    
    except Exception as e:
        return f"❌ 执行失败：{e}"

async def test_cli_collaboration():
    """测试 CLI 协作"""
    print("=" * 60)
    print("🧪 多智能体交互 MVP 测试 - CLI 版本")
    print("=" * 60)
    
    user_input = "帮我写一个 Python 函数，计算两个数的和"
    print(f"\n👤 用户：{user_input}\n")
    
    # Step 1: DFEcrab 分析
    print("🦀 DFEcrab 分析需求...")
    analysis = await run_cli_command([
        "dfecrab", "chat", "-m", f"请分析这个需求：{user_input}"
    ])
    print(f"🦀 DFEcrab: {analysis}\n")
    
    # Step 2: QwenCode 生成代码
    print("🤖 QwenCode 生成代码...")
    code = await run_cli_command([
        "qwencode", "generate", "-p", f"{user_input}\n分析：{analysis}"
    ])
    print(f"🤖 QwenCode: {code}\n")
    
    # Step 3: CodeBuddy 审查
    print("🤖 CodeBuddy 审查代码...")
    review = await run_cli_command([
        "codebuddy", "review", "-c", code
    ])
    print(f"🤖 CodeBuddy: {review}\n")
    
    print("=" * 60)
    print("✅ 测试完成")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_cli_collaboration())
```

---

### 方案 C：如果智能体都没有 API/CLI（最坏情况）

**架构**：通过**文件系统**进行交互

```
┌─────────────────────────────────────────────────────────┐
│              编排器（读写文件）                           │
│                                                         │
│  /tmp/input.txt → DFEcrab → QwenCode → CodeBuddy       │
│       ↓              ↓           ↓           ↓          │
│   用户输入      分析输出    代码输出    审查输出         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**测试脚本**：
```python
# test_multi_agent_file.py
# 多智能体交互 MVP 测试（文件版本）

import asyncio
import time
from pathlib import Path

WORK_DIR = Path("/tmp/multi_agent_test")
WORK_DIR.mkdir(exist_ok=True)

async def wait_for_file(file_path: Path, timeout: int = 30) -> str:
    """等待文件出现并读取内容"""
    start_time = time.time()
    
    while not file_path.exists():
        if time.time() - start_time > timeout:
            raise TimeoutError(f"等待文件超时：{file_path}")
        await asyncio.sleep(0.5)
    
    # 等待文件写入完成
    await asyncio.sleep(1)
    return file_path.read_text(encoding='utf-8')

async def test_file_collaboration():
    """测试文件协作"""
    print("=" * 60)
    print("🧪 多智能体交互 MVP 测试 - 文件版本")
    print("=" * 60)
    
    user_input = "帮我写一个 Python 函数，计算两个数的和"
    print(f"\n👤 用户：{user_input}\n")
    
    # Step 1: 写入用户输入
    input_file = WORK_DIR / "input.txt"
    input_file.write_text(user_input, encoding='utf-8')
    
    # Step 2: DFEcrab 分析（需要 DFEcrab 监控文件并输出）
    analysis_file = WORK_DIR / "analysis.txt"
    print("🦀 等待 DFEcrab 分析...")
    # 这里需要 DFEcrab 有文件监控功能
    # 或者手动触发 DFEcrab 处理
    
    # ... 类似处理其他智能体
    
    print("=" * 60)
    print("⚠️  文件方式需要智能体支持文件监控")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_file_collaboration())
```

---

## 3. 快速验证步骤

### Step 1: 调查三个智能体的接口能力（15 分钟）

```bash
# 1. 检查 DFEcrab
echo "=== DFEcrab ==="
curl -s http://localhost:6789/health | jq .
curl -s http://localhost:6789/api/chat -H "Content-Type: application/json" -d '{"message":"hello"}' | jq .

# 2. 检查 QwenCode
echo "=== QwenCode ==="
# 先找到 QwenCode 的运行方式和端口
ps aux | grep qwencode
lsof -i -P -n | grep LISTEN | grep qwencode

# 3. 检查 CodeBuddy
echo "=== CodeBuddy ==="
ps aux | grep codebuddy
```

### Step 2: 根据调查结果选择方案（5 分钟）

| 调查结果 | 选择方案 |
|---------|---------|
| 三个都有 HTTP API | 方案 A（最简单） |
| 有 CLI 命令 | 方案 B |
| 都没有 | 方案 C 或 需要开发适配器 |

### Step 3: 运行 MVP 测试（30 分钟）

```bash
# 下载测试脚本
# 根据实际情况修改 AGENT_CONFIG

# 运行测试
python test_multi_agent_mvp.py
```

### Step 4: 分析结果（10 分钟）

**成功**：
- ✅ 三个智能体都能响应
- ✅ 消息能正确传递
- ✅ 结果能正确汇总

**失败**：
- ❌ 某个智能体无法连接 → 需要开发适配器
- ❌ 响应格式不一致 → 需要格式转换
- ❌ 超时 → 需要增加超时时间或优化

---

## 4. 预期结果

### 最佳情况（方案 A 成功）

```
============================================================
🧪 多智能体交互 MVP 测试 - 链式协作
============================================================

👤 用户：帮我写一个 Python 函数，计算两个数的和

🦀 DFEcrab 分析需求...
🦀 DFEcrab: 这个需求需要一个简单的加法函数，需要考虑：
1. 参数类型验证（应该是数字）
2. 返回值类型
3. 错误处理（非数字输入）

🤖 QwenCode 生成代码...
🤖 QwenCode: def add(a, b):
    """计算两个数的和"""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("参数必须是数字")
    return a + b

🤖 CodeBuddy 审查代码...
🤖 CodeBuddy: 代码整体不错，建议：
1. 添加 docstring 说明返回值
2. 考虑添加类型注解
3. 可以支持更多数字类型（如 Decimal）

🦀 DFEcrab 汇总结果...
🦀 DFEcrab: 任务完成！代码已生成并通过审查。
建议采纳 CodeBuddy 的建议，添加类型注解和更完善的文档。

============================================================
✅ 测试完成
============================================================
```

### 最坏情况

```
============================================================
🧪 多智能体交互 MVP 测试 - 链式协作
============================================================

👤 用户：帮我写一个 Python 函数，计算两个数的和

❌ qwencode 连接失败：Connection refused
❌ codebuddy 连接失败：Connection refused
🦀 DFEcrab: 这个需求需要一个简单的加法函数...

============================================================
⚠️  只有 DFEcrab 可用，其他智能体无法连接
============================================================
```

---

## 5. 后续行动

### 如果 MVP 测试成功

1. ✅ 确认可行性
2. 完善编排器逻辑
3. 添加错误处理
4. 开发 TUI 界面
5. 写入 TODO.md 阶段九

### 如果 MVP 测试失败

1. ❌ 分析失败原因
2. 开发对应的适配器
3. 或者调整交互方案
4. 重新测试

---

## 6. 测试脚本（完整版）

```python
#!/usr/bin/env python3
"""
多智能体交互 MVP 测试

测试 QwenCode、CodeBuddy、DFEcrab 三个智能体能否协同工作
"""

import asyncio
import httpx
import json
from typing import Optional, Dict, Any

# ============ 配置区 ============

AGENT_CONFIG = {
    "dfecrab": {
        "name": "DFEcrab",
        "url": "http://localhost:6789/api/chat",
        "icon": "🦀",
        "role": "coordinator"
    },
    "qwencode": {
        "name": "QwenCode",
        "url": "http://localhost:8080/api/v1/chat",
        "icon": "🤖",
        "role": "developer"
    },
    "codebuddy": {
        "name": "CodeBuddy",
        "url": "http://localhost:8081/api/v1/chat",
        "icon": "🤖",
        "role": "reviewer"
    },
}

# ============ 核心逻辑 ============

class AgentClient:
    """智能体客户端"""
    
    def __init__(self, agent_id: str, config: Dict[str, Any]):
        self.agent_id = agent_id
        self.name = config.get("name", agent_id)
        self.url = config.get("url")
        self.icon = config.get("icon", "🤖")
        self.role = config.get("role", "assistant")
        self._client = httpx.AsyncClient(timeout=60.0)
    
    async def chat(self, message: str, context: Dict = None) -> str:
        """与智能体对话"""
        if not self.url:
            return f"❌ {self.name} 未配置 URL"
        
        try:
            response = await self._client.post(
                self.url,
                json={"message": message, "context": context or {}}
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("response", "")
            else:
                return f"❌ {self.name} 返回错误：{response.status_code}"
        
        except httpx.ConnectError:
            return f"❌ {self.name} 连接失败（可能未运行）"
        except Exception as e:
            return f"❌ {self.name} 错误：{e}"
    
    async def close(self):
        await self._client.aclose()


class MultiAgentOrchestrator:
    """多智能体编排器"""
    
    def __init__(self):
        self.agents: Dict[str, AgentClient] = {}
        for agent_id, config in AGENT_CONFIG.items():
            self.agents[agent_id] = AgentClient(agent_id, config)
    
    async def test_chain_collaboration(self, user_input: str):
        """测试链式协作"""
        print("=" * 60)
        print("🧪 多智能体交互 MVP 测试 - 链式协作")
        print("=" * 60)
        print(f"\n👤 用户：{user_input}\n")
        
        results = {}
        
        # Step 1: DFEcrab 分析
        dfecrab = self.agents.get("dfecrab")
        if dfecrab:
            print(f"{dfecrab.icon} {dfecrab.name} 分析需求...")
            analysis = await dfecrab.chat(
                f"请分析这个需求，并输出技术要点：{user_input}"
            )
            print(f"{dfecrab.icon} {dfecrab.name}: {analysis}\n")
            results["analysis"] = analysis
        else:
            print("⚠️ DFEcrab 未配置")
            return
        
        # Step 2: QwenCode 生成代码
        qwencode = self.agents.get("qwencode")
        if qwencode:
            print(f"{qwencode.icon} {qwencode.name} 生成代码...")
            code = await qwencode.chat(
                f"请根据以下需求生成 Python 代码：\n需求：{user_input}\n分析：{analysis}"
            )
            print(f"{qwencode.icon} {qwencode.name}: {code}\n")
            results["code"] = code
        else:
            print("⚠️ QwenCode 未配置")
            return
        
        # Step 3: CodeBuddy 审查
        codebuddy = self.agents.get("codebuddy")
        if codebuddy:
            print(f"{codebuddy.icon} {codebuddy.name} 审查代码...")
            review = await codebuddy.chat(
                f"请审查以下代码，指出问题和改进建议：\n{code}"
            )
            print(f"{codebuddy.icon} {codebuddy.name}: {review}\n")
            results["review"] = review
        else:
            print("⚠️ CodeBuddy 未配置")
        
        # Step 4: DFEcrab 汇总
        if dfecrab:
            print(f"{dfecrab.icon} {dfecrab.name} 汇总结果...")
            summary = await dfecrab.chat(
                f"请汇总本次协作的结果：\n需求：{user_input}\n分析：{analysis}\n代码：{code}\n审查：{review}"
            )
            print(f"{dfecrab.icon} {dfecrab.name}: {summary}\n")
            results["summary"] = summary
        
        print("=" * 60)
        print("✅ 测试完成")
        print("=" * 60)
        
        # 保存结果
        with open("test_result.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("📄 结果已保存到 test_result.json")
    
    async def close(self):
        for agent in self.agents.values():
            await agent.close()


async def main():
    orchestrator = MultiAgentOrchestrator()
    
    try:
        # 测试输入
        user_input = "帮我写一个 Python 函数，计算两个数的和"
        
        await orchestrator.test_chain_collaboration(user_input)
    
    except KeyboardInterrupt:
        print("\n❌ 测试中断")
    except Exception as e:
        print(f"\n❌ 测试失败：{e}")
        import traceback
        traceback.print_exc()
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
```

---

**文档版本**：1.0  
**创建时间**：2026-03-30  
**审阅状态**：待测试
