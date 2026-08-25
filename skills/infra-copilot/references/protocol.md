<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:95ef654407405dec296437cd57be8a6faae85fa03c852e108d92f8c8b4570b9e
Source-Hash: blake3:610330dd4563b654254941e6f2a7b8e5ab26863113f033de88d2dbbfb6a9063e
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

Before any resume scan, read `.infra-copilot/config.md` from the current repo. If it is
missing but `.claude/infra-copilot.local.md` exists, use that legacy file for this run and
offer to copy it unchanged to the agent-neutral path. If both files are missing, emit the
handoff block, show the schema, offer to scaffold from
[`config.md.example`](config.md.example), and wait — never guess org/domain/IDs. Once a
config is loaded, export the shell vars every check depends on. Full schema, migration
rules, and export block: [`config.md`](config.md). On a cold run, `hcp-login` creates the
credential file after this initial export; as soon as that step's check turns green,
repeat the `HCP_TOKEN` export from `config.md` before checking `hcp-signup` or any later
HCP step.

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
terraform version      # provisioning + import blocks
gh --version           # GitHub CLI — repo ops, Pages, App install checks
jq --version           # JSON wrangling for HCP/Cloudflare/GitHub APIs
curl --version         # HCP + Cloudflare REST
```

**Pinned, not merely present.** A tool that runs is not the same as the tool the repo
agreed on. Two contributors can both clear a `>= 1.9` floor on Terraform 1.9 and 1.15 and
get plans that render differently. So the `preflight` block in [`steps.yaml`](steps.yaml)
asserts *parity with the repo's pin* where one exists, and falls back to a floor only where
it does not. `mise` is the default mechanism (`mise.toml` + `mise.lock`); any manager that
yields version parity satisfies the contract, so the checks never test for mise itself.
See [`docs/setup.md`](docs/setup.md#6-local-development) and
[`decisions.md.example`](decisions.md.example).

Report three states, not two — "present" hides the interesting case:

| State | Meaning | Report as |
|---|---|---|
| pinned, matches | repo pin and running binary agree | `terraform 1.15.9 ✓ (pinned)` |
| pinned, differs | drift — the reviewed plan may not be the applied one | `terraform 1.13.0 ✗ (pinned 1.15.9)` |
| not pinned | no decision recorded yet; floor applies | `terraform 1.15.9 ⚠ (unpinned)` |

Two traps make this easy to get wrong, and both produce a false green:
`mise current <tool>` exits **0 even when nothing is pinned** (it only warns), and a mise
shim with no version set makes the tool unrunnable. A naive `if mise current X; then
compare` therefore takes the pinned branch, compares empty to empty, and passes. Read the
version first, require it non-empty, *then* branch.

Then detect the credential the whole flow pivots on:

```sh
jq -e '.credentials["app.terraform.io"].token | strings | length > 0' \
  ~/.terraform.d/credentials.tfrc.json >/dev/null 2>&1 \
  && echo "HCP token present — agent can drive the API" \
  || echo "No HCP token yet — the first HUMAN step will mint one"
```
