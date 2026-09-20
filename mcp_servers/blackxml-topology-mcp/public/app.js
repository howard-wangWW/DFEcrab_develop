const state = {
  index: null,
  line: null,
  topology: null,
  switchStates: {},
  operations: [],
  baselineEnergized: new Set(),
  userStatus: null,
  impactedUsers: [],
  impactedUserTotal: 0,
  outageTransformerIds: [],
  impactRequestVersion: 0,
  userImporting: false,
  relatedMode: "auto",
  transform: { scale: 1, x: 0, y: 0 },
  dragging: null,
  searchTimer: null,
  mapSearchMatches: [],
  statusVersion: "",
  contextSwitchId: ""
};

const MIN_ZOOM = 1;
const MAX_ZOOM = 64;
const SEARCH_MAX_ZOOM = 24;

const els = {
  lineSearch: document.getElementById("lineSearch"),
  lineTree: document.getElementById("lineTree"),
  svgHost: document.getElementById("svgHost"),
  statusText: document.getElementById("statusText"),
  selectedLine: document.getElementById("selectedLine"),
  metricDevices: document.getElementById("metricDevices"),
  metricSwitches: document.getElementById("metricSwitches"),
  metricTrans: document.getElementById("metricTrans"),
  metricOutage: document.getElementById("metricOutage"),
  operationList: document.getElementById("operationList"),
  outageList: document.getElementById("outageList"),
  deviceSearch: document.getElementById("deviceSearch"),
  mapCabinetSearch: document.getElementById("mapCabinetSearch"),
  mapSearchResults: document.getElementById("mapSearchResults"),
  primaryMode: document.getElementById("primaryMode"),
  autoMode: document.getElementById("autoMode"),
  sameSourceMode: document.getElementById("sameSourceMode"),
  importXml: document.getElementById("importXml"),
  xmlImportInput: document.getElementById("xmlImportInput"),
  importUsers: document.getElementById("importUsers"),
  userImportInput: document.getElementById("userImportInput"),
  impactUserCount: document.getElementById("impactUserCount"),
  exportImpactUsers: document.getElementById("exportImpactUsers"),
  switchContextMenu: document.getElementById("switchContextMenu"),
  switchContextName: document.getElementById("switchContextName"),
  switchContextState: document.getElementById("switchContextState"),
  switchContextClose: document.getElementById("switchContextClose"),
  switchContextOpen: document.getElementById("switchContextOpen")
};

init();

async function init() {
  bindUi();
  await refreshStatusVersion(false);
  await refreshUserStatus();
  await loadIndex();
  window.setInterval(() => refreshStatusVersion(true), 30000);
}

async function refreshStatusVersion(reloadWhenChanged) {
  try {
    const res = await fetch("/api/status");
    const summary = await res.json();
    const version = JSON.stringify({
      version: summary.version || "",
      switchFiles: summary.switchFiles || [],
      groundFiles: summary.groundFiles || [],
      switchCount: summary.switchCount || 0,
      groundCount: summary.groundCount || 0,
      currentVersion: summary.currentVersion || (summary.current && summary.current.version) || "",
      currentFiles: summary.currentFiles || (summary.current && summary.current.currentFiles) || [],
      currentCount: summary.currentCount || (summary.current && summary.current.currentCount) || 0
    });
    const changed = !!state.statusVersion && state.statusVersion !== version;
    state.statusVersion = version;
    if (changed && reloadWhenChanged && state.line) {
      await loadTopology(state.line);
    }
  } catch (err) {
    console.warn("switch status refresh failed", err);
  }
}

function bindUi() {
  els.lineSearch.addEventListener("input", () => renderTree());
  els.deviceSearch.addEventListener("input", () => {
    els.mapCabinetSearch.value = els.deviceSearch.value;
    scheduleDeviceSearch(els.deviceSearch.value, false);
  });
  els.deviceSearch.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") locateSearchTarget(els.deviceSearch.value);
  });
  els.mapCabinetSearch.addEventListener("input", () => {
    els.deviceSearch.value = els.mapCabinetSearch.value;
    scheduleDeviceSearch(els.mapCabinetSearch.value, true);
  });
  els.mapCabinetSearch.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") {
      evt.preventDefault();
      const first = state.mapSearchMatches[0];
      locateSearchTarget(els.mapCabinetSearch.value, first && first.id, true);
      hideMapSearchResults();
    }
    if (evt.key === "Escape") hideMapSearchResults();
  });
  els.mapSearchResults.addEventListener("pointerdown", (evt) => evt.preventDefault());
  els.mapSearchResults.addEventListener("click", (evt) => {
    const button = evt.target.closest("[data-node-id]");
    if (!button) return;
    const match = state.mapSearchMatches.find((item) => item.id === button.dataset.nodeId);
    if (!match) return;
    els.mapCabinetSearch.value = match.name;
    els.deviceSearch.value = match.name;
    locateSearchTarget(match.name, match.id, true);
    hideMapSearchResults();
  });
  els.mapCabinetSearch.addEventListener("blur", () => {
    window.setTimeout(hideMapSearchResults, 120);
  });
  document.getElementById("reloadLine").addEventListener("click", () => {
    if (state.line) loadTopology(state.line);
  });
  document.getElementById("fitView").addEventListener("click", fitView);
  document.getElementById("exportSvg").addEventListener("click", exportSvg);
  document.getElementById("exportTextTopology").addEventListener("click", exportTextTopology);
  els.importXml.addEventListener("click", () => els.xmlImportInput.click());
  els.xmlImportInput.addEventListener("change", importXmlFiles);
  els.importUsers.addEventListener("click", () => els.userImportInput.click());
  els.userImportInput.addEventListener("change", importUserFiles);
  els.exportImpactUsers.addEventListener("click", exportImpactUsers);
  document.getElementById("switchMode").addEventListener("click", () => setModeButton("switchMode"));
  document.getElementById("outageMode").addEventListener("click", () => setModeButton("outageMode"));
  els.primaryMode.addEventListener("click", () => setRelatedMode("primary"));
  els.autoMode.addEventListener("click", () => setRelatedMode("auto"));
  els.sameSourceMode.addEventListener("click", () => setRelatedMode("sameSource"));

  els.svgHost.addEventListener("wheel", onWheel, { passive: false });
  els.svgHost.addEventListener("pointerdown", onPointerDown);
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", endDrag);
  window.addEventListener("pointercancel", endDrag);
  els.switchContextClose.addEventListener("click", () => applyContextSwitchState(true));
  els.switchContextOpen.addEventListener("click", () => applyContextSwitchState(false));
  document.addEventListener("pointerdown", (evt) => {
    if (!els.switchContextMenu.hidden && !els.switchContextMenu.contains(evt.target)) closeSwitchContextMenu();
  });
  window.addEventListener("blur", closeSwitchContextMenu);
  window.addEventListener("resize", closeSwitchContextMenu);
  window.addEventListener("keydown", (evt) => {
    if (evt.key === "Escape") {
      closeSwitchContextMenu();
      hideMapSearchResults();
    }
  });
}

