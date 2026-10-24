---
name: infra
description: "Route infrastructure work to the correct infra-skills workflow: setup for a greenfield bootstrap, import for existing resources, prune for the spent blocks an import leaves behind, add for new resources or providers, and status for a read-only health check. Use when the request names infra-skills generally, or the right workflow is unclear."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:d4ca4a3b1b8c035d0e9e8cf2ede54424c683c62bd288b88ca35db5a60a9f978b
Source-Hash: blake3:42c7574fde1dc55e8f96bd54590bf4f29122805f262a3a990b60d7f7f4763ae5
Schema-Version: v1
-->

# infra

## Workflow

Choose the smallest workflow that matches the request, then load its skill:

| Intent | Skill |
|---|---|
| Bootstrap an empty infrastructure repository | [`../infra-setup/SKILL.md`](../infra-setup/SKILL.md) |
| Adopt resources that already exist | [`../infra-import/SKILL.md`](../infra-import/SKILL.md) |
| Remove the spent `import {}` / `moved {}` blocks an adoption left behind | [`../infra-prune/SKILL.md`](../infra-prune/SKILL.md) |
| Add a new resource, repository, or provider | [`../infra-add/SKILL.md`](../infra-add/SKILL.md) |
| Inspect current state without changing anything | [`../infra-status/SKILL.md`](../infra-status/SKILL.md) |

The shared protocol, phase manifest, provider guidance, and operational runbooks live in
[`references/`](references/). They are the single behavioral source of truth for every
host package. Host-specific commands and manifests are adapters only.

## Guardrails

This skill owns no operations. It selects one workflow and hands off — it never reads
config, runs a check, or mutates anything itself. If a request spans two workflows, route
to the earlier one and let it name its successor: `infra-setup` ends by pointing at `infra-import`,
`infra-import` at `infra-prune` once its apply has landed, and `infra-import` and `infra-add` each say when the
other applies.

## Validation

Exactly one skill is selected, and the reason it was selected is stated. If none of the
five fits, say so rather than choosing the closest.
