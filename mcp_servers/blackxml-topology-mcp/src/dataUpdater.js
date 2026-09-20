//数据在线更新
//输入更新目录中的文件，输出更新后的索引
const fs = require("fs");
const path = require("path");
const { execFile } = require("child_process");
const { promisify } = require("util");

const { createUserStore } = require("./userStore");
const {
  CODE_ROOT,
  DATA_ROOT,
  XML_DIR,
  STATUS_DIR,
  CURRENT_DIR,
  UPDATE_DIR,
  BACKUP_DIR
} = require("./dataPaths");

const execFileAsync = promisify(execFile);
const MAX_LIST_FILES = 500;
const UPDATE_LOCK = path.join(DATA_ROOT, ".mcp-data-update.lock");
let updateRunning = false;

function updatesEnabled() {
  return String(process.env.MCP_ENABLE_UPDATES || "").toLowerCase() === "true";
}

function requireUpdateAccess(confirm) {
  if (!updatesEnabled()) throw new Error("MCP data updates are disabled by the administrator.");
  if (confirm !== "APPLY") throw new Error('Set confirm to "APPLY" to perform this update.');
  if (updateRunning) throw new Error("Another MCP data update is already running.");
}

function safeInboxFile(name, extensions) {
  const value = String(name || "").trim();
  if (!value || path.basename(value) !== value || value.includes("..")) {
    throw new Error(`Invalid update file name: ${value || "(empty)"}`);
  }
  const extension = path.extname(value).toLowerCase();
  if (!extensions.includes(extension)) throw new Error(`Unsupported file extension: ${extension}`);
  const source = path.join(UPDATE_DIR, value);
  if (!fs.existsSync(source) || !fs.statSync(source).isFile()) {
    throw new Error(`Update file not found: ${value}`);
  }
  return source;
}

function timestamp() {
  return new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14);
}

function fileInfo(filePath) {
  const stat = fs.statSync(filePath);
  return {
    name: path.basename(filePath),
    size: stat.size,
    modifiedAt: stat.mtime.toISOString()
  };
}

function listUpdateFiles() {
  fs.mkdirSync(UPDATE_DIR, { recursive: true });
  const files = fs.readdirSync(UPDATE_DIR, { withFileTypes: true })
    .filter((item) => item.isFile())
    .map((item) => fileInfo(path.join(UPDATE_DIR, item.name)))
    .sort((left, right) => right.modifiedAt.localeCompare(left.modifiedAt))
    .slice(0, MAX_LIST_FILES);
  return {
    enabled: updatesEnabled(),
    updateDir: UPDATE_DIR,
    files,
    accepted: {
      xml: [".xml"],
      users: [".csv"],
      switchCurrent: [".dat"],
      switchStatus: [".dt"]
    }
  };
}

function backupExisting(target, group, batch) {
  if (!fs.existsSync(target)) return null;
  const backupDirectory = path.join(BACKUP_DIR, batch, group);
  fs.mkdirSync(backupDirectory, { recursive: true });
  const backup = path.join(backupDirectory, path.basename(target));
  fs.copyFileSync(target, backup);
  return backup;
}

function copyAtomic(source, target, group, batch) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const backup = backupExisting(target, group, batch);
  const temporary = `${target}.update-${process.pid}-${Date.now()}`;
  fs.copyFileSync(source, temporary);
  try {
    fs.renameSync(temporary, target);
  } catch (error) {
    if (process.platform !== "win32" || !["EEXIST", "EPERM"].includes(error.code)) throw error;
    fs.rmSync(target, { force: true });
    fs.renameSync(temporary, target);
  }
  return { source: fileInfo(source), target, backup };
}

function validateXml(source) {
  const descriptor = fs.openSync(source, "r");
  try {
    const size = Math.min(fs.statSync(source).size, 1024 * 1024);
    const buffer = Buffer.alloc(size);
    fs.readSync(descriptor, buffer, 0, size, 0);
    const text = buffer.toString("utf8");
    if (!/<rdf:RDF[\s>]|<cim:|<cim\d*:/i.test(text)) {
      throw new Error(`${path.basename(source)} is not a CIM/RDF XML file.`);
    }
  } finally {
    fs.closeSync(descriptor);
  }
}

