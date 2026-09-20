/**
 * DFEcrab TUI - Based on Ink (React for Terminal)
 * Reference: Claude Code, Qwen Code
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { render, Box, Text, useInput, useApp } from 'ink';
import { WebSocketClient } from './websocket.js';
import { Message } from './types.js';
import { MessageList } from './components/MessageList.js';
import { InputPrompt } from './components/InputPrompt.js';
import { StatusBar } from './components/StatusBar.js';

// 解析命令行参数
// --port 指定的是 HTTP 端口，WebSocket 在同一端口的 /ws 路径
// 默认：HTTP 6789, WS ws://localhost:6789/ws
const args = process.argv.slice(2);
let host = 'localhost';
let httpPort = 6789;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--host' && args[i + 1]) {
    host = args[i + 1];
    i++;
  } else if (args[i] === '--port' && args[i + 1]) {
    httpPort = parseInt(args[i + 1]);
    i++;
  }
}

const WS_URL = `ws://${host}:${httpPort}/ws`;
const HTTP_URL = `http://${host}:${httpPort}`;

/**
 * 主应用组件
 */
const App: React.FC = () => {
  const { exit } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  
  const wsRef = useRef<WebSocketClient | null>(null);

  // 连接 WebSocket
  useEffect(() => {
    const ws = new WebSocketClient(WS_URL);
    wsRef.current = ws;

    ws.on('connected', () => {
      setIsConnected(true);
      setMessages(prev => [...prev, {
        type: 'system',
        content: `✅ 已连接到 ${HTTP_URL}`
      }]);
    });

    ws.on('disconnected', () => {
      setIsConnected(false);
    });

    ws.on('message', (data: unknown) => {
      const msg = data as { type: string; data?: Record<string, unknown> };
      const { type, data: payload } = msg;
      
      if (type === 'message') {
        const content = (payload?.content as string) || '';
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
          content: (payload?.message as string) || '未知错误'
        }]);
      }
    });

    ws.on('error', (data: unknown) => {
      const err = data as { message?: string };
      setMessages(prev => [...prev, {
        type: 'error',
        content: `连接错误：${err.message || '未知错误'}`
      }]);
    });

    ws.connect().catch(() => {
      setMessages(prev => [...prev, {
        type: 'error',
        content: `无法连接到 ${WS_URL}`
      }]);
    });

    return () => {
      ws.disconnect();
    };
  }, [isStreaming]);

  // 处理输入提交
  const handleSubmit = useCallback((text: string) => {
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
    <Box flexDirection="column">
      {/* 头部 ASCII Art */}
      <Box flexDirection="column" marginBottom={1}>
        <Box>
          <Text bold color="blue">
            ┌────────────────────────────────────────────────────────────┐
          </Text>
        </Box>
        <Box>
          <Text bold color="blue">│</Text>
          <Text bold color="cyan">
            ██████╗ ██████╗  ██████╗ ████████╗    ██████╗  █████╗  ██████╗██╗  ██╗
          </Text>
          <Text bold color="blue">│</Text>
        </Box>
        <Box>
          <Text bold color="blue">│</Text>
          <Text bold color="cyan">
            ██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝    ██╔══██╗██╔══██╗██╔════╝██║ ██╔╝
          </Text>
          <Text bold color="blue">│</Text>
        </Box>
        <Box>
          <Text bold color="blue">│</Text>
          <Text bold color="cyan">
            ██████╔╝██████╔╝██║   ██║   ██║       ██████╔╝███████║██║     █████╔╝
          </Text>
          <Text bold color="blue">│</Text>
        </Box>
        <Box>
          <Text bold color="blue">│</Text>
          <Text bold color="cyan">
            ██╔═══╝ ██╔══██╗██║   ██║   ██║       ██╔═══╝ ██╔══██║██║     ██╔═██╗
          </Text>
          <Text bold color="blue">│</Text>
        </Box>
        <Box>
          <Text bold color="blue">│</Text>
          <Text bold color="cyan">
            ██║     ██║  ██║╚██████╔╝   ██║       ██║     ██║  ██║╚██████╗██║  ██╗
          </Text>
          <Text bold color="blue">│</Text>
        </Box>
        <Box>
          <Text bold color="blue">│</Text>
          <Text bold color="cyan">
            ╚═╝     ╚═╝  ╚═╝ ╚═════╝    ╚═╝       ╚═╝     ╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝
          </Text>
          <Text bold color="blue">│</Text>
        </Box>
        <Box>
          <Text bold color="blue">
            └────────────────────────────────────────────────────────────┘
          </Text>
        </Box>
        <Box marginTop={1}>
          <Text dimColor>
            DFEcrab v4.1.0 (Ink TypeScript) | {HTTP_URL}
          </Text>
        </Box>
      </Box>

      {/* 消息列表 */}
      <Box flexGrow={1} flexDirection="column">
        <MessageList messages={messages} />
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
};

// 渲染应用
const { waitUntilExit } = render(<App />);
await waitUntilExit();
