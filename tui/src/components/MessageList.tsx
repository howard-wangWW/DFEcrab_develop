/**
 * MessageList 组件
 * 显示对话历史
 */

import React from 'react';
import { Box, Text } from 'ink';
import { Message } from '../types.js';

export interface MessageListProps {
  messages: Message[];
}

export const MessageList: React.FC<MessageListProps> = ({ messages = [] }) => {
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
        <MessageItem key={index} type={msg.type} content={msg.content} />
      ))}
    </Box>
  );
};

interface MessageItemProps {
  type: string;
  content: string;
}

const MessageItem: React.FC<MessageItemProps> = ({ type, content }) => {
  switch (type) {
    case 'user':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold color="green">👤 你： </Text>
            <Text>{content}</Text>
          </Box>
        </Box>
      );

    case 'assistant':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold color="cyan">🤖 AI: </Text>
            <Text wrap="wrap">{content}</Text>
          </Box>
        </Box>
      );

    case 'system':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold color="yellow">⚙️ 系统： </Text>
            <Text dimColor>{content}</Text>
          </Box>
        </Box>
      );

    case 'error':
      return (
        <Box flexDirection="column" marginBottom={1}>
          <Box>
            <Text bold color="red">❌ 错误： </Text>
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
};
