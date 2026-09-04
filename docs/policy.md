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
| [`claude-code-status-only.json`](../templates/managed-settings/claude-code-status-only.json) | auditing a production repo: `status` and nothing else |

The status-only profile is the more interesting one. `status` promises to change nothing
and works to keep that promise — reading run status through the HCP API rather than
running `terraform plan`, and using `git --no-optional-locks` so it leaves git's index
alone. That profile turns a promise the skill makes about itself into something the host
enforces.

Managed settings live at platform-specific paths — `/Library/Application
Support/ClaudeCode/managed-settings.json` on macOS, `/etc/claude-code/` on Linux,
`C:\Program Files\ClaudeCode\` on Windows — and support managed-only fields such as
`allowManagedPermissionRulesOnly`, which the shipped profiles set. Check your Claude Code
version's own documentation for the current path list before deploying; run `/status` in a
session to see which layers are active.

> **`allowManagedPermissionRulesOnly` locks the rule set.** An incomplete allow list then
> blocks work rather than merely failing to restrict it. Deploy to one machine first.

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
