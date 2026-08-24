---
name: infra-copilot
description: "Route infrastructure work to the correct infra-copilot workflow: setup for a greenfield bootstrap, import for existing resources, add for new resources or providers, and status for a read-only health check. Use when the user asks generally for infra-copilot or the correct workflow is unclear."
# Content-Hash: blake3:2fd7abf96d13391da4189bf25668dbc544941a1cf18fe0ae7ecf3f9b05a1f8df
# Source-Hash: blake3:0aa53c1adce5e3fdfd714f4a47ed61c359243158d948c08dac6c0ad0aa68eec2
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


## Resources

This skill bundles supporting files. Read them on demand when the task calls for them — don't bulk-load.

### References

- [`references/cloudflare.md`](references/cloudflare.md) — Provider: Cloudflare (agent-first)
- [`references/config.md`](references/config.md) — Repo-local config contract
- [`references/config.md.example`](references/config.md.example)
- [`references/docs/ci.md`](references/docs/ci.md) — CI
- [`references/docs/hcp-api.md`](references/docs/hcp-api.md) — HCP Terraform API toolkit
- [`references/docs/import.md`](references/docs/import.md) — Importing existing Cloudflare resources
- [`references/docs/secrets.md`](references/docs/secrets.md) — Secrets
- [`references/docs/setup.md`](references/docs/setup.md) — Setup
- [`references/docs/state.md`](references/docs/state.md) — Terraform state
- [`references/gcp.md`](references/gcp.md) — Provider: GCP (TEMPLATE — not active)
- [`references/github.md`](references/github.md) — Provider: GitHub (agent-first)
- [`references/hcp.md`](references/hcp.md) — HCP bootstrap + workspaces (agent-first)
- [`references/migration.md`](references/migration.md) — Migration: adopting existing resources (agent-first)
- [`references/protocol.md`](references/protocol.md) — The infra-copilot protocol (shared)
- [`references/steps.yaml`](references/steps.yaml)