async function withUpdateLock(work) {
  fs.mkdirSync(DATA_ROOT, { recursive: true });
  let lock;
  try {
    lock = fs.openSync(UPDATE_LOCK, "wx");
    fs.writeFileSync(lock, JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString() }));
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    const age = Date.now() - fs.statSync(UPDATE_LOCK).mtimeMs;
    if (age < 2 * 60 * 60 * 1000) throw new Error("Another MCP data update is already running.");
    fs.rmSync(UPDATE_LOCK, { force: true });
    lock = fs.openSync(UPDATE_LOCK, "wx");
  }
  updateRunning = true;
  try {
    return await work();
  } finally {
    updateRunning = false;
    if (lock !== undefined) fs.closeSync(lock);
    fs.rmSync(UPDATE_LOCK, { force: true });
  }
}

async function updateXmlFiles(args = {}) {
  requireUpdateAccess(args.confirm);
  const names = Array.isArray(args.files) ? args.files : [args.file].filter(Boolean);
  if (!names.length || names.length > 500) throw new Error("Provide between 1 and 500 XML file names.");
  return withUpdateLock(async () => {
    const batch = timestamp();
    const results = [];
    for (const name of names) {
      const source = safeInboxFile(name, [".xml"]);
      validateXml(source);
      results.push(copyAtomic(source, path.join(XML_DIR, path.basename(source)), "BLACKXML", batch));
    }
    return { updated: results.length, batch, files: results };
  });
}

async function updateUserIndex(args = {}) {
  requireUpdateAccess(args.confirm);
  const inputs = [
    ["ZY", args.zyFile],
    ["DY", args.dyFile]
  ].filter(([, name]) => name);
  if (!inputs.length) throw new Error("Provide zyFile and/or dyFile.");
  return withUpdateLock(async () => {
    const store = createUserStore(DATA_ROOT);
    const results = [];
    for (const [type, name] of inputs) {
      const source = safeInboxFile(name, [".csv"]);
      const result = await store.importCsv(fs.createReadStream(source), {
        type,
        fileName: path.basename(source)
      });
      results.push({
        type,
        file: fileInfo(source),
        totalRows: result.totalRows,
        indexedRows: result.indexedRows,
        datasetId: result.datasetId
      });
    }
    return { updated: results.length, datasets: results, status: store.status() };
  });
}

async function updateSwitchCurrent(args = {}) {
  requireUpdateAccess(args.confirm);
  return withUpdateLock(async () => {
    const source = safeInboxFile(args.file, [".dat"]);
    const batch = timestamp();
    return {
      batch,
      file: copyAtomic(source, path.join(CURRENT_DIR, path.basename(source)), "switch-current", batch)
    };
  });
}

async function updateSwitchStatus(args = {}) {
  requireUpdateAccess(args.confirm);
  const names = Array.isArray(args.files) ? args.files : [args.file].filter(Boolean);
  if (!names.length || names.length > 20) throw new Error("Provide between 1 and 20 switch-status files.");
  return withUpdateLock(async () => {
    const batch = timestamp();
    const results = names.map((name) => {
      const source = safeInboxFile(name, [".dt"]);
      return copyAtomic(source, path.join(STATUS_DIR, path.basename(source)), "switch-status", batch);
    });
    return { updated: results.length, batch, files: results };
  });
}

async function runBuilder(script, args = []) {
  const result = await execFileAsync(process.execPath, [path.join(CODE_ROOT, "tools", script), ...args], {
    cwd: CODE_ROOT,
    env: process.env,
    timeout: Math.max(60000, Number(process.env.MCP_REBUILD_TIMEOUT_MS) || 20 * 60 * 1000),
    maxBuffer: 5 * 1024 * 1024,
    windowsHide: true
  });
  const output = String(result.stdout || "").trim();
  return { script, output: output.slice(-12000) };
}

async function rebuildIndexes(args = {}) {
  requireUpdateAccess(args.confirm);
  const target = String(args.target || "all").toLowerCase();
  if (!["current", "analytics", "all"].includes(target)) {
    throw new Error("target must be current, analytics, or all.");
  }
  return withUpdateLock(async () => {
    const results = [];
    if (target === "current" || target === "all") {
      results.push(await runBuilder("build-current-catalog.js", ["--quiet"]));
    }
    if (target === "analytics" || target === "all") {
      const minUsers = Math.max(1, Math.floor(Number(args.minUsers) || 1));
      results.push(await runBuilder("build-grid-analytics.js", ["--min-users", String(minUsers), "--quiet"]));
    }
    return { rebuilt: target, results };
  });
}

