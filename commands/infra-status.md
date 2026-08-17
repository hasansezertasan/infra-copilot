---
description: "Shortcut that loads the infra-copilot status skill — read-only health check that scans every manifest step and reports where infra stands and which skill fixes the first red step."
allowed-tools: Read, Bash, Glob, Grep
---

# /infra-status

Explicit entry point for the [`status`](../skills/status/SKILL.md) skill — a **read-only**
pass that runs every step's `check` across the whole manifest and reports state. Changes
nothing.

Load `../skills/status/SKILL.md` and drive it:

1. **Read config** — [`config.md`](../shared/config.md). Missing/incomplete config
   is itself a finding; report it and stop (don't scaffold — that's `/infra-setup`).
2. **Preflight** — report tool presence + the HCP token pivot.
3. **Full resume scan** over all phases of [`steps.yaml`](../shared/steps.yaml). Run
   `check`s only — never a step's `run`, never a handoff block.
4. **Report** the phase-by-phase table and a verdict mapping the first red step to the
   skill that fixes it (setup / import / add). Phases 5–6 red is expected for most repos —
   say so, don't flag as failure.

Note the restricted tools: this command intentionally has no `Edit`/`Write` — it only reads.
