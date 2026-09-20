#!/usr/bin/env node
const { reloadUpdateManifest } = require("../src/dataUpdater");

async function main() {
  const manifest = process.argv[2] || "reload.json";
  const result = await reloadUpdateManifest({ manifest, confirm: "APPLY" });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message || error}\n`);
  process.exitCode = 1;
});
