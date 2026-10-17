// Dependency-free repository check: the hardening rules CI relies on.
// Run by `npm run check` from the repo root; exits non-zero and lists every
// violation.
//
// There is no YAML parser on purpose. The check reads one strict subset of
// block-style YAML and fails closed on everything else, so a workflow it cannot
// read can never pass: every line must be `key:`, `key: value`, `- key: value`,
// `- value` or a lone `-`. Flow collections (except `{}`, `[]` and a list of
// plain words), tags, anchors, aliases, explicit keys, multi-line scalars, tabs,
// duplicate keys, multiple documents and inconsistent indentation are errors.
// Block scalars (`run: |`) are skipped. Rules enforced:
//   - top-level `permissions: {}` and a scoped `permissions` on every job;
//   - every step's and job's `uses:` pinned by commit SHA (`./` is exempt);
//   - where the generated Claude manifest exists, the Antigravity adapter (the
//     root `plugin.json`) exists, declares the Antigravity `$schema` and carries
//     the same `name` and `description`. (Codex adopts a root plugin.json that
//     declares the portable agent-plugins.org schema as its own manifest.)
//     The template repository, which has no generated output, is skipped.
//   - no host-loaded component at the repository root (`.mcp.json`, `hooks/`,
//     ...), anywhere this runs: both catalogs install the root, so the host
//     would ship it. ai-rulez reports these as AR9T0, a rule the template turns
//     off for the adapter. A repo that ships one on purpose lists it, with the
//     reason, in `.config/root-components.json`.
// Scanned: `.github/workflows` and `action.yml`/`action.yaml` under
// `.github/actions`. Local actions elsewhere are not followed.
import { existsSync, lstatSync, readdirSync, readFileSync, statSync } from "node:fs";
import { basename, join } from "node:path";

if (Number(process.versions.node.split(".")[0]) < 20) {
  console.error("check-repo: Node 20 or newer is required");
  process.exit(1);
}

const problems = [];
const report = (path, index, message) => problems.push(`${path}:${index + 1}: ${message}`);

// A symlink counts even when its target is gone.
const lexists = (path) => {
  try {
    lstatSync(path);
    return true;
  } catch {
    return false;
  }
};
const isFile = (path) => {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
};
const yamlFiles = (dir, wanted) =>
  existsSync(dir)
    ? readdirSync(dir, { recursive: true })
        .filter((name) => wanted.test(basename(name)))
        .map((name) => join(dir, name))
    : [];

// Drops a trailing or full-line comment. Quoted text and `${{ }}` expressions
// are opaque, so a `#` inside them is not a comment.
const stripComment = (line) => {
  let quote = "";
  let previous = ""; // last non-space character outside quotes
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (quote) {
      if (char === "\\" && quote === '"') i++;
      else if (char === quote) {
        quote = "";
        previous = char;
      }
    } else if (line.startsWith("${{", i)) {
      const end = line.indexOf("}}", i);
      if (end < 0) break;
      i = end + 1;
      previous = "}";
    } else if ((char === '"' || char === "'") && (previous === "" || ":-,".includes(previous))) {
      quote = char;
    } else if (char === "#" && (i === 0 || /\s/.test(line[i - 1]))) {
      return line.slice(0, i).trimEnd();
    } else if (!/\s/.test(char)) {
      previous = char;
    }
  }
  return line.trimEnd();
};

const BLOCK_SCALAR = /^[|>][+-]?\d*[+-]?$/;
const PLAIN_WORDS = /^\[\s*[\w./-]+(?:\s*,\s*[\w./-]+)*\s*\]$/;
const QUOTED = /^(?:"(?:[^"\\]|\\.)*"|'(?:[^']|'')*')$/;
const KEY = /^(?:"([\w./-]+)"|'([\w./-]+)'|([\w./-]+)) *:(?: +([^]*))?$/;
const PROTECTED_KEY = /^(?:jobs|permissions|runs|steps|uses)$/i;

