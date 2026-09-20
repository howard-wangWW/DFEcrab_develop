//全网负荷分析-统计每个开关下带了多少用户
// 分析维度:
//   - 全网所有开关的用户数统计
//   - 断开开关后必然失电的变压器
//   - ZY (专变) 和 DY (公变) 用户分别统计
//   - 结果存在 SQLite 中，支持快速查询
const fs = require("fs");
const path = require("path");
const { DatabaseSync } = require("node:sqlite");
const { getStatusForEquipment } = require("./switchStatus");
const { getCurrentForEquipment } = require("./switchCurrent");

const SUPER_ROOT = "__grid_source_root__";
const SWITCH_TAGS = new Set(["Breaker", "LoadBreakSwitch", "Disconnector", "Fuse"]);

function openAnalyticsDatabase(rootDir) {
  const dataDir = path.join(rootDir, "\u7528\u6237\u5217\u8868\u7d22\u5f15");
  fs.mkdirSync(dataDir, { recursive: true });
  const dbPath = path.join(dataDir, "grid-analytics.sqlite");
  const db = new DatabaseSync(dbPath);
  db.exec(`
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE IF NOT EXISTS metadata (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS switch_loads (
      switch_id TEXT PRIMARY KEY,
      switch_name TEXT,
      cabinet TEXT,
      station TEXT,
      feeder_id TEXT,
      feeder_name TEXT,
      file TEXT,
      closed INTEGER NOT NULL,
      current_amp REAL,
      current_display TEXT,
      transformer_count INTEGER NOT NULL,
      users_total INTEGER NOT NULL,
      users_zy INTEGER NOT NULL,
      users_dy INTEGER NOT NULL,
      source_feeders TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_switch_loads_users
      ON switch_loads(users_total DESC);
    CREATE INDEX IF NOT EXISTS idx_switch_loads_feeder
      ON switch_loads(feeder_id);
  `);
  return { db, dbPath };
}

function analyticsStatus(rootDir) {
  const { db, dbPath } = openAnalyticsDatabase(rootDir);
  const metadata = Object.fromEntries(
    db.prepare("SELECT key, value FROM metadata").all().map((item) => {
      let value = item.value;
      try { value = JSON.parse(value); } catch (error) { /* keep text */ }
      return [item.key, value];
    })
  );
  const row = db.prepare("SELECT COUNT(*) AS count, MAX(users_total) AS maxUsers FROM switch_loads").get();
  return {
    dbPath,
    built: !!metadata.builtAt,
    rowCount: Number(row.count || 0),
    maxUsers: Number(row.maxUsers || 0),
    ...metadata
  };
}

