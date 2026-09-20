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

/**
 * Markdown 图片语法匹配：![alt](url)
 *
 * Ink 是终端 UI，只能渲染文本、无法显示位图，因此把图片语法降级成可读的链接行，
 * 用户可在浏览器中打开查看；批量浏览请用后端的 /api/images/gallery 画廊页。
 */
const IMAGE_MD_RE = /!\[([^\]]*)\]\(([^)\s]+)\)/g;

/** 后端 HTTP 地址，用于把 "/api/images/xxx" 补全成绝对 URL */
const IMAGE_BASE_URL = process.env.DFECRAB_HTTP_URL || 'http://localhost:6789';

const toTerminalContent = (content: string): string =>
  String(content || '').replace(IMAGE_MD_RE, (_m, alt, url) => {
    const abs = /^https?:\/\//i.test(url)
      ? url
      : `${IMAGE_BASE_URL}${url.startsWith('/') ? '' : '/'}${url}`;
    return `\n🖼 图片${alt ? `（${alt}）` : ''}: ${abs}\n`;
  });

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
            <Text wrap="wrap">{toTerminalContent(content)}</Text>
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
