//运行状态分析器：从电源出发追踪所有设备的带电/失电状态
//从电源出发追踪所有设备的带电/失电状态
//算法: 多源 BFS（广度优先搜索）
// 1. 初始化:
//    - 从所有电源点（变电站出线开关）出发
//    - 每个电源分配一个唯一"域"和颜色
// 2. BFS 遍历:
//    - 遇到合的开关 → 可以通过，继续往下走
//    - 遇到分的开关 → 阻挡，标记为失电
//    - 遇到接地开关 → 不导电
//    - 其他设备 → 默认导电
// 3. 结果判定:
//    - 设备只被一个电源到达 → 正常供电
//    - 设备没被任何电源到达 → 失电
//    - 设备被多个电源到达 → 合环（危险！）
//    - 开关两侧连不同电源 → 联络点
const SWITCH_TAGS = new Set(["Breaker", "LoadBreakSwitch", "Disconnector", "GroundDisconnector", "Fuse"]);

function computeOperationalState(graph, switchState = {}) {
  const equipmentDomains = new Map();
  const connectivityDomains = new Map();
  const queue = [];
  const switchIds = new Set((graph.switches || []).map((item) => item.id));
  const isConductive = (eqId) => {
    const eq = graph.equipmentById[eqId];
    if (!eq) return false;
    if (eq.tag === "GroundDisconnector") return false;
    if (switchIds.has(eqId) || SWITCH_TAGS.has(eq.tag)) return switchState[eqId] !== false;
    return true;
  };

  function setDomain(map, id, domain, distance) {
    if (!id || !domain) return false;
    if (!map.has(id)) map.set(id, new Map());
    const domains = map.get(id);
    const domainId = domain.id || domain.owner;
    const current = domains.get(domainId);
    if (current && current.distance <= distance) return false;
    domains.set(domainId, { ...domain, distance });
    return true;
  }

  const sourceDefs = (
    graph.sources && graph.sources.length
      ? graph.sources
      : (graph.sourceBreakers || [graph.sourceBreaker]).filter(Boolean).map((id, index) => ({
          id,
          nodeId: "",
          color: ["rgb(0,255,0)", "rgb(0,210,255)", "rgb(255,0,255)", "rgb(255,220,0)"][index % 4],
          label: (graph.equipmentById[id] && (graph.equipmentById[id].dispatchNumber || graph.equipmentById[id].name)) || ""
        }))
  ).filter((source) => source.id && graph.equipmentById[source.id] && isConductive(source.id));

  for (const source of sourceDefs) {
    const domain = {
      id: source.id,
      owner: source.owner || source.nodeId || source.id,
      nodeId: source.nodeId || "",
      color: source.color,
      label: source.label || ""
    };
    setDomain(equipmentDomains, source.id, domain, 0);
    queue.push({ type: "eq", id: source.id, domain, distance: 0 });
  }

  while (queue.length) {
    const cur = queue.shift();
    if (cur.type === "eq") {
      if (!isConductive(cur.id)) continue;
      for (const cn of graph.eqToCn[cur.id] || []) {
        const distance = cur.distance + 1;
        if (setDomain(connectivityDomains, cn, cur.domain, distance)) {
          queue.push({ type: "cn", id: cn, domain: cur.domain, distance });
        }
      }
    } else {
      for (const eqId of graph.cnToEq[cur.id] || []) {
        const eq = graph.equipmentById[eqId];
        if (!eq || eq.tag === "GroundDisconnector") continue;
        const distance = cur.distance + 1;
        const changed = setDomain(equipmentDomains, eqId, cur.domain, distance);
        if (changed && isConductive(eqId)) {
          queue.push({ type: "eq", id: eqId, domain: cur.domain, distance });
        }
      }
    }
  }

  const looped = computeLoopedOperationalPaths(graph, switchState, sourceDefs, isConductive);
  const tiePoints = { ...looped.tiePoints };
  for (const item of graph.switches || []) {
    if (item.tag === "GroundDisconnector") continue;
    if (tiePoints[item.id]) continue;
    const sides = (graph.eqToCn[item.id] || []).map((cn) => ({
      cn,
      domains: operationalDomains(connectivityDomains.get(cn))
    }));
    const ownerSets = sides
      .filter((side) => side.domains.length)
      .map((side) => new Set(side.domains.map((domain) => domain.owner)));
    const separated =
      ownerSets.length >= 2 &&
      ownerSets.some((owners, index) =>
        ownerSets.some((other, otherIndex) => otherIndex > index && [...owners].every((owner) => !other.has(owner)))
      );
    const owners = new Set(sides.flatMap((side) => side.domains.map((domain) => domain.owner)));
    const isTiePoint = separated || (!!item.isTiePoint && owners.size > 1);
    if (isTiePoint) tiePoints[item.id] = { sides, closed: switchState[item.id] !== false };
  }

  return {
    equipment: [...equipmentDomains.keys()],
    connectivityNodes: [...connectivityDomains.keys()],
    loopedEquipment: [...looped.equipment],
    loopedConnectivityNodes: [...looped.connectivityNodes],
    equipmentDomains: Object.fromEntries([...equipmentDomains].map(([id, domains]) => [id, operationalDomains(domains)])),
    connectivityDomains: Object.fromEntries([...connectivityDomains].map(([id, domains]) => [id, operationalDomains(domains)])),
    tiePoints,
    loopEquipmentOwners: looped.equipmentOwners,
    loopConnectivityOwners: looped.connectivityOwners
  };
}

