/**
 * InputPrompt 组件
 * Reference: Qwen Code InputPrompt
 */

import React, { useState, useCallback } from 'react';
import { Box, Text, useInput } from 'ink';

export interface InputPromptProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export const InputPrompt: React.FC<InputPromptProps> = ({
  value = '',
  onChange,
  onSubmit,
  disabled = false,
  placeholder = '输入消息...'
}) => {
  const [history, setHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // 处理键盘输入
  useInput((input, key) => {
    if (disabled) return;

    // 回车提交
    if (key.return) {
      if (value.trim()) {
        onSubmit(value);
        // 添加到历史记录
        setHistory(prev => [...prev, value]);
        setHistoryIndex(-1);
      }
      return true;
    }

    // 向上箭头 - 历史上一条
    if (key.upArrow) {
      if (history.length > 0 && historyIndex < history.length - 1) {
        const newIndex = historyIndex + 1;
        setHistoryIndex(newIndex);
        onChange(history[history.length - 1 - newIndex]);
      }
      return true;
    }

    // 向下箭头 - 历史上下条
    if (key.downArrow) {
      if (historyIndex > 0) {
        const newIndex = historyIndex - 1;
        setHistoryIndex(newIndex);
        onChange(history[history.length - 1 - newIndex]);
      } else if (historyIndex === 0) {
        setHistoryIndex(-1);
        onChange('');
      }
      return true;
    }

    // Ctrl+C / Ctrl+D 清空
    if ((key.ctrl && input === 'c') || (key.ctrl && input === 'd')) {
      onChange('');
      return true;
    }

    // 退格
    if (key.backspace && value.length > 0) {
      onChange(value.slice(0, -1));
      return true;
    }

    // 其他输入交给 Ink 处理
    if (input && !key.ctrl && !key.meta) {
      onChange(value + input);
      return true;
    }

    return false;
  });

  return (
    <Box flexDirection="column">
      <Box borderStyle="round" borderColor={disabled ? 'gray' : 'blue'} paddingX={1}>
        <Text dimColor>👤 你： </Text>
        <Text>{value || <Text dimColor>{placeholder}</Text>}</Text>
      </Box>
      <Box marginTop={0}>
        <Text dimColor>
          Enter 发送 ↑↓ 历史 Ctrl+C 清空
        </Text>
      </Box>
    </Box>
  );
};
