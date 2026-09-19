<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:86e009ebeed6c82ed9b237cfd684d38ea4a6b5e81bcf6f616508817bdf81cf95
Source-Hash: blake3:a1b92c11a3a7463ec7aa55fb3c2189f0298e1f9e4ed8f646f0314bc77ecb97e7
Schema-Version: v1
-->

# infra-copilot: status

A **read-only** pass over the whole `infra-copilot` manifest. It runs the same resume scan
the action skills use, but stops there: it reports state and **never provisions, pastes,
or applies anything.** Use it to answer "where are we?" before picking a next action.

The status router delegates here. The shared machinery — actor model, resume scan,
preflight — is in
[`protocol.md`](protocol.md); the manifest it scans is
[`steps.yaml`](steps.yaml).

## Guardrails

**This command changes nothing.** Everything below follows from that:

- Never run a step's `run` — only its `check`, and only checks that do not touch the
  working tree. The phase-4 plan checks and the phase-5 `migrate-import` check run
  `terraform init`/`plan`, which writes `.terraform/` and can update
  `.terraform.lock.hcl`; read run status via the HCP API instead.
- Never emit the handoff block. Nothing is being unblocked here, so a `HUMAN` step's
  `check` is classified like any other and its handoff is not printed.
- Never scaffold or edit config. A missing or incomplete `.infra-copilot/config.md` is
  reported and the scan stops; offering to create it belongs to `setup`.
- Read git with `git --no-optional-locks`, which leaves git's index untouched.
- A red step is a finding, not a licence to fix it. Report which skill owns it.

## Workflow

1. **Read config** (shared protocol, Step 0). Load `.infra-copilot/config.md`, falling
   back to `.claude/infra-copilot.local.md` for migration, and export the org vars
   ([`config.md`](config.md)). If both are missing, or the loaded
   config is incomplete, report it and stop; do **not** offer to scaffold or edit (that
   belongs to `setup`).
