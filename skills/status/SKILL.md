---
name: status
description: "READ-ONLY health check for an infra-copilot repo: run every step's check across the whole manifest (HCP org, workspaces, Cloudflare token, GitHub App, plans, imports) and report exactly where things stand — what's green, what's the first red step, and which skill fixes it. Changes NOTHING. Use this WHENEVER the user asks where infra stands or whether it's done, rather than asking to change it. Trigger on: 'is our infra actually set up or did it stall', 'did the bootstrap finish', 'where did setup get to', 'which step is red', 'infra doctor', 'health check don't change anything', 'check infra state', 'audit the infra config'. Prefer this (read-only) over setup/import/add when the user only wants to know status; then it tells them which skill to run next."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:2e7908085e8eb0713362482bc9f316455524dcc2d7c21167020b0c24689051d6
Source-Hash: blake3:12b3d3a72035a2f80cbef94c4a717cd26053ba55cd9fe7fcb436614d93955148
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
2. **Preflight** — for `terraform`/`gh`/`jq`, report whether each is **pinned and
   matching**, **pinned and drifted**, or **missing its required pin**. Report `curl`
   separately as present or missing; it is intentionally system-provided and has no pin. A
   drifted pin is a real finding: the plan a reviewer reads may not be the plan that gets
   applied. A missing `mise.toml` key or `mise.lock` is a failed toolchain contract — say
   so, and point at [`../infra-copilot/references/decisions.md.example`](../infra-copilot/references/decisions.md.example).
   Report the HCP token pivot: present or not.
   If `terraform/gcp` exists, also report `gcloud` as pinned/matching, drifted, or missing;
   omit it while the optional GCP phase has not been adopted.
3. **Full scan — but only with checks that don't touch the working tree.** Walk **every**
   step in [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml) (all phases, 0–6). Never run a
   step's `run`. Classify each `check` before running it — the read-only guarantee depends
   on this:

   - **Non-mutating checks** (HCP/Cloudflare/GitHub API reads, file existence, tool
     versions — phases 0–3, plus the phase-4 `status-check-context` step) — run them
     directly. These only read. `status-check-context` is two `gh api` reads and a
     comparison in `$TMPDIR`; it touches neither the working tree nor any provider state,
     so run it even though it sits in phase 4.
   - **Mutating checks — do NOT run them.** `plan-cloudflare`, `plan-github`, and the
     phase-5 `migrate-import` check run `terraform init`/`plan`,
     which writes `.terraform/` and can create or update `.terraform.lock.hcl` — that would
     dirty the checkout, and this command promises to change nothing. Instead, read the
     **run status per workspace via the HCP API** (non-mutating — see
     [`../infra-copilot/references/docs/hcp-api.md`](../infra-copilot/references/docs/hcp-api.md)). Resolve the current revision
     first by asking whether the checkout corresponds to a commit at all. `git rev-parse
     HEAD` names the last *commit*, not what is on disk, so uncommitted changes under a
     leaf's directory mean the files you are auditing were never sent to HCP. Test each
     leaf on its own — `git --no-optional-locks status --porcelain -- terraform/cloudflare`,
     and the same for `terraform/github` — and if the output is non-empty, that leaf's plan
     check is `?` (working tree differs from the last tested revision). Stop there for that
     leaf; a green run for HEAD says nothing about edited files. `--no-optional-locks` keeps
     this read from touching git's index, preserving the change-nothing promise.

     For a clean leaf, resolve the revision with `git rev-parse HEAD` and use the guide's
     specific-commit lookup, which correlates on the run's configuration-version ingress
     `commit-sha` — never on the run message — and names every operation so the PR's
     *speculative* plan is visible at all. Judge only the lookup's `latest`, the newest run
     for that revision, and keep failure distinct from ignorance:

     - `"green": true` → `✓`.
     - `latest` in a terminal failure (`errored`, `canceled`, `discarded`,
       `force_canceled`) → `✗`. That is definitive evidence the revision does not plan, so
       the step is **red** and eligible to be the first red step that routes the user to a
       fixing skill. Never soften it to `?`.
     - `latest` still in flight (`planning`, `planned`, `applying`, `plan_queued`, …) → `?`
       (not finished yet).
     - no match at all → `?` (current revision not verified).

     Never let an older green run for the same commit override a newer failing one.
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

   Infer *done* from committed state plus the latest run for the current revision:
   `terraform/cloudflare/generated.tf` exists (committed), **and** that run either carries
   status `applied` — it executed its plan, imports included — or its plan summary reports
   `imports: 0`. Read the summary with the plan-summary helper in
   [`../infra-copilot/references/docs/hcp-api.md`](../infra-copilot/references/docs/hcp-api.md).

   Both halves of that disjunction matter. Applying a run does **not** rewrite its stored
   plan, so an applied import run still lists the imports it just performed; demanding
   `imports: 0` there would report a finished migration as unfinished indefinitely, because
   the normal merge workflow never produces a second no-op run for the same commit. Phase 5
   is **incomplete** only when the latest run has *not* applied and its plan still counts
   imports, or when you cannot read that evidence at all. Only call phase 5 actionable when
   resources demonstrably exist at the provider but aren't in state.

