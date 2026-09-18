# Pruning spent one-shot blocks

`import { to = … id = "…" }` and `moved { from = … to = … }` are **instructions, not
configuration**. Terraform executes each exactly once; from the next run onward the
resource is managed by its address and the block does nothing. Removing them is a separate
pull request from the one that added them, because the **apply has to land in between**.

This is the only runbook in `infra-copilot` that deletes anything, so most of it is
preconditions.

## Never the same PR as the import

The import PR's blocks are what teaches Terraform that the live resource is the one at that
address. Remove them before the apply and the next plan proposes **creating** resources
that already exist — 139 pending imports become 139 creates against a live project. The
order is fixed:

1. `infra-copilot:import` opens the PR with the blocks. Plan shows *will be imported*.
2. The PR merges, the run **applies**. The resources are now in state.
3. This runbook opens a second PR removing the blocks. Plan shows **`No changes.`**

## What may be removed

| Block | Remove when | Never |
|---|---|---|
| `import {}` | `terraform state list` contains the `to =` address | before the apply |
| `moved {}` | state contains the **new** address **and** not the old one | while either is untrue |

Everything else stays. `resource`, `data`, `module`, `provider`, `variable`, `locals`,
`output` are configuration: deleting a `resource` block proposes a **destroy**, and on
something like `google_project_service` that destroy is an API disable on a live project.
Retiring a real resource is a deliberate, separate act and is not this workflow.

`removed {}` is one-shot in the same way but is **out of scope here**, deliberately: its
precondition is the inverse (the address must be *absent* from state), and getting that
backwards forgets or destroys a live resource. Nothing tracks spent `removed` blocks yet;
leave them, and remove one by hand only with that inverted check in front of you.

## Discover candidates

Per leaf — one leaf at a time, because leaves have separate workspaces and separate
applies:

```sh
cd terraform/<leaf>
grep -rn '^[[:space:]]*import[[:space:]]*{' *.tf
grep -rn '^[[:space:]]*moved[[:space:]]*{'  *.tf
```

cf-terraforming appends its blocks to the file holding the generated HCL. The runbook in
[`import.md`](import.md) pipes one zone into a single `generated.tf`, but an adoption that
runs it per zone or per resource type ends up with several (`generated_dns.tf`,
`generated_prod.tf`, …) — so grep the leaf, don't open one known filename.

## Prove each block is spent

A clean plan is **not** evidence. A speculative plan is equally clean when the imports have
already run and when they are still pending — the difference is only visible in state.

`terraform state list` reads the **backend**, not the provider, so it works in both modes:
in HCP mode the workspace token is enough, and in object-storage mode you need read access
to the state bucket but none of the provider credentials the plan would want. If you
cannot read state at all, **stop** — there is no substitute, and every rule below depends
on it.

```sh
state=$(mktemp) && chmod 600 "$state"    # addresses are not secret; a shared /tmp path is
terraform state list > "$state"          # still someone else's to overwrite

# For each `to = <address>` in an import block, the address must already be there:
grep -Fx 'cloudflare_dns_record.www' "$state"

# For each moved block, the NEW address is present and the OLD one is gone:
grep -Fx '<new address>' "$state" && ! grep -Fx '<old address>' "$state"

rm -f "$state"
```

Any address that is missing means that block is still pending. Leave it, and every other
block in that leaf, alone: finish the import first.

A `to =` that is an expression rather than a literal address —
`cloudflare_dns_record.this[each.key]`, `…[count.index]` — never appears in
`terraform state list` as written. Compare the resource's *instances* instead: every
address `terraform state list` reports for that resource, matched against the keys the
configuration expands to. If you cannot enumerate them confidently, treat the block as
pending. A literal grep that finds nothing is the one case where "missing from state" is
not evidence of anything.

> Addresses with an index (`cloudflare_dns_record.this["www"]`) appear in
> `terraform state list` exactly as written in the block, quotes included. Compare whole
> lines (`grep -Fx`): a substring match on `cloudflare_dns_record.this` reports every key
> in the map as present, so one still-pending record would read as spent.

## Refuse on a dirty plan

Before editing, the leaf must plan cleanly apart from the blocks being removed — imports
pending for the addresses you verified, and nothing else. If the plan carries an unrelated
create, change, or destroy, **stop and report**. Pruning into an unrelated diff makes the
`No changes.` evidence unreadable and buries somebody else's pending change in a chore PR.

## Remove, plan, open the PR

Delete the block and nothing around it — leave the `resource` blocks the imports pointed
at, and leave the file in place even if it ends up holding only HCL.

```sh
terraform fmt
terraform plan   # expect: No changes. Your infrastructure matches the configuration.
```

In object-storage mode, local plans do not authenticate: commit, push, and read the plan
from the workflow run (`gh workflow run terraform-plan.yml --ref "$(git branch --show-current)"`),
same as the import itself.

Open one PR per leaf with a Conventional title — `chore(cloudflare): remove spent import
blocks` — and paste the `No changes.` plan in the body. That is what proves the removed
blocks were inert.

## After

`prune-spent-imports` in [`../steps.yaml`](../steps.yaml) reads green once no
`import {}` or `moved {}` blocks remain committed, so `infra-copilot:status` stops
reporting the leftovers. The plan for the pruned commit is also the repository's first
*positive* evidence that phase 5 finished: a fresh commit whose plan is `No changes.` with
no imports counted.
