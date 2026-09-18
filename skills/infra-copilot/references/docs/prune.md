<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:6ef02e34c5d4005e684c6e7072480125a9b10177a300a5134fb7762bb9188f74
Source-Hash: blake3:85ed16473b38f11a302d67301a847ea11fed63fa048bd05f5ad785344d74267f
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
none of the provider credentials the plan would want.

Avoiding provider auth is not avoiding backend auth, though. Where the bucket is reachable
only from CI — WIF/OIDC federated to the workflow, no local credential by design — this
check cannot run on a laptop at all. Then either a human with bucket read runs it and
pastes the output, or it runs inside the authenticated plan workflow. What you must not do
is skip it: if you cannot read state, **stop**. There is no substitute, and every rule
below depends on it.

```sh
terraform init -input=false              # a fresh checkout has no backend configured,
                                         # and `state list` fails without one
state=$(mktemp) && chmod 600 "$state"    # addresses are not secret; a shared /tmp path is
terraform state list > "$state"          # still someone else's to overwrite

# `held` exits 0 when state contains this address or anything under it. index($0,…)==1
# anchors at the start of the line, so `module.new` never matches `module.newer`.
held() {
  awk -v a="$1" '$0 == a || index($0, a ".") == 1 || index($0, a "[") == 1 {f=1}
                 END { exit !f }' "$2"
}

# import: the `to =` address must already be held.
held 'cloudflare_dns_record.www' "$state"

# moved: the NEW address is held and the OLD one is not.
held '<new address>' "$state" && ! held '<old address>' "$state"

rm -f "$state"
```

The three shapes matter because **an aggregate `to` never appears verbatim**.
`terraform state list` prints `module.new.aws_instance.x`, never bare `module.new`; it
prints `aws_instance.x[0]` and `…["a"]`, never bare `aws_instance.x` for a resource with
`count` or `for_each`. A whole-line comparison against those `to` addresses fails forever,
so an applied move reads as pending and the leaf can never be pruned.

Two things follow. The prefix must be **anchored** — that is what `index(…) == 1` buys:
unanchored, `module.new` matches `module.newer` and a different module's state entry
proves your move. And when the `to` names one keyed instance, query it **whole**,
`cloudflare_dns_record.this["www"]` and not `cloudflare_dns_record.this`: the bare name
answers "does any key exist", which is the aggregate question, so a single applied record
would vouch for every still-pending one.

Any address that is not held means that block is still pending. Leave it, and every other
block in that leaf, alone: finish the import first.

**Chained moves resolve to their last address.** `a → b` followed by `b → c` applies as
one hop: state ends up holding `c`, and `b` never appears. Judged one block at a time the
first looks pending forever, and the whole leaf stays unprunable. When one block's `to` is
another's `from`, follow the chain to its terminal address and validate it as a unit —
the terminal address held, every earlier address in the chain absent — then remove the
chain together or not at all.

Held proves the **address** is managed, not that what sits there is the object the block
named. They diverge only if something created a resource at that address instead of
importing it — an apply made outside this workflow, since the import check rejects any
plan containing a create. If you have reason to suspect that, run
`terraform state show <address>` and compare it against the block's `id` before removing
anything; a prune would otherwise certify the duplicate it exists to prevent.

**A block under `terraform/modules/` is not one leaf's to prune.** A shared module is an
input to several workspaces, each with its own state, and each applies the move on its own
next run. The new address showing up in the leaf you happen to be in proves nothing about
the others — and deleting the block turns an unmigrated consumer's next plan into a
destroy/create. Enumerate the consumers and check each one's state before touching it:

Their addresses also need qualifying. A block inside a module is written relative to that
module — `aws_instance.new` — while a consumer's state reports the absolute
`module.<call>.aws_instance.new`. Comparing the bare address holds nothing forever, and
worse, a same-named resource in the consumer's *root* module would satisfy it and vouch
for a move that never happened. Prefix each module call:

A leaf can also reach the module *through another module* — it calls `modules/parent`,
and `parent` calls `../child`. A grep for `modules/child` finds no leaf at all, and the
consumer you would then skip is a real one. So walk the graph, don't grep once: find the
direct callers, and for each caller that is itself under `terraform/modules/`, find *its*
callers, until every path ends at a leaf. If the graph is deeper than you can enumerate
confidently, leave the block — an unfound consumer is the destroy/create above.

```sh
grep -rl 'modules/<name>' terraform/ --include='*.tf'     # direct callers: leaves AND modules
# repeat for each caller under terraform/modules/, until only leaves remain

# per leaf, the call addresses. A module may be called more than once; for_each/count
# calls appear as module.<call>["a"]; and a transitively consumed module is nested, so
# the whole leading run of `module.<name>` pairs is the prefix -- never just the first.
terraform state list | awk -F. '{ p=""
  for (i = 1; i <= NF; i++) {
    if ($i == "module") { p = p (p == "" ? "" : ".") $i "." $(i+1); i++ } else break
  }
  if (p != "") print p }' | sort -u
# module.solo
# module.foo["a"]
# module.parent.module.child      <- nested: `module.parent` alone is a different address

# then, per call, the same two rules with the call prefixed:
held "module.<call>.<new address>" "$state" && ! held "module.<call>.<old address>" "$state"
```

Every call has to pass, not just the first one found — a leaf that calls the module twice
applies the move twice. If any call, consumer, or state is unmigrated or unreadable, leave
the block. Plan every consuming leaf, not just one, before opening the PR.

One case `held` cannot settle: a `to =` written as an *expression* —
`cloudflare_dns_record.this[each.key]`, `…[count.index]`. It is not an address at all
until the configuration expands, so nothing in state can match it. Compare instances
instead: the addresses state reports for that resource, against the keys the config
expands to. If you cannot enumerate them confidently, treat the block as pending — this
is the one case where "not in state" is evidence of nothing.

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