function computeLoopedOperationalPaths(graph, switchState, sourceDefs, isConductive) {
  const loopedEquipment = new Set();
  const loopedConnectivityNodes = new Set();
  const equipmentOwnerSets = new Map();
  const connectivityOwnerSets = new Map();
  const tiePoints = {};
  const sourceById = new Map(sourceDefs.map((source) => [source.id, source]));

  for (const tie of graph.switches || []) {
    if (!tie.isTiePoint || switchState[tie.id] === false || tie.tag === "GroundDisconnector") continue;
    const sideCns = graph.eqToCn[tie.id] || [];
    if (sideCns.length < 2) continue;
    const sidePaths = sideCns.map((cn) =>
      shortestSourcePaths(graph, cn, tie.id, sourceById, isConductive)
    );
    let best = null;
    for (let leftIndex = 0; leftIndex < sidePaths.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < sidePaths.length; rightIndex += 1) {
        for (const left of sidePaths[leftIndex]) {
          for (const right of sidePaths[rightIndex]) {
            if (left.owner === right.owner) continue;
            const distance = left.distance + right.distance;
            if (!best || distance < best.distance) {
              best = { leftIndex, rightIndex, left, right, distance };
            }
          }
        }
      }
    }
    if (!best) continue;

    addLoopPath(best.left, loopedEquipment, loopedConnectivityNodes, equipmentOwnerSets, connectivityOwnerSets);
    addLoopPath(best.right, loopedEquipment, loopedConnectivityNodes, equipmentOwnerSets, connectivityOwnerSets);
    loopedEquipment.add(tie.id);
    for (const cn of sideCns) loopedConnectivityNodes.add(cn);
    tiePoints[tie.id] = {
      closed: true,
      sides: sideCns.map((cn, index) => {
        const path =
          index === best.leftIndex ? best.left :
          index === best.rightIndex ? best.right :
          null;
        return { cn, domains: path ? [sourcePathDomain(path)] : [] };
      })
    };
  }

  return {
    equipment: loopedEquipment,
    connectivityNodes: loopedConnectivityNodes,
    equipmentOwners: ownerSetsToObject(equipmentOwnerSets),
    connectivityOwners: ownerSetsToObject(connectivityOwnerSets),
    tiePoints
  };
}

