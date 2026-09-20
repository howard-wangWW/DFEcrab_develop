//电流目录-按电流大小排序全网开关，支持 Top-N 查询
// 用途:
//   - 电流最大的20个开关
//   - 超过200A的所有开关
//   - 某变电站有哪些带电流测点的开关
const fs = require("fs");
const path = require("path");
const { DatabaseSync } = require("node:sqlite");

function openCurrentCatalog(rootDir) {
  const dataDir = path.join(rootDir, "\u7528\u6237\u5217\u8868\u7d22\u5f15");
  fs.mkdirSync(dataDir, { recursive: true });
  const dbPath = path.join(dataDir, "switch-current-catalog.sqlite");
  const db = new DatabaseSync(dbPath);
  db.exec(`
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS switch_currents (
      raw_id TEXT PRIMARY KEY,
      switch_id TEXT,
      mrid TEXT,
      tag TEXT,
      switch_name TEXT,
      dispatch_number TEXT,
      cabinet TEXT,
      station TEXT,
      feeder_id TEXT,
      feeder_name TEXT,
      file TEXT,
      matched_xml INTEGER NOT NULL,
      current_amp REAL NOT NULL,
      current_display TEXT,
      ia REAL,
      ib REAL,
      ic REAL,
      i0 REAL,
      current_file TEXT,
      current_timestamp TEXT,
      feeder_ids TEXT,
      feeder_names TEXT,
      station_names TEXT,
      files TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_switch_currents_amp
      ON switch_currents(current_amp DESC);
    CREATE INDEX IF NOT EXISTS idx_switch_currents_station
      ON switch_currents(station);
    CREATE INDEX IF NOT EXISTS idx_switch_currents_feeder
      ON switch_currents(feeder_id);
    CREATE INDEX IF NOT EXISTS idx_switch_currents_matched
      ON switch_currents(matched_xml, current_amp DESC);
  `);
  return { db, dbPath };
}

function currentCatalogStatus(rootDir) {
  const { db, dbPath } = openCurrentCatalog(rootDir);
  const metadata = Object.fromEntries(
    db.prepare("SELECT key, value FROM metadata").all().map((item) => {
      let value = item.value;
      try { value = JSON.parse(value); } catch (error) { /* keep text */ }
      return [item.key, value];
    })
  );
  const row = db.prepare(`
    SELECT COUNT(*) AS count,
           SUM(CASE WHEN matched_xml = 1 THEN 1 ELSE 0 END) AS matched,
           MAX(current_amp) AS maxAmp
    FROM switch_currents
  `).get();
  return {
    dbPath,
    built: !!metadata.builtAt,
    currentCount: Number(row.count || 0),
    matchedXmlCount: Number(row.matched || 0),
    unmatchedXmlCount: Number(row.count || 0) - Number(row.matched || 0),
    maxAmp: Number(row.maxAmp || 0),
    ...metadata
  };
}