async function refreshUserStatus() {
  try {
    const res = await fetch("/api/users/status");
    state.userStatus = await res.json();
    const datasets = state.userStatus.datasets || [];
    els.importUsers.title = datasets.length
      ? datasets.map((item) => `${item.type}: ${item.fileName}，${item.indexedRows}户`).join("\n")
      : "请选择 ZY.csv 和 DY.csv";
  } catch (error) {
    state.userStatus = null;
  }
}

function setModeButton(id) {
  document.getElementById("switchMode").classList.toggle("active", id === "switchMode");
  document.getElementById("outageMode").classList.toggle("active", id === "outageMode");
}

function setRelatedMode(mode) {
  state.relatedMode = mode;
  els.primaryMode.classList.toggle("active", mode === "primary");
  els.autoMode.classList.toggle("active", mode === "auto");
  els.sameSourceMode.classList.toggle("active", mode === "sameSource");
  if (state.line) loadTopology(state.line);
}

async function loadIndex(preferredFile = "") {
  const res = await fetch(preferredFile ? "/api/lines?refresh=1" : "/api/lines");
  state.index = await res.json();
  els.statusText.textContent = `BLACKXML：${state.index.count} 条`;
  renderTree();
  const preferred =
    (preferredFile && state.index.map[preferredFile]) ||
    state.index.lines.find((line) => line.fileName.includes("F09") && line.fileName.includes("中心三线")) ||
    state.index.lines.find((line) => !line.error);
  if (preferred) loadTopology(preferred);
}

function importRelativePath(file) {
  const raw = file.webkitRelativePath || file.name;
  const parts = raw.split(/[\\/]+/).filter(Boolean);
  if (parts.length > 1) parts.shift();
  return parts.join("/") || file.name;
}

async function importXmlFiles() {
  const files = [...(els.xmlImportInput.files || [])]
    .filter((file) => file.name.toLowerCase().endsWith(".xml"))
    .sort((a, b) => importRelativePath(a).localeCompare(importRelativePath(b), "zh-Hans-CN"));
  els.xmlImportInput.value = "";
  if (!files.length) return;

  let lastImported = "";
  try {
    for (const file of files) {
      const relativePath = importRelativePath(file);
      els.statusText.textContent = `正在导入图模文件夹：${relativePath}...`;
      const xml = await file.text();
      const res = await fetch(`/api/import?path=${encodeURIComponent(relativePath)}`, {
        method: "POST",
        headers: { "Content-Type": "application/xml; charset=utf-8" },
        body: xml
      });
      const data = await res.json();
      if (!res.ok || data.error) {
        throw new Error(data.error || `导入失败：${relativePath}`);
      }
      lastImported = data.relativePath || relativePath;
    }
    els.statusText.textContent = `已导入 ${files.length} 个 XML，正在刷新...`;
    await loadIndex(lastImported);
  } catch (err) {
    els.statusText.textContent = err.message || "XML 导入失败";
  }
}

function userFileType(file) {
  const name = String(file && file.name || "").toUpperCase();
  if (name === "ZY.CSV" || name.startsWith("ZY_")) return "ZY";
  if (name === "DY.CSV" || name.startsWith("DY_")) return "DY";
  return "";
}

async function importUserFiles() {
  const files = [...(els.userImportInput.files || [])]
    .map((file) => ({ file, type: userFileType(file) }))
    .filter((item) => item.type)
    .sort((a, b) => b.type.localeCompare(a.type));
  els.userImportInput.value = "";
  if (!files.length || state.userImporting) {
    els.statusText.textContent = "请选择 ZY.csv 或 DY.csv";
    return;
  }

  state.userImporting = true;
  els.importUsers.disabled = true;
  try {
    for (const item of files) {
      const result = await uploadUserFile(item.file, item.type);
      els.statusText.textContent = `${item.file.name} 导入完成：${result.indexedRows} 户`;
    }
    await refreshUserStatus();
    els.statusText.textContent = `用户列表导入完成，共 ${state.userStatus.totalUsers || 0} 户`;
    if (state.outageTransformerIds.length) queryImpactedUsers(state.outageTransformerIds);
  } catch (error) {
    els.statusText.textContent = error.message || "用户列表导入失败";
  } finally {
    state.userImporting = false;
    els.importUsers.disabled = false;
  }
}

