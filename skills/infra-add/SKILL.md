---
name: infra-add
description: "Provision something new in an already-bootstrapped infra repo: a managed GitHub repo, a resource on an existing provider, or a brand-new provider such as GCP. Ends on a green plan showing the new thing as will be created. Use when the thing does not exist yet — if it already exists at the provider, use infra-skills:infra-import instead."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:df478b92402aeb17945b4bb2cc46ecfa410d0d926108fb2627d32da98a374aab
Source-Hash: blake3:42c7574fde1dc55e8f96bd54590bf4f29122805f262a3a990b60d7f7f4763ae5
Schema-Version: v1
-->

# infra-add

Grow a repo that `infra-skills:infra-setup` already bootstrapped. Three flavors of "add," in
increasing blast radius. This file is a **router**: the reusable machinery — actor model,
handoff, resume, preflight — lives in [`../infra/references/protocol.md`](../infra/references/protocol.md); the
manifest in [`../infra/references/steps.yaml`](../infra/references/steps.yaml); per-provider detail under
[`../infra/references/`](../infra/references/).

> **New vs. existing.** `add` provisions things that **don't exist yet** — Terraform will
> `create` them, and a `create` in the plan is the *expected, correct* outcome. If the
> thing already exists at the provider and you're bringing it under management, that's
> **infra-skills:infra-import** (where a `create` means something went wrong).

## Guardrails

`infra-skills:infra-setup` phases 0–4 are green before this runs. `add` extends a working
repo; it does not bootstrap credentials.

Only for things that do **not** exist yet. If the resource already exists at the
provider, this skill would tell Terraform to create a duplicate — use
**infra-skills:infra-import** instead. Never fake a `HUMAN` step: an App-scope change, a token
mint or paste, and a provider decision are the human's, per the shared protocol.

## Pick the flavor

### 1. Add a managed repo (smallest)

Terraform's `github-org` leaf manages repos. To add one:

1. **Config** — `managed_repos` is a Template answer in the README Config block, outside the customization
   markers, so the Skills never edit it. Add the repo through the Template's own update flow
   ([`../infra/references/config.md`](../infra/references/config.md)), then re-export `$REPO` if it's the first
   entry (the repository used by the execution service).
2. **GitHub App install scope** (`HUMAN` if the App is installed on selected repos) — the
   App must be able to see the new repo. If install is scoped, a human extends it in the
   org's App-install settings, then replies `done`. See
   [`../infra/references/github.md`](../infra/references/github.md).
3. **Terraform** — add the resource/module in `terraform/github/`, then verify the plan:
   use the [get-plan operation](../infra/references/operations.md#get-plan).
   Green plan showing the new repo as **will be created** (or **imported**, if it
   already exists on GitHub — then hand to `infra-skills:infra-import`).

### 2. Add a resource to an existing provider

A new Cloudflare DNS record, page rule, or GitHub repo setting — the provider and its
execution and credentials already exist, so this is pure Terraform:

1. Write the resource under the right leaf (`terraform/cloudflare/` or `terraform/github/`).
2. If it needs a permission the current scoped token lacks (e.g. a new Cloudflare resource
   type), the token needs widening — a `HUMAN` mint/paste. Scope-widening guidance:
   [`../infra/references/cloudflare.md`](../infra/references/cloudflare.md) and
   [`../infra/references/docs/secrets.md`](../infra/references/docs/secrets.md).
3. Use [get-plan](../infra/references/operations.md#get-plan) → green with the new resource as **will be created**.
   Apply through the approved execution procedure after review.

### 3. Adopt a brand-new provider (largest — a design decision)

Adding a provider like **GCP** is a **locked-design-decision change**, not a routine add.
GCP is opt-in: nothing is provisioned until the decision is recorded.

Route a new-provider adoption through Phase 6 of
[`../infra/references/steps.yaml`](../infra/references/steps.yaml), using
the shared resume protocol. The manifest and protocol own the bootstrap behavior,
sequence, and safety rules.

Runbook for the GCP case (keyless WIF auth, adoption hazards): [`../infra/references/gcp.md`](../infra/references/gcp.md).

## Workflow

1. **Read config first** (shared protocol, Step 0) — [`../infra/references/config.md`](../infra/references/config.md).
2. **Pick the flavor** above; run `AGENT` steps and stop + hand off on `HUMAN` steps
   (App-scope change, token mint/paste, provider decision). Full actor/handoff/resume
   contract: [`../infra/references/protocol.md`](../infra/references/protocol.md).
3. **Verify with a plan**, then follow the [read-run-status operation](../infra/references/operations.md#read-run-status) to confirm the approved apply.

## Validation

`terraform plan` is green, the new thing is shown as **will be created**, and nothing is
unexpectedly destroyed. A resource appearing as *will be created* that you know already
exists live means this was the wrong skill — stop and use **infra-skills:infra-import**.

## Example

Adding one managed repo, after the config edit:

```text
# terraform/github
Plan: 1 to add, 0 to change, 0 to destroy.
  + github_repository.this["new-service"]
```

One `to add`, nothing to destroy: that is the shape to expect.