// A value is plain text, a quoted string, a block-scalar header, `{}`, `[]` or
// a flow list of plain words. Everything else is outside the supported subset.
const valueProblem = (key, value) => {
  if (value === "" || BLOCK_SCALAR.test(value) || /^\{\s*\}$/.test(value) || /^\[\s*\]$/.test(value)) return null;
  if (/^[!&*?%@`]/.test(value)) return "anchors, aliases and tags are not supported; repeat the value";
  if (PLAIN_WORDS.test(value)) return key === "steps" ? "flow style is not supported; use block style" : null;
  if (/^[{[]/.test(value)) return "flow style is not supported; use block style";
  if (/^["']/.test(value) && !QUOTED.test(value)) return "multi-line or malformed quoted scalars are not supported";
  return null;
};

// Reads one file into a tree of key nodes and list items. Structure comes from
// indentation only; anything that cannot be placed fails closed.
const readTree = (path) => {
  const text = readFileSync(path, "utf8").replace(/^﻿/, "").replace(/\r\n/g, "\n");
  if (/[\r\u0085\u2028\u2029]/.test(text)) problems.push(`${path}: unsupported line break characters`);
  const root = { type: "root", col: -1, value: "", children: [], items: [] };
  const stack = [root];
  let scalarCol = -1; // columns up to this one end a block scalar's body
  let first = true;
  text.split("\n").forEach((raw, index) => {
    const fail = (message) => report(path, index, message);
    const indent = raw.length - raw.trimStart().length;
    if (scalarCol >= 0) {
      if (raw.trim() === "" || indent > scalarCol) return;
      scalarCol = -1;
    }
    const line = stripComment(raw);
    if (line.trim() === "") return;
    if (/^ *\t/.test(line)) return fail("tabs are not supported; indent with spaces");
    if (first && line === "---") return void (first = false);
    first = false;
    if (/^(?:---|\.\.\.)(?:\s|$)/.test(line)) return fail("multiple documents are not supported");

    const [, spaces, dashText = "", rest] = /^( *)(-(?: +|$))?([^]*)$/.exec(line);
    const col = spaces.length;
    const dash = dashText !== "";
    if (/^-(?: |$)/.test(rest)) return fail("nested sequences are not supported");

    while (stack.length > 1) {
      const top = stack.at(-1);
      const opens = top.type === "key" && top.value === "";
      if (top.col > col || (top.col === col && !(dash && opens))) stack.pop();
      else break;
    }
    const parent = stack.at(-1);
    if (parent.type === "key" && parent.value !== "") return fail("a value cannot be followed by a nested block; keep scalars on one line");
    if (dash && (parent.type !== "key" || parent.children.length > 0)) return fail("unexpected sequence item");
    if (!dash && parent.type === "key" && parent.items.length > 0) return fail("a mapping cannot follow sequence items");
    if (dash && parent.itemCol !== undefined && parent.itemCol !== col) return fail("inconsistent indentation");
    if (dash) parent.itemCol = col;

    let owner = parent;
    if (dash) {
      const item = { type: "item", col, line: index, value: "", children: [], items: [] };
      parent.items.push(item);
      stack.push(item);
      owner = item;
    }
    const keyCol = col + dashText.length;
    if (rest === "") {
      if (!dash) fail("unsupported line; use `key: value` or `- value`");
      return;
    }

    const match = KEY.exec(rest);
    if (!match) {
      if (dash && BLOCK_SCALAR.test(rest)) return void (scalarCol = col);
      if (/^[!&*?%@`]/.test(rest)) return fail("anchors, aliases and tags are not supported; repeat the value");
      if (/^[{[]/.test(rest)) return fail("flow style is not supported; use block style");
      const plain = /^[\w./~$(=+][^]*$/.test(rest) && !rest.includes(": ") && !rest.endsWith(":");
      if (dash && (plain || QUOTED.test(rest))) return;
      return fail("unsupported line; use `key: value` or `- value`");
    }

    const key = match[1] ?? match[2] ?? match[3];
    const value = (match[4] ?? "").trim();
    if (owner.childCol !== undefined && owner.childCol !== keyCol) return fail("inconsistent indentation");
    owner.childCol = keyCol;
    if (PROTECTED_KEY.test(key) && key !== key.toLowerCase()) fail(`\`${key}\` must be lowercase`);
    if (owner.children.some((child) => child.key === key)) fail(`duplicate key \`${key}\``);
    const problem = valueProblem(key, value);
    if (problem) fail(problem);
    if (BLOCK_SCALAR.test(value)) scalarCol = keyCol;
    const node = { type: "key", key, value, col: keyCol, line: index, children: [], items: [] };
    owner.children.push(node);
    stack.push(node);
  });
  return root;
};

const child = (node, key) => node?.children.find((entry) => entry.key === key);

