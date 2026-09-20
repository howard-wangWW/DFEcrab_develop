/**
 * 消息类型定义
 */

export interface Message {
  type: 'user' | 'assistant' | 'system' | 'error';
  content: string;
  timestamp?: number;
}

export interface StreamState {
  isStreaming: boolean;
  currentContent: string;
}
