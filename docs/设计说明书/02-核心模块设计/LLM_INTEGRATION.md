# DFEcrab 大模型集成设计文档

> **生成日期**: 2026-04-05
> **适用版本**: DFEcrab v4.0.0
> **文档类型**: 架构设计

---

## 📋 目录

- [架构概述](#架构概述)
- [llama.cpp server 配置](#llamacpp-server-配置)
- [Agent 调用机制](#agent-调用机制)
- [上下文传递](#上下文传递)
- [智能内容生成](#智能内容生成)
- [配置管理](#配置管理)
- [测试验证](#测试验证)
- [故障排查](#故障排查)

---

## 架构概述

### 集成方式

DFEcrab 通过 **OpenAI 兼容 API** 连接远程大模型：

```
┌─────────────────────────────────────┐
│         Agent Service               │
│                                     │
│  reporter_agent                     │
│  ├── 检查任务类型                    │
│  ├── 非规则模板场景                  │
│  └── 调用远程大模型                  │
└──────────────┬──────────────────────┘
               │ HTTP POST
               ▼
┌─────────────────────────────────────┐
│     llama.cpp server                │
│     (192.168.1.150:4096)           │
│                                     │
│  /v1/chat/completions               │
│  - OpenAI 兼容 API                   │
│  - 支持流式输出                      │
│  - 支持多模型                        │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│         LLM 模型                     │
│                                     │
│  Qwen3-Coder-30B-A3B-Instruct-4bit │
│  - 4bit 量化                         │
│  - 30B 参数                          │
│  - 代码和文本生成                    │
└─────────────────────────────────────┘
```

### 设计原则

| 原则 | 说明 |
|------|------|
| **上下文完整** | 传递完整的 session 历史，让大模型理解上下文 |
| **智能判断** | 由大模型理解用户意图，而非写死规则 |
| **Fallback 机制** | 大模型调用失败时，使用简单规则兜底 |
| **配置灵活** | 支持通过配置文件修改模型地址和参数 |

---

## llama.cpp server 配置

### 服务信息

| 配置项 | 值 |
|--------|-----|
| **地址** | `http://192.168.1.150:4096` |
| **模型路径** | `/Users/e8900ai/LLM_Fine/models/qwen/Qwen3-Coder-30B-A3B-Instruct-4bit` |
| **API 端点** | `/v1/chat/completions` |
| **协议** | OpenAI 兼容 |

### 验证服务

```bash
# 检查服务健康状态
curl http://192.168.1.150:4096/health

# 查看可用模型
curl http://192.168.1.150:4096/v1/models

# 测试对话
curl http://192.168.1.150:4096/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "/Users/e8900ai/LLM_Fine/models/qwen/Qwen3-Coder-30B-A3B-Instruct-4bit",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false,
    "max_tokens": 100
  }'
```

---

## Agent 调用机制

### 调用流程

```
用户请求: "改成秋天"
         ↓
Gateway 构建增强消息
         ↓
Manager 分发给 reporter_agent
         ↓
reporter_agent 检查任务类型
         ↓
非电网数据报告 → 调用大模型
         ↓
构建 prompt（含完整上下文）
         ↓
POST /v1/chat/completions
         ↓
接收生成内容
         ↓
返回给 Manager
```

### 代码实现

**位置**: `services/agent_service/agent_service_grpc.py`

```python
def _execute_reporter_skills(self, skills: list, input_data: Dict, instruction: str) -> Any:
    """执行报告员技能 - 使用大模型生成内容"""
    
    # 判断是否为电网数据分析报告
    if "analysis_result" in input_data or "数据分析" in str(analysis_data):
        # 使用规则模板生成电网报告
        return generate_grid_report(analysis_data)
    else:
        # 通用文本生成 - 调用大模型
        return self._call_llm(input_data.get("message", ""))

def _call_llm(self, message: str) -> Any:
    """调用远程大模型"""
    
    llm_url = "http://192.168.1.150:4096/v1/chat/completions"
    model_name = "/Users/e8900ai/LLM_Fine/models/qwen/Qwen3-Coder-30B-A3B-Instruct-4bit"
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": message}
        ],
        "stream": False,
        "temperature": 0.7
    }
    
    response = requests.post(llm_url, json=payload, timeout=60)
    result = response.json()
    generated_content = result["choices"][0]["message"]["content"]
    
    return {"report_content": generated_content, "status": "success"}
```

---

## 上下文传递

### 增强消息构建

Gateway 在调用 Manager 前，会构建包含完整上下文的增强消息：

```python
def _build_enhanced_message(self, message, session_id, session_summary, session_history):
    """构建增强的消息，包含 session 上下文"""
    
    if session_history:
        history_text = "\n\n".join([
            f"[{'用户' if m['role'] == 'user' else '助手'}]: {m['content']}"
            for m in session_history[-5:]  # 最近 5 条
        ])
        
        enhanced = f"""[会话上下文]
主题: {session_summary}
Session ID: {session_id}

历史对话:
{history_text}

---
当前消息: {message}"""
    else:
        enhanced = f"""[新会话]
主题: {session_summary}
Session ID: {session_id}

消息: {message}"""
    
    return enhanced
```

### Agent 提取当前消息

Agent 收到增强消息后，会提取"当前消息"部分：

```python
# 提取"当前消息"部分（如果消息被 Gateway 增强了）
current_message = message
if "当前消息:" in message:
    current_message = message.split("当前消息:")[-1].strip()
```

### 上下文理解示例

**场景**: 用户说"改成秋天"

**增强消息**:
```
[会话上下文]
主题: 文学创作任务
Session ID: session_xxx

历史对话:
[用户]: 写一首春天的诗
[助手]: # 春之韵
        春风拂面柳依依，
        百花齐放映朝晖。
        ...

---
当前消息: 改成秋天
```

**大模型理解**:
- 之前写的是春天的诗
- 现在要求改成秋天
- 应该保持诗歌格式，但内容改成秋天主题

**生成结果**:
```
秋风染红叶，雁阵向南飞。
霜露沾草尖，收获满田归。
```

---

## 智能内容生成

### 支持的场景

| 场景 | 处理方式 |
|------|----------|
| **电网数据报告** | 规则模板生成（快速、稳定）|
| **诗歌创作** | 大模型生成（智能、灵活）|
| **通用文本** | 大模型生成 |
| **代码生成** | 大模型生成 |

### 诗歌生成示例

**测试 1：春天**
```bash
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "写一首春天的诗"}'
```

**响应**:
```
# 春之韵

春风拂面柳依依，
百花齐放映朝晖。
燕舞莺啼生机盎，
万物复苏展新颜。
```

**测试 2：改成秋天**
```bash
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "改成秋天", "session_id": "session_xxx"}'
```

**响应**:
```
秋风染红叶，雁阵向南飞。
霜露沾草尖，收获满田归。
```

**测试 3：改成夏天**
```bash
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "改成夏天", "session_id": "session_xxx"}'
```

**响应**:
```
夏雨润荷香，蝉声满院长。
绿荫遮烈日，清风送清凉。
```

---

## 配置管理

### dfecrab.json 配置

```json
{
  "model": {
    "provider": "ollama",
    "model_name": "qwen3.5:4b",
    "model_type": "ollama_chat",
    "config_name": "ollama_qwen",
    "api_base": "http://192.168.1.150:4096/v1",
    "timeout": 60
  },
  "model_providers": {
    "ollama": {
      "provider": "ollama",
      "model_name": "qwen3.5:4b",
      "model_type": "ollama_chat",
      "config_name": "ollama_qwen",
      "api_base": "http://192.168.1.150:4096/v1",
      "enabled": true,
      "timeout": 60
    }
  }
}
```

### Agent 调用配置

Agent 内部的调用参数可以配置：

```python
# 可配置的参数
LLM_CONFIG = {
    "url": "http://192.168.1.150:4096/v1/chat/completions",
    "model": "/Users/e8900ai/LLM_Fine/models/qwen/Qwen3-Coder-30B-A3B-Instruct-4bit",
    "temperature": 0.7,
    "max_tokens": 1000,
    "timeout": 60
}
```

---

## 测试验证

### 服务测试

```bash
# 1. 测试 llama.cpp server 连通性
curl http://192.168.1.150:4096/v1/models

# 2. 测试对话
curl http://192.168.1.150:4096/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "/Users/e8900ai/LLM_Fine/models/qwen/Qwen3-Coder-30B-A3B-Instruct-4bit",
    "messages": [{"role": "user", "content": "写一首关于秋天的诗，20字以内"}],
    "stream": false,
    "max_tokens": 100
  }'
```

### 集成测试

```bash
# 1. 测试简单任务（写诗）
SESSION_ID=$(curl -s -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "写一首春天的诗"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# 2. 测试上下文理解（改成秋天）
curl -X POST http://localhost:6789/api/v2/chat \
  -H 'Content-Type: application/json' \
  -d "{\"message\": \"改成秋天\", \"session_id\": \"$SESSION_ID\"}"

# 3. 查看 Session 消息历史
curl http://localhost:6789/api/v2/sessions/$SESSION_ID/messages
```

---

## 故障排查

### 大模型调用超时

**问题**: `Read timed out. (read timeout=60)`

**排查**:
1. 检查网络连通性: `ping 192.168.1.150`
2. 检查服务状态: `curl http://192.168.1.150:4096/health`
3. 增加 timeout 配置

### 模型返回空

**问题**: 大模型返回空内容

**排查**:
1. 检查 prompt 是否完整
2. 检查模型是否加载成功
3. 查看 llama.cpp server 日志

### 上下文丢失

**问题**: 大模型不理解上下文

**排查**:
1. 检查 Gateway 是否正确构建增强消息
2. 检查 Agent 是否正确提取当前消息
3. 查看完整日志流

### 日志查看

```bash
# Agent 日志
tail -f logs/worker_reporter_grpc.log

# 搜索大模型调用
grep -A 10 "调用.*大模型\|llm_url\|LLM" logs/worker_*.log
```

---

*文档版本：v1.0 | 更新日期：2026-04-05*
