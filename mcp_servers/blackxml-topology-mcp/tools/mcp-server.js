#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const originalEmitWarning = process.emitWarning.bind(process);
process.emitWarning = (warning, ...args) => {
  const text = String((warning && warning.message) || warning || "");
  const type = typeof args[0] === "string" ? args[0] : (warning && warning.name) || "";
  if (type === "ExperimentalWarning" && /SQLite/i.test(text)) return;
  return originalEmitWarning(warning, ...args);
};

process.on("warning", (warning) => {
  if (warning && warning.name === "ExperimentalWarning" && /SQLite/i.test(warning.message || "")) return;
  console.error(warning);
});

const { createLineIndex, resolveIndexedFile } = require("../src/indexer");
const { buildTopologyFromFile } = require("../src/topology");
const { loadSwitchStatus } = require("../src/switchStatus");
const { loadSwitchCurrent } = require("../src/switchCurrent");
const { createUserStore } = require("../src/userStore");
const { buildTopologyText } = require("../src/textTopology");
const { computeOperationalState, diffOperationalState, SWITCH_TAGS } = require("../src/operational");
const { compareSwitchOrder, switchDisplayLabel } = require("../src/switchOrder");
const { analyticsStatus, querySwitchLoads } = require("../src/gridAnalytics");
const { currentCatalogStatus, queryCurrentCatalog } = require("../src/currentCatalog");
const {
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
} = require("../src/dataUpdater");
const {
  CODE_ROOT: ROOT,
  DATA_ROOT,
  XML_DIR,
  STATUS_DIR,
  CURRENT_DIRS,
  UPDATE_DIR,
  BACKUP_DIR
} = require("../src/dataPaths");

const DEFAULT_MAX_RELATED = 64;
const DEFAULT_MAX_NODES = 900;
const DEFAULT_LIMIT = 50;

let indexCache = null;
let selectionCache = undefined;

function selectionManifest() {
  if (selectionCache !== undefined) return selectionCache;
  try {
    selectionCache = JSON.parse(fs.readFileSync(path.join(ROOT, "selection.json"), "utf8"));
  } catch (error) {
    selectionCache = null;
  }
  return selectionCache;
}

function selectionScope() {
  const selection = selectionManifest();
  if (!selection) return { mode: "full", note: "全量图模数据集。" };
  return {
    mode: "lite",
    seedTopologyFileCount: Number(selection.seedTopologyFileCount || selection.feeders && selection.feeders.length || 0),
    topologyFileCount: Number(selection.topologyFileCount || selection.feeders && selection.feeders.length || 0),
    feederCount: Number(selection.feederCount || 0),
    completeSeedCount: Number(selection.completeSeedCount || 0),
    incompleteSeedCount: Number(selection.incompleteSeedCount || 0),
    generatedAt: selection.generatedAt || "",
    note: "本服务只包含selection.json列出的精选图模，总体统计仅代表轻量数据集。"
  };
}

function topologyReliability(line) {
  const selection = selectionManifest();
  if (!selection) return { complete: true, energizationReliable: true, note: "全量关联图模可用。" };
  const info = selection.topologyCompleteness && selection.topologyCompleteness[line && line.relativePath];
  if (!info || info.complete !== true) {
    return {
      complete: false,
      energizationReliable: false,
      componentFileCount: Number((info && info.componentFileCount) || 0),
      includedFileCount: Number((info && info.includedFileCount) || 1),
      missingFileCount: Number((info && info.missingFileCount) || 0),
      note: "轻量包未包含该连通分量的全部关联馈线，不能可靠判断带电/失电；energized返回null。"
    };
  }
  return {
    complete: true,
    energizationReliable: true,
    componentFileCount: Number(info.componentFileCount || 1),
    includedFileCount: Number(info.includedFileCount || 1),
    missingFileCount: 0,
    note: "该馈线所在连通分量已完整收录，可进行带电分析。"
  };
}
const userStore = createUserStore(DATA_ROOT);

