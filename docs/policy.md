# Restricting what infra-copilot can do

This plugin drives three provider APIs, runs Terraform against remote state, and reads a
credential file. None of that is constrained by the plugin — restriction is the host's
job, and this page is about what you can and cannot achieve there.

**No permission profile ships with this plugin, deliberately.** An earlier draft included
two ready-to-deploy Claude Code profiles; they were dropped because a file that looks
authoritative invites being deployed unread, and the guarantees such a file appears to
offer are weaker than its name implies. The reasons are below, and they are the useful
part. Copy what fits your threat model, having read why each rule does or does not bite.

## What the plugin invokes

The **provider-facing** tools that appear in `references/steps.yaml` and
`references/checks/`. Not an exhaustive list of every process spawned — see
[the compound-command problem](#the-compound-command-problem):

| Command | Verbs used |
|---|---|
| `terraform` | `fmt`, `init`, `login`, `plan`, `validate`, `version` |
| `mise` | pin reads, `install --dry-run`, `lock` |
| `gh` | `api`, `auth status`, `auth login`, `--version` |
| `jq`, `curl` | JSON handling, provider REST |
| `cf-terraforming` | Cloudflare import generation only |
| `gcloud` | conditional, only when `terraform/gcp` exists |
| `git` | `rev-parse`, `--no-optional-locks status`, `add mise.toml mise.lock` |

**`terraform apply` and `terraform destroy` appear nowhere.** `setup` ends at green
*speculative* plans, `status` is read-only, and `import` warns that applying before
adoption clobbers live resources. Applying is always a human action through HCP's own
review.

## The rules that actually bite

Two kinds of rule work regardless of how the plugin composes a command:

**Non-`Bash` rules.** `Skill()`, `Edit()`, `Write()` and `Read()` match on their own
terms, so these are the load-bearing ones:

```json
{
  "permissions": {
    "deny": [
      "Skill(infra-copilot:setup)",
      "Skill(infra-copilot:import)",
      "Skill(infra-copilot:add)",
      "Edit(**)",
      "Write(**)",
      "Read(./.env)",
      "Read(./**/.env)",
      "Read(./**/*.tfvars)",
      "Read(./**/*.tfvars.json)"
    ]
  }
}
```

Note the recursion: this plugin's Terraform roots are `terraform/cloudflare` and
`terraform/github`, so a root-only `Read(./terraform.tfvars)` leaves
`terraform/cloudflare/terraform.tfvars` readable.

**`Bash` denies.** These stop the agent composing a command directly:

```json
{
  "permissions": {
    "deny": [
      "Bash(terraform apply)",
      "Bash(terraform apply *)",
      "Bash(terraform destroy)",
      "Bash(terraform destroy *)"
    ]
  }
}
```

**Both forms are needed.** `Bash(terraform apply *)` requires an argument after the verb,
so it does not match a bare `terraform apply` — which is the common invocation. The same
trap applies to any rule you write in the `verb *` shape: `Bash(terraform version)` does
not match `terraform version -json`, which this plugin's preflight runs.

## The compound-command problem

A `Bash` **allow**-list is close to inoperative here, because the manifest's checks are
compound shell strings rather than single commands. A representative one:

```sh
ver=$(terraform version -json 2>/dev/null | jq -r '.terraform_version // empty');
pin=$(mise config get --file ./mise.toml tools.terraform | tr -d '[:space:]')
```

That does not begin with a command name, and it spawns `terraform`, `jq`, `mise` and `tr`
in one invocation. A prefix-matching rule cannot reliably gate it. Enumerating the
utilities such checks use — `mktemp`, `grep`, `sed`, `awk`, `tr`, `rm` — would grant `rm`
and `sed` broadly and gate nothing in exchange.

So: use `Bash` rules to *deny* specific dangerous verbs, and do not expect an allow-list
to bound what the plugin can run.

> **`allowManagedPermissionRulesOnly` is a trap here.** It locks the rule set, so any
> command your list misses becomes a hard block rather than a prompt. The `status` scan
> alone runs twelve `curl`-based checks and launches a shipped shell script. If you want
> the lock, add it only after a real bootstrap has run under your rules.

## Read-only cannot be enforced at the command level

It is tempting to build a profile that permits `infra-copilot:status` and nothing else.
`status` promises to change nothing and works at it — reading run status through the HCP
API rather than running `plan`, using `git --no-optional-locks` so it leaves git's index
alone.

That promise cannot be enforced with command rules. This plugin reaches providers through
`gh api` and `curl`, and its own runbooks use `gh api -X PATCH`, `gh api -X PUT`,
`curl -X POST` and `curl -X PATCH`. A prefix-matching grammar cannot separate a GET from a
PATCH *inside* those commands, so permitting `status` to read permits writing through the
same verb. `--no-optional-locks` suppresses optional locking; it does not make `git`
read-only, so `reset`, `clean` and `push` all match a `git --no-optional-locks *` rule.

Denying the literal `-X` forms is a speed bump, not a boundary.

Enforced read-only needs a **tool-level** boundary instead — an agent with no write tools
at all. That is the read-only subagent tracked in [`roadmap.md`](roadmap.md) (#19), and it
is the only mechanism that makes `status`'s central promise something a host enforces
rather than something the skill asserts about itself.

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

The HCP token is in the agent's environment by design — it is the pivot the whole workflow
turns on, and no version of this plugin drives the HCP API without it.

**Do not deny that read.** It breaks every HCP step from phase 0 onward. Requiring the
operator to `export HCP_TOKEN` by hand each session moves the same secret into the same
environment through a different door, so it buys appearance rather than safety. If your
threat model needs the token out of the agent's reach entirely, this plugin is not the
right tool for that repository.

## Claude Code specifics

Precedence, highest first: managed settings → CLI flags → `.claude/settings.local.json` →
`.claude/settings.json` → `~/.claude/settings.json`. Rules evaluate **deny → ask → allow**,
first match wins. Run `/status` in a session to see which layers are active.

Managed settings live at a platform-specific **file**:

| Platform | Path |
|---|---|
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux / WSL | `/etc/claude-code/managed-settings.json` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` |

Check your Claude Code version's own documentation before deploying — these paths and the
managed-only field names are its to change, not this plugin's.

> **Merge, do not copy.** If that file already exists it carries your other permission
> rules, hooks and marketplace restrictions. Writing a fresh document over it drops all of
> them. Back it up, then merge.

## Other hosts

Per-plugin restriction on the other supported hosts is **unverified**, and saying so beats
describing a grammar nobody here has exercised:

- **OpenCode** has a tri-state `permission` block (`allow`/`ask`/`deny`) in
  `opencode.json` plus per-agent tool maps. The shape above translates; the key names do
  not. Consult OpenCode's documentation.
- **Codex CLI** and **Antigravity** expose no per-plugin deny grammar that could be
  confirmed. Treat restriction there as uninstall-only until proven otherwise:
  `codex plugin remove` / `agy plugin uninstall`.

**Do not auto-write host configuration.** If a future skill offers to install any of this,
it must back up first, merge rather than overwrite, prompt opt-in, and be idempotent on
re-run. Codex's own trust prompt is the right surface for Codex; writing
`~/.codex/config.toml` on a user's behalf is not.
