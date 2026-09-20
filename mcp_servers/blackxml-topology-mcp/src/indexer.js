//扫描所有 XML 文件，建立快速查找索引
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { parseCimMeta } = require("./cimParser");

const INDEX_CACHE_VERSION = 3;
//递归遍历目录找到所有 XML
function walkXml(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walkXml(full));
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".xml")) {
      out.push(full);
    }
  }
  return out;
}

function defaultIndexCacheFile(xmlDir) {
  return path.join(path.dirname(xmlDir), ".cache", "line-index.json");
}
//计算文件哈希用于缓存判断
function xmlSignature(files) {
  const hash = crypto.createHash("sha1");
  for (const filePath of files) {
    const stat = fs.statSync(filePath);
    hash.update(path.resolve(filePath));
    hash.update("\0");
    hash.update(String(stat.size));
    hash.update("\0");
    hash.update(String(stat.mtimeMs));
    hash.update("\n");
  }
  return hash.digest("hex");
}

function encodeConnectivityKey(key) {
  return typeof key === "number" ? ["n", key] : ["s", String(key)];
}

function decodeConnectivityKey(key) {
  if (Array.isArray(key) && key[0] === "n") return Number(key[1]);
  if (Array.isArray(key) && key[0] === "s") return String(key[1]);
  return connectivityNodeKey(key);
}

function attachHiddenMaps(index, byConnectivityNode, connectivityNodesByFile) {
  Object.defineProperty(index, "byConnectivityNode", {
    value: byConnectivityNode,
    enumerable: false
  });
  Object.defineProperty(index, "connectivityNodesByFile", {
    value: connectivityNodesByFile,
    enumerable: false
  });
  return index;
}

function readCachedIndex(cacheFile, xmlDir, signature) {
  try {
    if (!cacheFile || !fs.existsSync(cacheFile)) return null;
    const cached = JSON.parse(fs.readFileSync(cacheFile, "utf8"));
    if (
      cached.version !== INDEX_CACHE_VERSION ||
      cached.xmlDir !== xmlDir ||
      cached.signature !== signature ||
      !cached.index
    ) {
      return null;
    }
    const byConnectivityNode = new Map(
      (cached.byConnectivityNode || []).map(([key, value]) => [decodeConnectivityKey(key), value])
    );
    const connectivityNodesByFile = new Map(cached.connectivityNodesByFile || []);
    return attachHiddenMaps(cached.index, byConnectivityNode, connectivityNodesByFile);
  } catch (err) {
    return null;
  }
}

function writeCachedIndex(cacheFile, xmlDir, signature, index) {
  try {
    fs.mkdirSync(path.dirname(cacheFile), { recursive: true });
    const payload = {
      version: INDEX_CACHE_VERSION,
      xmlDir,
      signature,
      generatedAt: new Date().toISOString(),
      index: {
        generatedAt: index.generatedAt,
        xmlDir: index.xmlDir,
        count: index.count,
        lines: index.lines,
        map: index.map,
        bySourceSubst: index.bySourceSubst,
        bySubstation: index.bySubstation
      },
      byConnectivityNode: [...index.byConnectivityNode.entries()].map(([key, value]) => [
        encodeConnectivityKey(key),
        value
      ]),
      connectivityNodesByFile: [...index.connectivityNodesByFile.entries()]
    };
    fs.writeFileSync(cacheFile, JSON.stringify(payload), "utf8");
  } catch (err) {
    // Cache failures should not prevent the topology service from working.
  }
}

function parseName(fileName, circuitName) {
  const stem = fileName.replace(/\.xml$/i, "");
  const match = stem.match(/^(.*?变电站)(.*)$/);
  const fullStationName = match ? match[1] : stem.split(/F\d+/)[0] || "未分组";
  const parsedLineName = match ? match[2] : "";
  const lineName = parsedLineName || circuitName || stem;
  const hasAreaPrefix = !!match && fullStationName.length > 4;
  const district = hasAreaPrefix ? fullStationName.slice(0, 2) : "其他";
  const stationName =
    hasAreaPrefix
      ? fullStationName.slice(2)
      : fullStationName;
  const feederNo = (lineName.match(/F(\d+)/) || [])[1] || "";
  return {
    stationName,
    fullStationName,
    stationLabel: district !== "其他" ? `${district}/${stationName}` : stationName,
    lineName,
    district,
    feederNo
  };
}

function connectivityNodeKey(value) {
  const text = String(value || "");
  if (/^[1-9]\d{0,15}$/.test(text)) {
    const numeric = Number(text);
    if (Number.isSafeInteger(numeric)) return numeric;
  }
  return text;
}

