<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:4fbc88be59ae3fb372778efaf246ebb3fce73f5cf6a0eec616554dca2ee722ff
Source-Hash: blake3:c5685395138066d55267f7fc18e082e5ba4632a7e2e8ed3145b4749f4becfdb1
Schema-Version: v1
-->


# The infra-copilot protocol (shared)

Every `infra-copilot` skill — `setup`, `import`, `add`, `status` — runs on the same small
protocol: the **actor split**, the **handoff block**, the **resume scan**, and the
**preflight**. It lives here once so the action skills stay thin routers and never drift
apart. Read this file whenever a skill says "follow the shared protocol."

## The one idea

**The human is the browser and the keyholder. Everything scriptable is the agent's.**

There is exactly one thing a human must do that an agent cannot: sit at a browser, sign
up for a SaaS, and mint the first credential. Once an HCP token exists (from
`terraform login`), the agent creates workspaces, sets variables, reads plans, imports
resources, and confirms applies **over the API** — no more clicking. The human surface is
three action kinds only:

1. **Sign up** for a service (browser-only).
2. **Mint a credential** in a dashboard (browser-only — no API bootstraps the first token).
3. **Paste a secret** into HCP (browser-only — the agent must never see the plaintext).

Everything else — verifying, creating workspaces, importing, planning — is the agent's.

## Step 0 — read the repo config (AGENT, always first)

Before any resume scan, read `.infra-copilot/config.md` from the current repo and
export the shell vars every check depends on. Full schema + export block:
[`config.md`](config.md). If the file is missing, emit the handoff block, show the schema,
offer to scaffold from [`config.md.example`](config.md.example),
and wait — never guess org/domain/IDs.

## Actors

Every step in [`steps.yaml`](steps.yaml) is tagged with who performs it:

| Tag | Meaning | Behaviour |
|---|---|---|
| **`AGENT`** | Agent runs it (shell, `gh`, `terraform`, HCP API). | Execute. Verify with the step's `check`. Continue on green. |
| **`HUMAN`** | Irreducibly human (signup, dashboard, secret paste). | **Stop.** Emit the handoff block. Wait for `done`. Then run the `check` before continuing. |

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

Every skill here is **idempotent and resumable**. Before doing anything, walk the steps in
this skill's scope (its phase range of [`steps.yaml`](steps.yaml)) top to bottom and run
each step's `check` to discover where things already stand. Resume at the first step whose
check is red. An all-green scope means "already done, nothing to do."

```text
for step in scope(steps.yaml):
    if run(step.check) is green:  skip, print "✓ {step.id}"
    else:                         resume here
```

Never assume state from memory or a prior session — always re-check. See
[`steps.yaml`](steps.yaml) for the runtime contract (which shell vars to export first).

## Preflight (AGENT)

Confirm the toolbox. All of these are the agent's to install if missing — none need a human.

```sh
terraform version      # ≥ 1.9   — provisioning + import blocks
gh --version           # GitHub CLI — repo ops, Pages, App install checks
jq --version           # JSON wrangling for HCP/Cloudflare/GitHub APIs
curl --version         # HCP + Cloudflare REST
```

These are the human-readable checks; the `preflight` block in [`steps.yaml`](steps.yaml)
enforces the version floor (Terraform ≥ 1.9) programmatically — run those to gate.

Then detect the credential the whole flow pivots on:

```sh
jq -re '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json \
  && echo "HCP token present — agent can drive the API" \
  || echo "No HCP token yet — the first HUMAN step will mint one"
```
