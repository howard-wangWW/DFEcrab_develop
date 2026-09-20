//用户数据存储-管理中压/低压用户与变压器的对应关系
//管理中压/低压用户与变压器的对应关系
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { StringDecoder } = require("string_decoder");
const { DatabaseSync } = require("node:sqlite");

const REQUIRED_COLUMNS = [
  "PW_TRANS_ID",//变压器ID
  "PW_TRANS_NAME",
  "FEEDER_ID",
  "FEEDER_NAME",
  "COMSUMER_ID",//用户ID
  "CONSUMER_NAME",//用户名
  "CONSUMER_TYPE",//用户类型: ZY/DY
  "CONSUMER_ADDRESS",
  "VOLTAGE_LEVEL"//电压等级
];

class CsvRowParser {
  constructor(onRow) {
    this.onRow = onRow;
    this.row = [];
    this.field = "";
    this.inQuotes = false;
    this.quotePending = false;
  }

  push(text) {
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (this.inQuotes) {
        if (this.quotePending) {
          if (char === '"') {
            this.field += '"';
            this.quotePending = false;
            continue;
          }
          this.inQuotes = false;
          this.quotePending = false;
        } else if (char === '"') {
          this.quotePending = true;
          continue;
        } else {
          this.field += char;
          continue;
        }
      }

      if (char === '"' && this.field.length === 0) {
        this.inQuotes = true;
      } else if (char === ",") {
        this.row.push(this.field);
        this.field = "";
      } else if (char === "\n") {
        this.row.push(this.field.endsWith("\r") ? this.field.slice(0, -1) : this.field);
        this.field = "";
        this.emitRow();
      } else if (char !== "\r") {
        this.field += char;
      }
    }
  }

  finish() {
    if (this.quotePending) {
      this.inQuotes = false;
      this.quotePending = false;
    }
    if (this.field.length || this.row.length) {
      this.row.push(this.field);
      this.field = "";
      this.emitRow();
    }
  }

  emitRow() {
    const row = this.row;
    this.row = [];
    this.onRow(row);
  }
}

function normalizeType(type) {
  const value = String(type || "").trim().toUpperCase();
  if (value !== "ZY" && value !== "DY") throw new Error("用户列表类型必须是 ZY 或 DY");
  return value;
}

