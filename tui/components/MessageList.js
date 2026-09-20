/**
 * MessageList 组件
 * 显示对话历史
 */

import React from 'react';
import { Box, Text } from 'ink';

export function MessageList({ messages = [] }) {
  if (!messages || messages.length === 0) {
    return (
      <Box>
        <Text dimColor>暂无消息，输入消息开始对话...</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {messages.map((msg, index) => (
        <Message key={index} type={msg.type} content={msg.content} />
      ))}
    </Box>
  );
}

function Message({ type, content }) {
  switch (type) {
    case 'user':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold green>👤 你： </Text>
            <Text>{content}</Text>
          </Box>
        </Box>
      );

    case 'assistant':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold cyan>🤖 AI: </Text>
            <Text wrap="wrap">{content}</Text>
          </Box>
        </Box>
      );

    case 'system':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold yellow>⚙️ 系统： </Text>
            <Text dimColor>{content}</Text>
          </Box>
        </Box>
      );

    case 'error':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold red>❌ 错误： </Text>
            <Text dimColor>{content}</Text>
          </Box>
        </Box>
      );

    default:
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Text>{content}</Text>
        </Box>
      );
  }
}
