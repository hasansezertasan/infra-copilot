---
name: setup
description: "Agent-first, human-in-the-loop GREENFIELD bootstrap of a Terraform + HCP Terraform Cloud + Cloudflare + GitHub SaaS infra repo. Reads a repo-local config (.infra-copilot/config.md), then wires HCP state, the Cloudflare token, and the GitHub App, and runs the first plan on both leaves. Use this WHENEVER a fresh/empty infra repo needs standing up — even if the user doesn't say 'infra-copilot'. Trigger on: 'set up infra', 'bootstrap this repo', 'nothing is wired up yet', 'get HCP/Cloudflare/the GitHub App connected', 'onboard our new org', 'wire up Terraform Cloud + Cloudflare + GitHub', 'there's no HCP workspace yet', 'plan won't init', 'run infra-setup', '/infra-setup'. This is the STAND-UP skill; use infra-copilot:import to adopt resources that already exist, infra-copilot:add to grow an already-bootstrapped repo, infra-copilot:status to just check state."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:97730f6a817b450988420713b169d431f5de86270467f612cc2e23b6270349bc
Source-Hash: blake3:d3abe5be6cb04f08b47c678f49ab17acd140ddd96fe66800afd01f14d7d7087c
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
| 0 | **HCP bootstrap** — sign up, `terraform login`, get the pivot token | `HUMAN` then `AGENT` | [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md), [`../infra-copilot/references/docs/setup.md#1`](../infra-copilot/references/docs/setup.md#1-hcp-terraform--organization) |
| 1 | **HCP workspaces** — create `cloudflare` + `github-org`, VCS + safety toggles | `AGENT` (API) + `HUMAN` VCS OAuth | [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md), [`../infra-copilot/references/docs/setup.md#2`](../infra-copilot/references/docs/setup.md#2-hcp-terraform--workspaces) |
| 2 | **Cloudflare** — mint scoped token, paste into HCP, verify | `HUMAN` mint/paste, `AGENT` verify | [`../infra-copilot/references/cloudflare.md`](../infra-copilot/references/cloudflare.md) |
| 3 | **GitHub** — create + install the GitHub App, paste creds into HCP | `HUMAN` create/install/paste, `AGENT` verify | [`../infra-copilot/references/github.md`](../infra-copilot/references/github.md) |
| 4 | **First plan** — `init` + speculative `plan` per leaf, read via API | `AGENT` | [`../infra-copilot/references/docs/hcp-api.md`](../infra-copilot/references/docs/hcp-api.md), [`../infra-copilot/references/docs/setup.md#6`](../infra-copilot/references/docs/setup.md#6-local-development) |

Adopting resources that already exist (a live domain, existing repos)? That's
**infra-copilot:import** (Phase 5), run after this reaches green plans.

> **⚠️ Pre-existing resources — stop before applying.** Unlike the old monolith, `setup`
> ends at green *speculative* plans (phase 4) and does **not** auto-import. If the phase-4
> plan shows resources as `will be created` that you know already exist live — a domain
> already serving traffic, repos already on GitHub — do **not** apply: an apply would
> recreate or clobber them. Run **infra-copilot:import** first to adopt them (the plan
> should then read *imports, not creates*), and only then apply.

## How to run

1. **Read config first** (shared protocol, Step 0). Load `.infra-copilot/config.md`, or
   use `.claude/infra-copilot.local.md` as the migration fallback, and export the org
   vars. If both are missing → handoff, offer to scaffold, wait.
   See [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Preflight**, then **resume scan** over phases 0–4 of
   [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml): run each `check`, print `✓` for green,
   resume at the first red step. Full contract:
   [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md).
3. **Respect the actor split.** Run `AGENT` steps yourself. On a `HUMAN` step, stop, emit
   the handoff block, wait for `done`, re-run the `check` — never fake a signup, a
   dashboard click, or a secret paste.
4. **Route to the deep-dives** under `../infra-copilot/references/` for the fine print; don't duplicate them.

### Phase notes

- **Phase 0 — HCP bootstrap.** The only unavoidable cold-start; produces the token that
  lets you script everything after. `HUMAN` signs up + runs `terraform login`; then you
  own the HCP API. Commands + verify: [`../infra-copilot/references/hcp.md`](../infra-copilot/references/hcp.md#phase-0--bootstrap).
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

## Done signal

Setup is complete when you can report:

- ✓ HCP org `$ORG` + project `infra` reachable via API.
- ✓ Workspaces `cloudflare` and `github-org` exist, VCS-linked, auto-apply off, fork speculative plans off.
- ✓ All sensitive vars present (`cloudflare_api_token`; `github_app_id`, `github_app_installation_id`, `github_app_pem`).
- ✓ `terraform plan` green on both leaves.

If the domain/repos already exist, continue with **infra-copilot:import** to adopt them
(plan should then show imports, not creates). Otherwise day-to-day work follows your
repo's own contributor guide.

## Configuring for your org

All org-specific values — HCP org, GitHub org, apex domain, Cloudflare account/zone IDs,
managed repos, HCP status-check ID — live in `.infra-copilot/config.md` (schema +
export block: [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md)). Fill it in once and re-run —
the resume protocol handles the rest.
