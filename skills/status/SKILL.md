---
name: status
description: "READ-ONLY health check for an infra-copilot repo: run every step's check across the whole manifest (HCP org, workspaces, Cloudflare token, GitHub App, plans, imports) and report exactly where things stand — what's green, what's the first red step, and which skill fixes it. Changes NOTHING. Use this WHENEVER the user asks where infra stands or whether it's done, rather than asking to change it. Trigger on: 'is our infra actually set up or did it stall', 'did the bootstrap finish', 'where did setup get to', 'which step is red', 'infra doctor', 'health check don't change anything', 'check infra state', 'audit the infra config'. Prefer this (read-only) over setup/import/add when the user only wants to know status; then it tells them which skill to run next."
---

# infra-copilot: status

A **read-only** pass over the whole `infra-copilot` manifest. It runs the same resume scan
the action skills use, but stops there: it reports state and **never provisions, pastes,
or applies anything.** Use it to answer "where are we?" before picking a next action.

This file is a **router**: the machinery — actor model, resume scan, preflight — is in
[`../shared/protocol.md`](../shared/protocol.md); the manifest it scans is
[`../shared/steps.yaml`](../shared/steps.yaml).

## What it does

1. **Read config** (shared protocol, Step 0). Load `.claude/infra-copilot.local.md`,
   export the org vars ([`../shared/config.md`](../shared/config.md)). Missing/incomplete
   config is itself a finding — report it and stop; do **not** offer to scaffold or edit
   (that belongs to `setup`).
2. **Preflight** — report which of `terraform`/`gh`/`jq`/`curl` are present and whether
   Terraform meets the ≥ 1.9 floor. Report the HCP token pivot: present or not.
3. **Full resume scan** — walk **every** step in
   [`../shared/steps.yaml`](../shared/steps.yaml) (all phases, 0–6) and run each `check`.
   Run checks only; never run a step's `run`. For a `HUMAN` step, run its `check` too —
   don't emit the handoff block (nothing is being unblocked here).

## Report format

Print a phase-by-phase table, then a one-line verdict. Use this shape:

```
infra-copilot status — <repo> (org: $ORG)

Preflight   terraform 1.x ✓   gh ✓   jq ✓   curl ✓   HCP token ✓
Phase 0  HCP bootstrap    ✓ hcp-signup  ✓ hcp-login  ✓ hcp-verify
Phase 1  workspaces       ✓ vcs-connect  ✗ workspaces-create   ← first red
Phase 2  cloudflare       – cf-token            (not reached)
…
Verdict: bootstrap incomplete — first red is `workspaces-create` (phase 1).
         Fix with: infra-copilot:setup
```

Legend: `✓` check passed · `✗` check failed · `–` not evaluated / not reached.

## Verdict → which skill

Map the first red step to the skill that owns it, so the user knows what to run next:

| First red step is in… | Run |
|---|---|
| Phases 0–4 | **infra-copilot:setup** |
| Phase 5 (migrate-*) | **infra-copilot:import** — only relevant if adopting pre-existing resources |
| Phase 6 (gcp-*) | **infra-copilot:add** — and only after the design decision |
| All green | Nothing — repo is set up. |

Note that a red Phase 5 or 6 is **expected and fine** for most repos — they're optional
(import only matters if resources pre-exist; GCP is a template). Say so rather than
flagging them as failures. The meaningful failure is a red step in phases 0–4.
