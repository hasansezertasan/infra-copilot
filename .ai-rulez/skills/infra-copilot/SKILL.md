---
name: infra-copilot
description: "Route infrastructure work to the correct infra-copilot workflow: setup for a greenfield bootstrap, import for existing resources, add for new resources or providers, and status for a read-only health check. Use when the user asks generally for infra-copilot or the correct workflow is unclear."
---

# infra-copilot

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