function ownString(value) {
  const text = String(value || "");
  return text ? Buffer.from(text, "utf8").toString("utf8") : "";
}
//创建馈线索引
function createLineIndex(xmlDir, options = {}) {
  const files = walkXml(xmlDir);
  const cacheFile = options.cacheFile === false ? "" : (options.cacheFile || defaultIndexCacheFile(xmlDir));
  const signature = cacheFile ? xmlSignature(files) : "";
  const cached = cacheFile ? readCachedIndex(cacheFile, xmlDir, signature) : null;
  if (cached) return cached;

  const lines = [];
  const bySourceSubst = new Map();
  const bySubstation = new Map();
  const byConnectivityNode = new Map();
  const connectivityNodesByFile = new Map();

  function addSharedNode(relativePath, cn) {
    if (!connectivityNodesByFile.has(relativePath)) {
      connectivityNodesByFile.set(relativePath, []);
    }
    const nodes = connectivityNodesByFile.get(relativePath);
    if (nodes[nodes.length - 1] !== cn && !nodes.includes(cn)) nodes.push(cn);
  }

  for (const filePath of files) {
    try {
      const meta = parseCimMeta(filePath);
      const circuit = meta.circuit || {};
      const relativePath = path.relative(xmlDir, filePath).replace(/\\/g, "/");
      const parsed = parseName(meta.fileName, circuit.name);
      const circuitName = ownString(circuit.name || parsed.lineName);
      const stationName = ownString(parsed.stationName);
      const fullStationName = ownString(parsed.fullStationName || parsed.stationName);
      const stationLabel = ownString(parsed.stationLabel || stationName);
      const lineName = circuitName || ownString(parsed.lineName);
      const line = {
        id: ownString(circuit.id) || relativePath,
        fileName: ownString(meta.fileName),
        relativePath,
        circuitName,
        circuitMrid: ownString(circuit.mrid),
        sourceSubst: ownString(circuit.sourceSubst),
        sourceBreaker: ownString(circuit.sourceBreaker),
        stationName,
        fullStationName,
        stationLabel,
        lineName,
        displayName: ownString(`${stationName}${lineName}`),
        fullDisplayName: ownString(`${fullStationName}${lineName}`),
        district: ownString(parsed.district),
        feederNo: ownString(parsed.feederNo),
        substationIds: meta.substations.map((item) => ownString(item.id)),
        substationNames: meta.substations.map((item) => ownString(item.name)).filter(Boolean),
        substationCount: meta.substations.length,
        connectivityNodeCount: meta.connectivityNodeIds.length
      };
      lines.push(line);
      if (line.sourceSubst) {
        if (!bySourceSubst.has(line.sourceSubst)) bySourceSubst.set(line.sourceSubst, []);
        bySourceSubst.get(line.sourceSubst).push(line.relativePath);
      }
      for (const substationId of line.substationIds) {
        if (!bySubstation.has(substationId)) bySubstation.set(substationId, []);
        bySubstation.get(substationId).push(line.relativePath);
      }
      for (const rawCn of meta.connectivityNodeIds) {
        const cn = connectivityNodeKey(rawCn);
        const existing = byConnectivityNode.get(cn);
        if (!existing) {
          byConnectivityNode.set(cn, line.relativePath);
          continue;
        }
        if (typeof existing === "string") {
          if (existing === line.relativePath) continue;
          const sharedFiles = [existing, line.relativePath];
          byConnectivityNode.set(cn, sharedFiles);
          addSharedNode(existing, cn);
          addSharedNode(line.relativePath, cn);
          continue;
        }
        if (!existing.includes(line.relativePath)) {
          existing.push(line.relativePath);
          addSharedNode(line.relativePath, cn);
        }
      }
    } catch (err) {
      lines.push({
        id: path.relative(xmlDir, filePath).replace(/\\/g, "/"),
        fileName: path.basename(filePath),
        relativePath: path.relative(xmlDir, filePath).replace(/\\/g, "/"),
        error: err.message,
        stationName: "解析失败",
        lineName: path.basename(filePath),
        displayName: path.basename(filePath),
        substationIds: [],
        substationNames: [],
        substationCount: 0
      });
    }
  }

  for (const [cn, filesForNode] of byConnectivityNode) {
    if (typeof filesForNode === "string") byConnectivityNode.delete(cn);
  }

  lines.sort((a, b) => a.displayName.localeCompare(b.displayName, "zh-Hans-CN"));
  const map = {};
  for (const line of lines) map[line.relativePath] = line;

  const result = {
    generatedAt: new Date().toISOString(),
    xmlDir,
    count: lines.length,
    lines,
    map,
    bySourceSubst: Object.fromEntries(bySourceSubst),
    bySubstation: Object.fromEntries(bySubstation)
  };
  attachHiddenMaps(result, byConnectivityNode, connectivityNodesByFile);
  if (cacheFile) writeCachedIndex(cacheFile, xmlDir, signature, result);
  return result;
}
//根据条件查找文件
function resolveIndexedFile(xmlDir, index, fileParam) {
  const normalized = String(fileParam).replace(/\\/g, "/");
  const line = index.map[normalized] || index.lines.find((item) => item.id === normalized);
  if (!line) return null;
  const resolved = path.normalize(path.join(xmlDir, line.relativePath));
  if (!resolved.startsWith(path.normalize(xmlDir))) return null;
  return resolved;
}

module.exports = {
  connectivityNodeKey,
  createLineIndex,
  resolveIndexedFile,
  walkXml
};
