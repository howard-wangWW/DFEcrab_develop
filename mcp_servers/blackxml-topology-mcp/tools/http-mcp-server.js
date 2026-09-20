#!/usr/bin/env node
const http = require("http");
const path = require("path");
const fs = require("fs");
const crypto = require("crypto");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const MCP_SERVER = path.join(__dirname, "mcp-server.js");
const HOST = process.env.MCP_HOST || "0.0.0.0";
const PORT = Math.max(1, Number(process.env.MCP_PORT) || 3100);
const AUTH_TOKEN = String(process.env.MCP_AUTH_TOKEN || "").trim();
const REQUEST_TIMEOUT = Math.max(5000, Number(process.env.MCP_REQUEST_TIMEOUT_MS) || 120000);
const sessions = new Map();
let requestSequence = 0;

function authorized(req, url) {
  if (!AUTH_TOKEN) return true;
  const bearer = String(req.headers.authorization || "").replace(/^Bearer\s+/i, "");
  if (bearer === AUTH_TOKEN) return true;
  const sessionId = url.searchParams.get("sessionId") || "";
  return url.pathname === "/message" && sessions.has(sessionId);
}

function json(res, status, value, extraHeaders = {}) {
  const body = Buffer.from(JSON.stringify(value), "utf8");
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": body.length,
    "access-control-allow-origin": "*",
    ...extraHeaders
  });
  res.end(body);
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let length = 0;
    req.on("data", (chunk) => {
      length += chunk.length;
      if (length > 2 * 1024 * 1024) {
        reject(new Error("request body exceeds 2 MB"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"));
      } catch (error) {
        reject(new Error("invalid JSON body"));
      }
    });
    req.on("error", reject);
  });
}

class McpBridge {
  constructor(onNotification = null) {
    this.onNotification = onNotification;
    this.pending = new Map();
    this.buffer = "";
    // 支持 musl 版 Node：通过环境变量获取正确的启动命令
    const MUSL_LD = process.env.MUSL_LD;
    const MUSL_LIB_PATH = process.env.MUSL_LIB_PATH;
    const NODE_REAL = process.env.NODE_REAL;
    let childCmd, childArgs;
    if (MUSL_LD && NODE_REAL) {
      childCmd = MUSL_LD;
      childArgs = ["--library-path", MUSL_LIB_PATH, NODE_REAL, MCP_SERVER];
    } else {
      childCmd = process.execPath;
      childArgs = [MCP_SERVER];
    }
    process.stderr.write(`[McpBridge] Spawning: ${childCmd} ${childArgs.join(" ")}\n`);
    this.child = spawn(childCmd, childArgs, {
      cwd: ROOT,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true
    });
    this.child.on("error", (err) => {
      process.stderr.write(`[McpBridge] Spawn ERROR: ${err.message}\n`);
    });
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (chunk) => this.onData(chunk));
    this.child.stderr.on("data", (chunk) => process.stderr.write(chunk));
    this.child.on("exit", (code) => {
      process.stderr.write(`[McpBridge] Child exited with code ${code}\n`);
      const error = new Error(`MCP child exited with code ${code}`);
      for (const item of this.pending.values()) item.reject(error);
      this.pending.clear();
    });
  }

  onData(chunk) {
    this.buffer += chunk;
    let newline;
    while ((newline = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, newline).trim();
      this.buffer = this.buffer.slice(newline + 1);
      if (!line) continue;
      let message;
      try { message = JSON.parse(line); } catch (error) { continue; }
      const pending = this.pending.get(String(message.id));
      if (pending) {
        this.pending.delete(String(message.id));
        clearTimeout(pending.timer);
        message.id = pending.originalId;
        pending.resolve(message);
      } else if (this.onNotification) {
        this.onNotification(message);
      }
    }
  }

  notify(message) {
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  request(message) {
    if (message.id === undefined || message.id === null) {
      this.notify(message);
      return Promise.resolve(null);
    }
    const internalId = `http-${++requestSequence}`;
    const outgoing = { ...message, id: internalId };
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(internalId);
        reject(new Error(`MCP request timed out after ${REQUEST_TIMEOUT} ms`));
      }, REQUEST_TIMEOUT);
      this.pending.set(internalId, { resolve, reject, timer, originalId: message.id });
      this.notify(outgoing);
    });
  }

  close() {
    if (!this.child.killed) this.child.kill();
  }
}

