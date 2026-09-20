//把电网 XML 文件变成既能让 AI 读懂、又能让人看图的拓扑结构。
//用多源 BFS 把电网的"图模+实时状态+电流"统一起来——既算出每个设备的带电状态、电源归属、
// 是否合环，又用走廊压缩和边折叠让图清爽可读，最终同时输出"AI 能读的文字结构 + 人能看的 SVG 图
const fs = require("fs");
const path = require("path");
const { parseCimFile, mergeModels, mergeModelInto } = require("./cimParser");
const { connectivityNodeKey } = require("./indexer");
const { renderSvg } = require("./svgRenderer");
const { getStatusForEquipment, serializableStatusSummary } = require("./switchStatus");
const { getCurrentForEquipment, serializableCurrentSummary } = require("./switchCurrent");
const { compareSwitchOrder, switchDisplayLabel } = require("./switchOrder");

const SWITCH_TAGS = new Set(["Breaker", "LoadBreakSwitch", "Disconnector", "GroundDisconnector", "Fuse"]);
const PASS_THROUGH_TAGS = new Set(["ACLineSegment", "BusbarSection", "Jumper", "EnergyConsumer"]);
const AUTO_CORRIDOR_EQUIPMENT_LIMIT = 1800;
const AUTO_CORRIDOR_NODE_LIMIT = 180;
const AUTO_CORRIDOR_MIN_ASPECT = 0.22;
const AUTO_CORRIDOR_MIN_ASPECT_NODES = 40;
const SOURCE_COLORS = [
  "rgb(0,255,0)",
  "rgb(0,210,255)",
  "rgb(255,0,255)",
  "rgb(255,220,0)",
  "rgb(255,120,0)",
  "rgb(150,255,90)",
  "rgb(255,90,150)",
  "rgb(70,140,255)",
  "rgb(0,255,190)",
  "rgb(210,120,255)",
  "rgb(255,180,70)",
  "rgb(120,255,255)"
];

function sourceColorAt(index) {
  if (index < SOURCE_COLORS.length) return SOURCE_COLORS[index];
  const hue = Math.round((index * 137.508 + 17) % 360);
  return `hsl(${hue},100%,60%)`;
}

function cleanId(id) {
  return String(id || "").replace(/^(SUBST|SWITCH|SEG|BUSBAR|TRANS|WINDING)_/, "");
}

