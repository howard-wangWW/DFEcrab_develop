//渲染 SVG 图形
const { switchDisplayLabel } = require("./switchOrder");

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function symbolDefs() {
  return `
<defs>
  <symbol preserveAspectRatio="xMidYMid" id="terminal:端子"><circle visibility="hidden" cx="0" cy="0" r="1" /></symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 16 37" id="SwitchBox@0">
    <line stroke="rgb(0,255,0)" x1="8" y1="1" x2="8" y2="10" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="8" y1="27" x2="8" y2="36" stroke-width="1"/>
    <rect fill="rgb(0,255,0)" stroke="rgb(0,255,0)" stroke-width="1.4" x="3" y="10" width="10" height="17"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 16 37" id="SwitchBox@1">
    <line stroke="rgb(255,0,0)" x1="8" y1="1" x2="8" y2="10" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" x1="8" y1="27" x2="8" y2="36" stroke-width="1"/>
    <rect fill="none" stroke="rgb(255,0,0)" stroke-width="1.4" x="3" y="10" width="10" height="17"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 40 10" id="Breaker:断路器@0">
    <line stroke="rgb(0,255,0)" y1="5" x1="5" y2="5" x2="10" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" y1="5" x1="30" y2="5" x2="35" stroke-width="1"/>
    <rect fill="rgb(0,255,0)" stroke="rgb(0,255,0)" stroke-width="1" x="10" y="0" width="20" height="10"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 40 10" id="Breaker:断路器@1">
    <line stroke="rgb(255,0,0)" y1="5" x1="5" y2="5" x2="10" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="5" x1="30" y2="5" x2="35" stroke-width="1"/>
    <rect fill="none" stroke="rgb(255,0,0)" stroke-width="1" x="10" y="0" width="20" height="10"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 16 37" id="Breaker:断路器纵@0">
    <line stroke="rgb(255,0,0)" y1="36" x1="8" y2="25" x2="8" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="12" x1="8" y2="1" x2="8" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="9.7" x1="5" y2="14.7" x2="11" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="25.2" x1="8.1" y2="15" x2="1.1" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="14.7" x1="5.2" y2="9.7" x2="10.8" stroke-width="1"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 16 37" id="Breaker:断路器纵@1">
    <line stroke="rgb(255,0,0)" y1="36" x1="8" y2="25" x2="8" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="12" x1="8" y2="1" x2="8" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="9.7" x1="5" y2="14.7" x2="11" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="25.2" x1="8.1" y2="12" x2="8" stroke-width="1"/>
    <line stroke="rgb(255,0,0)" y1="14.7" x1="5.2" y2="9.7" x2="10.8" stroke-width="1"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 40 10" id="LoadBreakSwitch:负荷开关@0">
    <line stroke="rgb(0,255,0)" y1="5" x1="4" y2="5" x2="13" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" y1="5" x1="28" y2="5" x2="36" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" y1="5" x1="13" y2="0" x2="28" stroke-width="1"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="13" cy="5" r="1.5"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="28" cy="5" r="1.5"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 40 10" id="LoadBreakSwitch:负荷开关@1">
    <line stroke="rgb(255,0,0)" y1="5" x1="4" y2="5" x2="36" stroke-width="1"/>
    <circle fill="rgb(255,0,0)" stroke="rgb(255,0,0)" cx="13" cy="5" r="1.5"/>
    <circle fill="rgb(255,0,0)" stroke="rgb(255,0,0)" cx="28" cy="5" r="1.5"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 16 37" id="LoadBreakSwitch:负荷开关纵@0">
    <line stroke="rgb(0,255,0)" x1="8" y1="1" x2="8" y2="10" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="8" y1="27" x2="8" y2="36" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="8" y1="10" x2="2" y2="27" stroke-width="1"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="8" cy="10" r="1.5"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="8" cy="27" r="1.5"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 16 37" id="LoadBreakSwitch:负荷开关纵@1">
    <line stroke="rgb(255,0,0)" x1="8" y1="1" x2="8" y2="36" stroke-width="1"/>
    <circle fill="rgb(255,0,0)" stroke="rgb(255,0,0)" cx="8" cy="10" r="1.5"/>
    <circle fill="rgb(255,0,0)" stroke="rgb(255,0,0)" cx="8" cy="27" r="1.5"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 40 10" id="Disconnector:隔离开关@0">
    <line stroke="rgb(0,255,0)" x1="5" y1="5" x2="10" y2="5" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="30" y1="5" x2="35" y2="5" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="10" y1="5" x2="30" y2="12" stroke-width="1"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="10" cy="5" r="1"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="30" cy="5" r="1"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 40 10" id="Disconnector:隔离开关@1">
    <line stroke="rgb(0,255,0)" x1="5" y1="5" x2="10" y2="5" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="30" y1="5" x2="35" y2="5" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="10" y1="5" x2="30" y2="7" stroke-width="1"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="10" cy="5" r="1"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="30" cy="5" r="1"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 18 38" id="Disconnector:隔离开关纵@0">
    <line stroke="rgb(0,255,0)" x1="8" y1="1" x2="8" y2="10" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="8" y1="28" x2="8" y2="37" stroke-width="1"/>
    <line stroke="rgb(0,255,0)" x1="8" y1="10" x2="15" y2="28" stroke-width="1"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="8" cy="10" r="1.4"/>
    <circle fill="rgb(0,255,0)" stroke="rgb(0,255,0)" cx="8" cy="28" r="1.4"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 18 38" id="Disconnector:隔离开关纵@1">
    <line stroke="rgb(255,0,0)" x1="8" y1="1" x2="8" y2="37" stroke-width="1"/>
    <circle fill="rgb(255,0,0)" stroke="rgb(255,0,0)" cx="8" cy="10" r="1.4"/>
    <circle fill="rgb(255,0,0)" stroke="rgb(255,0,0)" cx="8" cy="28" r="1.4"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 44 28" id="PowerTransformer:变压器">
    <circle cx="18" cy="10" r="9" fill="none" stroke="rgb(255,0,0)" stroke-width="1.2"/>
    <circle cx="18" cy="18" r="9" fill="none" stroke="rgb(255,0,0)" stroke-width="1.2"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 26 26" id="Source:电源">
    <polygon points="13,1 25,23 1,23" fill="none" stroke="currentColor" stroke-width="2"/>
    <path d="M13 6 L9 15 H14 L11 22 L19 11 H14 Z" fill="currentColor"/>
  </symbol>
  <symbol preserveAspectRatio="xMidYMid" viewBox="0 0 28 44" id="PowerTransformerVertical">
    <circle cx="14" cy="17" r="9" fill="none" stroke="rgb(255,0,0)" stroke-width="1.2"/>
    <circle cx="14" cy="27" r="9" fill="none" stroke="rgb(255,0,0)" stroke-width="1.2"/>
  </symbol>
</defs>`;
}

