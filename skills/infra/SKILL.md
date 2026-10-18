---
name: infra
description: "Route infrastructure work to the correct infra-skills workflow: setup for a greenfield bootstrap, import for existing resources, prune for the spent blocks an import leaves behind, add for new resources or providers, and status for a read-only health check. Use when the request names infra-skills generally, or the right workflow is unclear."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:8407b396918408a062213aaa0658ae48a7df9c1cffe83807409aefd58f1fa866
Source-Hash: blake3:bc3035ae93f0d480805e2aa47fc30257a53ec0a06c0ebbeb36e6fe1679fa5ebb
Schema-Version: v1
-->

# infra-skills

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
