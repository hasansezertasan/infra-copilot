---
name: infra-setup
description: "Agent-first, human-in-the-loop bootstrap for a Terraform + HCP + Cloudflare + GitHub SaaS infra repo. Reads a repo-local config (.claude/infra-copilot.local.md) then wires HCP state, the Cloudflare token, and the GitHub App, imports existing resources, and runs the first plan. Trigger on: 'set up infra', 'bootstrap this repo', 'run infra-setup', 'onboard a new org', '/infra-setup'."
---

# infra-setup

Agent-runnable bootstrap for this repo. You (the agent) execute it end-to-end, pausing
only for the steps a human irreducibly must do. Keep this file as the **router**: it
carries the protocol (actor model, handoff, resume) and routes to `references/` for the
per-provider detail and to the repo's canonical `docs/` for the fine print.

> **This is a Skill, not a script.** There is no `infra-setup` executable. Drive it by
> reading this file and the manifest, then running each step. A human invokes it with
> `/infra-setup` or by saying "set up the infra."

> **Orchestrates, does not duplicate.** Authoritative per-step detail lives in
> [`references/docs/setup.md`](references/docs/setup.md) (bootstrap) and
> [`references/docs/import.md`](references/docs/import.md) (Cloudflare migration). This
> skill adds the *actor split* and *resume protocol* on top. When a step says "see
> `setup.md#3`", read that section.

## The one idea

**The human is the browser and the keyholder. Everything scriptable is the agent's.**

There is exactly one thing a human must do that an agent cannot: sit at a browser, sign
up for a SaaS, and mint the first credential. Once an HCP token exists (from
`terraform login`), the agent creates workspaces, sets variables, reads plans, and
confirms applies **over the HCP API** — no more clicking. So the human surface shrinks to
three action kinds:

1. **Sign up** for a service (browser-only).
2. **Mint a credential** in a dashboard (browser-only — no API bootstraps the first token).
3. **Paste a secret** into HCP (browser-only — the agent must never see the plaintext).

Everything else — verifying, creating workspaces, importing resources, first plan — is yours.

## Step 0 — read the repo config (AGENT, always first)

Before the resume scan, read `.claude/infra-copilot.local.md` from the current repo and
export the shell vars every check depends on. Full schema + the export block:
[`references/config.md`](references/config.md). If the file is missing, emit the handoff
block, show the schema, offer to scaffold from `references/infra-copilot.local.md.example`,
and wait — never guess org/domain/IDs.

## Actors

Every step in [`references/steps.yaml`](references/steps.yaml) is tagged with who performs it:

| Tag | Meaning | Your behaviour |
|---|---|---|
| **`AGENT`** | You run it (shell, `gh`, `terraform`, HCP API). | Execute. Verify with the step's `check`. Continue on green. |
| **`HUMAN`** | Irreducibly human (signup, dashboard, secret paste). | **Stop.** Emit the handoff block. Wait for the human to reply `done`. Then run the `check` before continuing. |

### The handoff block

When a step is `HUMAN`, do **not** guess or fake it. Stop and print exactly this shape, then wait:

```
┌─ HUMAN ACTION NEEDED ─────────────────────────────
│ Step:   <id> — <title>
│ Why:    <one line — what this unblocks>
│ Do this:
│   1. <precise, copy-pasteable instruction, with URL>
│   2. …
│ When done, reply "done" and I'll verify.
└───────────────────────────────────────────────────
```

After the human replies, run the step's `check`. If it fails, re-emit the handoff with
what you observed — never silently proceed past a red check.

## Resume protocol

This skill is **idempotent and resumable**. On every run, before doing anything, walk
[`references/steps.yaml`](references/steps.yaml) top to bottom and run each step's `check`
to discover *where setup already is*. Resume at the first step whose check is red. An
all-green repo means "already set up, nothing to do."

```text
for step in steps.yaml:
    if run(step.check) is green:  skip, print "✓ {step.id}"
    else:                         resume here
```

Never assume state from memory or a prior session — always re-check.
See [`references/steps.yaml`](references/steps.yaml) for the runtime contract (which shell
vars to export before running any check).

## Preflight (AGENT)

Confirm your toolbox. All of these are yours to install if missing — none need a human.

```sh
terraform version      # ≥ 1.9   — provisioning + import blocks
gh --version           # GitHub CLI — repo ops, Pages, App install checks
jq --version           # JSON wrangling for HCP/Cloudflare/GitHub APIs
curl --version         # HCP + Cloudflare REST
```

These are the human-readable checks; the manifest's `preflight` block in
[`references/steps.yaml`](references/steps.yaml) enforces the version floor (Terraform ≥ 1.9)
programmatically — run those to gate, not just `terraform version`.

Then detect the credential the whole flow pivots on:

```sh
jq -re '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json \
  && echo "HCP token present — agent can drive the API" \
  || echo "No HCP token yet — first HUMAN step will mint one"
```

