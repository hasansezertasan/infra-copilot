---
name: prune
description: "Remove spent one-shot `import {}` and `moved {}` blocks after their apply landed, proving per block that state already holds the address and ending on a plan of No changes. Use once an import applied, never before."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:34f492108e3f9b3b144a5ae001842a2f9c64102ba0c95fb7ac571bed7d7252de
Source-Hash: blake3:1c623a6b4e8ec5329f0a004c93e23de7a30a7048d6e01b869f5819abb12c9c4b
Schema-Version: v1
-->

# infra-copilot: prune

Delete the **one-shot instruction blocks** an adoption leaves behind. `import {}` and
`moved {}` execute once **against a given state**; after that run applies, the resources are
managed by their addresses and the blocks are inert. Nothing else removes them, so they
accumulate. Scope is one leaf at a time — blocks under `terraform/modules/` are out, see
guardrail 5.

This file is a **router**: the reusable machinery — actor model, handoff, resume,
preflight — lives in [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md); the manifest in
[`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml) (**phase 5**, `prune-spent-imports`); the
canonical runbook in [`../infra-copilot/references/docs/prune.md`](../infra-copilot/references/docs/prune.md).

> **Why not the last step of `import`?** The apply has to land between the two, so they can
> never be the same pull request. `import` ends on *imports, not creates*; this ends on *No
> changes*. Two end states, days apart, usually two different sessions.

## Guardrails

The only workflow here that deletes, and both failure directions hit live infrastructure:

- **Pruning too early** — before the apply, the blocks still *are* the adoption
  instructions, so the next plan proposes **creating** resources that already exist.
- **Pruning the wrong construct** — removing a `resource` block proposes a **destroy**. On
  something like `google_project_service` that is an API disable on a live project.

So:

1. Touch **only** `import {}` and `moved {}` blocks. Never `resource`, `data`, `module`,
   `provider`, `locals`, or `variable`. Removing a resource is `add`'s inverse and is not
   this workflow.
2. Decide with a **plan pair**, not a hunch: the leaf plans with nothing pending *before*
   the edit, and `No changes.` *after* it. A block that has not run still shows up — a
   pending `import` prints `will be imported`, a pending `moved` prints its rename — so
   that pair is what separates spent from pending. `terraform state list` membership is
   the cheap pre-filter in front of it, never the sole evidence: address shapes like an
   aggregate module target or a `count` added on one side defeat it. The runbook has the
   rules and the cases where only a plan can answer.
3. **Refuse on a dirty plan.** If the leaf does not plan cleanly apart from the blocks you
   are about to remove, stop and report rather than prune into an unrelated diff.
4. **One pull request per leaf.** Leaves have separate workspaces and separate applies.
5. **Leaves only — never `terraform/modules/`.** Every consuming state reads a module's
   blocks separately, and that set is not closed. A module's `moved` block is its upgrade
   path, which Terraform says to retain; its `import` block is spent only per consumer, and
   deleting it while one is behind makes that consumer plan a **create** against a live
   resource. `prune-spent-imports` excludes the directory for the same reason, so a
   retained module block never shows up as work. The runbook has the citation.

## Workflow

1. **Read config first** (shared protocol, Step 0) and export the org vars —
   [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Resume scan** over `prune-spent-imports` in
   [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml). Green means no one-shot blocks are
   committed and there is nothing to do.
3. **Follow the runbook** [`../infra-copilot/references/docs/prune.md`](../infra-copilot/references/docs/prune.md): discover
   candidates, check each address against `terraform state list`, delete only the block,
   plan, open the PR.
4. If the before-plan still carries the block's own import or move, the apply has not
   landed. Stop and say so — that is `infra-copilot:import` finishing its work, not a
   prune.

## Validation

`terraform plan` for the leaf reports **`No changes. Your infrastructure matches the
configuration.`** with no `will be created`, `will be imported`, or `will be destroyed`.
Capture that output for the pull request body — it is the evidence that the removed blocks
were inert. `prune-spent-imports` then reads green for that leaf.

## Example

```text
# terraform/cloudflare — before
$ grep -c '^import {' generated_dns.tf
99
$ terraform state list | grep -c cloudflare_dns_record
99                      # filter: every `to =` address is already in state
$ terraform plan
No changes. Your infrastructure matches the configuration.   # nothing pending

# after removing the 99 import blocks, nothing else
$ terraform plan
No changes. Your infrastructure matches the configuration.   # they were inert
```

A `will be imported` in the *first* plan means those blocks had not run yet — leave them.
A `will be created` in the second means one address was not what the block named — restore
it.
