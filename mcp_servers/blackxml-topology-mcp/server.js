const fs = require("fs");
const http = require("http");
const path = require("path");
const url = require("url");

const { createLineIndex, resolveIndexedFile } = require("./src/indexer");
const { buildTopologyFromFile } = require("./src/topology");
const { loadSwitchStatus } = require("./src/switchStatus");
const { loadSwitchCurrent } = require("./src/switchCurrent");
const { createUserStore } = require("./src/userStore");
const { buildTopologyText } = require("./src/textTopology");

const ROOT = __dirname;
const XML_DIR = path.join(ROOT, "BLACKXML");
const STATUS_DIR = path.join(ROOT, "\u5f00\u5173\u72b6\u6001");
const CURRENT_DIRS = [ROOT, STATUS_DIR];
const PUBLIC_DIR = path.join(ROOT, "public");
const PORT = Number(process.env.PORT || 5173);
const IMPORT_LIMIT = 80 * 1024 * 1024;

let indexCache = null;
const userStore = createUserStore(ROOT);

function send(res, status, body, type = "application/json; charset=utf-8") {
  res.writeHead(status, {
    "Content-Type": type,
    "Cache-Control": "no-store"
  });
  res.end(body);
}

function json(res, status, data) {
  send(res, status, JSON.stringify(data), "application/json; charset=utf-8");
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function getIndex() {
  if (!indexCache) {
    indexCache = createLineIndex(XML_DIR);
  }
  return indexCache;
}

function runtimeStatusSummary() {
  const switchSummary = loadSwitchStatus(STATUS_DIR).summary;
  const currentSummary = loadSwitchCurrent(CURRENT_DIRS).summary;
  return {
    ...switchSummary,
    current: currentSummary,
    currentFiles: currentSummary.currentFiles,
    currentRows: currentSummary.currentRows,
    currentCount: currentSummary.currentCount,
    currentVersion: currentSummary.version
  };
}

function collectBody(req, limit = IMPORT_LIMIT) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error("XML file is too large"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function safeXmlRelativePath(name) {
  const raw = String(name || "import.xml").replace(/\\/g, "/");
  const parts = raw
    .split("/")
    .filter(Boolean)
    .filter((part) => part !== "." && part !== "..")
    .map((part) => part.replace(/[<>:"/\\|?*\x00-\x1f]/g, "_"))
    .filter(Boolean);
  let relativePath = parts.join("/");
  if (!relativePath) relativePath = "import.xml";
  if (!relativePath.toLowerCase().endsWith(".xml")) relativePath = `${relativePath}.xml`;
  return relativePath;
}

async function importXml(req, res, parsed) {
  if (req.method !== "POST") {
    json(res, 405, { error: "POST required" });
    return;
  }
  const xml = await collectBody(req);
  if (!/<rdf:RDF[\s>]|<cim:/.test(xml)) {
    json(res, 400, { error: "not a CIM/RDF XML file" });
    return;
  }
  const relativePath = safeXmlRelativePath(parsed.query.path || parsed.query.name || req.headers["x-file-name"]);
  const root = path.normalize(XML_DIR);
  const target = path.normalize(path.join(XML_DIR, relativePath));
  if (target !== root && !target.startsWith(root + path.sep)) {
    json(res, 403, { error: "invalid file name" });
    return;
  }
  await fs.promises.mkdir(path.dirname(target), { recursive: true });
  await fs.promises.writeFile(target, xml, "utf8");
  indexCache = null;
  const index = getIndex();
  const line = index.map[relativePath] || index.lines.find((item) => item.relativePath === relativePath) || null;
  json(res, 200, {
    ok: true,
    fileName: path.basename(relativePath),
    relativePath,
    line,
    count: index.count
  });
}

async function importUsers(req, res, parsed) {
  if (req.method !== "POST") {
    json(res, 405, { error: "POST required" });
    return;
  }
  const type = String(parsed.query.type || "").toUpperCase();
  const fileName = parsed.query.name || req.headers["x-file-name"] || `${type}.csv`;
  const result = await userStore.importCsv(req, { type, fileName });
  json(res, 200, { ok: true, ...result });
}

async function collectJson(req) {
  const body = await collectBody(req, 2 * 1024 * 1024);
  return body ? JSON.parse(body) : {};
}

async function exportImpactUsers(req, res) {
  if (req.method !== "POST") {
    json(res, 405, { error: "POST required" });
    return;
  }
  const body = await collectJson(req);
  const transformerIds = body.transformerIds || [];
  const fileName = encodeURIComponent(String(body.fileName || "失电影响用户.csv").replace(/[\\/:*?"<>|]/g, "_"));
  res.writeHead(200, {
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": `attachment; filename*=UTF-8''${fileName}`,
    "Cache-Control": "no-store"
  });
  res.write("\uFEFF用户类型,用户编号,用户名称,用户类别,用户地址,变压器ID,变压器名称,馈线ID,馈线名称,电压等级\r\n");
  for (const item of userStore.iterateUsers(transformerIds)) {
    const row = [
      item.type === "ZY" ? "中压" : "低压",
      item.consumerId,
      item.consumerName,
      item.consumerType,
      item.consumerAddress,
      item.transformerId,
      item.transformerName,
      item.feederId,
      item.feederName,
      item.voltageLevel
    ].map(csvCell).join(",");
    if (!res.write(`${row}\r\n`)) {
      await new Promise((resolve) => res.once("drain", resolve));
    }
  }
  res.end();
}

async function exportTopologyText(req, res) {
  if (req.method !== "POST") {
    json(res, 405, { error: "POST required" });
    return;
  }
  const body = await collectJson(req);
  const index = getIndex();
  const filePath = resolveIndexedFile(XML_DIR, index, body.file);
  if (!filePath) {
    json(res, 404, { error: "XML file not found in index" });
    return;
  }
  const topology = buildTopologyFromFile({
    xmlDir: XML_DIR,
    filePath,
    index,
    relatedMode: body.related || "auto",
    maxRelated: Number(body.maxRelated || 64),
    maxNodes: Number(body.maxNodes || 900),
    switchStatus: loadSwitchStatus(STATUS_DIR),
    switchCurrent: loadSwitchCurrent(CURRENT_DIRS)
  });
  const text = buildTopologyText(topology, body.switchStates || {});
  const baseName = String(
    body.fileName || `${topology.line.displayName || topology.line.lineName || "图模"}-文字拓扑.txt`
  ).replace(/[\\/:*?"<>|]/g, "_");
  res.writeHead(200, {
    "Content-Type": "text/plain; charset=utf-8",
    "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(baseName)}`,
    "Cache-Control": "no-store"
  });
  res.end(`\uFEFF${text}`);
}

function serveStatic(req, res, pathname) {
  let local = pathname === "/" ? "/index.html" : pathname;
  local = decodeURIComponent(local).replace(/\//g, path.sep);
  const target = path.normalize(path.join(PUBLIC_DIR, local));
  if (!target.startsWith(PUBLIC_DIR)) {
    send(res, 403, "Forbidden", "text/plain; charset=utf-8");
    return;
  }
  fs.readFile(target, (err, data) => {
    if (err) {
      send(res, 404, "Not found", "text/plain; charset=utf-8");
      return;
    }
    const ext = path.extname(target).toLowerCase();
    const types = {
      ".html": "text/html; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".csv": "text/csv; charset=utf-8",
      ".svg": "image/svg+xml; charset=utf-8",
      ".png": "image/png"
    };
    send(res, 200, data, types[ext] || "application/octet-stream");
  });
}

async function handleApi(req, res, parsed) {
  const pathname = parsed.pathname;
  if (pathname === "/api/import") {
    await importXml(req, res, parsed);
    return;
  }

  if (pathname === "/api/users/import") {
    await importUsers(req, res, parsed);
    return;
  }

  if (pathname === "/api/users/status") {
    json(res, 200, userStore.status());
    return;
  }

  if (pathname === "/api/users/query") {
    if (req.method !== "POST") {
      json(res, 405, { error: "POST required" });
      return;
    }
    const body = await collectJson(req);
    json(res, 200, userStore.queryUsers(body.transformerIds, body.limit));
    return;
  }

  if (pathname === "/api/users/export") {
    await exportImpactUsers(req, res);
    return;
  }

  if (pathname === "/api/topology/text") {
    await exportTopologyText(req, res);
    return;
  }

  if (pathname === "/api/lines") {
    const force = parsed.query.refresh === "1";
    if (force) indexCache = null;
    json(res, 200, getIndex());
    return;
  }

  if (pathname === "/api/status") {
    json(res, 200, runtimeStatusSummary());
    return;
  }

  if (pathname === "/api/topology" || pathname === "/api/svg") {
    const index = getIndex();
    const fileParam = parsed.query.file;
    if (!fileParam) {
      json(res, 400, { error: "missing file query parameter" });
      return;
    }
    const filePath = resolveIndexedFile(XML_DIR, index, fileParam);
    if (!filePath) {
      json(res, 404, { error: "XML file not found in index" });
      return;
    }
    const topology = buildTopologyFromFile({
      xmlDir: XML_DIR,
      filePath,
      index,
      relatedMode: parsed.query.related || "auto",
      maxRelated: Number(parsed.query.maxRelated || 64),
      maxNodes: Number(parsed.query.maxNodes || 900),
      switchStatus: loadSwitchStatus(STATUS_DIR),
      switchCurrent: loadSwitchCurrent(CURRENT_DIRS)
    });
    if (pathname === "/api/svg") {
      send(res, 200, topology.svg, "image/svg+xml; charset=utf-8");
    } else {
      json(res, 200, topology);
    }
    return;
  }

  json(res, 404, { error: "unknown api route" });
}

const server = http.createServer((req, res) => {
  const parsed = url.parse(req.url, true);
  if (parsed.pathname.startsWith("/api/")) {
    Promise.resolve(handleApi(req, res, parsed)).catch((err) => {
      console.error(err);
      json(res, 500, { error: err.message, stack: err.stack });
    });
    return;
  }
  serveStatic(req, res, parsed.pathname);
});

server.requestTimeout = 0;
server.listen(PORT, () => {
  console.log(`Topology manager running at http://localhost:${PORT}`);
});
