#!/usr/bin/env node

const tools = [
  {
    name: "ping_blackxml_mcp",
    description: "Minimal Cherry Studio MCP connectivity test.",
    inputSchema: {
      type: "object",
      properties: {}
    }
  }
];

function send(message) {
  const payload = JSON.stringify(message);
  if (responseMode === "line") {
    process.stdout.write(`${payload}\n`);
    return;
  }
  process.stdout.write(`Content-Length: ${Buffer.byteLength(payload, "utf8")}\r\n\r\n${payload}`);
}

function result(id, value) {
  send({ jsonrpc: "2.0", id, result: value });
}

async function handle(message) {
  const { id, method, params = {} } = message;
  if (message.id === undefined || String(method).startsWith("notifications/")) return;
  if (method === "initialize") {
    return result(id, {
      protocolVersion: params.protocolVersion || "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "minimal-blackxml-test", version: "1.0.0" }
    });
  }
  if (method === "tools/list") return result(id, { tools });
  if (method === "tools/call") {
    return result(id, {
      content: [{ type: "text", text: "minimal MCP ok" }],
      structuredContent: { ok: true, now: new Date().toISOString() }
    });
  }
  if (method === "ping") return result(id, {});
  return send({ jsonrpc: "2.0", id, error: { code: -32601, message: `Method not found: ${method}` } });
}

let buffer = Buffer.alloc(0);
let responseMode = "framed";

process.stdin.on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  drain().catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
  });
});

async function drain() {
  while (buffer.length) {
    const boundary = findHeaderBoundary(buffer);
    if (!boundary) {
      const text = buffer.toString("utf8");
      const newline = text.indexOf("\n");
      if (!text.trimStart().startsWith("{") || newline < 0) return;
      const line = text.slice(0, newline).trim();
      buffer = Buffer.from(text.slice(newline + 1), "utf8");
      responseMode = "line";
      await handle(JSON.parse(line));
      continue;
    }
    const header = buffer.slice(0, boundary.index).toString("utf8");
    const match = header.match(/Content-Length:\s*(\d+)/i);
    if (!match) {
      buffer = buffer.slice(boundary.index + boundary.length);
      continue;
    }
    const start = boundary.index + boundary.length;
    const end = start + Number(match[1]);
    if (buffer.length < end) return;
    const payload = buffer.slice(start, end).toString("utf8");
    buffer = buffer.slice(end);
    responseMode = "framed";
    await handle(JSON.parse(payload));
  }
}

function findHeaderBoundary(input) {
  const crlf = input.indexOf("\r\n\r\n");
  const lf = input.indexOf("\n\n");
  if (crlf < 0 && lf < 0) return null;
  if (crlf >= 0 && (lf < 0 || crlf <= lf)) return { index: crlf, length: 4 };
  return { index: lf, length: 2 };
}
