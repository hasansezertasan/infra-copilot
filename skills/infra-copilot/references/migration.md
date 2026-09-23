<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:e7b862877a27a8c490232341ef44c5d546d3af374ee869244a6cc323491d5693
Source-Hash: blake3:4e46d743abe52e4a37a6604b75961963bddb2d09a2c95e122f4447c3271d7c73
Schema-Version: v1
-->


# Migration: adopting existing resources (agent-first)

Deep dive for [Phase 5](../../import/SKILL.md), the `infra-copilot:import` skill. How to bring
resources that **already exist** under Terraform management
without recreating them — across providers. The Cloudflare specifics are canonical in
[`import.md`](docs/import.md); this file is the cross-provider pattern and the actor split.

## The universal pattern

Every migration, whatever the provider, is the same five moves:

1. **Discover** what exists (read-only credential).
2. **Generate HCL** for each resource.
3. **Emit `import` blocks** (Terraform 1.5+ `import { to = … id = "…" }`).
4. **Plan** — the success signal is *"will be imported"*, and crucially **nothing
   *"will be created"*.**
5. **Commit + apply** on merge (human/API-confirmed, per [`ci.md`](docs/ci.md)).

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
[`import.md`](docs/import.md). Don't duplicate it; the agent should read and follow it.

Example: existing Email-Routing DNS records on `<apex-domain>` are import candidates. Pages
projects and R2 buckets were discovered but **deliberately excluded** (out of scope). That
scope call is the human-confirmed part of "review generated HCL".

> `cf-terraforming` is for **one-time onboarding**, not steady state, and **not for CI**.
> New resources should be written in Terraform directly from the start.

## GitHub

The `integrations/github` provider has no `cf-terraforming` equivalent; adopt existing
repos/settings with `import` blocks + handwritten (or `-generate-config-out`) HCL.

```sh
# AGENT discovers via gh (read-only) — e.g. repos to adopt:
gh repo list "$GITHUB_ORG" --json name,visibility,defaultBranchRef

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
mise exec -- gcloud services list --enabled --format='value(config.name)'
mise exec -- gcloud storage buckets list --format='value(name)'   # etc., per resource type
# import { to = google_storage_bucket.assets  id = "<project-id>/<bucket-name>" }
cd terraform/gcp && terraform plan  # expect: imported, not created
```

Before generating anything, apply the exclusions and scope order in
[`gcp.md`](./gcp.md#adoption-hazards): Google-managed service agents, default service
accounts, Google-created buckets, and the Terraform identity itself are not adopted, and
the foundation pass comes before any live system.

### Import IDs

Formats are inconsistent between resource types, and a wrong one fails the import (or
worse, matches nothing and the plan proposes a create). Verified against a real adoption:

| Resource | Import ID |
|---|---|
| `google_project_service` | `<project-id>/<service>` |
| `google_storage_bucket` | `<project-id>/<bucket-name>` (or bare `<bucket-name>`) |
| `google_service_account` | `projects/<project-id>/serviceAccounts/<email>` |
| `google_artifact_registry_repository` | `projects/<project-id>/locations/<location>/repositories/<repo-id>` |
| `google_project_iam_member` | `<project-id> <role> <member>` — **space-separated**, not slash |

The space-separated IAM form is the one people get wrong, e.g.
`"my-project roles/storage.admin serviceAccount:ci@my-project.iam.gserviceaccount.com"`.
For anything else, read the resource's *Import* section in the registry docs before
writing the block.

### `-generate-config-out` failure modes

`terraform plan -generate-config-out=generated.tf` writes a block for every `import`
whose target has no configuration yet, each preceded by
`# __generated__ by Terraform from "<id>"`. Two ways it goes wrong quietly:

**Deleting a resource strands its comment on the next one.** Deleting from `resource`
through the following blank line takes the *next* resource's comment with it and leaves
the deleted one's comment attached to an unrelated resource. The file still parses,
`validate` and `fmt` pass, and every comment below the edit now lies. Delete the comment
and its block as a unit, then re-check each comment against the resource beneath it. In
practice, removing four IAM bindings left three mislabeled resources, and the stray text
still matched a `grep` for the very member that had been excluded — the config looked
broken when it was correct, and would have looked correct had it been broken.

**Regeneration silently drops hand edits.** The generator cannot reproduce a
`prevent_destroy`, a `disable_on_destroy = false`, or a deliberate exclusion; a fresh run
re-emits what you removed and drops what you added. Keep `generated.tf` purely generated
and move every resource you edit by hand into its own hand-maintained file. If you must
edit the generated file, say so in a header comment so nobody regenerates over it.

### Verification checklist

Cheap and mechanical; each item caught a real problem:

- [ ] `import` blocks ↔ resource blocks are 1:1 — no orphans either way, no duplicate
      addresses
- [ ] The plan reads `N to import, 0 to add, 0 to change, 0 to destroy`
- [ ] Any `will be created` means a **wrong import address or ID** — fix it, never apply
      it
- [ ] Every `# __generated__` comment matches the resource beneath it
- [ ] Every `google_project_service` sets `disable_on_destroy = false`, and no
      `google_project_iam_binding` / `_policy` appears
- [ ] `terraform fmt -recursive -check` and `terraform validate` are both clean

## After a clean import plan

Open a PR (Conventional title). The four required checks run
([`ci.md`](docs/ci.md)); a maintainer reads the plan (UI or the
[HCP API toolkit](docs/hcp-api.md)) and confirms the apply on merge. The import executes as a
real run.

**The blocks then have to come out, in a second PR.** `import {}` and `moved {}` are
one-shot: once that run applies, the resources are managed by their addresses and the
blocks are inert — but nothing removes them on its own, and a repo that defers it
accumulates them. That prune is its own workflow, with its own preconditions (state must
already hold each address, and only instruction blocks may be touched): see
[`prune.md`](docs/prune.md) and the `infra-copilot:prune` skill. Never in the same PR as
the import — the apply has to land in between.
