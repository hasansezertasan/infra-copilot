---
description: "Shortcut that loads the infra-copilot prune skill — remove spent one-shot import/moved blocks after their apply landed, ending on a plan of No changes."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:d4e10f150508311093582256972a1527270d4235ef7a009082f656e49a94aa8d
Source-Hash: blake3:7bfda8f8cc78a8ac10d894a3051f644385db1b1467474089cb948caff867a5da
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
3. **Follow the runbook** [`prune.md`](../skills/infra-copilot/references/docs/prune.md): prove each block
   spent by the evidence that backend allows — `terraform state list` membership in front
   of the plan pair on HCP, the two workflow plans alone in object-storage mode, where the
   bucket credential lives in Actions and a local `state list` cannot authenticate. Only
   `import {}` and `moved {}` blocks — never a `resource`, `data`, `module`, or `provider`.
4. **Success = plan shows `No changes.`** A `will be created` means the block was still
   pending, not spent — restore it. Recovery differs by block: a pending `import {}` means
   finishing `infra-copilot:import`; a pending `moved {}` means letting the move apply,
   then re-checking it by the runbook's rule for its shape, which is not the same test for
   distinct addresses, for an added index, and for a removed one.

Contract for the actor split: [`protocol.md`](../skills/infra-copilot/references/protocol.md).