const tools = [
  {
    name: "search_feeders",
    description: "搜索馈线。支持按变电站、F编号、线路名或任意关键词检索 BLACKXML 索引。",
    inputSchema: {
      type: "object",
      properties: {
        station: { type: "string", description: "变电站名称关键词，例如：宝安站、宝城宝安变电站。" },
        feeder: { type: "string", description: "馈线编号或名称，例如：F21、21、F21宝润线。" },
        query: { type: "string", description: "任意关键词，会匹配展示名、文件名、站名、线路名。" },
        limit: { type: "number", description: "返回数量，默认 20，最大 200。" }
      }
    }
  },
  {
    name: "get_feeder_topology",
    description: "查询某条馈线的拓扑结构，包含电源、图模文本、开关状态、电流、联络点和统计信息。仅当DAT中存在与图模设备ID匹配的测点时返回该开关电流。",
    inputSchema: {
      type: "object",
      properties: {
        file: { type: "string", description: "BLACKXML 相对路径。已知文件时优先使用。" },
        station: { type: "string", description: "变电站名称关键词。" },
        feeder: { type: "string", description: "馈线 F 编号或线路名。" },
        format: { type: "string", enum: ["text", "summary", "json"], description: "返回格式，默认 text。" },
        switchStates: { type: "object", description: "模拟开关状态覆盖，键为开关ID，值 true=合、false=分。" },
        related: { type: "string", enum: ["auto", "primary", "all"], description: "关联图模加载模式，默认 auto。" },
        maxRelated: { type: "number", description: "最多关联 XML 数量，默认 64。" },
        maxNodes: { type: "number", description: "布局最多节点数，默认 900。" },
        limit: { type: "number", description: "json/summary 列表返回上限。" }
      }
    }
  },
  {
    name: "get_cabinet_topology",
    description: "查询某个环网柜/开关柜在馈线中的局部拓扑，返回柜内开关状态和相邻开关/柜。",
    inputSchema: {
      type: "object",
      properties: {
        cabinet: { type: "string", description: "环网柜或开关柜名称关键词。" },
        file: { type: "string", description: "可选，BLACKXML 相对路径。" },
        station: { type: "string", description: "可选，变电站名称关键词。" },
        feeder: { type: "string", description: "可选，馈线 F 编号或线路名。" },
        switchStates: { type: "object", description: "模拟开关状态覆盖。" },
        radius: { type: "number", description: "邻接层级，默认 1，最大 3。" },
        limit: { type: "number", description: "返回邻接设备数量上限。" }
      },
      required: ["cabinet"]
    }
  },
  {
    name: "search_devices",
    description: "在全库或指定馈线内搜索柜子、开关、变压器、线路设备；匹配到DAT测点的开关会返回current电流对象。",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "设备、柜子、开关号、ID 或名称关键词。" },
        file: { type: "string", description: "可选，限定 BLACKXML 相对路径。" },
        station: { type: "string", description: "可选，限定变电站。" },
        feeder: { type: "string", description: "可选，限定馈线。" },
        type: { type: "string", enum: ["all", "cabinet", "switch", "transformer", "equipment"], description: "设备类型过滤，默认 all。" },
        limit: { type: "number", description: "返回数量，默认 30。" }
      },
      required: ["query"]
    }
  },
  {
    name: "assess_switch_operation",
    description: "评估单个开关合上/断开后的停电、复电、合环影响，包含影响变压器和用户摘要。",
    inputSchema: {
      type: "object",
      properties: {
        file: { type: "string", description: "BLACKXML 相对路径。" },
        station: { type: "string", description: "变电站名称关键词。" },
        feeder: { type: "string", description: "馈线 F 编号或线路名。" },
        switch: { type: "string", description: "开关ID、开关号、柜名+开关号或名称关键词。" },
        action: { type: "string", enum: ["open", "close", "toggle", "分", "合", "断开", "合上"], description: "操作类型。" },
        switchStates: { type: "object", description: "操作前已有的模拟状态覆盖。" },
        includeUsers: { type: "boolean", description: "是否查询影响用户，默认 true。" },
        userLimit: { type: "number", description: "用户明细上限，默认 200。" },
        limit: { type: "number", description: "设备列表上限，默认 50。" }
      },
      required: ["switch", "action"]
    }
  },
  {
    name: "simulate_operations",
    description: "按顺序模拟多个开关操作，适合大模型做操作票/仿真推演。",
    inputSchema: {
      type: "object",
      properties: {
        file: { type: "string", description: "BLACKXML 相对路径。" },
        station: { type: "string", description: "变电站名称关键词。" },
        feeder: { type: "string", description: "馈线 F 编号或线路名。" },
        operations: {
          type: "array",
          description: "操作序列。",
          items: {
            type: "object",
            properties: {
              switch: { type: "string", description: "开关ID、开关号、柜名+开关号或名称关键词。" },
              action: { type: "string", enum: ["open", "close", "toggle", "分", "合", "断开", "合上"] }
            },
            required: ["switch", "action"]
          }
        },
        switchStates: { type: "object", description: "操作前已有的模拟状态覆盖。" },
        includeUsers: { type: "boolean", description: "是否查询最终影响用户，默认 true。" },
        userLimit: { type: "number", description: "用户明细上限，默认 200。" },
        limit: { type: "number", description: "设备列表上限，默认 50。" }
      },
      required: ["operations"]
    }
  },
  {
    name: "query_impacted_users",
    description: "按变压器ID查询中压/低压用户清单，可用于停电影响用户明细。",
    inputSchema: {
      type: "object",
      properties: {
        transformerIds: { type: "array", items: { type: "string" }, description: "变压器设备ID列表，例如 TRANS_..." },
        limit: { type: "number", description: "用户明细上限，默认 1000。" }
      },
      required: ["transformerIds"]
    }
  },
  {
    name: "get_grid_overview",
    description: "查询全配网总体统计。用于回答配网有多少条馈线、多少个XML、多少座变电站、多少用户、哪些馈线用户最多，以及开关状态和电流数据覆盖情况。",
    inputSchema: {
      type: "object",
      properties: {
        topFeederLimit: { type: "number", description: "返回用户数最多的馈线数量，默认10，最大100。" }
      }
    }
  },
  {
    name: "query_switch_user_loads",
    description: "查询开关下带用户数及当前电流。按当前开关状态和多电源拓扑，统计断开该开关后必然失电的变压器及ZY/DY用户数；适合回答哪些开关下带超过2000户。",
    inputSchema: {
      type: "object",
      properties: {
        minUsers: { type: "number", description: "最少用户数，默认2000。" },
        station: { type: "string", description: "可选，按变电站名称过滤。" },
        feeder: { type: "string", description: "可选，按馈线ID或馈线名称过滤。" },
        query: { type: "string", description: "可选，按柜名、开关号或开关ID过滤。" },
        limit: { type: "number", description: "返回数量，默认100，最大1000。" }
      }
    }
  },
  {
    name: "query_switch_currents",
    description: "按实际电流对全网开关排序和筛选。用于回答电流最大/最小、超过某安培值、某变电站或馈线有哪些带电流测点的开关；返回柜名、馈线、三相电流和DAT来源。",
    inputSchema: {
      type: "object",
      properties: {
        minAmp: { type: "number", description: "可选，最小电流（A）。" },
        maxAmp: { type: "number", description: "可选，最大电流（A）。" },
        station: { type: "string", description: "可选，按变电站名称过滤。" },
        feeder: { type: "string", description: "可选，按馈线ID、F编号或馈线名称过滤。" },
        cabinet: { type: "string", description: "可选，按柜名过滤。" },
        query: { type: "string", description: "可选，按设备ID、开关号或柜名关键词过滤。" },
        sort: { type: "string", enum: ["desc", "asc"], description: "按电流降序或升序，默认desc。" },
        includeUnmatched: { type: "boolean", description: "是否包含DAT中存在但无法匹配BLACKXML设备的原始测点，默认false。" },
        limit: { type: "number", description: "返回数量，默认100，最大1000。" }
      }
    }
  },
  {
    name: "list_update_files",
    description: "列出管理员放入更新暂存区的XML、站线变户CSV、开关电流DAT和开关状态DT文件。",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "update_data_bundle",
    description: "统一更新BLACKXML、站线变户、开关电流和开关状态，并按需重建索引。执行前会预检全部暂存文件，同名文件自动备份。",
    inputSchema: {
      type: "object",
      properties: {
        xmlFiles: { type: "array", items: { type: "string" }, description: "XML文件名列表，最多500个。" },
        zyFile: { type: "string", description: "中压站线变户CSV文件名。" },
        dyFile: { type: "string", description: "低压站线变户CSV文件名。" },
        currentFile: { type: "string", description: "开关电流DAT文件名。" },
        statusFiles: { type: "array", items: { type: "string" }, description: "开关状态DT文件名列表，最多20个。" },
        rebuild: { type: "string", enum: ["none", "current", "analytics", "all"], description: "更新后重建的索引，默认all。" },
        minUsers: { type: "number", description: "分析索引的最小用户数，默认1。" },
        confirm: { type: "string", enum: ["APPLY"], description: "必须明确传APPLY才执行。" }
      },
      required: ["confirm"]
    }
  },
  {
    name: "reload_update_manifest",
    description: "读取更新暂存区中的reload.json，统一更新XML、站线变户、开关电流和开关状态，成功后归档清单。适合软件定时reload。",
    inputSchema: {
      type: "object",
      properties: {
        manifest: { type: "string", description: "JSON清单文件名，默认reload.json。" },
        confirm: { type: "string", enum: ["APPLY"], description: "必须明确传APPLY才执行。" }
      },
      required: ["confirm"]
    }
  },
  {
    name: "sync_to_dameng",
    description: "将MCP开关电流和负荷分析索引同步到达梦DM8。可选同步约四百万行站线变户数据。连接信息由管理员环境变量提供。",
    inputSchema: {
      type: "object",
      properties: {
        includeUsers: { type: "boolean", description: "是否同步站线变户全量数据，默认false。" },
        confirm: { type: "string", enum: ["APPLY"] }
      },
      required: ["confirm"]
    }
  },
  {
    name: "update_blackxml",
    description: "从更新暂存区导入一个或多个CIM/RDF XML图模。更新前自动备份同名文件，并刷新馈线索引。",
    inputSchema: {
      type: "object",
      properties: {
        files: { type: "array", items: { type: "string" }, description: "更新暂存区内的XML文件名，最多500个。" },
        confirm: { type: "string", enum: ["APPLY"], description: "必须明确传APPLY才执行。" }
      },
      required: ["files", "confirm"]
    }
  },
  {
    name: "update_station_line_transformer_users",
    description: "从更新暂存区导入站-线-变-户CSV并原子切换ZY/DY用户数据集。支持只更新其中一种。",
    inputSchema: {
      type: "object",
      properties: {
        zyFile: { type: "string", description: "中压用户CSV文件名。" },
        dyFile: { type: "string", description: "低压用户CSV文件名。" },
        confirm: { type: "string", enum: ["APPLY"], description: "必须明确传APPLY才执行。" }
      },
      required: ["confirm"]
    }
  },
  {
    name: "update_switch_current",
    description: "从更新暂存区导入开关电流DAT文件，保留旧文件并由时间戳选择最新数据。",
    inputSchema: {
      type: "object",
      properties: {
        file: { type: "string", description: "DAT文件名。" },
        confirm: { type: "string", enum: ["APPLY"] }
      },
      required: ["file", "confirm"]
    }
  },
  {
    name: "update_switch_status",
    description: "从更新暂存区导入全量或增量开关状态DT文件，更新前自动备份同名文件。",
    inputSchema: {
      type: "object",
      properties: {
        files: { type: "array", items: { type: "string" }, description: "DT文件名，最多20个。" },
        confirm: { type: "string", enum: ["APPLY"] }
      },
      required: ["files", "confirm"]
    }
  },
  {
    name: "rebuild_data_indexes",
    description: "数据更新后重建开关电流目录和开关用户数分析索引。全量图模可能需要较长时间。",
    inputSchema: {
      type: "object",
      properties: {
        target: { type: "string", enum: ["current", "analytics", "all"], description: "默认all。" },
        minUsers: { type: "number", description: "分析索引最小用户阈值，默认1。" },
        confirm: { type: "string", enum: ["APPLY"] }
      },
      required: ["confirm"]
    }
  },
  {
    name: "get_mcp_status",
    description: "查看 MCP 服务、BLACKXML、开关状态、用户索引的当前状态。",
    inputSchema: { type: "object", properties: {} }
  }
];

