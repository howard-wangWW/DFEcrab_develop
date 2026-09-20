#!/usr/bin/env node
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { DatabaseSync } = require("node:sqlite");

const { createLineIndex } = require("../src/indexer");
const { parseCimFile } = require("../src/cimParser");

const ROOT = path.resolve(__dirname, "..");
const XML_DIR = path.join(ROOT, "BLACKXML");
const DEFAULT_TARGET = path.join(path.dirname(ROOT), "blackxml-topology-mcp-lite");
const PRIORITY_NAMES = [
  "光明上村变电站F09中心三线",
  "光明上村变电站F01松石线",
  "光明蒋石变电站F24蒋庄线",
  "光明民生变电站F02民汇线",
  "龙华玉翠变电站F05弓村线",
  "宝城宝安变电站F10流工线",
  "宝城宝安变电站F15裕安一线",
  "宝城宝安变电站F17新安湖线",
  "宝城宝安变电站F21宝润线",
  "宝城创新变电站F18乐群线",
  "宝城创新变电站F43湖滨线",
  "罗湖黄贝岭变电站F63水库新村线",
  "罗湖八卦岭变电站F24卦力线",
  "平湖远丰变电站F17远成线",
  "光明蒋石变电站F41蒋新五线",
  "布吉登峰变电站F07上雪东线",
  "罗湖黄贝岭变电站F14集浩线",
  "福田星河变电站F05星临一线",
  "福田星河变电站F47泰安一线",
  "福田秋悦变电站F02泰安二线",
  "福田泰然变电站F45泰安线",
  "福田少年宫变电站F14星河世纪线"
];

function parseArgs(argv) {
  const result = {};
  for (let index = 2; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) continue;
    const key = item.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) result[key] = true;
    else {
      result[key] = next;
      index += 1;
    }
  }
  return result;
}

function chooseLines(index, count) {
  const selected = [];
  const seen = new Set();
  const add = (line) => {
    if (!line || line.error || seen.has(line.relativePath) || selected.length >= count) return;
    seen.add(line.relativePath);
    selected.push(line);
  };
  for (const name of PRIORITY_NAMES) {
    add(index.lines.find((line) => line.fullDisplayName === name));
  }
  const candidates = index.lines
    .filter((line) => !line.error && line.connectivityNodeCount >= 8 && line.substationCount >= 2)
    .map((line) => ({
      line,
      size: fs.statSync(path.join(XML_DIR, line.relativePath)).size
    }))
    .filter((item) => item.size <= 4 * 1024 * 1024)
    .sort((left, right) => {
      const station = left.line.fullStationName.localeCompare(right.line.fullStationName, "zh-Hans-CN");
      return station || right.line.connectivityNodeCount - left.line.connectivityNodeCount || left.size - right.size;
    });
  const districtBuckets = new Map();
  for (const item of candidates) {
    const district = item.line.district || "其他";
    if (!districtBuckets.has(district)) districtBuckets.set(district, []);
    districtBuckets.get(district).push(item.line);
  }
  const districts = [...districtBuckets.keys()].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  let progress = true;
  while (selected.length < count && progress) {
    progress = false;
    for (const district of districts) {
      const bucket = districtBuckets.get(district);
      while (bucket.length && seen.has(bucket[0].relativePath)) bucket.shift();
      if (!bucket.length) continue;
      add(bucket.shift());
      progress = true;
      if (selected.length >= count) break;
    }
  }
  return selected;
}