function uploadUserFile(file, type) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/users/import?type=${encodeURIComponent(type)}&name=${encodeURIComponent(file.name)}`);
    xhr.setRequestHeader("Content-Type", "text/csv; charset=utf-8");
    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.min(99, Math.round((event.loaded / event.total) * 100));
      els.statusText.textContent = `正在导入 ${file.name}：${percent}%`;
    });
    xhr.addEventListener("load", () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (error) {
        reject(new Error("用户列表导入响应无法解析"));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300 || data.error) {
        reject(new Error(data.error || `导入失败：${file.name}`));
        return;
      }
      resolve(data);
    });
    xhr.addEventListener("error", () => reject(new Error(`上传失败：${file.name}`)));
    xhr.send(file);
  });
}

function renderTree() {
  if (!state.index) return;
  const q = els.lineSearch.value.trim().toLowerCase();
  const lines = state.index.lines.filter((line) => {
    if (!q) return true;
    return `${line.displayName} ${line.fullDisplayName || ""} ${line.stationName || ""} ${line.fullStationName || ""} ${line.stationLabel || ""} ${line.district || ""} ${line.relativePath} ${line.circuitMrid}`.toLowerCase().includes(q);
  });
  const groups = new Map();
  for (const line of lines) {
    const key = line.stationLabel || line.stationName || "未分组";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(line);
  }
  els.lineTree.innerHTML = [...groups.entries()]
    .slice(0, 120)
    .map(([station, items]) => {
      const children = items
        .slice(0, 140)
        .map((line) => {
          const active = state.line && state.line.relativePath === line.relativePath ? " active" : "";
          return `<div class="line-item${active}" data-file="${escapeHtml(line.relativePath)}"><span class="tree-icon"></span>${escapeHtml(line.lineName || line.fileName)}<small>(${line.substationCount || 0})</small></div>`;
        })
        .join("");
      return `<section class="station-group"><div class="station-head">▸ ${escapeHtml(station)} (${items.length})</div>${children}</section>`;
    })
    .join("");
  els.lineTree.querySelectorAll(".line-item").forEach((item) => {
    item.addEventListener("click", () => {
      const line = state.index.map[item.dataset.file];
      if (line) loadTopology(line);
    });
  });
}

async function loadTopology(line) {
  closeSwitchContextMenu();
  state.line = line;
  state.switchStates = {};
  state.operations = [];
  state.baselineEnergized = new Set();
  state.impactedUsers = [];
  state.impactedUserTotal = 0;
  state.outageTransformerIds = [];
  state.impactRequestVersion += 1;
  renderTree();
  els.selectedLine.textContent = line.displayName || line.fullDisplayName || line.fileName;
  els.statusText.textContent = "正在生成 SVG...";
  els.svgHost.innerHTML = "";
  const params = new URLSearchParams({
    file: line.relativePath,
    related: state.relatedMode,
    maxRelated: "64"
  });
  const res = await fetch(`/api/topology?${params.toString()}`);
  const data = await res.json();
  if (data.error) {
    els.statusText.textContent = data.error;
    return;
  }
  state.topology = data;
  state.switchStates = { ...data.graph.initialSwitchState };
  state.baselineEnergized = new Set(
    computeOperationalState(data.graph, state.switchStates).equipment
  );
  mountSvg(data.svg);
  bindSvg();
  updateMetrics();
  runSimulation();
  fitView();
  els.statusText.textContent = `${data.line.displayName || data.line.lineName}  实时状态 ${data.stats.liveSwitchStatus || 0}/${data.stats.switches || 0}  电流 ${data.stats.liveSwitchCurrent || 0}`;
}

function mountSvg(svgText) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(svgText, "image/svg+xml");
  const parserError = doc.querySelector("parsererror");
  if (parserError) {
    throw new Error(parserError.textContent || "SVG解析失败");
  }
  const svg = document.importNode(doc.documentElement, true);
  els.svgHost.replaceChildren(svg);
}

function bindSvg() {
  const svg = els.svgHost.querySelector("svg");
  if (!svg) return;
  svg.querySelectorAll(".device.switch").forEach((item) => {
    item.addEventListener("click", (evt) => {
      evt.stopPropagation();
      selectSwitch(item.dataset.eqId);
    });
    item.addEventListener("contextmenu", (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      selectSwitch(item.dataset.eqId);
      openSwitchContextMenu(item.dataset.eqId, evt.clientX, evt.clientY);
    });
  });
  svg.querySelectorAll(".topo-edge").forEach((item) => {
    item.addEventListener("click", (evt) => {
      evt.stopPropagation();
      selectLineSegment(item);
    });
  });
}

function selectLineSegment(lineEl) {
  const svg = els.svgHost.querySelector("svg");
  if (!svg) return;
  svg.querySelectorAll(".line-selected,.device-highlight").forEach((item) => {
    item.classList.remove("line-selected", "device-highlight");
  });
  lineEl.classList.add("line-selected");
  const fromId = lineEl.dataset.fromEquipment;
  const toId = lineEl.dataset.toEquipment;
  for (const id of [fromId, toId]) {
    const device = id && svg.querySelector(`[data-eq-id="${cssEscape(id)}"]`);
    if (device) device.classList.add("device-highlight");
  }
  const name = lineEl.dataset.lineName || lineEl.id || "线路";
  els.statusText.textContent = `${name}：${fromId || "?"} -> ${toId || "?"}`;
}

function selectSwitch(id) {
  if (!state.topology || !(id in state.switchStates)) return;
  const svg = els.svgHost.querySelector("svg");
  if (!svg) return;
  svg.querySelectorAll(".device-highlight,.line-selected").forEach((item) => {
    item.classList.remove("device-highlight", "line-selected");
  });
  const element = svg.querySelector(`[data-eq-id="${cssEscape(id)}"]`);
  if (element) element.classList.add("device-highlight");
  const eq = state.topology.graph.equipmentById[id];
  const name = switchDisplayName(eq);
  els.statusText.textContent = `${name || id}：${state.switchStates[id] !== false ? "合闸" : "分闸"}，右键可模拟操作`;
}

function openSwitchContextMenu(id, clientX, clientY) {
  if (!state.topology || !(id in state.switchStates)) return;
  const eq = state.topology.graph.equipmentById[id];
  const closed = state.switchStates[id] !== false;
  state.contextSwitchId = id;
  els.switchContextName.textContent = switchDisplayName(eq) || id;
  els.switchContextState.textContent = `当前状态：${closed ? "合闸" : "分闸"}`;
  els.switchContextClose.disabled = closed;
  els.switchContextOpen.disabled = !closed;
  els.switchContextMenu.hidden = false;
  const rect = els.switchContextMenu.getBoundingClientRect();
  const left = clamp(clientX, 8, Math.max(8, window.innerWidth - rect.width - 8));
  const top = clamp(clientY, 8, Math.max(8, window.innerHeight - rect.height - 8));
  els.switchContextMenu.style.left = `${left}px`;
  els.switchContextMenu.style.top = `${top}px`;
}

function closeSwitchContextMenu() {
  state.contextSwitchId = "";
  if (els.switchContextMenu) els.switchContextMenu.hidden = true;
}

function applyContextSwitchState(closed) {
  const id = state.contextSwitchId;
  closeSwitchContextMenu();
  if (id) setSwitchState(id, closed);
}

function setSwitchState(id, closed) {
  if (!state.topology || !(id in state.switchStates)) return;
  const currentClosed = state.switchStates[id] !== false;
  if (currentClosed === closed) return;
  state.switchStates[id] = closed;
  const eq = state.topology.graph.equipmentById[id];
  const existing = state.operations.find((item) => item.id === id);
  const op = {
    id,
    name: switchDisplayName(eq) || id,
    closed: state.switchStates[id]
  };
  if (existing) {
    existing.closed = op.closed;
  } else {
    state.operations.push(op);
  }
  runSimulation();
  els.statusText.textContent = `${op.name}：已模拟${closed ? "合闸" : "分闸"}`;
}

function runSimulation() {
  const topo = state.topology;
  if (!topo) return;
  const operational = computeOperationalState(topo.graph, state.switchStates);
  const energizedEq = new Set(operational.equipment);
  const loopedEq = new Set(operational.loopedEquipment || []);
  const energizedNodes = new Set();
  const loopedNodes = new Set();
  for (const node of Object.values(topo.layout.nodes || {})) {
    const domains = operationalDomainsForNode(node, topo.graph, operational);
    if (domains.length) energizedNodes.add(node.id);
    if ((node.equipment || []).some((eqId) => loopedEq.has(eqId))) loopedNodes.add(node.id);
  }
  updateSvgState(energizedEq, energizedNodes, loopedEq, loopedNodes, operational);
  renderOperations();
  renderOutage(energizedEq);
}

function computeOperationalState(graph, switchState) {
  const equipmentDomains = new Map();
  const connectivityDomains = new Map();
  const queue = [];
  const switchIds = new Set(graph.switches.map((item) => item.id));
  const isConductive = (eqId) => {
    const eq = graph.equipmentById[eqId];
    if (!eq) return false;
    if (eq.tag === "GroundDisconnector") return false;
    if (switchIds.has(eqId)) return switchState[eqId] !== false;
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
  const loopedEquipment = [...looped.equipment];
  const loopedConnectivityNodes = [...looped.connectivityNodes];
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
    const owners = new Set(
      sides.flatMap((side) => side.domains.map((domain) => domain.owner))
    );
    const isTiePoint = separated || (!!item.isTiePoint && owners.size > 1);
    if (isTiePoint) tiePoints[item.id] = { sides, closed: switchState[item.id] !== false };
  }

  return {
    equipment: [...equipmentDomains.keys()],
    connectivityNodes: [...connectivityDomains.keys()],
    loopedEquipment,
    loopedConnectivityNodes,
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

function updateSvgState(energizedEq, energizedNodes, loopedEq = new Set(), loopedNodes = new Set(), operational = null) {
  const svg = els.svgHost.querySelector("svg");
  if (!svg || !state.topology) return;
  const loopedCn = new Set((operational && operational.loopedConnectivityNodes) || []);
  const wireById = new Map((state.topology.layout.wires || []).map((wire) => [wire.id, wire]));
  svg.querySelectorAll(".device").forEach((item) => {
    const on = energizedEq.has(item.dataset.eqId);
    const looped = loopedEq.has(item.dataset.eqId);
    item.classList.toggle("energized", on);
    item.classList.toggle("deenergized", !on);
    item.classList.toggle("looped", looped);
  });
  svg.querySelectorAll(".layout-node").forEach((item) => {
    const on = energizedNodes.has(item.dataset.nodeId);
    const looped = loopedNodes.has(item.dataset.nodeId);
    item.classList.toggle("energized", on);
    item.classList.toggle("deenergized", !on);
    item.classList.toggle("looped", looped);
    item.querySelectorAll(".cabinet,.bus").forEach((child) => {
      child.classList.toggle("energized", on);
      child.classList.toggle("deenergized", !on);
      child.classList.toggle("looped", looped);
    });
  });
  svg.querySelectorAll(".topo-edge").forEach((item) => {
    const equipmentIds = (item.dataset.equipment || "").split(",").filter(Boolean);
    const wire = wireById.get(item.id);
    const on = equipmentIds.length
      ? equipmentIds.some((id) => energizedEq.has(id))
      : energizedNodes.has(item.dataset.from) && energizedNodes.has(item.dataset.to);
    const looped = equipmentIds.length
      ? equipmentIds.some((id) => loopedEq.has(id))
      : !!(wire && wire.from && wire.to && loopedCn.has(wire.from.cn) && loopedCn.has(wire.to.cn));
    item.classList.toggle("energized", on);
    item.classList.toggle("deenergized", !on);
    item.classList.toggle("looped", looped);
  });
  svg.querySelectorAll(".device.switch").forEach((item) => {
    const id = item.dataset.eqId;
    const closed = state.switchStates[id] !== false;
    item.dataset.state = closed ? "1" : "0";
    item.classList.toggle("closed", closed);
    item.classList.toggle("open", !closed);
    const use = item.querySelector("use");
    const href = symbolHref(item.dataset.tag, closed, item.dataset.inline === "1");
    use.setAttribute("href", href);
    use.setAttributeNS("http://www.w3.org/1999/xlink", "href", href);
    const tieState = item.querySelector('[data-role="tie-state"]');
    if (tieState) tieState.textContent = `联络 ${closed ? "合" : "分"}`;
  });
  if (operational) updateSourceVisuals(svg, operational);
}

function updateSourceVisuals(svg, operational) {
  const topo = state.topology;
  const wireById = new Map((topo.layout.wires || []).map((wire) => [wire.id, wire]));

  svg.querySelectorAll(".topo-edge").forEach((element) => {
    const wire = wireById.get(element.id);
    if (!wire) return;
    const equipmentDomains = uniqueOperationalDomains(
      (wire.equipmentIds || []).flatMap((id) => operational.equipmentDomains[id] || [])
    );
    const endpointDomains = uniqueOperationalDomains(
      [wire.from && wire.from.cn, wire.to && wire.to.cn]
        .filter(Boolean)
        .flatMap((cn) => operational.connectivityDomains[cn] || [])
    );
    const domains = equipmentDomains.length ? equipmentDomains : endpointDomains;
    const preferredOwners = uniqueValues(
      (wire.equipmentIds || []).flatMap((id) => operational.loopEquipmentOwners[id] || [])
        .concat(
          [wire.from && wire.from.cn, wire.to && wire.to.cn]
            .filter(Boolean)
            .flatMap((cn) => operational.loopConnectivityOwners[cn] || [])
        )
    );
    const domain =
      preferredOwners.length === 1
        ? domains.find((item) => item.owner === preferredOwners[0]) || domains[0]
        : domains[0];
    const energized = element.classList.contains("energized");
    if (energized && domain && domain.color) {
      element.style.stroke = domain.color;
      element.classList.add("source-colored");
      element.dataset.sourceLabel = domain.label || "";
    } else {
      element.style.removeProperty("stroke");
      element.classList.remove("source-colored");
      element.dataset.sourceLabel = "";
    }
    element.classList.toggle("multi-source", domains.length > 1);
  });

  for (const node of Object.values(topo.layout.nodes || {})) {
    const element = svg.querySelector(`[data-node-id="${cssEscape(node.id)}"]`);
    if (!element) continue;
    const domains = operationalDomainsForNode(node, topo.graph, operational);
    const preferredOwners = uniqueValues(
      (node.equipment || []).flatMap((eqId) => operational.loopEquipmentOwners[eqId] || [])
    );
    const domain =
      (preferredOwners.length === 1 && domains.find((item) => item.owner === preferredOwners[0])) ||
      domains[0] ||
      null;
    const color = node.isSource ? node.sourceColor : domain && domain.color;
    const energized = element.classList.contains("energized");
    element.classList.toggle("multi-source", domains.length > 1);
    element.querySelectorAll(".cabinet,.bus").forEach((child) => {
      if (energized && color) child.style.stroke = color;
      else child.style.removeProperty("stroke");
    });
  }

  svg.querySelectorAll(".device.switch").forEach((element) => {
    const id = element.dataset.eqId;
    const tie = operational.tiePoints[id] || null;
    const eq = topo.graph.equipmentById[id];
    updateTieVisual(element, eq, tie, state.switchStates[id] !== false);
  });
}

function operationalDomainsForNode(node, graph, operational) {
  const busbarCns = [];
  for (const eqId of node.equipment || []) {
    const item = graph.equipmentById[eqId];
    if (item && item.tag === "BusbarSection") busbarCns.push(...(graph.eqToCn[eqId] || []));
  }
  const busDomains = uniqueOperationalDomains(
    busbarCns.flatMap((cn) => operational.connectivityDomains[cn] || [])
  );
  if (busDomains.length) return busDomains;
  return uniqueOperationalDomains(
    (node.equipment || []).flatMap((eqId) => operational.equipmentDomains[eqId] || [])
  );
}

function uniqueOperationalDomains(domains) {
  const bySource = new Map();
  for (const domain of domains || []) {
    if (!domain || !domain.owner) continue;
    const key = domain.owner;
    if (!bySource.has(key)) bySource.set(key, domain);
  }
  return [...bySource.values()];
}

function uniqueValues(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function updateTieVisual(element, eq, tie, closed) {
  element.querySelectorAll(".tie-source-dot,[data-role='tie-state']").forEach((child) => child.remove());
  element.classList.toggle("tie-point", !!tie);
  element.dataset.tiePoint = tie ? "1" : "0";
  if (!tie || !eq) return;

  const position = state.topology.layout.devicePositions[eq.id];
  if (!position) return;
  const colors = uniqueOperationalDomains(tie.sides.flatMap((side) => side.domains)).map((domain) => domain.color).filter(Boolean);
  const inline = element.dataset.inline === "1";
  const ns = "http://www.w3.org/2000/svg";
  const addCircle = (x, y, color) => {
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("class", "tie-source-dot");
    circle.setAttribute("cx", x);
    circle.setAttribute("cy", y);
    circle.setAttribute("r", "3");
    circle.setAttribute("fill", color);
    element.appendChild(circle);
  };
  const text = document.createElementNS(ns, "text");
  text.setAttribute("class", "tie-state-label");
  text.setAttribute("data-role", "tie-state");
  text.textContent = `联络 ${closed ? "合" : "分"}`;

  if (inline) {
    if (colors[0]) addCircle(position.x + 4, position.y - 5, colors[0]);
    if (colors[1]) addCircle(position.x + 38, position.y - 5, colors[1]);
    text.setAttribute("x", position.x);
    text.setAttribute("y", position.y - 12);
  } else {
    if (colors[0]) addCircle(position.x + 8, position.y + 2, colors[0]);
    if (colors[1]) addCircle(position.x + 8, position.y + 39, colors[1]);
    text.setAttribute("x", position.x - 15);
    text.setAttribute("y", position.y + 84);
  }
  element.appendChild(text);
}

function symbolHref(tag, closed, inline) {
  const statePart = closed ? "1" : "0";
  if (inline) {
    if (tag === "Disconnector" || tag === "GroundDisconnector") return `#Disconnector:隔离开关@${statePart}`;
    if (tag === "LoadBreakSwitch") return `#LoadBreakSwitch:负荷开关@${statePart}`;
    return `#Breaker:断路器@${statePart}`;
  }
  return `#SwitchBox@${statePart}`;
}

