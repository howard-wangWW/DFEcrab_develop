# WebSocket 实时推送文档

> 版本：v1.0  
> 日期：2026-04-04  
> WebSocket URL：`ws://localhost:6790/ws`

---

## 概述

DFEcrab 支持通过 WebSocket 实时推送任务进度更新。客户端可以订阅特定任务或所有任务，接收实时进度、状态变更和完成通知。

---

## 连接流程

```
客户端                          服务端
  |                              |
  |-------- 建立连接 ----------->|
  |                              |
  |------ auth_request --------->|
  |<----- auth_response ---------|
  |                              |
  |------ subscribe ------------>|
  |<----- event (subscribed) ----|
  |                              |
  |<----- task_progress ---------|  (自动推送)
  |<----- task_complete ---------|  (自动推送)
  |                              |
```

---

## 消息类型

### 客户端 → 服务端

#### 1. 认证请求
```json
{
  "type": "auth_request",
  "data": {
    "method": "token",
    "token": "your_token_here"
  }
}
```

#### 2. 订阅任务
```json
{
  "type": "subscribe",
  "data": {
    "event_type": "task:abc123"  // 订阅特定任务
  }
}
```

或订阅所有任务：
```json
{
  "type": "subscribe",
  "data": {
    "event_type": "task:*"  // 订阅所有任务
  }
}
```

#### 3. 取消订阅
```json
{
  "type": "unsubscribe",
  "data": {
    "event_type": "task:abc123"
  }
}
```

---

### 服务端 → 客户端

#### 1. 认证响应
```json
{
  "type": "auth_response",
  "data": {
    "success": true,
    "method": "token"
  }
}
```

#### 2. 订阅确认
```json
{
  "type": "event",
  "data": {
    "event_type": "task:abc123",
    "data": {"subscribed": "task:abc123"}
  }
}
```

#### 3. 任务进度更新
```json
{
  "type": "task_progress",
  "data": {
    "task_id": "abc123",
    "progress": {
      "task_id": "abc123",
      "overall_progress": 40.0,
      "is_complete": false,
      "total_steps": 5,
      "completed_steps": 2,
      "current_step": 2,
      "steps": {
        "step_0": {"step_id": "step_0", "status": "completed", "updated_at": "..."},
        "step_1": {"step_id": "step_1", "status": "completed", "updated_at": "..."},
        "step_2": {"step_id": "step_2", "status": "running", "updated_at": "..."}
      },
      "members": {
        "sess_a1": {
          "agent": "qwencode",
          "role": "designer",
          "status": "completed",
          "progress": 100.0,
          "updated_at": "..."
        }
      }
    }
  }
}
```

#### 4. 任务完成通知
```json
{
  "type": "task_complete",
  "data": {
    "task_id": "abc123",
    "result": {
      "status": "completed",
      "progress": 100.0,
      "completed_at": "2026-04-04T10:30:00"
    }
  }
}
```

#### 5. 错误消息
```json
{
  "type": "error",
  "data": {
    "message": "错误描述"
  }
}
```

---

## JavaScript 示例

```javascript
const ws = new WebSocket('ws://localhost:6790/ws');

ws.onopen = () => {
  console.log('WebSocket 连接已建立');
  
  // 1. 认证
  ws.send(JSON.stringify({
    type: 'auth_request',
    data: { method: 'token', token: 'your_token' }
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  switch (msg.type) {
    case 'auth_response':
      if (msg.data.success) {
        console.log('认证成功');
        
        // 2. 订阅任务
        ws.send(JSON.stringify({
          type: 'subscribe',
          data: { event_type: 'task:*' }  // 订阅所有任务
        }));
      }
      break;
    
    case 'event':
      if (msg.data.data?.subscribed) {
        console.log(`已订阅：${msg.data.data.subscribed}`);
      }
      break;
    
    case 'task_progress':
      console.log(`任务 ${msg.data.task_id} 进度：${msg.data.progress.overall_progress}%`);
      // 更新 UI
      updateProgressBar(msg.data.task_id, msg.data.progress);
      break;
    
    case 'task_complete':
      console.log(`任务 ${msg.data.task_id} 已完成`);
      // 更新 UI
      markTaskComplete(msg.data.task_id, msg.data.result);
      break;
    
    case 'error':
      console.error('错误：', msg.data.message);
      break;
  }
};

ws.onerror = (error) => {
  console.error('WebSocket 错误：', error);
};

ws.onclose = () => {
  console.log('WebSocket 连接已关闭');
};

// UI 更新函数
function updateProgressBar(taskId, progress) {
  const element = document.getElementById(`progress-${taskId}`);
  if (element) {
    element.style.width = `${progress.overall_progress}%`;
    element.textContent = `${progress.overall_progress.toFixed(1)}%`;
  }
}

function markTaskComplete(taskId, result) {
  const element = document.getElementById(`task-${taskId}`);
  if (element) {
    element.classList.add('completed');
    element.textContent = `✅ 任务 ${taskId} 已完成`;
  }
}
```

---

## Python 示例

```python
import asyncio
import websockets
import json

async def subscribe_to_tasks():
    uri = "ws://localhost:6790/ws"
    
    async with websockets.connect(uri) as websocket:
        # 1. 认证
        await websocket.send(json.dumps({
            "type": "auth_request",
            "data": {"method": "token", "token": "your_token"}
        }))
        
        response = json.loads(await websocket.recv())
        if response["data"]["success"]:
            print("认证成功")
            
            # 2. 订阅所有任务
            await websocket.send(json.dumps({
                "type": "subscribe",
                "data": {"event_type": "task:*"}
            }))
            
            # 3. 接收消息
            async for message in websocket:
                msg = json.loads(message)
                
                if msg["type"] == "task_progress":
                    task_id = msg["data"]["task_id"]
                    progress = msg["data"]["progress"]["overall_progress"]
                    print(f"任务 {task_id} 进度：{progress:.1f}%")
                
                elif msg["type"] == "task_complete":
                    task_id = msg["data"]["task_id"]
                    print(f"任务 {task_id} 已完成")
                
                elif msg["type"] == "error":
                    print(f"错误：{msg['data']['message']}")

asyncio.run(subscribe_to_tasks())
```

---

## 订阅模式

| 订阅类型 | 说明 | 示例 |
|---------|------|------|
| `task:{task_id}` | 订阅特定任务 | `task:abc123` |
| `task:*` | 订阅所有任务 | `task:*` |

---

## 错误处理

| 错误类型 | 原因 | 处理方式 |
|---------|------|---------|
| `Not authenticated` | 未认证 | 先发送 auth_request |
| `Missing event_type` | 缺少 event_type | 检查请求格式 |
| `Unknown event_type` | 未知事件类型 | 使用有效的订阅类型 |

---

## 最佳实践

1. **及时订阅**：连接成功后立即订阅需要的任务
2. **错误重连**：实现自动重连逻辑
3. **资源管理**：不需要的任务及时取消订阅
4. **心跳保活**：定期发送 ping 消息保持连接

---

*文档版本: 1.0*  
*最后更新: 2026-04-04*
