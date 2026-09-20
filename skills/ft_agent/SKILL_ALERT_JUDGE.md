---
name: alert-judge
description: 电力告警信号研判技能。通过 ReAct 模式加载微调后的模型，按需调用台账、调度日志、操作票查询工具，综合研判电力告警信号是正常信号、异常信号还是需人工审核的信号。
---

# 电力系统专家 - 告警信号研判技能

## 技能名称
`alert-judge`

## 描述
该技能用于加载微调后的 ReAct 模型，对电力系统的告警信号进行智能研判。Agent 接收告警内容后，自动解析站点名称、日期、馈线/母线等关键信息，按需调用台账查询、调度日志查询、操作票查询等工具，最终综合判断告警信号的性质。

## Agent 运行模式（ReAct 循环）

本技能的核心运行模式为 **ReAct（Reasoning + Acting）** 循环，流程如下：

### 完整执行流程

```
┌─────────────────────────────────────────────────┐
│  1. 构造请求                                      │
│     将 System Prompt + 用户告警信息组装为 messages │
│     发送给微调后的模型                         │
└───────────────────┬─────────────────────────────┘
                    ▼
┌─────────────────────────────────────────────────┐
│  2. 模型推理输出                                   │
│     微调模型根据 System Prompt 和上下文进行推理      │
│     输出文本内容（可能包含 Action/Action Input）     │
└───────────────────┬─────────────────────────────┘
                    ▼
          ┌─────────────────┐
          │ 检查输出内容      │
          └────────┬────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌─────────┐ ┌───────────┐ ┌──────────────┐
│ 包含     │ │ 包含       │ │ 都不包含      │
│Final    │ │ Action:   │ │ (纯文本)      │
│Answer:  │ │ 和        │ │              │
│         │ │ Action    │ │              │
│         │ │ Input:    │ │              │
└────┬────┘ └─────┬─────┘ └──────┬───────┘
     │            │              │
     ▼            ▼              ▼
┌─────────┐ ┌───────────┐ ┌──────────────┐
│ 对话结束  │ │ 解析并调用  │ │ 作为最终回答  │
│ 返回结论  │ │ 对应工具    │ │ 结束对话      │
└─────────┘ └─────┬─────┘ └──────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│  3. 工具调用与结果处理                             │
│     解析 Action Input 中的参数（支持多个 JSON 对象） │
│     调用对应的 Dify 工作流 API 获取数据              │
│     对操作票结果进行汇总统计（票类型和数量）           │
│     将工具结果格式化为 Observation 前缀注入消息历史   │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
         ┌─────────────────┐
         │ 回到步骤 2        │  ← 将 Observation 作为新的 user 消息
         │ 继续下一轮推理     │     追加到 messages 中
         └─────────────────┘
```

### 关键机制说明

**消息历史管理**：
- 初始 `messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": 用户告警}]`
- 每轮模型输出后，将 assistant 消息追加到 messages
- 工具执行结果以 `{"role": "user", "content": "Observation: ..."}` 形式追加
- 每次独立研判结束后自动重置历史

**循环终止条件**（任意一个满足即停止）：
1. 模型输出包含 `Final Answer:` → 提取结论，结束
2. 达到最大推理轮数（默认 10 轮）→ 超时，结束
3. 模型输出纯文本（不含 Action 也不含 Final Answer）→ 作为最终回答，结束

**工具调用解析规则**：
- 从模型输出中通过正则提取 `Action:` 后的工具名称和 `Action Input:` 后的 JSON 参数
- 支持单个 JSON 对象或多个 JSON 对象的批量调用
- 支持 Markdown 代码块包裹的 JSON（自动去除 \`\`\` 标记）

**操作票结果特殊处理**：
- 当工具为 `search_caozuotickets` 时，对返回结果进行汇总
- 解析 `operaType` 字段，统计各类票的数量
- 格式化输出：`Observation:{查到操作票数量为N，"operaType"类型...}`

<!-- ## 系统提示词（System Prompt）

发送给微调模型的核心提示词，定义了工具列表和判断逻辑：

```
## 可用工具
你拥有以下工具，请根据需要调用对应的工具：
1. search_taizhang: 查询站点台账信息。参数定义: {...}
2. search_diaodulog: 根据信号日期、站点名称，搜索调度日志。参数定义: {...}
3. search_caozuotickets: 查询操作票信息。参数定义: {...}

## 判断逻辑
1. 分析告警内容，从alert_content字段中提取站点名称及日期。
2. 如果需要调用台账，则调用 search_taizhang 工具查询该站点的台账信息。
3. 如果需要调用日志，则调用 search_diaodulog 工具查询站点的调度日志。
4. 如果需要调用操作票，则调用 search_caozuotickets 工具查询站点的操作票。
5. 最后综合判断告警是正常信号、异常信号还是需人工审核的信号，给出最终结论处理结果。
6. 最终结论必须以 "Final Answer:" 开头。
``` -->

## 可用工具

### 1. search_taizhang - 台账查询
查询站点台账信息，获取该站点各母线的运行状态。

| 参数 | 类型 | 说明 |
|------|------|------|
| `station` | string | 站点名称，例如：光明站 |
| `feeder_num` | string | 馈线名称 |
| `bus_num` | string | 母线名称 |

- **接口**：Dify 工作流 API（POST）
- **URL**：`http://172.20.42.72/v1/workflows/run`
- **API Key**：`app-QuvM7MPQWopzRRAvzAxtwW5x`
- **认证方式**：`Authorization: Bearer {api_key}`
- **请求体格式**：
  ```json
  {
    "inputs": {"input": "{JSON字符串，参数已做双引号和反斜杠转义}"},
    "response_mode": "blocking",
    "user": "agent-caller"
  }
  ```