2. **Preflight** — first load the provider inventory. If a provider toolchain trust gate
   is pending, evaluate and report that Phase 6 gate before running the full mise check;
   do not misroute its expected HUMAN re-trust handoff as a generic phase-0 failure.
   Once those gates are green, for `terraform`/`gh`/`jq`, report whether each is **pinned and
   matching**, **pinned and drifted**, or **missing its required pin**. Report `curl`
   separately as present or missing; it is intentionally system-provided and has no pin. A
   drifted pin is a real finding: the plan a reviewer reads may not be the plan that gets
   applied. A missing `mise.toml` key or `mise.lock` is a failed toolchain contract and a
   red phase-0 `toolchain-pin` step — say so, and point at
   [`docs/setup.md#6`](docs/setup.md#6-local-development) and
   [`decisions.md.example`](decisions.md.example).
   Report the HCP token pivot: present or not.
   For each additional provider, run `new-provider-toolchain` first without activating
   any conditional provider preflight. If that HUMAN trust gate is red, report the gate
   and do not inspect or execute its provider CLIs. Only after it is green, export that
   entry's `NEW_PROVIDER_MISE_TOOLS` and report each declared tool as pinned and installed,
   drifted, or missing. Omit provider-tool output when that list is empty. GCP declares
   `gcloud`, but this reporting is provider-neutral.
3. **Full scan — but only with checks that don't touch the working tree.** Walk **every**
   step in [`steps.yaml`](steps.yaml) (all phases, 0–6). Never run a
   step's `run`. Classify each `check` before running it — the read-only guarantee depends
   on this:

   - **Non-mutating checks** (API reads, file existence, tool versions — phases 0–3;
     phase 4's `status-check-context` and `hcp-apply-scope`; phase 5's
     `prune-spent-imports`, which reads `HEAD` with `git ls-tree` and `git show`, then
     scans `.tf` with `awk` and `.tf.json` with `jq` (tri-state: exit 2 means it could not
     verify — git unreadable, `jq` missing, no temp file, or a `.tf.json` that does not
     parse — report `?`); and every Phase 6 step, including the read-only `new-provider-plan`
     evidence check) — run them directly.
     `status-check-context` is two `gh api` reads and a comparison in `$TMPDIR`;
     `hcp-apply-scope` lists workspaces and reads the permissions HCP reports for the
     current credential, and deliberately never posts an apply. Neither touches the
     working tree or any provider state. Reporting setup healthy without evaluating
     `hcp-apply-scope`, or an adoption healthy without evaluating its workspace and
     credential metadata, would hide the state these checks exist to recover.
   - **Mutating checks — do NOT run them.** In HCP mode, `plan-cloudflare`, `plan-github`,
     and the phase-5 `migrate-import` check run `terraform init`/`plan`,
     which writes `.terraform/` and can create or update `.terraform.lock.hcl` — that would
     dirty the checkout, and this command promises to change nothing. Instead, read the
     **run status per workspace via the HCP API** (non-mutating — see
     [`docs/hcp-api.md`](docs/hcp-api.md)).

     **Exception for object-storage mode:** The plan checks (`plan-cloudflare-gha`,
     `plan-github-gha`) and `migrate-import` check perform only GitHub API reads and
     log inspection — no local `terraform` commands. These checks ARE safe to run during
     status in object-storage mode. Resolve the current revision
     first by asking whether the checkout corresponds to a commit at all. `git rev-parse
     HEAD` names the last *commit*, not what is on disk, so uncommitted changes under a
     leaf's directory mean the files you are auditing were never sent to HCP. Test each
     leaf together with shared inputs — `git --no-optional-locks status --porcelain --
     terraform/cloudflare terraform/modules .infra-copilot/config.md mise.toml`, and the same leaf
     substitution for `terraform/github` or `terraform/$NEW_PROVIDER` — and if the output is non-empty, that leaf's plan
     check is `?` (working tree differs from the last tested revision). Stop there for that
     leaf; a green run for HEAD says nothing about edited files. `--no-optional-locks` keeps
     this read from touching git's index, preserving the change-nothing promise.

     For a clean leaf, find the newest commit whose relevant trees match — `git log
     --format=%H -1 -- terraform/<leaf> terraform/modules .infra-copilot/config.md
     mise.toml`. Path-filtered workspaces correctly create no run for unrelated later
     commits, so correlating on exact `HEAD` would report `?` whenever HEAD contains
     only an unrelated change after the last Terraform update. Use the guide's
     specific-commit lookup with that relevant commit, which correlates on the run's
     configuration-version ingress `commit-sha` — never on the run message — and names
     every operation so the PR's *speculative* plan is visible at all. Judge only the
     lookup's `latest`, the newest run for that revision, and keep failure distinct
     from ignorance:

     - `"green": true` AND `latest.operation` is not `destroy` → `✓`, subject to the
       Phase 5 and Phase 6 content checks below. A `destroy` operation that reaches
       `applied` is green by status but destructive by intent — report it as `✗`.
     - `latest` in a terminal failure (`errored`, `canceled`, `discarded`,
       `force_canceled`, `pre_plan_errored`, `cost_estimation_errored`,
       `policy_errored`, `post_plan_errored`, `policy_hard_failed`) → `✗`. That is
       definitive evidence the revision does not plan, so the step is **red** and
       eligible to be the first red step that routes the user to a fixing skill.
       Never soften it to `?`.
     - `latest` still in flight (`planning`, `planned`, `applying`, `plan_queued`, …) → `?`
       (not finished yet).
     - no match at all → `?` (current revision not verified).

     Never let an older green run for the same commit override a newer failing one.
   - **Null checks** (`check: ~`, e.g. `migrate-discovery-token`) — nothing scriptable to
     run. Report them as `·` (human-gated / ephemeral), never attempt to execute the null.
   - For `HUMAN` steps, apply the same classification to their `check`; never emit the
     handoff block — nothing is being unblocked here.

   **Phase 6 plan contents and durable completion.** For `new-provider-plan`, a terminal
   green HCP run is necessary but not sufficient. Its manifest helper correlates on the
   newest commit whose provider leaf, shared `terraform/modules`, and
   `.infra-copilot/config.md` trees match, because
   the path-filtered workspace correctly has no run for unrelated later commits. Read its
   structured plan summary using the helper in
   [`docs/hcp-api.md`](docs/hcp-api.md)
   and read the workspace's `resource-count`. Mark the step `✓` only when destroys are
   zero and either the plan creates at least one resource (the safe first plan) or the
   workspace already has a positive resource count (the adoption was applied and the
   current safe plan is now no-op or update-only). A no-create plan with zero resources,
   or any plan containing a destroy, is `✗`. This content predicate applies to both
   `planned_and_finished` and `applied` runs; never substitute the generic `green` flag.

   **Completion vs. not-started (phase 5).** The `migrate-import` check accepts a plan with
   pending imports **or** a no-op plan — the post-apply, post-prune state is the correct
   terminal one, and an earlier version of this check demanded `will be imported` and so
   read red exactly once the migration was finished. Green there therefore does not say
   *which* of the two it is. Do not read that into a clean run either: a speculative
   `planned_and_finished` run is "clean" *and* can still carry `will be imported`, which
   means the imports are pending, not finished. A successful plan is evidence the config is
   valid, never evidence that it was applied.

   `prune-spent-imports` is the separate, cheap signal: red while `import {}` / `moved {}`
   blocks are still committed anywhere under `terraform/`. It cannot tell a pending block
   from a spent one either — that needs state membership, which needs an init — so read it
   together with the run evidence below: spent blocks after an applied run route to
   `infra-copilot:prune`, the same blocks before one mean the import is unfinished.

   **That discriminator is backend-specific, and the run evidence below is HCP's.** In
   object-storage mode there is no HCP run to read `status: applied` from — but there is no
   need to reconstruct one in prose either, because `migrate-import` is safe to run during
   status in this mode (above) and its object-storage branch already does the whole
   correlation: it reads the `plan-cloudflare` job log, and on a no-op plan it requires a
   successful **`apply-cloudflare` job** — the leaf's own job, not merely a green run — in a
   run this revision descends from. Run it, then read its outcome:

   | check | plan log | phase 5 |
   |---|---|---|
   | exit 0 | contains `will be imported` | **pending** — route to `infra-copilot:import` |
   | exit 0 | no-op | **applied** — the apply job was verified to get here; route to `prune` |
   | exit 1 | no-op | the apply has not landed — finish the import |
   | exit 2 | — | `?`, route nowhere |

   **That check is Cloudflare's.** It reads `plan-cloudflare` and `apply-cloudflare`, so it
   discriminates only that leaf. `plan-github-gha` checks job success and nothing more, and
   an additional-provider leaf has no equivalent at all — so in object-storage mode a red
   `prune-spent-imports` whose blocks live in `terraform/github` or a provider leaf is
   **ambiguous, and stays that way**: report phase 5 as `?` for that leaf, name the blocks,
   and route nowhere. Do not fall through to `prune` — the same red means *pending* before
   the apply, and pruning a pending import is the one outcome this phase exists to prevent.
   The human can settle it by reading that leaf's plan log; status cannot.

   Do not re-derive that correlation here. An earlier version of this section did, and got
   it wrong twice in one paragraph: it asked only whether the *run* was green, which a
   GitHub-only run satisfies because `apply-cloudflare` is conditionally skipped; and it
   correlated against `target_sha`, which the check's own comment rules out in as many
   words — on a prune branch `target_sha` **is** the prune commit, so nothing can have
   applied it before the merge, and every valid prune PR would read as an unfinished
   import. The check tests `apply_sha` against `HEAD` instead, and is safe doing so because
   the pending and premature-prune plans (`will be imported`, `will be created`) are both
   rejected before that point. Two copies of this rule is one too many.

   **Route by the leaf the blocks are in.** `migrate-import` is Cloudflare-specific — it
   plans `terraform/cloudflare` and wants that leaf's generated HCL — while
   `prune-spent-imports` is provider-neutral and scans every leaf. A repo whose only
   adoption was in `terraform/github` or an additional-provider leaf therefore has a red
   `migrate-import` that means *not applicable*, not *unfinished*: report it as such and
   do not send the user to the Cloudflare import flow because a GitHub `moved` block is
   waiting to be pruned. Judge each leaf's evidence from that leaf.

   Infer *done* from committed state plus the latest run for the current revision, **read
   against the leaf holding the blocks, not against Cloudflare**. The committed evidence is
   that leaf's adoption HCL: for `terraform/cloudflare` it is `generated*.tf` — cf-terraforming
   output is split by zone and resource type, so match the glob rather than a single
   `generated.tf` — and for a GitHub or additional-provider leaf it is whatever that
   adoption wrote, since nothing generates a fixed filename there. The run is that leaf's
   own workspace run. Requiring Cloudflare's generator output would report a correctly
   applied HCP GitHub import as unfinished, which is the same leaf-blindness the routing
   rule above exists to prevent. Then that run either carries status `applied` — it executed its
   plan, imports included — or its plan summary reports `imports: 0` **with `creates: 0`
   and `destroys: 0`**. Read the summary with the plan-summary helper in
   [`docs/hcp-api.md`](docs/hcp-api.md).

   **Those counts see imports, not moves.** A pending `moved {}` plans as zero added, zero
   changed, zero destroyed — the rename is a state operation, not a resource change — so a
   revision carrying an unapplied move satisfies `imports: 0`, `creates: 0` and
   `destroys: 0` exactly as a finished adoption does. The counts half is therefore evidence
   only when the committed leftovers are `import` blocks. When `prune-spent-imports` names
   a file holding `moved {}`, use the `applied` half or report `?`; never read a clean
   speculative plan as proof a move has landed. The runbook's before-plan does catch it —
   a pending move prints its rename — but that plan is the prune workflow's, not status's.

   The creates clause is not decoration: a prune done *before* its import applied produces
   exactly `imports: 0` with creates — Terraform no longer knows the live resources are
   the ones at those addresses, so it offers to make them again. Reading that as
   completion reports the one outcome this whole phase exists to prevent, moments before
   CI duplicates live infrastructure. The generic "green run" flag does not look at
   counts; this predicate must.

   Both halves of that disjunction matter. Applying a run does **not** rewrite its stored
   plan, so an applied import run still lists the imports it just performed; demanding
   `imports: 0` there would report a finished migration as unfinished indefinitely, because
   the normal merge workflow never produces a second no-op run for the same commit — until
   the prune PR does, which is why the `imports: 0` half exists at all and why it is the
   stronger evidence once `prune-spent-imports` is green.

   The `applied` half is **deliberately count-blind**, unlike the phase-6 predicate above,
   and the asymmetry is the point. It correlates on the latest run for the *current*
   revision, so once phase 5 is genuinely finished every later Cloudflare change is that
   run: a phase-6 revision that adds one record applies with `creates: 1`. Requiring zero
   creates here would fail that run on both halves and report phase 5 unfinished forever
   after, routing the user to the import flow for work that finished weeks earlier. The
   case it would buy — a prune merged before its import applied, so the apply created
   duplicates and still reported `applied` — is caught where it can still be prevented
   rather than diagnosed: the `migrate-import` check plans the leaf and exits red on
   `will be created`, and the runbook refuses to remove a block whose address is absent
   from state. Once such a run has applied, no count read here undoes it. Prefer the
   signal that fires before the apply. Phase 5
   is **incomplete** only when the latest run has *not* applied and its plan still counts
   imports, or when you cannot read that evidence at all. Only call phase 5 actionable when
   resources demonstrably exist at the provider but aren't in state, or when spent blocks
   are still committed.

## Validation

A complete report accounts for **every** step in the manifest — none silently omitted —
carries a one-line verdict naming the first red step, and states which skill owns it.
Distinguish the four outcomes rather than collapsing them: passed, failed, not evaluated,
and *could not be verified*. Reporting an unreadable check as a failure is as wrong as
reporting a failure as green.

## Example report

Print a phase-by-phase table, then a one-line verdict. Use this shape:

```text
infra-copilot status — <repo> (org: $ORG)

Preflight   terraform 1.15.9 ✓ pinned   gh 2.81.0 ✗ pin missing   jq ✓   curl ✓   HCP token ✓
Phase 0  bootstrap        ✓ toolchain-pin  ✓ repo-config-sync  ✓ hcp-login  ✓ hcp-signup  ✓ hcp-verify
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
| `vcs-connect` exit 2 (`CANNOT VERIFY`) | **Nothing to fix in the repo.** The check is tri-state: after the plan-only handoff the credential cannot read `/organizations/<org>/oauth-clients`, which is organization-scoped, so it falls back to looking for a workspace connected to `$REPO`. A 2 means neither signal was readable. Report `?` and name the cause; do not route to `setup`, and **do not** widen the team's organization access to turn it green — that would undo `hcp-apply-scope`. |
| `hcp-apply-scope` exit 2 (`CANNOT VERIFY`) | **Nothing to fix in the repo.** Report `?` and name the cause — a missing credential, an unreadable API response, or a managed `terraform/<leaf>/` with no visible workspace. Do not route to any skill; a transient read failure is not setup work. |
| `hcp-apply-scope` exit 1 (phase 4) | **Nothing — this is credential work, not `setup`.** For `UNPROTECTED`, the agent's credential can apply: provision the plan-only identity in that step's `run`. For `OVER-RESTRICTED`, grant the team the workspace `Plan` permission. For `SPLIT-BRAIN`, re-export `HCP_TOKEN` from the source `terraform` uses. Running `setup` fixes none of these. |
| `status-check-context` exit 1 (phase 4) | **Nothing — fix it directly**, not via `setup`. For `BLOCKED`, replace only the stale `Terraform Cloud/…` entry in `terraform/github/branch_protection.tf`, keep every other required context, and follow the break-glass sequence ([`docs/ci.md`](docs/ci.md#hcp-status-check-context)). For `UNDERPROTECTED`, re-apply `branch_protection.tf` so an HCP context is required again. |
| Other steps in phases 0–4 | **infra-copilot:setup** |
| Phase 5 (migrate-*) | **infra-copilot:import** — only relevant if adopting pre-existing resources |
| `prune-spent-imports` exit 2 (`CANNOT VERIFY`) | **Nothing to fix in the repo.** The check could not read git — not a repository, or unreadable metadata. Report `?` and name the cause; an unreadable check is not evidence that blocks remain, so do not route to `prune`. |
| `prune-spent-imports` (phase 5) | **infra-copilot:prune** — if the import already applied. If it has not, the blocks are pending, not spent: finish `infra-copilot:import` first. Route on the leaf holding the blocks, not on Cloudflare's `migrate-import`. |
| Phase 6 (`new-provider-*`) | **infra-copilot:add** — and only after the design decision |
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

Note that Phase 5 or 6 being **not applicable** is expected for most repos — import only
matters if resources pre-exist, and `additional_providers` is normally empty. Once a
provider entry or an extra Terraform leaf exists, however, a red Phase 6 step is an
interrupted adoption and is actionable; do not dismiss it as optional. The meaningful
bootstrap failure remains a red step in phases 0–4.
