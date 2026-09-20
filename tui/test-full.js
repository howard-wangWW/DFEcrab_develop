#!/usr/bin/env node
/**
 * DFEcrab 自动化测试脚本
 * 1. 启动 Gateway
 * 2. 等待 Gateway 就绪
 * 3. 测试 WebSocket 连接
 * 4. 测试消息收发
 */

import { spawn } from 'child_process';
import WebSocket from 'ws';
import http from 'http';

const GATEWAY_URL = 'http://localhost:6789';
const WS_URL = 'ws://localhost:6789/ws';
const GATEWAY_DIR = '/Users/zhanghanzhi/DFEcrab--';

let gatewayProcess = null;
let testPassed = false;

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

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForGateway(maxAttempts = 30) {
  console.log('等待 Gateway 启动...');
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const data = await httpGet(GATEWAY_URL);
      if (data) return true;
    } catch (e) {
      // 继续等待
    }
    await sleep(500);
  }
  return false;
}

async function startGateway() {
  console.log('🚀 启动 Gateway...\n');
  
  // 先检查是否已有 Gateway 在运行
  try {
    const existing = await httpGet(GATEWAY_URL);
    if (existing) {
      console.log('⚠️  检测到已有 Gateway 运行，将使用现有服务\n');
      return true;
    }
  } catch (e) {
    // 没有运行，继续启动
  }
  
  return new Promise((resolve) => {
    gatewayProcess = spawn('bash', ['-c', 'source venv/bin/activate && ./dfecrab start'], {
      cwd: GATEWAY_DIR,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    gatewayProcess.stdout.on('data', (data) => {
      const output = data.toString();
      if (output.includes('启动成功') || output.includes('Uvicorn running')) {
        resolve(true);
      }
    });

    gatewayProcess.stderr.on('data', (data) => {
      console.error('Gateway 错误:', data.toString());
    });

    gatewayProcess.on('error', (err) => {
      console.error('启动失败:', err.message);
      resolve(false);
    });

    // 10 秒超时
    setTimeout(() => {
      console.log('启动超时');
      resolve(false);
    }, 10000);
  });
}

async function stopGateway() {
  if (gatewayProcess) {
    gatewayProcess.kill('SIGTERM');
    await sleep(1000);
  }
}

async function testWebSocket() {
  console.log('\n🧪 测试 WebSocket...\n');
  
  return new Promise((resolve) => {
    const ws = new WebSocket(WS_URL);
    let messageCount = 0;

    ws.on('open', () => {
      console.log('✅ WebSocket 连接成功');
      
      // 发送注册消息 (Gateway 期望的格式)
      ws.send(JSON.stringify({
        type: 'register',
        cli_id: 'test-' + Date.now(),
        agent_id: 'default',
        capabilities: ['test'],
        sessions: []
      }));
      console.log('📤 发送注册请求\n');
    });

    ws.on('message', (data) => {
      const msg = JSON.parse(data.toString());
      messageCount++;

      if (msg.type === 'register_ack') {
        console.log(`✅ 注册成功：${msg.cli_id}`);
        
        // 发送测试消息
        setTimeout(() => {
          ws.send(JSON.stringify({
            type: 'message',
            data: {
              message: '测试消息',
              cli_id: msg.cli_id,
              agent_id: 'default'
            }
          }));
          console.log('📤 发送测试消息\n');
        }, 500);
      }

      if (msg.type === 'message') {
        console.log('✅ 收到 AI 回复:', msg.data?.content?.substring(0, 50));
        testPassed = true;
      }
      
      if (msg.type === 'error') {
        console.log('⚠️  错误:', JSON.stringify(msg.data || msg));
        testPassed = false;
      }

      if (msg.type === 'message_ack') {
        console.log('✅ 消息确认\n');
      }
    });

    ws.on('close', () => {
      console.log(`\n共收到 ${messageCount} 条消息`);
      resolve(testPassed);
    });

    ws.on('error', (err) => {
      console.log('❌ WebSocket 错误:', err.message);
      resolve(false);
    });

    // 15 秒超时
    setTimeout(() => {
      ws.close();
      resolve(testPassed);
    }, 15000);
  });
}

async function runTests() {
  console.log('='.repeat(50));
  console.log('DFEcrab 自动化测试');
  console.log('='.repeat(50));
  console.log('');

  try {
    // 1. 启动 Gateway
    const started = await startGateway();
    if (!started) {
      console.log('❌ Gateway 启动失败');
      await stopGateway();
      process.exit(1);
    }

    // 2. 等待 Gateway 就绪
    const ready = await waitForGateway();
    if (!ready) {
      console.log('❌ Gateway 就绪超时');
      await stopGateway();
      process.exit(1);
    }

    console.log('✅ Gateway 已就绪\n');

    // 3. HTTP 测试
    console.log('测试 HTTP...');
    try {
      const data = await httpGet(GATEWAY_URL);
      console.log('✅ HTTP 正常:', JSON.stringify(data), '\n');
    } catch (e) {
      console.log('❌ HTTP 失败:', e.message, '\n');
    }

    // 4. WebSocket 测试
    const wsPassed = await testWebSocket();

    // 5. 清理
    console.log('\n停止 Gateway...');
    await stopGateway();

    // 6. 结果
    console.log('\n' + '='.repeat(50));
    console.log(wsPassed ? '✅ 测试通过' : '⚠️  测试部分通过');
    console.log('='.repeat(50));

    process.exit(wsPassed ? 0 : 1);

  } catch (error) {
    console.error('测试异常:', error);
    await stopGateway();
    process.exit(1);
  }
}

await runTests();