function replaceCurrentCatalog(rootDir, rows, metadata = {}) {
  const { db, dbPath } = openCurrentCatalog(rootDir);
  const insert = db.prepare(`
    INSERT INTO switch_currents(
      raw_id, switch_id, mrid, tag, switch_name, dispatch_number,
      cabinet, station, feeder_id, feeder_name, file, matched_xml,
      current_amp, current_display, ia, ib, ic, i0,
      current_file, current_timestamp, feeder_ids, feeder_names,
      station_names, files
    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  const setMeta = db.prepare(`
    INSERT INTO metadata(key, value) VALUES(?, ?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value
  `);
  db.exec("BEGIN IMMEDIATE");
  try {
    db.exec("DELETE FROM switch_currents; DELETE FROM metadata;");
    for (const row of rows) {
      insert.run(
        row.rawId,
        row.switchId || "",
        row.mrid || "",
        row.tag || "",
        row.switchName || "",
        row.dispatchNumber || "",
        row.cabinet || "",
        row.station || "",
        row.feederId || "",
        row.feederName || "",
        row.file || "",
        row.matchedXml ? 1 : 0,
        Number(row.currentAmp || 0),
        row.currentDisplay || "",
        Number.isFinite(row.ia) ? row.ia : null,
        Number.isFinite(row.ib) ? row.ib : null,
        Number.isFinite(row.ic) ? row.ic : null,
        Number.isFinite(row.i0) ? row.i0 : null,
        row.currentFile || "",
        row.currentTimestamp || "",
        JSON.stringify(row.feederIds || []),
        JSON.stringify(row.feederNames || []),
        JSON.stringify(row.stationNames || []),
        JSON.stringify(row.files || [])
      );
    }
    for (const [key, value] of Object.entries(metadata)) {
      setMeta.run(key, JSON.stringify(value));
    }
    db.exec("COMMIT");
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
  return { dbPath, status: currentCatalogStatus(rootDir) };
}

function parseArray(value) {
  try {
    const parsed = JSON.parse(value || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function numberOrNull(value) {
  return value === null || value === undefined ? null : Number(value);
}

function queryCurrentCatalog(rootDir, options = {}) {
  const { db } = openCurrentCatalog(rootDir);
  const limit = Math.max(1, Math.min(Math.floor(Number(options.limit) || 100), 1000));
  const filters = [];
  const params = [];
  if (!options.includeUnmatched) filters.push("matched_xml = 1");
  const minAmp = Number(options.minAmp);
  if (Number.isFinite(minAmp)) {
    filters.push("current_amp >= ?");
    params.push(minAmp);
  }
  const maxAmp = Number(options.maxAmp);
  if (Number.isFinite(maxAmp)) {
    filters.push("current_amp <= ?");
    params.push(maxAmp);
  }
  for (const [value, columns] of [
    [options.station, ["station", "station_names"]],
    [options.feeder, ["feeder_id", "feeder_name", "feeder_ids", "feeder_names"]],
    [options.cabinet, ["cabinet"]],
    [options.query, ["raw_id", "switch_id", "mrid", "switch_name", "dispatch_number", "cabinet"]]
  ]) {
    const text = String(value || "").trim();
    if (!text) continue;
    filters.push(`(${columns.map((column) => `${column} LIKE ?`).join(" OR ")})`);
    params.push(...columns.map(() => `%${text}%`));
  }
  const where = filters.length ? `WHERE ${filters.join(" AND ")}` : "";
  const direction = String(options.sort || "desc").toLowerCase() === "asc" ? "ASC" : "DESC";
  const count = Number(db.prepare(`SELECT COUNT(*) AS count FROM switch_currents ${where}`).get(...params).count || 0);
  const rows = db.prepare(`
    SELECT raw_id AS rawId, switch_id AS switchId, mrid, tag,
           switch_name AS switchName, dispatch_number AS dispatchNumber,
           cabinet, station, feeder_id AS feederId, feeder_name AS feederName,
           file, matched_xml AS matchedXml,
           current_amp AS currentAmp, current_display AS currentDisplay,
           ia, ib, ic, i0, current_file AS currentFile,
           "current_timestamp" AS currentTimestamp,
           feeder_ids AS feederIds, feeder_names AS feederNames,
           station_names AS stationNames, files
    FROM switch_currents
    ${where}
    ORDER BY current_amp ${direction}, raw_id
    LIMIT ?
  `).all(...params, limit).map((row) => ({
    ...row,
    matchedXml: !!row.matchedXml,
    currentAmp: Number(row.currentAmp || 0),
    ia: numberOrNull(row.ia),
    ib: numberOrNull(row.ib),
    ic: numberOrNull(row.ic),
    i0: numberOrNull(row.i0),
    feederIds: parseArray(row.feederIds),
    feederNames: parseArray(row.feederNames),
    stationNames: parseArray(row.stationNames),
    files: parseArray(row.files)
  }));
  return { count, rows, truncated: count > rows.length, sort: direction.toLowerCase() };
}

module.exports = {
  currentCatalogStatus,
  queryCurrentCatalog,
  replaceCurrentCatalog
};
