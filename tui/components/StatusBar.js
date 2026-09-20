/**
 * StatusBar 组件
 * 显示连接状态和快捷键提示
 */

import React from 'react';
import { Box, Text } from 'ink';

export function StatusBar({ connected, streaming, messageCount }) {
  return (
    <Box flexDirection="column">
      {/* 状态栏 */}
      <Box
        backgroundColor="green"
        paddingX={1}
        width="100%"
      >
        <Text black>
          {connected ? '🟢 已连接' : '🔴 未连接'}
          {' │ '}
          消息：{messageCount}
          {' │ '}
          版本：v4.1.0 (Ink)
        </Text>
      </Box>

      {/* 快捷键提示 */}
      <Box
        backgroundColor="blue"
        paddingX={1}
        width="100%"
      >
        <Text white>
          Ctrl+Q 退出 │ Enter 发送 │ ↑↓ 历史 │ Ctrl+C 清空
        </Text>
      </Box>
    </Box>
  );
}
