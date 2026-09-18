---
description: "Shortcut that loads the infra-copilot import skill — adopt existing provider resources into Terraform (cf-terraforming import blocks) without recreating them."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, Task, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:64948c128c4bf5aa67512d248e647183bc24918be144ecd402c474fb1032e51a
Source-Hash: blake3:c3b9c855782f1cbcf4a44419194c8b2bd0fa29f3b0f58ad283cea1d199a9f9ce
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
