<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:1777429c8e1d4d5c083371480eb4d072f7fb322c7d89c4f73d72ed9efa8a6c17
Source-Hash: blake3:4e6a6c5c98165b144cbbc4fc83b2198714bd7f13b2acad454787d2e39eeedbd7
Schema-Version: v1
-->


# The infra-copilot protocol (shared)

Every `infra-copilot` skill — `setup`, `import`, `add`, `status` — runs on the same small
protocol: the **actor split**, the **handoff block**, the **resume scan**, and the
**preflight**. It lives here once so the action skills stay thin routers and never drift
apart. Read this file whenever a skill says "follow the shared protocol."

## The one idea

**The human is the browser, keyholder, and reviewer of executable repository trust.
Everything else scriptable is the agent's.**

Human steps are limited to actions that require browser identity, secret custody, or an
independent trust decision. Once an HCP token exists (from `terraform login`), the agent
creates workspaces, sets variables, reads plans, imports resources, and confirms applies
**over the API** — no more clicking. The human surface is four action kinds only:

1. **Sign up** for a service (browser-only).
2. **Mint a credential** in a dashboard (browser-only — no API bootstraps the first token).
3. **Paste a secret** into HCP (browser-only — the agent must never see the plaintext).
4. **Choose and review repository tool pins** before trusting executable `mise.toml`
   behavior; the agent that proposes a config must not approve its own trust boundary.

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
| **`HUMAN`** | Irreducibly human (signup, dashboard, secret paste, executable-config review). | **Stop.** Emit the handoff block. Wait for `done`. Then run the `check` before continuing. |

### The handoff block

When a step is `HUMAN`, do **not** guess or fake it. Stop and print exactly this shape, then wait:

```text
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

`setup` has one cold-start ordering rule: first confirm that the `mise` command itself is
available, then begin its resume scan with phase 0's `toolchain-pin` step. Do not run the
pin-dependent preflight entries (`mise`'s full contract or the `terraform`/`gh`/`jq` tool
checks) before that step has established committed pins. Once `toolchain-pin` is green,
run the full preflight and continue the resume scan at `hcp-login`. This keeps the
fail-fast gate while giving a missing toolchain an owned, resumable step. `status` remains
read-only: it reports the same failed step but never executes its `run`.

```text
for step in scope(steps.yaml):
    rc = run(step.check)
    if rc == 0:
        skip, print "✓ {step.id}"
    elif not step.tri_state:
        resume here                     # two-state: any non-zero is red
    elif rc == 1:
        resume here
    elif rc == 2:
        report "? {step.id} — could not verify: <stderr>", STOP, do NOT run step.run
    else:
        report "? {step.id} — unexpected check exit code {rc}", STOP, do NOT run step.run
```

Never assume state from memory or a prior session — always re-check. See
[`steps.yaml`](steps.yaml) for the runtime contract (which shell vars to export first).

### Exit code 2 — could not verify

A check may exit **2** to mean *the evidence could not be read* — a missing export, an
unauthenticated CLI, a failed API call — as distinct from exit 1, *the thing being checked
is wrong*.

**This applies only to steps carrying `tri_state: true` in
[`steps.yaml`](steps.yaml).** Every other check is two-state: any non-zero means red,
full stop. That distinction is not cosmetic — ordinary tools already use 2 for their own
reasons. `jq` exits 2 when its input file does not exist, which is exactly the cold-start
state of `hcp-login`'s check, so treating 2 as "cannot verify" everywhere would refuse to
run the login step that creates the file and would block every greenfield bootstrap.

For a `tri_state` step, treat 2 as neither green nor red:

- Report the step as `?` with the check's own stderr, which names the cause.
- **Do not execute the step's `run`.** A `run` describes how to fix a real failure; on a 2
  nothing has been shown to be broken, so following it can do harm. `status-check-context`
  is the clearest case: its `run` tells you to edit branch protection, which is exactly the
  wrong instruction when the only problem is that `gh` is not logged in.
- Fix the named precondition, then re-run the scan from the same step.

For a `tri_state` step only exit **1** means resume-and-fix. Any other unexpected code is
treated like a 2 — reported, not acted on — because a code the check does not define is
not evidence about the repository either. A two-state step keeps the simple rule: non-zero
is red.

## Preflight (AGENT)

Confirm the toolbox. All of these are the agent's to install if missing — none need a human.

```sh
terraform version      # provisioning + import blocks
gh --version           # GitHub CLI — repo ops, Pages, App install checks
jq --version           # JSON wrangling for HCP/Cloudflare/GitHub APIs
curl --version         # HCP + Cloudflare REST
mise --version         # reads committed pins and enforces the lockfile
```

**Installed is not activated.** `mise install` downloads the pinned tools without
putting them on `PATH`. Every check below invokes a bare binary, so activate the
environment first (`eval "$(mise activate bash)"`, or the hook for the running shell) or
run each command through `mise exec --`. Skipping this compares a system binary against
the repository pin and reports drift that does not exist.

**Pinned, not merely present.** A tool that runs is not the same as the tool the repo
agreed on. Two contributors can both clear a `>= 1.9` floor on Terraform 1.9 and 1.15 and
get plans that render differently. So the `preflight` block in [`steps.yaml`](steps.yaml)
asserts *parity with the repo's committed pin*. The default manifest requires
`mise.toml` + `mise.lock` and reads each exact key with `mise config get --file`; it never
uses the active mise environment as evidence of what the repository committed.
See [`docs/setup.md`](docs/setup.md#6-local-development) and
[`decisions.md.example`](decisions.md.example).

Report the committed pin and whether the running binary matches it:

| State | Meaning | Report as |
|---|---|---|
| pinned, matches | repo pin and running binary agree | `terraform 1.15.9 ✓ (pinned)` |
| pinned, differs | drift — the reviewed plan may not be the applied one | `terraform 1.13.0 ✗ (pinned 1.15.9)` |
| pin missing | repository contract is incomplete | `terraform 1.15.9 ✗ (pin missing)` |

`mise current <tool>` is deliberately forbidden here. It reports the active version,
which can come from user/global configuration and can be empty even when it exits zero.
Read `./mise.toml` explicitly, require a non-empty exact value, and compare the binary to
that value. If a consuming repo chooses another manager, its manifest checks must read
that manager's committed pin directly.

For `setup`, phase 0's `toolchain-pin` HUMAN step owns bootstrapping missing `mise.toml`
and `mise.lock` from the constrained example in
[`docs/setup.md`](docs/setup.md#6-local-development). Run its check, follow the handoff
protocol if red, and only then run the pin-dependent preflight checks. After the Terraform
check passes, export the value needed by Phase 1:

```sh
export TERRAFORM_VERSION=$(mise config get --file ./mise.toml tools.terraform)
```

Do not perform this export during config loading: a fresh repository has not established
the toolchain contract yet. `status` remains read-only and reports missing pin files
instead of creating them.

Then detect the credential the whole flow pivots on:

```sh
jq -e '.credentials["app.terraform.io"].token | strings | length > 0' \
  ~/.terraform.d/credentials.tfrc.json >/dev/null 2>&1 \
  && echo "HCP token present — agent can drive the API" \
  || echo "No HCP token yet — the first HUMAN step will mint one"
```
