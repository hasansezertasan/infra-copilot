---
name: setup
description: "Greenfield bootstrap of a Terraform + HCP Terraform + Cloudflare + GitHub infra repo: wires HCP state, the Cloudflare token and the GitHub App, then reaches a green first plan on both leaves. Use when nothing is wired up yet, even if the user does not name infra-copilot. Not for adopting resources that already exist (infra-copilot:import), nor for provisioning new ones in a working repo (infra-copilot:add)."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:fb26470eec39a89de4f1a64a5b8f17d91c8dfa2b756a992a219b421c5d023c8d
Source-Hash: blake3:8ff82acc79def5f9ff1589320a05c6274cc0f2c948e0d3e71abae0f5c402e3cf
Schema-Version: v1
-->

# infra-copilot: setup

Greenfield bootstrap. You (the agent) execute it end-to-end, pausing only for the steps a
human irreducibly must do. This file is a **router**: the reusable machinery — actor
model, handoff block, resume scan, preflight — lives in
[`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md); the per-step manifest in
[`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml) (**phases 0–4**); per-provider detail and
the canonical docs under [`../infra-copilot/references/`](../infra-copilot/references/).

> **This is a Skill, not a script.** There is no `setup` executable. Drive it by reading
> this file, the protocol, and the manifest, then running each step. A human invokes it
> with `/infra-setup` or by saying "set up the infra."

## Scope

`setup` owns the cold start: from an empty repo to green plans on both leaves.