### 2. search_diaodulog - 调度日志查询
根据信号日期和站点名称，搜索调度日志。

| 参数 | 类型 | 说明 |
|------|------|------|
| `date` | string | 信号日期 |
| `station` | string | 站点名称 |
| `feeder_num` | string | 馈线名称 |

- **接口**：Dify 工作流 API（POST）
- **URL**：`http://172.20.42.72/v1/workflows/run`
- **API Key**：`app-zN99rBkuT8NeI00weQwpUULy`

### 3. search_caozuotickets - 操作票查询
查询操作票信息，获取停电票、复电票、转出票、恢复票等票类型。

| 参数 | 类型 | 说明 |
|------|------|------|
| `station` | string | 站点名称，例如：光明站 |
| `feeder_num` | string | 馈线名称 |
| `bus_num` | string | 母线名称 |

- **接口**：Dify 工作流 API（POST）
- **URL**：`http://172.20.42.72/v1/workflows/run`
- **API Key**：`app-cxPBtXUz0llwhcGqfkyxBZUw`

> **操作票结果汇总规则**：当返回操作票时，系统自动统计总票数和票类型分布。有效票类型包括：停电票、复电票、转出票、恢复票。统计结果以 `Observation:{查到操作票数量为N，"operaType"类型...}` 格式注入模型上下文。

## 模型配置

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 模型服务地址 | `http://172.20.41.86:8124/v1` | 内部部署的 Qwen 模型 API 服务 |
| 模型名称 | `Qwen3-14B-HGY` | 微调后的 ReAct 模型 |
| API 兼容 | OpenAI 兼容格式 | 使用 openai Python SDK 调用 |
| 温度 | `0.0` | 确定性输出，保证格式稳定 |
| 最大 Token | `4096` | 单次响应最大长度 |
| 最大推理轮数 | `10` | 防止无限循环 |

## 模型输出格式

微调模型输出遵循 ReAct 格式，一次输出可能包含以下任意一种模式：

### 模式一：工具调用
```
Thought: {模型分析推理过程，可选}
Action: {工具名称，如 search_taizhang}
Action Input: {JSON 格式的参数，如 {"station": "民治站", "feeder_num": "10kV1M", "bus_num": "1M"}}
```

### 模式二：最终结论
```
Thought: {模型分析推理过程，可选}
Final Answer: {最终研判结论，包含信号类型和判断理由}
```

### 模式三：多工具批量调用
```
Action: search_caozuotickets
Action Input: {"station": "民治站", "feeder_num": "10kV1M", "bus_num": "1M"}, {"station": "民治站", "feeder_num": "10kV2M", "bus_num": "2M"}
```


> 具体判断标准由微调模型根据 System Prompt 中的判断逻辑自行推理，不同告警类型可能有不同的判断路径。

## 技术实现要点

### API 调用方式
- 使用 OpenAI 兼容客户端（`openai.OpenAI` / `openai.AsyncOpenAI`）连接模型服务
- 同步模式：`client.chat.completions.create(model, messages, temperature, max_tokens)`
- 异步模式：`await async_client.chat.completions.create(...)`
- API Key 可为空（本地部署的模型服务无需认证）

### Dify 工作流调用
- 参数需先 JSON 序列化，再对双引号（`"` → `\"`）和反斜杠（`\` → `\\`）进行转义
- 转义后的 JSON 字符串作为 `inputs.input` 字段的值传入
- 响应中 `data.outputs` 或 `outputs` 字段为工具返回数据
- 单键值 dict 时提取 value 作为结果文本，否则 JSON 序列化整个 outputs

### 日志记录
- 每次调用完整记录到 `logs/` 目录
- 日志格式：JSON，包含 `session_id`、`start_time`、`end_time`、`conversations`（含 user_input、api_request、api_response、agent_thinking、tool_call、final_response 等事件类型）
- 用于后续微调数据收集和质量分析

## 依赖

```
openai          # OpenAI 兼容 API 客户端
requests        # HTTP 工具调用（Dify 工作流）
python-dotenv   # 环境变量管理
```

## 注意事项
- 模型服务 `172.20.41.86:8124` 和 Dify 工作流 `172.20.42.72/v1/workflows/run` 需确保网络可达
- 温度参数设为 `0.0` 以保证 ReAct 格式输出稳定
- 每次独立研判结束后自动重置消息历史，避免上下文污染
- 超过最大推理轮数（10 轮）仍未输出 Final Answer 时，视为超时异常
- 告警内容需包含站点名称（`XX站`）和日期信息，模型方能正确提取参数
