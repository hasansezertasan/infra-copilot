// Dependency-free release-merge guard: permits release creation only for the
// sole pending release PR, merged as the commit being released. Without it,
// release-please can release an older, failed pending merge on a later green
// push. Run by the release workflow before release-please.
//
//   node scripts/release-merge.mjs --pulls <file> --sha <commit>
//
// <file> holds the closed pull requests as `gh api --paginate --slurp` writes
// them (an array of pages). Prints `is-release-merge=true|false` for
// $GITHUB_OUTPUT and exits 0 either way; bad usage or unreadable input exits 1.
import { readFileSync } from "node:fs";

if (Number(process.versions.node.split(".")[0]) < 20) {
  console.error("release-merge: Node 20 or newer is required");
  process.exit(1);
}

const PENDING_LABEL = "autorelease: pending";
const usage = "release-merge: usage: release-merge.mjs --pulls <file> --sha <commit>";

const args = process.argv.slice(2);
if (args.length !== 4 || args[0] !== "--pulls" || args[2] !== "--sha" || !args[3]) {
  console.error(usage);
  process.exit(1);
}
const [, pullsPath, , sha] = args;

let pages;
try {
  pages = JSON.parse(readFileSync(pullsPath, "utf8"));
} catch (error) {
  console.error(`release-merge: ${pullsPath}: cannot read as JSON (${error.code ?? error.name})`);
  process.exit(1);
}
if (!Array.isArray(pages) || !pages.every(Array.isArray)) {
  console.error(`release-merge: ${pullsPath}: expected an array of pages, as \`gh api --paginate --slurp\` writes`);
  process.exit(1);
}

const pending = pages.flat().filter(
  (pr) =>
    pr?.merged_at &&
    pr.base?.ref === "main" &&
    Array.isArray(pr.labels) &&
    pr.labels.some((label) => label?.name === PENDING_LABEL),
);
const allowed = pending.length === 1 && pending[0].merge_commit_sha === sha;

console.log(`is-release-merge=${allowed}`);
if (!allowed) {
  console.error("release-merge: release creation skipped: no unique pending release matches the validated commit");
}