function renderOperations() {
  els.operationList.innerHTML = state.operations.length
    ? state.operations
        .map((item, index) => {
          const stateClass = item.closed ? "state-closed" : "state-open";
          return `<li><span>${index + 1}. ${escapeHtml(item.name)}</span><span class="${stateClass}">${item.closed ? "合" : "分"}</span></li>`;
        })
        .join("")
    : `<li><span>暂无操作</span><span></span></li>`;
}

function renderOutage(energizedEq) {
  const topo = state.topology;
  const outages = topo.graph.equipment
    .filter(
      (item) =>
        item.tag === "PowerTransformer" &&
        state.baselineEnergized.has(item.id) &&
        !energizedEq.has(item.id)
    );
  const transformerIds = outages.map((item) => item.id);
  state.outageTransformerIds = transformerIds;
  els.metricOutage.textContent = outages.length;
  if (!transformerIds.length) {
    state.impactRequestVersion += 1;
    state.impactedUsers = [];
    state.impactedUserTotal = 0;
    els.impactUserCount.textContent = "0";
    els.exportImpactUsers.disabled = true;
    els.outageList.innerHTML = `<li><span>无新增失电影响用户</span><span></span></li>`;
    return;
  }
  els.impactUserCount.textContent = "...";
  els.exportImpactUsers.disabled = true;
  els.outageList.innerHTML = `<li><span>正在查询 ${outages.length} 台失电变压器的用户...</span><span></span></li>`;
  queryImpactedUsers(transformerIds);
}

