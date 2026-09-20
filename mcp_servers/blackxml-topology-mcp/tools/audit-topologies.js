const path = require("path");
const { performance } = require("perf_hooks");
const { createLineIndex } = require("../src/indexer");
const { parseCimFile } = require("../src/cimParser");
const { buildTopology } = require("../src/topology");
const { renderSvg } = require("../src/svgRenderer");
const { loadSwitchStatus } = require("../src/switchStatus");

const ROOT = path.resolve(__dirname, "..");
const XML_DIR = path.join(ROOT, "BLACKXML");
const STATUS_DIR = path.join(ROOT, "\u5f00\u5173\u72b6\u6001");

function parseLimit(argv) {
  const index = argv.indexOf("--limit");
  if (index < 0) return Infinity;
  const value = Number(argv[index + 1]);
  return Number.isFinite(value) && value > 0 ? value : Infinity;
}

function parseSampleLimit(argv) {
  const index = argv.indexOf("--samples");
  if (index < 0) return 12;
  const value = Number(argv[index + 1]);
  return Number.isFinite(value) && value >= 0 ? value : 12;
}

const SWITCH_TAGS = new Set(["Breaker", "LoadBreakSwitch", "Disconnector", "GroundDisconnector", "Fuse"]);

function normalizedName(value) {
  return String(value || "").trim().toUpperCase().replace(/\s+/g, "");
}

function isHiddenCabinetSwitch(item) {
  if (!item || !SWITCH_TAGS.has(item.tag)) return false;
  const names = [item.dispatchNumber, item.name, item.mrid, item.id].map(normalizedName).filter(Boolean);
  if (item.tag === "GroundDisconnector") return true;
  if (item.tag === "Disconnector" && item.container && item.container.startsWith("SUBST_")) return true;
  if (item.tag === "Disconnector" && names.some((name) => /^\d{3,4}$/.test(name) && name.endsWith("4"))) return true;
  return false;
}

function isVisibleSwitch(item) {
  return !!item && SWITCH_TAGS.has(item.tag) && !isHiddenCabinetSwitch(item);
}

function inlineSymbolSize(item) {
  if (item.tag === "Disconnector" || item.tag === "GroundDisconnector") return { width: 42, height: 16 };
  return { width: 42, height: 14 };
}

function switchObstacle(item, topology) {
  const pos = topology.layout.devicePositions[item.id];
  if (!pos) return null;
  const node = item.layoutNodeId && topology.layout.nodes[item.layoutNodeId];
  const inline = !!(node && node.kind === "inline-switch");
  const size = inline ? inlineSymbolSize(item) : { width: 24, height: 46 };
  const x = inline ? pos.x : pos.x - 4;
  const y = inline ? pos.y : pos.y - 2;
  return {
    eqId: item.id,
    name: item.dispatchNumber || item.name || item.id,
    x1: x - 4,
    y1: y - 4,
    x2: x + size.width + 4,
    y2: y + size.height + 4
  };
}

function parseAttrs(tag) {
  const attrs = {};
  for (const match of tag.matchAll(/\s([:\w-]+)="([^"]*)"/g)) {
    attrs[match[1]] = match[2];
  }
  return attrs;
}

function parsePoints(value) {
  return String(value || "")
    .trim()
    .split(/\s+/)
    .map((pair) => {
      const [x, y] = pair.split(",").map(Number);
      return { x, y };
    })
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
}

function parsePolylines(svg) {
  const polylines = [];
  for (const match of String(svg || "").matchAll(/<polyline\b[^>]*>/g)) {
    const attrs = parseAttrs(match[0]);
    if (attrs["data-kind"] && attrs["data-kind"] !== "line") continue;
    polylines.push({
      id: attrs.id || "",
      fromEquipment: attrs["data-from-equipment"] || "",
      toEquipment: attrs["data-to-equipment"] || "",
      equipment: attrs["data-equipment"] || "",
      points: parsePoints(attrs.points)
    });
  }
  return polylines;
}

