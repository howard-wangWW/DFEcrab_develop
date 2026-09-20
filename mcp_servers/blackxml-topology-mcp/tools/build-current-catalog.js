#!/usr/bin/env node
const path = require("path");

const { parseCimFile } = require("../src/cimParser");
const { createLineIndex } = require("../src/indexer");
const { loadSwitchCurrent, getCurrentForEquipment } = require("../src/switchCurrent");
const { switchDisplayLabel } = require("../src/switchOrder");
const { replaceCurrentCatalog } = require("../src/currentCatalog");
const { DATA_ROOT, XML_DIR, CURRENT_DIRS } = require("../src/dataPaths");

const SWITCH_TAGS = new Set(["Breaker", "LoadBreakSwitch", "Disconnector", "Fuse"]);

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

function addUnique(set, value) {
  const text = String(value || "").trim();
  if (text) set.add(text);
}

function main() {
  const args = parseArgs(process.argv);
  const quiet = !!args.quiet;
  const index = createLineIndex(XML_DIR);
  const currentData = loadSwitchCurrent(CURRENT_DIRS);
  if (!currentData.byRawId.size) {
    throw new Error(currentData.summary.error || "No switch current rows were loaded.");
  }
  const equipmentMetadata = new Map();
  const startedAt = Date.now();
  const validLines = index.lines.filter((line) => !line.error);

  for (let lineIndex = 0; lineIndex < validLines.length; lineIndex += 1) {
    const line = validLines[lineIndex];
    const model = parseCimFile(path.join(XML_DIR, line.relativePath), { includeTerminals: false });
    for (const item of model.equipment.values()) {
      if (!SWITCH_TAGS.has(item.tag)) continue;
      const current = getCurrentForEquipment(item, currentData);
      if (!current) continue;
      const cabinetItem = model.substations.get(item.container);
      const priority = line.sourceBreaker === item.id ? 2 : 1;
      let meta = equipmentMetadata.get(current.rawId);
      if (!meta) {
        meta = {
          priority: 0,
          feederIds: new Set(),
          feederNames: new Set(),
          stationNames: new Set(),
          files: new Set()
        };
        equipmentMetadata.set(current.rawId, meta);
      }
      addUnique(meta.feederIds, line.id || (line.circuitMrid ? `CIRCUIT_${line.circuitMrid}` : ""));
      addUnique(meta.feederNames, line.fullDisplayName || line.displayName || line.lineName);
      addUnique(meta.stationNames, line.fullStationName || line.stationName);
      addUnique(meta.files, line.relativePath);
      if (priority >= meta.priority) {
        meta.priority = priority;
        meta.switchId = item.id;
        meta.mrid = item.mrid || "";
        meta.tag = item.tag;
        meta.switchName = switchDisplayLabel(item, item.id);
        meta.dispatchNumber = item.dispatchNumber || "";
        meta.cabinet = cabinetItem ? cabinetItem.name || "" : "";
        meta.station = line.fullStationName || line.stationName || "";
        meta.feederId = line.id || (line.circuitMrid ? `CIRCUIT_${line.circuitMrid}` : "");
        meta.feederName = line.fullDisplayName || line.displayName || line.lineName || "";
        meta.file = line.relativePath;
      }
    }
    const done = lineIndex + 1;
    if (!quiet && (done === validLines.length || done % 250 === 0)) {
      console.log(`[${done}/${validLines.length}] matched-current-ids=${equipmentMetadata.size}`);
    }
  }

  const rows = [...currentData.byRawId.entries()].map(([rawId, current]) => {
    const meta = equipmentMetadata.get(rawId);
    return {
      rawId,
      switchId: meta && meta.switchId,
      mrid: meta && meta.mrid,
      tag: meta && meta.tag,
      switchName: meta && meta.switchName,
      dispatchNumber: meta && meta.dispatchNumber,
      cabinet: meta && meta.cabinet,
      station: meta && meta.station,
      feederId: meta && meta.feederId,
      feederName: meta && meta.feederName,
      file: meta && meta.file,
      matchedXml: !!meta,
      currentAmp: current.amp,
      currentDisplay: current.display,
      ia: current.ia,
      ib: current.ib,
      ic: current.ic,
      i0: current.i0,
      currentFile: current.fileName,
      currentTimestamp: current.timestamp,
      feederIds: meta ? [...meta.feederIds] : [],
      feederNames: meta ? [...meta.feederNames] : [],
      stationNames: meta ? [...meta.stationNames] : [],
      files: meta ? [...meta.files] : []
    };
  });
  const selectedFile = (currentData.summary.currentFiles || []).find((item) => item.selected) || null;
  const metadata = {
    builtAt: new Date().toISOString(),
    elapsedMs: Date.now() - startedAt,
    xmlFileCount: index.count,
    indexGeneratedAt: index.generatedAt,
    switchCurrentVersion: currentData.summary.version,
    switchCurrentFile: selectedFile ? selectedFile.name : "",
    sourceCurrentCount: currentData.summary.currentCount,
    matchedXmlCount: equipmentMetadata.size,
    unmatchedXmlCount: currentData.summary.currentCount - equipmentMetadata.size
  };
  const result = replaceCurrentCatalog(DATA_ROOT, rows, metadata);
  console.log(JSON.stringify({
    dbPath: result.dbPath,
    currentCount: result.status.currentCount,
    matchedXmlCount: result.status.matchedXmlCount,
    unmatchedXmlCount: result.status.unmatchedXmlCount,
    maxAmp: result.status.maxAmp,
    elapsedMs: result.status.elapsedMs,
    builtAt: result.status.builtAt
  }, null, 2));
}

main();
