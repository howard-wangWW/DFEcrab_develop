//XML 解析器
//CIM/RDF 格式的电网图模文件（XML），
// 把 XML 文件翻译成程序能理解的 JSON 结构。
const fs = require("fs");
const path = require("path");
// 每个 XML 文件包含以下设备类型：
const RDF_ID_RE = /rdf:ID="([^"]+)"/;
const EQUIPMENT_TAGS = [
  "ACLineSegment",      // 线路段
  "BusbarSection",      // 母线
  "Breaker",            // 断路器
  "LoadBreakSwitch",    // 负荷开关
  "Disconnector",       // 隔离开关
  "GroundDisconnector", // 接地开关
  "Fuse",               // 熔断器
  "Jumper",             // 跳线
  "PowerTransformer",   // 变压器
  "TransformerWinding",// 变压器绕组
  "EnergyConsumer"      // 用电设备
];

function stripHash(value) {
  return (value || "").replace(/^#/, "");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function text(block, tag) {
  const safe = escapeRegExp(tag);
  const re = new RegExp(`<cim:${safe}>([\\s\\S]*?)<\\/cim:${safe}>`);
  const match = block.match(re);
  return match ? decodeXml(match[1].trim()) : "";
}

function ref(block, tag) {
  const safe = escapeRegExp(tag);
  const re = new RegExp(`<cim:${safe}\\s+rdf:resource="([^"]+)"\\s*\\/?\\s*>`);
  const match = block.match(re);
  return match ? stripHash(match[1]) : "";
}

function decodeXml(value) {
  return String(value || "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function parseBlocks(xml, tag, visitor) {
  const safe = escapeRegExp(tag);
  const re = new RegExp(`<cim:${safe}\\s+rdf:ID="([^"]+)"[\\s\\S]*?<\\/cim:${safe}>`, "g");
  let match;
  while ((match = re.exec(xml))) {
    visitor(match[1], match[0]);
  }
}
//解析单个 XML 文件，返回设备列表、连接关系、电源点
function parseCimFile(filePath, options = {}) {
  const includeEquipment = options.includeEquipment !== false;
  const includeTerminals = options.includeTerminals !== false;
  const includeSubstations = options.includeSubstations !== false;
  const xml = fs.readFileSync(filePath, "utf8");
  const model = {
    filePath,
    fileName: path.basename(filePath),
    circuits: [],
    substations: new Map(),
    equipment: new Map(),
    terminals: [],
    psrTypes: new Map(),
    windingToTransformer: new Map()
  };

  parseBlocks(xml, "PSRType", (id, block) => {
    model.psrTypes.set(id, {
      id,
      mrid: text(block, "Naming.mRID") || text(block, "Naming.mrid"),
      name: text(block, "Naming.name"),
      category: text(block, "PSRType.transSubDistCategory")
    });
  });

  parseBlocks(xml, "Circuit", (id, block) => {
    model.circuits.push({
      id,
      name: text(block, "Naming.name"),
      mrid: text(block, "Naming.mRID") || text(block, "Naming.mrid"),
      dispatchNumber: text(block, "PowerSystemResource.dispatchNumber"),
      psrType: ref(block, "PowerSystemResource.PSRType"),
      baseVoltage: ref(block, "PowerSystemResource.BaseVoltage"),
      sourceSubst: ref(block, "Circuit.SourceSubst"),
      sourceBreaker: ref(block, "Circuit.SourceBreaker"),
      isCurrentCircuit: text(block, "Circuit.isCurrentCircuit") === "true",
      isSpecialLine: text(block, "Circuit.isSpecialLine") === "true"
    });
  });

  if (includeSubstations) {
    parseBlocks(xml, "Substation", (id, block) => {
      model.substations.set(id, {
        id,
        name: text(block, "Naming.name"),
        mrid: text(block, "Naming.mRID") || text(block, "Naming.mrid"),
        psrType: ref(block, "PowerSystemResource.PSRType"),
        baseVoltage: ref(block, "PowerSystemResource.BaseVoltage"),
        circuit: ref(block, "Substation.MemberOf_Circuit")
      });
    });
  }

  if (includeEquipment) {
    for (const tag of EQUIPMENT_TAGS) {
      parseBlocks(xml, tag, (id, block) => {
        const item = {
          id,
          tag,
          name: text(block, "Naming.name"),
          mrid: text(block, "Naming.mRID") || text(block, "Naming.mrid"),
          dispatchNumber: text(block, "PowerSystemResource.dispatchNumber"),
          psrType: ref(block, "PowerSystemResource.PSRType"),
          baseVoltage: ref(block, "PowerSystemResource.BaseVoltage"),
          container: ref(block, "Equipment.MemberOf_EquipmentContainer"),
          capacity: text(block, "PowerTransformer.ratedCapacity"),
          transformerType: text(block, "PowerTransformer.Transformer_Type"),
          parentTransformer: ref(block, "TransformerWinding.MemberOf_PowerTransformer"),
          files: [filePath]
        };
        if (tag === "TransformerWinding" && item.parentTransformer) {
          model.windingToTransformer.set(id, item.parentTransformer);
        }
        model.equipment.set(id, item);
      });
    }
  }

  if (includeTerminals) {
    parseBlocks(xml, "Terminal", (id, block) => {
      const eq = ref(block, "Terminal.ConductingEquipment");
      const cn = ref(block, "Terminal.ConnectivityNode");
      if (eq && cn) {
        model.terminals.push({ id, equipment: eq, connectivityNode: cn });
      }
    });
  }

  return model;
}
//只解析元数据（文件名、变电站、馈线号）
function parseCimMeta(filePath) {
  const model = parseCimFile(filePath, {
    includeEquipment: false,
    includeTerminals: true,
    includeSubstations: true
  });
  const current = model.circuits.find((item) => item.isCurrentCircuit) || model.circuits[0] || null;
  return {
    filePath,
    fileName: path.basename(filePath),
    relativePath: "",
    circuit: current,
    circuits: model.circuits,
    substations: [...model.substations.values()],
    connectivityNodeIds: [...new Set(model.terminals.map((terminal) => terminal.connectivityNode).filter(Boolean))]
  };
}
//合并两个 XML 的模型数据（用于关联馈线）
function mergeModels(models) {
  const merged = {
    filePath: models[0] ? models[0].filePath : "",
    fileName: models[0] ? models[0].fileName : "",
    circuits: [],
    substations: new Map(),
    equipment: new Map(),
    terminals: [],
    psrTypes: new Map(),
    windingToTransformer: new Map()
  };
  const terminalKeys = new Set();
  for (const model of models) {
    mergeModelInto(merged, model, terminalKeys);
  }
  return merged;
}

function mergeModelInto(merged, model, terminalKeys = null) {
  if (!merged || !model) return merged;
  const keys =
    terminalKeys ||
    new Set(
      (merged.terminals || []).map(
        (terminal) => `${terminal.equipment}|${terminal.connectivityNode}`
      )
    );
  if (!merged.filePath && model.filePath) merged.filePath = model.filePath;
  if (!merged.fileName && model.fileName) merged.fileName = model.fileName;
  for (const circuit of model.circuits) {
    if (!merged.circuits.some((item) => item.id === circuit.id)) {
      merged.circuits.push(circuit);
    }
  }
  for (const [id, item] of model.substations) {
    if (!merged.substations.has(id)) merged.substations.set(id, { ...item });
  }
  for (const [id, item] of model.equipment) {
    if (!merged.equipment.has(id)) {
      merged.equipment.set(id, { ...item, files: [...(item.files || [])] });
    } else {
      const existing = merged.equipment.get(id);
      const files = new Set([...(existing.files || []), ...(item.files || [])]);
      existing.files = [...files];
    }
  }
  for (const [id, parent] of model.windingToTransformer) {
    merged.windingToTransformer.set(id, parent);
  }
  for (const [id, item] of model.psrTypes) {
    if (!merged.psrTypes.has(id)) merged.psrTypes.set(id, item);
  }
  for (const terminal of model.terminals) {
    const key = `${terminal.equipment}|${terminal.connectivityNode}`;
    if (keys.has(key)) continue;
    keys.add(key);
    merged.terminals.push(terminal);
  }
  return merged;
}

module.exports = {
  EQUIPMENT_TAGS,
  parseCimFile,
  parseCimMeta,
  mergeModels,
  mergeModelInto,
  stripHash
};
