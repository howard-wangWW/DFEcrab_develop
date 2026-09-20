/**
 * WebSocket 客户端
 * Reference: Claude Code WebSocket handling
 */

import WebSocket, { WebSocketServer } from 'ws';

export type WSMessageType = 'connected' | 'disconnected' | 'message' | 'error';

export interface WSMessage {
  type: string;
  data?: Record<string, unknown>;
}

export type WSEventCallback = (data: unknown) => void;

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private url: string;
  private listeners: Map<string, WSEventCallback[]>;
  private reconnectDelay: number;
  private maxReconnectAttempts: number;
  private reconnectAttempts: number;

  constructor(url: string) {
    this.url = url;
    this.listeners = new Map();
    this.reconnectDelay = 3000;
    this.maxReconnectAttempts = 5;
    this.reconnectAttempts = 0;
  }

  on(event: string, callback: WSEventCallback): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event)!.push(callback);
  }

  off(event: string, callback: WSEventCallback): void {
    const callbacks = this.listeners.get(event);
    if (callbacks) {
      const index = callbacks.indexOf(callback);
      if (index > -1) {
        callbacks.splice(index, 1);
      }
    }
  }

  private emit(event: string, data?: unknown): void {
    const callbacks = this.listeners.get(event) || [];
    callbacks.forEach(cb => cb(data));
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url);

        this.ws.on('open', () => {
          this.reconnectAttempts = 0;
          this.emit('connected');
          resolve();
        });

        this.ws.on('close', () => {
          this.emit('disconnected');
          // 尝试重连
          if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            setTimeout(() => this.connect(), this.reconnectDelay);
          }
        });

        this.ws.on('error', (error) => {
          this.emit('error', { message: error.message });
          reject(error);
        });

        this.ws.on('message', (data: WebSocket.Data) => {
          try {
            const message: WSMessage = JSON.parse(data.toString());
            this.emit('message', message);
          } catch (e) {
            this.emit('error', { message: '解析消息失败' });
          }
        });
      } catch (error) {
        reject(error);
      }
    });
  }

  send(type: string, data: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }));
    }
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}
