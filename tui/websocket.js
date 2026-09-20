/**
 * WebSocket 客户端
 * Reference: Claude Code WebSocket handling
 */

import WebSocket from 'ws';

export class WebSocketClient {
  constructor(url) {
    this.url = url;
    this.ws = null;
    this.listeners = new Map();
    this.reconnectDelay = 3000;
    this.maxReconnectAttempts = 5;
    this.reconnectAttempts = 0;
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(callback);
  }

  emit(event, data) {
    const callbacks = this.listeners.get(event) || [];
    callbacks.forEach(cb => cb(data));
  }

  connect() {
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

        this.ws.on('message', (data) => {
          try {
            const message = JSON.parse(data.toString());
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

  send(type, data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }));
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
