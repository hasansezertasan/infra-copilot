---
description: "Shortcut that loads the infra-copilot status skill — read-only health check that scans every manifest step and reports where infra stands and which skill fixes the first red step."
allowed-tools: Read, Bash, Glob, Grep
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:5fb8e6240f21ed4b6f705f5e04d7339bb6884df42299f0ebc89fa7e5dd33bc0b
Source-Hash: blake3:c7e18e4bed4625c5997461695420f0cec83964365dec9f247022fafb62fd97fb
Schema-Version: v1
-->

# /infra-status

Explicit entry point for the [`status`](../skills/status/SKILL.md) skill — a **read-only**
pass that runs every step's `check` across the whole manifest and reports state. Changes
nothing.

Load `../skills/status/SKILL.md` and drive it:

1. **Read config** — prefer `.infra-copilot/config.md`, falling back to
   `.claude/infra-copilot.local.md` for migration; see
   [`config.md`](../skills/infra-copilot/references/config.md). If both are missing, or the loaded config is
   incomplete, report it and stop (don't scaffold — that's `/infra-setup`).
2. **Preflight** — report tool presence + the HCP token pivot.
3. **Full resume scan** over all phases of [`steps.yaml`](../skills/infra-copilot/references/steps.yaml). Run
   `check`s only — never a step's `run`, never a handoff block.
4. **Report** the phase-by-phase table and a verdict mapping the first red step to the
   skill that fixes it (setup / import / add). Phases 5–6 red is expected for most repos —
   say so, don't flag as failure.

The status skill itself defines and enforces the read-only contract across hosts.