| # | Phase | Actors | Deep dive |
|---|---|---|---|
| 0 | **Toolchain + HCP bootstrap** — commit reviewed pins, sign up, `terraform login`, get the pivot token | `HUMAN` then `AGENT` | [`../infra-copilot/references/docs/setup.md#6`](../infra-copilot/references/docs/setup.md#6-local-development), [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md), [`../infra-copilot/references/docs/setup.md#1`](../infra-copilot/references/docs/setup.md#1-hcp-terraform--organization) |
| 1 | **HCP workspaces** — create `cloudflare` + `github-org`, VCS + safety toggles | `AGENT` (API) + `HUMAN` VCS OAuth | [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md), [`../infra-copilot/references/docs/setup.md#2`](../infra-copilot/references/docs/setup.md#2-hcp-terraform--workspaces) |
| 2 | **Cloudflare** — mint scoped token, paste into HCP, verify | `HUMAN` mint/paste, `AGENT` verify | [`../infra-copilot/references/cloudflare.md`](../infra-copilot/references/cloudflare.md) |
| 3 | **GitHub** — create + install the GitHub App, paste creds into HCP | `HUMAN` create/install/paste, `AGENT` verify | [`../infra-copilot/references/github.md`](../infra-copilot/references/github.md) |
| 4 | **First plan** — `init` + speculative `plan` per leaf, read via API | `AGENT` | [`../infra-copilot/references/docs/hcp-api.md`](../infra-copilot/references/docs/hcp-api.md) |

Adopting resources that already exist (a live domain, existing repos)? That's
**infra-copilot:import** (Phase 5), run after this reaches green plans.

> **⚠️ Pre-existing resources — stop before applying.** Unlike the old monolith, `setup`
> ends at green *speculative* plans (phase 4) and does **not** auto-import. If the phase-4
> plan shows resources as `will be created` that you know already exist live — a domain
> already serving traffic, repos already on GitHub — do **not** apply: an apply would
> recreate or clobber them. Run **infra-copilot:import** first to adopt them (the plan
> should then read *imports, not creates*), and only then apply.

## Workflow

1. **Read config first** (shared protocol, Step 0). Load `.infra-copilot/config.md`, or
   use `.claude/infra-copilot.local.md` as the migration fallback, and export the org
   vars. If both are missing → handoff, offer to scaffold, wait.
   See [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Bootstrap preflight**, then **resume scan** over phases 0–4 of
   [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml). On a cold repo, check that `mise` itself
   is available, then scan `toolchain-pin` before running the pin-dependent preflight
   checks. Once it is green, finish preflight, handle the optional `repo-config-sync` step,
   print `✓`, and continue from `hcp-login`. Full contract:
   [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md).
3. **Respect the actor split.** Run `AGENT` steps yourself. On a `HUMAN` step, stop, emit
   the handoff block, wait for `done`, re-run the `check` — never fake a signup, a
   dashboard click, or a secret paste.
4. **Route to the deep-dives** under `../infra-copilot/references/` for the fine print; don't duplicate them.

### Phase notes

- **Phase 0 — Toolchain + HCP bootstrap.** The first `HUMAN` step chooses exact tool
  versions, reviews the whole `mise.toml`, and commits it with `mise.lock`; this must
  happen before pin-dependent preflight. If the consuming repository ships an executable
  `scripts/sync-config.sh`, stop for a human to review and run it next, then verify its
  deterministic changes and canonical config were committed together;
  repositories without the helper skip this step. Then `HUMAN` signs up + runs
  `terraform login`, after which you own the HCP API. Toolchain sequence:
  [`../infra-copilot/references/docs/setup.md#6`](../infra-copilot/references/docs/setup.md#6-local-development).
  HCP commands + verify: [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md#phase-0--bootstrap).
- **Phase 1 — HCP workspaces.** Two workspaces (`cloudflare`, `github-org`), one per leaf.
  A human does the one-time GitHub↔HCP OAuth (browser); you create both via the API with
  the right working dir, path-scoped triggers, remote execution, and auto-apply **off**.
  `create_ws` helper + safety rationale: [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md#phase-1--workspaces).
- **Phase 2 — Cloudflare.** You can't mint a scoped token from nothing and must never see
  the plaintext — minting/pasting are `HUMAN`, verifying is `AGENT`.
  [`../infra-copilot/references/cloudflare.md`](../infra-copilot/references/cloudflare.md).
- **Phase 3 — GitHub.** The `github-org` workspace authenticates as a **GitHub App**, not
  a PAT. Creation + install are browser flows; three creds get pasted into HCP.
  [`../infra-copilot/references/github.md`](../infra-copilot/references/github.md).
- **Phase 4 — First plan.** Prove every credential end-to-end. Per leaf: `terraform init`
  then speculative `terraform plan` (runs in HCP). A VCS-connected workspace **allows
  `plan` but blocks `apply`** from the CLI — intentional. Read plans without the UI via
  [`../infra-copilot/references/docs/hcp-api.md`](../infra-copilot/references/docs/hcp-api.md). Green on both leaves =
  credentials proven.

## Validation

Setup is complete when you can report:

- ✓ `mise.toml` + `mise.lock` are reviewed, committed together, exact-pinned, and
  installable with `MISE_LOCKED=1`.
- ✓ HCP org `$ORG` + project `infra` reachable via API.
- ✓ Workspaces `cloudflare` and `github-org` exist, VCS-linked, auto-apply off, fork speculative plans off.
- ✓ Both workspaces use the exact Terraform version committed in `mise.toml`.
- ✓ All sensitive vars present (`cloudflare_api_token`; `github_app_id`, `github_app_installation_id`, `github_app_pem`).
- ✓ `terraform plan` green on both leaves.

If the domain/repos already exist, continue with **infra-copilot:import** to adopt them
(plan should then show imports, not creates). Otherwise day-to-day work follows your
repo's own contributor guide.

## Guardrails

`setup` ends at green **speculative** plans and does not apply. If a phase-4 plan shows
resources as `will be created` that you know already exist live — a domain already
serving traffic, repos already on GitHub — do **not** apply: an apply would recreate or
clobber them. Run **infra-copilot:import** first, so the plan reads *imports, not
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
managed repos, HCP status-check ID — live in `.infra-copilot/config.md` (schema +
export block: [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md)). Fill it in once and re-run —
the resume protocol handles the rest.
