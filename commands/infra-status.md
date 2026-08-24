---
description: "Shortcut that loads the infra-copilot status skill — read-only health check that scans every manifest step and reports where infra stands and which skill fixes the first red step."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:4bf5f1938f7d2e5fc24d99918cb637a99610d270a99a65e1890256425203a298
Source-Hash: blake3:c5685395138066d55267f7fc18e082e5ba4632a7e2e8ed3145b4749f4becfdb1
Schema-Version: v1
-->

# /infra-status

Explicit entry point for the [`status`](../skills/status/SKILL.md) skill — a **read-only**
pass that runs every step's `check` across the whole manifest and reports state. Changes
nothing.

Load `../skills/status/SKILL.md` and drive it:

1. **Read config** — [`config.md`](../skills/infra-copilot/references/config.md). Missing/incomplete config
   is itself a finding; report it and stop (don't scaffold — that's `/infra-setup`).
2. **Preflight** — report tool presence + the HCP token pivot.
3. **Full resume scan** over all phases of [`steps.yaml`](../skills/infra-copilot/references/steps.yaml). Run
   `check`s only — never a step's `run`, never a handoff block.
4. **Report** the phase-by-phase table and a verdict mapping the first red step to the
   skill that fixes it (setup / import / add). Phases 5–6 red is expected for most repos —
   say so, don't flag as failure.

The status skill itself defines and enforces the read-only contract across hosts.
