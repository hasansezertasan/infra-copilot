---
description: "Shortcut that loads the infra-copilot import skill — adopt existing provider resources into Terraform (cf-terraforming import blocks) without recreating them."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:fbfdc8d919179931a3bd93593a3c49c6df51dcafe207d6376dbbc88e7b938339
Source-Hash: blake3:e9f2c56c6f9369568f21df5929b0e9bf0e2610477b2106755d9de9741995d55f
Schema-Version: v1
-->

# /infra-import

Explicit entry point for the [`import`](../skills/import/SKILL.md) skill — adopt resources
that already exist at a provider (a live domain, its DNS, existing repos) into Terraform
management **without recreating** them (phase 5). Run after `/infra-setup` reaches green
plans.

Load `../skills/import/SKILL.md` and drive it:

1. **Read config first** — [`config.md`](../skills/infra-copilot/references/config.md).
2. **Resume scan** over phase 5 of [`steps.yaml`](../skills/infra-copilot/references/steps.yaml). The
   discovery token is a throwaway **read-only** credential (`HUMAN`, deleted after) —
   never the HCP edit token.
3. **Follow the runbook** [`import.md`](../skills/infra-copilot/references/docs/import.md): `cf-terraforming`
   generate + import blocks, then `terraform plan`.
4. **Success = plan shows imports, not creates.** A `will be created` means a live resource
   wasn't recognized — stop and investigate.

Contract for the actor split: [`protocol.md`](../skills/infra-copilot/references/protocol.md).
