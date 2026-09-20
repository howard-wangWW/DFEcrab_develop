/**
 * StatusBar 组件
 * 显示连接状态和快捷键提示
 */

import React from 'react';
import { Box, Text } from 'ink';

export interface StatusBarProps {
  connected: boolean;
  streaming: boolean;
  messageCount: number;
}

export const StatusBar: React.FC<StatusBarProps> = ({
  connected,
  streaming,
  messageCount
}) => {
  return (
    <Box flexDirection="column">
      {/* 状态栏 */}
      <Box paddingX={1} width="100%">
        <Text backgroundColor={connected ? 'green' : 'red'} color="black" bold>
          {' '.repeat(2)}
          {connected ? '🟢 已连接' : '🔴 未连接'}
          {' │ '}
          消息：{messageCount}
          {' │ '}
          版本：v4.1.0 (Ink TS)
          {streaming && ' │ 🔄 生成中...'}
          {' '.repeat(2)}
        </Text>
      </Box>

      {/* 快捷键提示 */}
      <Box paddingX={1} width="100%">
        <Text backgroundColor="blue" color="white">
          {' '.repeat(2)}
          Ctrl+Q 退出 │ Enter 发送 │ ↑↓ 历史 │ Ctrl+C 清空
          {' '.repeat(2)}
        </Text>
      </Box>
    </Box>
  );
};