function collectComponentFiles(index, startRelativePath) {
  if (!(index.byConnectivityNode instanceof Map) || !(index.connectivityNodesByFile instanceof Map)) {
    return [startRelativePath];
  }
  const seen = new Set([startRelativePath]);
  const queue = [startRelativePath];
  for (let position = 0; position < queue.length; position += 1) {
    for (const cn of index.connectivityNodesByFile.get(queue[position]) || []) {
      for (const next of index.byConnectivityNode.get(cn) || []) {
        if (!next || seen.has(next)) continue;
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return queue;
}

function cleanId(value) {
  return String(value || "").trim().replace(/^(SUBST|SWITCH|SEG|BUSBAR|TRANS|WINDING)_/, "");
}

function filterTabFile(source, target, idColumn, selectedIds, encoding = "utf8") {
  const input = fs.readFileSync(source);
  const chunks = [];
  let matched = 0;
  let start = 0;
  for (let index = 0; index <= input.length; index += 1) {
    if (index < input.length && input[index] !== 10) continue;
    let end = index;
    if (end > start && input[end - 1] === 13) end -= 1;
    if (end > start && input[start] === 35) {
      const line = input.toString(encoding, start, end);
      const parts = line.split("\t");
      if (selectedIds.has(cleanId(parts[idColumn]))) {
        chunks.push(input.subarray(start, index < input.length ? index + 1 : index));
        matched += 1;
      }
    }
    start = index + 1;
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, chunks.length ? Buffer.concat(chunks) : Buffer.alloc(0));
  return matched;
}

function buildUsersDatabase(targetRoot, transformerIds) {
  const sourcePath = path.join(ROOT, "\u7528\u6237\u5217\u8868\u7d22\u5f15", "users.sqlite");
  const targetDir = path.join(targetRoot, "\u7528\u6237\u5217\u8868\u7d22\u5f15");
  fs.mkdirSync(targetDir, { recursive: true });
  const targetPath = path.join(targetDir, "users.sqlite");
  const db = new DatabaseSync(targetPath);
  db.exec(`
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE datasets (
      type TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, file_name TEXT NOT NULL,
      total_rows INTEGER NOT NULL, indexed_rows INTEGER NOT NULL, imported_at TEXT NOT NULL
    );
    CREATE TABLE users (
      dataset_id TEXT NOT NULL, type TEXT NOT NULL, transformer_id TEXT NOT NULL,
      transformer_name TEXT, feeder_id TEXT, feeder_name TEXT,
      consumer_id TEXT, consumer_name TEXT, consumer_type TEXT,
      consumer_address TEXT, voltage_level TEXT
    );
    CREATE TEMP TABLE selected_transformers(id TEXT PRIMARY KEY);
  `);
  const insertId = db.prepare("INSERT OR IGNORE INTO selected_transformers(id) VALUES(?)");
  db.exec("BEGIN");
  for (const id of transformerIds) insertId.run(id);
  db.exec("COMMIT");
  db.prepare("ATTACH DATABASE ? AS source").run(sourcePath);
  db.exec(`
    INSERT INTO users
    SELECT u.dataset_id, u.type, u.transformer_id, u.transformer_name,
           u.feeder_id, u.feeder_name, u.consumer_id, u.consumer_name,
           u.consumer_type, u.consumer_address, u.voltage_level
    FROM source.users u
    JOIN source.datasets d ON d.type = u.type AND d.dataset_id = u.dataset_id
    JOIN selected_transformers s ON s.id = u.transformer_id;

    INSERT INTO datasets(type, dataset_id, file_name, total_rows, indexed_rows, imported_at)
    SELECT u.type, MAX(u.dataset_id), 'lite-' || MAX(d.file_name), COUNT(*), COUNT(), datetime('now')
    FROM users u
    JOIN source.datasets d ON d.type = u.type AND d.dataset_id = u.dataset_id
    GROUP BY u.type;

    CREATE INDEX idx_users_dataset_transformer ON users(dataset_id, transformer_id);
    CREATE INDEX idx_users_dataset_feeder ON users(dataset_id, feeder_id);
    PRAGMA wal_checkpoint(TRUNCATE);
  `);
  const counts = db.prepare("SELECT type, indexed_rows AS count FROM datasets ORDER BY type").all();
  db.close();
  return { targetPath, counts, total: counts.reduce((sum, item) => sum + Number(item.count || 0), 0) };
}

function writeDeploymentFiles(target) {
  fs.writeFileSync(path.join(target, "package.json"), JSON.stringify({
    name: "blackxml-topology-mcp-lite",
    version: "1.0.0",
    private: true,
    description: "Lightweight BLACKXML topology MCP server",
    scripts: {
      start: "node tools/http-mcp-server.js",
      mcp: "node tools/mcp-server.js",
      "build:indexes": "node tools/build-current-catalog.js --quiet && node tools/build-grid-analytics.js --min-users 1 --quiet"
    },
    engines: { node: ">=22" }
  }, null, 2) + "\n", "utf8");
  fs.writeFileSync(path.join(target, "Dockerfile"), [
    "FROM node:22-bookworm-slim",
    "WORKDIR /app",
    "COPY . .",
    "ENV MCP_HOST=0.0.0.0 MCP_PORT=3100",
    "EXPOSE 3100",
    "CMD [\"node\", \"tools/http-mcp-server.js\"]",
    ""
  ].join("\n"), "utf8");
  fs.writeFileSync(path.join(target, "docker-compose.yml"), [
    "services:",
    "  blackxml-topology-mcp-lite:",
    "    build: .",
    "    restart: unless-stopped",
    "    ports:",
    "      - \"3100:3100\"",
    "    environment:",
    "      MCP_AUTH_TOKEN: ${MCP_AUTH_TOKEN:-}",
    ""
  ].join("\n"), "utf8");
  fs.writeFileSync(path.join(target, ".dockerignore"), [
    ".cache",
    "logs",
    "*.sqlite-shm",
    "*.sqlite-wal",
    ""
  ].join("\n"), "utf8");
}

function main() {
  const args = parseArgs(process.argv);
  const target = path.resolve(String(args.target || DEFAULT_TARGET));
  const count = Math.max(20, Math.min(Number(args.count) || 50, 80));
  if (fs.existsSync(target)) throw new Error(`Target already exists: ${target}`);
  fs.mkdirSync(target, { recursive: true });
  fs.mkdirSync(path.join(target, "BLACKXML"), { recursive: true });
  fs.mkdirSync(path.join(target, "\u5f00\u5173\u72b6\u6001"), { recursive: true });
  fs.cpSync(path.join(ROOT, "src"), path.join(target, "src"), { recursive: true });
  fs.mkdirSync(path.join(target, "tools"), { recursive: true });
  for (const name of [
    "mcp-server.js", "http-mcp-server.js", "build-current-catalog.js", "build-grid-analytics.js"
  ]) {
    fs.copyFileSync(path.join(ROOT, "tools", name), path.join(target, "tools", name));
  }

  const index = createLineIndex(XML_DIR);
  const seedLines = chooseLines(index, count);
  const componentByFile = new Map();
  const packageFiles = new Set(seedLines.map((line) => line.relativePath));
  for (const line of seedLines) {
    const componentFiles = collectComponentFiles(index, line.relativePath);
    for (const file of componentFiles) componentByFile.set(file, componentFiles);
    if (componentFiles.length <= 4) {
      for (const file of componentFiles) packageFiles.add(file);
    }
  }
  const selected = [...packageFiles].map((file) => index.map[file]).filter(Boolean);
  for (const line of selected) {
    if (!componentByFile.has(line.relativePath)) {
      const componentFiles = collectComponentFiles(index, line.relativePath);
      for (const file of componentFiles) componentByFile.set(file, componentFiles);
    }
  }
  const selectedEquipmentIds = new Set();
  const transformerIds = new Set();
  let xmlBytes = 0;
  for (const line of selected) {
    const source = path.join(XML_DIR, line.relativePath);
    const destination = path.join(target, "BLACKXML", line.relativePath);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.copyFileSync(source, destination);
    xmlBytes += fs.statSync(source).size;
    const model = parseCimFile(source, { includeTerminals: false });
    for (const item of model.equipment.values()) {
      selectedEquipmentIds.add(cleanId(item.id));
      selectedEquipmentIds.add(cleanId(item.mrid));
      if (item.tag === "PowerTransformer") {
        transformerIds.add(item.id);
        transformerIds.add(item.mrid);
        if (item.mrid) transformerIds.add(`TRANS_${item.mrid}`);
      }
    }
  }

  const statusFiles = fs.readdirSync(path.join(ROOT, "\u5f00\u5173\u72b6\u6001"));
  const statusRows = {};
  for (const name of statusFiles) {
    const source = path.join(ROOT, "\u5f00\u5173\u72b6\u6001", name);
    if (!fs.statSync(source).isFile()) continue;
    statusRows[name] = filterTabFile(
      source,
      path.join(target, "\u5f00\u5173\u72b6\u6001", name),
      1,
      selectedEquipmentIds,
      "utf8"
    );
  }
  const currentFiles = fs.readdirSync(ROOT).filter((name) => /^sz_\d{8}_\d{6}_dms\.dat$/i.test(name));
  const currentRows = {};
  for (const name of currentFiles) {
    currentRows[name] = filterTabFile(
      path.join(ROOT, name),
      path.join(target, name),
      3,
      selectedEquipmentIds,
      "latin1"
    );
  }
  const users = buildUsersDatabase(target, [...transformerIds]);
  writeDeploymentFiles(target);

  const selection = {
    generatedAt: new Date().toISOString(),
    sourceRoot: ROOT,
    seedTopologyFileCount: seedLines.length,
    seedFeederCount: new Set(seedLines.map((line) => line.id).filter(Boolean)).size,
    topologyFileCount: selected.length,
    feederCount: new Set(selected.map((line) => line.id).filter(Boolean)).size,
    xmlSizeMB: Math.round(xmlBytes / 1024 / 1024 * 100) / 100,
    equipmentIdCount: selectedEquipmentIds.size,
    transformerIdCount: transformerIds.size,
    statusRows,
    currentRows,
    users,
    completeSeedCount: seedLines.filter((line) => {
      const component = componentByFile.get(line.relativePath) || [line.relativePath];
      return component.every((file) => packageFiles.has(file));
    }).length,
    incompleteSeedCount: seedLines.filter((line) => {
      const component = componentByFile.get(line.relativePath) || [line.relativePath];
      return !component.every((file) => packageFiles.has(file));
    }).length,
    topologyCompleteness: Object.fromEntries(selected.map((line) => {
      const component = componentByFile.get(line.relativePath) || [line.relativePath];
      const included = component.filter((file) => packageFiles.has(file));
      return [line.relativePath, {
        complete: included.length === component.length,
        componentFileCount: component.length,
        includedFileCount: included.length,
        missingFileCount: component.length - included.length
      }];
    })),
    seedFeeders: seedLines.map((line) => ({
      id: line.id,
      name: line.fullDisplayName,
      file: line.relativePath
    })),
    feeders: selected.map((line) => ({
      id: line.id,
      name: line.fullDisplayName,
      file: line.relativePath,
      district: line.district,
      station: line.fullStationName,
      feederNo: line.feederNo
    }))
  };
  fs.writeFileSync(path.join(target, "selection.json"), JSON.stringify(selection, null, 2), "utf8");
  execFileSync(process.execPath, [path.join(target, "tools", "build-current-catalog.js"), "--quiet"], {
    cwd: target,
    stdio: "inherit"
  });
  execFileSync(process.execPath, [path.join(target, "tools", "build-grid-analytics.js"), "--min-users", "1", "--quiet"], {
    cwd: target,
    stdio: "inherit"
  });
  console.log(JSON.stringify({ target, ...selection, feeders: selection.feeders.length }, null, 2));
}

main();
