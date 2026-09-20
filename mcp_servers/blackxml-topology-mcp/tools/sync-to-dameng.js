#!/usr/bin/env node
const path = require("path");
const dmdb = require("dmdb");
const { DatabaseSync } = require("node:sqlite");

const { DATA_ROOT } = require("../src/dataPaths");

const INDEX_DIR = path.join(DATA_ROOT, "\u7528\u6237\u5217\u8868\u7d22\u5f15");
const BATCH_SIZE = Math.max(100, Number(process.env.DMDB_BATCH_SIZE) || 2000);
const INCLUDE_USERS = process.argv.includes("--users") || process.env.DM_SYNC_USERS === "true";

const SOURCES = [
  {
    file: "switch-current-catalog.sqlite",
    tables: [
      ["metadata", "MCP_CURRENT_METADATA"],
      ["switch_currents", "MCP_SWITCH_CURRENTS"]
    ]
  },
  {
    file: "grid-analytics.sqlite",
    tables: [
      ["metadata", "MCP_ANALYTICS_METADATA"],
      ["switch_loads", "MCP_SWITCH_LOADS"]
    ]
  },
  ...(INCLUDE_USERS
    ? [{ file: "users.sqlite", tables: [["datasets", "MCP_USER_DATASETS"], ["users", "MCP_USERS"]] }]
    : [])
];

function quoted(value) {
  return `"${String(value).replace(/"/g, '""')}"`;
}

function dmType(sqliteType) {
  const type = String(sqliteType || "TEXT").toUpperCase();
  if (type.includes("INT")) return "BIGINT";
  if (type.includes("REAL") || type.includes("FLOA") || type.includes("DOUB")) return "DOUBLE";
  if (type.includes("BLOB")) return "BLOB";
  return "VARCHAR(32767)";
}

function qualified(table) {
  const schema = String(process.env.DMDB_SCHEMA || "").trim();
  return schema ? `${quoted(schema)}.${quoted(table)}` : quoted(table);
}

async function ensureTable(connection, target, columns) {
  const definition = columns.map((column) => `${quoted(column.name)} ${dmType(column.type)}`).join(", ");
  try {
    await connection.execute(`CREATE TABLE ${qualified(target)} (${definition})`);
  } catch (error) {
    const message = String(error.message || error);
    if (!/already|exist|已存在|对象名冲突/i.test(message)) throw error;
  }
}

async function flush(connection, sql, rows) {
  if (!rows.length) return 0;
  const result = await connection.executeMany(sql, rows, { batchErrors: false });
  const count = Number(result.rowsAffected) || rows.length;
  rows.length = 0;
  return count;
}

async function syncTable(connection, sqlite, source, target) {
  const columns = sqlite.prepare(`PRAGMA table_info(${quoted(source)})`).all();
  if (!columns.length) throw new Error(`SQLite table not found: ${source}`);
  await ensureTable(connection, target, columns);
  await connection.execute(`DELETE FROM ${qualified(target)}`);
  const names = columns.map((column) => column.name);
  const placeholders = names.map((_, index) => `:${index + 1}`).join(", ");
  const insert = `INSERT INTO ${qualified(target)} (${names.map(quoted).join(", ")}) VALUES (${placeholders})`;
  const select = sqlite.prepare(`SELECT ${names.map(quoted).join(", ")} FROM ${quoted(source)}`);
  const rows = [];
  let synced = 0;
  for (const row of select.iterate()) {
    rows.push(names.map((name) => row[name]));
    if (rows.length >= BATCH_SIZE) synced += await flush(connection, insert, rows);
  }
  synced += await flush(connection, insert, rows);
  return synced;
}

async function main() {
  const url = String(process.env.DMDB_URL || "").trim();
  if (!url) throw new Error("DMDB_URL is required, for example dm://USER:PASSWORD@host:5236");
  const connection = await dmdb.getConnection(url);
  const summary = [];
  try {
    for (const source of SOURCES) {
      const sqlite = new DatabaseSync(path.join(INDEX_DIR, source.file), { readOnly: true });
      try {
        for (const [table, target] of source.tables) {
          const rows = await syncTable(connection, sqlite, table, target);
          summary.push({ source: `${source.file}:${table}`, target, rows });
        }
      } finally {
        sqlite.close();
      }
    }
    await connection.commit();
    process.stdout.write(`${JSON.stringify({ ok: true, includeUsers: INCLUDE_USERS, tables: summary }, null, 2)}\n`);
  } catch (error) {
    await connection.rollback().catch(() => {});
    throw error;
  } finally {
    await connection.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || error}\n`);
  process.exitCode = 1;
});