const sharedBridge = new McpBridge();

function selectionSummary() {
  try {
    return JSON.parse(fs.readFileSync(path.join(ROOT, "selection.json"), "utf8"));
  } catch (error) {
    return {};
  }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "authorization,content-type,mcp-protocol-version,mcp-session-id"
    });
    res.end();
    return;
  }
  if (!authorized(req, url)) {
    json(res, 401, { error: "unauthorized" });
    return;
  }
  if (req.method === "GET" && url.pathname === "/health") {
    const selection = selectionSummary();
    const isLite = fs.existsSync(path.join(ROOT, "selection.json"));
    json(res, 200, {
      ok: true,
      service: isLite ? "blackxml-topology-mcp-lite" : "blackxml-topology-mcp-full",
      scope: isLite ? "lite" : "full",
      feederCount: selection.feederCount || 0,
      generatedAt: selection.generatedAt || ""
    });
    return;
  }
  if (req.method === "POST" && url.pathname === "/mcp") {
    try {
      const message = await readJson(req);
      if (Array.isArray(message)) throw new Error("JSON-RPC batches are not supported");
      const response = await sharedBridge.request(message);
      if (!response) {
        res.writeHead(202, { "access-control-allow-origin": "*" });
        res.end();
        return;
      }
      json(res, 200, response, {
        "mcp-session-id": "lite-stateless",
        "mcp-protocol-version": "2024-11-05"
      });
    } catch (error) {
      json(res, 500, { jsonrpc: "2.0", id: null, error: { code: -32000, message: error.message } });
    }
    return;
  }
  if (req.method === "GET" && url.pathname === "/sse") {
    const sessionId = crypto.randomUUID();
    res.writeHead(200, {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      connection: "keep-alive",
      "access-control-allow-origin": "*"
    });
    const bridge = new McpBridge((message) => {
      if (!res.writableEnded) res.write(`event: message\ndata: ${JSON.stringify(message)}\n\n`);
    });
    sessions.set(sessionId, { bridge, res });
    const forwardedPrefix = String(req.headers["x-forwarded-prefix"] || "").replace(/\/$/, "");
    res.write(`event: endpoint\ndata: ${forwardedPrefix}/message?sessionId=${sessionId}\n\n`);
    const keepAlive = setInterval(() => {
      if (!res.writableEnded) res.write(": keepalive\n\n");
    }, 20000);
    req.on("close", () => {
      clearInterval(keepAlive);
      bridge.close();
      sessions.delete(sessionId);
    });
    return;
  }
  if (req.method === "POST" && url.pathname === "/message") {
    const session = sessions.get(url.searchParams.get("sessionId") || "");
    if (!session) {
      json(res, 404, { error: "unknown SSE session" });
      return;
    }
    try {
      session.bridge.notify(await readJson(req));
      res.writeHead(202, { "access-control-allow-origin": "*" });
      res.end();
    } catch (error) {
      json(res, 400, { error: error.message });
    }
    return;
  }
  json(res, 404, { error: "not found", endpoints: ["/health", "/mcp", "/sse"] });
});

server.listen(PORT, HOST, () => {
  const scope = fs.existsSync(path.join(ROOT, "selection.json")) ? "lite" : "full";
  console.log(`BLACKXML ${scope} MCP listening on http://${HOST}:${PORT}`);
  console.log(`Streamable JSON-RPC: http://${HOST}:${PORT}/mcp`);
  console.log(`SSE: http://${HOST}:${PORT}/sse`);
});

function shutdown() {
  for (const session of sessions.values()) session.bridge.close();
  sharedBridge.close();
  server.close(() => process.exit(0));
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