async function queryImpactedUsers(transformerIds) {
  const requestVersion = ++state.impactRequestVersion;
  try {
    const res = await fetch("/api/users/query", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ transformerIds, limit: 1000 })
    });
    const data = await res.json();
    if (requestVersion !== state.impactRequestVersion) return;
    if (!res.ok || data.error) throw new Error(data.error || "影响用户查询失败");
    state.userStatus = data.status || state.userStatus;
    state.impactedUsers = data.users || [];
    state.impactedUserTotal = Number(data.total || 0);
    els.impactUserCount.textContent = String(state.impactedUserTotal);
    els.exportImpactUsers.disabled = state.impactedUserTotal === 0;
    if (!state.impactedUserTotal) {
      const imported = state.userStatus && (state.userStatus.datasets || []).length;
      els.outageList.innerHTML = imported
        ? `<li><span>失电变压器未匹配到用户</span><span></span></li>`
        : `<li><span>请先导入 ZY.csv 和 DY.csv</span><span></span></li>`;
      return;
    }
    const summary = data.truncated
      ? `<li><span>当前展示前 ${state.impactedUsers.length} 户</span><span>共 ${state.impactedUserTotal} 户</span></li>`
      : "";
    els.outageList.innerHTML =
      summary +
      state.impactedUsers.map((item) => {
        const typeName = item.type === "ZY" ? "中压" : "低压";
        const detail = [
          item.consumerId && `编号：${item.consumerId}`,
          item.transformerName && `变压器：${item.transformerName}`,
          item.transformerId
        ].filter(Boolean).join(" | ");
        return `<li class="user-impact-item"><span class="user-impact-main"><strong>${escapeHtml(item.consumerName || item.consumerId || "未命名用户")}</strong><small>${escapeHtml(detail)}</small></span><span class="user-voltage">${typeName}</span></li>`;
      }).join("");
  } catch (error) {
    if (requestVersion !== state.impactRequestVersion) return;
    state.impactedUsers = [];
    state.impactedUserTotal = 0;
    els.impactUserCount.textContent = "0";
    els.exportImpactUsers.disabled = true;
    els.outageList.innerHTML = `<li><span>${escapeHtml(error.message || "影响用户查询失败")}</span><span></span></li>`;
  }
}