function getIndex(force = false) {
  if (!indexCache || force) indexCache = createLineIndex(XML_DIR);
  return indexCache;
}

function safeLimit(value, fallback = DEFAULT_LIMIT, max = 500) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return Math.max(1, Math.min(Math.floor(n), max));
}

function normalize(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, "");
}

function stationKey(value) {
  return normalize(value)
    .replace(/变电站/g, "")
    .replace(/供电局/g, "")
    .replace(/供电分局/g, "")
    .replace(/站$/g, "");
}

function stationMatches(line, stationValue) {
  const station = normalize(stationValue);
  if (!station) return true;
  const blob = normalize(`${line.stationName} ${line.fullStationName} ${line.stationLabel} ${line.district} ${line.displayName} ${line.fullDisplayName} ${line.fileName}`);
  if (blob.includes(station)) return true;
  const key = stationKey(stationValue);
  if (!key) return true;
  const stationBlob = stationKey(`${line.stationName} ${line.fullStationName} ${line.stationLabel} ${line.district} ${line.displayName} ${line.fullDisplayName} ${line.fileName}`);
  return stationBlob.includes(key);
}

function normalizeFeeder(value) {
  const text = String(value || "").trim().toUpperCase().replace(/\s+/g, "");
  const match = text.match(/F?0*(\d+)/);
  return match ? String(Number(match[1])) : "";
}

function lineSummary(line) {
  return {
    file: line.relativePath,
    feederId: line.id || (line.circuitMrid ? `CIRCUIT_${line.circuitMrid}` : ""),
    circuitMrid: line.circuitMrid || "",
    displayName: line.displayName,
    fullDisplayName: line.fullDisplayName || line.displayName,
    district: line.district || "",
    stationName: line.stationName,
    fullStationName: line.fullStationName || line.stationName,
    stationLabel: line.stationLabel || line.stationName,
    lineName: line.lineName,
    feederNo: line.feederNo,
    substationCount: line.substationCount,
    connectivityNodeCount: line.connectivityNodeCount
  };
}

function matchesLine(line, args = {}) {
  if (line.error) return false;
  const station = normalize(args.station);
  const feeder = normalizeFeeder(args.feeder || args.f);
  const feederText = normalize(args.feeder || args.f);
  const query = normalize(args.query);
  if (station && !stationMatches(line, args.station)) return false;
  if (feeder || feederText) {
    const lineBlob = normalize(`${line.lineName} ${line.displayName} ${line.fullDisplayName} ${line.fileName}`);
    if (feeder && String(Number(line.feederNo || -1)) !== feeder && !lineBlob.includes(`f${feeder}`)) return false;
    if (!feeder && feederText && !lineBlob.includes(feederText)) return false;
  }
  if (query) {
    const blob = normalize(`${line.displayName} ${line.fullDisplayName} ${line.stationName} ${line.fullStationName} ${line.stationLabel} ${line.district} ${line.lineName} ${line.fileName} ${line.relativePath}`);
    if (!blob.includes(query)) return false;
  }
  return true;
}

function searchFeeders(args = {}) {
  const limit = safeLimit(args.limit, 20, 200);
  const lines = getIndex().lines
    .filter((line) => matchesLine(line, args))
    .slice(0, limit)
    .map(lineSummary);
  return { count: lines.length, lines };
}

function resolveLine(args = {}) {
  const index = getIndex();
  if (args.file) {
    const filePath = resolveIndexedFile(XML_DIR, index, args.file);
    if (!filePath) throw userError("找不到指定 BLACKXML 文件", { file: args.file });
    const normalized = String(args.file).replace(/\\/g, "/");
    const line = index.map[normalized] || index.lines.find((item) => path.normalize(path.join(XML_DIR, item.relativePath)) === filePath);
    return { index, line, filePath };
  }

  const matches = index.lines.filter((line) => matchesLine(line, args));
  if (!matches.length) {
    throw userError("没有匹配的馈线", { args, candidates: searchFeeders({ query: args.query || args.station || args.feeder, limit: 10 }).lines });
  }
  if (matches.length > 1) {
    const exact = matches.filter((line) => {
      const feeder = normalizeFeeder(args.feeder || args.f);
      const station = normalize(args.station);
      return (!feeder || String(Number(line.feederNo || -1)) === feeder) &&
        (!station || normalize(line.stationName) === station || normalize(line.displayName).startsWith(station) || stationMatches(line, args.station));
    });
    if (exact.length === 1) {
      const filePath = path.join(XML_DIR, exact[0].relativePath);
      return { index, line: exact[0], filePath };
    }
    throw userError("匹配到多条馈线，请补充变电站或 file", {
      count: matches.length,
      candidates: matches.slice(0, 20).map(lineSummary)
    });
  }
  return { index, line: matches[0], filePath: path.join(XML_DIR, matches[0].relativePath) };
}

