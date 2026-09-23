<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:4cdef5e769cc38f277cbf713c53e3d82295b0425cc29476ee2674cb9993bf785
Source-Hash: blake3:57bfce8e636b9fb929456710e44c56405ba8795d5b77fe8558b69e47c1a5549c
Schema-Version: v1
-->

# Pruning spent one-shot blocks

`import { to = … id = "…" }` and `moved { from = … to = … }` are **instructions, not
configuration**. Terraform executes each against a given state exactly once; from that
state's next run onward the resource is managed by its address and the block does nothing.
Removing them is a separate pull request from the one that added them, because the
**apply has to land in between**.

*Exactly once* is a claim about **one state**, which is why this runbook stops at the leaf.
A block under `terraform/modules/` is read by every consuming state separately, and the set
of those states is not closed — a workspace restored from an older state, or a consumer
outside this repository, has still to cross it. **Neither kind is pruned here:**

- A module's `moved` block is its **upgrade path**, not a leftover. Terraform's own guidance
  is to [retain historical module
  moves](https://developer.hashicorp.com/terraform/language/modules/develop/refactoring#removing-moved-blocks):
  "Removing a `moved` block is a breaking change […] We strongly recommend that you retain
  all historical `moved` blocks from earlier versions of your modules."
- A module's `import` block *is* spent once applied — but per consumer, and deleting it
  while one consumer is behind makes that consumer's next plan **create** a resource that
  already exists. Proving the set complete means resolving every `source`, including
  relative ones like `../child`, through the whole call graph; a grep for one spelling
  quietly misses exactly the consumer you needed.

`prune-spent-imports` excludes `terraform/modules/` for the same reason, so a retained
module block does not hold phase 5 red. Removing one is a deliberate human change against a
known consumer list — not this runbook's, and not on a schedule.

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
| `import {}` in a leaf | `terraform state list` contains the `to =` address | before the apply |
| `moved {}` in a leaf | state holds the **new** address (or its instances/descendants) **and** not the old one | while either is untrue |
| either, under `terraform/modules/` | — | **always**: see below |

The `state list` column is how the first two are *filtered* in HCP mode. In object-storage
mode that command cannot authenticate, so the plan pair carries them alone — see
[State membership filters first](#state-membership-filters-first--where-it-can-run-at-all).

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
grep -rnE '^[[:space:]]*(import|moved)[[:space:]]*(\{|/\*)' *.tf
grep -rnE '^ {0,2}"(import|moved)"[[:space:]]*:' *.tf.json          # JSON leaves
```

A JSON leaf writes the same thing as `"import": [ { "to": …, "id": … } ]`, so a candidate
there is one array entry to delete, not a block — and deleting the last entry means
removing the key. Every rule below applies unchanged; only the editing differs. Only a
**top-level** key counts: an ordinary nested one named `import` — inside `locals`, say — is
configuration. `jq -e 'has("import") or has("moved")'` answers that exactly, and the
indent-matched grep above does not; use it on any JSON leaf you are unsure about.

The opener is matched up to `{` **or** `/*`, because a comment may stand in for whitespace
in a header — `import /* imported in #123 */ {` is a block, and `prune-spent-imports`
counts it, so a discovery that required `{` to end the line would report the file as red
with nothing to find.

**These two commands find lines, not blocks — read each hit before treating it as a
candidate.** A grep cannot see what a line is inside, and three shapes match without being
one-shot blocks: a `/* … */` block comment around dead HCL, a heredoc carrying JavaScript
(`import {` on its own line above `handler,` in an inline Worker script), and a `.tf.json`
key nested below the top level. Leave script content alone; a commented-out block is dead
code, so delete the comment rather than pruning what is inside it.

`prune-spent-imports` in [`../steps.yaml`](../steps.yaml) discriminates all three — it is
string-aware, so it skips heredoc bodies, both comment forms, and anything inside a quoted
value, and it reads JSON with `jq`. **A hit these greps report but that check does not is
not a candidate**: check the leaf against it before editing, rather than trusting the grep.

cf-terraforming appends its blocks to the file holding the generated HCL. The runbook in
[`import.md`](import.md) pipes one zone into a single `generated.tf`, but an adoption that
runs it per zone or per resource type ends up with several (`generated_dns.tf`,
`generated_prod.tf`, …) — so grep the leaf, don't open one known filename.

## Prove each block is spent

Two questions, and they need different instruments:

1. **Has this block already run?** Terraform answers it, in a plan.
2. **Is this block one I may touch at all?** State membership answers it, cheaply,
   before you spend a plan on a leaf full of pending work.

### The plan pair decides

A block that has **not** run still appears in the plan: a pending `import` prints
`will be imported`, a pending `moved` prints its rename. A block that **has** run
contributes nothing. So bracket the edit with two plans, in this order:

```sh
terraform plan          # 1. before: no `will be imported`, no pending move, nothing
                        #    else outstanding -- otherwise stop, the work is unfinished
# remove the candidate blocks, and nothing else
terraform plan          # 2. after:  No changes. Your infrastructure matches the
                        #    configuration.  <- the blocks were inert
```

Anything other than `No changes.` in the second plan means at least one block was still
doing work: **restore it** and leave the leaf alone. This is the authority for every shape
the address rules below cannot settle, because Terraform parses its own addresses —
aggregate module targets, `count`/`for_each` in either direction, chains, expressions,
JSON leaves. When the two disagree, the plan is right.

### State membership filters first — where it can run at all

**In object-storage mode, skip this section.** The bucket credential lives in GitHub
Actions (WIF/OIDC), not on the machine running the runbook, so `terraform init` cannot
configure the backend and `terraform state list` cannot read it — the same reason local
plans do not authenticate. Avoiding *provider* credentials never avoided *backend* ones.

That costs nothing, because this section was never the evidence: it is a pre-filter in
front of the plan pair, and the plan pair is what decides. So in object-storage mode the
plan pair **is** the whole procedure, read from the workflow rather than the terminal:

1. Remove the candidate blocks on a branch, push, and read that run's plan — the *after*
   plan. `No changes.` means they were inert; anything else means restore them.
2. That single plan carries both halves here. A block that had not applied leaves its
   resource in the config and out of state, so removing it plans a **create**; an
   unapplied move plans its rename; and an unrelated pending change is not `No changes.`
   either. `No changes.` excludes all three at once.

The before-plan is a convenience in HCP mode — fail fast, before editing — not a separate
safety property, and here it is **not obtainable**: `terraform-plan.yml` gates each leaf's
job on `dorny/paths-filter`, so a dispatch on a branch with no Terraform delta from its
base skips the very job you wanted. The deletion is what creates the delta. Do not read a
skipped job as a clean before-plan.

Both plans authenticate because the workflow holds the credential. The address table below
is skipped, not failed — treat every block as undecided and let the two plans settle it,
which is what the table's own escape clause says to do anyway.

In HCP mode the filter runs locally as written:

```sh
terraform init -input=false              # a fresh checkout has no backend configured
state=$(mktemp) && chmod 600 "$state"    # addresses are not secret; a shared /tmp path is
terraform state list > "$state"          # still someone else's to overwrite

# held: this address, or anything under it. `terraform state list` never prints a bare
# aggregate -- a module is `module.m.aws_instance.x`, a count/for_each resource is
# `aws_instance.x[0]` -- so an aggregate address has to be matched through descendants.
# The boundary test (next character `.` or `[`) keeps `module.new` off `module.newer`.
held() {
  awk -v a="$1" '$0 == a || index($0, a ".") == 1 || index($0, a "[") == 1 {f=1}
                 END { exit !f }' "$2"
}

# exactly: this address and nothing under it.
exactly() { grep -Fxq "$1" "$2"; }
```

Keep `$state` until every check below has run — the helpers read it each time — and
`rm -f "$state"` at the end, after the plan.

| Block | Looks spent when |
|---|---|
| `import` | `held <to>` |
| `moved`, distinct addresses | `held <new>` **and not** `held <old>` |
| `moved` **adding** an index (`x` → `x[0]`) | `held <new>` alone |
| `moved` **removing** a resource index (`x[0]` → `x`) | `exactly <new>` **and not** `exactly <old>` |

The two index rows are not one rule. **Adding** an index makes the old address a prefix of
the new, so `held <old>` is satisfied by `aws_instance.web[0]` — the very instance that
proves the move happened; asking for the old address to be absent would reject an applied
move forever. **Removing** one inverts that: before the apply, state still holds
`aws_instance.web[0]`, and `held aws_instance.web` says *true* on the strength of the
instance the move is supposed to rename, so both sides must be exact there.

Query a single keyed instance **whole** — `cloudflare_dns_record.this["www"]`, not
`cloudflare_dns_record.this`. The bare name asks the aggregate question, so one applied
record would vouch for every still-pending one.

**Where the table runs out, stop reading it and plan.** Each of these looks spent, or looks
pending, for reasons that have nothing to do with whether it ran:

- **An index removed from a *module* call** (`module.app[0]` → `module.app`). State never
  prints a bare `module.app`, only its descendants, so `exactly` can never succeed.
- **Chained moves.** `a → b` then `b → c` applies as one hop: state holds only `c`, and `b`
  never appears, so the first block looks pending forever.
- **An expression target** — `this[each.key]`, `…[count.index]` — is not an address until
  the configuration expands, so nothing in state can match it.

In all four, the plan pair is the decision and the table is noise. Treat a block the table
cannot settle as pending until a plan says otherwise; never the reverse.

**Held proves the address is managed**, not that what sits there is the object the block
named. The two diverge only if something *created* a resource at that address instead of
importing it — an apply made outside this workflow, since the import check rejects any plan
containing a create. Where that is plausible, run `terraform state show '<address>'` and
compare against the block's `id` first — single-quoted, because a keyed address carries its
own quotes and brackets (`cloudflare_dns_record.this["www"]`) that the shell would otherwise
eat or glob; a prune would otherwise certify the duplicate it
exists to prevent.

## Refuse on a dirty plan

That first plan has a second job: the leaf must be otherwise quiet. If it carries an
unrelated create, change, or destroy, **stop and report**. Pruning into an unrelated diff
makes the `No changes.` evidence unreadable and buries somebody else's pending change in a
chore PR.

## Remove, plan, open the PR

Delete the block and nothing around it — leave the `resource` blocks the imports pointed
at, and leave the file in place even if it ends up holding only HCL.

```sh
terraform fmt
terraform plan   # expect: No changes. Your infrastructure matches the configuration.
rm -f "$state"   # the snapshot has done its job
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