function shortestSourcePaths(graph, startCn, blockedSwitchId, sourceById, isConductive) {
  const startKey = `cn:${startCn}`;
  const queue = [{ type: "cn", id: startCn, key: startKey, distance: 0 }];
  const seen = new Set([startKey]);
  const parent = new Map();
  const resultByOwner = new Map();

  while (queue.length) {
    const current = queue.shift();
    if (current.type === "eq") {
      const source = sourceById.get(current.id);
      if (source) {
        const owner = source.owner || source.nodeId || source.id;
        if (!resultByOwner.has(owner)) {
          resultByOwner.set(owner, reconstructSourcePath(current, parent, source, owner));
        }
      }
      if (current.id === blockedSwitchId || !isConductive(current.id)) continue;
      for (const cn of graph.eqToCn[current.id] || []) {
        enqueuePathStep(queue, seen, parent, current, "cn", cn);
      }
    } else {
      for (const eqId of graph.cnToEq[current.id] || []) {
        if (eqId === blockedSwitchId || !isConductive(eqId)) continue;
        enqueuePathStep(queue, seen, parent, current, "eq", eqId);
      }
    }
  }

  return [...resultByOwner.values()];
}

function enqueuePathStep(queue, seen, parent, previous, type, id) {
  const key = `${type}:${id}`;
  if (!id || seen.has(key)) return;
  seen.add(key);
  parent.set(key, previous.key);
  queue.push({ type, id, key, distance: previous.distance + 1 });
}

function reconstructSourcePath(current, parent, source, owner) {
  const equipment = new Set();
  const connectivityNodes = new Set();
  let key = current.key;
  while (key) {
    const separator = key.indexOf(":");
    const type = key.slice(0, separator);
    const id = key.slice(separator + 1);
    if (type === "eq") equipment.add(id);
    else connectivityNodes.add(id);
    key = parent.get(key);
  }
  return { source, owner, distance: current.distance, equipment, connectivityNodes };
}

function addLoopPath(path, loopedEquipment, loopedConnectivityNodes, equipmentOwnerSets, connectivityOwnerSets) {
  for (const eqId of path.equipment) {
    loopedEquipment.add(eqId);
    addOwner(equipmentOwnerSets, eqId, path.owner);
  }
  for (const cn of path.connectivityNodes) {
    loopedConnectivityNodes.add(cn);
    addOwner(connectivityOwnerSets, cn, path.owner);
  }
}

function addOwner(ownerSets, id, owner) {
  if (!id || !owner) return;
  if (!ownerSets.has(id)) ownerSets.set(id, new Set());
  ownerSets.get(id).add(owner);
}

function ownerSetsToObject(ownerSets) {
  return Object.fromEntries([...ownerSets].map(([id, owners]) => [id, [...owners]]));
}

function sourcePathDomain(path) {
  return {
    id: path.source.id,
    owner: path.owner,
    nodeId: path.source.nodeId || "",
    color: path.source.color,
    label: path.source.label || ""
  };
}

function operationalDomains(domains) {
  if (!domains) return [];
  return [...domains.values()]
    .sort((a, b) => (a.distance ?? 9999) - (b.distance ?? 9999))
    .map((domain) => ({
      id: domain.id || "",
      owner: domain.owner,
      nodeId: domain.nodeId || "",
      color: domain.color,
      label: domain.label || ""
    }));
}

function diffOperationalState(graph, before, after) {
  const beforeEq = new Set(before.equipment || []);
  const afterEq = new Set(after.equipment || []);
  const beforeLoop = new Set(before.loopedEquipment || []);
  const afterLoop = new Set(after.loopedEquipment || []);
  const outagedEquipment = [...beforeEq].filter((id) => !afterEq.has(id));
  const restoredEquipment = [...afterEq].filter((id) => !beforeEq.has(id));
  const newlyLoopedEquipment = [...afterLoop].filter((id) => !beforeLoop.has(id));
  const clearedLoopedEquipment = [...beforeLoop].filter((id) => !afterLoop.has(id));
  const transformers = graph.transformers || [];
  return {
    outagedEquipment,
    restoredEquipment,
    newlyLoopedEquipment,
    clearedLoopedEquipment,
    outagedTransformers: transformers.filter((item) => beforeEq.has(item.id) && !afterEq.has(item.id)).map((item) => item.id),
    restoredTransformers: transformers.filter((item) => !beforeEq.has(item.id) && afterEq.has(item.id)).map((item) => item.id)
  };
}

module.exports = {
  computeOperationalState,
  diffOperationalState,
  SWITCH_TAGS
};
