#!/usr/bin/env node
/**
 * DFEcrab TUI - Based on Ink (React for Terminal)
 * Reference: Claude Code, Qwen Code
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { render, Box, Text, useInput, useApp } from 'ink';
import { WebSocketClient } from './websocket.js';
import { MessageList } from './components/MessageList.js';
import { InputPrompt } from './components/InputPrompt.js';
import { StatusBar } from './components/StatusBar.js';

// 解析命令行参数
const args = process.argv.slice(2);
let host = 'localhost';
let port = '6789';

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--host' && args[i + 1]) {
    host = args[i + 1];
    i++;
  } else if (args[i] === '--port' && args[i + 1]) {
    port = args[i + 1];
    i++;
  }
}

const WS_URL = `ws://${host}:${parseInt(port) + 1}`;
const HTTP_URL = `http://${host}:${port}`;

/**
 * 主应用组件
 */
function App() {
  const { exit } = useApp();
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [status, setStatus] = useState('disconnected');
  
  const wsRef = useRef(null);
  const messagesEndRef = useRef(null);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 连接 WebSocket
  useEffect(() => {
    const ws = new WebSocketClient(WS_URL);
    wsRef.current = ws;

    ws.on('connected', () => {
      setIsConnected(true);
      setStatus('connected');
      setMessages(prev => [...prev, {
        type: 'system',
        content: `✅ 已连接到 ${HTTP_URL}`
      }]);
    });

    ws.on('disconnected', () => {
      setIsConnected(false);
      setStatus('disconnected');
    });

    ws.on('message', (data) => {
      const { type, data: payload } = data;
      
      if (type === 'message') {
        const content = payload.content || '';
        if (!isStreaming) {
          setIsStreaming(true);
          setMessages(prev => [...prev, {
            type: 'assistant',
            content: ''
          }]);
        }
        
        setMessages(prev => {
          const newMessages = [...prev];
          const lastMessage = newMessages[newMessages.length - 1];
          if (lastMessage && lastMessage.type === 'assistant') {
            lastMessage.content += content;
          }
          return newMessages;
        });
      } else if (type === 'message_ack') {
        setIsStreaming(false);
      } else if (type === 'error') {
        setMessages(prev => [...prev, {
          type: 'error',
          content: payload.message || '未知错误'
        }]);
      }
    });

    ws.connect();

    return () => {
      ws.disconnect();
    };
  }, [isStreaming]);

  // 处理输入提交
  const handleSubmit = useCallback((text) => {
    if (!text.trim() || !wsRef.current) return;

    // 添加用户消息
    setMessages(prev => [...prev, {
      type: 'user',
      content: text
    }]);

    // 发送到服务器
    wsRef.current.send('message', {
      message: text,
      client_id: `tui-${Date.now()}`,
      agent_id: 'default'
    });

    setInputValue('');
  }, []);

  // 处理快捷键
  useInput((input, key) => {
    if (key.ctrl && input === 'c') {
      exit();
    }
    if (key.ctrl && input === 'q') {
      exit();
    }
  });

  return (
    <Box flexDirection="column" height="100%">
      {/* 头部 */}
      <Box flexDirection="column" marginBottom={1}>
        <Box>
          <Text bold blue>
            ┌────────────────────────────────────────────────────────────┐
          </Text>
        </Box>
        <Box>
          <Text bold blue>│</Text>
          <Text bold cyan>
            ██████╗ ██████╗  ██████╗ ████████╗    ██████╗  █████╗  ██████╗██╗  ██╗
          </Text>
          <Text bold blue>│</Text>
        </Box>
        <Box>
          <Text bold blue>│</Text>
          <Text bold cyan>
            ██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝    ██╔══██╗██╔══██╗██╔════╝██║ ██╔╝
          </Text>
          <Text bold blue>│</Text>
        </Box>
        <Box>
          <Text bold blue>│</Text>
          <Text bold cyan>
            ██████╔╝██████╔╝██║   ██║   ██║       ██████╔╝███████║██║     █████╔╝
          </Text>
          <Text bold blue>│</Text>
        </Box>
        <Box>
          <Text bold blue>│</Text>
          <Text bold cyan>
            ██╔═══╝ ██╔══██╗██║   ██║   ██║       ██╔═══╝ ██╔══██║██║     ██╔═██╗
          </Text>
          <Text bold blue>│</Text>
        </Box>
        <Box>
          <Text bold blue>│</Text>
          <Text bold cyan>
            ██║     ██║  ██║╚██████╔╝   ██║       ██║     ██║  ██║╚██████╗██║  ██╗
          </Text>
          <Text bold blue>│</Text>
        </Box>
        <Box>
          <Text bold blue>│</Text>
          <Text bold cyan>
            ╚═╝     ╚═╝  ╚═╝ ╚═════╝    ╚═╝       ╚═╝     ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝
          </Text>
          <Text bold blue>│</Text>
        </Box>
        <Box>
          <Text bold blue>
            └────────────────────────────────────────────────────────────┘
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text dimColor>
            DFEcrab v4.1.0 (Ink TUI) | {HTTP_URL}
          </Text>
        </Box>
      </Box>

      {/* 消息列表 */}
      <Box flexGrow={1} flexDirection="column" overflow="hidden">
        <MessageList messages={messages} />
        <div ref={messagesEndRef} />
      </Box>

      {/* 输入区域 */}
      <Box marginTop={1} flexDirection="column">
        <InputPrompt
          value={inputValue}
          onChange={setInputValue}
          onSubmit={handleSubmit}
          disabled={!isConnected || isStreaming}
          placeholder={isConnected ? '输入消息...' : '连接中...'}
        />
      </Box>

      {/* 状态栏 */}
      <Box marginTop={1}>
        <StatusBar
          connected={isConnected}
          streaming={isStreaming}
          messageCount={messages.length}
        />
      </Box>
    </Box>
  );
}

// 渲染应用
const { waitUntilExit } = render(<App />);
await waitUntilExit();