function metadata(objectId, objectName) {
  return `<metadata><cge:PSR_Ref ObjectID="${esc(objectId)}" ObjectName="${esc(objectName)}" /></metadata>`;
}

function linePath(from, to) {
  const x1 = from.x;
  const y1 = from.y;
  const x2 = to.x;
  const y2 = to.y;
  const mid = Math.round((x1 + x2) / 2);
  if (Math.abs(y1 - y2) < 8) return `${x1},${y1} ${x2},${y2}`;
  return `${x1},${y1} ${mid},${y1} ${mid},${y2} ${x2},${y2}`;
}

function laneOffset(index) {
  const lane = (index % 17) - 8;
  const band = Math.floor(index / 17) * 10;
  return lane * 18 + band;
}

function portVector(port) {
  if (port === "top") return { x: 0, y: -1 };
  if (port === "bottom") return { x: 0, y: 1 };
  if (port === "left") return { x: -1, y: 0 };
  if (port === "right") return { x: 1, y: 0 };
  if (port === "junction") return { x: 0, y: 0 };
  return { x: 0, y: 1 };
}

function isSidePort(port) {
  return port === "left" || port === "right";
}

function isFacingSidePorts(fromPort, toPort, x1, y1, x2, y2) {
  if (Math.abs(y1 - y2) > 8) return false;
  return (
    (fromPort === "right" && toPort === "left" && x1 <= x2) ||
    (fromPort === "left" && toPort === "right" && x1 >= x2)
  );
}

function sideClearanceY(y1, y2, index) {
  return Math.min(y1, y2) - 30 - (index % 5) * 12;
}

function bottomClearanceY(y1, y2, out1, out2, offset, index) {
  return Math.max(y1, y2, out1.y, out2.y) + 38 + Math.abs(offset) + (index % 3) * 12;
}

function closeBottomClearanceY(y1, y2, out1, out2) {
  return Math.max(y1, y2, out1.y, out2.y) + 16;
}

function verticalLaneX(out1, out2, offset) {
  let laneX = Math.round((out1.x + out2.x) / 2 + offset);
  if (Math.abs(laneX - out1.x) < 22) laneX = out1.x + (out2.x >= out1.x ? 1 : -1) * (34 + Math.abs(offset));
  if (Math.abs(laneX - out2.x) < 22) laneX = out2.x + (out1.x >= out2.x ? 1 : -1) * (34 + Math.abs(offset));
  return laneX;
}

function balancedLaneY(out1, out2, offset) {
  let laneY = Math.round((out1.y + out2.y) / 2 + offset);
  if (Math.abs(laneY - out1.y) < 36) laneY = out1.y + (out2.y >= out1.y ? 1 : -1) * (42 + Math.abs(offset));
  if (Math.abs(laneY - out2.y) < 36) laneY = out2.y + (out1.y >= out2.y ? 1 : -1) * (42 + Math.abs(offset));
  return laneY;
}

function lowerPenaltyRoute(horizontal, laneY, vertical, laneX, wire, routeContext) {
  return routePenalty(vertical, wire, routeContext, laneX, "x") <
    routePenalty(horizontal, wire, routeContext, laneY, "y")
    ? vertical
    : horizontal;
}

function horizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY) {
  return [
    { x: x1, y: y1 },
    out1,
    { x: out1.x, y: laneY },
    { x: out2.x, y: laneY },
    out2,
    { x: x2, y: y2 }
  ];
}

function verticalLaneRoute(x1, y1, out1, out2, x2, y2, laneX) {
  return [
    { x: x1, y: y1 },
    out1,
    { x: laneX, y: out1.y },
    { x: laneX, y: out2.y },
    out2,
    { x: x2, y: y2 }
  ];
}

function buildRouteContext(layout, graph) {
  const obstacles = [];
  for (const [eqId, pos] of Object.entries(layout.devicePositions || {})) {
    const item = graph.equipmentById[eqId];
    if (!item || !["Breaker", "Fuse", "LoadBreakSwitch", "Disconnector", "GroundDisconnector"].includes(item.tag)) continue;
    const node = item.layoutNodeId && layout.nodes[item.layoutNodeId];
    const inline = !!(node && node.kind === "inline-switch");
    const size = inline ? inlineSymbolSize(item) : { width: 24, height: 46 };
    const x = inline ? pos.x : pos.x - 4;
    const y = inline ? pos.y : pos.y - 2;
    obstacles.push({
      eqId,
      inline,
      x1: x - 4,
      y1: y - 4,
      x2: x + size.width + 4,
      y2: y + size.height + 4
    });
  }
  const bounds = obstacles.length
    ? {
        x1: Math.min(...obstacles.map((item) => item.x1)),
        y1: Math.min(...obstacles.map((item) => item.y1)),
        x2: Math.max(...obstacles.map((item) => item.x2)),
        y2: Math.max(...obstacles.map((item) => item.y2))
      }
    : null;
  return { obstacles, nodes: layout.nodes || {}, bounds };
}