async function updateDataBundle(args = {}) {
  requireUpdateAccess(args.confirm);
  const xmlNames = Array.isArray(args.xmlFiles) ? args.xmlFiles : [];
  const statusNames = Array.isArray(args.statusFiles) ? args.statusFiles : [];
  if (xmlNames.length > 500) throw new Error("Provide no more than 500 XML files.");
  if (statusNames.length > 20) throw new Error("Provide no more than 20 switch-status files.");

  const xmlSources = xmlNames.map((name) => safeInboxFile(name, [".xml"]));
  xmlSources.forEach(validateXml);
  const userInputs = [
    ["ZY", args.zyFile],
    ["DY", args.dyFile]
  ].filter(([, name]) => name)
    .map(([type, name]) => [type, safeInboxFile(name, [".csv"])]);
  const currentSource = args.currentFile ? safeInboxFile(args.currentFile, [".dat"]) : null;
  const statusSources = statusNames.map((name) => safeInboxFile(name, [".dt"]));
  const rebuild = args.rebuild === undefined ? "all" : String(args.rebuild).toLowerCase();
  if (!["none", "current", "analytics", "all"].includes(rebuild)) {
    throw new Error("rebuild must be none, current, analytics, or all.");
  }
  if (!xmlSources.length && !userInputs.length && !currentSource && !statusSources.length) {
    throw new Error("Provide at least one XML, CSV, DAT, or DT update file.");
  }

  return withUpdateLock(async () => {
    const batch = timestamp();
    const result = {
      batch,
      blackxml: [],
      users: [],
      switchCurrent: null,
      switchStatus: [],
      indexes: []
    };
    for (const source of xmlSources) {
      result.blackxml.push(copyAtomic(source, path.join(XML_DIR, path.basename(source)), "BLACKXML", batch));
    }
    if (userInputs.length) {
      const store = createUserStore(DATA_ROOT);
      for (const [type, source] of userInputs) {
        const imported = await store.importCsv(fs.createReadStream(source), {
          type,
          fileName: path.basename(source)
        });
        result.users.push({
          type,
          file: fileInfo(source),
          totalRows: imported.totalRows,
          indexedRows: imported.indexedRows,
          datasetId: imported.datasetId
        });
      }
    }
    if (currentSource) {
      result.switchCurrent = copyAtomic(
        currentSource,
        path.join(CURRENT_DIR, path.basename(currentSource)),
        "switch-current",
        batch
      );
    }
    for (const source of statusSources) {
      result.switchStatus.push(
        copyAtomic(source, path.join(STATUS_DIR, path.basename(source)), "switch-status", batch)
      );
    }
    if (rebuild === "current" || rebuild === "all") {
      result.indexes.push(await runBuilder("build-current-catalog.js", ["--quiet"]));
    }
    if (rebuild === "analytics" || rebuild === "all") {
      const minUsers = Math.max(1, Math.floor(Number(args.minUsers) || 1));
      result.indexes.push(
        await runBuilder("build-grid-analytics.js", ["--min-users", String(minUsers), "--quiet"])
      );
    }
    if (args.syncDameng === true) {
      const syncArgs = args.syncDamengUsers === true ? ["--users"] : [];
      result.dameng = await runBuilder("sync-to-dameng.js", syncArgs);
    }
    return result;
  });
}

async function syncToDameng(args = {}) {
  requireUpdateAccess(args.confirm);
  return withUpdateLock(async () => {
    const syncArgs = args.includeUsers === true ? ["--users"] : [];
    return runBuilder("sync-to-dameng.js", syncArgs);
  });
}

async function reloadUpdateManifest(args = {}) {
  requireUpdateAccess(args.confirm);
  const manifestName = String(args.manifest || "reload.json").trim();
  const manifestPath = safeInboxFile(manifestName, [".json"]);
  if (fs.statSync(manifestPath).size > 1024 * 1024) {
    throw new Error("Reload manifest must not exceed 1 MB.");
  }
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`Invalid reload manifest: ${error.message}`);
  }
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error("Reload manifest must contain a JSON object.");
  }
  const result = await updateDataBundle({ ...manifest, confirm: args.confirm });
  const archivedName = `${path.basename(manifestName, ".json")}.applied-${result.batch}.json`;
  fs.renameSync(manifestPath, path.join(UPDATE_DIR, archivedName));
  return { manifest: manifestName, archivedAs: archivedName, result };
}

module.exports = {
  listUpdateFiles,
  reloadUpdateManifest,
  syncToDameng,
  rebuildIndexes,
  updateDataBundle,
  updateSwitchCurrent,
  updateSwitchStatus,
  updateUserIndex,
  updateXmlFiles,
  updatesEnabled
};
