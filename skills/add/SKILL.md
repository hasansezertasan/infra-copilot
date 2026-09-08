---
name: add
description: "Provision something new in an already-bootstrapped infra repo: a managed GitHub repo, a resource on an existing provider, or a brand-new provider such as GCP. Ends on a green plan showing the new thing as will be created. Use when the thing does not exist yet — if it already exists at the provider, use infra-copilot:import instead."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:69d798d59ecfc0889098bd7e9005deccc6a451a8e7a468e2ba2c3411faca5420
Source-Hash: blake3:6a85e947e5b1460762120c5f8a3464d8751814b5e0023568157f95380e97602c
Schema-Version: v1
-->

# infra-copilot: add

Grow a repo that `infra-copilot:setup` already bootstrapped. Three flavors of "add," in
increasing blast radius. This file is a **router**: the reusable machinery — actor model,
handoff, resume, preflight — lives in [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md); the
manifest in [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml); per-provider detail under
[`../infra-copilot/references/`](../infra-copilot/references/).

> **New vs. existing.** `add` provisions things that **don't exist yet** — Terraform will
> `create` them, and a `create` in the plan is the *expected, correct* outcome. If the
> thing already exists at the provider and you're bringing it under management, that's
> **infra-copilot:import** (where a `create` means something went wrong).

## Guardrails

`infra-copilot:setup` phases 0–4 are green before this runs. `add` extends a working
repo; it does not bootstrap credentials.

Only for things that do **not** exist yet. If the resource already exists at the
provider, this skill would tell Terraform to create a duplicate — use
**infra-copilot:import** instead. Never fake a `HUMAN` step: an App-scope change, a token
mint or paste, and a provider decision are the human's, per the shared protocol.

## Pick the flavor

### 1. Add a managed repo (smallest)

Terraform's `github-org` leaf manages repos. To add one:

1. **Config** — append the repo to `managed_repos` in `.infra-copilot/config.md`
   ([`../infra-copilot/references/config.md`](../infra-copilot/references/config.md)) and re-export `$REPO` if it's the first
   entry (the VCS repo HCP watches).
2. **GitHub App install scope** (`HUMAN` if the App is installed on selected repos) — the
   App must be able to see the new repo. If install is scoped, a human extends it in the
   org's App-install settings, then replies `done`. See
   [`../infra-copilot/references/github.md`](../infra-copilot/references/github.md).
3. **Terraform** — add the resource/module in `terraform/github/`, `terraform init` +
   `plan`. Green plan showing the new repo as **will be created** (or **imported**, if it
   already exists on GitHub — then hand to `infra-copilot:import`).

### 2. Add a resource to an existing provider

A new Cloudflare DNS record, page rule, or GitHub repo setting — the provider and its
workspace/token already exist, so this is pure Terraform:

1. Write the resource under the right leaf (`terraform/cloudflare/` or `terraform/github/`).
2. If it needs a permission the current scoped token lacks (e.g. a new Cloudflare resource
   type), the token needs widening — a `HUMAN` mint/paste. Scope-widening guidance:
   [`../infra-copilot/references/cloudflare.md`](../infra-copilot/references/cloudflare.md) and
   [`../infra-copilot/references/docs/secrets.md`](../infra-copilot/references/docs/secrets.md).
3. `plan` → green with the new resource as **will be created**. `apply` runs through HCP
   per your normal review flow.

### 3. Adopt a brand-new provider (largest — a design decision)

Adding a provider like **GCP** is a **locked-design-decision change**, not a routine add.
GCP is *not* provisioned today (template only).

Route a new-provider adoption through Phase 6 of
[`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml), using
the shared resume protocol. Retain the requested provider's validated lowercase slug for
the protocol's bootstrap decision when config has no entry yet; an empty initial inventory
does not cancel an explicit adoption request. The manifest and protocol own the sequence
and safety rules.

Template + rationale for the GCP case: [`../infra-copilot/references/gcp.md`](../infra-copilot/references/gcp.md).

## Workflow

1. **Read config first** (shared protocol, Step 0) — [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Pick the flavor** above; run `AGENT` steps and stop + hand off on `HUMAN` steps
   (App-scope change, token mint/paste, provider decision). Full actor/handoff/resume
   contract: [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md).
3. **Verify with a plan**, then apply through your normal HCP review.

## Validation

`terraform plan` is green, the new thing is shown as **will be created**, and nothing is
unexpectedly destroyed. A resource appearing as *will be created* that you know already
exists live means this was the wrong skill — stop and use **infra-copilot:import**.

## Example

Adding one managed repo, after the config edit:

```text
# terraform/github
Plan: 1 to add, 0 to change, 0 to destroy.
  + github_repository.this["new-service"]
```

One `to add`, nothing to destroy: that is the shape to expect.
