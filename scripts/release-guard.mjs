// Dependency-free release guard: stops a release whose preconditions fail.
// Run by the release workflow before release-please; exits non-zero and lists
// every failed precondition.
//
//   node scripts/release-guard.mjs --publish   the package is published to npm
//   node scripts/release-guard.mjs --private   the package is never published
//
// Preconditions:
//   - package.json, the release-please manifest and every generated plugin
//     manifest carry the same version, so a release PR cannot leave drift;
//   - the mode matches package.json: `--publish` needs a public package,
//     `--private` needs `"private": true`.
import { readFileSync } from "node:fs";

if (Number(process.versions.node.split(".")[0]) < 20) {
  console.error("release-guard: Node 20 or newer is required");
  process.exit(1);
}

const mode = process.argv[2];
if (process.argv.length !== 3 || !["--publish", "--private"].includes(mode)) {
  console.error("release-guard: usage: release-guard.mjs --publish|--private");
  process.exit(1);
}

const problems = [];
const readJson = (path) => {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    problems.push(`${path}: cannot read as JSON (${error.code ?? error.name})`);
    return undefined;
  }
};

const pkg = readJson("package.json");
const versions = {
  "package.json": pkg?.version,
  ".release-please-manifest.json": readJson(".release-please-manifest.json")?.["."],
  ".claude-plugin/plugin.json": readJson(".claude-plugin/plugin.json")?.version,
  ".claude-plugin/marketplace.json": readJson(".claude-plugin/marketplace.json")?.plugins?.[0]?.version,
  ".codex-plugin/plugin.json": readJson(".codex-plugin/plugin.json")?.version,
};
for (const [path, version] of Object.entries(versions)) {
  if (typeof version !== "string" || version !== versions["package.json"]) {
    problems.push(`${path}: version ${JSON.stringify(version)} does not match package.json ${JSON.stringify(versions["package.json"])}`);
  }
}

if (pkg) {
  if (mode === "--publish" && pkg.private === true) {
    problems.push('package.json: "private": true, but the repo publishes to npm');
  }
  if (mode === "--private" && pkg.private !== true) {
    problems.push('package.json: must be "private": true, because the repo does not publish to npm');
  }
}

if (problems.length) {
  console.error(`release-guard: release stopped\n${problems.map((p) => `  ${p}`).join("\n")}`);
  process.exit(1);
}
console.log("release-guard: preconditions hold");
