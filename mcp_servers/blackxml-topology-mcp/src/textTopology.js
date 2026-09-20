//生成拓扑文本描述
//输入：拓扑图 + 开关状态 输出：AI 可读的文字描述
const TEXT_SWITCH_TAGS = new Set([
  "Breaker",
  "LoadBreakSwitch",
  "Disconnector",
  "Fuse"
]);
const { compareSwitchOrder, switchDisplayLabel } = require("./switchOrder");

function buildTopologyText(topology, switchStates = {}) {
  const graph = topology && topology.graph;
  const layout = topology && topology.layout;
  if (!graph || !layout) throw new Error("拓扑数据不完整");

  const states = { ...(graph.initialSwitchState || {}), ...(switchStates || {}) };
  const sourceIds = new Set((graph.sources || []).map((item) => item.id));
  const visibleSwitches = (graph.switches || []).filter((item) =>
    isTextSwitch(item, sourceIds)
  );
  const switchIds = new Set(visibleSwitches.map((item) => item.id));
  for (const sourceId of sourceIds) switchIds.add(sourceId);

  const adjacency = buildSwitchAdjacency(graph, switchIds);
  const sources = orderedSources(topology, states);
  if (!sources.length) throw new Error("未找到站内电源开关");

  const forest = buildSourceForest(adjacency, sources, switchIds, graph);
  const lines = [];

  for (const source of sources) {
    lines.push(`${sourceRootName(source, graph, layout)}/`);
    appendTreeLines({
      lines,
      parentId: source.id,
      parentOfParentId: "",
      children: forest.children,
      adjacency,
      forest,
      graph,
      layout,
      states,
      prefix: ""
    });
    if (!(forest.children.get(source.id) || []).length) {
      lines.push("└── （无下级开关）");
    }
    lines.push("");
  }

  if (forest.unassigned.length) {
    lines.push("未接入带电电源/");
    forest.unassigned.forEach((id, index) => {
      const isLast = index === forest.unassigned.length - 1;
      appendDetachedTree({
        lines,
        id,
        parentId: "",
        adjacency,
        seen: new Set(),
        graph,
        layout,
        states,
        prefix: "",
        isLast
      });
    });
    lines.push("");
  }

  const links = crossSourceLinks(adjacency, forest, sources, graph, layout, states);
  if (links.length) {
    lines.push("联络关系/");
    links.forEach((link, index) => {
      lines.push(`${index === links.length - 1 ? "└──" : "├──"} ${link}`);
    });
    lines.push("");
  }

  return `${lines.join("\r\n").trimEnd()}\r\n`;
}

