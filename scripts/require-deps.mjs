// Runs before `npm run check` (npm's `precheck` hook, so `check:all` gets it too).
// Without `npm ci`, `npx` resolves some other `ai-rulez` and the check dies with
// an unrelated message such as `unknown flag: --check`.
import { existsSync } from "node:fs";

if (!existsSync("node_modules/.bin/ai-rulez")) {
  console.error("require-deps: node_modules is missing the pinned tools; run `npm ci` first");
  process.exit(1);
}
