const fs = require("fs");
const path = require("path");
const { createLineIndex, resolveIndexedFile } = require("../src/indexer");
const { buildTopologyFromFile } = require("../src/topology");
const { loadSwitchStatus } = require("../src/switchStatus");
const { loadSwitchCurrent } = require("../src/switchCurrent");

const ROOT = path.resolve(__dirname, "..");
const XML_DIR = path.join(ROOT, "BLACKXML");
const STATUS_DIR = path.join(ROOT, "\u5f00\u5173\u72b6\u6001");
const CURRENT_DIRS = [ROOT, STATUS_DIR];

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    const item = argv[i];
    if (item.startsWith("--")) {
      const key = item.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith("--")) {
        args[key] = true;
      } else {
        args[key] = next;
        i++;
      }
    }
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv);
  if (!args.file) {
    console.log("Usage: node tools/generate-svg.js --file <relative XML path> [--out output.svg] [--related primary|auto|sameSource]");
    process.exit(1);
  }

  const index = createLineIndex(XML_DIR);
  let filePath = resolveIndexedFile(XML_DIR, index, args.file);
  if (!filePath) {
    const direct = path.resolve(ROOT, args.file);
    if (direct.startsWith(ROOT) && fs.existsSync(direct)) filePath = direct;
  }
  if (!filePath) {
    throw new Error(`Cannot find XML file: ${args.file}`);
  }

  const topology = buildTopologyFromFile({
    xmlDir: XML_DIR,
    filePath,
    index,
    relatedMode: args.related || "auto",
    maxRelated: Number(args.maxRelated || 64),
    maxNodes: Number(args.maxNodes || 900),
    switchStatus: loadSwitchStatus(STATUS_DIR),
    switchCurrent: loadSwitchCurrent(CURRENT_DIRS)
  });

  const out = args.out
    ? path.resolve(ROOT, args.out)
    : path.join(ROOT, "BLACKSVG_GENERATED", path.basename(filePath).replace(/\.xml$/i, ".svg"));
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, topology.svg, "utf8");
  console.log(`Generated ${out}`);
  console.log(`Equipment ${topology.stats.equipment}, switches ${topology.stats.switches}, transformers ${topology.stats.transformers}, files ${topology.includedFiles.length}`);
  console.log(`Status applied ${Object.keys(topology.graph.switchStatusById || {}).length}, switch rows ${topology.graph.statusSummary.switchRows}, ground rows ${topology.graph.statusSummary.groundRows}`);
  console.log(`Current applied ${Object.keys(topology.graph.switchCurrentById || {}).length}, current rows ${topology.graph.currentSummary.currentRows}`);
}

main();
