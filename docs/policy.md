# Restricting what infra-copilot can do

This plugin drives three provider APIs, runs Terraform against remote state, and reads a
credential file. None of that is constrained by the plugin itself — restriction is the
host's job, and the hosts differ enormously in what they offer.

## What the plugin actually invokes

The rules below are derived from the shipped manifest rather than guessed. Every command
that appears in `references/steps.yaml` or `references/checks/`:

| Command | Verbs used |
|---|---|
| `terraform` | `fmt`, `init`, `login`, `plan`, `validate`, `version` |
| `mise` | pin reads, `install --dry-run`, `lock` |
| `gh` | `api`, `auth status`, `auth login`, `--version` |
| `jq`, `curl`, `mktemp` | JSON handling, provider REST, temp files |
| `cf-terraforming` | Cloudflare import generation only |
| `gcloud` | conditional, only when `terraform/gcp` exists |
| `git` | `rev-parse`, `--no-optional-locks status`, `add mise.toml mise.lock` |

**`terraform apply` and `terraform destroy` appear nowhere.** `setup` ends at green
*speculative* plans, `status` is read-only, and `import` warns that applying before
adoption clobbers live resources. Applying is always a human action through HCP's own
review, which is why the profiles deny both outright — denying them costs nothing and
removes the worst outcome.

## The HCP token: what "the agent never sees secrets" does and does not cover

`protocol.md` states the model plainly: the human signs up, mints credentials, and pastes
secrets into HCP, and the agent must never see that plaintext. That holds for the
**Cloudflare API token** and the **GitHub App credentials** — they go from a browser into
HCP workspace variables, and the agent only ever verifies their presence over the API.

It does **not** hold for the HCP token itself. Phase 0 has the human run
`terraform login`, and every later step reads the result:

```sh
export HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' \
  ~/.terraform.d/credentials.tfrc.json)
```

So the HCP token is in the agent's environment by design — that is the pivot the whole
workflow turns on, and there is no version of this plugin that drives the HCP API without
it.

**The profiles here allow that read, deliberately.** Denying
`Read(~/.terraform.d/credentials.tfrc.json)` breaks every HCP step from phase 0 onward.
The alternative — requiring the operator to `export HCP_TOKEN` by hand each session —
moves the same secret into the same environment through a different door, so it buys
appearance rather than safety. If your threat model needs the token out of the agent's
reach entirely, this plugin is not the right tool for that repo.

What the profiles do instead is bound the blast radius: the token can drive the HCP API,
and it cannot apply Terraform.

## Claude Code

The only host here with a mature allow/ask/deny grammar and org-level managed settings.

**Precedence**, highest first: managed settings → CLI flags →
`.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json`.
Rules evaluate **deny → ask → allow**, first match wins.

Two profiles ship, both intended to be read and edited before use:

| Profile | For |
|---|---|
| [`claude-code.json`](../templates/managed-settings/claude-code.json) | normal use: plan yes, apply never |
| [`claude-code-status-only.json`](../templates/managed-settings/claude-code-status-only.json) | auditing a live repo: narrowed to `status` |

Note that `Bash(terraform apply *)` does **not** match a bare `terraform apply` — the
wildcard needs an argument. Both profiles therefore deny the bare and argument forms of
`apply` and `destroy` separately. It is worth checking your own rules for the same trap.

The legacy `.claude/infra-copilot.local.md` fallback is **not** denied. `config.md` and the
README both name it as a supported migration path, so denying it would stop `setup` and
`status` loading any configuration in a repo that still uses it. Retire the fallback first
if you want it blocked.

Managed settings live at a platform-specific **file**:

| Platform | Path |
|---|---|
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux / WSL | `/etc/claude-code/managed-settings.json` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` |

Check your Claude Code version's own documentation before deploying; run `/status` in a
session to see which layers are active.

> **Merge, do not copy.** If that file already exists it carries your other permission
> rules, hooks and marketplace restrictions. Copying a template over it drops all of
> them. Back it up, then merge these keys and arrays into it — the same rule this document
> imposes on any automated installer.

**Neither profile sets `allowManagedPermissionRulesOnly`,** deliberately. That field locks
the rule set, so any command the list misses becomes a hard block rather than a prompt —
and the status scan alone runs twelve `curl`-based checks plus a shipped shell script.
Exercise a profile against a real bootstrap first, then add the lock if you want it.

## What a command-level grammar cannot express

The status-only profile **reduces blast radius; it does not enforce read-only**, and no
arrangement of these rules would.

This plugin reaches providers through `gh api` and `curl`, and its own runbooks use
`gh api -X PATCH`, `gh api -X PUT`, `curl -X POST` and `curl -X PATCH`. A prefix-matching
grammar cannot separate a GET from a PATCH *inside* those commands, so permitting `status`
to read at all permits writing through the same verb. The `-X` denies in the profile stop
the literal forms this plugin documents — a speed bump, not a boundary.

Enforced read-only needs a **tool-level** boundary instead: an agent that has no write
tools at all, which is what the read-only subagent in
[`docs/roadmap.md`](roadmap.md) (#19) would provide. Until that exists, treat the
status-only profile as narrowing rather than proof.

## Other hosts

I have not verified per-plugin restriction on the other supported hosts, and would rather
say so than describe a grammar I have not exercised. What is known:

- **OpenCode** has a tri-state `permission` block (`allow`/`ask`/`deny`) in
  `opencode.json` plus per-agent tool maps. The shape of the Claude profiles translates,
  but the key names do not — consult OpenCode's own documentation.
- **Codex CLI** and **Antigravity** expose no per-plugin deny grammar that I could
  confirm. Treat restriction there as uninstall-only until proven otherwise:
  `codex plugin remove` / `agy plugin uninstall`.

**Do not auto-write host configuration.** If a future skill offers to install any of
this, it must back up first, merge rather than overwrite, prompt opt-in, and be idempotent
on re-run. Codex's own trust prompt is the right surface for Codex; writing
`~/.codex/config.toml` on a user's behalf is not.

## Related

- `docs/roadmap.md` — what is deliberately unbuilt, including the read-only subagent that
  would enforce the same `status` guarantee at the agent layer instead of the host layer.
