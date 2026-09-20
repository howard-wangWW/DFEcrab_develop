#!/usr/bin/env node
/**
 * DFEcrab WebSocket 简单测试
 */

import WebSocket from 'ws';

const WS_URL = 'ws://localhost:6790';

console.log('🧪 DFEcrab WebSocket 测试\n');
console.log(`连接：${WS_URL}\n`);

const ws = new WebSocket(WS_URL);
let testPassed = false;

ws.on('open', () => {
  console.log('✅ WebSocket 连接成功\n');
  
  // 发送认证
  ws.send(JSON.stringify({
    type: 'auth_request',
    data: { client_id: 'test-' + Date.now() }
  }));
});

ws.on('message', (data) => {
  const msg = JSON.parse(data.toString());
  console.log('📥 收到:', msg.type, JSON.stringify(msg.data || {}).substring(0, 100));
  
  if (msg.type === 'auth_response' && msg.data?.success) {
    console.log('✅ 认证成功\n');
    
    // 发送消息
    setTimeout(() => {
      ws.send(JSON.stringify({
        type: 'message',
        data: {
          message: '你好',
          client_id: 'test-' + Date.now(),
          agent_id: 'default'
        }
      }));
      console.log('📤 发送消息：你好\n');
    }, 500);
  }
  
  if (msg.type === 'message') {
    console.log('✅ 收到 AI 回复!\n');
    testPassed = true;
  }
});

ws.on('error', (err) => {
  console.log('❌ 错误:', err.message);
  process.exit(1);
});

ws.on('close', () => {
  console.log('连接关闭');
  console.log(testPassed ? '\n✅ 测试通过' : '\n⚠️ 未收到 AI 回复');
  process.exit(testPassed ? 0 : 1);
});

// 10 秒超时
setTimeout(() => {
  console.log('\n⏱️ 超时');
  ws.close();
  process.exit(testPassed ? 0 : 1);
}, 10000);
