//开关电流加载器
//功能 ：加载 .dat 文件中记录的开关电流值
// 文件格式:
//   sz_20260324_161500_DMS.DAT
//   每行一个开关记录: 开关ID + Ia + Ib + Ic + I0 (三相电流+零序)
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const { cleanStatusId } = require("./switchStatus");

let cache = null;

function timestampFromName(name) {
  const match = String(name || "").match(/(\d{8})_(\d{6})/);
  return match ? `${match[1]}${match[2]}` : "";
}

function classifyCurrentFile(filePath) {
  const name = path.basename(filePath);
  if (!/^sz_\d{8}_\d{6}_dms\.dat$/i.test(name)) return null;
  return {
    path: filePath,
    name,
    timestamp: timestampFromName(name)
  };
}

function collectCurrentFiles(input) {
  const dirs = (Array.isArray(input) ? input : [input]).filter(Boolean);
  const seen = new Set();
  const files = [];
  for (const dir of dirs) {
    if (!fs.existsSync(dir)) continue;
    for (const name of fs.readdirSync(dir)) {
      const filePath = path.join(dir, name);
      if (seen.has(filePath)) continue;
      seen.add(filePath);
      let stat = null;
      try {
        stat = fs.statSync(filePath);
      } catch (error) {
        continue;
      }
      if (!stat.isFile()) continue;
      const file = classifyCurrentFile(filePath);
      if (file) files.push(file);
    }
  }
  return files;
}

function currentSignature(files) {
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

function newestCurrentFile(files) {
  return files
    .slice()
    .sort((a, b) => {
      const byTime = a.timestamp.localeCompare(b.timestamp);
      if (byTime) return byTime;
      const astat = fs.statSync(a.path);
      const bstat = fs.statSync(b.path);
      return astat.mtimeMs - bstat.mtimeMs;
    })
    .pop() || null;
}

function parseNumber(value) {
  const n = Number(String(value || "").trim());
  return Number.isFinite(n) ? n : null;
}

function parseValid(value) {
  return String(value || "").trim() === "1";
}

function formatAmp(value) {
  if (!Number.isFinite(value)) return "";
  const rounded = Math.round(Math.abs(value) * 10) / 10;
  return `${rounded.toFixed(1).replace(/\.0$/, "")}A`;
}

function phase(parts, valueIndex, validIndex) {
  const value = parseNumber(parts[valueIndex]);
  const valid = parseValid(parts[validIndex]);
  return { value, valid };
}

function currentRowFromLine(line, file) {
  if (!line || line.charCodeAt(0) !== 35) return null;
  const parts = line.split("\t");
  if (parts.length < 18) return null;
  const rawId = cleanStatusId(parts[3]);
  if (!rawId) return null;

  const phases = {
    ia: phase(parts, 10, 11),
    ib: phase(parts, 12, 13),
    ic: phase(parts, 14, 15),
    i0: phase(parts, 16, 17)
  };
  const validPhaseValues = [phases.ia, phases.ib, phases.ic]
    .filter((item) => item.valid && Number.isFinite(item.value))
    .map((item) => Math.abs(item.value));
  if (!validPhaseValues.length) return null;

  const amp = Math.max(...validPhaseValues);
  return {
    rawId,
    amp,
    display: formatAmp(amp),
    ia: phases.ia.value,
    ib: phases.ib.value,
    ic: phases.ic.value,
    i0: phases.i0.value,
    valid: {
      ia: phases.ia.valid,
      ib: phases.ib.valid,
      ic: phases.ic.valid,
      i0: phases.i0.valid
    },
    fileName: file.name,
    timestamp: file.timestamp
  };
}

function readCurrentRows(file) {
  const byRawId = new Map();
  const buffer = fs.readFileSync(file.path);
  let rows = 0;
  let start = 0;
  for (let i = 0; i <= buffer.length; i += 1) {
    if (i < buffer.length && buffer[i] !== 10) continue;
    let end = i;
    if (end > start && buffer[end - 1] === 13) end -= 1;
    if (buffer[start] === 35) {
      const line = buffer.toString("latin1", start, end);
      const row = currentRowFromLine(line, file);
      if (row) {
        rows += 1;
        byRawId.set(row.rawId, row);
      }
    }
    start = i + 1;
  }
  return { byRawId, rows };
}

function emptyCurrent(currentDirs, error = "") {
  return {
    currentDirs: Array.isArray(currentDirs) ? currentDirs : [currentDirs || ""],
    error,
    byRawId: new Map(),
    rows: 0,
    files: [],
    summary: {
      currentDirs: Array.isArray(currentDirs) ? currentDirs : [currentDirs || ""],
      error,
      version: "",
      currentFiles: [],
      currentRows: 0,
      currentCount: 0
    }
  };
}

function loadSwitchCurrent(currentDirs) {
  const files = collectCurrentFiles(currentDirs);
  const signature = currentSignature(files);
  if (cache && cache.signature === signature) return cache.data;
  if (!files.length) {
    const data = emptyCurrent(currentDirs, "current data file not found");
    cache = { signature, data };
    return data;
  }

  const selected = newestCurrentFile(files);
  const parsed = readCurrentRows(selected);
  const version = signatureVersion(signature);
  const fileSummary = files.map((file) => ({
    name: file.name,
    timestamp: file.timestamp,
    selected: file.path === selected.path
  }));
  const data = {
    currentDirs: Array.isArray(currentDirs) ? currentDirs : [currentDirs || ""],
    error: "",
    byRawId: parsed.byRawId,
    rows: parsed.rows,
    files: fileSummary,
    summary: {
      currentDirs: Array.isArray(currentDirs) ? currentDirs : [currentDirs || ""],
      error: "",
      version,
      currentFiles: fileSummary,
      currentRows: parsed.rows,
      currentCount: parsed.byRawId.size
    }
  };
  cache = { signature, data };
  return data;
}

function getCurrentForEquipment(item, switchCurrent) {
  if (!item || !switchCurrent || !switchCurrent.byRawId) return null;
  const candidates = [
    cleanStatusId(item.id),
    cleanStatusId(item.mrid)
  ].filter(Boolean);
  const seen = new Set();
  for (const id of candidates) {
    if (seen.has(id)) continue;
    seen.add(id);
    const hit = switchCurrent.byRawId.get(id);
    if (hit) return hit;
  }
  return null;
}

function serializableCurrentSummary(switchCurrent) {
  return switchCurrent && switchCurrent.summary ? switchCurrent.summary : emptyCurrent("").summary;
}

module.exports = {
  getCurrentForEquipment,
  loadSwitchCurrent,
  serializableCurrentSummary
};