function clearHorizontalLaneRoute(x1, y1, out1, out2, x2, y2, baseLaneY, wire, index, routeContext) {
  if (!routeContext || !routeContext.obstacles || !routeContext.obstacles.length) {
    return horizontalLaneRoute(x1, y1, out1, out2, x2, y2, baseLaneY);
  }

  const initial = horizontalLaneRoute(x1, y1, out1, out2, x2, y2, baseLaneY);
  const blockers = blockingObstacles(initial, wire, routeContext);
  const candidates = [baseLaneY];
  for (const blocker of blockers) {
    const gap = 18 + (index % 3) * 6;
    candidates.push(blocker.y1 - gap, blocker.y2 + gap);
  }
  for (let step = 1; step <= 8; step++) {
    candidates.push(baseLaneY - step * 24, baseLaneY + step * 24);
  }
  for (let step = 1; step <= 50; step++) {
    candidates.push(baseLaneY - step * 12, baseLaneY + step * 12);
  }
  if (routeContext.bounds) {
    const gap = 70 + (index % 5) * 16;
    candidates.push(routeContext.bounds.y1 - gap, routeContext.bounds.y2 + gap);
  }

  let best = initial;
  let bestScore = routePenalty(initial, wire, routeContext, baseLaneY);
  for (const laneY of candidates) {
    const route = horizontalLaneRoute(x1, y1, out1, out2, x2, y2, Math.round(laneY));
    const score = routePenalty(route, wire, routeContext, baseLaneY);
    if (score < bestScore) {
      best = route;
      bestScore = score;
    }
    if (score < 1) break;
  }
  return best;
}

function clearVerticalLaneRoute(x1, y1, out1, out2, x2, y2, baseLaneX, wire, index, routeContext) {
  if (!routeContext || !routeContext.obstacles || !routeContext.obstacles.length) {
    return verticalLaneRoute(x1, y1, out1, out2, x2, y2, baseLaneX);
  }

  const initial = verticalLaneRoute(x1, y1, out1, out2, x2, y2, baseLaneX);
  const blockers = blockingObstacles(initial, wire, routeContext);
  const candidates = [baseLaneX];
  for (const blocker of blockers) {
    const gap = 18 + (index % 3) * 6;
    candidates.push(blocker.x1 - gap, blocker.x2 + gap);
  }
  for (let step = 1; step <= 8; step++) {
    candidates.push(baseLaneX - step * 24, baseLaneX + step * 24);
  }
  for (let step = 1; step <= 50; step++) {
    candidates.push(baseLaneX - step * 12, baseLaneX + step * 12);
  }
  if (routeContext.bounds) {
    const gap = 70 + (index % 5) * 16;
    candidates.push(routeContext.bounds.x1 - gap, routeContext.bounds.x2 + gap);
  }

  let best = initial;
  let bestScore = routePenalty(initial, wire, routeContext, baseLaneX, "x");
  for (const laneX of candidates) {
    const route = verticalLaneRoute(x1, y1, out1, out2, x2, y2, Math.round(laneX));
    const score = routePenalty(route, wire, routeContext, baseLaneX, "x");
    if (score < bestScore) {
      best = route;
      bestScore = score;
    }
    if (score < 1) break;
  }
  return best;
}

function routePenalty(points, wire, routeContext, baseLane, axis = "y") {
  const blockers = blockingObstacles(points, wire, routeContext);
  const lane = points[2] ? points[2][axis] : baseLane;
  return blockers.length * 100000 + blockedObstacleLength(points, wire, routeContext) * 1000 + Math.abs(lane - baseLane);
}

function blockingObstacles(points, wire, routeContext) {
  const endpointEq = new Set([wire.from && wire.from.eqId, wire.to && wire.to.eqId].filter(Boolean));
  const hits = [];
  const seen = new Set();
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    for (const obstacle of routeContext.obstacles || []) {
      if (endpointEq.has(obstacle.eqId)) continue;
      if (!segmentIntersectsBox(a, b, obstacle)) continue;
      if (seen.has(obstacle.eqId)) continue;
      seen.add(obstacle.eqId);
      hits.push(obstacle);
    }
  }
  return hits;
}

function blockedObstacleLength(points, wire, routeContext) {
  const endpointEq = new Set([wire.from && wire.from.eqId, wire.to && wire.to.eqId].filter(Boolean));
  let total = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    for (const obstacle of routeContext.obstacles || []) {
      if (endpointEq.has(obstacle.eqId)) continue;
      total += segmentBoxOverlapLength(a, b, obstacle);
    }
  }
  return total;
}

