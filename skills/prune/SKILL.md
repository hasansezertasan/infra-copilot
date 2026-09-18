---
name: prune
description: "Remove spent one-shot `import {}` and `moved {}` blocks after their apply landed, proving per block that state already holds the address and ending on a plan of No changes. Use once an import applied, never before."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:d88eb919fdad0a8bcff6bb9da361bbeb4ffe14f1c5bf27c8f5b5623961757967
Source-Hash: blake3:22be82fe229a301d56ddb5ecbf71556345fa3d0af9fa3d7dddf93a82ae9e99b6
Schema-Version: v1
-->

# infra-copilot: prune

Delete the **one-shot instruction blocks** an adoption leaves behind. `import {}` and
`moved {}` execute once; after that run applies, the resources are managed by their
addresses and the blocks are inert. Nothing else removes them, so they accumulate.

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
2. Verify **per block** that state already holds the address — `terraform state list`
   contains the `to =` target; for `moved`, the new address is present **and** the old one
   is absent. Never infer spent-ness from a green plan: a plan is clean both when the
   imports have run and when they are still pending.
3. **Refuse on a dirty plan.** If the leaf does not plan cleanly apart from the blocks you
   are about to remove, stop and report rather than prune into an unrelated diff.
4. **One pull request per leaf.** Leaves have separate workspaces and separate applies.

## Workflow

1. **Read config first** (shared protocol, Step 0) and export the org vars —
   [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Resume scan** over `prune-spent-imports` in
   [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml). Green means no one-shot blocks are
   committed and there is nothing to do.
3. **Follow the runbook** [`../infra-copilot/references/docs/prune.md`](../infra-copilot/references/docs/prune.md): discover
   candidates, check each address against `terraform state list`, delete only the block,
   plan, open the PR.
4. If state does **not** hold an address, the apply has not landed. Stop and say so —
   that is `infra-copilot:import` finishing its work, not a prune.

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
99                      # every `to =` address is already in state: spent

# after removing the 99 import blocks, nothing else
$ terraform plan
No changes. Your infrastructure matches the configuration.
```

A single `will be created` here means one address was **not** in state — restore that
block, it was still pending.
