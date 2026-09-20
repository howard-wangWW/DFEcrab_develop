//路径配置中心
const path = require("path");

const CODE_ROOT = path.resolve(__dirname, "..");
const DATA_ROOT = path.resolve(process.env.MCP_DATA_ROOT || CODE_ROOT);
const XML_DIR = path.resolve(process.env.MCP_XML_DIR || path.join(DATA_ROOT, "BLACKXML"));
const STATUS_DIR = path.resolve(process.env.MCP_STATUS_DIR || path.join(DATA_ROOT, "\u5f00\u5173\u72b6\u6001"));
const CURRENT_DIR = path.resolve(process.env.MCP_CURRENT_DIR || DATA_ROOT);
const UPDATE_DIR = path.resolve(process.env.MCP_UPDATE_DIR || path.join(DATA_ROOT, "\u66f4\u65b0\u6570\u636e"));
const BACKUP_DIR = path.resolve(process.env.MCP_BACKUP_DIR || path.join(DATA_ROOT, "\u6570\u636e\u5907\u4efd"));

module.exports = {
  CODE_ROOT,
  DATA_ROOT,
  XML_DIR,
  STATUS_DIR,
  CURRENT_DIR,
  CURRENT_DIRS: [...new Set([CURRENT_DIR, STATUS_DIR])],
  UPDATE_DIR,
  BACKUP_DIR
};
