---
name: infra-setup
description: "Greenfield bootstrap of a Terraform + Cloudflare + GitHub infra repo with either HCP Terraform (cloud block) or object-storage backend (GCS/S3/Azure + GitHub Actions). Wires state, the Cloudflare token, and the GitHub App, then reaches a green first plan on both leaves. Use when nothing is wired up yet. Not for adopting resources that already exist (infra-skills:infra-import), nor for provisioning new ones in a working repo (infra-skills:infra-add)."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:854ea255a631908d22952af72449efb33fdba6da2d7f973bb9dcb2591ea8ec28
Source-Hash: blake3:42c7574fde1dc55e8f96bd54590bf4f29122805f262a3a990b60d7f7f4763ae5
Schema-Version: v1
-->

# infra-setup

Greenfield bootstrap. You (the agent) execute it end-to-end, pausing only for the steps a
human irreducibly must do. This file is a **router**: the reusable machinery — actor
model, handoff block, resume scan, preflight — lives in
[`../infra/references/protocol.md`](../infra/references/protocol.md); the per-step manifest in
[`../infra/references/steps.yaml`](../infra/references/steps.yaml) (**phases 0–4**); per-provider detail and
the canonical docs under [`../infra/references/`](../infra/references/).

> **This is a Skill, not a script.** There is no `setup` executable. Drive it by reading
> this file, the protocol, and the manifest, then running each step. A human invokes it
> with `/infra-skills:infra-setup` or by saying "set up the infra."

## Scope

`setup` owns the cold start: from an empty repo to green plans on both leaves.