function segmentIntersectsBox(a, b, box) {
  if (Math.abs(a.y - b.y) < 0.1) {
    const y = a.y;
    if (y < box.y1 || y > box.y2) return false;
    return Math.max(Math.min(a.x, b.x), box.x1) < Math.min(Math.max(a.x, b.x), box.x2) - 0.1;
  }
  if (Math.abs(a.x - b.x) < 0.1) {
    const x = a.x;
    if (x < box.x1 || x > box.x2) return false;
    return Math.max(Math.min(a.y, b.y), box.y1) < Math.min(Math.max(a.y, b.y), box.y2) - 0.1;
  }
  return false;
}

function hasSwitchCrossing(polyline, obstacle) {
  const endpointEq = new Set(
    [polyline.fromEquipment, polyline.toEquipment, ...String(polyline.equipment || "").split(",")]
      .map((value) => value.trim())
      .filter(Boolean)
  );
  if (endpointEq.has(obstacle.eqId)) return false;
  for (let index = 0; index < polyline.points.length - 1; index++) {
    if (segmentIntersectsBox(polyline.points[index], polyline.points[index + 1], obstacle)) return true;
  }
  return false;
}

function visibleSwitch(item, topology) {
  if (!item || !isVisibleSwitch(item)) return null;
  if (!topology.layout.devicePositions[item.id]) return null;
  return item;
}

function visibleSwitchLink(wire, topology) {
  if (!wire || !["ACLineSegment", "Jumper"].includes(wire.tag)) return false;
  const from = wire.from;
  const to = wire.to;
  if (!from || !to || !from.eqId || !to.eqId) return false;
  if (!from.nodeId || from.nodeId !== to.nodeId || !from.nodeId.startsWith("site:")) return false;
  if (from.port !== to.port || !["top", "bottom"].includes(from.port)) return false;
  const equipment = topology.graph.equipmentById || {};
  return !!(visibleSwitch(equipment[from.eqId], topology) && visibleSwitch(equipment[to.eqId], topology));
}

function sameCabinetTransformerTap(wire, topology) {
  if (!wire || wire.tag !== "ConnectivityLead") return false;
  const from = wire.from;
  const to = wire.to;
  if (!from || !to || !from.nodeId || from.nodeId !== to.nodeId || !from.nodeId.startsWith("site:")) return false;
  const equipment = topology.graph.equipmentById || {};
  const pairs = [
    [from, to],
    [to, from]
  ];
  return pairs.some(([a, b]) => {
    const switchItem = equipment[a.eqId];
    const transformer = equipment[b.eqId];
    return a.port === "bottom" && b.port === "top" && visibleSwitch(switchItem, topology) && transformer && transformer.tag === "PowerTransformer";
  });
}

function auditGeometry(topology, sampleLimit, samples) {
  const internalSwitchLinks = [];
  const sameCabinetTapJunctions = [];
  const switchCrossings = [];

  for (const wire of topology.layout.wires || []) {
    if (visibleSwitchLink(wire, topology)) internalSwitchLinks.push(wire);
    if (sameCabinetTransformerTap(wire, topology)) sameCabinetTapJunctions.push(wire);
  }

  const obstacles = (topology.graph.switches || [])
    .map((item) => visibleSwitch(item, topology))
    .filter(Boolean)
    .map((item) => switchObstacle(item, topology))
    .filter(Boolean);
  const polylines = parsePolylines(topology.svg || renderSvg(topology));

  for (const polyline of polylines) {
    for (const obstacle of obstacles) {
      if (!hasSwitchCrossing(polyline, obstacle)) continue;
      switchCrossings.push({ polyline, obstacle });
      if (samples.length < sampleLimit) {
        samples.push({
          line: topology.line.relativePath || topology.line.name || topology.line.id,
          kind: "switchCrossing",
          wire: polyline.id,
          switch: obstacle.name,
          switchId: obstacle.eqId
        });
      }
      break;
    }
  }

  for (const wire of internalSwitchLinks.slice(0, Math.max(0, sampleLimit - samples.length))) {
    samples.push({
      line: topology.line.relativePath || topology.line.name || topology.line.id,
      kind: "internalSwitchLink",
      wire: wire.id,
      from: wire.from.eqId,
      to: wire.to.eqId
    });
  }
  for (const wire of sameCabinetTapJunctions.slice(0, Math.max(0, sampleLimit - samples.length))) {
    samples.push({
      line: topology.line.relativePath || topology.line.name || topology.line.id,
      kind: "sameCabinetTransformerTap",
      wire: wire.id,
      from: wire.from.eqId,
      to: wire.to.eqId
    });
  }

  return {
    internalSwitchLinks: internalSwitchLinks.length,
    sameCabinetTapJunctions: sameCabinetTapJunctions.length,
    switchCrossings: switchCrossings.length
  };
}