function segmentBoxOverlapLength(a, b, box) {
  if (Math.abs(a.y - b.y) < 0.1) {
    const y = a.y;
    if (y < box.y1 || y > box.y2) return 0;
    return Math.max(0, Math.min(Math.max(a.x, b.x), box.x2) - Math.max(Math.min(a.x, b.x), box.x1));
  }
  if (Math.abs(a.x - b.x) < 0.1) {
    const x = a.x;
    if (x < box.x1 || x > box.x2) return 0;
    return Math.max(0, Math.min(Math.max(a.y, b.y), box.y2) - Math.max(Math.min(a.y, b.y), box.y1));
  }
  return 0;
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

function routeWire(wire, index, routeContext = {}) {
  const from = wire.from;
  const to = wire.to;
  const offset = laneOffset(index);
  const x1 = Math.round(from.x);
  const y1 = Math.round(from.y);
  const x2 = Math.round(to.x);
  const y2 = Math.round(to.y);
  const v1 = portVector(from.port);
  const v2 = portVector(to.port);
  const out1 = { x: x1 + v1.x * 18, y: y1 + v1.y * 18, keep: v1.x !== 0 || v1.y !== 0 };
  const out2 = { x: x2 + v2.x * 18, y: y2 + v2.y * 18, keep: v2.x !== 0 || v2.y !== 0 };
  const bottomPort = from.port === "bottom" || to.port === "bottom";
  const sidePort = isSidePort(from.port) || isSidePort(to.port);
  const fromSide = isSidePort(from.port);
  const toSide = isSidePort(to.port);
  const hasJunctionPort = from.port === "junction" || to.port === "junction";
  const mixedSideVertical =
    (fromSide && (to.port === "top" || to.port === "bottom")) ||
    (toSide && (from.port === "top" || from.port === "bottom"));
  const sameNode = from.nodeId && from.nodeId === to.nodeId;
  let points;

  if (isFacingSidePorts(from.port, to.port, x1, y1, x2, y2)) {
    const direct = [
      { x: x1, y: y1 },
      { x: x2, y: y2 }
    ];
    points = blockingObstacles(direct, wire, routeContext).length ? null : direct;
  }

  const fromNode = from.nodeId && routeContext.nodes && routeContext.nodes[from.nodeId];
  const toNode = to.nodeId && routeContext.nodes && routeContext.nodes[to.nodeId];
  const alignedCabinetRows =
    fromNode &&
    toNode &&
    fromNode.id !== toNode.id &&
    Math.abs(fromNode.y - toNode.y) <= 12 &&
    ["ACLineSegment", "Jumper"].includes(wire.tag);

  if (
    !points &&
    sameNode &&
    fromNode &&
    fromNode.id.startsWith("site:") &&
    ["ACLineSegment", "Jumper"].includes(wire.tag)
  ) {
    if (from.port === "bottom" && to.port === "bottom") {
      const laneY = Math.max(out1.y, out2.y) + 16;
      points = horizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY);
    } else if (from.port === "top" && to.port === "top") {
      const laneY = Math.min(out1.y, out2.y) - 16;
      points = horizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY);
    } else {
      points = verticalLaneRoute(
        x1,
        y1,
        out1,
        out2,
        x2,
        y2,
        Math.round((out1.x + out2.x) / 2)
      );
    }
  }

  if (!points && alignedCabinetRows) {
    const laneY = Math.max(
      fromNode.y + fromNode.height,
      toNode.y + toNode.height
    ) + 24;
    points = clearHorizontalLaneRoute(
      x1,
      y1,
      out1,
      out2,
      x2,
      y2,
      laneY,
      wire,
      index,
      routeContext
    );
  } else if (
    !points &&
    sidePort &&
    hasJunctionPort
  ) {
    const laneY = balancedLaneY(out1, out2, offset);
    const laneX = verticalLaneX(out1, out2, offset);
    const horizontal = clearHorizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY, wire, index, routeContext);
    const vertical = clearVerticalLaneRoute(x1, y1, out1, out2, x2, y2, laneX, wire, index, routeContext);
    points = lowerPenaltyRoute(horizontal, laneY, vertical, laneX, wire, routeContext);
  } else if (
    !points &&
    sidePort &&
    Math.abs(out1.y - out2.y) > Math.max(180, Math.abs(out1.x - out2.x) * 1.4)
  ) {
    const laneY = balancedLaneY(out1, out2, offset);
    const laneX = verticalLaneX(out1, out2, offset);
    const horizontal = clearHorizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY, wire, index, routeContext);
    const vertical = clearVerticalLaneRoute(x1, y1, out1, out2, x2, y2, laneX, wire, index, routeContext);
    points = lowerPenaltyRoute(horizontal, laneY, vertical, laneX, wire, routeContext);
  } else if (!points && mixedSideVertical) {
    const sideY = fromSide ? y1 : y2;
    points = clearHorizontalLaneRoute(x1, y1, out1, out2, x2, y2, sideY, wire, index, routeContext);
  } else if (!points && sidePort) {
    const laneY = bottomPort
      ? bottomClearanceY(y1, y2, out1, out2, offset, index)
      : sideClearanceY(y1, y2, index);
    const laneX = verticalLaneX(out1, out2, offset);
    const horizontal = clearHorizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY, wire, index, routeContext);
    const vertical = clearVerticalLaneRoute(x1, y1, out1, out2, x2, y2, laneX, wire, index, routeContext);
    points = lowerPenaltyRoute(horizontal, laneY, vertical, laneX, wire, routeContext);
  } else if (
    !points &&
    (from.port === "junction" || to.port === "junction") &&
    Math.abs(y1 - y2) < 8 &&
    !blockingObstacles(
      [
        { x: x1, y: y1 },
        { x: x2, y: y2 }
      ],
      wire,
      routeContext
    ).length
  ) {
    points = [
      { x: x1, y: y1 },
      { x: x2, y: y2 }
    ];
  } else if (!points && from.port === "junction" && to.port === "junction") {
    const laneY = balancedLaneY(out1, out2, offset);
    const laneX = verticalLaneX(out1, out2, offset);
    const horizontal = clearHorizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY, wire, index, routeContext);
    const vertical = clearVerticalLaneRoute(x1, y1, out1, out2, x2, y2, laneX, wire, index, routeContext);
    points = lowerPenaltyRoute(horizontal, laneY, vertical, laneX, wire, routeContext);
  } else if (!points && Math.abs(out1.x - out2.x) >= Math.abs(out1.y - out2.y)) {
    let laneY;
    if (bottomPort) {
      laneY = sameNode ? closeBottomClearanceY(y1, y2, out1, out2) : bottomClearanceY(y1, y2, out1, out2, offset, index);
    } else if (Math.abs(out1.y - out2.y) < 10) {
      laneY = out1.y + (v1.y || 1) * (34 + Math.abs(offset)) + (offset < 0 ? -10 : 10);
    } else {
      laneY = Math.round((out1.y + out2.y) / 2 + offset);
      if (Math.abs(laneY - out1.y) < 30) laneY = out1.y + (v1.y || 1) * (30 + Math.abs(offset));
      if (Math.abs(laneY - out2.y) < 30) laneY = out2.y + (v2.y || -1) * (30 + Math.abs(offset));
    }
    if (!points) {
      points = clearHorizontalLaneRoute(x1, y1, out1, out2, x2, y2, laneY, wire, index, routeContext);
    }
  } else if (!points) {
    points = clearVerticalLaneRoute(x1, y1, out1, out2, x2, y2, verticalLaneX(out1, out2, offset), wire, index, routeContext);
  }

  const compacted = compactPoints(points);
  return {
    wire,
    points: compacted,
    label: labelPoint(compacted)
  };
}