The mode sections below describe each implementation's duties for the leaves routed to
it, not a repository-wide either/or. Load and validate `leaf_backends` with the default
in config before preflight. In mixed repositories, establish both service prerequisites,
configure only each service's effective bootstrap subset, and verify credentials/plans
on each leaf's selected implementation. Additional providers join the service inventory
but their leaf setup remains Phase 6. Do not recreate or reconnect a migrated HCP leaf.
Synchronize Actions' static `CLOUDFLARE_BACKEND` and `GITHUB_BACKEND` values with effective
config in the cutover PR and verify plan/apply workflow agreement before proceeding.
For existing HCP state, follow
[`the migration runbook`](../infra/references/docs/object-storage-state.md#migrating-from-hcp),
not a fresh backend initialization. See
[`operation selection`](../infra/references/operations.md#selection-and-resume).

### HCP implementation (effective HCP leaves)

| # | Phase | Actors | Deep dive |
|---|---|---|---|
| 0 | **Toolchain + HCP bootstrap** — commit reviewed pins, sign up, `terraform login`, get the pivot token | `HUMAN` then `AGENT` | [`../infra/references/docs/setup.md#6`](../infra/references/docs/setup.md#6-local-development), [`../infra/references/hcp.md`](../infra/references/hcp.md), [`../infra/references/docs/setup.md#1`](../infra/references/docs/setup.md#1-hcp-terraform--organization) |
| 1 | **HCP workspaces** — create `cloudflare` + `github-org`, VCS + safety toggles | `AGENT` (API) + `HUMAN` VCS OAuth | [`../infra/references/hcp.md`](../infra/references/hcp.md), [`../infra/references/docs/setup.md#2`](../infra/references/docs/setup.md#2-hcp-terraform--workspaces) |
| 2 | **Cloudflare** — mint scoped token, paste into HCP, verify | `HUMAN` mint/paste, `AGENT` verify | [`../infra/references/cloudflare.md`](../infra/references/cloudflare.md) |
| 3 | **GitHub** — create + install the GitHub App, paste creds into HCP | `HUMAN` create/install/paste, `AGENT` verify | [`../infra/references/github.md`](../infra/references/github.md) |
| 4 | **Narrow the credential, then first plan** — hand off to a plan-only HCP identity, then `init` + speculative `plan` per leaf, read via API | `HUMAN` handoff, then `AGENT` | [`../infra/references/steps.yaml`](../infra/references/steps.yaml) (`hcp-apply-scope`), [`../infra/references/docs/hcp-api.md`](../infra/references/docs/hcp-api.md) |

### Object-storage implementation (effective object-storage leaves)

| # | Phase | Actors | Deep dive |
|---|---|---|---|
| 0 | **Toolchain + state bucket** — commit reviewed pins, create versioned bucket, configure `backend.tf` blocks | `HUMAN` then `AGENT` | [`../infra/references/docs/object-storage-state.md#object-storage-backend`](../infra/references/docs/object-storage-state.md#object-storage-backend) |
| 1 | **GitHub Actions CI** — create plan/apply workflows, configure GitHub Environment protection | `AGENT` then `HUMAN` | [`../infra/references/docs/object-storage-ci.md#github-actions`](../infra/references/docs/object-storage-ci.md#github-actions) |
| 2 | **Cloudflare** — mint scoped token, add `CLOUDFLARE_API_TOKEN` to GitHub Actions secrets, verify | `HUMAN` mint/save, `AGENT` verify | [`../infra/references/cloudflare.md`](../infra/references/cloudflare.md) |
| 3 | **GitHub** — create + install GitHub App, add secrets (`GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `GH_APP_PEM`) to GitHub Actions | `HUMAN` create/install/save, `AGENT` verify | [`../infra/references/github.md`](../infra/references/github.md) |
| 4 | **First plan** — verify `plan-cloudflare` and `plan-github` jobs succeed in GitHub Actions | `AGENT` | [`../infra/references/steps.yaml`](../infra/references/steps.yaml), [`../infra/references/docs/object-storage-ci.md#github-actions`](../infra/references/docs/object-storage-ci.md#github-actions) |

Adopting resources that already exist (a live domain, existing repos)? That's
**infra-skills:infra-import** (Phase 5), run after this reaches green plans.

> **⚠️ Pre-existing resources — stop before applying.** Unlike the old monolith, `setup`
> ends at green *speculative* plans (phase 4) and does **not** auto-import. If the phase-4
> plan shows resources as `will be created` that you know already exist live — a domain
> already serving traffic, repos already on GitHub — do **not** apply: an apply would
> recreate or clobber them. Run **infra-skills:infra-import** first to adopt them (the plan
> should then read *imports, not creates*), and only then apply.

## Workflow

1. **Render the Template, or resume** (shared protocol, Step 0). On a directory with no
   `.copier-answers.yml` and no README Config block, run `template-render`: read the
   Template's current `copier.yml`, ask its questions, render with the pinned Copier and
   commit the answers file. A repo is rendered when it has a committed answers file and
   a README Config block; it resumes, and is never re-scaffolded. A Config block without
   an answers file (or the reverse) is not rendered: hand off, never render over it.
   Never edit a file the Template owns. Then run `template-contract`: an older tag
   proposes the Template's `copier update`, a bare commit hands off.

   Then **read config.** Load the Config block from the
   root `README.md` and export the org vars. A legacy `.infra-copilot/` directory or
   `.claude/infra-copilot.local.md` → unsupported, stop. No Config block → handoff, wait.
   For a new setup, recommend **object-storage** first. Explain HCP's managed runs and
   UI, its free tier's 500-resource limit, and this workflow's required paid tier with
   team management for the plan-only credential, even below 500 resources. Ask for the
   choice using the shared protocol and record it as the Template's `backend` answer
   (`object-storage` or `hcp`), explicit and never defaulted. `backend` sits outside the
   customization markers, so you never write it yourself.
   Existing configs without `backend` stop for the migration handoff; existing `cloud {}`
   blocks prompt an offer for the human to record `backend: hcp`, never an automatic mode switch.
   See [`../infra/references/config.md`](../infra/references/config.md).
2. **Bootstrap preflight**, then **resume scan** over phases 0–4 of
   [`../infra/references/steps.yaml`](../infra/references/steps.yaml). On a cold repo, check that `mise` itself
   is available, then scan `toolchain-pin` before running the pin-dependent preflight
   checks. Once it is green, finish preflight, print `✓`, and continue through every selected service's bootstrap members. Full contract:
   [`../infra/references/protocol.md`](../infra/references/protocol.md).
3. **Respect the actor split.** Run `AGENT` steps yourself. On a `HUMAN` step, stop, emit
   the handoff block, wait for `done`, re-run the `check` — never fake a signup, a
   dashboard click, or a secret paste.
4. **Route to the deep-dives** under `../infra/references/` for the fine print; don't duplicate them.

### Phase notes

**HCP mode:**

- **Phase 0 — Toolchain + HCP bootstrap.** The first `HUMAN` step chooses exact tool
  versions, reviews the whole `mise.toml`, and commits it with `mise.lock`; this must
  happen before pin-dependent preflight. Then `HUMAN` signs up + runs
  `terraform login`, after which you own the HCP API. Toolchain sequence:
  [`../infra/references/docs/setup.md#6`](../infra/references/docs/setup.md#6-local-development).
  HCP commands + verify: [`../infra/references/hcp.md`](../infra/references/hcp.md#phase-0--bootstrap).
- **Phase 1 — HCP workspaces.** Only HCP-routed bootstrap leaves get workspaces
  (`cloudflare` for Cloudflare, `github-org` for GitHub).
  A human does the one-time GitHub↔HCP VCS connection (browser); create the selected subset via the API with
  the right working dir, path-scoped triggers, remote execution, and auto-apply **off**.
  `create_ws` helper + safety rationale: [`../infra/references/hcp.md`](../infra/references/hcp.md#phase-1--workspaces).
- **Phase 2 — Cloudflare.** You can't mint a scoped token from nothing and must never see
  the plaintext — minting/pasting are `HUMAN`, verifying is `AGENT`.
  [`../infra/references/cloudflare.md`](../infra/references/cloudflare.md).
- **Phase 3 — GitHub.** The `github-org` workspace authenticates as a **GitHub App**, not
  a PAT. Creation + install are browser flows; three creds get pasted into HCP.
  [`../infra/references/github.md`](../infra/references/github.md).
- **Phase 4 — First plan.** Prove every credential end-to-end. Per leaf: `terraform init`
  then speculative `terraform plan` (runs in HCP). A VCS-connected workspace **allows
  `plan` but blocks `apply`** from the CLI — intentional. Read plans without the UI via
  [`../infra/references/docs/hcp-api.md`](../infra/references/docs/hcp-api.md). Green on both leaves =
  credentials proven.

**Object-storage mode:**

- **Phase 0 — Toolchain + state bucket.** Tool versions are committed in `mise.toml` +
  `mise.lock`. `HUMAN` creates the versioned, private state bucket with locking configured.
  `AGENT` writes `backend.tf` blocks in each leaf pointing to the state bucket.
  [`../infra/references/docs/object-storage-state.md#object-storage-backend`](../infra/references/docs/object-storage-state.md#object-storage-backend).
- **Phase 1 — GitHub Actions CI.** `AGENT` creates `.github/workflows/terraform-plan.yml` and
  `terraform-apply.yml`. `HUMAN` restricts the `production` GitHub Environment to `main` and adds
  required reviewers where the plan offers them, or locks an `Apply gate` decision.
  [`../infra/references/docs/object-storage-ci.md#github-actions`](../infra/references/docs/object-storage-ci.md#github-actions).
- **Phase 2 — Cloudflare.** `HUMAN` mints scoped token and adds `CLOUDFLARE_API_TOKEN` to
  GitHub Actions secrets; `AGENT` verifies.
  [`../infra/references/cloudflare.md`](../infra/references/cloudflare.md).
- **Phase 3 — GitHub.** `HUMAN` creates/installs GitHub App and adds `GH_APP_ID`,
  `GH_APP_INSTALLATION_ID`, and `GH_APP_PEM` to GitHub Actions secrets; `AGENT` verifies.
  [`../infra/references/github.md`](../infra/references/github.md).
- **Phase 4 — First plan.** Trigger or inspect GitHub Actions plan workflows for `cloudflare`
  and `github` leaves; verify both jobs succeed. Align required status check job names.
  [`../infra/references/docs/object-storage-ci.md#github-actions`](../infra/references/docs/object-storage-ci.md#github-actions).

## Validation

Setup is complete when you can report:

- ✓ The README Config block explicitly records the chosen `backend`.

**For every effective HCP leaf and the shared HCP service:**

- ✓ `mise.toml` + `mise.lock` are reviewed, committed together, exact-pinned, and
  installable with `MISE_LOCKED=1`.
- ✓ HCP org `$ORG` + project `infra` reachable via API.
- ✓ Every HCP-routed bootstrap workspace exists, VCS-linked, auto-apply off, fork speculative plans off.
- ✓ Each selected workspace uses the exact Terraform version committed in `mise.toml`.
- ✓ Its required variables are present: `cloudflare_api_token` only for HCP-routed Cloudflare;
  `github_app_id`, `github_app_installation_id`, `github_app_pem` only for HCP-routed GitHub.
- ✓ `terraform plan` is green on every HCP-routed bootstrap leaf.
- ✓ `hcp-apply-scope` green — the credential in use cannot apply. It is a `HUMAN`
  step like `cf-token` and `gh-app`: stop there, hand off, and continue when it turns
  green. Setup is not complete while the agent still holds the apply-capable user
  token from `terraform login`.

**For every effective object-storage leaf and the shared runner service:**

- ✓ `mise.toml` + `mise.lock` are reviewed, committed together, exact-pinned, and
  installable with `MISE_LOCKED=1`.
- ✓ State bucket created, versioned, private, with locking configured.
- ✓ `backend.tf` blocks configured in each object-storage-routed bootstrap leaf.
- ✓ GitHub Actions workflows committed (`terraform-plan.yml`, `terraform-apply.yml`) and production environment configured.
- ✓ Required Actions secrets are present: `CLOUDFLARE_API_TOKEN` only for runner-routed Cloudflare;
  `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `GH_APP_PEM` only for runner-routed GitHub.
- ✓ Each object-storage-routed bootstrap leaf's plan job is green (`plan-cloudflare` or `plan-github`).
- ✓ Required status checks in branch protection match workflow job names.

If the domain/repos already exist, continue with **infra-skills:infra-import** to adopt them
(plan should then show imports, not creates). Otherwise day-to-day work follows your
repo's own contributor guide.

## Guardrails

`setup` ends at green **speculative** plans and does not apply. If a phase-4 plan shows
resources as `will be created` that you know already exist live — a domain already
serving traffic, repos already on GitHub — do **not** apply: an apply would recreate or
clobber them. Run **infra-skills:infra-import** first, so the plan reads *imports, not
creates*.

Never fake a `HUMAN` step. A signup, a dashboard click and a secret paste are the
human's, and the agent must never see a pasted secret in plaintext. On a red check after
a human replies `done`, re-emit the handoff with what you observed rather than
proceeding.

## Example

A resumed run prints what is already green and stops at the first red step:

```text
✓ toolchain-pin   ✓ hcp-login   ✓ hcp-signup   ✓ hcp-verify
✓ vcs-connect     ✗ workspaces-create   ← resume here
```

Everything green means the scope is already done and there is nothing to do.

## Configuring for your org

All org-specific values — HCP org, GitHub org, apex domain, Cloudflare account/zone IDs,
managed repos, HCP status-check ID — live in the README Config block (schema +
export block: [`../infra/references/config.md`](../infra/references/config.md)). The Template answers (orgs, domain, account IDs, `managed_repos`) change only through the
Template's update flow; fill in the customization region once and re-run —
the resume protocol handles the rest.
