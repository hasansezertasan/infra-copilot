---
name: status
description: "READ-ONLY health check for an infra-copilot repo: run every step's check across the whole manifest (HCP org, workspaces, Cloudflare token, GitHub App, plans, imports) and report exactly where things stand — what's green, what's the first red step, and which skill fixes it. Changes NOTHING. Use this WHENEVER the user asks where infra stands or whether it's done, rather than asking to change it. Trigger on: 'is our infra actually set up or did it stall', 'did the bootstrap finish', 'where did setup get to', 'which step is red', 'infra doctor', 'health check don't change anything', 'check infra state', 'audit the infra config'. Prefer this (read-only) over setup/import/add when the user only wants to know status; then it tells them which skill to run next."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:26ac46b46683321f8dde4d6852569339046a3e4ad7c6798a4c6813d6aa0a6c32
Source-Hash: blake3:4c4be53a504ab0eb505449e369f2d08953fc82292a1de10981172419bd136621
Schema-Version: v1
-->

# infra-copilot: status

A **read-only** pass over the whole `infra-copilot` manifest. It runs the same resume scan
the action skills use, but stops there: it reports state and **never provisions, pastes,
or applies anything.** Use it to answer "where are we?" before picking a next action.

This file is a **router**: the machinery — actor model, resume scan, preflight — is in
[`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md); the manifest it scans is
[`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml).

## What it does

1. **Read config** (shared protocol, Step 0). Load `.infra-copilot/config.md`, falling
   back to `.claude/infra-copilot.local.md` for migration, and export the org vars
   ([`../infra-copilot/references/config.md`](../infra-copilot/references/config.md)). If both are missing, or the loaded
   config is incomplete, report it and stop; do **not** offer to scaffold or edit (that
   belongs to `setup`).
2. **Preflight** — report which of `terraform`/`gh`/`jq`/`curl` are present and whether
   Terraform meets the ≥ 1.9 floor. Report the HCP token pivot: present or not.
3. **Full scan — but only with checks that don't touch the working tree.** Walk **every**
   step in [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml) (all phases, 0–6). Never run a
   step's `run`. Classify each `check` before running it — the read-only guarantee depends
   on this:

   - **Non-mutating checks** (HCP/Cloudflare/GitHub API reads, file existence, tool
     versions — phases 0–3) — run them directly. These only read.
   - **Mutating checks — do NOT run them.** The phase-4 checks (`plan-cloudflare`,
     `plan-github`) and the phase-5 `migrate-import` check run `terraform init`/`plan`,
     which writes `.terraform/` and can create or update `.terraform.lock.hcl` — that would
     dirty the checkout, and this command promises to change nothing. Instead, read the
     **run status per workspace via the HCP API** (non-mutating — see
     [`../infra-copilot/references/docs/hcp-api.md`](../infra-copilot/references/docs/hcp-api.md)). Resolve the current revision
     with `git rev-parse HEAD`, then use the guide's specific-commit lookup, which
     correlates on the run's configuration-version ingress `commit-sha` — never on the run
     message — and names every operation so the PR's *speculative* plan is visible at all.
     Judge only the lookup's `latest`, the newest run for that revision: green is its
     `"green": true`. A newest run that is failing or still in flight, a run for any other
     revision, or no match at all is `?` (current revision not verified). Never let an
     older green run for the same commit override a newer failing one.
   - **Null checks** (`check: ~`, e.g. `migrate-discovery-token`) — nothing scriptable to
     run. Report them as `·` (human-gated / ephemeral), never attempt to execute the null.
   - For `HUMAN` steps, apply the same classification to their `check`; never emit the
     handoff block — nothing is being unblocked here.

   **Completion vs. not-started (phase 5).** The `migrate-import` check only goes green while
   a plan still shows `will be imported`; once imports are **applied**, the plan is a no-op
   and that check reads red even though the work is done. So don't equate red-phase-5 with
   "import needed." Do not read the inverse into a clean run either: a speculative
   `planned_and_finished` run is "clean" *and* can still carry `will be imported`, which
   means the imports are pending, not finished. A successful plan is evidence the config is
   valid, never evidence that it was applied.

   Infer *done* only from committed state plus a demonstrably empty import set:
   `terraform/cloudflare/generated.tf` exists (committed) **and** the plan summary for the
   latest run on the current revision reports `imports: 0` — read it with the plan-summary
   helper in
   [`../infra-copilot/references/docs/hcp-api.md`](../infra-copilot/references/docs/hcp-api.md).
   If that summary still counts imports, or you cannot read it, phase 5 is **incomplete**;
   report it that way rather than inferring completion from a green run. Only call phase 5
   actionable when resources demonstrably exist at the provider but aren't in state.

## Report format

Print a phase-by-phase table, then a one-line verdict. Use this shape:

```
infra-copilot status — <repo> (org: $ORG)

Preflight   terraform 1.x ✓   gh ✓   jq ✓   curl ✓   HCP token ✓
Phase 0  HCP bootstrap    ✓ hcp-login  ✓ hcp-signup  ✓ hcp-verify
Phase 1  workspaces       ✓ vcs-connect  ✗ workspaces-create   ← first red
Phase 2  cloudflare       – cf-token            (not reached)
…
Verdict: bootstrap incomplete — first red is `workspaces-create` (phase 1).
         Fix with: infra-copilot:setup
```

Legend: `✓` passed · `✗` failed · `–` not evaluated / not reached · `?` plan-gated
(read from HCP API, not run locally) · `·` human-gated / ephemeral (null check, not executed).

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