function isTextSwitch(item, sourceIds) {
  if (!item || !TEXT_SWITCH_TAGS.has(item.tag)) return false;
  if (sourceIds.has(item.id)) return true;
  if (item.tag !== "Disconnector") return true;
  if (item.container && item.container.startsWith("SUBST_")) return false;
  const name = String(item.dispatchNumber || item.name || item.mrid || item.id)
    .trim()
    .toUpperCase()
    .replace(/\s+/g, "");
  return !(/^\d{3,4}$/.test(name) && name.endsWith("4"));
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

function orderedSources(topology, states) {
  const sources = [...(topology.graph.sources || [])];
  const currentSource = topology.graph.sourceBreaker;
  sources.sort((a, b) => {
    if (a.id === currentSource) return -1;
    if (b.id === currentSource) return 1;
    return 0;
  });
  const active = sources.filter((item) => states[item.id] !== false);
  return active.length ? active : sources;
}

function buildSourceForest(adjacency, sources, switchIds, graph) {
  const owner = new Map();
  const parent = new Map();
  const distance = new Map();
  const children = new Map();
  const queue = [];
  const sourceSet = new Set(sources.map((item) => item.id));

  sources.forEach((source, index) => {
    owner.set(source.id, index);
    distance.set(source.id, 0);
    queue.push(source.id);
  });

  while (queue.length) {
    const current = queue.shift();
    const neighbors = [...(adjacency.get(current) || [])].sort((a, b) => compareSwitchIds(a, b, graph));
    for (const next of neighbors) {
      if (sourceSet.has(next)) continue;
      if (owner.has(next)) continue;
      owner.set(next, owner.get(current));
      distance.set(next, (distance.get(current) || 0) + 1);
      parent.set(next, current);
      if (!children.has(current)) children.set(current, []);
      children.get(current).push(next);
      queue.push(next);
    }
  }

  const sizeMemo = new Map();
  const subtreeSize = (id) => {
    if (sizeMemo.has(id)) return sizeMemo.get(id);
    const size = 1 + (children.get(id) || []).reduce((sum, child) => sum + subtreeSize(child), 0);
    sizeMemo.set(id, size);
    return size;
  };
  for (const items of children.values()) {
    items.sort((a, b) => compareSwitchIds(a, b, graph) || subtreeSize(a) - subtreeSize(b) || a.localeCompare(b));
  }

  return {
    owner,
    parent,
    distance,
    children,
    unassigned: [...switchIds].filter((id) => !owner.has(id) && !sourceSet.has(id)).sort((a, b) => compareSwitchIds(a, b, graph))
  };
}

function compareSwitchIds(a, b, graph) {
  return compareSwitchOrder(graph.equipmentById[a], graph.equipmentById[b]) || String(a).localeCompare(String(b));
}

function appendTreeLines({
  lines,
  parentId,
  parentOfParentId = "",
  children,
  adjacency,
  forest,
  graph,
  layout,
  states,
  prefix
}) {
  const normalItems = children.get(parentId) || [];
  const extensionItems = tieExtensionChildren({
    id: parentId,
    parentId: parentOfParentId,
    normalItems,
    adjacency,
    forest,
    graph,
    layout,
    states
  });
  const items = [...normalItems, ...extensionItems.map((id) => ({ id, extension: true }))];
  const stopAtNextLevel = isOpenTiePoint(parentId, graph, states);
  items.forEach((id, index) => {
    const childId = typeof id === "string" ? id : id.id;
    const isExtension = typeof id !== "string" && id.extension;
    const isLast = index === items.length - 1;
    const childItems = stopAtNextLevel || isExtension ? [] : children.get(childId) || [];
    const childExtensionItems = stopAtNextLevel || isExtension
      ? []
      : tieExtensionChildren({
          id: childId,
          parentId,
          normalItems: childItems,
          adjacency,
          forest,
          graph,
          layout,
          states
        });
    lines.push(
      `${prefix}${isLast ? "└──" : "├──"} ${switchLabel(childId, graph, layout, states)}${childItems.length || childExtensionItems.length ? "/" : ""}`
    );
    if (childItems.length) {
      appendTreeLines({
        lines,
        parentId: childId,
        parentOfParentId: parentId,
        children,
        adjacency,
        forest,
        graph,
        layout,
        states,
        prefix: `${prefix}${isLast ? "    " : "│   "}`
      });
    }
  });
}

function isOpenTiePoint(id, graph, states) {
  const item = graph.equipmentById[id];
  return !!(item && item.isTiePoint && states[id] === false);
}

function tieExtensionChildren({
  id,
  parentId,
  normalItems,
  adjacency,
  forest,
  graph,
  layout,
  states
}) {
  if (!isOpenTiePoint(id, graph, states)) return [];
  const owner = forest.owner.get(id);
  const normalSet = new Set(normalItems || []);
  const candidates = [...(adjacency.get(id) || [])]
    .filter((next) => next !== parentId)
    .filter((next) => !normalSet.has(next))
    .filter((next) => !isSourceSwitch(next, graph))
    .filter((next) => {
      const nextOwner = forest.owner.get(next);
      return nextOwner === undefined || nextOwner !== owner;
    });
  if (!candidates.length) return [];

  const sameCabinet = candidates.filter((next) => sameLayoutNode(id, next, graph, layout));
  const pool = sameCabinet.length ? sameCabinet : candidates;
  const minDistance = Math.min(
    ...pool.map((next) => Number.isFinite(forest.distance.get(next)) ? forest.distance.get(next) : Number.MAX_SAFE_INTEGER)
  );
  return pool
    .filter((next) => {
      const distance = Number.isFinite(forest.distance.get(next)) ? forest.distance.get(next) : Number.MAX_SAFE_INTEGER;
      return distance === minDistance;
    })
    .sort((a, b) => switchLabel(a, graph, layout, states).localeCompare(switchLabel(b, graph, layout, states), "zh-Hans-CN"));
}

function isSourceSwitch(id, graph) {
  return (graph.sources || []).some((source) => source.id === id);
}

function sameLayoutNode(a, b, graph, layout) {
  const aItem = graph.equipmentById[a] || {};
  const bItem = graph.equipmentById[b] || {};
  const aNode = aItem.layoutNodeId || (layout.equipmentNode && layout.equipmentNode[a]) || "";
  const bNode = bItem.layoutNodeId || (layout.equipmentNode && layout.equipmentNode[b]) || "";
  return !!aNode && aNode === bNode;
}

function appendDetachedTree({
  lines,
  id,
  parentId,
  adjacency,
  seen,
  graph,
  layout,
  states,
  prefix,
  isLast
}) {
  if (seen.has(id)) return;
  seen.add(id);
  const children = [...(adjacency.get(id) || [])]
    .filter((next) => next !== parentId && !seen.has(next))
    .sort();
  lines.push(
    `${prefix}${isLast ? "└──" : "├──"} ${switchLabel(id, graph, layout, states)}${children.length ? "/" : ""}`
  );
  children.forEach((childId, index) => {
    appendDetachedTree({
      lines,
      id: childId,
      parentId: id,
      adjacency,
      seen,
      graph,
      layout,
      states,
      prefix: `${prefix}${isLast ? "    " : "│   "}`,
      isLast: index === children.length - 1
    });
  });
}

function crossSourceLinks(adjacency, forest, sources, graph, layout, states) {
  const sourceSet = new Set(sources.map((item) => item.id));
  const seen = new Set();
  const links = [];

  for (const [from, neighbors] of adjacency) {
    if (sourceSet.has(from) || !forest.owner.has(from)) continue;
    for (const to of neighbors) {
      if (sourceSet.has(to) || !forest.owner.has(to)) continue;
      const key = [from, to].sort().join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      if (forest.owner.get(from) === forest.owner.get(to)) continue;
      links.push(
        `${switchLabel(from, graph, layout, states)} ↔ ${switchLabel(to, graph, layout, states)}`
      );
    }
  }

  return links.sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

function sourceRootName(source, graph, layout) {
  const item = graph.equipmentById[source.id] || {};
  const node = source.nodeId && layout.nodes[source.nodeId];
  const station = String((node && node.name) || "").trim() || "未知电源站";
  const feeder = `${item.name || source.label || ""}${item.dispatchNumber || ""}`.replace(/\s+/g, "");
  return `${station}${feeder}`;
}

function switchLabel(id, graph, layout, states) {
  const item = graph.equipmentById[id] || {};
  const nodeId = item.layoutNodeId || (layout.equipmentNode && layout.equipmentNode[id]) || "";
  const node = nodeId && layout.nodes[nodeId];
  const cabinet = node && !node.isSource && node.kind !== "inline-switch"
    ? String(node.name || "").trim()
    : "";
  const number = String(switchDisplayLabel(item, id)).trim();
  const name = cabinet && number && !cabinet.includes(number)
    ? `${cabinet}${number}`
    : cabinet || number || id;
  const current = graph.switchCurrentById && graph.switchCurrentById[id];
  const currentText = current && current.display ? `,I=${current.display}` : "";
  return `${name}(${states[id] === false ? "分" : "合"}${currentText})`;
}

module.exports = {
  buildTopologyText
};