async function exportImpactUsers() {
  if (!state.outageTransformerIds.length || !state.impactedUserTotal) return;
  els.exportImpactUsers.disabled = true;
  try {
    const lineName = state.line && (state.line.displayName || state.line.lineName || "馈线");
    const res = await fetch("/api/users/export", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({
        transformerIds: state.outageTransformerIds,
        fileName: `${lineName}-失电影响用户.csv`
      })
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "导出失败");
    }
    const blob = await res.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${lineName}-失电影响用户.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    els.statusText.textContent = `已导出 ${state.impactedUserTotal} 户影响用户`;
  } catch (error) {
    els.statusText.textContent = error.message || "影响用户导出失败";
  } finally {
    els.exportImpactUsers.disabled = state.impactedUserTotal === 0;
  }
}

function switchDisplayName(eq) {
  if (!eq) return "";
  const node =
    state.topology &&
    state.topology.layout &&
    state.topology.layout.nodes &&
    eq.layoutNodeId &&
    state.topology.layout.nodes[eq.layoutNodeId];
  const cabinetName = node && node.name;
  const switchName = eq.dispatchNumber || eq.name || eq.mrid || eq.id;
  if (!cabinetName) return switchName;
  if (!switchName || cabinetName.includes(switchName)) return cabinetName;
  return `${cabinetName} ${switchName}`;
}

function updateMetrics() {
  const stats = state.topology ? state.topology.stats : {};
  els.metricDevices.textContent = stats.equipment || 0;
  els.metricSwitches.textContent = stats.switches || 0;
  els.metricTrans.textContent = stats.transformers || 0;
  els.metricOutage.textContent = 0;
  els.impactUserCount.textContent = "0";
  els.exportImpactUsers.disabled = true;
}

function scheduleDeviceSearch(query, showResults) {
  window.clearTimeout(state.searchTimer);
  if (showResults) renderMapSearchResults(query);
  state.searchTimer = window.setTimeout(() => {
    const first = state.mapSearchMatches[0];
    locateSearchTarget(query, showResults && first ? first.id : "", showResults);
  }, 220);
}

function renderMapSearchResults(query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q || !state.topology) {
    state.mapSearchMatches = [];
    hideMapSearchResults();
    return;
  }
  state.mapSearchMatches = findCabinetMatches(q).slice(0, 10);
  els.mapSearchResults.hidden = false;
  els.mapSearchResults.innerHTML = state.mapSearchMatches.length
    ? state.mapSearchMatches
        .map(
          (item) =>
            `<button class="map-search-result" type="button" data-node-id="${escapeHtml(item.id)}">${escapeHtml(item.name)}</button>`
        )
        .join("")
    : `<div class="map-search-empty">未找到匹配柜子</div>`;
}

