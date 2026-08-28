---
description: "Shortcut that loads the infra-copilot status skill — read-only health check that scans every manifest step and reports where infra stands and which skill fixes the first red step."
allowed-tools: Read, Bash, Glob, Grep
---

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
   skill that fixes it (setup / import / add). Three exceptions the skill defines, and it owns
   the detail: phases 5–6 red is expected for most repos — say so, don't flag as failure;
   `status-check-context` exiting 1 maps to **no skill**, because it is fixed directly in
   `terraform/github/branch_protection.tf`; and `status-check-context` exiting 2 is
   `CANNOT VERIFY` — report it as `?` with its cause and route nowhere, since an
   unreadable check says nothing about the repository. Follow the skill's verdict table
   rather than routing everything in phases 0–4 to `setup`.

The status skill itself defines and enforces the read-only contract across hosts.