function compactPoints(points) {
  const out = [];
  for (const point of points) {
    const prev = out[out.length - 1];
    if (prev && Math.abs(prev.x - point.x) < 0.1 && Math.abs(prev.y - point.y) < 0.1) continue;
    out.push(point);
  }
  return out.filter((point, index, list) => {
    const prev = list[index - 1];
    const next = list[index + 1];
    if (!prev || !next) return true;
    if (point.keep) return true;
    const sameX = Math.abs(prev.x - point.x) < 0.1 && Math.abs(point.x - next.x) < 0.1;
    const sameY = Math.abs(prev.y - point.y) < 0.1 && Math.abs(point.y - next.y) < 0.1;
    return !(sameX || sameY);
  });
}

function pointsToString(points) {
  return points.map((point) => `${round(point.x)},${round(point.y)}`).join(" ");
}

function round(value) {
  return Math.round(Number(value) * 10) / 10;
}

function labelPoint(points) {
  if (!points.length) return { x: 0, y: 0 };
  const index = Math.max(0, Math.floor(points.length / 2) - 1);
  const a = points[index];
  const b = points[index + 1] || points[index];
  return { x: (a.x + b.x) / 2 + 4, y: (a.y + b.y) / 2 - 5 };
}

function shortId(value) {
  const text = String(value || "");
  const digits = text.match(/\d{4,}$/);
  if (digits) return digits[0].slice(-5);
  return text.replace(/^(SEG|SWITCH|TRANS)_/, "").slice(-5);
}

function segmentList(route) {
  const segments = [];
  for (let i = 0; i < route.points.length - 1; i++) {
    const a = route.points[i];
    const b = route.points[i + 1];
    if (Math.abs(a.x - b.x) < 0.1 && Math.abs(a.y - b.y) < 0.1) continue;
    segments.push({
      route,
      a,
      b,
      horizontal: Math.abs(a.y - b.y) < 0.1,
      vertical: Math.abs(a.x - b.x) < 0.1
    });
  }
  return segments;
}

