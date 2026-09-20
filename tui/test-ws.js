#!/usr/bin/env node
/**
 * DFEcrab WebSocket 自动化测试
 */

import WebSocket from 'ws';
import http from 'http';

const HTTP_URL = 'http://localhost:6789';
const WS_URL = 'ws://localhost:6790';

function httpGet(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          resolve(data);
        }
      });
    }).on('error', reject);
  });
}

async function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function testWebSocket() {
  console.log('🧪 DFEcrab WebSocket 自动化测试\n');
  console.log(`HTTP: ${HTTP_URL}`);
  console.log(`WebSocket: ${WS_URL}\n`);

  // 测试 1: HTTP 健康检查
  console.log('测试 1: HTTP 健康检查...');
  try {
    const data = await httpGet(HTTP_URL);
    console.log(`✅ HTTP 正常：${JSON.stringify(data)}\n`);
  } catch (error) {
    console.log(`❌ HTTP 失败：${error.message}\n`);
    return false;
  }

  // 测试 2: WebSocket 连接
  console.log('测试 2: WebSocket 连接...');
  
  return new Promise((resolve) => {
    const ws = new WebSocket(WS_URL);
    let messageCount = 0;
    let receivedAIResponse = false;

    ws.on('open', () => {
      console.log('✅ WebSocket 连接成功\n');
      
      // 发送认证请求
      const authMsg = {
        type: 'auth_request',
        data: {
          client_id: 'test-client-' + Date.now()
        }
      };
      ws.send(JSON.stringify(authMsg));
      console.log('📤 发送认证请求');
    });

    ws.on('message', (data) => {
      const msg = JSON.parse(data.toString());
      messageCount++;

      if (msg.type === 'auth_response') {
        console.log(`📥 认证响应：${msg.data?.success ? '✅ 成功' : '❌ 失败'}`);
        
        if (msg.data?.success) {
          // 发送测试消息
          setTimeout(() => {
            const testMsg = {
              type: 'message',
              data: {
                message: '你好，测试 WebSocket 连接',
                client_id: authMsg.data.client_id,
                agent_id: 'default'
              }
            };
            ws.send(JSON.stringify(testMsg));
            console.log('📤 发送测试消息：你好，测试 WebSocket 连接\n');
          }, 200);
        }
      }

      if (msg.type === 'message') {
        console.log(`📥 AI 回复：${msg.data?.content?.substring(0, 50) || '...'}`);
        receivedAIResponse = true;
      }

      if (msg.type === 'message_ack') {
        console.log('📥 消息确认\n');
      }

      if (msg.type === 'ping') {
        ws.send(JSON.stringify({ type: 'pong' }));
      }
    });

    ws.on('error', (error) => {
      console.log(`❌ WebSocket 错误：${error.message}`);
      resolve(false);
    });

    ws.on('close', () => {
      console.log('================================');
      console.log(`共收到 ${messageCount} 条消息`);
      console.log(`AI 回复：${receivedAIResponse ? '✅' : '❌'}`);
      resolve(receivedAIResponse);
    });

    // 15 秒超时
    setTimeout(() => {
      console.log('\n⏱️ 测试超时');
      ws.close();
      resolve(receivedAIResponse);
    }, 15000);
  });
}

// 运行测试
const passed = await testWebSocket();
console.log('\n' + (passed ? '✅ 测试通过' : '⚠️  测试部分通过'));
process.exit(passed ? 0 : 1);
