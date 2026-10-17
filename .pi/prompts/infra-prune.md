---
description: Shortcut that loads the infra-copilot prune skill — remove spent one-shot import/moved blocks after their apply landed, ending on a plan of No changes.
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:6b89e702dca41cfeb91150e8ec5084bde92e4e9bb2711c705f8a791aa75872b6
Source-Hash: blake3:df6d5f221d5f2752857325a9d44038aac3612972e673e1181956a295f21aba0f
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
   spent by the evidence that backend allows — the runbook says which, and the answer
   differs between HCP and object-storage. Only `import {}` and `moved {}` blocks — never
   a `resource`, `data`, `module`, or `provider`.
4. **Success = plan shows `No changes.`** A `will be created` means the block was still
   pending, not spent — restore it. Recovery differs by block: a pending `import {}` means
   finishing `infra-copilot:import`; a pending `moved {}` means letting the move apply,
   then re-checking it by the runbook's rule for its shape, which is not the same test for
   distinct addresses, for an added index, and for a removed one.

Contract for the actor split: [`protocol.md`](../skills/infra-copilot/references/protocol.md).
