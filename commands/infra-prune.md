---
description: "Shortcut that loads the infra-copilot prune skill — remove spent one-shot import/moved blocks after their apply landed, ending on a plan of No changes."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:77a372f8036d9875924939820b9c0c5339078894d800daee9080be252408ae67
Source-Hash: blake3:9e1edb5b37d8b4776d580dd73226e92ecbfe169e516fc7a12021203d4380006d
Schema-Version: v1
-->

# /infra-prune

Explicit entry point for the [`prune`](../skills/prune/SKILL.md) skill — delete the
one-shot `import {}` and `moved {}` blocks an adoption left behind, once the run that
executed them has **applied** (phase 5, `prune-spent-imports`). Run after `/infra-import`
and after that PR merged and applied — never in the same pull request.

Load `../skills/prune/SKILL.md` and drive it:

1. **Read config first** — [`config.md`](../skills/infra-copilot/references/config.md).
2. **Resume scan** over `prune-spent-imports` in
   [`steps.yaml`](../skills/infra-copilot/references/steps.yaml). Green means nothing is left to prune.
3. **Follow the runbook** [`prune.md`](../skills/infra-copilot/references/docs/prune.md): per block, prove
   `terraform state list` already holds the `to =` address before removing it. Only
   `import {}` and `moved {}` blocks — never a `resource`, `data`, `module`, or `provider`.
4. **Success = plan shows `No changes.`** A `will be created` means an address was not in
   state and the block was still pending — restore it and finish the import first.

Contract for the actor split: [`protocol.md`](../skills/infra-copilot/references/protocol.md).