function replaceSwitchLoads(rootDir, rows, metadata = {}) {
  const { db, dbPath } = openAnalyticsDatabase(rootDir);
  const insert = db.prepare(`
    INSERT INTO switch_loads(
      switch_id, switch_name, cabinet, station, feeder_id, feeder_name, file,
      closed, current_amp, current_display, transformer_count,
      users_total, users_zy, users_dy, source_feeders
    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(switch_id) DO UPDATE SET
      switch_name=excluded.switch_name,
      cabinet=excluded.cabinet,
      station=excluded.station,
      feeder_id=excluded.feeder_id,
      feeder_name=excluded.feeder_name,
      file=excluded.file,
      closed=excluded.closed,
      current_amp=excluded.current_amp,
      current_display=excluded.current_display,
      transformer_count=excluded.transformer_count,
      users_total=excluded.users_total,
      users_zy=excluded.users_zy,
      users_dy=excluded.users_dy,
      source_feeders=excluded.source_feeders
    WHERE excluded.users_total > switch_loads.users_total
  `);
  const setMeta = db.prepare(`
    INSERT INTO metadata(key, value) VALUES(?, ?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value
  `);
  db.exec("BEGIN IMMEDIATE");
  try {
    db.exec("DELETE FROM switch_loads; DELETE FROM metadata;");
    for (const row of rows) {
      insert.run(
        row.switchId,
        row.switchName || "",
        row.cabinet || "",
        row.station || "",
        row.feederId || "",
        row.feederName || "",
        row.file || "",
        row.closed ? 1 : 0,
        Number.isFinite(row.currentAmp) ? row.currentAmp : null,
        row.currentDisplay || "",
        Number(row.transformerCount || 0),
        Number(row.usersTotal || 0),
        Number(row.usersZY || 0),
        Number(row.usersDY || 0),
        JSON.stringify(row.sourceFeeders || [])
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
  return { dbPath, rows: rows.length, status: analyticsStatus(rootDir) };
}

function querySwitchLoads(rootDir, options = {}) {
  const { db } = openAnalyticsDatabase(rootDir);
  const minUsers = Math.max(0, Math.floor(Number(options.minUsers) || 2000));
  const limit = Math.max(1, Math.min(Math.floor(Number(options.limit) || 100), 1000));
  const filters = ["users_total >= ?"];
  const params = [minUsers];
  for (const [value, columns] of [
    [options.station, ["station"]],
    [options.feeder, ["feeder_id", "feeder_name"]],
    [options.query, ["switch_id", "switch_name", "cabinet"]]
  ]) {
    const text = String(value || "").trim();
    if (!text) continue;
    filters.push(`(${columns.map((column) => `${column} LIKE ?`).join(" OR ")})`);
    params.push(...columns.map(() => `%${text}%`));
  }
  const where = filters.join(" AND ");
  const count = Number(db.prepare(`SELECT COUNT(*) AS count FROM switch_loads WHERE ${where}`).get(...params).count || 0);
  const rows = db.prepare(`
    SELECT switch_id AS switchId, switch_name AS switchName, cabinet, station,
           feeder_id AS feederId, feeder_name AS feederName, file,
           closed, current_amp AS currentAmp, current_display AS currentDisplay,
           transformer_count AS transformerCount,
           users_total AS usersTotal, users_zy AS usersZY, users_dy AS usersDY,
           source_feeders AS sourceFeeders
    FROM switch_loads
    WHERE ${where}
    ORDER BY users_total DESC, switch_id
    LIMIT ?
  `).all(...params, limit).map((row) => ({
    ...row,
    closed: !!row.closed,
    currentAmp: row.currentAmp === null ? null : Number(row.currentAmp),
    transformerCount: Number(row.transformerCount || 0),
    usersTotal: Number(row.usersTotal || 0),
    usersZY: Number(row.usersZY || 0),
    usersDY: Number(row.usersDY || 0),
    sourceFeeders: JSON.parse(row.sourceFeeders || "[]")
  }));
  return { count, rows, truncated: count > rows.length, minUsers };
}

function addEdge(adjacency, left, right) {
  if (!adjacency.has(left)) adjacency.set(left, new Set());
  if (!adjacency.has(right)) adjacency.set(right, new Set());
  adjacency.get(left).add(right);
  adjacency.get(right).add(left);
}

function conductiveGraph(graph, switchStates) {
  const adjacency = new Map([[SUPER_ROOT, new Set()]]);
  const isConductive = (item) => {
    if (!item || item.tag === "GroundDisconnector") return false;
    if (SWITCH_TAGS.has(item.tag)) return switchStates[item.id] !== false;
    return true;
  };
  for (const item of graph.equipment || []) {
    if (!isConductive(item)) continue;
    const eqNode = `eq:${item.id}`;
    if (!adjacency.has(eqNode)) adjacency.set(eqNode, new Set());
    for (const cn of graph.eqToCn[item.id] || []) addEdge(adjacency, eqNode, `cn:${cn}`);
  }
  const sourceIds = (
    graph.sources && graph.sources.length
      ? graph.sources.map((source) => source.id)
      : (graph.sourceBreakers || [graph.sourceBreaker]).filter(Boolean)
  );
  for (const sourceId of sourceIds) {
    const item = graph.equipmentById[sourceId];
    if (!isConductive(item)) continue;
    addEdge(adjacency, SUPER_ROOT, `eq:${sourceId}`);
  }
  return adjacency;
}

function immediateDominators(adjacency, root = SUPER_ROOT) {
  const visited = new Set();
  const postorder = [];
  const stack = [{ node: root, entered: false }];
  while (stack.length) {
    const frame = stack.pop();
    if (frame.entered) {
      postorder.push(frame.node);
      continue;
    }
    if (visited.has(frame.node)) continue;
    visited.add(frame.node);
    stack.push({ node: frame.node, entered: true });
    for (const next of adjacency.get(frame.node) || []) {
      if (!visited.has(next)) stack.push({ node: next, entered: false });
    }
  }
  const rpo = postorder.reverse();
  const order = new Map(rpo.map((node, index) => [node, index]));
  const idom = new Map([[root, root]]);
  const intersect = (leftStart, rightStart) => {
    let left = leftStart;
    let right = rightStart;
    while (left !== right) {
      while (order.get(left) > order.get(right)) left = idom.get(left);
      while (order.get(right) > order.get(left)) right = idom.get(right);
    }
    return left;
  };
  let changed = true;
  while (changed) {
    changed = false;
    for (const node of rpo.slice(1)) {
      const predecessors = [...(adjacency.get(node) || [])].filter((item) => idom.has(item));
      if (!predecessors.length) continue;
      let nextIdom = predecessors[0];
      for (const predecessor of predecessors.slice(1)) nextIdom = intersect(predecessor, nextIdom);
      if (idom.get(node) !== nextIdom) {
        idom.set(node, nextIdom);
        changed = true;
      }
    }
  }
  return { idom, rpo };
}

function addCounts(target, source) {
  target.total += Number(source.total || 0);
  target.ZY += Number(source.ZY || 0);
  target.DY += Number(source.DY || 0);
  target.transformers += Number(source.transformers || 0);
}

function computeSwitchLoads(graph, switchStates, transformerUserCounts) {
  const adjacency = conductiveGraph(graph, switchStates);
  const { idom, rpo } = immediateDominators(adjacency);
  const totals = new Map(rpo.map((node) => [node, { total: 0, ZY: 0, DY: 0, transformers: 0 }]));
  for (const transformer of graph.transformers || []) {
    const node = `eq:${transformer.id}`;
    if (!totals.has(node)) continue;
    const counts = transformerUserCounts[transformer.id];
    if (!counts) continue;
    totals.set(node, {
      total: Number(counts.total || 0),
      ZY: Number(counts.ZY || 0),
      DY: Number(counts.DY || 0),
      transformers: Number(counts.total || 0) > 0 ? 1 : 0
    });
  }
  for (let index = rpo.length - 1; index > 0; index -= 1) {
    const node = rpo[index];
    const parent = idom.get(node);
    if (parent && parent !== node && totals.has(parent)) addCounts(totals.get(parent), totals.get(node));
  }
  const result = {};
  for (const item of graph.switches || []) {
    if (item.tag === "GroundDisconnector" || switchStates[item.id] === false) continue;
    const counts = totals.get(`eq:${item.id}`);
    if (!counts) continue;
    result[item.id] = counts;
  }
  return result;
}

function buildAnalysisGraph(model, switchStatus, switchCurrent) {
  const equipmentById = {};
  for (const [id, item] of model.equipment) {
    if (item.tag === "TransformerWinding") continue;
    equipmentById[id] = { ...item, mrid: item.mrid || id };
  }
  const eqToCnSets = new Map();
  const cnToEqSets = new Map();
  for (const terminal of model.terminals || []) {
    const equipmentId = model.windingToTransformer.get(terminal.equipment) || terminal.equipment;
    if (!equipmentById[equipmentId] || !terminal.connectivityNode) continue;
    if (!eqToCnSets.has(equipmentId)) eqToCnSets.set(equipmentId, new Set());
    if (!cnToEqSets.has(terminal.connectivityNode)) cnToEqSets.set(terminal.connectivityNode, new Set());
    eqToCnSets.get(equipmentId).add(terminal.connectivityNode);
    cnToEqSets.get(terminal.connectivityNode).add(equipmentId);
  }
  const switches = [];
  const transformers = [];
  const initialSwitchState = {};
  const switchCurrentById = {};
  const cabinetByEquipment = {};
  for (const item of Object.values(equipmentById)) {
    const cabinet = model.substations.get(item.container);
    if (cabinet && cabinet.name) cabinetByEquipment[item.id] = cabinet.name;
    if (item.tag === "PowerTransformer") transformers.push(item);
    if (!SWITCH_TAGS.has(item.tag) && item.tag !== "GroundDisconnector") continue;
    switches.push(item);
    const status = getStatusForEquipment(item, switchStatus);
    initialSwitchState[item.id] = item.tag === "GroundDisconnector" ? false : status ? status.closed : true;
    const current = getCurrentForEquipment(item, switchCurrent);
    if (current) {
      switchCurrentById[item.id] = {
        amp: current.amp,
        display: current.display,
        ia: current.ia,
        ib: current.ib,
        ic: current.ic,
        i0: current.i0,
        fileName: current.fileName,
        timestamp: current.timestamp
      };
    }
  }
  const circuits = model.circuits || [];
  const sources = [];
  const seenSources = new Set();
  for (const circuit of circuits) {
    if (!circuit.sourceBreaker || seenSources.has(circuit.sourceBreaker) || !equipmentById[circuit.sourceBreaker]) continue;
    seenSources.add(circuit.sourceBreaker);
    const station = model.substations.get(circuit.sourceSubst);
    sources.push({
      id: circuit.sourceBreaker,
      owner: circuit.sourceBreaker,
      label: [station && station.name, circuit.name || circuit.dispatchNumber].filter(Boolean).join(" "),
      circuitId: circuit.id,
      feederId: circuit.id,
      feederMrid: circuit.mrid || ""
    });
  }
  return {
    equipment: Object.values(equipmentById),
    equipmentById,
    eqToCn: Object.fromEntries([...eqToCnSets].map(([id, values]) => [id, [...values]])),
    cnToEq: Object.fromEntries([...cnToEqSets].map(([id, values]) => [id, [...values]])),
    switches,
    transformers,
    sources,
    sourceBreakers: sources.map((source) => source.id),
    sourceBreaker: sources[0] ? sources[0].id : "",
    initialSwitchState,
    switchCurrentById,
    cabinetByEquipment
  };
}

module.exports = {
  analyticsStatus,
  buildAnalysisGraph,
  computeSwitchLoads,
  querySwitchLoads,
  replaceSwitchLoads
};
