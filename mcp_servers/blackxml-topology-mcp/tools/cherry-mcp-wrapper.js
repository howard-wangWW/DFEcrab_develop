#!/usr/bin/env node
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const LOG_DIR = path.join(ROOT, "logs");
const LOG_FILE = path.join(LOG_DIR, "cherry-mcp-wrapper.log");
const SERVER = path.join(__dirname, "mcp-server.js");
const NODE = process.execPath;

fs.mkdirSync(LOG_DIR, { recursive: true });

function log(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  fs.appendFileSync(LOG_FILE, line, "utf8");
}

log(`wrapper start node=${NODE} server=${SERVER} cwd=${process.cwd()}`);

const child = spawn(NODE, [SERVER], {
  cwd: ROOT,
  stdio: ["pipe", "pipe", "pipe"],
  env: {
    ...process.env,
    BLACKXML_MCP_WRAPPED: "1"
  },
  windowsHide: true
});

child.on("spawn", () => log(`child spawned pid=${child.pid}`));
child.on("error", (error) => log(`child error ${error.stack || error.message}`));
child.on("exit", (code, signal) => log(`child exit code=${code} signal=${signal || ""}`));

process.stdin.on("data", (chunk) => {
  log(`stdin ${chunk.length} bytes ${chunk.slice(0, 120).toString("utf8").replace(/\r/g, "\\r").replace(/\n/g, "\\n")}`);
  child.stdin.write(chunk);
});

process.stdin.on("end", () => {
  log("stdin end");
  child.stdin.end();
});

child.stdout.on("data", (chunk) => {
  log(`stdout ${chunk.length} bytes ${chunk.slice(0, 120).toString("utf8").replace(/\r/g, "\\r").replace(/\n/g, "\\n")}`);
  process.stdout.write(chunk);
});

child.stderr.on("data", (chunk) => {
  log(`stderr ${chunk.length} bytes ${chunk.toString("utf8").slice(0, 1000)}`);
});

process.on("exit", (code) => {
  log(`wrapper exit code=${code}`);
  if (!child.killed) child.kill();
});
