#!/usr/bin/env node
const path = require("path");

const { createLineIndex } = require("../src/indexer");
const { parseCimFile, mergeModelInto } = require("../src/cimParser");
const { loadSwitchStatus } = require("../src/switchStatus");
const { loadSwitchCurrent } = require("../src/switchCurrent");
const { createUserStore } = require("../src/userStore");
const { switchDisplayLabel } = require("../src/switchOrder");
const {
  buildAnalysisGraph,
  computeSwitchLoads,
  replaceSwitchLoads
} = require("../src/gridAnalytics");
const { DATA_ROOT, XML_DIR, STATUS_DIR, CURRENT_DIRS } = require("../src/dataPaths");


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

function collectComponentFiles(index, startRelativePath) {
  if (!(index.byConnectivityNode instanceof Map) || !(index.connectivityNodesByFile instanceof Map)) {
    return [startRelativePath];
  }
  const seen = new Set([startRelativePath]);
  const queue = [startRelativePath];
  for (let position = 0; position < queue.length; position += 1) {
    const relativePath = queue[position];
    for (const cn of index.connectivityNodesByFile.get(relativePath) || []) {
      for (const next of index.byConnectivityNode.get(cn) || []) {
        if (!next || seen.has(next)) continue;
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return queue;
}

function mergeComponentModels(relativePaths) {
  let merged = null;
  let terminalKeys = null;
  for (const relativePath of relativePaths) {
    const model = parseCimFile(path.join(XML_DIR, relativePath));
    if (!merged) {
      merged = model;
      terminalKeys = new Set(
        merged.terminals.map((terminal) => `${terminal.equipment}|${terminal.connectivityNode}`)
      );
    } else {
      mergeModelInto(merged, model, terminalKeys);
    }
  }
  return merged;
}

function lineForUserFeeder(index, feederId) {
  const normalized = String(feederId || "").trim();
  if (!normalized) return null;
  const rawMrid = normalized.replace(/^CIRCUIT_/, "");
  return index.lines.find((line) =>
    line.id === normalized || line.circuitMrid === rawMrid || `CIRCUIT_${line.circuitMrid}` === normalized
  ) || null;
}

function componentCandidates(index, feederRows, minUsers) {
  const statsByFeeder = new Map(feederRows.map((row) => [row.feederId, row]));
  const lineStats = feederRows
    .map((row) => ({ row, line: lineForUserFeeder(index, row.feederId) }))
    .filter((item) => item.line);
  const visitedFiles = new Set();
  const components = [];
  for (const item of lineStats) {
    if (visitedFiles.has(item.line.relativePath)) continue;
    const files = collectComponentFiles(index, item.line.relativePath);
    for (const file of files) visitedFiles.add(file);
    const componentLines = files.map((file) => index.map[file]).filter(Boolean);
    const feederIds = [...new Set(componentLines.map((line) => line.id).filter(Boolean))];
    const userRows = feederIds.map((id) => statsByFeeder.get(id)).filter(Boolean);
    const usersTotal = userRows.reduce((sum, row) => sum + Number(row.total || 0), 0);
    if (usersTotal < minUsers) continue;
    const primary = componentLines
      .slice()
      .sort((left, right) => {
        const leftUsers = Number((statsByFeeder.get(left.id) || {}).total || 0);
        const rightUsers = Number((statsByFeeder.get(right.id) || {}).total || 0);
        return rightUsers - leftUsers || left.relativePath.localeCompare(right.relativePath, "zh-Hans-CN");
      })[0] || item.line;
    components.push({ files, lines: componentLines, primary, usersTotal, feederIds });
  }
  return components.sort((left, right) => right.usersTotal - left.usersTotal);
}

function main() {
  const args = parseArgs(process.argv);
  const minUsers = Math.max(1, Math.floor(Number(args["min-users"]) || 2000));
  const maxComponents = Math.max(0, Math.floor(Number(args["max-components"]) || 0));
  const quiet = !!args.quiet;
  const index = createLineIndex(XML_DIR);
  const userStore = createUserStore(DATA_ROOT);
  const feederStats = userStore.feederUserCounts({ minUsers: 1, limit: 20000 });
  if (feederStats.truncated) throw new Error("Feeder user statistics were truncated; raise the internal limit.");
  let components = componentCandidates(index, feederStats.rows, minUsers);
  const totalComponents = components.length;
  if (maxComponents) components = components.slice(0, maxComponents);

  const switchStatus = loadSwitchStatus(STATUS_DIR);
  const switchCurrent = loadSwitchCurrent(CURRENT_DIRS);
  const rows = [];
  const startedAt = Date.now();
  for (let componentIndex = 0; componentIndex < components.length; componentIndex += 1) {
    const component = components[componentIndex];
    const model = mergeComponentModels(component.files);
    const graph = buildAnalysisGraph(model, switchStatus, switchCurrent);
    const transformerCounts = userStore.transformerUserCounts(graph.transformers.map((item) => item.id));
    const loads = computeSwitchLoads(graph, graph.initialSwitchState, transformerCounts);
    const sourceFeeders = graph.sources.map((source) => source.label).filter(Boolean);
    const sourceLineByBreaker = new Map(
      component.lines
        .filter((line) => line.sourceBreaker)
        .map((line) => [line.sourceBreaker, line])
    );
    for (const item of graph.switches) {
      const load = loads[item.id];
      if (!load || load.total < minUsers) continue;
      const current = graph.switchCurrentById[item.id];
      // A connected component can contain many feeder XMLs. Source breakers have
      // an unambiguous owning Circuit, so do not label every source as the
      // component's highest-user feeder.
      const owningLine = sourceLineByBreaker.get(item.id) || component.primary;
      rows.push({
        switchId: item.id,
        switchName: switchDisplayLabel(item, item.id),
        cabinet: graph.cabinetByEquipment[item.id] || "",
        station: owningLine.fullStationName || owningLine.stationName || "",
        feederId: owningLine.id || `CIRCUIT_${owningLine.circuitMrid}`,
        feederName: owningLine.fullDisplayName || owningLine.displayName || owningLine.lineName,
        file: owningLine.relativePath,
        closed: graph.initialSwitchState[item.id] !== false,
        currentAmp: current ? current.amp : null,
        currentDisplay: current ? current.display : "",
        transformerCount: load.transformers,
        usersTotal: load.total,
        usersZY: load.ZY,
        usersDY: load.DY,
        sourceFeeders
      });
    }
    const done = componentIndex + 1;
    if (!quiet) {
      console.log(`[${done}/${components.length}] ${component.primary.fullDisplayName || component.primary.displayName} files=${component.files.length} users=${component.usersTotal} matches=${rows.length}`);
    }
  }

  const userStatus = userStore.status();
  const metadata = {
    builtAt: new Date().toISOString(),
    elapsedMs: Date.now() - startedAt,
    minCandidateUsers: minUsers,
    complete: !maxComponents || maxComponents >= totalComponents,
    componentCount: totalComponents,
    processedComponents: components.length,
    xmlFileCount: index.count,
    indexGeneratedAt: index.generatedAt,
    userDatasets: userStatus.datasets.map((item) => ({
      type: item.type,
      datasetId: item.datasetId,
      indexedRows: item.indexedRows,
      importedAt: item.importedAt
    })),
    feedersWithUsers: feederStats.totalFeeders,
    topFeedersByUsers: feederStats.rows.slice(0, 100),
    switchStatusVersion: switchStatus.summary.version,
    switchCurrentVersion: switchCurrent.summary.version,
    switchCurrentFile: (switchCurrent.summary.currentFiles.find((item) => item.selected) || {}).name || ""
  };
  const result = replaceSwitchLoads(DATA_ROOT, rows, metadata);
  console.log(JSON.stringify({
    dbPath: result.dbPath,
    rows: result.status.rowCount,
    maxUsers: result.status.maxUsers,
    complete: result.status.complete,
    componentCount: result.status.componentCount,
    processedComponents: result.status.processedComponents,
    elapsedMs: result.status.elapsedMs,
    builtAt: result.status.builtAt
  }, null, 2));
}

main();