function buildTopology(args = {}) {
  const { index, line, filePath } = resolveLine(args);
  const topology = buildTopologyFromFile({
    xmlDir: XML_DIR,
    filePath,
    index,
    relatedMode: args.related || "auto",
    maxRelated: Number(args.maxRelated || DEFAULT_MAX_RELATED),
    maxNodes: Number(args.maxNodes || DEFAULT_MAX_NODES),
    switchStatus: loadSwitchStatus(STATUS_DIR),
    switchCurrent: loadSwitchCurrent(CURRENT_DIRS)
  });
  return { topology, line };
}

function buildStates(topology, overrides = {}) {
  return { ...(topology.graph.initialSwitchState || {}), ...(overrides || {}) };
}

function displayNameForEquipment(topology, id) {
  const item = topology.graph.equipmentById[id];
  if (!item) return id;
  const nodeId = item.layoutNodeId || (topology.layout.equipmentNode && topology.layout.equipmentNode[id]) || "";
  const node = nodeId && topology.layout.nodes[nodeId];
  const cabinet = node && !node.isSource && node.kind !== "inline-switch" ? String(node.name || "").trim() : "";
  const name = equipmentDisplayLabel(item, id);
  if (cabinet && name && !cabinet.includes(name)) return `${cabinet}${name}`;
  return cabinet || name || id;
}

function equipmentDisplayLabel(item, fallback = "") {
  if (item && SWITCH_TAGS.has(item.tag)) {
    return switchDisplayLabel(item, fallback);
  }
  return String((item && (item.dispatchNumber || item.name || item.mrid || item.id)) || fallback || "").trim();
}

function equipmentSummary(topology, id, state = null) {
  const item = topology.graph.equipmentById[id];
  if (!item) return { id, missing: true };
  const nodeId = item.layoutNodeId || (topology.layout.equipmentNode && topology.layout.equipmentNode[id]) || "";
  const node = nodeId && topology.layout.nodes[nodeId];
  const domains = state && state.equipmentDomains ? state.equipmentDomains[id] || [] : [];
  const current = topology.graph.switchCurrentById && topology.graph.switchCurrentById[id];
  return {
    id,
    tag: item.tag,
    name: displayNameForEquipment(topology, id),
    rawName: item.name || "",
    dispatchNumber: item.dispatchNumber || "",
    cabinet: node && node.kind !== "inline-switch" ? node.name || "" : "",
    energized: state ? (state.equipment || []).includes(id) : undefined,
    looped: state ? (state.loopedEquipment || []).includes(id) : undefined,
    current: current ? {
      amp: current.amp,
      display: current.display,
      ia: current.ia,
      ib: current.ib,
      ic: current.ic,
      i0: current.i0,
      fileName: current.fileName,
      timestamp: current.timestamp
    } : null,
    sources: domains.map((domain) => ({ label: domain.label, color: domain.color, owner: domain.owner }))
  };
}

function summarizeIds(topology, ids, state, limit) {
  const safe = safeLimit(limit, DEFAULT_LIMIT, 500);
  return {
    total: ids.length,
    truncated: ids.length > safe,
    items: ids.slice(0, safe).map((id) => equipmentSummary(topology, id, state))
  };
}

function topologySummary(topology, states = null, limit = DEFAULT_LIMIT) {
  const operational = computeOperationalState(topology.graph, states || buildStates(topology));
  const reliability = topologyReliability(topology.line);
  const switches = (topology.graph.switches || []).slice(0, safeLimit(limit, DEFAULT_LIMIT, 300)).map((item) => {
    const summary = {
      ...equipmentSummary(topology, item.id, operational),
      closed: (states || topology.graph.initialSwitchState || {})[item.id] !== false,
      tiePoint: !!item.isTiePoint
    };
    if (!reliability.energizationReliable) {
      summary.energized = null;
      summary.energizationReliable = false;
    }
    return summary;
  });
  return {
    scope: selectionScope(),
    analysisReliability: reliability,
    line: lineSummary(topology.line),
    includedFiles: topology.includedFiles || [],
    relatedFiles: topology.relatedFiles || [],
    stats: topology.stats,
    currentCoverage: {
      matchedSwitches: Number((topology.stats && topology.stats.liveSwitchCurrent) || 0),
      topologySwitches: Number((topology.stats && topology.stats.switches) || 0),
      datCurrentPoints: Number((topology.graph.currentSummary && topology.graph.currentSummary.currentCount) || 0),
      note: Number((topology.stats && topology.stats.liveSwitchCurrent) || 0) === 0
        ? "当前DAT没有与本次拓扑内开关设备ID匹配的测点；这不表示全网电流文件未加载。"
        : "current字段仅对DAT中存在匹配设备ID的开关有值。"
    },
    sources: (topology.graph.sources || []).map((source) => ({
      id: source.id,
      label: source.label,
      color: source.color,
      nodeId: source.nodeId,
      name: displayNameForEquipment(topology, source.id)
    })),
    energized: {
      equipment: operational.equipment.length,
      connectivityNodes: operational.connectivityNodes.length,
      loopedEquipment: operational.loopedEquipment.length,
      tiePoints: Object.keys(operational.tiePoints || {}).length
    },
    switches
  };
}

function getFeederTopology(args = {}) {
  const { topology } = buildTopology(args);
  const states = buildStates(topology, args.switchStates);
  const format = args.format || "text";
  const summary = topologySummary(topology, states, args.limit);
  if (format === "summary") return summary;
  if (format === "json") {
    return {
      ...summary,
      topologyText: clipText(buildTopologyText(topology, args.switchStates || {}), 80000),
      cabinets: Object.values(topology.layout.nodes || {})
        .filter((node) => node.kind === "substation")
        .slice(0, safeLimit(args.limit, DEFAULT_LIMIT, 300))
        .map((node) => ({
          id: node.id,
          name: node.name,
          switches: (node.equipment || [])
            .filter((id) => topology.graph.equipmentById[id] && SWITCH_TAGS.has(topology.graph.equipmentById[id].tag))
            .map((id) => ({
              id,
              name: displayNameForEquipment(topology, id),
              closed: states[id] !== false,
              tiePoint: !!topology.graph.equipmentById[id].isTiePoint
            }))
        }))
    };
  }
  return {
    ...summary,
    topologyText: clipText(buildTopologyText(topology, args.switchStates || {}), 120000)
  };
}

function findCabinetLineCandidates(cabinet, args = {}) {
  const q = normalize(cabinet);
  if (!q) return [];
  return getIndex().lines
    .filter((line) => !line.error)
    .filter((line) => {
      if (!matchesLine(line, { station: args.station, feeder: args.feeder })) return false;
      return (line.substationNames || []).some((name) => normalize(name).includes(q));
    })
    .slice(0, safeLimit(args.limit, 20, 200));
}

