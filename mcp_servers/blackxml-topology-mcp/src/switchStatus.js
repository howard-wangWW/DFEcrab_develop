//开关状态加载器
//功能 ：加载 .dt 文件中记录的开关分/合状态
// 文件格式:
//   SZ_20260518040000_PD_ALL.dt  → 全量状态
//   SZ_20260518140000_PD.dt      → 增量状态
// 每个 .dt 文件:
//   - 包含所有开关的 ID 和当前状态（合=1/分=0）
//   - 自动选最新时间戳的文件
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

let cache = null;

function cleanStatusId(value) {
  return String(value || "").trim().replace(/^(SUBST|SWITCH|SEG|BUSBAR|TRANS|WINDING)_/, "");
}

function timestampFromName(name) {
  const match = String(name || "").match(/(\d{14})/);
  return match ? match[1] : "";
}

function classifyStatusFile(filePath) {
  const name = path.basename(filePath);
  const upper = name.toUpperCase();
  if (!upper.endsWith(".DT")) return null;
  const isGround = upper.includes("SZGND_");
  const isSwitch = !isGround && upper.includes("SZ_");
  if (!isGround && !isSwitch) return null;
  if (!upper.includes("_PD")) return null;
  return {
    path: filePath,
    name,
    kind: isGround ? "ground" : "switch",
    mode: upper.includes("_PD_ALL") ? "full" : "increment",
    timestamp: timestampFromName(name)
  };
}

function statusSignature(files) {
  return files
    .map((file) => {
      const stat = fs.statSync(file.path);
      return `${file.path}|${stat.size}|${stat.mtimeMs}`;
    })
    .sort()
    .join("\n");
}

function signatureVersion(signature) {
  return crypto.createHash("sha1").update(signature || "").digest("hex");
}

function readStatusRows(file) {
  const text = fs.readFileSync(file.path, "utf8");
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.startsWith("#")) continue;
    const parts = line.split("\t");
    if (parts.length < 5) continue;
    const rawId = cleanStatusId(parts[1]);
    const value = String(parts[3] || "").trim();
    if (!rawId || !/^[01]$/.test(value)) continue;
    rows.push({
      rawId,
      closed: value === "1",
      value,
      quality: String(parts[4] || "").trim(),
      switchType: String(parts[5] || "").trim(),
      fileName: file.name,
      timestamp: file.timestamp,
      mode: file.mode,
      kind: file.kind
    });
  }
  return rows;
}

function selectedFilesForKind(files, kind) {
  const items = files
    .filter((file) => file.kind === kind)
    .sort((a, b) => {
      const byTime = a.timestamp.localeCompare(b.timestamp);
      if (byTime) return byTime;
      return (a.mode === "full" ? 0 : 1) - (b.mode === "full" ? 0 : 1);
    });
  const fulls = items.filter((file) => file.mode === "full");
  const latestFull = fulls[fulls.length - 1] || null;
  if (!latestFull) return items.filter((file) => file.mode === "increment");
  return items.filter((file) => {
    if (file.path === latestFull.path) return true;
    return file.mode === "increment" && file.timestamp >= latestFull.timestamp;
  });
}

function applyFiles(files) {
  const byRawId = new Map();
  let rows = 0;
  for (const file of files) {
    const parsed = readStatusRows(file);
    rows += parsed.length;
    for (const row of parsed) {
      byRawId.set(row.rawId, row);
    }
  }
  return {
    byRawId,
    rows,
    files: files.map((file) => ({
      name: file.name,
      kind: file.kind,
      mode: file.mode,
      timestamp: file.timestamp
    }))
  };
}

function emptyStatus(statusDir, error = "") {
  return {
    statusDir,
    error,
    switch: { byRawId: new Map(), rows: 0, files: [] },
    ground: { byRawId: new Map(), rows: 0, files: [] },
    summary: {
      statusDir,
      error,
      version: "",
      switchFiles: [],
      groundFiles: [],
      switchRows: 0,
      groundRows: 0,
      switchCount: 0,
      groundCount: 0
    }
  };
}

function loadSwitchStatus(statusDir) {
  if (!statusDir || !fs.existsSync(statusDir)) {
    cache = null;
    return emptyStatus(statusDir || "", "status directory not found");
  }

  const files = fs
    .readdirSync(statusDir)
    .map((name) => path.join(statusDir, name))
    .filter((filePath) => fs.statSync(filePath).isFile())
    .map(classifyStatusFile)
    .filter(Boolean);
  const signature = statusSignature(files);
  if (cache && cache.statusDir === statusDir && cache.signature === signature) return cache.data;
  const version = signatureVersion(signature);

  const switchData = applyFiles(selectedFilesForKind(files, "switch"));
  const groundData = applyFiles(selectedFilesForKind(files, "ground"));
  const data = {
    statusDir,
    error: "",
    switch: switchData,
    ground: groundData,
    summary: {
      statusDir,
      error: "",
      version,
      switchFiles: switchData.files,
      groundFiles: groundData.files,
      switchRows: switchData.rows,
      groundRows: groundData.rows,
      switchCount: switchData.byRawId.size,
      groundCount: groundData.byRawId.size
    }
  };
  cache = { statusDir, signature, data };
  return data;
}

function getStatusForEquipment(item, switchStatus) {
  if (!item || !switchStatus) return null;
  const candidates = [
    cleanStatusId(item.id),
    cleanStatusId(item.mrid)
  ].filter(Boolean);
  const seen = new Set();
  const ids = candidates.filter((id) => {
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  const primary = item.tag === "GroundDisconnector" ? switchStatus.ground : switchStatus.switch;
  const secondary = item.tag === "GroundDisconnector" ? switchStatus.switch : switchStatus.ground;
  for (const id of ids) {
    const hit = primary && primary.byRawId && primary.byRawId.get(id);
    if (hit) return hit;
  }
  for (const id of ids) {
    const hit = secondary && secondary.byRawId && secondary.byRawId.get(id);
    if (hit) return hit;
  }
  return null;
}

function serializableStatusSummary(switchStatus) {
  return switchStatus && switchStatus.summary ? switchStatus.summary : emptyStatus("").summary;
}

module.exports = {
  cleanStatusId,
  getStatusForEquipment,
  loadSwitchStatus,
  serializableStatusSummary
};
