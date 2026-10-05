<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:00188bc558fc0c94df44722012b1abaa1a26f3425f86cbc1ff6b584d77d9ba72
Source-Hash: blake3:1dc2bb768d75a6b5f133bcb28897bd2eec92647e797988f199e55974253b44f8
Schema-Version: v1
-->

# infra-copilot: status

A read-only scan of every manifest operation. The router delegates here; selection,
actor rules and resume live in [protocol](protocol.md) and [operations](operations.md).

## Guardrails

Never execute a step's `run`, issue a mutation handoff, initialize Terraform, obtain a
local plan, scaffold config or change tracked files. Read git with
`git --no-optional-locks`. Missing/incomplete config is a finding owned by setup; report
it and stop before exporting variables, preflight, or conditions. Follow config loading's
validation and migration contract without editing its choice.

## Workflow

1. Load validated config per [config](config.md), including the legacy fallback, and
   resolve operation implementations. No missing choice may become an all-skipped scan.
2. Preflight: read provider inventory first. If that HUMAN trust gate is red, report it
   before executing any conditional provider tool. Report declared pins as matching,
   drifted or missing. Report `curl`
   separately as present or missing; it has no pin. No inventory entry means no provider
   tool output. Do not make expected Phase 6 re-trust a Phase 0 failure.
3. Scan every Phase 6 step per declared provider as well as every other applicable
   manifest member, in order. Group by phase, operation and provider entry. Keep member
   IDs for diagnostics, but name the operation in the verdict. A step without an
   `operation` is its own operation. Explicit N/A includes its reason; do not count it
   as proved safety or report the opposite implementation as unfinished.
4. Read checks only when they do not write the working tree. For mutating plan checks,
   use [read-run-status](operations.md#read-run-status) to get current-revision evidence;
   the selected implementation owns run lookup, plan counts and leaf correlation.
   Read-only permission checks, tracked-file checks and inventory checks can run.
   A dirty relevant tree makes remote evidence unknown for that checkout. Null checks
   are human-gated/ephemeral, not commands to execute. Tri-state exit 2 is unknown;
   other nonzero exits are red unless the implementation's evidence contract says pending.
5. Preserve failed, unknown, pending, human-gated and N/A separately. Every operation
   accounts for all applicable members. A readable failure outranks unknown; name it as
   first red even if another member cannot be read. Never substitute an older success.
6. Report latest execution runs separately from completion. A failed apply is a real
   independent finding and appears before the verdict, but does not change first-red.
   Never route an unreadable permission or protection check to a repair skill.

## Phase 6 plan contents and durable completion

A successful plan does not mean a provider has finished adoption. Follow the selected
[get-plan](operations.md#get-plan) and [read-run-status](operations.md#read-run-status)
contracts: compare resource-count evidence and approved apply evidence to committed
inputs. Unexpected destroys are
   zero before accepting completion; a safe first plan may be green with expected creates. Describe deployed resources as
applied only after the approved apply lands. Keep credentials verification and provider completion distinct.

## Phase 5 completion

The migration is incomplete while its imports are pending or its evidence cannot be read.
An approved run with status `applied` proves its adoption instructions ran, even though
its stored plan still counts those imports. Otherwise require `imports: 0`, `creates: 0`
and `destroys: 0` on the current revision for retained import blocks. A no-op count cannot
prove a `moved` block ran: require applied evidence or the deletion's no-op prune plan.
An applied later resource addition does not reopen a completed migration merely because
its stored plan counts creates. Never prune solely because a speculative plan succeeded.

## Validation

Account for every applicable operation/member and every additional provider. Name the
first red operation and member, or state that evidence is unknown. Distinguish a failure
from a check that could not be verified. A skipped leaf plan is never a green plan.

## Example report

```text
infra-copilot status — <repo>
Preflight terraform ✓ pinned   gh ✓ pinned   jq ✓ pinned   curl ✓ present
Phase 0 bootstrap ✓ toolchain-pin  ✓ repo-config-sync  ✓ bootstrap-state
Phase 1 execution ✗ provision-execution (member: selected execution check) ← first red
Phase 2 credentials – store-cloudflare-credential (not reached)
Verdict: execution incomplete — first red operation provision-execution (phase 1).
         Fix with: infra-copilot:setup
```

Legend: `✓` passed · `✗` failed · `–` pending/not reached · `?` unreadable/current revision
not verified · `·` human-gated · `N/A` implementation-specific non-applicability with reason.

## Verdict → which skill

| Finding | Route |
|---|---|
| Unreadable evidence or permission/protection check | Report cause; no repair skill. |
| Failed plan-access or required-check-context | Selected operation's recovery procedure; status never changes permissions or protection. |
| Other operations in phases 0–4 | `infra-copilot:setup` |
| `import-resources` | `infra-copilot:import`, only for requested pre-existing resources. |
| `prune-blocks` | `infra-copilot:prune` after apply; pending adoption goes to import first. |
| Phase 6 operations | `infra-copilot:add`, per declared provider. |
| Latest-run information | Report result and URL independently, no repair skill. |
| All applicable operations green | Nothing to do. |
