<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:1d89736056292dc4095a041dee74ad4c2d09afd534abacf58e5a9b2f9f9f521e
Source-Hash: blake3:9e1edb5b37d8b4776d580dd73226e92ecbfe169e516fc7a12021203d4380006d
Schema-Version: v1
-->


# The infra-copilot protocol (shared)

Every `infra-copilot` skill — `setup`, `import`, `add`, `status` — runs on the same small
protocol: the **actor split**, the **handoff block**, the **resume scan**, and the
**preflight**. It lives here once so the action skills stay thin routers and never drift
apart. Read this file whenever a skill says "follow the shared protocol."

## The one idea

**The human is the browser, keyholder, and reviewer of executable repository trust.
The agent owns everything that does not require those identities or decisions.**

Human steps are limited to actions that require browser identity, secret custody, or an
independent trust decision. The human surface is five action kinds only:

1. **Sign up** for a service (browser-only).
2. **Mint a credential** in a dashboard (browser-only — no API bootstraps the first token).
3. **Paste a secret** into the secret store (HCP workspace variables or GitHub Actions
   secrets, depending on backend mode — the agent must never see the plaintext).
4. **Choose and review repository tool pins** before trusting executable `mise.toml`
   behavior; the agent that proposes a config must not approve its own trust boundary.
5. **Run a privileged mutation after credential narrowing** (HCP mode: workspace changes
   using the canonical helper; object-storage mode: environment approval configuration).

Everything else — repository changes, verification, imports, and plans — is the agent's.

## Step 0 — read the repo config (AGENT, always first)

