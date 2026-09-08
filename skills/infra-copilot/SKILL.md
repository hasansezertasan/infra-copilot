---
name: infra-copilot
description: "Route infrastructure work to the correct infra-copilot workflow: setup for a greenfield bootstrap, import for existing resources, add for new resources or providers, and status for a read-only health check. Use when the user asks generally for infra-copilot or the correct workflow is unclear."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:8c4f82b1a117faa49a14b38a822c11c6c1128e273b76d43dd01f4d62c57c5662
Source-Hash: blake3:1b5cc49163541b6667f01a3731f2b01326ce8992bf15f0eede9b9d28c27bc1eb
Schema-Version: v1
-->

# infra-copilot

## Workflow

Choose the smallest workflow that matches the request, then load its skill:

| Intent | Skill |
|---|---|
| Bootstrap an empty infrastructure repository | [`../setup/SKILL.md`](../setup/SKILL.md) |
| Adopt resources that already exist | [`../import/SKILL.md`](../import/SKILL.md) |
| Add a new resource, repository, or provider | [`../add/SKILL.md`](../add/SKILL.md) |
| Inspect current state without changing anything | [`../status/SKILL.md`](../status/SKILL.md) |

The shared protocol, phase manifest, provider guidance, and operational runbooks live in
[`references/`](references/). They are the single behavioral source of truth for every
host package. Host-specific commands and manifests are adapters only.

## Guardrails

This skill owns no operations. It selects one workflow and hands off — it never reads
config, runs a check, or mutates anything itself. If a request spans two workflows, route
to the earlier one and let it name its successor: `setup` ends by pointing at `import`,
and `import` and `add` each say when the other applies.

## Validation

Exactly one skill is selected, and the reason it was selected is stated. If none of the
four fits, say so rather than choosing the closest.