## Phases

Run in order. Each routes to a `references/` deep-dive and the canonical `docs/` section.

| # | Phase | Actors | Deep dive |
|---|---|---|---|
| 0 | **HCP bootstrap** — sign up, `terraform login`, get the pivot token | `HUMAN` then `AGENT` | [`references/hcp.md`](references/hcp.md), [`references/docs/setup.md#1`](references/docs/setup.md#1-hcp-terraform--organization) |
| 1 | **HCP workspaces** — create `cloudflare` + `github-org`, set VCS + safety toggles | `AGENT` (API) + `HUMAN` VCS OAuth | [`references/hcp.md`](references/hcp.md), [`references/docs/setup.md#2`](references/docs/setup.md#2-hcp-terraform--workspaces) |
| 2 | **Cloudflare** — mint scoped token, paste into HCP, verify | `HUMAN` mint/paste, `AGENT` verify | [`references/cloudflare.md`](references/cloudflare.md) |
| 3 | **GitHub** — create + install the GitHub App, paste creds into HCP | `HUMAN` create/install/paste, `AGENT` verify | [`references/github.md`](references/github.md) |
| 4 | **First plan** — `init` + speculative `plan` per leaf, read via API | `AGENT` | [`references/docs/setup.md#6`](references/docs/setup.md#6-local-development) |
| 5 | **Migration** — adopt existing resources with import blocks (no re-create) | `AGENT` run, `HUMAN` discovery token | [`references/migration.md`](references/migration.md) |
| 6 | **GCP** *(optional, template only)* — not provisioned today | design decision first | [`references/gcp.md`](references/gcp.md) |

### Phase 0 — HCP bootstrap
The only unavoidable cold-start; produces the token that lets you script the rest.
`HUMAN` signs up + runs `terraform login`; then you own the HCP API. Commands and verify:
[`references/hcp.md`](references/hcp.md#phase-0--bootstrap).

### Phase 1 — HCP workspaces
Two workspaces (`cloudflare`, `github-org`), one per leaf. A human does the one-time
GitHub↔HCP OAuth (browser); you create both workspaces via the API with the right working
dir, path-scoped triggers, remote execution, and auto-apply **off**. Ready-to-run
`create_ws` helper + the safety-toggle rationale: [`references/hcp.md`](references/hcp.md#phase-1--workspaces).

### Phase 2 — Cloudflare
You can't mint a scoped Cloudflare token from nothing, and must never see the plaintext —
so minting/pasting are `HUMAN`, verifying is `AGENT`. Full walkthrough:
[`references/cloudflare.md`](references/cloudflare.md).

### Phase 3 — GitHub
The `github-org` workspace authenticates as a **GitHub App**, not a PAT. Creation +
install are browser flows; three creds get pasted into HCP. Walkthrough incl. the
manifest-flow shortcut: [`references/github.md`](references/github.md).

### Phase 4 — First plan (AGENT)
Prove every credential end-to-end. Per leaf: `terraform init` then `terraform plan`
(speculative, runs in HCP). A VCS-connected workspace **allows `plan` but blocks `apply`**
from the CLI — intentional. Read plans without the UI via
[`references/docs/hcp-api.md`](references/docs/hcp-api.md). Green on both leaves = credentials proven.

### Phase 5 — Migration (adopt existing resources)
If the domain/repos already exist, **import** them so Terraform manages them without
recreating. Canonical runbook: [`references/docs/import.md`](references/docs/import.md);
cross-provider pattern: [`references/migration.md`](references/migration.md). Success signal:
`terraform plan` shows every existing resource as **"will import"**, nothing as **"will create"**.

### Phase 6 — GCP (template, optional)
**Not provisioned today.** GCP is not a managed provider here. Adopting it is a
**locked-design-decision change** — update the repo's locked design decisions doc and its
Terraform layout README first, then follow the same actor split. Template:
[`references/gcp.md`](references/gcp.md).

## Done signal

Setup is complete when you can report:

- ✓ HCP org `$ORG` (<your-org>) + project `infra` reachable via API.
- ✓ Workspaces `cloudflare` and `github-org` exist, VCS-linked, auto-apply off, fork speculative plans off.
- ✓ All sensitive vars present (`cloudflare_api_token`; `github_app_id`, `github_app_installation_id`, `github_app_pem`).
- ✓ `terraform plan` green on both leaves.
- ✓ Existing resources imported (plan shows imports, no creates) — if migrating.

Then day-to-day work follows your repo's own contributor guide.

## Configuring for your org

All org-specific values — HCP org, GitHub org, apex domain, Cloudflare account/zone IDs,
managed repos, and the HCP status-check ID — live in one place:
`.claude/infra-copilot.local.md` (schema and export block: [`references/config.md`](references/config.md)).
Fill it in once and re-run this skill from Phase 0 — the resume protocol handles the rest.