function main() {
  const started = performance.now();
  const limit = parseLimit(process.argv);
  const sampleLimit = parseSampleLimit(process.argv);
  const index = createLineIndex(XML_DIR);
  const switchStatus = loadSwitchStatus(STATUS_DIR);
  const lines = index.lines.slice(0, limit);
  const failures = [];
  const geometrySamples = [];
  let equipment = 0;
  let switches = 0;
  let statusApplied = 0;
  let sourceDefaults = 0;
  let unreportedDefaults = 0;
  let wires = 0;
  let invalidWireEndpoints = 0;
  let missingSourceBreakers = 0;
  let internalSwitchLinks = 0;
  let sameCabinetTapJunctions = 0;
  let switchCrossings = 0;

  for (const [position, line] of lines.entries()) {
    try {
      const model = parseCimFile(path.join(XML_DIR, line.relativePath));
      const topology = buildTopology(model, line, {
        includedFiles: [line.relativePath],
        relatedFiles: [],
        maxNodes: 900,
        switchStatus
      });
      equipment += topology.stats.equipment;
      switches += topology.stats.switches;
      statusApplied += Object.keys(topology.graph.switchStatusById || {}).length;
      const sourceIds = new Set(topology.graph.sourceBreakers || []);
      for (const item of topology.graph.switches || []) {
        if (topology.graph.switchStatusById[item.id]) continue;
        if (sourceIds.has(item.id)) sourceDefaults++;
        else unreportedDefaults++;
      }
      wires += (topology.layout.wires || []).length;
      if (topology.graph.sourceBreaker && !topology.graph.equipmentById[topology.graph.sourceBreaker]) {
        missingSourceBreakers++;
      }
      for (const wire of topology.layout.wires || []) {
        for (const endpoint of [wire.from, wire.to]) {
          if (!endpoint || !Number.isFinite(endpoint.x) || !Number.isFinite(endpoint.y)) {
            invalidWireEndpoints++;
          }
        }
      }
      topology.svg = renderSvg(topology);
      const geometry = auditGeometry(topology, sampleLimit, geometrySamples);
      internalSwitchLinks += geometry.internalSwitchLinks;
      sameCabinetTapJunctions += geometry.sameCabinetTapJunctions;
      switchCrossings += geometry.switchCrossings;
    } catch (err) {
      failures.push({ file: line.relativePath, error: err.message });
    }
    if ((position + 1) % 1000 === 0) {
      console.log(`Audited ${position + 1}/${lines.length}`);
    }
  }

  console.log(
    JSON.stringify(
      {
        files: lines.length,
        failures,
        equipment,
        switches,
        statusApplied,
        statusCoverage: switches ? statusApplied / switches : 0,
        sourceDefaults,
        unreportedDefaults,
        wires,
        invalidWireEndpoints,
        missingSourceBreakers,
        geometry: {
          internalSwitchLinks,
          sameCabinetTapJunctions,
          switchCrossings,
          samples: geometrySamples
        },
        statusVersion: switchStatus.summary.version,
        seconds: (performance.now() - started) / 1000
      },
      null,
      2
    )
  );
  if (failures.length || invalidWireEndpoints || missingSourceBreakers) process.exitCode = 1;
}

main();
