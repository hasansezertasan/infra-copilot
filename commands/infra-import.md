---
description: "Shortcut that loads the infra-copilot import skill — adopt existing provider resources into Terraform (cf-terraforming import blocks) without recreating them."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

# /infra-import

Explicit entry point for the [`import`](../skills/import/SKILL.md) skill — adopt resources
that already exist at a provider (a live domain, its DNS, existing repos) into Terraform
management **without recreating** them (phase 5). Run after `/infra-setup` reaches green
plans.

Load `../skills/import/SKILL.md` and drive it:

1. **Read config first** — [`config.md`](../skills/shared/config.md).
2. **Resume scan** over phase 5 of [`steps.yaml`](../skills/shared/steps.yaml). The
   discovery token is a throwaway **read-only** credential (`HUMAN`, deleted after) —
   never the HCP edit token.
3. **Follow the runbook** [`import.md`](../skills/shared/docs/import.md): `cf-terraforming`
   generate + import blocks, then `terraform plan`.
4. **Success = plan shows imports, not creates.** A `will be created` means a live resource
   wasn't recognized — stop and investigate.

Contract for the actor split: [`protocol.md`](../skills/shared/protocol.md).