function getCabinetTopology(args = {}) {
  if (!args.cabinet) throw userError("缺少 cabinet 参数");
  if (!args.file && !args.feeder) {
    const candidates = findCabinetLineCandidates(args.cabinet, args);
    if (candidates.length !== 1) {
      return {
        ambiguous: candidates.length > 1,
        message: candidates.length ? "该柜子出现在多条馈线中，请指定 file/station/feeder" : "未找到该柜子",
        candidates: candidates.map(lineSummary)
      };
    }
    args = { ...args, file: candidates[0].relativePath };
  }
  const { topology } = buildTopology(args);
  const states = buildStates(topology, args.switchStates);
  const operational = computeOperationalState(topology.graph, states);
  const node = findCabinetNode(topology, args.cabinet);
  if (!node) {
    const matches = searchDevicesInTopology(topology, args.cabinet, "cabinet", 20);
    throw userError("指定馈线中未找到柜子", { cabinet: args.cabinet, candidates: matches });
  }
  const adjacency = buildSwitchAdjacency(topology.graph, visibleSwitchIds(topology.graph));
  const radius = Math.max(1, Math.min(Number(args.radius || 1), 3));
  const local = cabinetNeighborhood(topology, node, adjacency, states, operational, radius, args.limit);
  return {
    line: lineSummary(topology.line),
    cabinet: {
      id: node.id,
      rawId: node.rawId,
      name: node.name,
      energized: local.switches.some((item) => item.energized),
      sourceLabels: unique(local.switches.flatMap((item) => (item.sources || []).map((source) => source.label).filter(Boolean)))
    },
    ...local
  };
}