function hideMapSearchResults() {
  els.mapSearchResults.hidden = true;
}

function findCabinetMatches(q) {
  const nodes = Object.values((state.topology && state.topology.layout && state.topology.layout.nodes) || {})
    .filter((node) => node.kind === "substation" && node.name);
  return nodes
    .map((node) => {
      const name = String(node.name || "");
      const normalized = name.toLowerCase();
      let score = 3;
      if (normalized === q) score = 0;
      else if (normalized.startsWith(q)) score = 1;
      else if (normalized.includes(q)) score = 2;
      else if (searchBlob(node.id, node.rawId, node.objectId).includes(q)) score = 3;
      else return null;
      return { type: "node", id: node.id, name, score };
    })
    .filter(Boolean)
    .sort((a, b) => a.score - b.score || a.name.length - b.name.length || a.name.localeCompare(b.name, "zh-Hans-CN"));
}

function locateSearchTarget(query, preferredNodeId = "", cabinetOnly = false) {
  const svg = els.svgHost.querySelector("svg");
  if (!svg || !state.topology) return;
  svg.querySelectorAll(".device-highlight").forEach((item) => item.classList.remove("device-highlight"));
  const q = query.trim().toLowerCase();
  if (!q) return;
  const match =
    (preferredNodeId && findCabinetMatches(q).find((item) => item.id === preferredNodeId)) ||
    (cabinetOnly ? findCabinetMatches(q)[0] : findSearchTarget(q));
  if (!match) {
    els.statusText.textContent = `未找到：${query}`;
    return;
  }
  const el =
    match.type === "node"
      ? svg.querySelector(`[data-node-id="${cssEscape(match.id)}"]`)
      : svg.querySelector(`[data-eq-id="${cssEscape(match.id)}"]`);
  if (el) {
    el.classList.add("device-highlight");
    zoomToSvgElement(el, match.type);
    els.statusText.textContent = `已定位：${match.name}`;
  }
}

function findSearchTarget(q) {
  const topo = state.topology;
  const nodes = Object.values((topo.layout && topo.layout.nodes) || {});
  const cabinetMatch = findCabinetMatches(q)[0];
  if (cabinetMatch) return cabinetMatch;

  const nodeMatch = nodes.find((node) => {
    return searchBlob(node.id, node.rawId, node.objectId, node.name, node.kind).includes(q);
  });
  if (nodeMatch) {
    return { type: "node", id: nodeMatch.id, name: nodeMatch.name || nodeMatch.rawId || nodeMatch.id };
  }

  const equipmentMatch = topo.graph.equipment.find((item) => {
    return searchBlob(item.id, item.mrid, item.name, item.dispatchNumber, item.tag).includes(q);
  });
  if (equipmentMatch) {
    return {
      type: "equipment",
      id: equipmentMatch.id,
      name: equipmentMatch.dispatchNumber || equipmentMatch.name || equipmentMatch.mrid || equipmentMatch.id
    };
  }

  const nodeByEquipment = nodes.find((node) => {
    return (node.equipment || []).some((eqId) => {
      const item = topo.graph.equipmentById[eqId];
      return item && searchBlob(item.id, item.mrid, item.name, item.dispatchNumber, item.tag).includes(q);
    });
  });
  if (nodeByEquipment) {
    return { type: "node", id: nodeByEquipment.id, name: nodeByEquipment.name || nodeByEquipment.rawId || nodeByEquipment.id };
  }

  return null;
}

function searchBlob(...values) {
  return values
    .filter((value) => value !== undefined && value !== null)
    .join(" ")
    .toLowerCase();
}

function zoomToSvgElement(el, type) {
  const svg = els.svgHost.querySelector("svg");
  if (!svg || !el || !el.getBBox) return;
  let box;
  try {
    box = el.getBBox();
  } catch (err) {
    return;
  }
  if (!box || !Number.isFinite(box.x) || !Number.isFinite(box.y)) return;

  fitView();
  const viewBox = svg.viewBox && svg.viewBox.baseVal;
  if (!viewBox || !viewBox.width || !viewBox.height) return;

  const hostBox = els.svgHost.getBoundingClientRect();
  const aspect = hostBox.width && hostBox.height ? hostBox.width / hostBox.height : 16 / 9;
  const pad = type === "node" ? 64 : 54;
  let width = Math.max(box.width + pad * 2, type === "node" ? 420 : 300);
  let height = Math.max(box.height + pad * 2, type === "node" ? 270 : 210);
  if (width / height > aspect) {
    height = width / aspect;
  } else {
    width = height * aspect;
  }

  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  const scale = clamp(
    Math.min(viewBox.width / width, viewBox.height / height),
    1.15,
    SEARCH_MAX_ZOOM
  );
  state.transform = {
    scale,
    x: (viewBox.x + viewBox.width / 2) / scale - cx,
    y: (viewBox.y + viewBox.height / 2) / scale - cy
  };
  applyTransform();
}

function fitView() {
  const svg = els.svgHost.querySelector("svg");
  if (svg && state.topology && state.topology.layout) {
    const nodes = Object.values(state.topology.layout.nodes || {});
    if (nodes.length) {
      const pad = 140;
      const minX = Math.min(...nodes.map((node) => Number(node.x) || 0));
      const minY = Math.min(...nodes.map((node) => Number(node.y) || 0));
      const maxX = Math.max(...nodes.map((node) => (Number(node.x) || 0) + (Number(node.width) || 0)));
      const maxY = Math.max(...nodes.map((node) => (Number(node.y) || 0) + (Number(node.height) || 0)));
      svg.setAttribute("viewBox", `${minX - pad} ${minY - pad} ${maxX - minX + pad * 2} ${maxY - minY + pad * 2}`);
    }
  }
  state.transform = { scale: 1, x: 0, y: 0 };
  applyTransform();
}

