---
name: add
description: "Provision something new in an already-bootstrapped infra repo: a managed GitHub repo, a resource on an existing provider, or a brand-new provider such as GCP. Ends on a green plan showing the new thing as will be created. Use when the thing does not exist yet — if it already exists at the provider, use infra-copilot:import instead."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:28e2b2c68044a9b601cf3c591873117c7a9ab1af3f6153c01c297ea40b5a65a2
Source-Hash: blake3:442b1d6efb723635feb68e4317c333d9df78a268c7e774efc132d587f7d406e6
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
GCP is *not* provisioned today (template only). Before any Terraform:

1. **Decide, on the record** (`HUMAN`, step `gcp-decision` in
   [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml)) — update
   `.infra-copilot/decisions.md` and `terraform/README.md`. Do not provision ahead of the decision.
2. **New leaf + workspace** — create `terraform/<provider>/`, a matching HCP workspace
   (same `create_ws` pattern as setup Phase 1, [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md)),
   with the same safety toggles (auto-apply off, path-scoped triggers).
3. **Credential** — mint the provider's scoped token/service-account key (`HUMAN`) and
   paste it into the new workspace's variables (`HUMAN`, sensitive). The agent verifies via
   the vars API, never sees the plaintext.
4. **First plan** on the new leaf — same proof-of-credentials as setup Phase 4.

Template + rationale for the GCP case: [`../infra-copilot/references/gcp.md`](../infra-copilot/references/gcp.md).

## Workflow

1. **Read config first** (shared protocol, Step 0) — [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Pick the flavor** above; run its `AGENT` steps, stop + hand off on its `HUMAN` steps
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