function safeFileName(name, type) {
  const base = path.basename(String(name || `${type}.csv`)).replace(/[<>:"/\\|?*\x00-\x1f]/g, "_");
  return base || `${type}.csv`;
}

function openDatabase(dbPath) {
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec(`
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    PRAGMA temp_store=MEMORY;
    PRAGMA cache_size=-131072;
    CREATE TABLE IF NOT EXISTS datasets (
      type TEXT PRIMARY KEY,
      dataset_id TEXT NOT NULL,
      file_name TEXT NOT NULL,
      total_rows INTEGER NOT NULL,
      indexed_rows INTEGER NOT NULL,
      imported_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS users (
      dataset_id TEXT NOT NULL,
      type TEXT NOT NULL,
      transformer_id TEXT NOT NULL,
      transformer_name TEXT,
      feeder_id TEXT,
      feeder_name TEXT,
      consumer_id TEXT,
      consumer_name TEXT,
      consumer_type TEXT,
      consumer_address TEXT,
      voltage_level TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_users_dataset_transformer
      ON users(dataset_id, transformer_id);
    CREATE INDEX IF NOT EXISTS idx_users_dataset_feeder
      ON users(dataset_id, feeder_id);
  `);
  return db;
}

function createUserStore(rootDir) {
  const dataDir = path.join(rootDir, "用户列表索引");
  const dbPath = path.join(dataDir, "users.sqlite");
  const db = openDatabase(dbPath);

  function status() {
    const datasets = db.prepare(`
      SELECT type, dataset_id AS datasetId, file_name AS fileName,
             total_rows AS totalRows, indexed_rows AS indexedRows,
             imported_at AS importedAt
      FROM datasets
      ORDER BY type
    `).all();
    return {
      dbPath,
      datasets,
      totalUsers: datasets.reduce((sum, item) => sum + Number(item.indexedRows || 0), 0)
    };
  }

  async function importCsv(readable, options = {}) {
    const type = normalizeType(options.type);
    const fileName = safeFileName(options.fileName, type);
    const datasetId = `${type}-${Date.now()}-${crypto.randomBytes(4).toString("hex")}`;
    const decoder = new StringDecoder("utf8");
    let header = null;
    let columnIndex = null;
    let totalRows = 0;
    let indexedRows = 0;
    let transactionOpen = false;
    const insert = db.prepare(`
      INSERT INTO users (
        dataset_id, type, transformer_id, transformer_name,
        feeder_id, feeder_name, consumer_id, consumer_name,
        consumer_type, consumer_address, voltage_level
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const begin = () => {
      if (!transactionOpen) {
        db.exec("BEGIN IMMEDIATE");
        transactionOpen = true;
      }
    };
    const commit = () => {
      if (transactionOpen) {
        db.exec("COMMIT");
        transactionOpen = false;
      }
    };
    const rollback = () => {
      if (transactionOpen) {
        db.exec("ROLLBACK");
        transactionOpen = false;
      }
    };

    const parser = new CsvRowParser((row) => {
      if (!header) {
        header = row.map((value, index) => (index === 0 ? value.replace(/^\uFEFF/, "") : value).trim());
        columnIndex = Object.fromEntries(header.map((name, index) => [name, index]));
        const missing = REQUIRED_COLUMNS.filter((name) => columnIndex[name] === undefined);
        if (missing.length) throw new Error(`用户CSV缺少字段：${missing.join(", ")}`);
        begin();
        return;
      }
      if (row.length === 1 && !row[0]) return;
      totalRows += 1;
      const transformerId = String(row[columnIndex.PW_TRANS_ID] || "").trim();
      if (!transformerId) return;
      insert.run(
        datasetId,
        type,
        transformerId,
        String(row[columnIndex.PW_TRANS_NAME] || "").trim(),
        String(row[columnIndex.FEEDER_ID] || "").trim(),
        String(row[columnIndex.FEEDER_NAME] || "").trim(),
        String(row[columnIndex.COMSUMER_ID] || "").trim(),
        String(row[columnIndex.CONSUMER_NAME] || "").trim(),
        String(row[columnIndex.CONSUMER_TYPE] || "").trim(),
        String(row[columnIndex.CONSUMER_ADDRESS] || "").trim(),
        String(row[columnIndex.VOLTAGE_LEVEL] || "").trim()
      );
      indexedRows += 1;
      if (indexedRows % 20000 === 0) {
        commit();
        begin();
      }
    });

    try {
      for await (const chunk of readable) parser.push(decoder.write(chunk));
      parser.push(decoder.end());
      parser.finish();
      if (!header) throw new Error("用户CSV为空");
      commit();

      const old = db.prepare("SELECT dataset_id AS datasetId FROM datasets WHERE type = ?").get(type);
      db.exec("BEGIN IMMEDIATE");
      transactionOpen = true;
      db.prepare(`
        INSERT INTO datasets(type, dataset_id, file_name, total_rows, indexed_rows, imported_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(type) DO UPDATE SET
          dataset_id=excluded.dataset_id,
          file_name=excluded.file_name,
          total_rows=excluded.total_rows,
          indexed_rows=excluded.indexed_rows,
          imported_at=excluded.imported_at
      `).run(type, datasetId, fileName, totalRows, indexedRows, new Date().toISOString());
      if (old && old.datasetId && old.datasetId !== datasetId) {
        db.prepare("DELETE FROM users WHERE dataset_id = ?").run(old.datasetId);
      }
      commit();
      db.exec("PRAGMA wal_checkpoint(PASSIVE)");
      return { type, fileName, totalRows, indexedRows, datasetId, status: status() };
    } catch (error) {
      rollback();
      try {
        db.prepare("DELETE FROM users WHERE dataset_id = ?").run(datasetId);
      } catch (cleanupError) {
        console.warn("user import cleanup failed", cleanupError);
      }
      throw error;
    }
  }

  function activeDatasets() {
    return db.prepare("SELECT type, dataset_id AS datasetId FROM datasets").all();
  }

  function normalizeTransformerIds(ids) {
    return [...new Set((ids || []).map((id) => String(id || "").trim()).filter(Boolean))].slice(0, 500);
  }

  function buildQuery(ids, selectSql, suffix = "") {
    const transformers = normalizeTransformerIds(ids);
    const datasets = activeDatasets();
    if (!transformers.length || !datasets.length) return null;
    const datasetWhere = datasets.map(() => "(u.type = ? AND u.dataset_id = ?)").join(" OR ");
    const transformerWhere = transformers.map(() => "?").join(",");
    return {
      sql: `${selectSql} WHERE (${datasetWhere}) AND u.transformer_id IN (${transformerWhere}) ${suffix}`,
      params: datasets.flatMap((item) => [item.type, item.datasetId]).concat(transformers)
    };
  }

  function queryUsers(transformerIds, limit = 1000) {
    const safeLimit = Math.max(1, Math.min(Number(limit) || 1000, 5000));
    const countQuery = buildQuery(
      transformerIds,
      "SELECT u.type, COUNT(*) AS count FROM users u",
      "GROUP BY u.type"
    );
    if (!countQuery) return { total: 0, counts: { ZY: 0, DY: 0 }, users: [], truncated: false, status: status() };
    const grouped = db.prepare(countQuery.sql).all(...countQuery.params);
    const counts = { ZY: 0, DY: 0 };
    for (const item of grouped) counts[item.type] = Number(item.count || 0);
    const total = counts.ZY + counts.DY;
    const listQuery = buildQuery(
      transformerIds,
      `SELECT u.type, u.transformer_id AS transformerId,
              u.transformer_name AS transformerName,
              u.feeder_id AS feederId, u.feeder_name AS feederName,
              u.consumer_id AS consumerId, u.consumer_name AS consumerName,
              u.consumer_type AS consumerType,
              u.consumer_address AS consumerAddress,
              u.voltage_level AS voltageLevel
       FROM users u`,
      "ORDER BY u.type DESC, u.transformer_name, u.consumer_name LIMIT ?"
    );
    const users = db.prepare(listQuery.sql).all(...listQuery.params, safeLimit);
    return { total, counts, users, truncated: total > users.length, status: status() };
  }

  function iterateUsers(transformerIds) {
    const query = buildQuery(
      transformerIds,
      `SELECT u.type, u.transformer_id AS transformerId,
              u.transformer_name AS transformerName,
              u.feeder_id AS feederId, u.feeder_name AS feederName,
              u.consumer_id AS consumerId, u.consumer_name AS consumerName,
              u.consumer_type AS consumerType,
              u.consumer_address AS consumerAddress,
              u.voltage_level AS voltageLevel
       FROM users u`,
      "ORDER BY u.type DESC, u.transformer_name, u.consumer_name"
    );
    if (!query) return [][Symbol.iterator]();
    return db.prepare(query.sql).iterate(...query.params);
  }

  function feederUserCounts(options = {}) {
    const datasets = activeDatasets();
    if (!datasets.length) return { totalFeeders: 0, rows: [], truncated: false };
    const minUsers = Math.max(0, Math.floor(Number(options.minUsers) || 0));
    const safeLimit = Math.max(1, Math.min(Math.floor(Number(options.limit) || 100), 20000));
    const query = String(options.query || "").trim();
    const datasetWhere = datasets.map(() => "(u.type = ? AND u.dataset_id = ?)").join(" OR ");
    const filterSql = query ? "AND (u.feeder_id LIKE ? OR u.feeder_name LIKE ?)" : "";
    const baseParams = datasets.flatMap((item) => [item.type, item.datasetId]);
    if (query) baseParams.push(`%${query}%`, `%${query}%`);
    const groupedSql = `
      FROM users u
      WHERE (${datasetWhere}) AND u.feeder_id <> '' ${filterSql}
      GROUP BY u.feeder_id
      HAVING COUNT(*) >= ?
    `;
    const totalFeeders = Number(
      db.prepare(`SELECT COUNT(*) AS count FROM (SELECT u.feeder_id ${groupedSql})`)
        .get(...baseParams, minUsers).count || 0
    );
    const rows = db.prepare(`
      SELECT u.feeder_id AS feederId,
             MAX(u.feeder_name) AS feederName,
             COUNT(*) AS total,
             SUM(CASE WHEN u.type = 'ZY' THEN 1 ELSE 0 END) AS ZY,
             SUM(CASE WHEN u.type = 'DY' THEN 1 ELSE 0 END) AS DY
      ${groupedSql}
      ORDER BY total DESC, feederId
      LIMIT ?
    `).all(...baseParams, minUsers, safeLimit).map((item) => ({
      feederId: item.feederId,
      feederName: item.feederName || "",
      total: Number(item.total || 0),
      counts: { ZY: Number(item.ZY || 0), DY: Number(item.DY || 0) }
    }));
    return { totalFeeders, rows, truncated: totalFeeders > rows.length };
  }

  function transformerUserCounts(transformerIds) {
    const ids = [...new Set((transformerIds || []).map((id) => String(id || "").trim()).filter(Boolean))];
    const result = {};
    for (let offset = 0; offset < ids.length; offset += 400) {
      const chunk = ids.slice(offset, offset + 400);
      const query = buildQuery(
        chunk,
        `SELECT u.transformer_id AS transformerId,
                COUNT(*) AS total,
                SUM(CASE WHEN u.type = 'ZY' THEN 1 ELSE 0 END) AS ZY,
                SUM(CASE WHEN u.type = 'DY' THEN 1 ELSE 0 END) AS DY
         FROM users u`,
        "GROUP BY u.transformer_id"
      );
      if (!query) continue;
      for (const item of db.prepare(query.sql).all(...query.params)) {
        result[item.transformerId] = {
          total: Number(item.total || 0),
          ZY: Number(item.ZY || 0),
          DY: Number(item.DY || 0)
        };
      }
    }
    return result;
  }

  return {
    dbPath,
    status,
    importCsv,
    queryUsers,
    iterateUsers,
    feederUserCounts,
    transformerUserCounts
  };
}

module.exports = {
  createUserStore
};
