# Migration: adopting existing resources (agent-first)

Deep dive for [Phase 5](../SKILL.md#phase-5--migration-adopt-existing-resources) of the
infra-setup skill. How to bring resources that **already exist** under Terraform management
without recreating them — across providers. The Cloudflare specifics are canonical in
[`import.md`](../../../../docs/import.md); this file is the cross-provider pattern and the actor split.

## The universal pattern

Every migration, whatever the provider, is the same five moves:

1. **Discover** what exists (read-only credential).
2. **Generate HCL** for each resource.
3. **Emit `import` blocks** (Terraform 1.5+ `import { to = … id = "…" }`).
4. **Plan** — the success signal is *"will be imported"*, and crucially **nothing
   *"will be created"*.**
5. **Commit + apply** on merge (human/API-confirmed, per [`ci.md`](../../../../docs/ci.md)).

> The single check that catches a botched import: `terraform plan` must show the resource
> as **imported**, never **created**. A `create` for something that already exists means
> the resource address or import ID is wrong — fix before opening the PR.

## The actor split

| Action | Actor | Why |
|---|---|---|
| Mint a short-lived **read-only** discovery token | **HUMAN** | Dashboard-only; scoped narrower than the HCP edit token. |
| Run the discovery tool / API | **AGENT** | `cf-terraforming`, `gcloud`, `gh` — read-only. |
| Generate HCL + import blocks | **AGENT** | Deterministic transformation. |
| Review/rename generated HCL, drop unwanted resources | **AGENT** (human confirms scope) | Scope decisions may need a human nod. |
| `terraform plan` to confirm imports-only | **AGENT** | Speculative run in HCP. |
| Delete the discovery token when done | **HUMAN** | Revoke in dashboard. |

## Cloudflare — canonical

Use Cloudflare's own [`cf-terraforming`](https://github.com/cloudflare/cf-terraforming),
maintained alongside the provider so import IDs and schemas track provider changes. Full
runbook — install, discovery token, `generate`, `import --modern-import-block`, the
supported-resource matrix, and the script/route gaps — is in
[`import.md`](../../../../docs/import.md). Don't duplicate it; the agent should read and follow it.

What this repo actually imported: the six Email-Routing DNS records on `perish.dev`. Pages
projects and R2 buckets were discovered but **deliberately excluded** (out of scope). That
scope call is the human-confirmed part of "review generated HCL".

> `cf-terraforming` is for **one-time onboarding**, not steady state, and **not for CI**.
> New resources should be written in Terraform directly from the start.

## GitHub

The `integrations/github` provider has no `cf-terraforming` equivalent; adopt existing
repos/settings with `import` blocks + handwritten (or `-generate-config-out`) HCL.

```sh
# AGENT discovers via gh (read-only) — e.g. repos to adopt:
gh repo list perishdev --json name,visibility,defaultBranchRef

# Then, per resource, an import block in terraform/github/*.tf:
#   import { to = github_repository.infra          id = "infra" }
#   import { to = github_branch_protection.infra    id = "infra:main" }   # provider-specific id format
cd terraform/github && terraform plan   # expect: imported, not created
```

Import ID formats are provider-specific (a repo is its name; branch protection is
`repo:pattern`; a membership is `org:username`). Check the resource's registry docs for
the exact `id` string before writing the block.

## GCP

**Only after GCP is an adopted provider** — see [`gcp.md`](./gcp.md). No first-party
generator; discover with `gcloud ... list`, then Terraform 1.5+ `import` blocks with HCL
either handwritten or via `terraform plan -generate-config-out=generated.tf`:

```sh
gcloud projects list
gcloud storage buckets list        # etc., per resource type
# import { to = google_storage_bucket.assets  id = "projects/<p>/buckets/<name>" }
cd terraform/gcp && terraform plan  # expect: imported, not created
```

## After a clean import plan

Open a PR (Conventional title). The four required checks run
([`ci.md`](../../../../docs/ci.md)); a maintainer reads the plan (UI or the
[HCP API toolkit](../../../../docs/hcp-api.md)) and confirms the apply on merge. The import executes as a
real run — after which the `import` blocks can be removed in a follow-up (they're one-shot;
the resources are managed by their addresses thereafter).