Before any resume scan, read `.infra-copilot/config.md` from the current repo. If it is
missing but `.claude/infra-copilot.local.md` exists, use that legacy file for this run and
offer to copy it unchanged to the agent-neutral path. If both files are missing, emit the
handoff block, show the schema, offer to scaffold from
[`config.md.example`](config.md.example), and wait — never guess org/domain/IDs. If a
config already exists and you are re-scaffolding, preserve the region between its
`infra-copilot:customization` markers verbatim and hand off rather than guess when those
markers are missing or unbalanced: [`config.md`](config.md#re-scaffolding-an-existing-config). Once a
config is loaded, export the shell vars every check depends on — including `BACKEND`, which
gates which steps apply. Full schema, migration rules, and export block: [`config.md`](config.md).

On a cold HCP-mode run, `hcp-login` creates the credential file after this initial export;
as soon as that step's check turns green, repeat the `HCP_TOKEN` export from `config.md`
before checking `hcp-signup` or any later HCP step. In object-storage mode, no HCP
credential is needed — cloud provider auth happens via Workload Identity Federation or
environment variables.

## Actors

Every step in [`steps.yaml`](steps.yaml) is tagged with who performs it:

| Tag | Meaning | Behaviour |
|---|---|---|
| **`AGENT`** | Agent runs it (shell, `gh`, `terraform`, HCP API). | Execute. Verify with the step's `check`. Continue on green. |
| **`HUMAN`** | Requires signup, dashboard identity, secret custody, executable-config review, or post-handoff HCP authority intentionally withheld from the agent. | **Stop.** Emit the handoff block. Wait for `done`. Then run the `check` before continuing. |

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

### Asking a decision

The handoff block above unblocks a step: it names work only a human can do and waits for
`done`. A **decision** is different — the answer changes what the agent does next, and
the answers are enumerable. Which provider flavor to adopt (`add`), whether to scaffold a
missing config (`setup`), whether a discovered resource is adopted or excluded
(`import`): each is a choice, not a handoff.

Ask exactly one logical decision and wait for its result. Use the host's native question
tool only when that named tool is currently declared **and** allowed **and** its
capability record in [`hosts.md`](hosts.md) supports the request's mode and choice count.
Otherwise render the identical request as text.

The ceiling counts **the choices you send**. Where `hosts.md` records custom input as
`host-supplied` the tool appends `Other` itself and you must not list one, so three
explicit options is three choices; everywhere else you send `Other` and it counts.

Two consequences of that rule worth stating, because they are the ones that bite:

- The tool names differ per host — `AskUserQuestion`, `request_user_input`,
  `ask_question`, `question` — so never name one in a skill body. Read
  [`hosts.md`](hosts.md) for the running host and use what it lists, or fall back.
- A mode recorded as absent or `not recorded` means fall back, not improvise — a
  multi-select request on a host recorded for binary and single is a text question.
  `not recorded` **custom input** never forces the fallback; it only means you supply
  `Other` yourself and count it.

The text fallback is the same request, rendered:

```text
┌─ DECISION NEEDED ─────────────────────────────────
│ Question: <one line — the single decision>
│ Why:      <what this changes downstream>
│   1. <option> — <consequence>
│   2. <option> — <consequence>
│   3. Other — enter a custom response
│ Reply with <one number | as many numbers as apply, comma-separated>, or your own answer.
└───────────────────────────────────────────────────
```

The reply line is **mode-sensitive**: a single-select decision asks for one number, a
multi-select decision asks for as many as apply. Multi-select is the mode most likely to
reach this block — Codex is recorded for binary and single only — and a request that
silently arrives as single-select is a different question from the one asked.

Always offer `Other — enter a custom response` in the fallback, and as an explicit choice
on any host whose custom input is not `host-supplied`. A decision the agent forces into
its own list is a decision it made.

## Resume protocol

Every skill here is **idempotent and resumable**. Before doing anything, walk the steps in
this skill's scope (its phase range of [`steps.yaml`](steps.yaml)) top to bottom and run
each step's `check` to discover where things already stand. Resume at the first step whose
check is red. An all-green scope means "already done, nothing to do."

Phase 6 is parameterized rather than GCP-specific. Export
`ADDITIONAL_PROVIDER_NAMES` and the flattened `ADDITIONAL_PROVIDER_MISE_TOOLS`, then run
`new-provider-inventory` once; that manifest check catches an extra Terraform leaf with
no durable adoption record, an unclassified non-bootstrap mise pin, or an explicitly
marked provider tool omitted from the declarations. Provider pins use
`# infra-copilot:provider-cli <key>` and unrelated pins use
`# infra-copilot:general-tool <key>`, so omissions are detectable without putting
general-purpose repository tools in the provider inventory.
Scaffold and verify the decision and leaf for every entry, run every applicable provider
toolchain trust gate, and only then walk each entry's remaining `new-provider-*` steps.
This ordering prevents a provider CLI declared under a later entry from being executed
before its HUMAN review. On `add` and `status`, when inventory shows a provider entry
whose toolchain gate is not yet green, run only the system `mise --version` check, the
inventory, and that entry's Phase 6 checks through `new-provider-toolchain` before the
full mise preflight. The full mise check requires current trust and must not steal this
resumable HUMAN handoff by reporting a generic preflight failure first. Conditional
provider entries also remain inactive because no per-entry `NEW_PROVIDER_MISE_TOOLS` is
exported yet. After all
toolchain gates are green, export each entry in turn and run the complete preflight so
every reviewed provider CLI is version-checked before its runbook commands. An
empty list means the optional phase is not applicable only when the inventory check is
green. When `add` was explicitly invoked to adopt a provider that has no matching entry,
retain the validated requested provider slug as `NEW_PROVIDER` and instantiate
`new-provider-decision` once in bootstrap mode. Leave the other `NEW_PROVIDER*` values
empty so its check stays red. After the HUMAN records the decision and config entry,
reload config and continue the normal per-entry scan. The empty-list shortcut must never
discard an explicit adoption request.

For each entry, `new-provider-toolchain` is applicable only when its `mise_tools` list is
non-empty. The decision records the list before scaffolding, the inventory rejects an
actual provider pin omitted from all entries, and all applicable HUMAN trust gates verify
their declared pins, resolved executable paths, and active mise versions before any
provider CLI command runs. An empty list skips that gate
only when the actual tool inventory confirms no provider pin needs it. The workspace-access step precedes
detailed workspace verification because the plan-only credential cannot read an ungranted
workspace. Its bootstrap check treats only a 404 as expected HUMAN work and keeps network,
authentication, and API failures unverifiable. After the workspace is visible, the next
check independently re-derives its detailed settings, and the separate plan-access check
proves the restored restricted credential can plan but cannot apply or update workspaces.
The access check scopes both repository-derived visibility and Plan requirements to the
current provider while still auditing every visible workspace for apply/update capability. This
lets a later provider reach its own bootstrap handoff without weakening the global
negative-permission audit.

The credential handoff records a real, non-future UTC `credentials_verified_at` in committed config only after
the HUMAN installs every declared variable. `new-provider-plan` accepts or reuses only a
run created after the entire recorded UTC second and the workspace's latest `updated-at`,
so a prior workspace run cannot prove the new least-privilege credential or reconciled
execution settings work.

`setup` has one cold-start ordering rule: first confirm that the `mise` command itself is
available, then begin its resume scan with phase 0's `toolchain-pin` step. Do not run the
pin-dependent preflight entries (`mise`'s full contract or the `terraform`/`gh`/`jq` tool
checks) before that step has established committed pins. Once `toolchain-pin` is green,
run the full preflight, stop for the `HUMAN` `repo-config-sync` step when its check is red, and continue the
resume scan at `hcp-login`. The sync step is a no-op when the consuming repository does
not ship `scripts/sync-config.sh`. This keeps the fail-fast gate while giving a missing
toolchain and repository-specific literal synchronization owned, resumable steps. A
repository with only the legacy config fallback skips synchronization because no canonical
`.infra-copilot/config.md` exists yet.
`status` remains read-only: it reports the same failed step but never executes its `run`.

```text
for step in scope(steps.yaml):
    if step.when and not eval(step.when):
        skip, print "- {step.id} (skipped: backend mode)"
        continue
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

### Conditional steps (`when`)

A step may carry a `when` field — a shell condition that gates whether the step runs at all.
If `when` evaluates false, the step is skipped entirely: no check, no run, no handoff.

```yaml
- id: hcp-login
  when: '[ "$BACKEND" = "hcp" ] || [ -z "$BACKEND" ]'
  # ... rest of step
```

This is how backend-specific steps coexist in one manifest:

- HCP-mode steps use `'[ "$BACKEND" = "hcp" ] || [ -z "$BACKEND" ]'` — run when HCP or default
- Object-storage steps use `'[ "$BACKEND" = "object-storage" ]'` — run only in that mode

The condition runs **before** the check. A skipped step does not count as green or red — it
simply does not exist for this run. The resume scan proceeds to the next step.

Evaluate `when` exactly as written — a shell test expression. The variables it references
(`$BACKEND`, etc.) are exported during Step 0 config loading.

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
# Either source, in terraform's precedence order — see config.md Step 0. A
# file-only test reports "no token" for anyone using TF_TOKEN_app_terraform_io,
# which is the route hcp-apply-scope's plan-only handoff may leave in place.
if [ -n "${TF_TOKEN_app_terraform_io:-}" ] \
  || jq -e '.credentials["app.terraform.io"].token | strings | length > 0' \
       ~/.terraform.d/credentials.tfrc.json >/dev/null 2>&1
then
  echo "HCP token present — agent can drive the API"
else
  echo "No HCP token yet — the first HUMAN step will mint one"
fi
```