function findCabinetNode(topology, query) {
  const q = normalize(query);
  const nodes = Object.values(topology.layout.nodes || {}).filter((node) => node.kind === "substation" && node.name);
  return nodes
    .map((node) => {
      const name = normalize(node.name);
      let score = 99;
      if (name === q) score = 0;
      else if (name.startsWith(q)) score = 1;
      else if (name.includes(q)) score = 2;
      else if (normalize(`${node.id} ${node.rawId} ${node.objectId}`).includes(q)) score = 3;
      return score < 99 ? { node, score } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.score - b.score || a.node.name.length - b.node.name.length)[0]?.node || null;
}

function visibleSwitchIds(graph) {
  return new Set((graph.switches || [])
    .filter((item) => item.tag !== "GroundDisconnector")
    .map((item) => item.id));
}

function buildSwitchAdjacency(graph, switchIds) {
  const adjacency = new Map([...switchIds].map((id) => [id, new Set()]));
  const eqToCn = graph.eqToCn || {};
  const cnToEq = graph.cnToEq || {};
  for (const startId of switchIds) {
    const queue = (eqToCn[startId] || []).map((id) => ({ type: "cn", id }));
    const seenCn = new Set(eqToCn[startId] || []);
    const seenEq = new Set([startId]);
    while (queue.length) {
      const current = queue.shift();
      if (current.type === "cn") {
        for (const eqId of cnToEq[current.id] || []) {
          if (seenEq.has(eqId)) continue;
          seenEq.add(eqId);
          if (switchIds.has(eqId)) {
            adjacency.get(startId).add(eqId);
            adjacency.get(eqId).add(startId);
            continue;
          }
          queue.push({ type: "eq", id: eqId });
        }
      } else {
        for (const cn of eqToCn[current.id] || []) {
          if (seenCn.has(cn)) continue;
          seenCn.add(cn);
          queue.push({ type: "cn", id: cn });
        }
      }
    }
  }
  return adjacency;
}

function cabinetNeighborhood(topology, node, adjacency, states, operational, radius, limit) {
  const nodeSwitchIds = (node.equipment || [])
    .filter((id) => adjacency.has(id))
    .sort((a, b) => compareSwitchOrder(topology.graph.equipmentById[a], topology.graph.equipmentById[b]));
  const visited = new Set(nodeSwitchIds);
  const queue = nodeSwitchIds.map((id) => ({ id, depth: 0 }));
  const edges = [];
  while (queue.length) {
    const current = queue.shift();
    if (current.depth >= radius) continue;
    for (const next of adjacency.get(current.id) || []) {
      edges.push({ from: current.id, to: next, depth: current.depth + 1 });
      if (visited.has(next)) continue;
      visited.add(next);
      queue.push({ id: next, depth: current.depth + 1 });
    }
  }
  const ids = [...visited];
  const safe = safeLimit(limit, DEFAULT_LIMIT, 300);
  return {
    switches: nodeSwitchIds.map((id) => ({
      ...equipmentSummary(topology, id, operational),
      closed: states[id] !== false,
      tiePoint: !!topology.graph.equipmentById[id].isTiePoint
    })),
    transformers: (node.equipment || [])
      .filter((id) => topology.graph.equipmentById[id] && topology.graph.equipmentById[id].tag === "PowerTransformer")
      .map((id) => equipmentSummary(topology, id, operational)),
    neighbors: ids
      .filter((id) => !nodeSwitchIds.includes(id))
      .slice(0, safe)
      .map((id) => ({
        ...equipmentSummary(topology, id, operational),
        closed: states[id] !== false,
        tiePoint: !!topology.graph.equipmentById[id].isTiePoint
      })),
    connections: edges.slice(0, safe).map((edge) => ({
      from: displayNameForEquipment(topology, edge.from),
      fromId: edge.from,
      to: displayNameForEquipment(topology, edge.to),
      toId: edge.to,
      depth: edge.depth
    }))
  };
}

function searchDevices(args = {}) {
  if (!args.query) throw userError("缺少 query 参数");
  if (args.file || args.feeder) {
    const { topology } = buildTopology(args);
    return {
      line: lineSummary(topology.line),
      matches: searchDevicesInTopology(topology, args.query, args.type || "all", args.limit)
    };
  }

  if (args.station && (!args.type || args.type === "all" || args.type === "cabinet")) {
    const matches = searchCabinetsInIndex(args);
    if (matches.length) {
      return {
        scope: "index",
        matches,
        hint: "已按站名和柜名在图模索引中匹配。需要柜内开关和相邻设备时，请用返回的 file 调用 get_cabinet_topology。"
      };
    }
  }

  const limit = safeLimit(args.limit, 30, 200);
  const q = normalize(args.query);
  const lineMatches = getIndex().lines
    .filter((line) => !line.error)
    .filter((line) => stationMatches(line, args.station))
    .filter((line) =>
      normalize(`${line.displayName} ${line.fullDisplayName} ${line.stationName} ${line.fullStationName} ${line.stationLabel} ${line.district} ${line.relativePath} ${(line.substationNames || []).join(" ")}`).includes(q)
    )
    .slice(0, limit)
    .map(lineSummary);
  return {
    scope: "index",
    matches: lineMatches,
    hint: "如需精确到柜内开关，请带 file/station/feeder 再调用 search_devices 或 get_cabinet_topology。"
  };
}

function searchCabinetsInIndex(args = {}) {
  const q = normalize(args.query);
  const safe = safeLimit(args.limit, 30, 200);
  const out = [];
  for (const line of getIndex().lines) {
    if (!line || line.error || !stationMatches(line, args.station)) continue;
    for (const name of line.substationNames || []) {
      const blob = normalize(name);
      if (!blob.includes(q)) continue;
      out.push({
        type: "cabinet",
        name,
        line: lineSummary(line),
        file: line.relativePath
      });
      if (out.length >= safe) return out;
    }
  }
  return out.sort((a, b) => scoreMatch(a, q) - scoreMatch(b, q) || String(a.name).localeCompare(String(b.name), "zh-Hans-CN"));
}

function searchDevicesInTopology(topology, query, type = "all", limit = DEFAULT_LIMIT) {
  const q = normalize(query);
  const out = [];
  const safe = safeLimit(limit, 30, 300);
  if (type === "all" || type === "cabinet") {
    for (const node of Object.values(topology.layout.nodes || {})) {
      if (node.kind !== "substation") continue;
      const blob = normalize(`${node.id} ${node.rawId} ${node.objectId} ${node.name}`);
      if (blob.includes(q)) out.push({ type: "cabinet", id: node.id, rawId: node.rawId, name: node.name });
    }
  }
  if (type !== "cabinet") {
    for (const item of topology.graph.equipment || []) {
      if (type === "switch" && !SWITCH_TAGS.has(item.tag)) continue;
      if (type === "transformer" && item.tag !== "PowerTransformer") continue;
      if (type === "equipment" && SWITCH_TAGS.has(item.tag)) continue;
      const name = displayNameForEquipment(topology, item.id);
      const blob = normalize(`${item.id} ${item.mrid} ${item.name} ${item.dispatchNumber} ${item.tag} ${name}`);
      if (blob.includes(q)) out.push({ type: item.tag, id: item.id, name, dispatchNumber: item.dispatchNumber || "" });
    }
  }
  return out
    .sort((a, b) => scoreMatch(a, q) - scoreMatch(b, q) || String(a.name).localeCompare(String(b.name), "zh-Hans-CN"))
    .slice(0, safe);
}

function scoreMatch(item, q) {
  const name = normalize(`${item.name} ${item.id}`);
  if (name === q) return 0;
  if (name.startsWith(q)) return 1;
  return 2;
}

function resolveSwitch(topology, query) {
  const q = normalize(query);
  const switches = topology.graph.switches || [];
  const rows = switches.map((item) => {
    const display = displayNameForEquipment(topology, item.id);
    const candidates = [
      item.id,
      item.mrid,
      item.name,
      item.dispatchNumber,
      display,
      `${display}${item.name || ""}`,
      `${display}${item.dispatchNumber || ""}`
    ].filter(Boolean);
    let score = 99;
    for (const value of candidates) {
      const n = normalize(value);
      if (n === q) score = Math.min(score, 0);
      else if (n.endsWith(q) || n.startsWith(q)) score = Math.min(score, 1);
      else if (n.includes(q)) score = Math.min(score, 2);
    }
    return { item, display, score };
  }).filter((row) => row.score < 99);
  if (!rows.length) {
    throw userError("找不到开关", { query, candidates: searchDevicesInTopology(topology, query, "switch", 10) });
  }
  rows.sort((a, b) => a.score - b.score || a.display.length - b.display.length);
  if (rows.length > 1 && rows[0].score > 0 && rows[0].score === rows[1].score) {
    throw userError("开关匹配不唯一，请使用柜名+开关号或开关ID", {
      query,
      candidates: rows.slice(0, 10).map((row) => ({ id: row.item.id, name: row.display, state: row.item.id }))
    });
  }
  return rows[0].item;
}

function actionToClosed(action, current) {
  const text = normalize(action);
  if (["open", "分", "断开", "拉开", "fen"].includes(text)) return false;
  if (["close", "合", "合上", "闭合", "he"].includes(text)) return true;
  if (["toggle", "切换"].includes(text)) return !current;
  throw userError("未知操作类型", { action });
}

function simulateOperations(args = {}) {
  const operations = args.operations || (args.switch && args.action ? [{ switch: args.switch, action: args.action }] : []);
  if (!operations.length) throw userError("缺少 operations");
  const { topology } = buildTopology(args);
  const graph = topology.graph;
  const states = buildStates(topology, args.switchStates);
  const initialState = computeOperationalState(graph, states);
  let before = initialState;
  const steps = [];
  const resolvedOperations = [];

  for (const op of operations) {
    const sw = resolveSwitch(topology, op.switch);
    const oldClosed = states[sw.id] !== false;
    const newClosed = actionToClosed(op.action, oldClosed);
    states[sw.id] = newClosed;
    const after = computeOperationalState(graph, states);
    const diff = diffOperationalState(graph, before, after);
    const step = {
      switch: equipmentSummary(topology, sw.id, after),
      action: newClosed ? "close" : "open",
      stateBefore: oldClosed ? "合" : "分",
      stateAfter: newClosed ? "合" : "分",
      impact: summarizeImpact(topology, before, after, diff, args.limit)
    };
    steps.push(step);
    resolvedOperations.push({ switchId: sw.id, switchName: displayNameForEquipment(topology, sw.id), closed: newClosed });
    before = after;
  }

  const finalState = before;
  const finalDiff = diffOperationalState(graph, initialState, finalState);
  const includeUsers = args.includeUsers !== false;
  const outageUsers = includeUsers ? userStore.queryUsers(finalDiff.outagedTransformers, args.userLimit || 200) : null;
  const restoredUsers = includeUsers ? userStore.queryUsers(finalDiff.restoredTransformers, args.userLimit || 200) : null;
  return {
    line: lineSummary(topology.line),
    operations: resolvedOperations,
    steps,
    finalImpact: summarizeImpact(topology, initialState, finalState, finalDiff, args.limit),
    impactedUsers: includeUsers
      ? {
          outage: outageUsers,
          restored: restoredUsers
        }
      : undefined,
    finalSwitchStates: states
  };
}

function summarizeImpact(topology, before, after, diff, limit = DEFAULT_LIMIT) {
  const tiePoints = Object.entries(after.tiePoints || {}).map(([id, value]) => ({
    id,
    name: displayNameForEquipment(topology, id),
    closed: value.closed,
    sides: value.sides
  }));
  return {
    counts: {
      outagedEquipment: diff.outagedEquipment.length,
      restoredEquipment: diff.restoredEquipment.length,
      outagedTransformers: diff.outagedTransformers.length,
      restoredTransformers: diff.restoredTransformers.length,
      newlyLoopedEquipment: diff.newlyLoopedEquipment.length,
      clearedLoopedEquipment: diff.clearedLoopedEquipment.length,
      tiePoints: tiePoints.length
    },
    outagedTransformers: summarizeIds(topology, diff.outagedTransformers, after, limit),
    restoredTransformers: summarizeIds(topology, diff.restoredTransformers, after, limit),
    outagedEquipment: summarizeIds(topology, diff.outagedEquipment, after, limit),
    restoredEquipment: summarizeIds(topology, diff.restoredEquipment, after, limit),
    newlyLoopedEquipment: summarizeIds(topology, diff.newlyLoopedEquipment, after, limit),
    tiePoints: tiePoints.slice(0, safeLimit(limit, DEFAULT_LIMIT, 200))
  };
}

function queryImpactedUsers(args = {}) {
  const result = userStore.queryUsers(args.transformerIds || [], args.limit || 1000);
  return {
    transformerIds: args.transformerIds || [],
    ...result
  };
}

function gridOverview(args = {}) {
  const index = getIndex();
  const validLines = index.lines.filter((line) => !line.error);
  const uniqueFeederIds = new Set(
    validLines.map((line) => line.id || (line.circuitMrid ? `CIRCUIT_${line.circuitMrid}` : "")).filter(Boolean)
  );
  const stations = new Set(
    validLines.map((line) => line.fullStationName || line.stationName).filter(Boolean)
  );
  const districts = new Set(validLines.map((line) => line.district).filter(Boolean));
  const topFeederLimit = safeLimit(args.topFeederLimit, 10, 100);
  const switchStatus = loadSwitchStatus(STATUS_DIR).summary;
  const switchCurrent = loadSwitchCurrent(CURRENT_DIRS).summary;
  const users = userStore.status();
  const analytics = analyticsStatus(DATA_ROOT);
  const currentCatalog = currentCatalogStatus(DATA_ROOT);
  const topFeeders = (analytics.topFeedersByUsers || []).slice(0, topFeederLimit);
  const currentFile = (switchCurrent.currentFiles || []).find((item) => item.selected) || null;
  return {
    scope: selectionScope(),
    definition: {
      feederCount: "按Circuit唯一ID去重后的馈线数量",
      xmlFileCount: "BLACKXML目录中的XML图模文件数量，可能包含同一馈线的重复/分片文件",
      stationCount: "按完整变电站名称去重",
      userCount: "当前导入的ZY和DY用户记录总数"
    },
    feederCount: uniqueFeederIds.size,
    feederRecordCount: validLines.length,
    xmlFileCount: index.count,
    duplicateOrFragmentXmlCount: Math.max(0, validLines.length - uniqueFeederIds.size),
    invalidXmlCount: index.lines.length - validLines.length,
    stationCount: stations.size,
    districtCount: districts.size,
    userCount: users.totalUsers,
    userDatasets: users.datasets,
    feederUserStatistics: {
      feedersWithUsers: Number(analytics.feedersWithUsers || 0),
      topFeeders,
      available: !!analytics.built,
      complete: analytics.complete === true,
      note: !analytics.built
        ? "尚未构建全网分析索引"
        : analytics.complete === true
          ? "来自持久化全网分析索引"
          : `当前仅完成${analytics.processedComponents || 0}/${analytics.componentCount || 0}个连通分量，排行不能视为全网结论`
    },
    switchStatus: {
      switchCount: switchStatus.switchCount,
      groundCount: switchStatus.groundCount,
      files: switchStatus.switchFiles,
      version: switchStatus.version
    },
    switchCurrent: {
      currentCount: switchCurrent.currentCount,
      currentRows: switchCurrent.currentRows,
      selectedFile: currentFile,
      version: switchCurrent.version,
      catalog: currentCatalog
    },
    switchUserLoadAnalytics: analytics
  };
}

function analyticsFreshness(status) {
  const current = loadSwitchCurrent(CURRENT_DIRS).summary;
  const switchStatus = loadSwitchStatus(STATUS_DIR).summary;
  const users = userStore.status();
  const currentDatasets = users.datasets.map((item) => item.datasetId).sort();
  const indexedDatasets = (status.userDatasets || []).map((item) => item.datasetId).sort();
  const reasons = [];
  if (JSON.stringify(currentDatasets) !== JSON.stringify(indexedDatasets)) reasons.push("用户列表已变化");
  if (status.switchStatusVersion !== switchStatus.version) reasons.push("开关状态已变化");
  if (status.switchCurrentVersion !== current.version) reasons.push("开关电流文件已变化");
  return { fresh: reasons.length === 0, reasons };
}

function querySwitchUserLoads(args = {}) {
  const status = analyticsStatus(DATA_ROOT);
  if (!status.built) {
    return {
      error: "开关用户数分析索引尚未构建",
      buildCommand: "F:\\Node\\node.exe tools/build-grid-analytics.js --min-users 2000"
    };
  }
  const minUsers = Math.max(0, Math.floor(Number(args.minUsers) || 2000));
  if (minUsers < Number(status.minCandidateUsers || 0)) {
    return {
      error: `当前分析索引只保证用户数不少于${status.minCandidateUsers}的查询完整`,
      requestedMinUsers: minUsers,
      buildCommand: `F:\\Node\\node.exe tools/build-grid-analytics.js --min-users ${minUsers}`,
      analytics: status
    };
  }
  const result = querySwitchLoads(DATA_ROOT, {
    minUsers,
    station: args.station,
    feeder: args.feeder,
    query: args.query,
    limit: safeLimit(args.limit, 100, 1000)
  });
  const freshness = analyticsFreshness(status);
  const scopeWarning = status.complete === true
    ? ""
    : `分析索引尚未完整构建，仅完成${status.processedComponents || 0}/${status.componentCount || 0}个连通分量；当前结果不能用于全网结论。`;
  return {
    scope: selectionScope(),
    definition: "用户数表示在当前开关状态和全部已知电源下，断开该开关后因不存在其他供电路径而必然失电的用户数。",
    method: "对完整关联XML构建多电源导通图，用支配关系汇总开关下游变压器的ZY/DY用户。",
    threshold: minUsers,
    count: result.count,
    switches: result.rows,
    truncated: result.truncated,
    warning: [scopeWarning, freshness.fresh ? "" : `分析索引已过期：${freshness.reasons.join("、")}`]
      .filter(Boolean)
      .join(" "),
    analytics: {
      builtAt: status.builtAt,
      complete: status.complete,
      minCandidateUsers: status.minCandidateUsers,
      processedComponents: status.processedComponents,
      rowCount: status.rowCount,
      freshness
    }
  };
}

function querySwitchCurrents(args = {}) {
  const status = currentCatalogStatus(DATA_ROOT);
  if (!status.built) {
    return {
      error: "开关电流检索目录尚未构建",
      buildCommand: "F:\\Node\\node.exe tools/build-current-catalog.js --quiet",
      currentData: loadSwitchCurrent(CURRENT_DIRS).summary
    };
  }
  const result = queryCurrentCatalog(DATA_ROOT, {
    minAmp: args.minAmp,
    maxAmp: args.maxAmp,
    station: args.station,
    feeder: args.feeder,
    cabinet: args.cabinet,
    query: args.query,
    sort: args.sort,
    includeUnmatched: args.includeUnmatched === true,
    limit: safeLimit(args.limit, 100, 1000)
  });
  const liveCurrent = loadSwitchCurrent(CURRENT_DIRS).summary;
  const fresh = status.switchCurrentVersion === liveCurrent.version;
  const hasScope = !!String(args.station || args.feeder || args.cabinet || args.query || "").trim();
  return {
    scope: selectionScope(),
    definition: "currentAmp取DAT中有效A/B/C三相电流绝对值的最大值；默认只返回已匹配BLACKXML设备的测点。",
    count: result.count,
    switches: result.rows,
    truncated: result.truncated,
    sort: result.sort,
    note: result.count === 0 && hasScope
      ? "当前DAT中没有与该筛选范围BLACKXML设备ID匹配的电流测点；不能据此推断电流文件整体未加载。"
      : "",
    warning: fresh ? "" : "电流DAT已变化，目录中的数值可能过期，请重新构建开关电流检索目录。",
    coverage: {
      datCurrentPoints: status.currentCount,
      matchedBlackxmlPoints: status.matchedXmlCount,
      unmatchedBlackxmlPoints: status.unmatchedXmlCount,
      currentFile: status.switchCurrentFile,
      builtAt: status.builtAt,
      fresh
    }
  };
}

function getMcpStatus() {
  const index = getIndex();
  const status = loadSwitchStatus(STATUS_DIR).summary;
  const current = loadSwitchCurrent(CURRENT_DIRS).summary;
  return {
    scope: selectionScope(),
    root: ROOT,
    dataRoot: DATA_ROOT,
    xmlDir: XML_DIR,
    statusDir: STATUS_DIR,
    currentDirs: CURRENT_DIRS,
    lineCount: index.count,
    indexGeneratedAt: index.generatedAt,
    switchStatus: status,
    switchCurrent: current,
    switchCurrentCatalog: currentCatalogStatus(DATA_ROOT),
    gridAnalytics: analyticsStatus(DATA_ROOT),
    users: userStore.status(),
    updates: {
      enabled: updatesEnabled(),
      updateDir: UPDATE_DIR,
      backupDir: BACKUP_DIR
    },
    tools: tools.map((tool) => tool.name)
  };
}

function clipText(text, maxChars) {
  const value = String(text || "");
  if (value.length <= maxChars) return value;
  return `${value.slice(0, maxChars)}\n...（已截断，原始长度 ${value.length} 字符）`;
}

function unique(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function userError(message, details = {}) {
  const error = new Error(message);
  error.user = true;
  error.details = details;
  return error;
}

async function callTool(name, args = {}) {
  switch (name) {
    case "search_feeders":
      return searchFeeders(args);
    case "get_feeder_topology":
      return getFeederTopology(args);
    case "get_cabinet_topology":
      return getCabinetTopology(args);
    case "search_devices":
      return searchDevices(args);
    case "assess_switch_operation":
      return simulateOperations({ ...args, operations: [{ switch: args.switch, action: args.action }] });
    case "simulate_operations":
      return simulateOperations(args);
    case "query_impacted_users":
      return queryImpactedUsers(args);
    case "get_grid_overview":
      return gridOverview(args);
    case "query_switch_user_loads":
      return querySwitchUserLoads(args);
    case "query_switch_currents":
      return querySwitchCurrents(args);
    case "list_update_files":
      return listUpdateFiles();
    case "update_data_bundle": {
      const result = await updateDataBundle(args);
      if (Array.isArray(args.xmlFiles) && args.xmlFiles.length) indexCache = null;
      return result;
    }
    case "reload_update_manifest": {
      const result = await reloadUpdateManifest(args);
      indexCache = null;
      return result;
    }
    case "sync_to_dameng":
      return syncToDameng(args);
    case "update_blackxml": {
      const result = await updateXmlFiles(args);
      indexCache = null;
      return { ...result, index: { lineCount: getIndex(true).count, generatedAt: getIndex().generatedAt } };
    }
    case "update_station_line_transformer_users":
      return updateUserIndex(args);
    case "update_switch_current":
      return updateSwitchCurrent(args);
    case "update_switch_status":
      return updateSwitchStatus(args);
    case "rebuild_data_indexes":
      return rebuildIndexes(args);
    case "get_mcp_status":
      return getMcpStatus();
    default:
      throw userError(`未知工具：${name}`);
  }
}

function toolResult(data) {
  return {
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    structuredContent: data
  };
}

function errorToolResult(error) {
  const data = {
    error: error.message || String(error),
    details: error.details || undefined,
    stack: error.user ? undefined : error.stack
  };
  return {
    isError: true,
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    structuredContent: data
  };
}

async function handleRequest(message) {
  const { id, method, params = {} } = message;
  if (method === "initialize") {
    return {
      jsonrpc: "2.0",
      id,
      result: {
        protocolVersion: params.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        instructions: "默认使用简体中文回答。进行配网数据分析并生成图表时，图表标题、坐标轴、图例、分类名称和注释必须使用简体中文；专业缩写和设备原始名称可保留。Python Matplotlib 必须优先设置 font.sans-serif 为 WenQuanYi Zen Hei，并设置 axes.unicode_minus=false，不要改用仅支持西文的字体。图表保存为 /mnt/data 下的 PNG 文件，分析明细同时保存为 CSV，并将文件作为附件返回。",
        serverInfo: {
          name: selectionScope().mode === "lite" ? "blackxml-topology-mcp-lite" : "blackxml-topology-mcp",
          version: "1.0.0"
        }
      }
    };
  }
  if (method === "tools/list") {
    return { jsonrpc: "2.0", id, result: { tools } };
  }
  if (method === "tools/call") {
    try {
      const result = await callTool(params.name, params.arguments || {});
      return { jsonrpc: "2.0", id, result: toolResult(result) };
    } catch (error) {
      return { jsonrpc: "2.0", id, result: errorToolResult(error) };
    }
  }
  if (method === "resources/list") {
    return { jsonrpc: "2.0", id, result: { resources: [] } };
  }
  if (method === "prompts/list") {
    return { jsonrpc: "2.0", id, result: { prompts: [] } };
  }
  if (method === "ping") {
    return { jsonrpc: "2.0", id, result: {} };
  }
  return {
    jsonrpc: "2.0",
    id,
    error: { code: -32601, message: `Method not found: ${method}` }
  };
}

function sendMessage(message) {
  const payload = JSON.stringify(message);
  if (responseMode === "line") {
    process.stdout.write(`${payload}\n`);
    return;
  }
  process.stdout.write(`Content-Length: ${Buffer.byteLength(payload, "utf8")}\r\n\r\n${payload}`);
}

let buffer = Buffer.alloc(0);
let responseMode = "framed";

process.stdin.on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  drainMessages().catch((error) => {
    console.error(error);
  });
});