// `uses:` must carry a full commit SHA, or a sha256 digest for docker images.
// Local references (`./...`) have nothing to pin.
const checkUses = (path, node) => {
  const ref = node.value.replace(/^(["'])(.*)\1$/, "$2");
  const pinned = ref.startsWith("docker://") ? /^docker:\/\/[^@\s]+@sha256:[0-9a-f]{64}$/ : /^[^@\s]+@[0-9a-f]{40}$/;
  if (ref === "") report(path, node.line, "`uses:` has no value");
  else if (!ref.startsWith("./") && !pinned.test(ref)) report(path, node.line, `\`${ref}\` is not pinned by commit SHA`);
};

const checkSteps = (path, steps) => {
  for (const step of steps?.items ?? []) {
    const uses = child(step, "uses");
    if (uses) checkUses(path, uses);
  }
};

// A job's `permissions:` must be `{}` or a block of scopes set to read, write
// or none: no scalar such as `write-all`, no expression, no empty block.
const scopedPermissions = (node) => {
  if (/^\{\s*\}$/.test(node.value)) return true;
  const levels = node.children.map((scope) => scope.value.replace(/^(["'])(.*)\1$/, "$2"));
  return node.value === "" && node.items.length === 0 && levels.length > 0 && levels.every((level) => /^(?:read|write|none)$/.test(level));
};

const workflows = yamlFiles(".github/workflows", /\.ya?ml$/);
if (workflows.length === 0) problems.push(".github/workflows: no workflows found");

for (const path of workflows) {
  if (!isFile(path)) {
    problems.push(`${path}: not a readable file`);
    continue;
  }
  const tree = readTree(path);

  const permissions = child(tree, "permissions");
  if (!permissions || !/^\{\s*\}$/.test(permissions.value)) {
    problems.push(`${path}: top-level \`permissions: {}\` is required`);
  }

  const jobs = child(tree, "jobs");
  if (!jobs) problems.push(`${path}: no \`jobs:\` mapping found`);
  else if (jobs.children.length === 0) problems.push(`${path}: \`jobs:\` has no jobs`);
  for (const job of jobs?.children ?? []) {
    const uses = child(job, "uses");
    if (uses) checkUses(path, uses);
    checkSteps(path, child(job, "steps"));
    const own = child(job, "permissions");
    if (!own) report(path, job.line, `job \`${job.key}\` has no permissions block`);
    else if (!scopedPermissions(own)) {
      report(path, own.line, `job \`${job.key}\` has unscoped permissions; use \`{}\` or scopes set to read, write or none`);
    }
  }
}

for (const path of yamlFiles(".github/actions", /^action\.ya?ml$/)) {
  if (!isFile(path)) problems.push(`${path}: not a readable file`);
  else checkSteps(path, child(child(readTree(path), "runs"), "steps"));
}

const ANTIGRAVITY_SCHEMA = "https://antigravity.google/schemas/v1/plugin.json";

// Antigravity installs straight from the Git URL, so nothing generates its
// adapter. Keep its identity equal to the generated Claude manifest.
const readManifest = (path) => {
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    problems.push(`${path}: cannot read as JSON (${error.code ?? error.name})`);
    return undefined;
  }
  // Valid but falsy or non-object JSON (`null`, `0`, `[]`) is not a manifest.
  if (typeof manifest !== "object" || manifest === null || Array.isArray(manifest)) {
    problems.push(`${path}: must be a JSON object`);
    return undefined;
  }
  return manifest;
};
if (isFile(".claude-plugin/plugin.json")) {
  const claude = readManifest(".claude-plugin/plugin.json");
  const adapter = readManifest("plugin.json");
  if (adapter && adapter.$schema !== ANTIGRAVITY_SCHEMA) {
    problems.push(`plugin.json: $schema ${JSON.stringify(adapter.$schema)} must be ${ANTIGRAVITY_SCHEMA}`);
  }
  if (adapter && claude) {
    for (const field of ["name", "description"]) {
      if (adapter[field] !== claude[field]) {
        problems.push(
          `plugin.json: ${field} ${JSON.stringify(adapter[field])} does not match .claude-plugin/plugin.json ${JSON.stringify(claude[field])}`,
        );
      }
    }
  }
}

// Paths Claude or Codex load from an installed plugin by default. `skills/` is
// the intended payload, and `plugin.json` is the adapter checked above.
// The list is ai-rulez 5.3.0's AR9T0 set, plus `agents` and `commands` from
// Claude's standard plugin layout, which AR9T0 does not flag.
const ROOT_COMPONENTS = [
  ".mcp.json",
  ".app.json",
  ".lsp.json",
  "settings.json",
  "hooks",
  "agents",
  "commands",
  "bin",
  "output-styles",
  "workflows",
  "themes",
  "monitors",
];
// Opt-in for a repo that ships a root component deliberately (infra-copilot's
// SessionStart hook and subagent). `.config/root-components.json` is repo-owned
// and absent by default: an object mapping each allowed component to the reason
// it ships. An unknown name or an empty reason is an error, so a typo or a bare
// opt-out cannot pass.
const ALLOWLIST = ".config/root-components.json";
const allowed = new Set();
if (lexists(ALLOWLIST)) {
  const list = readManifest(ALLOWLIST);
  for (const [name, reason] of Object.entries(list ?? {})) {
    if (!ROOT_COMPONENTS.includes(name)) problems.push(`${ALLOWLIST}: ${JSON.stringify(name)} is not a root component this check knows`);
    else if (typeof reason !== "string" || reason.trim() === "") problems.push(`${ALLOWLIST}: ${name} needs a non-empty reason string`);
    else allowed.add(name);
  }
}
for (const name of ROOT_COMPONENTS) {
  if (!allowed.has(name) && lexists(name)) {
    problems.push(`root component: ${name} is loaded by the host from the installed plugin root; move it out of the repository root`);
  }
}

if (problems.length > 0) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`check-repo: ${workflows.length} workflow(s) ok`);