function crossingMarkers(routes) {
  const segments = routes.flatMap(segmentList);
  const markers = [];
  const seen = new Set();
  for (let i = 0; i < segments.length; i++) {
    for (let j = i + 1; j < segments.length; j++) {
      const a = segments[i];
      const b = segments[j];
      if (a.route === b.route) continue;
      const horizontal = a.horizontal ? a : b.horizontal ? b : null;
      const vertical = a.vertical ? a : b.vertical ? b : null;
      if (!horizontal || !vertical) continue;
      const x = vertical.a.x;
      const y = horizontal.a.y;
      if (!between(x, horizontal.a.x, horizontal.b.x) || !between(y, vertical.a.y, vertical.b.y)) continue;
      if (nearEndpoint(x, y, horizontal) || nearEndpoint(x, y, vertical)) continue;
      const key = `${Math.round(x)}|${Math.round(y)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      markers.push({ x, y });
    }
  }
  return markers;
}

function between(value, a, b) {
  return value > Math.min(a, b) + 6 && value < Math.max(a, b) - 6;
}

function nearEndpoint(x, y, segment) {
  return distance(x, y, segment.a.x, segment.a.y) < 10 || distance(x, y, segment.b.x, segment.b.y) < 10;
}

function distance(x1, y1, x2, y2) {
  return Math.hypot(x1 - x2, y1 - y2);
}

function bridgePath(marker) {
  const x = round(marker.x);
  const y = round(marker.y);
  return `M ${x - 8} ${y} Q ${x} ${y - 10} ${x + 8} ${y}`;
}

function symbolFor(item, closed, vertical = true) {
  const state = closed ? "1" : "0";
  return `#SwitchBox@${state}`;
}

function inlineSymbolFor(item, closed) {
  const state = closed ? "1" : "0";
  if (item.tag === "Disconnector" || item.tag === "GroundDisconnector") return `#Disconnector:隔离开关@${state}`;
  if (item.tag === "LoadBreakSwitch") return `#LoadBreakSwitch:负荷开关@${state}`;
  return `#Breaker:断路器@${state}`;
}

function inlineSymbolSize(item) {
  if (item.tag === "Disconnector" || item.tag === "GroundDisconnector") return { width: 42, height: 16 };
  if (item.tag === "LoadBreakSwitch") return { width: 42, height: 14 };
  return { width: 42, height: 14 };
}

function renderSvg(topology) {
  const { layout, graph, line } = topology;
  const width = Math.max(1200, Math.ceil(layout.width));
  const height = Math.max(720, Math.ceil(layout.height));
  const energizedNodes = new Set(graph.initialEnergized.equipment);
  const loopedEq = new Set(graph.initialEnergized.loopedEquipment || []);
  const energizedSites = new Set(
    graph.initialEnergized.equipment
      .map((id) => graph.equipmentById[id] && graph.equipmentById[id].layoutNodeId)
      .filter(Boolean)
  );
  const loopedSites = new Set(
    [...loopedEq]
      .map((id) => graph.equipmentById[id] && graph.equipmentById[id].layoutNodeId)
      .filter(Boolean)
  );

  const parts = [];
  parts.push(`<?xml version="1.0" encoding="utf-8" standalone="no"?>`);
  parts.push(`<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:cge="http://iec.ch/TC57/2005/SVG-schema#" xmlns="http://www.w3.org/2000/svg">`);
  parts.push(symbolDefs());
  parts.push(`<style>
    .canvas-bg{fill:rgb(0,0,0)}
    .topo-edge{fill:none;stroke:rgb(80,145,255);stroke-width:3}
    .topo-edge.related{stroke:rgb(255,0,0)}
    .topo-edge.deenergized{stroke:rgb(85,85,85)}
    .topo-edge.tie{stroke-dasharray:14 8}
    .topo-edge.looped{animation:loopFlash .8s steps(2,end) infinite;stroke-width:6}
    .layout-node.looped .cabinet,.layout-node.looped .bus{animation:loopFlash .8s steps(2,end) infinite}
    .device.looped use{animation:loopFlash .8s steps(2,end) infinite}
    @keyframes loopFlash{50%{opacity:.25}}
    .topo-edge.line-selected{stroke:rgb(255,255,0);stroke-width:6}
    .topo-edge:hover{stroke-width:6}
    .jump-marker{fill:none;stroke:rgb(255,255,255);stroke-width:2}
    .junction-node{fill:rgb(0,255,255);stroke:rgb(0,0,0);stroke-width:2;vector-effect:non-scaling-stroke}
    .cabinet{fill:none;stroke:rgb(255,165,0);stroke-width:1.2}
    .cabinet.deenergized{stroke:rgb(100,100,100)}
    .bus{stroke:rgb(80,145,255);stroke-width:2}
    .bus.deenergized{stroke:rgb(80,80,80)}
    .label{fill:rgb(236,236,236);font-family:SimSun,Arial,sans-serif;font-size:24px}
    .small-label{fill:rgb(236,236,236);font-family:SimSun,Arial,sans-serif;font-size:18px}
    .inline-switch-label{fill:rgb(236,236,236);font-family:KaiTi,SimSun,Arial,sans-serif;font-size:17px;writing-mode:tb;paint-order:stroke;stroke:rgb(0,0,0);stroke-width:3}
    .tie-state-label{fill:rgb(255,255,0);font-family:SimSun,Arial,sans-serif;font-size:13px;font-weight:bold;paint-order:stroke;stroke:rgb(0,0,0);stroke-width:3}
    .current-label{fill:rgb(190,235,255);font-family:Arial,sans-serif;font-size:11px;text-anchor:middle;paint-order:stroke;stroke:rgb(0,0,0);stroke-width:3}
    .tie-source-dot{stroke:rgb(0,0,0);stroke-width:1;vector-effect:non-scaling-stroke}
    .device.tie-point.open use{filter:url(#tieGlow)}
    .status-default-mark{fill:rgb(255,210,0);font-family:Arial,sans-serif;font-size:13px;font-weight:bold;paint-order:stroke;stroke:rgb(0,0,0);stroke-width:3}
    .line-id-label{fill:rgb(255,255,0);font-family:Arial,sans-serif;font-size:13px;paint-order:stroke;stroke:rgb(0,0,0);stroke-width:3}
    .source-label{fill:rgb(0,255,0);font-family:Arial,sans-serif;font-size:18px;paint-order:stroke;stroke:rgb(0,0,0);stroke-width:3}
    .feeder-label{fill:rgb(255,255,0);font-family:Arial,sans-serif;font-size:24px;font-weight:bold;paint-order:stroke;stroke:rgb(0,0,0);stroke-width:4}
    .device.deenergized{opacity:.48}
    .device.energized{opacity:1}
    .device.switch{cursor:pointer;pointer-events:bounding-box}
    .topo-edge,.cabinet,.bus,.device use{vector-effect:non-scaling-stroke}
    .device-highlight .cabinet,.device-highlight use{filter:url(#selectedGlow)}
    .outage-mark{fill:rgba(255,255,255,0.08);stroke:rgb(160,160,160);stroke-dasharray:6 5}
    .source-colored.deenergized{opacity:.55}
  </style>`);
  parts.push(`<filter id="selectedGlow"><feDropShadow dx="0" dy="0" stdDeviation="5" flood-color="#55aaff"/></filter>`);
  parts.push(`<filter id="tieGlow"><feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="#ffff00"/></filter>`);
  parts.push(`<rect class="canvas-bg" x="0" y="0" width="${width}" height="${height}"/>`);
  parts.push(`<g id="viewport">`);
  parts.push(`<g id="HeadClass">`);
  for (const s of Object.values(layout.nodes).filter((node) => node.isSource)) {
    const sourceX = s.x - 58;
    const sourceY = s.y - 46;
    const color = s.sourceColor || "rgb(0,255,0)";
    const label = s.feederLabel ? `电源 ${s.feederLabel}` : "电源";
    parts.push(`<g id="power-source-${esc(s.rawId)}" data-kind="source" data-node-id="${esc(s.id)}" style="color:${esc(color)}"><use x="${sourceX}" y="${sourceY}" width="30" height="30" xlink:href="#Source:\u7535\u6e90"/><text class="source-label" x="${sourceX}" y="${sourceY - 8}" style="fill:${esc(color)}">${esc(label)}</text></g>`);
  }
  parts.push(`</g>`);

  parts.push(`<g id="ACLineSegmentClass">`);
  if (layout.wires && layout.wires.length) {
    const routeContext = buildRouteContext(layout, graph);
    const routes = layout.wires.map((wire, index) => routeWire(wire, index, routeContext));
    const markers = crossingMarkers(routes);
    for (const route of routes) {
      const wire = route.wire;
      const equipmentIds = wire.equipmentIds || [];
      const isOn =
        equipmentIds.some((id) => energizedNodes.has(id)) ||
        (wire.from && wire.to && energizedSites.has(wire.from.nodeId) && energizedSites.has(wire.to.nodeId));
      const classes = ["topo-edge", isOn ? "energized" : "deenergized"];
      if (wire.related) classes.push("related");
      if (wire.sourceColor) classes.push("source-colored");
      const isLooped =
        equipmentIds.some((id) => loopedEq.has(id)) ||
        (wire.from && wire.to && loopedSites.has(wire.from.nodeId) && loopedSites.has(wire.to.nodeId));
      if (isLooped) classes.push("looped");
      const title = `${wire.name || wire.id}: ${wire.from.eqId || ""} -> ${wire.to.eqId || ""}`;
      const colorStyle = wire.sourceColor ? ` style="stroke:${esc(wire.sourceColor)}"` : "";
      parts.push(`<polyline id="${esc(wire.id)}" class="${classes.join(" ")}" data-kind="line" data-from="${esc(wire.from.nodeId)}" data-to="${esc(wire.to.nodeId)}" data-from-equipment="${esc(wire.from.eqId)}" data-to-equipment="${esc(wire.to.eqId)}" data-looped="${isLooped ? "1" : "0"}" data-source-label="${esc(wire.sourceLabel || "")}" data-line-name="${esc(wire.name || wire.id)}" data-equipment="${esc(equipmentIds.join(","))}" points="${pointsToString(route.points)}"${colorStyle}><title>${esc(title)}</title>${metadata(wire.id, wire.name || wire.id)}</polyline>`);
      if (!wire.skipLabel) {
        parts.push(`<text class="line-id-label" x="${round(route.label.x)}" y="${round(route.label.y)}">${esc(shortId(wire.name || wire.id))}</text>`);
      }
    }
    for (const marker of markers) {
      parts.push(`<path class="jump-marker" d="${bridgePath(marker)}"/>`);
    }
    for (const junction of layout.junctions || []) {
      parts.push(`<circle class="junction-node" cx="${round(junction.x)}" cy="${round(junction.y)}" r="4" data-kind="junction" data-cn="${esc(junction.cn)}"><title>${esc(junction.cn)}</title></circle>`);
    }
  } else {
    const routeContext = buildRouteContext(layout, graph);
    for (const [edgeIndex, edge] of layout.edges.entries()) {
      const from = layout.nodes[edge.from];
      const to = layout.nodes[edge.to];
      if (!from || !to) continue;
      const p1 = { x: from.x + from.width, y: from.y + from.height / 2, port: "right", nodeId: edge.from, eqId: "" };
      const p2 = { x: to.x, y: to.y + to.height / 2, port: "left", nodeId: edge.to, eqId: "" };
      const isOn = energizedSites.has(edge.from) && energizedSites.has(edge.to);
      const classes = ["topo-edge", isOn ? "energized" : "deenergized"];
      if (edge.related) classes.push("related");
      if (!edge.tree) classes.push("tie");
      const isLooped = loopedSites.has(edge.from) && loopedSites.has(edge.to);
      if (isLooped) classes.push("looped");
      const route = routeWire({ ...edge, from: p1, to: p2, tag: "ACLineSegment" }, edgeIndex, routeContext);
      parts.push(`<polyline id="${esc(edge.id)}" class="${classes.join(" ")}" data-kind="line" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" data-equipment="${esc(edge.equipmentIds.join(","))}" points="${pointsToString(route.points)}">${metadata(edge.id, edge.name || edge.id)}</polyline>`);
    }
  }
  parts.push(`</g>`);

  parts.push(`<g id="SubstationClass">`);
  for (const node of Object.values(layout.nodes)) {
    if (node.kind === "inline-switch") continue;
    const on = energizedSites.has(node.id);
    const looped = loopedSites.has(node.id);
    const objectId = node.kind === "substation" ? `SUBST_${node.rawId}` : node.rawId;
    const busY = node.y + (node.busOffsetY || 46);
    const sourceColor = node.isSource ? node.sourceColor || "rgb(0,255,0)" : "";
    const domainColor = sourceColor || node.sourceColor || "";
    const domainStyle = domainColor ? ` style="stroke:${esc(domainColor)}"` : "";
    const feederStyle = sourceColor ? ` style="fill:${esc(sourceColor)}"` : "";
    parts.push(`<g id="${esc(node.rawId)}" class="layout-node ${on ? "energized" : "deenergized"} ${looped ? "looped" : ""}" data-node-id="${esc(node.id)}" data-kind="${esc(node.kind)}">`);
    parts.push(`<rect class="cabinet ${on ? "energized" : "deenergized"} ${looped ? "looped" : ""}" x="${node.x}" y="${node.y}" width="${node.width}" height="${node.height}" rx="0"${domainStyle}/>`);
    parts.push(`<line class="bus ${on ? "energized" : "deenergized"} ${looped ? "looped" : ""}" x1="${node.x + 18}" y1="${busY}" x2="${node.x + node.width - 18}" y2="${busY}"${domainStyle}/>`);
    if (node.isSource && node.feederLabel) {
      parts.push(`<text class="feeder-label" x="${node.x + 14}" y="${node.y + 32}"${feederStyle}>${esc(node.feederLabel)}</text>`);
    }
    parts.push(`<text class="label" x="${node.x}" y="${node.y - 12}">${esc(node.name)}</text>`);
    parts.push(metadata(objectId, node.name));
    parts.push(`</g>`);
  }
  parts.push(`</g>`);

  parts.push(`<g id="BreakerClass">`);
  parts.push(renderDeviceUses(layout, graph, energizedNodes, loopedEq, ["Breaker", "Fuse"]));
  parts.push(`</g>`);

  parts.push(`<g id="LoadSwitchClass">`);
  parts.push(renderDeviceUses(layout, graph, energizedNodes, loopedEq, ["LoadBreakSwitch"]));
  parts.push(`</g>`);

  parts.push(`<g id="DisconnectorClass">`);
  parts.push(renderDeviceUses(layout, graph, energizedNodes, loopedEq, ["Disconnector", "GroundDisconnector"]));
  parts.push(`</g>`);

  parts.push(`<g id="TransformerClass">`);
  for (const item of graph.equipment.filter((eq) => eq.tag === "PowerTransformer")) {
    const pos = layout.devicePositions[item.id];
    if (!pos) continue;
    const on = energizedNodes.has(item.id);
    const looped = loopedEq.has(item.id);
    parts.push(`<g id="${esc(item.mrid || item.id)}" class="device transformer ${on ? "energized" : "deenergized"} ${looped ? "looped" : ""}" data-eq-id="${esc(item.id)}" data-kind="transformer">`);
    parts.push(`<use x="${pos.x - 14}" y="${pos.y}" width="28" height="44" xlink:href="#PowerTransformerVertical"/>`);
    parts.push(`<text class="small-label" x="${pos.x - 32}" y="${pos.y + 66}">${esc(item.dispatchNumber || item.name || item.mrid)}</text>`);
    parts.push(metadata(item.id, item.name || item.id));
    parts.push(`</g>`);
  }
  parts.push(`</g>`);

  parts.push(`<g id="LabelClass">`);
  parts.push(`<text class="small-label" x="24" y="${height - 28}">${esc(line.displayName || line.lineName || "")}  设备:${graph.equipment.length}  开关:${graph.switches.length}  变压器:${graph.transformers.length}</text>`);
  parts.push(`</g>`);
  parts.push(`</g>`);
  parts.push(`</svg>`);
  return parts.join("\n");
}

function renderDeviceUses(layout, graph, energizedNodes, loopedEq, tags) {
  const parts = [];
  for (const item of graph.equipment.filter((eq) => tags.includes(eq.tag))) {
    const pos = layout.devicePositions[item.id];
    if (!pos) continue;
    const node = item.layoutNodeId && layout.nodes[item.layoutNodeId];
    const inline = !!(node && node.kind === "inline-switch");
    const on = energizedNodes.has(item.id);
    const looped = loopedEq.has(item.id);
    const closed = graph.initialSwitchState[item.id] !== false;
    const status = graph.switchStatusById && graph.switchStatusById[item.id];
    const current = graph.switchCurrentById && graph.switchCurrentById[item.id];
    const currentText = current && current.display ? String(current.display) : "";
    const isSourceBreaker = (graph.sourceBreakers || []).includes(item.id);
    const statusOrigin = status ? status.kind : isSourceBreaker ? "source" : "default";
    const label = switchDisplayLabel(item);
    const href = inline ? inlineSymbolFor(item, closed) : symbolFor(item, closed, true);
    const sourceSides = item.sourceSides || [];
    const sideLabels = sourceSides.map((side) => side.domains.map((domain) => domain.label).filter(Boolean).join("/"));
    const sourceColors = sourceSides.map((side) => side.domains[0] && side.domains[0].color).filter(Boolean);
    const stateLabel = closed ? "合" : "分";
    const statusTitle = status
      ? `${label} 状态:${stateLabel} 来源:${status.fileName || status.kind || ""}`
      : `${label} 状态:${stateLabel} 来源:${isSourceBreaker ? "变电站电源默认" : "图模默认(无实时状态)"}`;
    const tieTitle = item.isTiePoint ? ` 联络:${sideLabels.filter(Boolean).join(" - ")}` : "";
    const currentTitle = currentText ? ` I:${currentText}` : "";
    parts.push(`<g id="${esc(item.mrid || item.id)}" class="device switch status-${esc(statusOrigin)} ${inline ? "inline-switch" : ""} ${item.isTiePoint ? "tie-point" : ""} ${on ? "energized" : "deenergized"} ${looped ? "looped" : ""} ${closed ? "closed" : "open"}" data-eq-id="${esc(item.id)}" data-kind="switch" data-tag="${esc(item.tag)}" data-inline="${inline ? "1" : "0"}" data-state="${closed ? "1" : "0"}" data-current="${esc(currentText)}" data-tie-point="${item.isTiePoint ? "1" : "0"}" data-status-source="${esc(statusOrigin)}" data-status-file="${esc(status ? status.fileName : "")}" data-status-time="${esc(status ? status.timestamp : "")}"><title>${esc(statusTitle + tieTitle + currentTitle)}</title>`);
    if (inline) {
      const size = inlineSymbolSize(item);
      parts.push(`<use x="${pos.x}" y="${pos.y}" width="${size.width}" height="${size.height}" transform="translate(0,0)" xlink:href="${href}"/>`);
      parts.push(`<text class="inline-switch-label" x="${pos.x + size.width - 2}" y="${pos.y + size.height + 8}">${esc(label)}</text>`);
      if (currentText) {
        parts.push(`<text class="current-label" x="${pos.x + size.width / 2}" y="${pos.y + size.height + 24}">${esc(currentText)}</text>`);
      }
      if (item.isTiePoint) {
        sourceColors.slice(0, 2).forEach((color, index) => {
          const dotX = index === 0 ? pos.x + 4 : pos.x + size.width - 4;
          parts.push(`<circle class="tie-source-dot" cx="${dotX}" cy="${pos.y - 5}" r="3" fill="${esc(color)}"/>`);
        });
        parts.push(`<text class="tie-state-label" x="${pos.x}" y="${pos.y - 12}" data-role="tie-state">联络 ${stateLabel}</text>`);
      }
      if (statusOrigin === "default") {
        parts.push(`<text class="status-default-mark" x="${pos.x + size.width + 2}" y="${pos.y + 2}">?</text>`);
      }
    } else {
      parts.push(`<use x="${pos.x}" y="${pos.y}" width="16" height="42" transform="translate(-1.1,0)" xlink:href="${href}"/>`);
      parts.push(`<text class="small-label" x="${pos.x - 10}" y="${pos.y + 66}">${esc(label)}</text>`);
      if (currentText) {
        parts.push(`<text class="current-label" x="${pos.x + 8}" y="${pos.y + 80}">${esc(currentText)}</text>`);
      }
      if (item.isTiePoint) {
        if (sourceColors[0]) {
          parts.push(`<circle class="tie-source-dot" cx="${pos.x + 8}" cy="${pos.y + 2}" r="3" fill="${esc(sourceColors[0])}"/>`);
        }
        if (sourceColors[1]) {
          parts.push(`<circle class="tie-source-dot" cx="${pos.x + 8}" cy="${pos.y + 39}" r="3" fill="${esc(sourceColors[1])}"/>`);
        }
        parts.push(`<text class="tie-state-label" x="${pos.x - 15}" y="${pos.y + (currentText ? 96 : 84)}" data-role="tie-state">联络 ${stateLabel}</text>`);
      }
      if (statusOrigin === "default") {
        parts.push(`<text class="status-default-mark" x="${pos.x + 14}" y="${pos.y + 12}">?</text>`);
      }
    }
    parts.push(metadata(item.id, item.name || item.id));
    parts.push(`</g>`);
  }
  return parts.join("\n");
}

module.exports = {
  esc,
  renderSvg
};
