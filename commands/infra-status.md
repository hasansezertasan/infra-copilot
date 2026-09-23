---
description: "Shortcut that loads the infra-copilot status skill — read-only health check that scans every manifest step and reports where infra stands and which skill fixes the first red step."
allowed-tools: Read, Bash, Glob, Grep, Task
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:d82d262129f6876d22b29897255724a86746f85d276e7597315931461b5f80b3
Source-Hash: blake3:dbf5e6ca31477bb16666c5bc013ab59d0f71112ab8882d06315e3976a883c93e
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
   skill that fixes it (setup / import / prune / add). Three exceptions the skill defines, and it owns
   the detail: a red *migration* step in phases 5–6 is expected for most repos — say so,
   don't flag as failure — but a red `prune-spent-imports` is actionable, so never fold it
   into that exemption; which skill it routes to is the verdict table's call, because the
   same red means *spent, clean them up* after an applied run and *unfinished, keep going*
   before one;
   `status-check-context` exiting 1 maps to **no skill**, because it is fixed directly in
   `terraform/github/branch_protection.tf`; and `status-check-context` exiting 2 is
   `CANNOT VERIFY` — report it as `?` with its cause and route nowhere, since an
   unreadable check says nothing about the repository. Follow the skill's verdict table
   rather than routing everything in phases 0–4 to `setup`.

The status skill itself defines and enforces the read-only contract across hosts.