function makeLineInfo(index, relativePath) {
  return (index && index.map && index.map[relativePath]) || {
    relativePath,
    displayName: path.basename(relativePath),
    lineName: path.basename(relativePath)
  };
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function collectConnectivityNodeIds(models) {
  const ids = new Set();
  for (const model of models) {
    for (const terminal of model.terminals || []) {
      if (terminal.connectivityNode) ids.add(terminal.connectivityNode);
    }
  }
  return ids;
}

function connectivityPatterns(cnIds) {
  const ids = [...cnIds].filter(Boolean);
  const patterns = [];
  const chunkSize = 220;
  for (let i = 0; i < ids.length; i += chunkSize) {
    const body = ids.slice(i, i + chunkSize).map(escapeRegExp).join("|");
    if (body) patterns.push(new RegExp(`(?:rdf:resource="#(?:${body})"|rdf:ID="(?:${body})")`));
  }
  return patterns;
}

function findFilesByConnectivityNodes({ xmlDir, index, cnIds, selected, maxFiles }) {
  if (!index || !maxFiles) return [];
  if (index.byConnectivityNode instanceof Map) {
    const found = [];
    const seen = new Set();
    for (const cn of cnIds || []) {
      for (const relativePath of index.byConnectivityNode.get(connectivityNodeKey(cn)) || []) {
        if (!relativePath || selected.has(relativePath) || seen.has(relativePath)) continue;
        seen.add(relativePath);
        found.push({ relativePath, reason: "shared-connectivity-node" });
        if (found.length >= maxFiles) return found;
      }
    }
    return found;
  }
  const patterns = connectivityPatterns(cnIds);
  if (!patterns.length) return [];
  const found = [];
  for (const line of index.lines || []) {
    if (!line || line.error || selected.has(line.relativePath)) continue;
    const filePath = path.join(xmlDir, line.relativePath);
    let xml = "";
    try {
      xml = fs.readFileSync(filePath, "utf8");
    } catch (err) {
      continue;
    }
    if (patterns.some((pattern) => pattern.test(xml))) {
      found.push({ relativePath: line.relativePath, reason: "shared-connectivity-node" });
      if (found.length >= maxFiles) break;
    }
  }
  return found;
}

function findRelatedFiles({ index, selectedLine, relatedMode, maxRelated, selected }) {
  if (!index || relatedMode === "primary") return [];
  const seen = new Set(selected || [selectedLine.relativePath]);
  const related = [];
  const push = (relativePath, reason) => {
    if (!relativePath || seen.has(relativePath)) return;
    seen.add(relativePath);
    related.push({ relativePath, reason });
  };

  for (const substationId of selectedLine.substationIds || []) {
    if (substationId === selectedLine.sourceSubst) continue;
    for (const relativePath of index.bySubstation[substationId] || []) {
      push(relativePath, "shared-substation");
      if (related.length >= maxRelated) break;
    }
    if (related.length >= maxRelated) break;
  }

  if ((relatedMode === "sameSource" || relatedMode === "wide") && selectedLine.sourceSubst) {
    const same = (index.bySourceSubst[selectedLine.sourceSubst] || [])
      .filter((relativePath) => relativePath !== selectedLine.relativePath)
      .map((relativePath) => index.map[relativePath])
      .filter(Boolean)
      .sort((a, b) => feederDistance(selectedLine, a) - feederDistance(selectedLine, b));
    for (const line of same.slice(0, Math.max(0, maxRelated - related.length))) {
      push(line.relativePath, "same-source");
    }
  }

  return related.slice(0, maxRelated);
}

function feederDistance(a, b) {
  const an = Number(a.feederNo || 0);
  const bn = Number(b.feederNo || 0);
  if (an && bn) return Math.abs(an - bn);
  return a.displayName.localeCompare(b.displayName, "zh-Hans-CN");
}

function collectConnectedFiles(index, startRelativePath) {
  if (
    !index ||
    !(index.byConnectivityNode instanceof Map) ||
    !(index.connectivityNodesByFile instanceof Map)
  ) {
    return [startRelativePath];
  }
  const seen = new Set([startRelativePath]);
  const queue = [startRelativePath];
  for (let position = 0; position < queue.length; position++) {
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

function collectAutoCorridorPlan({
  index,
  selectedLine,
  primaryRelativePaths,
  sourceConnectivityNodes,
  maxFiles
}) {
  if (
    !index ||
    !(index.byConnectivityNode instanceof Map) ||
    !(index.connectivityNodesByFile instanceof Map)
  ) {
    return { primaryFiles: [], boundaryFiles: [] };
  }

  const primary = new Set(primaryRelativePaths || []);
  const queued = [...primary];
  const primaryFiles = [];
  const boundaryScores = new Map();
  const sourceBreaker = String(selectedLine && selectedLine.sourceBreaker || "");
  const sourceNodes = new Set(
    [...(sourceConnectivityNodes || [])].map(connectivityNodeKey)
  );

  for (let position = 0; position < queued.length; position++) {
    const relativePath = queued[position];
    const neighborScores = new Map();
    for (const cn of index.connectivityNodesByFile.get(relativePath) || []) {
      const key = connectivityNodeKey(cn);
      // XML variants of the same source breaker all meet at the station-side
      // feeder node. Expanding there mixes independent feeder models together.
      if (sourceNodes.has(key)) continue;
      for (const next of index.byConnectivityNode.get(key) || []) {
        if (!next || primary.has(next)) continue;
        const line = index.map && index.map[next];
        if (!line || line.error) continue;
        neighborScores.set(next, (neighborScores.get(next) || 0) + 1);
      }
    }
    for (const [next, sharedNodeCount] of neighborScores) {
      const line = index.map && index.map[next];
      if (
        sourceBreaker &&
        line &&
        line.sourceBreaker === sourceBreaker
      ) {
        // One or two shared non-source nodes indicate a real continuation.
        // A large overlap is normally an older/superset XML view of the same
        // feeder and must not be merged as additional topology.
        if (sharedNodeCount <= 2) {
          primary.add(next);
          queued.push(next);
          primaryFiles.push({
            relativePath: next,
            reason: "same-feeder-continuation"
          });
        }
        continue;
      }
      boundaryScores.set(
        next,
        (boundaryScores.get(next) || 0) + sharedNodeCount
      );
    }
  }

  const remaining = Math.max(0, maxFiles - primaryFiles.length);
  const boundaryFiles = [...boundaryScores]
    .sort((a, b) => {
      const scoreDifference = b[1] - a[1];
      if (scoreDifference) return scoreDifference;
      const aName = index.map[a[0]] && index.map[a[0]].displayName || a[0];
      const bName = index.map[b[0]] && index.map[b[0]].displayName || b[0];
      return aName.localeCompare(bName, "zh-Hans-CN");
    })
    .slice(0, remaining)
    .map(([relativePath]) => ({
      relativePath,
      reason: "direct-feeder-boundary"
    }));

  return { primaryFiles, boundaryFiles };
}

function reduceModelToSourceCorridors(model, primaryFilePaths, selectedLine) {
  const equipment = new Map(
    [...model.equipment].filter(([, item]) => item.tag !== "TransformerWinding")
  );
  const normalizedTerminals = [];
  const eqToCn = new Map();
  const cnToEq = new Map();

  for (const terminal of model.terminals || []) {
    const eqId = model.windingToTransformer.get(terminal.equipment) || terminal.equipment;
    if (!equipment.has(eqId) || !terminal.connectivityNode) continue;
    normalizedTerminals.push({ equipment: eqId, connectivityNode: terminal.connectivityNode });
    if (!eqToCn.has(eqId)) eqToCn.set(eqId, new Set());
    eqToCn.get(eqId).add(terminal.connectivityNode);
    if (!cnToEq.has(terminal.connectivityNode)) cnToEq.set(terminal.connectivityNode, new Set());
    cnToEq.get(terminal.connectivityNode).add(eqId);
  }

  const sourceEntries = [];
  const seenSources = new Set();
  for (const circuit of model.circuits || []) {
    const sourceId = circuit.sourceBreaker;
    if (!sourceId || !equipment.has(sourceId) || seenSources.has(sourceId)) continue;
    seenSources.add(sourceId);
    const sourceItem = equipment.get(sourceId);
    sourceEntries.push({
      id: sourceId,
      owner: circuit.sourceSubst || sourceItem.container || sourceId
    });
  }
  const selectedSourceId =
    (selectedLine && selectedLine.sourceBreaker) ||
    (sourceEntries[0] && sourceEntries[0].id) ||
    "";
  const selectedSource =
    sourceEntries.find((source) => source.id === selectedSourceId) ||
    sourceEntries[0] ||
    null;
  const selectedOwner = selectedSource ? selectedSource.owner : "";
  const selectedReachableEquipment = new Set();
  const selectedReachableNodes = new Set();
  if (selectedSource && equipment.has(selectedSource.id)) {
    const reachableQueue = [{ type: "eq", id: selectedSource.id }];
    selectedReachableEquipment.add(selectedSource.id);
    for (let position = 0; position < reachableQueue.length; position++) {
      const current = reachableQueue[position];
      if (current.type === "eq") {
        const item = equipment.get(current.id);
        if (!item || item.tag === "GroundDisconnector") continue;
        for (const cn of eqToCn.get(current.id) || []) {
          if (selectedReachableNodes.has(cn)) continue;
          selectedReachableNodes.add(cn);
          reachableQueue.push({ type: "cn", id: cn });
        }
      } else {
        for (const eqId of cnToEq.get(current.id) || []) {
          if (selectedReachableEquipment.has(eqId)) continue;
          const item = equipment.get(eqId);
          if (!item || item.tag === "GroundDisconnector") continue;
          selectedReachableEquipment.add(eqId);
          reachableQueue.push({ type: "eq", id: eqId });
        }
      }
    }
  }

  const eqLabels = new Map();
  const cnLabels = new Map();
  const queue = [];
  for (const source of sourceEntries) {
    if (
      selectedSource &&
      source.owner === selectedOwner &&
      source.id !== selectedSource.id
    ) {
      continue;
    }
    const label = {
      owner: source.owner,
      sourceId: source.id,
      distance: 0,
      parentType: "",
      parentId: ""
    };
    if (!eqLabels.has(source.id)) {
      eqLabels.set(source.id, label);
      queue.push({ type: "eq", id: source.id });
    }
  }

  const collisions = [];
  const collisionKeys = new Set();
  function recordCollision(aType, aId, bType, bId, aLabel, bLabel) {
    if (!aLabel || !bLabel || aLabel.owner === bLabel.owner) return;
    if (
      selectedOwner &&
      aLabel.owner !== selectedOwner &&
      bLabel.owner !== selectedOwner
    ) {
      return;
    }
    const nodes = [`${aType}:${aId}`, `${bType}:${bId}`].sort();
    const owners = [aLabel.owner, bLabel.owner].sort();
    const key = `${nodes.join("|")}|${owners.join("|")}`;
    if (collisionKeys.has(key)) return;
    collisionKeys.add(key);
    collisions.push({ aType, aId, bType, bId });
  }

  function visit(nextType, nextId, currentType, currentId, currentLabel) {
    const labels = nextType === "eq" ? eqLabels : cnLabels;
    const existing = labels.get(nextId);
    if (!existing) {
      labels.set(nextId, {
        owner: currentLabel.owner,
        sourceId: currentLabel.sourceId,
        distance: currentLabel.distance + 1,
        parentType: currentType,
        parentId: currentId
      });
      queue.push({ type: nextType, id: nextId });
      return;
    }
    recordCollision(currentType, currentId, nextType, nextId, currentLabel, existing);
  }

  for (let position = 0; position < queue.length; position++) {
    const current = queue[position];
    const labels = current.type === "eq" ? eqLabels : cnLabels;
    const label = labels.get(current.id);
    if (!label) continue;
    if (current.type === "eq") {
      const item = equipment.get(current.id);
      if (!item || item.tag === "GroundDisconnector") continue;
      for (const cn of eqToCn.get(current.id) || []) {
        visit("cn", cn, "eq", current.id, label);
      }
    } else {
      for (const eqId of cnToEq.get(current.id) || []) {
        const item = equipment.get(eqId);
        if (!item || item.tag === "GroundDisconnector") continue;
        visit("eq", eqId, "cn", current.id, label);
      }
    }
  }

  const retainedEquipment = new Set();
  const primaryNormalized = new Set(
    (Array.isArray(primaryFilePaths) ? primaryFilePaths : [primaryFilePaths])
      .filter(Boolean)
      .map((file) => path.normalize(file).toLowerCase())
  );
  for (const item of equipment.values()) {
    if (
      (item.files || []).some(
        (file) => primaryNormalized.has(path.normalize(file).toLowerCase())
      ) &&
      (!selectedReachableEquipment.size || selectedReachableEquipment.has(item.id))
    ) {
      retainedEquipment.add(item.id);
    }
  }

  function retainPath(type, id) {
    const seen = new Set();
    while (type && id) {
      const key = `${type}:${id}`;
      if (seen.has(key)) break;
      seen.add(key);
      if (type === "eq") retainedEquipment.add(id);
      const label = (type === "eq" ? eqLabels : cnLabels).get(id);
      if (!label || !label.parentType || !label.parentId) break;
      type = label.parentType;
      id = label.parentId;
    }
  }

  for (const collision of collisions) {
    retainPath(collision.aType, collision.aId);
    retainPath(collision.bType, collision.bId);
  }

  if (selectedLine && selectedLine.sourceBreaker) {
    retainedEquipment.add(selectedLine.sourceBreaker);
  }

  const retainedContainers = new Set();
  for (const eqId of retainedEquipment) {
    const item = equipment.get(eqId);
    if (item && item.container) retainedContainers.add(item.container);
  }

  const reducedEquipment = new Map();
  for (const [id, item] of model.equipment) {
    const normalizedId = model.windingToTransformer.get(id) || id;
    if (retainedEquipment.has(normalizedId)) reducedEquipment.set(id, item);
  }
  const reducedTerminals = (model.terminals || []).filter((terminal) => {
    const normalizedId = model.windingToTransformer.get(terminal.equipment) || terminal.equipment;
    return retainedEquipment.has(normalizedId);
  });
  const reducedSubstations = new Map(
    [...model.substations].filter(([id]) => retainedContainers.has(id))
  );
  const reducedCircuits = (model.circuits || []).filter(
    (circuit) =>
      circuit.id === selectedLine.id ||
      retainedEquipment.has(circuit.sourceBreaker)
  );
  const reducedWindingMap = new Map(
    [...model.windingToTransformer].filter(([, transformerId]) =>
      retainedEquipment.has(transformerId)
    )
  );

  return {
    model: {
      ...model,
      circuits: reducedCircuits,
      substations: reducedSubstations,
      equipment: reducedEquipment,
      terminals: reducedTerminals,
      windingToTransformer: reducedWindingMap
    },
    corridorEquipment: retainedEquipment.size,
    sourceBoundaries: collisions.length
  };
}

function layoutNeedsCorridorReduction(topology) {
  if (!topology || !topology.layout) return false;
  const nodeCount = Object.keys(topology.layout.nodes || {}).length;
  const width = Number(topology.layout.width) || 0;
  const height = Number(topology.layout.height) || 0;
  const aspect = height > 0 ? width / height : 1;
  return (
    nodeCount > AUTO_CORRIDOR_NODE_LIMIT ||
    (nodeCount >= AUTO_CORRIDOR_MIN_ASPECT_NODES &&
      aspect < AUTO_CORRIDOR_MIN_ASPECT)
  );
}

function buildTopologyFromFile({ xmlDir, filePath, index, relatedMode = "auto", maxRelated = 64, maxNodes = 900, switchStatus = null, switchCurrent = null }) {
  const relativePath = path.relative(xmlDir, filePath).replace(/\\/g, "/");
  const selectedLine = makeLineInfo(index, relativePath);
  const selected = new Set([relativePath]);
  const relatedFiles = [];
  const models = [parseCimFile(filePath)];
  let streamedModel = null;
  let componentFileCount = 1;
  let corridorReduced = false;
  let corridorReason = "";
  let corridorEquipment = 0;
  let sourceBoundaries = 0;
  let autoBoundaryCount = 0;
  const primaryRelativePaths = [relativePath];

  const addRelatedFile = (item) => {
    if (!item || !item.relativePath || selected.has(item.relativePath) || relatedFiles.length >= maxRelated) return false;
    selected.add(item.relativePath);
    relatedFiles.push(item);
    models.push(parseCimFile(path.join(xmlDir, item.relativePath)));
    return true;
  };

  if (relatedMode === "auto") {
    const sameCircuitFiles = (index && index.lines || [])
      .filter(
        (line) =>
          line &&
          !line.error &&
          line.id === selectedLine.id &&
          line.relativePath !== relativePath
      )
      .map((line) => ({
        relativePath: line.relativePath,
        reason: "same-circuit"
      }));
    for (const item of sameCircuitFiles) {
      if (addRelatedFile(item)) primaryRelativePaths.push(item.relativePath);
    }

    const primaryLines = primaryRelativePaths
      .map((item) => index && index.map && index.map[item])
      .filter(Boolean);
    const primarySubstationCount = Math.max(
      0,
      ...primaryLines.map((line) => Number(line.substationCount || 0))
    );
    const primaryConnectivityCount = Math.max(
      0,
      ...primaryLines.map((line) => Number(line.connectivityNodeCount || 0))
    );
    const canonicalSourceFile = (index && index.lines || [])
      .filter(
        (line) =>
          line &&
          !line.error &&
          line.sourceBreaker &&
          line.sourceBreaker === selectedLine.sourceBreaker &&
          !selected.has(line.relativePath)
      )
      .sort((a, b) =>
        Number(b.substationCount || 0) - Number(a.substationCount || 0) ||
        Number(b.connectivityNodeCount || 0) - Number(a.connectivityNodeCount || 0) ||
        a.displayName.localeCompare(b.displayName, "zh-Hans-CN")
      )[0];
    if (
      canonicalSourceFile &&
      (
        primarySubstationCount <= 2 ||
        Number(canonicalSourceFile.substationCount || 0) >= primarySubstationCount * 1.5 ||
        Number(canonicalSourceFile.connectivityNodeCount || 0) >= primaryConnectivityCount * 1.5
      )
    ) {
      const item = {
        relativePath: canonicalSourceFile.relativePath,
        reason: "source-feeder-detail"
      };
      if (addRelatedFile(item)) primaryRelativePaths.push(item.relativePath);
    }

    const sourceConnectivityNodes = new Set();
    for (const model of models) {
      for (const terminal of model.terminals || []) {
        if (
          terminal.equipment === selectedLine.sourceBreaker &&
          terminal.connectivityNode
        ) {
          sourceConnectivityNodes.add(terminal.connectivityNode);
        }
      }
    }
    const plan = collectAutoCorridorPlan({
      index,
      selectedLine,
      primaryRelativePaths,
      sourceConnectivityNodes,
      maxFiles: Math.max(0, maxRelated - relatedFiles.length)
    });
    for (const item of plan.primaryFiles) {
      if (addRelatedFile(item)) primaryRelativePaths.push(item.relativePath);
    }
    for (const item of plan.boundaryFiles) addRelatedFile(item);
    autoBoundaryCount = relatedFiles.filter(
      (item) => item.reason === "direct-feeder-boundary"
    ).length;
    componentFileCount = collectConnectedFiles(index, relativePath).length;
  } else if (relatedMode !== "primary") {
    const componentFiles = collectConnectedFiles(index, relativePath);
    componentFileCount = componentFiles.length;
    if (componentFiles.length - 1 > maxRelated) {
      streamedModel = mergeModels(models);
      models.length = 0;
      const terminalKeys = new Set(
        streamedModel.terminals.map(
          (terminal) => `${terminal.equipment}|${terminal.connectivityNode}`
        )
      );
      for (const componentFile of componentFiles) {
        if (componentFile === relativePath) continue;
        selected.add(componentFile);
        relatedFiles.push({
          relativePath: componentFile,
          reason: "source-corridor-component"
        });
        mergeModelInto(
          streamedModel,
          parseCimFile(path.join(xmlDir, componentFile)),
          terminalKeys
        );
      }
      corridorReduced = true;
      corridorReason = "component-file-limit";
    } else {
      for (const componentFile of componentFiles) {
        if (componentFile === relativePath) continue;
        addRelatedFile({
          relativePath: componentFile,
          reason: "shared-connectivity-node"
        });
      }

      for (const item of findRelatedFiles({ index, selectedLine, relatedMode, maxRelated: maxRelated - relatedFiles.length, selected })) {
        addRelatedFile(item);
      }
    }
  }

  let model = streamedModel || mergeModels(models);
  if (
    !corridorReduced &&
    relatedMode !== "primary" &&
    relatedMode !== "auto" &&
    componentFileCount > 1 &&
    model.equipment.size > AUTO_CORRIDOR_EQUIPMENT_LIMIT
  ) {
    corridorReduced = true;
    corridorReason = "equipment-limit";
  }
  if (corridorReduced) {
    const reduced = reduceModelToSourceCorridors(
      model,
      primaryRelativePaths.map((item) => path.join(xmlDir, item)),
      selectedLine
    );
    model = reduced.model;
    corridorEquipment = reduced.corridorEquipment;
    sourceBoundaries = reduced.sourceBoundaries;
  }
  let topology = buildTopology(model, selectedLine, {
    includedFiles: [relativePath, ...relatedFiles.map((item) => item.relativePath)],
    relatedFiles,
    maxNodes,
    switchStatus,
    switchCurrent,
    primaryFiles: primaryRelativePaths
  });
  if (
    !corridorReduced &&
    relatedMode !== "primary" &&
    relatedMode !== "auto" &&
    componentFileCount > 1 &&
    layoutNeedsCorridorReduction(topology)
  ) {
    const reduced = reduceModelToSourceCorridors(
      model,
      primaryRelativePaths.map((item) => path.join(xmlDir, item)),
      selectedLine
    );
    model = reduced.model;
    corridorReduced = true;
    corridorReason = "layout-density";
    corridorEquipment = reduced.corridorEquipment;
    sourceBoundaries = reduced.sourceBoundaries;
    topology = buildTopology(model, selectedLine, {
      includedFiles: [relativePath, ...relatedFiles.map((item) => item.relativePath)],
      relatedFiles,
      maxNodes,
      switchStatus,
      switchCurrent,
      primaryFiles: primaryRelativePaths
    });
  }
  topology.componentFileCount = componentFileCount;
  topology.corridorReduced = corridorReduced;
  topology.corridorReason = corridorReason;
  topology.corridorEquipment = corridorEquipment;
  topology.sourceBoundaries = sourceBoundaries;
  topology.autoBoundaryCount = autoBoundaryCount;
  topology.svg = renderSvg(topology);
  return topology;
}

function equipmentKind(item) {
  if (SWITCH_TAGS.has(item.tag)) return "switch";
  if (item.tag === "PowerTransformer") return "transformer";
  if (item.tag === "ACLineSegment") return "line";
  if (item.tag === "BusbarSection") return "busbar";
  return "equipment";
}

function switchName(item) {
  return String(switchDisplayLabel(item)).trim();
}

function normalizedSwitchName(item) {
  return switchName(item).toUpperCase().replace(/\s+/g, "");
}

function isHiddenCabinetSwitch(item) {
  if (!item || !SWITCH_TAGS.has(item.tag)) return false;
  const names = [item.dispatchNumber, item.name, item.mrid, item.id]
    .map((value) => String(value || "").trim().toUpperCase().replace(/\s+/g, ""))
    .filter(Boolean);
  if (item.tag === "GroundDisconnector") return true;
  if (item.tag === "Disconnector" && item.container && item.container.startsWith("SUBST_")) return true;
  if (item.tag === "Disconnector" && names.some((name) => /^\d{3,4}$/.test(name) && name.endsWith("4"))) return true;
  return false;
}

function isInternalCabinetLine(item) {
  return !!item && ["ACLineSegment", "Jumper"].includes(item.tag) && item.container && item.container.startsWith("SUBST_");
}

function isVisibleSwitch(item) {
  return !!item && SWITCH_TAGS.has(item.tag) && !isHiddenCabinetSwitch(item);
}

function compareDeviceName(a, b) {
  return compareSwitchOrder(a, b);
}

function compareFeederLabel(a, b) {
  const ai = Number((String(a || "").match(/F\s*(\d+)/i) || ["", "9999"])[1]);
  const bi = Number((String(b || "").match(/F\s*(\d+)/i) || ["", "9999"])[1]);
  if (ai !== bi) return ai - bi;
  return String(a || "").localeCompare(String(b || ""), "zh-Hans-CN");
}

function defaultSwitchClosed(item, selectedCircuit) {
  const name = `${item.name || ""}${item.dispatchNumber || ""}`.toLowerCase();
  if (item.tag === "GroundDisconnector") return false;
  if (/备用|pt|接地|地刀|t0|40$/.test(name)) return false;
  if (selectedCircuit && item.id === selectedCircuit.sourceBreaker) return true;
  return true;
}

function sourceFeederLabel(selectedLine, currentCircuit) {
  if (selectedLine && selectedLine.feederNo) return `F${selectedLine.feederNo}`;
  const text = [currentCircuit && currentCircuit.name, selectedLine && selectedLine.lineName, selectedLine && selectedLine.displayName, selectedLine && selectedLine.fileName]
    .filter(Boolean)
    .join(" ");
  const match = text.match(/F\d+/i);
  return match ? match[0].toUpperCase() : "";
}

function feederLabelFromCircuit(circuit, selectedLine) {
  const text = [circuit && circuit.name, circuit && circuit.dispatchNumber, selectedLine && selectedLine.lineName, selectedLine && selectedLine.displayName]
    .filter(Boolean)
    .join(" ");
  const match = text.match(/F\s*(\d+)/i);
  return match ? `F${match[1]}` : "";
}

function buildSourceInfo(model, selectedLine, sourceBreakers = []) {
  const bySubstation = new Map();
  const allowedSources = new Set(sourceBreakers);
  const colorBySource = new Map(
    sourceBreakers.map((sourceId, index) => [
      sourceId,
      sourceColorAt(index)
    ])
  );
  for (const circuit of model.circuits || []) {
    if (
      !circuit.sourceSubst ||
      !circuit.sourceBreaker ||
      (allowedSources.size && !allowedSources.has(circuit.sourceBreaker))
    ) {
      continue;
    }
    if (!bySubstation.has(circuit.sourceSubst)) {
      bySubstation.set(circuit.sourceSubst, {
        substationId: circuit.sourceSubst,
        feeders: [],
        sources: [],
        color: colorBySource.get(circuit.sourceBreaker) || sourceColorAt(bySubstation.size)
      });
    }
    const info = bySubstation.get(circuit.sourceSubst);
    const feeder = feederLabelFromCircuit(circuit, selectedLine);
    if (feeder && !info.feeders.includes(feeder)) info.feeders.push(feeder);
    if (!info.sources.some((source) => source.id === circuit.sourceBreaker)) {
      info.sources.push({
        id: circuit.sourceBreaker,
        label: feeder || circuit.dispatchNumber || circuit.name || "",
        color:
          colorBySource.get(circuit.sourceBreaker) ||
          sourceColorAt(info.sources.length)
      });
    }
  }
  for (const info of bySubstation.values()) {
    info.feeders.sort(compareFeederLabel);
    info.sources.sort((a, b) => compareFeederLabel(a.label, b.label));
    if (info.sources[0]) info.color = info.sources[0].color;
  }
  return bySubstation;
}

function buildTopology(model, selectedLine, options = {}) {
  const currentCircuit =
    model.circuits.find((item) => item.id === selectedLine.id) ||
    model.circuits.find((item) => item.isCurrentCircuit) ||
    model.circuits[0] ||
    {};

  const equipment = new Map();
  for (const [id, item] of model.equipment) {
    if (item.tag === "TransformerWinding") continue;
    equipment.set(id, {
      ...item,
      kind: equipmentKind(item),
      mrid: item.mrid || cleanId(item.id)
    });
  }

  let terminals = [];
  for (const terminal of model.terminals) {
    let eq = terminal.equipment;
    if (model.windingToTransformer.has(eq)) {
      eq = model.windingToTransformer.get(eq);
    }
    if (equipment.has(eq)) {
      terminals.push({ equipment: eq, connectivityNode: terminal.connectivityNode });
    }
  }

  let { eqToCn, cnToEq } = buildConnectionMaps(terminals);

  const initialSwitchState = {};
  const switchStatusById = {};
  const switchCurrentById = {};
  const switchStatus = options.switchStatus || null;
  const switchCurrent = options.switchCurrent || null;
  for (const item of equipment.values()) {
    if (SWITCH_TAGS.has(item.tag)) {
      const status = getStatusForEquipment(item, switchStatus);
      const current = getCurrentForEquipment(item, switchCurrent);
      initialSwitchState[item.id] = status ? status.closed : defaultSwitchClosed(item, currentCircuit);
      if (status) {
        switchStatusById[item.id] = {
          closed: status.closed,
          value: status.value,
          quality: status.quality,
          kind: status.kind,
          mode: status.mode,
          fileName: status.fileName,
          timestamp: status.timestamp
        };
      }
      if (current) {
        switchCurrentById[item.id] = {
          amp: current.amp,
          display: current.display,
          ia: current.ia,
          ib: current.ib,
          ic: current.ic,
          i0: current.i0,
          valid: current.valid,
          fileName: current.fileName,
          timestamp: current.timestamp
        };
      }
    }
  }
  const sourceBreakers = [
    currentCircuit.sourceBreaker,
    ...((model.circuits || []).map((item) => item.sourceBreaker))
  ].filter(Boolean);

  if (options.pruneReachable !== false) {
    const reachable = computePotentialReachable({
      sourceBreaker: currentCircuit.sourceBreaker || "",
      equipment,
      eqToCn,
      cnToEq
    });
    if (reachable.equipment.size) {
      for (const id of [...equipment.keys()]) {
        if (!reachable.equipment.has(id)) {
          equipment.delete(id);
          delete initialSwitchState[id];
          delete switchStatusById[id];
          delete switchCurrentById[id];
        }
      }
      terminals = terminals.filter((terminal) => equipment.has(terminal.equipment) && reachable.connectivityNodes.has(terminal.connectivityNode));
      ({ eqToCn, cnToEq } = buildConnectionMaps(terminals));
    }
  }
  const uniqueSourceBreakers = [...new Set(sourceBreakers)].filter((id) => equipment.has(id));

  const graph = {
    sourceBreaker: currentCircuit.sourceBreaker || "",
    sourceBreakers: uniqueSourceBreakers,
    sourceSubst: currentCircuit.sourceSubst || "",
    equipment: [...equipment.values()],
    equipmentById: {},
    terminals,
    cnToEq: Object.fromEntries([...cnToEq].map(([key, value]) => [key, [...value]])),
    eqToCn: Object.fromEntries([...eqToCn].map(([key, value]) => [key, [...value]])),
    initialSwitchState,
    switchStatusById,
    switchCurrentById,
    statusSummary: serializableStatusSummary(switchStatus),
    currentSummary: serializableCurrentSummary(switchCurrent),
    switches: [],
    transformers: [],
    initialEnergized: { equipment: [], connectivityNodes: [] }
  };
  for (const item of graph.equipment) {
    graph.equipmentById[item.id] = item;
    if (SWITCH_TAGS.has(item.tag)) graph.switches.push(item);
    if (item.tag === "PowerTransformer") graph.transformers.push(item);
  }

  const layout = buildLayout({
    model,
    graph,
    equipment,
    eqToCn,
    cnToEq,
    currentCircuit,
    selectedLine,
    primaryFiles: options.primaryFiles || [selectedLine.relativePath],
    maxNodes: options.maxNodes || 900
  });
  for (const item of graph.equipment) {
    item.layoutNodeId = layout.equipmentNode[item.id] || "";
  }
  graph.sources = uniqueSourceBreakers.map((id, index) => {
    const item = graph.equipmentById[id];
    const nodeId = layout.equipmentNode[id] || "";
    const node = nodeId && layout.nodes[nodeId];
    const sourceDefinition = layout.sourceDefinitions[id] || {};
    return {
      id,
      nodeId,
      owner: nodeId || id,
      color: sourceDefinition.color || (node && node.sourceColor) || sourceColorAt(index),
      label: sourceDefinition.label || (item && (item.name || item.dispatchNumber)) || ""
    };
  }).filter((source) => source.nodeId);
  graph.initialEnergized = computeEnergized(graph, initialSwitchState);

  return {
    line: selectedLine,
    currentCircuit,
    includedFiles: options.includedFiles || [selectedLine.relativePath],
    relatedFiles: options.relatedFiles || [],
    stats: {
      equipment: graph.equipment.length,
      switches: graph.switches.length,
      liveSwitchStatus: Object.keys(graph.switchStatusById).length,
      liveSwitchCurrent: Object.keys(graph.switchCurrentById).length,
      defaultSwitchStatus: graph.switches.length - Object.keys(graph.switchStatusById).length,
      transformers: graph.transformers.length,
      substations: model.substations.size,
      terminals: graph.terminals.length
    },
    graph,
    layout,
    svg: ""
  };
}

function buildConnectionMaps(terminals) {
  const eqToCn = new Map();
  const cnToEq = new Map();
  for (const terminal of terminals) {
    if (!eqToCn.has(terminal.equipment)) eqToCn.set(terminal.equipment, new Set());
    eqToCn.get(terminal.equipment).add(terminal.connectivityNode);
    if (!cnToEq.has(terminal.connectivityNode)) cnToEq.set(terminal.connectivityNode, new Set());
    cnToEq.get(terminal.connectivityNode).add(terminal.equipment);
  }
  return { eqToCn, cnToEq };
}

function computePotentialReachable({ sourceBreaker, equipment, eqToCn, cnToEq }) {
  const source = sourceBreaker && equipment.has(sourceBreaker) ? sourceBreaker : [...equipment.keys()][0];
  const visitedEq = new Set();
  const visitedCn = new Set();
  const queue = [];
  if (!source) return { equipment: visitedEq, connectivityNodes: visitedCn };
  visitedEq.add(source);
  queue.push({ type: "eq", id: source });

  const isPassable = (eqId) => {
    const item = equipment.get(eqId);
    if (!item) return false;
    return item.tag !== "GroundDisconnector";
  };

  while (queue.length) {
    const cur = queue.shift();
    if (cur.type === "eq") {
      if (!isPassable(cur.id)) continue;
      for (const cn of eqToCn.get(cur.id) || []) {
        if (visitedCn.has(cn)) continue;
        visitedCn.add(cn);
        queue.push({ type: "cn", id: cn });
      }
    } else {
      for (const eqId of cnToEq.get(cur.id) || []) {
        if (visitedEq.has(eqId)) continue;
        visitedEq.add(eqId);
        queue.push({ type: "eq", id: eqId });
      }
    }
  }

  return { equipment: visitedEq, connectivityNodes: visitedCn };
}

function nodeForEquipment(item, model) {
  if (!item) return "";
  if (item.container && model.substations.has(item.container)) {
    return `site:${item.container}`;
  }
  if (item.tag === "PowerTransformer" || isVisibleSwitch(item)) {
    return `eq:${item.id}`;
  }
  return "";
}

function equipmentBelongsToSelectedLine(item, selectedLine, primaryFiles = []) {
  if (!item || !selectedLine || !selectedLine.relativePath) return false;
  const relativePaths = (primaryFiles.length ? primaryFiles : [selectedLine.relativePath])
    .filter(Boolean)
    .map((file) => path.normalize(file).toLowerCase());
  return (item.files || []).some((file) => {
    const normalizedFile = path.normalize(file).toLowerCase();
    return relativePaths.some((relativePath) => normalizedFile.endsWith(relativePath));
  });
}

function buildLayout({ model, graph, equipment, eqToCn, cnToEq, currentCircuit, selectedLine, primaryFiles, maxNodes }) {
  const layoutNodes = new Map();
  const equipmentNode = {};
  const sourceInfo = buildSourceInfo(model, selectedLine, graph.sourceBreakers);
  const sourceDefinitions = {};
  for (const [substationId, info] of sourceInfo) {
    for (const source of info.sources || []) {
      sourceDefinitions[source.id] = {
        ...source,
        owner: `site:${substationId}`
      };
    }
  }

  function ensureNode(id, data) {
    if (!layoutNodes.has(id)) layoutNodes.set(id, data);
    return layoutNodes.get(id);
  }

  for (const substation of model.substations.values()) {
    const id = `site:${substation.id}`;
    ensureNode(id, {
      id,
      rawId: cleanId(substation.id),
      objectId: substation.id,
      kind: "substation",
      name: substation.name || cleanId(substation.id),
      equipment: [],
      isSource: sourceInfo.has(substation.id),
      feederLabel: sourceInfo.has(substation.id) ? sourceInfo.get(substation.id).feeders.join("/") : "",
      sourceColor: sourceInfo.has(substation.id) ? sourceInfo.get(substation.id).color : "",
      width: 180,
      height: 120
    });
  }

  for (const item of equipment.values()) {
    const nodeId = nodeForEquipment(item, model);
    if (!nodeId) continue;
    const node =
      nodeId.startsWith("site:")
        ? layoutNodes.get(nodeId)
        : ensureNode(nodeId, {
            id: nodeId,
            rawId: cleanId(item.id),
            objectId: item.id,
            kind: item.tag === "PowerTransformer" ? "transformer" : "inline-switch",
            name: item.dispatchNumber || item.name || cleanId(item.id),
            equipment: [],
            width: item.tag === "PowerTransformer" ? 120 : 112,
            height: item.tag === "PowerTransformer" ? 168 : 118
          });
    if (node) {
      node.equipment.push(item.id);
      if (equipmentBelongsToSelectedLine(item, selectedLine, primaryFiles)) {
        node.isPrimary = true;
      }
      equipmentNode[item.id] = nodeId;
    }
  }

  for (const node of layoutNodes.values()) {
    const switchCount = node.equipment.filter((id) => isVisibleSwitch(equipment.get(id))).length;
    const transformerCount = node.equipment.filter((id) => equipment.get(id).tag === "PowerTransformer").length;
    node.visibleEquipment = node.equipment.filter((id) => {
      const item = equipment.get(id);
      return isVisibleSwitch(item) || (item && item.tag === "PowerTransformer");
    });
    if (node.kind === "substation") {
      const switchPitch = node.isSource ? 68 : 42;
      node.width = Math.max(120, 72 + switchCount * switchPitch + transformerCount * 58);
      node.height = transformerCount ? 190 : 122;
      if (node.isSource) {
        node.busOffsetY = 62;
        node.width = Math.max(node.width, 190);
        node.height = Math.max(node.height, 150);
      }
    } else if (node.kind === "transformer") {
      node.width = Math.max(node.width, 120);
      node.height = Math.max(node.height, 168);
    }
  }

  for (const [nodeId, node] of [...layoutNodes]) {
    if (
      node.kind === "substation" &&
      !node.isSource &&
      !(node.visibleEquipment || []).length
    ) {
      for (const eqId of node.equipment) {
        if (equipmentNode[eqId] === nodeId) delete equipmentNode[eqId];
      }
      layoutNodes.delete(nodeId);
    }
  }

  const edges = collapseEdges({ layoutNodes, equipment, equipmentNode, eqToCn, cnToEq, maxNodes });
  const sourceNode =
    equipmentNode[currentCircuit.sourceBreaker] ||
    (currentCircuit.sourceSubst ? `site:${currentCircuit.sourceSubst}` : [...layoutNodes.keys()][0]);
  const sourceData = sourceNode && layoutNodes.get(sourceNode);
  if (sourceData) {
    sourceData.isSource = true;
    sourceData.isPrimary = true;
    sourceData.feederLabel = sourceData.feederLabel || sourceFeederLabel(selectedLine, currentCircuit);
    sourceData.sourceColor = sourceData.sourceColor || sourceColorAt(0);
    sourceData.busOffsetY = 62;
    sourceData.width = Math.max(sourceData.width, 190);
    sourceData.height = Math.max(sourceData.height, 150);
  }
  assignPositions(layoutNodes, edges, sourceNode);
  alignSourceNodesLeft(layoutNodes, edges, sourceNode);
  const sourceDomains = buildOperationalSourceDomains({
    layoutNodes,
    equipmentNode,
    equipment,
    eqToCn,
    cnToEq,
    sourceBreakers: graph.sourceBreakers,
    sourceDefinitions,
    switchState: graph.initialSwitchState
  });
  applyOperationalNodeDomains(layoutNodes, equipment, eqToCn, sourceDomains);
  applySwitchSourceMetadata(equipment, eqToCn, sourceDomains, graph.initialSwitchState);
  let devicePositions = assignDevicePositions(layoutNodes, equipment);
  let anchorIndex = buildDeviceAnchors(layoutNodes, equipment, eqToCn, cnToEq, devicePositions);
  let connectivityAnchors = buildConnectivityAnchorIndex({ equipment, cnToEq, anchorsByCn: anchorIndex.byCn });
  let wireResult = buildWires({ equipment, eqToCn, cnToEq, anchorsByCn: anchorIndex.byCn, connectivityAnchors, currentCircuit });
  if (
    pruneUnwiredSourceSwitches({
      layoutNodes,
      equipment,
      equipmentNode,
      wires: wireResult.wires
    })
  ) {
    devicePositions = assignDevicePositions(layoutNodes, equipment);
    anchorIndex = buildDeviceAnchors(layoutNodes, equipment, eqToCn, cnToEq, devicePositions);
    connectivityAnchors = buildConnectivityAnchorIndex({ equipment, cnToEq, anchorsByCn: anchorIndex.byCn });
    wireResult = buildWires({ equipment, eqToCn, cnToEq, anchorsByCn: anchorIndex.byCn, connectivityAnchors, currentCircuit });
  }
  applyWireSourceColors(wireResult.wires, sourceDomains);

  return {
    nodes: Object.fromEntries(layoutNodes),
    edges,
    wires: wireResult.wires,
    junctions: wireResult.junctions,
    suppressedDanglingLines: wireResult.suppressedDanglingLines,
    sourceNode,
    equipmentNode,
    sourceDefinitions,
    devicePositions,
    deviceAnchors: anchorIndex.byEquipment,
    width: Math.max(...[...layoutNodes.values()].map((node) => node.x + node.width + 100), 1200),
    height: Math.max(...[...layoutNodes.values()].map((node) => node.y + node.height + 120), 720)
  };
}

function pruneUnwiredSourceSwitches({ layoutNodes, equipment, equipmentNode, wires }) {
  const wiredEquipment = new Set();
  for (const wire of wires || []) {
    if (wire.from && wire.from.eqId) wiredEquipment.add(wire.from.eqId);
    if (wire.to && wire.to.eqId) wiredEquipment.add(wire.to.eqId);
  }

  let changed = false;
  for (const node of layoutNodes.values()) {
    if (!node.isSource) continue;
    const hidden = new Set(
      (node.visibleEquipment || []).filter((eqId) => {
        const item = equipment.get(eqId);
        return isVisibleSwitch(item) && !wiredEquipment.has(eqId);
      })
    );
    if (!hidden.size) continue;
    changed = true;
    node.equipment = node.equipment.filter((eqId) => !hidden.has(eqId));
    node.visibleEquipment = node.visibleEquipment.filter((eqId) => !hidden.has(eqId));
    for (const eqId of hidden) {
      if (equipmentNode[eqId] === node.id) delete equipmentNode[eqId];
    }

    const switches = node.equipment
      .map((eqId) => equipment.get(eqId))
      .filter(isVisibleSwitch);
    const transformers = node.equipment
      .map((eqId) => equipment.get(eqId))
      .filter((item) => item && item.tag === "PowerTransformer");
    node.width = Math.max(190, 72 + switches.length * 68 + transformers.length * 58);
    node.height = Math.max(transformers.length ? 190 : 150, 150);
    const feederLabels = switches
      .map((item) => {
        const match = `${item.name || ""} ${item.dispatchNumber || ""}`.match(/F\s*(\d+)/i);
        return match ? `F${match[1]}` : "";
      })
      .filter(Boolean)
      .sort(compareFeederLabel);
    node.feederLabel = [...new Set(feederLabels)].join("/");
  }
  return changed;
}

function buildOperationalSourceDomains({
  layoutNodes,
  equipmentNode,
  equipment,
  eqToCn,
  cnToEq,
  sourceBreakers,
  sourceDefinitions = {},
  switchState
}) {
  const equipmentDomains = new Map();
  const connectivityDomains = new Map();
  const queue = [];

  function isConductive(eqId) {
    const item = equipment.get(eqId);
    if (!item || item.tag === "GroundDisconnector") return false;
    if (SWITCH_TAGS.has(item.tag)) return switchState[eqId] !== false;
    return true;
  }

  function setDomain(map, id, domain, distance) {
    if (!id || !domain || !domain.color) return;
    if (!map.has(id)) map.set(id, new Map());
    const domains = map.get(id);
    const domainId = domain.id || domain.owner;
    const current = domains.get(domainId);
    if (!current || distance < current.distance) {
      domains.set(domainId, { ...domain, distance });
      return true;
    }
    return false;
  }

  for (const [index, sourceId] of (sourceBreakers || []).entries()) {
    if (!equipment.has(sourceId) || !isConductive(sourceId)) continue;
    const nodeId = equipmentNode[sourceId];
    const node = nodeId && layoutNodes.get(nodeId);
    const item = equipment.get(sourceId);
    const sourceDefinition = sourceDefinitions[sourceId] || {};
    const owner = nodeId || sourceId;
    const domain = {
      id: sourceId,
      owner,
      nodeId: nodeId || "",
      color: sourceDefinition.color || (node && node.sourceColor) || sourceColorAt(index),
      label: sourceDefinition.label || item.name || item.dispatchNumber || ""
    };
    if (node) {
      node.sourceOwner = owner;
      node.sourceLabel = domain.label;
      node.sourceColor = domain.color;
    }
    setDomain(equipmentDomains, sourceId, domain, 0);
    queue.push({ type: "eq", id: sourceId, domain, distance: 0 });
  }

  while (queue.length) {
    const current = queue.shift();
    if (current.type === "eq") {
      if (!isConductive(current.id)) continue;
      for (const cn of eqToCn.get(current.id) || []) {
        const distance = current.distance + 1;
        if (setDomain(connectivityDomains, cn, current.domain, distance)) {
          queue.push({ type: "cn", id: cn, domain: current.domain, distance });
        }
      }
    } else {
      for (const eqId of cnToEq.get(current.id) || []) {
        const item = equipment.get(eqId);
        if (!item || item.tag === "GroundDisconnector") continue;
        const distance = current.distance + 1;
        const changed = setDomain(equipmentDomains, eqId, current.domain, distance);
        if (changed && isConductive(eqId)) {
          queue.push({ type: "eq", id: eqId, domain: current.domain, distance });
        }
      }
    }
  }

  return { equipment: equipmentDomains, connectivityNodes: connectivityDomains };
}

function domainValues(domainMap, id) {
  const domains = domainMap && domainMap.get(id);
  return domains ? [...domains.values()] : [];
}

function uniqueDomains(domains) {
  const bySource = new Map();
  for (const domain of domains || []) {
    if (!domain || !domain.owner || !domain.color) continue;
    const key = domain.id || domain.owner;
    const current = bySource.get(key);
    if (!current || (domain.distance ?? 9999) < (current.distance ?? 9999)) {
      bySource.set(key, domain);
    }
  }
  return [...bySource.values()].sort((a, b) => (a.distance ?? 9999) - (b.distance ?? 9999));
}

function serializableDomains(domains) {
  return uniqueDomains(domains).map((domain) => ({
    id: domain.id || "",
    owner: domain.owner,
    nodeId: domain.nodeId || "",
    color: domain.color,
    label: domain.label || ""
  }));
}

function applyOperationalNodeDomains(layoutNodes, equipment, eqToCn, sourceDomains) {
  for (const node of layoutNodes.values()) {
    if (node.isSource) continue;
    const busbarCns = [];
    for (const eqId of node.equipment || []) {
      const item = equipment.get(eqId);
      if (item && item.tag === "BusbarSection") {
        busbarCns.push(...(eqToCn.get(eqId) || []));
      }
    }
    let domains = uniqueDomains(
      busbarCns.flatMap((cn) => domainValues(sourceDomains.connectivityNodes, cn))
    );
    if (!domains.length) {
      domains = uniqueDomains(
        (node.equipment || []).flatMap((eqId) => domainValues(sourceDomains.equipment, eqId))
      );
    }
    node.sourceDomains = serializableDomains(domains);
    node.multiSource = domains.length > 1;
    if (domains.length) {
      node.sourceOwner = domains[0].owner;
      node.sourceColor = domains[0].color;
      node.sourceLabel = domains[0].label || "";
    } else {
      node.sourceOwner = "";
      node.sourceColor = "";
      node.sourceLabel = "";
    }
  }
}

function applySwitchSourceMetadata(equipment, eqToCn, sourceDomains, switchState) {
  for (const item of equipment.values()) {
    if (!SWITCH_TAGS.has(item.tag) || item.tag === "GroundDisconnector") continue;
    const cns = [...(eqToCn.get(item.id) || [])];
    const sourceSides = cns.map((cn) => ({
      cn,
      domains: serializableDomains(domainValues(sourceDomains.connectivityNodes, cn))
    }));
    const activeSides = sourceSides.filter((side) => side.domains.length);
    const ownerSets = activeSides.map(
      (side) => new Set(side.domains.map((domain) => domain.id || domain.owner))
    );
    const separatedSources =
      ownerSets.length >= 2 &&
      ownerSets.some((owners, index) =>
        ownerSets.some((other, otherIndex) => otherIndex > index && [...owners].every((owner) => !other.has(owner)))
      );
    const allOwners = new Set(
      activeSides.flatMap((side) => side.domains.map((domain) => domain.id || domain.owner))
    );
    item.sourceSides = sourceSides;
    item.isTiePoint = separatedSources;
    item.tieClosed = item.isTiePoint ? switchState[item.id] !== false : false;
  }
}

function applyWireSourceColors(wires, sourceDomains = {}) {
  const equipmentDomains = sourceDomains.equipment || new Map();
  const connectivityDomains = sourceDomains.connectivityNodes || new Map();

  for (const wire of wires || []) {
    const equipmentMatches = uniqueDomains(
      (wire.equipmentIds || []).flatMap((id) => domainValues(equipmentDomains, id))
    );
    const endpointMatches = uniqueDomains(
      [wire.from, wire.to].flatMap((endpoint) =>
        endpoint && endpoint.cn ? domainValues(connectivityDomains, endpoint.cn) : []
      )
    );
    const domains = equipmentMatches.length ? equipmentMatches : endpointMatches;
    const domain = domains[0] || null;
    wire.sourceColor = domain ? domain.color : "";
    wire.sourceLabel = domain ? domain.label || "" : "";
    wire.sourceDomains = serializableDomains(domains);
    wire.multiSource = domains.length > 1;
  }
}

function alignSourceNodesLeft(layoutNodes, edges, sourceNode) {
  const adjacency = new Map();
  for (const node of layoutNodes.values()) adjacency.set(node.id, []);
  for (const edge of edges || []) {
    if (adjacency.has(edge.from)) adjacency.get(edge.from).push(edge.to);
    if (adjacency.has(edge.to)) adjacency.get(edge.to).push(edge.from);
  }

  const sources = [...layoutNodes.values()]
    .filter((node) => node.isSource)
    .map((node) => {
      const neighbors = (adjacency.get(node.id) || [])
        .map((id) => layoutNodes.get(id))
        .filter((neighbor) => neighbor && !neighbor.isSource);
      const neighborTops = neighbors
        .map((neighbor) => neighbor.y)
        .sort((a, b) => a - b);
      const middle = Math.floor(neighborTops.length / 2);
      const desiredY = neighborTops.length
        ? neighborTops.length % 2
          ? neighborTops[middle]
          : (neighborTops[middle - 1] + neighborTops[middle]) / 2
        : node.y;
      return {
        node,
        desiredY: node.id === sourceNode ? 80 : Math.max(80, desiredY),
        priority: node.id === sourceNode ? 0 : 1
      };
    })
    .sort((a, b) =>
      a.desiredY - b.desiredY ||
      a.priority - b.priority ||
      a.node.name.localeCompare(b.node.name, "zh-Hans-CN")
    );

  if (!sources.length) return;

  const sourceColumnX = 80;
  const sourceColumnRight = sourceColumnX +
    Math.max(...sources.map((entry) => entry.node.width || 190)) + 64;
  const nonSources = [...layoutNodes.values()].filter((node) => !node.isSource);
  if (nonSources.length) {
    const minimumNonSourceX = Math.min(...nonSources.map((node) => node.x));
    const shiftX = Math.max(0, sourceColumnRight - minimumNonSourceX);
    if (shiftX) {
      for (const node of nonSources) node.x += shiftX;
    }
  }

  const minimumGap = 70;
  const leftSources = [];
  for (const entry of sources) {
    const node = entry.node;
    node.x = sourceColumnX;
    node.y = entry.desiredY;
    let changed = true;
    while (changed) {
      changed = false;
      for (const placed of leftSources) {
        const overlaps =
          node.y < placed.y + placed.height + minimumGap &&
          node.y + node.height + minimumGap > placed.y;
        if (!overlaps) continue;
        node.y = placed.y + placed.height + minimumGap;
        changed = true;
      }
    }
    leftSources.push(node);
    leftSources.sort((a, b) => a.y - b.y);
  }
}

function collapseEdges({ layoutNodes, equipment, equipmentNode, eqToCn, cnToEq, maxNodes }) {
  const edgeMap = new Map();
  const nodes = [...layoutNodes.values()].slice(0, maxNodes);

  function addEdge(from, to, through) {
    if (!from || !to || from === to) return;
    const key = [from, to].sort().join("|");
    if (!edgeMap.has(key)) {
      edgeMap.set(key, {
        id: `EDGE_${edgeMap.size + 1}`,
        from,
        to,
        name: "",
        equipmentIds: [],
        related: false,
        tree: false
      });
    }
    const edge = edgeMap.get(key);
    for (const id of through) {
      if (!edge.equipmentIds.includes(id)) edge.equipmentIds.push(id);
    }
  }

  for (const node of nodes) {
    const boundaryCns = new Set();
    for (const eqId of node.equipment) {
      for (const cn of eqToCn.get(eqId) || []) boundaryCns.add(cn);
    }
    for (const startCn of boundaryCns) {
      const queue = [{ type: "cn", id: startCn, through: [] }];
      const seenCn = new Set([startCn]);
      const seenEq = new Set();
      while (queue.length) {
        const cur = queue.shift();
        if (cur.type === "cn") {
          for (const eqId of cnToEq.get(cur.id) || []) {
            if (seenEq.has(eqId)) continue;
            seenEq.add(eqId);
            const nextNode = equipmentNode[eqId];
            if (nextNode && nextNode !== node.id) {
              addEdge(node.id, nextNode, cur.through);
              continue;
            }
            const item = equipment.get(eqId);
            if (!item) continue;
            if (PASS_THROUGH_TAGS.has(item.tag) || !nextNode || nextNode === node.id) {
              queue.push({ type: "eq", id: eqId, through: [...cur.through, eqId] });
            }
          }
        } else {
          for (const cn of eqToCn.get(cur.id) || []) {
            if (seenCn.has(cn)) continue;
            seenCn.add(cn);
            queue.push({ type: "cn", id: cn, through: cur.through });
          }
        }
      }
    }
  }

  return [...edgeMap.values()];
}

function assignPositions(layoutNodes, edges, sourceNode) {
  const adjacency = new Map();
  for (const nodeId of layoutNodes.keys()) adjacency.set(nodeId, []);
  for (const edge of edges) {
    if (adjacency.has(edge.from)) adjacency.get(edge.from).push(edge.to);
    if (adjacency.has(edge.to)) adjacency.get(edge.to).push(edge.from);
  }

  if (assignPrimaryBackbonePositions(layoutNodes, edges, adjacency, sourceNode)) {
    return;
  }

  assignTreePositions(layoutNodes, edges, adjacency, sourceNode);
}

function assignPrimaryBackbonePositions(layoutNodes, edges, adjacency, sourceNode) {
  if (!sourceNode || !layoutNodes.has(sourceNode)) return false;
  const primaryNodes = new Set(
    [...layoutNodes.values()].filter((node) => node.isPrimary).map((node) => node.id)
  );
  primaryNodes.add(sourceNode);
  const sourceNodes = new Set(
    [...layoutNodes.values()].filter((node) => node.isSource).map((node) => node.id)
  );
  const backboneCandidates = new Set([...primaryNodes, ...sourceNodes]);
  if (backboneCandidates.size < 2) return false;

  const parent = new Map([[sourceNode, ""]]);
  const distance = new Map([[sourceNode, 0]]);
  const order = [sourceNode];
  for (let index = 0; index < order.length; index++) {
    const current = order[index];
    const neighbors = [...(adjacency.get(current) || [])].sort((a, b) =>
      nodeSortKey(layoutNodes.get(a)).localeCompare(nodeSortKey(layoutNodes.get(b)), "zh-Hans-CN")
    );
    for (const next of neighbors) {
      if (distance.has(next)) continue;
      distance.set(next, distance.get(current) + 1);
      parent.set(next, current);
      order.push(next);
    }
  }

  const reachableCandidates = [...backboneCandidates].filter((id) => distance.has(id));
  if (reachableCandidates.length < 2) return false;
  reachableCandidates.sort((a, b) => {
    const distanceDifference = distance.get(b) - distance.get(a);
    if (distanceDifference) return distanceDifference;
    const sourceDifference = Number(sourceNodes.has(b)) - Number(sourceNodes.has(a));
    if (sourceDifference) return sourceDifference;
    const degreeDifference =
      (adjacency.get(a) || []).length - (adjacency.get(b) || []).length;
    if (degreeDifference) return degreeDifference;
    return nodeSortKey(layoutNodes.get(a)).localeCompare(
      nodeSortKey(layoutNodes.get(b)),
      "zh-Hans-CN"
    );
  });

  const target = reachableCandidates[0];
  const backbone = [];
  for (let current = target; current; current = parent.get(current)) {
    backbone.push(current);
    if (current === sourceNode) break;
  }
  backbone.reverse();
  if (backbone.length < 2 || backbone[0] !== sourceNode) return false;

  const backboneSet = new Set(backbone);
  const visited = new Set(backbone);
  const treeEdges = new Set();
  const trunkY = 80;
  let backboneX = 80;
  for (let index = 0; index < backbone.length; index++) {
    const node = layoutNodes.get(backbone[index]);
    node.x = backboneX;
    node.y = trunkY;
    node.onBackbone = true;
    backboneX += nodeHorizontalFootprint(node) + 54;
    if (index) {
      treeEdges.add([backbone[index - 1], backbone[index]].sort().join("|"));
    }
  }

  const branchBands = [];
  const branchStartY = 360;
  for (const backboneId of backbone) {
    const attachment = layoutNodes.get(backboneId);
    const neighbors = [...(adjacency.get(backboneId) || [])]
      .filter((id) => !backboneSet.has(id) && !visited.has(id))
      .sort((a, b) =>
        nodeSortKey(layoutNodes.get(a)).localeCompare(nodeSortKey(layoutNodes.get(b)), "zh-Hans-CN")
      );
    for (const branchRoot of neighbors) {
      const branch = collectBranchTree(branchRoot, backboneSet, visited, adjacency);
      if (!branch.order.length) continue;
      treeEdges.add([backboneId, branchRoot].sort().join("|"));
      for (const [nodeId, branchParent] of branch.parent) {
        if (branchParent) {
          treeEdges.add([nodeId, branchParent].sort().join("|"));
        }
      }
      const depthOffsets = branchDepthOffsets(branch, layoutNodes);
      const leafY = { value: branchStartY };
      placeBranchTree({
        nodeId: branchRoot,
        layoutNodes,
        children: branch.children,
        depth: branch.depth,
        attachmentX: attachment.x,
        depthOffsets,
        leafY
      });
      packBranchIntoBands(branch.order, layoutNodes, branchBands, branchStartY);
    }
  }

  let componentOffset = branchBands.length
    ? Math.max(...branchBands.map((band) => band.y2)) + 100
    : branchStartY;
  for (const root of layoutNodes.keys()) {
    if (visited.has(root)) continue;
    const component = collectBranchTree(root, new Set(), visited, adjacency);
    if (!component.order.length) continue;
    for (const [nodeId, componentParent] of component.parent) {
      if (componentParent) treeEdges.add([nodeId, componentParent].sort().join("|"));
    }
    const depthOffsets = branchDepthOffsets(component, layoutNodes);
    const leafY = { value: componentOffset };
    placeBranchTree({
      nodeId: root,
      layoutNodes,
      children: component.children,
      depth: component.depth,
      attachmentX: 80,
      depthOffsets,
      leafY
    });
    const bounds = nodeBounds(component.order, layoutNodes);
    componentOffset = bounds.y2 + 100;
  }

  for (const edge of edges) {
    edge.tree = treeEdges.has([edge.from, edge.to].sort().join("|"));
  }
  return true;
}

function nodeSortKey(node) {
  return `${node && node.name ? node.name : ""}|${node && node.id ? node.id : ""}`;
}

function nodeHorizontalFootprint(node) {
  if (!node) return 120;
  const labelWidth = [...String(node.name || "")].reduce(
    (sum, char) => sum + (/[\u0000-\u00ff]/.test(char) ? 13 : 24),
    0
  );
  return Math.max(node.width || 0, Math.min(labelWidth, 390));
}

function collectBranchTree(root, blocked, visited, adjacency) {
  const parent = new Map([[root, ""]]);
  const depth = new Map([[root, 1]]);
  const order = [root];
  const children = new Map([[root, []]]);
  visited.add(root);
  for (let index = 0; index < order.length; index++) {
    const current = order[index];
    for (const next of adjacency.get(current) || []) {
      if (blocked.has(next) || visited.has(next)) continue;
      visited.add(next);
      parent.set(next, current);
      depth.set(next, depth.get(current) + 1);
      if (!children.has(current)) children.set(current, []);
      children.get(current).push(next);
      children.set(next, []);
      order.push(next);
    }
  }
  return { parent, depth, order, children };
}

function branchDepthOffsets(branch, layoutNodes) {
  const footprintByDepth = new Map();
  for (const nodeId of branch.order || []) {
    const level = branch.depth.get(nodeId) || 1;
    const footprint = nodeHorizontalFootprint(layoutNodes.get(nodeId));
    footprintByDepth.set(
      level,
      Math.max(footprintByDepth.get(level) || 0, footprint)
    );
  }
  const offsets = new Map([[1, 0]]);
  const maxDepth = Math.max(...footprintByDepth.keys(), 1);
  for (let level = 2; level <= maxDepth; level++) {
    offsets.set(
      level,
      (offsets.get(level - 1) || 0) +
        (footprintByDepth.get(level - 1) || 120) +
        58
    );
  }
  return offsets;
}

function nodeBounds(nodeIds, layoutNodes) {
  const nodes = (nodeIds || []).map((id) => layoutNodes.get(id)).filter(Boolean);
  if (!nodes.length) return { x1: 0, y1: 0, x2: 0, y2: 0 };
  return {
    x1: Math.min(...nodes.map((node) => node.x)),
    y1: Math.min(...nodes.map((node) => node.y)),
    x2: Math.max(...nodes.map((node) => node.x + node.width)),
    y2: Math.max(...nodes.map((node) => node.y + node.height))
  };
}

function packBranchIntoBands(nodeIds, layoutNodes, bands, minimumY) {
  let bounds = nodeBounds(nodeIds, layoutNodes);
  let targetY = Math.max(minimumY, bounds.y1);
  const horizontalGap = 46;
  const verticalGap = 72;
  let moved = true;
  while (moved) {
    moved = false;
    for (const band of bands) {
      const horizontalOverlap =
        bounds.x1 < band.x2 + horizontalGap &&
        bounds.x2 + horizontalGap > band.x1;
      const verticalOverlap =
        targetY < band.y2 + verticalGap &&
        targetY + (bounds.y2 - bounds.y1) + verticalGap > band.y1;
      if (!horizontalOverlap || !verticalOverlap) continue;
      targetY = band.y2 + verticalGap;
      moved = true;
    }
  }
  const deltaY = targetY - bounds.y1;
  if (deltaY) {
    for (const nodeId of nodeIds || []) {
      const node = layoutNodes.get(nodeId);
      if (node) node.y += deltaY;
    }
  }
  bounds = nodeBounds(nodeIds, layoutNodes);
  bands.push(bounds);
}

function placeBranchTree({
  nodeId,
  layoutNodes,
  children,
  depth,
  attachmentX,
  depthOffsets,
  leafY
}) {
  const childNodes = children.get(nodeId) || [];
  const node = layoutNodes.get(nodeId);
  if (!childNodes.length) {
    node.y = leafY.value;
    leafY.value += Math.max(205, node.height + 82);
  } else {
    for (const child of childNodes) {
      placeBranchTree({
        nodeId: child,
        layoutNodes,
        children,
        depth,
        attachmentX,
        depthOffsets,
        leafY
      });
    }
    node.y =
      childNodes.reduce((sum, child) => sum + layoutNodes.get(child).y, 0) /
      childNodes.length;
  }
  node.x = attachmentX + (depthOffsets.get(depth.get(nodeId) || 1) || 0);
}

function assignTreePositions(layoutNodes, edges, adjacency, sourceNode) {
  const roots = [];
  if (sourceNode && layoutNodes.has(sourceNode)) roots.push(sourceNode);
  for (const nodeId of layoutNodes.keys()) {
    if (!roots.includes(nodeId)) roots.push(nodeId);
  }

  const visited = new Set();
  let componentOffset = 0;
  const treeEdges = new Set();

  for (const root of roots) {
    if (visited.has(root)) continue;
    const parent = new Map([[root, ""]]);
    const depth = new Map([[root, 0]]);
    const order = [root];
    visited.add(root);
    for (let i = 0; i < order.length; i++) {
      const current = order[i];
      for (const next of adjacency.get(current) || []) {
        if (visited.has(next)) continue;
        visited.add(next);
        parent.set(next, current);
        depth.set(next, depth.get(current) + 1);
        treeEdges.add([current, next].sort().join("|"));
        order.push(next);
      }
    }

    const children = new Map();
    for (const nodeId of order) children.set(nodeId, []);
    for (const [nodeId, p] of parent) {
      if (p && children.has(p)) children.get(p).push(nodeId);
    }

    let leafY = componentOffset + 80;
    function place(nodeId) {
      const kids = children.get(nodeId) || [];
      const node = layoutNodes.get(nodeId);
      if (!kids.length) {
        node.y = leafY;
        leafY += Math.max(280, node.height + 170);
      } else {
        for (const child of kids) place(child);
        node.y = kids.reduce((sum, child) => sum + layoutNodes.get(child).y, 0) / kids.length;
      }
      node.x = 80 + (depth.get(nodeId) || 0) * 430;
    }
    place(root);
    componentOffset = leafY + 90;
  }

  for (const edge of edges) {
    edge.tree = treeEdges.has([edge.from, edge.to].sort().join("|"));
  }
}

function assignDevicePositions(layoutNodes, equipment) {
  const positions = {};
  for (const node of layoutNodes.values()) {
    const switches = node.equipment
      .map((id) => equipment.get(id))
      .filter(isVisibleSwitch)
      .sort(compareDeviceName);
    const transformers = node.equipment.map((id) => equipment.get(id)).filter((item) => item && item.tag === "PowerTransformer");
    if (node.kind === "inline-switch") {
      switches.forEach((item, index) => {
        positions[item.id] = {
          x: node.x + 24,
          y: node.y + 32 + index * 36,
          orientation: "horizontal",
          inline: true
        };
      });
      continue;
    }
    const busY = node.y + (node.busOffsetY || 46);
    const switchPitch = node.isSource ? 68 : 42;
    const startX = node.x + (node.isSource ? 42 : 26);
    const transformerStartX =
      node.kind === "transformer"
        ? node.x + node.width / 2
        : node.x + (node.isSource ? 72 : 40) + switches.length * 42;
    switches.forEach((item, index) => {
      positions[item.id] = {
        x: startX + index * switchPitch,
        y: busY - 1
      };
    });
    transformers.forEach((item, index) => {
      positions[item.id] = {
        x: transformerStartX + index * 58,
        y: busY + 34
      };
    });
  }
  return positions;
}

function buildDeviceAnchors(layoutNodes, equipment, eqToCn, cnToEq, positions) {
  const byEquipment = {};
  const byCn = new Map();

  function addCnAnchor(cn, anchor) {
    if (!cn) return;
    if (!byCn.has(cn)) byCn.set(cn, []);
    byCn.get(cn).push(anchor);
  }

  function cnsOf(eqId) {
    return [...(eqToCn.get(eqId) || [])];
  }

  for (const node of layoutNodes.values()) {
    const busCns = new Set();
    for (const eqId of node.equipment) {
      const item = equipment.get(eqId);
      if (item && item.tag === "BusbarSection") {
        for (const cn of cnsOf(eqId)) busCns.add(cn);
      }
    }

    for (const eqId of node.equipment) {
      const item = equipment.get(eqId);
      const pos = positions[eqId];
      if (!item || !pos) continue;

      if (isVisibleSwitch(item)) {
        const cns = cnsOf(eqId);
        if (node.kind === "inline-switch") {
          const ordered = orientInlineCns(eqId, cns, { equipment, eqToCn, cnToEq, positions, layoutNodes });
          const leftCn = ordered[0] || "";
          const rightCn = ordered[1] || "";
          const left = { eqId, nodeId: node.id, port: "left", cn: leftCn, x: pos.x + 5, y: pos.y + 5 };
          const right = { eqId, nodeId: node.id, port: "right", cn: rightCn, x: pos.x + 37, y: pos.y + 5 };
          byEquipment[eqId] = { left, right };
          addCnAnchor(leftCn, left);
          addCnAnchor(rightCn, right);
          continue;
        }
        let topCn = cns[0] || "";
        let bottomCn = cns[1] || "";
        if (node.isSource && cns.length === 1) {
          topCn = "";
          bottomCn = cns[0];
        } else if (cns.length > 1 && busCns.has(cns[1]) && !busCns.has(cns[0])) {
          topCn = cns[1];
          bottomCn = cns[0];
        } else if (cns.length > 1 && busCns.has(cns[0])) {
          topCn = cns[0];
          bottomCn = cns[1];
        }
        const top = { eqId, nodeId: node.id, port: "top", cn: topCn, x: pos.x + 8, y: pos.y + 1 };
        const bottom = { eqId, nodeId: node.id, port: "bottom", cn: bottomCn, x: pos.x + 8, y: pos.y + 36 };
        byEquipment[eqId] = { top, bottom };
        addCnAnchor(topCn, top);
        addCnAnchor(bottomCn, bottom);
      } else if (item.tag === "PowerTransformer") {
        const cns = cnsOf(eqId);
        const top = { eqId, nodeId: node.id, port: "top", cn: cns[0] || "", x: pos.x, y: pos.y };
        byEquipment[eqId] = { top };
        addCnAnchor(top.cn, top);
      }
    }
  }

  return { byEquipment, byCn };
}

function buildConnectivityAnchorIndex({ equipment, cnToEq, anchorsByCn }) {
  const byCn = new Map();

  for (const [cn, anchors] of anchorsByCn.entries()) {
    const visibleAnchors = uniqueAnchors(anchors);
    if (!visibleAnchors.length) continue;
    if (isSameCabinetTransformerTap(visibleAnchors, equipment)) continue;
    const eqIds = [...(cnToEq.get(cn) || [])];
    const drawableCount = eqIds.filter((id) => {
      const item = equipment.get(id);
      return item && ["ACLineSegment", "Jumper"].includes(item.tag) && !isInternalCabinetLine(item);
    }).length;
    const visibleEquipmentCount = visibleAnchors.filter((anchor) => anchor.eqId).length;
    const nodeCount = new Set(visibleAnchors.map((anchor) => anchor.nodeId).filter(Boolean)).size;
    const uniqueGeometryCount = new Set(visibleAnchors.map(anchorGeometryKey)).size;
    const portSet = new Set(visibleAnchors.map((anchor) => anchor.port));
    const hasOpposedVerticalPorts = portSet.has("top") && portSet.has("bottom");
    const hasSidePort = portSet.has("left") || portSet.has("right");

    if (
      uniqueGeometryCount < 2 &&
      !(drawableCount >= 2 && visibleEquipmentCount >= 1)
    ) {
      continue;
    }
    if (
      drawableCount < 1 &&
      nodeCount <= 1 &&
      !hasOpposedVerticalPorts &&
      !hasSidePort
    ) {
      continue;
    }

    const shared = sharedConnectivityAnchor(cn, visibleAnchors, byCn.size);
    shared.leadAnchors = visibleAnchors.filter((anchor) => distance(anchor, shared) > 2);
    byCn.set(cn, shared);
  }

  return byCn;
}

function isSameCabinetTransformerTap(anchors, equipment) {
  if (!anchors || anchors.length < 2) return false;
  const nodeIds = new Set(anchors.map((anchor) => anchor.nodeId).filter(Boolean));
  if (nodeIds.size !== 1) return false;
  const hasSwitchBottom = anchors.some((anchor) => {
    const item = equipment.get(anchor.eqId);
    return anchor.port === "bottom" && isVisibleSwitch(item);
  });
  const hasTransformerTop = anchors.some((anchor) => {
    const item = equipment.get(anchor.eqId);
    return anchor.port === "top" && item && item.tag === "PowerTransformer";
  });
  const onlyCabinetTaps = anchors.every((anchor) => {
    const item = equipment.get(anchor.eqId);
    return (
      (anchor.port === "bottom" && isVisibleSwitch(item)) ||
      (anchor.port === "top" && item && item.tag === "PowerTransformer")
    );
  });
  return hasSwitchBottom && hasTransformerTop && onlyCabinetTaps;
}

function uniqueAnchors(anchors) {
  const seen = new Set();
  const out = [];
  for (const anchor of anchors || []) {
    const key = `${anchor.eqId || ""}|${anchor.nodeId || ""}|${anchor.port || ""}|${Math.round(anchor.x)}|${Math.round(anchor.y)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(anchor);
  }
  return out;
}

function anchorGeometryKey(anchor) {
  return `${Math.round(anchor.x)},${Math.round(anchor.y)},${anchor.nodeId || ""},${anchor.port || ""}`;
}

function sharedConnectivityAnchor(cn, anchors, index) {
  const xs = anchors.map((anchor) => anchor.x);
  const ys = anchors.map((anchor) => anchor.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const sameNode = new Set(anchors.map((anchor) => anchor.nodeId).filter(Boolean)).size <= 1;
  const portSet = new Set(anchors.map((anchor) => anchor.port));
  const ports = [...portSet].filter(Boolean);
  let x = (minX + maxX) / 2;
  let y = (minY + maxY) / 2;

  if (sameNode && portSet.has("top") && !portSet.has("bottom")) {
    y = Math.min(...anchors.filter((anchor) => anchor.port === "top").map((anchor) => anchor.y));
  } else if (sameNode && portSet.has("bottom") && !portSet.has("top")) {
    y = Math.max(...anchors.filter((anchor) => anchor.port === "bottom").map((anchor) => anchor.y));
  } else if (maxY - minY <= 10) {
    y = ys.reduce((sum, value) => sum + value, 0) / ys.length;
  } else if (maxX - minX <= 10) {
    x = xs.reduce((sum, value) => sum + value, 0) / xs.length;
  }

  return {
    eqId: "",
    nodeId: `cn:${cleanId(cn)}`,
    port: ports.length === 1 ? ports[0] : "junction",
    cn,
    x: Math.round(x),
    y: Math.round(y),
    virtual: true,
    shared: true,
    order: index
  };
}

function distance(a, b) {
  return Math.hypot((a.x || 0) - (b.x || 0), (a.y || 0) - (b.y || 0));
}

function orientInlineCns(eqId, cns, context) {
  if (!cns || cns.length < 2) return cns || [];
  const leftScore = inlineCnNeighborX(cns[0], eqId, context);
  const rightScore = inlineCnNeighborX(cns[1], eqId, context);
  if (Number.isFinite(leftScore) && Number.isFinite(rightScore) && leftScore > rightScore) {
    return [cns[1], cns[0], ...cns.slice(2)];
  }
  return cns;
}

function inlineCnNeighborX(startCn, ownerEqId, context) {
  const { equipment, eqToCn, cnToEq, positions, layoutNodes } = context;
  const queue = [{ type: "cn", id: startCn, depth: 0 }];
  const seenCn = new Set([startCn]);
  const seenEq = new Set([ownerEqId]);
  while (queue.length) {
    const cur = queue.shift();
    if (cur.depth > 6) continue;
    if (cur.type === "cn") {
      for (const nextEqId of cnToEq.get(cur.id) || []) {
        if (seenEq.has(nextEqId)) continue;
        seenEq.add(nextEqId);
        const item = equipment.get(nextEqId);
        if (!item) continue;
        if ((isVisibleSwitch(item) || item.tag === "PowerTransformer") && positions[nextEqId]) {
          return positions[nextEqId].x;
        }
        if (canTraverseForInlineOrientation(item)) {
          queue.push({ type: "eq", id: nextEqId, depth: cur.depth + 1 });
        }
      }
    } else {
      for (const nextCn of eqToCn.get(cur.id) || []) {
        if (seenCn.has(nextCn)) continue;
        seenCn.add(nextCn);
        queue.push({ type: "cn", id: nextCn, depth: cur.depth + 1 });
      }
    }
  }
  return NaN;
}

function canTraverseForInlineOrientation(item) {
  return (
    canTraverseForAnchor(item) ||
    item.tag === "ACLineSegment" ||
    item.tag === "Jumper"
  );
}

function buildWires({ equipment, eqToCn, cnToEq, anchorsByCn, connectivityAnchors, currentCircuit }) {
  const wires = [];
  const virtualAnchors = new Map();
  const drawableTags = new Set(["ACLineSegment", "Jumper"]);
  const deferred = [];
  const anchorContext = { equipment, eqToCn, cnToEq, anchorsByCn, connectivityAnchors };
  const drawableLineIds = drawableLineComponentsToRender(anchorContext);

  function pushWire(item, from, to) {
    if (!from || !to) return false;
    if (from.eqId && from.eqId === to.eqId && from.port === to.port) return false;
    if (!from.eqId && !to.eqId && from.cn === to.cn) return false;
    wires.push({
      id: item.id,
      name: item.name || item.mrid || item.id,
      tag: item.tag,
      from,
      to,
      equipmentIds: [item.id],
      skipLabel: item.skipLabel || false,
      related: !!(currentCircuit && item.container && item.container.startsWith("CIRCUIT_") && item.container !== currentCircuit.id)
    });
    return true;
  }

  for (const item of equipment.values()) {
    if (!drawableTags.has(item.tag)) continue;
    if (isInternalCabinetLine(item)) continue;
    if (!drawableLineIds.has(item.id)) continue;
    const cns = [...(eqToCn.get(item.id) || [])];
    if (cns.length < 2) continue;
    let from = resolveAnchorForCn(cns[0], item.id, anchorContext);
    let to = resolveAnchorForCn(cns[1], item.id, anchorContext);
    if (!from && !to) {
      deferred.push({ item, cns });
      continue;
    }
    if (!from && to) from = virtualLineAnchor(cns[0], to, virtualAnchors);
    if (!to && from) to = virtualLineAnchor(cns[1], from, virtualAnchors);
    if (isSameCabinetSwitchLink(item, from, to, equipment)) continue;
    pushWire(item, from, to);
  }

  let changed = true;
  while (changed) {
    changed = false;
    for (let index = deferred.length - 1; index >= 0; index--) {
      const { item, cns } = deferred[index];
      let from = virtualAnchors.get(cns[0]) || resolveAnchorForCn(cns[0], item.id, anchorContext);
      let to = virtualAnchors.get(cns[1]) || resolveAnchorForCn(cns[1], item.id, anchorContext);
      if (!from && to) from = virtualLineAnchor(cns[0], to, virtualAnchors);
      if (!to && from) to = virtualLineAnchor(cns[1], from, virtualAnchors);
      if (isSameCabinetSwitchLink(item, from, to, equipment)) {
        deferred.splice(index, 1);
        changed = true;
        continue;
      }
      if (pushWire(item, from, to)) {
        deferred.splice(index, 1);
        changed = true;
      }
    }
  }

  for (const item of equipment.values()) {
    if (item.tag !== "PowerTransformer") continue;
    if (wires.some((wire) => wire.from.eqId === item.id || wire.to.eqId === item.id)) continue;
    const cns = [...(eqToCn.get(item.id) || [])];
    if (!cns.length) continue;
    const transformerAnchor = findAnchorForEquipment(anchorsByCn, item.id);
    if (!transformerAnchor) continue;
    const sourceAnchor = resolveAnchorForCn(cns[0], item.id, anchorContext);
    if (!sourceAnchor || sourceAnchor.eqId === item.id) continue;
    wires.push({
      id: `LEAD_${item.id}`,
      name: item.dispatchNumber || item.name || item.id,
      tag: "TransformerLead",
      from: sourceAnchor,
      to: transformerAnchor,
      equipmentIds: [item.id],
      related: false
    });
  }

  for (const anchor of connectivityAnchors.values()) {
    for (const terminal of anchor.leadAnchors || []) {
      if (!terminal.eqId || distance(anchor, terminal) < 3) continue;
      wires.push({
        id: `CNLEAD_${cleanId(anchor.cn)}_${cleanId(terminal.eqId)}_${terminal.port || "p"}`,
        name: anchor.cn,
        tag: "ConnectivityLead",
        from: anchor,
        to: terminal,
        equipmentIds: [terminal.eqId],
        skipLabel: true,
        related: false
      });
    }
  }

  const junctionsByCn = new Map();
  for (const [cn, anchor] of connectivityAnchors) junctionsByCn.set(cn, anchor);
  for (const [cn, anchor] of virtualAnchors) {
    if (!junctionsByCn.has(cn)) junctionsByCn.set(cn, anchor);
  }
  const simplifiedWires = collapseVirtualWireChains(wires);
  const usedJunctionNodes = new Set(
    simplifiedWires.flatMap((wire) =>
      [wire.from, wire.to]
        .filter((endpoint) => endpoint && !endpoint.eqId && endpoint.nodeId)
        .map((endpoint) => endpoint.nodeId)
    )
  );

  return {
    wires: simplifiedWires,
    suppressedDanglingLines: [...equipment.values()]
      .filter((item) => drawableTags.has(item.tag) && !isInternalCabinetLine(item) && !drawableLineIds.has(item.id))
      .map((item) => item.id),
    junctions: [...junctionsByCn.values()].filter((anchor) =>
      usedJunctionNodes.has(anchor.nodeId)
    )
  };
}

function isSameCabinetSwitchLink(item, from, to, equipment) {
  if (!item || !["ACLineSegment", "Jumper"].includes(item.tag)) return false;
  if (!from || !to || !from.eqId || !to.eqId) return false;
  if (!from.nodeId || from.nodeId !== to.nodeId || !from.nodeId.startsWith("site:")) return false;
  if (from.port !== to.port || !["top", "bottom"].includes(from.port)) return false;
  return isVisibleSwitch(equipment.get(from.eqId)) && isVisibleSwitch(equipment.get(to.eqId));
}

function drawableLineComponentsToRender(context) {
  const { equipment, eqToCn, cnToEq } = context;
  const activeIds = new Set(
    [...equipment.values()]
      .filter((item) => ["ACLineSegment", "Jumper"].includes(item.tag) && !isInternalCabinetLine(item))
      .map((item) => item.id)
  );
  const lineToCns = new Map();
  const cnToLines = new Map();
  const attachmentByCn = new Map();

  for (const eqId of activeIds) {
    const cns = [...(eqToCn.get(eqId) || [])];
    lineToCns.set(eqId, cns);
    for (const cn of cns) {
      if (!cnToLines.has(cn)) cnToLines.set(cn, new Set());
      cnToLines.get(cn).add(eqId);
    }
  }

  for (const [cn, lineIds] of cnToLines) {
    for (const lineId of lineIds) {
      const anchor = resolveAnchorForCn(cn, lineId, context);
      if (!anchor) continue;
      attachmentByCn.set(cn, lineAttachmentKey(anchor));
      break;
    }
  }

  const leafQueue = [];
  const queued = new Set();
  const enqueueLeaf = (cn) => {
    const lines = cnToLines.get(cn);
    if (!lines || lines.size > 1 || attachmentByCn.has(cn) || queued.has(cn)) return;
    queued.add(cn);
    leafQueue.push(cn);
  };
  for (const cn of cnToLines.keys()) enqueueLeaf(cn);

  while (leafQueue.length) {
    const cn = leafQueue.shift();
    queued.delete(cn);
    const lines = cnToLines.get(cn);
    if (!lines || lines.size !== 1 || attachmentByCn.has(cn)) continue;
    const [lineId] = lines;
    if (!activeIds.delete(lineId)) continue;
    for (const endpointCn of lineToCns.get(lineId) || []) {
      cnToLines.get(endpointCn)?.delete(lineId);
      enqueueLeaf(endpointCn);
    }
  }

  const keep = new Set();
  const visited = new Set();

  for (const startId of activeIds) {
    if (visited.has(startId)) continue;
    const component = [];
    const attachmentKeys = new Set();
    const queue = [startId];
    visited.add(startId);

    while (queue.length) {
      const eqId = queue.shift();
      component.push(eqId);
      for (const cn of lineToCns.get(eqId) || []) {
        const attachmentKey = attachmentByCn.get(cn);
        if (attachmentKey) attachmentKeys.add(attachmentKey);
        for (const nextEqId of cnToEq.get(cn) || []) {
          if (!activeIds.has(nextEqId) || visited.has(nextEqId)) continue;
          visited.add(nextEqId);
          queue.push(nextEqId);
        }
      }
    }

    if (attachmentKeys.size >= 2) {
      for (const eqId of component) keep.add(eqId);
    }
  }

  return keep;
}

function lineAttachmentKey(anchor) {
  if (anchor.shared && anchor.cn) return `cn:${anchor.cn}`;
  return [
    anchor.eqId || "",
    anchor.nodeId || "",
    anchor.port || "",
    Math.round(anchor.x || 0),
    Math.round(anchor.y || 0)
  ].join("|");
}

function collapseVirtualWireChains(inputWires) {
  const wires = [...inputWires];
  const drawableTags = new Set(["ACLineSegment", "Jumper"]);
  let changed = true;

  while (changed) {
    changed = false;
    const incidents = new Map();
    for (let index = 0; index < wires.length; index++) {
      const wire = wires[index];
      for (const side of ["from", "to"]) {
        const endpoint = wire[side];
        if (
          !endpoint ||
          endpoint.eqId ||
          !endpoint.nodeId ||
          !endpoint.nodeId.startsWith("cn:")
        ) {
          continue;
        }
        if (!incidents.has(endpoint.nodeId)) incidents.set(endpoint.nodeId, []);
        incidents.get(endpoint.nodeId).push({ index, side });
      }
    }

    for (const [nodeId, entries] of incidents) {
      if (entries.length !== 2 || entries[0].index === entries[1].index) continue;
      const first = wires[entries[0].index];
      const second = wires[entries[1].index];
      if (!drawableTags.has(first.tag) || !drawableTags.has(second.tag)) continue;
      const firstEndpoint = first[entries[0].side];
      const secondEndpoint = second[entries[1].side];
      if ((firstEndpoint && firstEndpoint.shared) || (secondEndpoint && secondEndpoint.shared)) continue;
      const firstOther = first[entries[0].side === "from" ? "to" : "from"];
      const secondOther = second[entries[1].side === "from" ? "to" : "from"];
      if (!firstOther || !secondOther) continue;
      if (firstOther.nodeId && firstOther.nodeId === secondOther.nodeId) continue;

      const merged = {
        ...first,
        id: first.id,
        name: first.name || second.name,
        tag: first.tag === second.tag ? first.tag : "ACLineSegment",
        from: firstOther,
        to: secondOther,
        equipmentIds: [
          ...new Set([...(first.equipmentIds || []), ...(second.equipmentIds || [])])
        ],
        skipLabel: !!first.skipLabel && !!second.skipLabel,
        related: !!first.related || !!second.related,
        collapsedNodes: [
          ...(first.collapsedNodes || []),
          nodeId,
          ...(second.collapsedNodes || [])
        ]
      };
      const remove = [entries[0].index, entries[1].index].sort((a, b) => b - a);
      for (const index of remove) wires.splice(index, 1);
      wires.push(merged);
      changed = true;
      break;
    }
  }

  return wires;
}

function virtualLineAnchor(cn, nearAnchor, virtualAnchors) {
  if (virtualAnchors.has(cn)) return virtualAnchors.get(cn);
  const anchor = danglingLineAnchor(nearAnchor, cn, virtualAnchors.size);
  anchor.port = "junction";
  virtualAnchors.set(cn, anchor);
  return anchor;
}

function danglingLineAnchor(anchor, cn, index) {
  const spread = (index % 5) * 18;
  if (anchor.port === "left") {
    return { eqId: "", nodeId: `cn:${cleanId(cn)}`, port: "right", cn, x: anchor.x - 140 - spread, y: anchor.y, virtual: true };
  }
  if (anchor.port === "right") {
    return { eqId: "", nodeId: `cn:${cleanId(cn)}`, port: "left", cn, x: anchor.x + 140 + spread, y: anchor.y, virtual: true };
  }
  if (anchor.port === "top") {
    return { eqId: "", nodeId: `cn:${cleanId(cn)}`, port: "bottom", cn, x: anchor.x, y: anchor.y - 120 - spread, virtual: true };
  }
  return { eqId: "", nodeId: `cn:${cleanId(cn)}`, port: "top", cn, x: anchor.x, y: anchor.y + 120 + spread, virtual: true };
}

function findAnchorForEquipment(anchorsByCn, eqId) {
  for (const anchors of anchorsByCn.values()) {
    const anchor = anchors.find((item) => item.eqId === eqId);
    if (anchor) return anchor;
  }
  return null;
}

function resolveAnchorForCn(startCn, excludedEqId, context) {
  const { equipment, eqToCn, cnToEq, anchorsByCn, connectivityAnchors } = context;
  const queue = [{ cn: startCn, depth: 0 }];
  const seenCn = new Set([startCn]);
  const seenEq = new Set([excludedEqId]);

  while (queue.length) {
    const { cn, depth } = queue.shift();
    const sharedAnchor = connectivityAnchors && connectivityAnchors.get(cn);
    const anchors = (anchorsByCn.get(cn) || []).filter((item) => item.eqId !== excludedEqId);
    const picked = pickAnchor(anchors);
    if (sharedAnchor && shouldPreferTerminalAnchor(sharedAnchor, anchors)) return picked;
    if (sharedAnchor) return sharedAnchor;
    if (picked) return picked;
    if (depth > 8) continue;

    for (const eqId of cnToEq.get(cn) || []) {
      if (seenEq.has(eqId)) continue;
      seenEq.add(eqId);
      const item = equipment.get(eqId);
      if (!item || !canTraverseForAnchor(item)) continue;
      for (const nextCn of eqToCn.get(eqId) || []) {
        if (seenCn.has(nextCn)) continue;
        seenCn.add(nextCn);
        queue.push({ cn: nextCn, depth: depth + 1 });
      }
    }
  }

  return null;
}

function shouldPreferTerminalAnchor(sharedAnchor, anchors) {
  if (!sharedAnchor || !anchors || anchors.length !== 1) return false;
  const anchor = anchors[0];
  return !!anchor.eqId && distance(sharedAnchor, anchor) <= 4;
}

function pickAnchor(anchors) {
  if (!anchors || !anchors.length) return null;
  return (
    anchors.find((item) => item.port === "bottom") ||
    anchors.find((item) => item.port === "top") ||
    anchors[0]
  );
}

function canTraverseForAnchor(item) {
  return (
    isHiddenCabinetSwitch(item) ||
    isInternalCabinetLine(item) ||
    item.tag === "BusbarSection" ||
    item.tag === "Jumper" ||
    item.tag === "EnergyConsumer"
  );
}

function computeEnergized(graph, switchState) {
  const visitedEq = new Set();
  const visitedCn = new Set();
  const queue = [];

  const isConductive = (eqId) => {
    const item = graph.equipmentById[eqId];
    if (!item) return false;
    if (item.tag === "GroundDisconnector") return false;
    if (SWITCH_TAGS.has(item.tag)) return switchState[eqId] !== false;
    return true;
  };

  const sources = (graph.sourceBreakers && graph.sourceBreakers.length ? graph.sourceBreakers : [graph.sourceBreaker])
    .filter((id) => id && graph.equipmentById[id]);
  if (!sources.length && graph.equipment[0] && isConductive(graph.equipment[0].id)) sources.push(graph.equipment[0].id);
  const activeSources = sources.filter(isConductive);
  if (!activeSources.length) {
    return { equipment: [], connectivityNodes: [], loopedEquipment: [], loopedConnectivityNodes: [] };
  }
  for (const source of activeSources) {
    if (visitedEq.has(source)) continue;
    queue.push({ type: "eq", id: source });
    visitedEq.add(source);
  }

  while (queue.length) {
    const cur = queue.shift();
    if (cur.type === "eq") {
      if (!isConductive(cur.id)) continue;
      for (const cn of graph.eqToCn[cur.id] || []) {
        if (visitedCn.has(cn)) continue;
        visitedCn.add(cn);
        queue.push({ type: "cn", id: cn });
      }
    } else {
      for (const eqId of graph.cnToEq[cur.id] || []) {
        if (visitedEq.has(eqId)) continue;
        visitedEq.add(eqId);
        queue.push({ type: "eq", id: eqId });
      }
    }
  }
  const sourceOwners = new Map(
    activeSources.map((id) => {
      const source = (graph.sources || []).find((item) => item.id === id);
      const equipment = graph.equipmentById[id];
      return [id, (source && source.owner) || (equipment && equipment.container) || id];
    })
  );
  const looped = computeLoopedComponents(graph, isConductive, sourceOwners);
  return {
    equipment: [...visitedEq],
    connectivityNodes: [...visitedCn],
    loopedEquipment: [...looped.equipment],
    loopedConnectivityNodes: [...looped.connectivityNodes]
  };
}

function computeLoopedComponents(graph, isConductive, activeSourceOwners) {
  const seenEq = new Set();
  const seenCn = new Set();
  const loopedEq = new Set();
  const loopedCn = new Set();

  for (const item of graph.equipment || []) {
    if (seenEq.has(item.id) || !isConductive(item.id)) continue;
    const componentEq = new Set();
    const componentCn = new Set();
    const queue = [{ type: "eq", id: item.id }];
    seenEq.add(item.id);

    while (queue.length) {
      const cur = queue.shift();
      if (cur.type === "eq") {
        componentEq.add(cur.id);
        for (const cn of graph.eqToCn[cur.id] || []) {
          if (seenCn.has(cn)) continue;
          seenCn.add(cn);
          queue.push({ type: "cn", id: cn });
        }
      } else {
        componentCn.add(cur.id);
        for (const eqId of graph.cnToEq[cur.id] || []) {
          if (seenEq.has(eqId) || !isConductive(eqId)) continue;
          seenEq.add(eqId);
          queue.push({ type: "eq", id: eqId });
        }
      }
    }

    const sourceOwners = new Set();
    for (const eqId of componentEq) {
      const owner = activeSourceOwners.get(eqId);
      if (owner) sourceOwners.add(owner);
    }
    if (sourceOwners.size >= 2) {
      for (const eqId of componentEq) loopedEq.add(eqId);
      for (const cn of componentCn) loopedCn.add(cn);
    }
  }

  return { equipment: loopedEq, connectivityNodes: loopedCn };
}

module.exports = {
  buildTopologyFromFile,
  buildTopology,
  computeEnergized,
  SWITCH_TAGS
};
