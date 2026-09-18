<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:fcc9983181c3c92a66f961d1f61e30c1324724cebeeccd07008b09b29362ceec
Source-Hash: blake3:8db545a50e7636724dbd90b4614161d9f8cb93df5be72af247b1a8fc5a28e56e
Schema-Version: v1
-->

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
| `moved {}` | state holds the **new** address (or its instances/descendants) **and** not the old one | while either is untrue |
| either, under `terraform/modules/` | **every** consuming leaf's state says so | while any consumer is unchecked |

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
grep -rnE '^[[:space:]]*(import|moved)[[:space:]]*\{[[:space:]]*((#|//).*)?$' *.tf
grep -rnE '^[[:space:]]*"(import|moved)"[[:space:]]*:' *.tf.json    # JSON leaves
```

A JSON leaf writes the same thing as `"import": [ { "to": …, "id": … } ]`, so a candidate
there is one array entry to delete, not a block — and deleting the last entry means
removing the key. Every rule below applies unchanged; only the editing differs.

After the `{`, only whitespace or a comment — that is what a block opener looks like.
Without that, a heredoc carrying JavaScript (`import { name } from "./x"` in an inline
Worker script) reads as a pending import. It is a grep, not a parser: a lone `import {`
inside a `/* … */` block comment still matches, so delete dead commented-out blocks rather
than trying to prune them.

cf-terraforming appends its blocks to the file holding the generated HCL. The runbook in
[`import.md`](import.md) pipes one zone into a single `generated.tf`, but an adoption that
runs it per zone or per resource type ends up with several (`generated_dns.tf`,
`generated_prod.tf`, …) — so grep the leaf, don't open one known filename.

## Prove each block is spent

A clean plan is **not** evidence. A speculative plan is equally clean when the imports have
already run and when they are still pending — the difference is only visible in state.

`terraform state list` reads the **backend**, not the provider: in HCP mode the workspace
token is enough, and in object-storage mode you need read access to the state bucket but
none of the provider credentials the plan would want. Avoiding provider auth is not
avoiding backend auth, though. Where the bucket is reachable only from CI — WIF/OIDC
federated to the workflow, no local credential by design — this cannot run on a laptop at
all, and belongs either inside the authenticated plan workflow or with someone who has
bucket read. What you must not do is skip it: if you cannot read state, **stop**. There is
no substitute, and every rule below depends on it.

```sh
terraform init -input=false              # a fresh checkout has no backend configured
state=$(mktemp) && chmod 600 "$state"    # addresses are not secret; a shared /tmp path is
terraform state list > "$state"          # still someone else's to overwrite

# held: this address, or anything under it. `terraform state list` never prints a bare
# aggregate -- a module is `module.m.aws_instance.x`, a count/for_each resource is
# `aws_instance.x[0]` -- so an aggregate `to` has to be matched through its descendants.
# The boundary test (next character `.` or `[`) keeps `module.new` off `module.newer`.
held() {
  awk -v a="$1" '$0 == a || index($0, a ".") == 1 || index($0, a "[") == 1 {f=1}
                 END { exit !f }' "$2"
}

# held_under: the same question for a MODULE-RELATIVE address, which state reports with
# the call path in front: `module.parent.module.child.aws_instance.x`. Matching the tail
# beats parsing that path, which is not splittable on dots -- a key may contain one, as
# in `module.zone["example.com"]`.
held_under() {
  awk -v a=".$1" '{ i = index($0, a)
                    if (i) { r = substr($0, i + length(a))
                             if (r == "" || r ~ /^[.[]/) f = 1 } }
                  END { exit !f }' "$2"
}

rm -f "$state"
```

| Block | Spent when |
|---|---|
| `import` | `held <to>` |
| `moved`, distinct addresses | `held <new>` **and not** `held <old>` |
| `moved` that only adds or removes an index (`x` → `x[0]`) | `held <new>` alone |
| anything written inside a module | `held_under`, in **every** consuming leaf |

The indexing row is not a shortcut. When the move adds `count` or `for_each` to the same
resource, the old address is a *prefix* of the new one, so `held <old>` is satisfied by
`aws_instance.web[0]` — the very instance that proves the move happened. Asking for the old
address to be absent would reject an applied move forever. State cannot hold a bare
aggregate anyway, so the new address being held is the whole of the evidence.

Query a single keyed instance **whole** — `cloudflare_dns_record.this["www"]`, not
`cloudflare_dns_record.this`. The bare name asks the aggregate question, so one applied
record would vouch for every still-pending one.

Any address that is not held means that block is still pending. Leave it, and every other
block in that leaf, alone: finish the import first.

**Chained moves resolve to their last address.** `a → b` followed by `b → c` applies as one
hop: state ends up holding `c`, and `b` never appears. Judged one block at a time the first
looks pending forever and the leaf stays unprunable. When one block's `to` is another's
`from`, follow the chain to its terminal address and validate it as a unit — terminal held,
every earlier address in the chain absent — then remove the chain together or not at all.

**A `to` written as an expression** — `cloudflare_dns_record.this[each.key]`,
`…[count.index]` — is not an address until the configuration expands, so nothing in state
can match it. Compare instances instead: the addresses state reports for that resource,
against the keys the config expands to. If you cannot enumerate them confidently, treat the
block as pending. This is the one case where "not in state" is evidence of nothing.

**Held proves the address is managed**, not that what sits there is the object the block
named. The two diverge only if something *created* a resource at that address instead of
importing it — an apply made outside this workflow, since the import check rejects any plan
containing a create. Where that is plausible, run `terraform state show <address>` and
compare against the block's `id` first; a prune would otherwise certify the duplicate it
exists to prevent.

## A block inside a module belongs to every consumer

A shared module is an input to several workspaces, each with its own state, each applying
the move on its own next run. The new address showing up in the leaf you happen to be in
proves nothing about the others, and deleting the block turns an unmigrated consumer's next
plan into a destroy/create.

Find the consumers by walking the call graph, not by one grep. A leaf can reach the module
*through another module* — it calls `modules/parent`, and `parent` calls `../child` — and
that leaf matches no search for `modules/child`, so it is exactly the consumer you would
skip. Callers can also be JSON.

```sh
# direct callers: leaves AND other modules, both syntaxes
grep -rl 'modules/<name>' terraform/ --include='*.tf' --include='*.tf.json'
# repeat for every caller under terraform/modules/ until each path ends at a leaf

# then, per consuming leaf, against that leaf's own state:
held_under '<new address>' "$state" && ! held_under '<old address>' "$state"
```

`held_under` answers for *any* call of the module, which is what the rule needs: if the
leaf calls the module twice and only one call has migrated, the old address is still there
under the other, the second test fails, and the block correctly stays. If any consumer is
unreadable or unmigrated, or the graph is deeper than you can enumerate confidently, leave
the block. Plan every consuming leaf, not just one, before opening the PR.

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