async function drainMessages() {
  while (buffer.length) {
    const headerBoundary = findHeaderBoundary(buffer);
    if (!headerBoundary) {
      const asText = buffer.toString("utf8");
      const newline = asText.indexOf("\n");
      if (!asText.trimStart().startsWith("{") || newline < 0) return;
      const line = asText.slice(0, newline).trim();
      buffer = Buffer.from(asText.slice(newline + 1), "utf8");
      responseMode = "line";
      await dispatch(JSON.parse(line));
      continue;
    }
    const header = buffer.slice(0, headerBoundary.index).toString("utf8");
    const match = header.match(/Content-Length:\s*(\d+)/i);
    if (!match) {
      buffer = buffer.slice(headerBoundary.index + headerBoundary.length);
      continue;
    }
    const length = Number(match[1]);
    const start = headerBoundary.index + headerBoundary.length;
    const end = start + length;
    if (buffer.length < end) return;
    const payload = buffer.slice(start, end).toString("utf8");
    buffer = buffer.slice(end);
    responseMode = "framed";
    await dispatch(JSON.parse(payload));
  }
}

function findHeaderBoundary(input) {
  const crlf = input.indexOf("\r\n\r\n");
  const lf = input.indexOf("\n\n");
  if (crlf < 0 && lf < 0) return null;
  if (crlf >= 0 && (lf < 0 || crlf <= lf)) return { index: crlf, length: 4 };
  return { index: lf, length: 2 };
}

async function dispatch(message) {
  if (!message || !message.method) return;
  if (message.id === undefined || String(message.method).startsWith("notifications/")) return;
  const response = await handleRequest(message);
  if (response) sendMessage(response);
}

process.on("uncaughtException", (error) => {
  console.error(error);
});

process.on("unhandledRejection", (error) => {
  console.error(error);
});