## Report format

Print a phase-by-phase table, then a one-line verdict. Use this shape:

```
infra-copilot status — <repo> (org: $ORG)

Preflight   terraform 1.15.9 ✓ pinned   gh 2.81.0 ✗ pin missing   jq ✓   curl ✓   HCP token ✓
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
| `status-check-context` exit 2 (`CANNOT VERIFY`) | **Nothing to fix in the repo.** Report `?` and name the cause — most often `gh auth login`. Do not route to any skill. |
| `status-check-context` exit 1 (phase 4) | **Nothing — fix it directly**, not via `setup`. For `BLOCKED`, replace only the stale `Terraform Cloud/…` entry in `terraform/github/branch_protection.tf`, keep every other required context, and follow the break-glass sequence ([`../infra-copilot/references/docs/ci.md`](../infra-copilot/references/docs/ci.md#hcp-status-check-context)). For `UNDERPROTECTED`, re-apply `branch_protection.tf` so an HCP context is required again. |
| Other steps in phases 0–4 | **infra-copilot:setup** |
| Phase 5 (migrate-*) | **infra-copilot:import** — only relevant if adopting pre-existing resources |
| Phase 6 (gcp-*) | **infra-copilot:add** — and only after the design decision |
| All green | Nothing — repo is set up. |

`status-check-context` has **three outcomes, and only two of them are verdicts.** Read the
exit code, not just the fact that it was non-zero:

- **exit 2, `CANNOT VERIFY: …`** — `REPO` unset, `gh` not authenticated, or an API read
  failed. This proves *nothing* about branch protection. Report it as `?`, not `✗`, name
  the cause, and do **not** mention `branch_protection.tf` or break-glass. The fix is
  usually `gh auth login`.

Exit 1 is a real verdict, and it has **two modes with opposite operational risk** — read
the message and report the right one first, ahead of any other finding:

- `BLOCKED: required but never published …` — protection requires a status nobody posts,
  so **every PR is blocked** even though the rest of the report reads green. This is the
  stale-context incident; recovery is the break-glass sequence.
- `UNDERPROTECTED: branch protection requires no 'Terraform Cloud/' context …` — the
  opposite. Merges are **not** blocked; they are going through without an HCP plan
  gating them. Do **not** send the user into break-glass — protection is misconfigured or
  was left relaxed after a previous recovery, and `branch_protection.tf` needs re-applying.

Never report one as the other: telling a user PRs are blocked when they are in fact
under-protected inverts the risk. And never report either when the check exited 2 — an
unreadable check is not evidence of a misconfigured repository.

**What this step does not cover.** If `main` has no branch protection at all, the check
passes. That is deliberate: `setup` ends at green speculative plans without applying
`branch_protection.tf`, and HCP is already posting statuses by then, so nothing observable
separates "not applied yet" from "removed". Do not read a green
`status-check-context` as proof that protection exists — only that a required HCP context,
if one is required, is being published. Whether protection is applied at all is a separate
invariant, and no step asserts it today.

Note that a red Phase 5 or 6 is **expected and fine** for most repos — they're optional
(import only matters if resources pre-exist; GCP is a template). Say so rather than
flagging them as failures. The meaningful failure is a red step in phases 0–4.