function onWheel(evt) {
  const svg = els.svgHost.querySelector("svg");
  if (!svg) return;
  evt.preventDefault();
  closeSwitchContextMenu();
  const pointer = clientToSvgPoint(evt.clientX, evt.clientY);
  const wheelDelta = normalizeWheelDelta(evt);
  const zoomFactor = Math.exp(-wheelDelta * 0.0018);
  const nextScale = clamp(
    state.transform.scale * zoomFactor,
    MIN_ZOOM,
    MAX_ZOOM
  );
  zoomAtSvgPoint(nextScale, pointer);
  applyTransform();
}

function normalizeWheelDelta(evt) {
  if (evt.deltaMode === 1) return evt.deltaY * 16;
  if (evt.deltaMode === 2) return evt.deltaY * Math.max(els.svgHost.clientHeight, 1);
  return evt.deltaY;
}

function zoomAtSvgPoint(nextScale, point) {
  const previous = state.transform;
  if (nextScale <= MIN_ZOOM + 0.0001) {
    state.transform = { scale: MIN_ZOOM, x: 0, y: 0 };
    return;
  }
  if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) {
    state.transform.scale = nextScale;
    return;
  }

  const contentX = point.x / previous.scale - previous.x;
  const contentY = point.y / previous.scale - previous.y;
  state.transform = {
    scale: nextScale,
    x: point.x / nextScale - contentX,
    y: point.y / nextScale - contentY
  };
}

function onPointerDown(evt) {
  if (!els.svgHost.querySelector("svg")) return;
  if (evt.button != null && evt.button !== 0) return;
  if (evt.target && evt.target.closest && evt.target.closest(".device,.topo-edge")) return;
  evt.preventDefault();
  const svgPoint = clientToSvgPoint(evt.clientX, evt.clientY);
  state.dragging = {
    x: evt.clientX,
    y: evt.clientY,
    svgX: svgPoint ? svgPoint.x : 0,
    svgY: svgPoint ? svgPoint.y : 0,
    tx: state.transform.x,
    ty: state.transform.y,
    pointerId: evt.pointerId
  };
  if (els.svgHost.setPointerCapture && evt.pointerId != null) {
    try {
      els.svgHost.setPointerCapture(evt.pointerId);
    } catch (err) {
      // Some browsers can reject capture after a synthetic pointer event.
    }
  }
}

function onPointerMove(evt) {
  if (!state.dragging) return;
  const svgPoint = clientToSvgPoint(evt.clientX, evt.clientY);
  if (svgPoint) {
    state.transform.x = state.dragging.tx + (svgPoint.x - state.dragging.svgX) / state.transform.scale;
    state.transform.y = state.dragging.ty + (svgPoint.y - state.dragging.svgY) / state.transform.scale;
  } else {
    state.transform.x = state.dragging.tx + clientDeltaToSvgDelta(evt.clientX - state.dragging.x, "x") / state.transform.scale;
    state.transform.y = state.dragging.ty + clientDeltaToSvgDelta(evt.clientY - state.dragging.y, "y") / state.transform.scale;
  }
  applyTransform();
}

function endDrag() {
  if (!state.dragging) return;
  if (els.svgHost.releasePointerCapture && state.dragging.pointerId != null) {
    try {
      els.svgHost.releasePointerCapture(state.dragging.pointerId);
    } catch (err) {
      // Pointer capture may already have been released by the browser.
    }
  }
  state.dragging = null;
}

function clientToSvgPoint(clientX, clientY) {
  const svg = els.svgHost.querySelector("svg");
  if (!svg || !svg.createSVGPoint || !svg.getScreenCTM) return null;
  const matrix = svg.getScreenCTM();
  if (!matrix) return null;
  const point = svg.createSVGPoint();
  point.x = clientX;
  point.y = clientY;
  return point.matrixTransform(matrix.inverse());
}

function clientDeltaToSvgDelta(delta, axis) {
  const svg = els.svgHost.querySelector("svg");
  const viewBox = svg && svg.viewBox && svg.viewBox.baseVal;
  const hostBox = els.svgHost.getBoundingClientRect();
  if (!viewBox || !hostBox.width || !hostBox.height) return delta;
  const svgAspect = viewBox.width / viewBox.height;
  const hostAspect = hostBox.width / hostBox.height;
  const unitsPerPixel =
    axis === "x"
      ? (hostAspect > svgAspect ? viewBox.height / hostBox.height : viewBox.width / hostBox.width)
      : (hostAspect > svgAspect ? viewBox.height / hostBox.height : viewBox.width / hostBox.width);
  return delta * unitsPerPixel;
}

function applyTransform() {
  const viewport = els.svgHost.querySelector("#viewport");
  if (!viewport) return;
  const { scale, x, y } = state.transform;
  viewport.setAttribute("transform", `scale(${scale}) translate(${x} ${y})`);
}

function exportSvg() {
  if (!state.line) return;
  const params = new URLSearchParams({
    file: state.line.relativePath,
    related: state.relatedMode,
    maxRelated: "16"
  });
  window.open(`/api/svg?${params.toString()}`, "_blank");
}

async function exportTextTopology() {
  if (!state.line || !state.topology) return;
  const button = document.getElementById("exportTextTopology");
  button.disabled = true;
  try {
    const lineName = state.line.displayName || state.line.lineName || "图模";
    const res = await fetch("/api/topology/text", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({
        file: state.line.relativePath,
        related: state.relatedMode,
        maxRelated: 64,
        switchStates: state.switchStates,
        fileName: `${lineName}-文字拓扑.txt`
      })
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.error || "图模文本导出失败");
    }
    const blob = await res.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = `${lineName}-文字拓扑.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    els.statusText.textContent = `已导出 ${lineName} 的文字拓扑`;
  } catch (error) {
    els.statusText.textContent = error.message || "图模文本导出失败";
  } finally {
    button.disabled = false;
  }
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cssEscape(value) {
  if (window.CSS && CSS.escape) return CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}
