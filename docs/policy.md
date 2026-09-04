# Restricting what infra-copilot can do

**Host permission rules cannot meaningfully constrain this plugin.** That is the
conclusion of trying, and it is worth more than the profile this page used to ship.

If you need to bound what infra-copilot can do, the boundary has to be *tool-level* or
*sandbox-level*, not command-level. The rest of this page is the evidence, because every
bypass below is one the plugin's own documentation supplies — so anyone writing rules
without knowing them will believe they have protections they do not have.

## What the plugin invokes

The provider-facing tools in `references/steps.yaml` and `references/checks/`:

| Command | Verbs used |
|---|---|
| `terraform` | `fmt`, `init`, `login`, `plan`, `validate`, `version` |
| `mise` | pin reads, `install --dry-run`, `lock`, **`exec --`** |
| `gh` | `api`, `auth status`, `auth login`, `--version` |
| `jq`, `curl` | JSON handling, provider REST |
| `cf-terraforming` | Cloudflare import generation only |
| `gcloud` | conditional, only when `terraform/gcp` exists |
| `git` | `rev-parse`, `--no-optional-locks status`, `add` |

`terraform apply` and `terraform destroy` appear nowhere: `setup` ends at green
*speculative* plans, `status` is read-only, `import` warns that applying before adoption
clobbers live resources. Applying is a human action through HCP's own review.

That makes `Bash(terraform apply)` look like a cheap, effective guard. It is not.

## Four bypasses, all documented by this plugin

**1. `mise exec --` wraps anything.** `protocol.md` instructs the agent to *"run each
command through `mise exec --`"*, because comparing a system binary against a repo pin is
the bug that convention exists to prevent. So the recommended invocation style is:

```sh
mise exec -- terraform apply     # matches Bash(mise *), not Bash(terraform apply)
```

Any `Bash(mise *)` grant defeats every Terraform deny. Denying `mise` instead breaks the
toolchain contract that #7 built the whole preflight around.

**2. Apply is a REST call.** `docs/hcp-api.md` ships the recipe:

```sh
curl -s -X POST "https://app.terraform.io/api/v2/runs/$RUN_ID/actions/apply" ...
```

With an HCP token authorised to apply — which phase 0 puts in the agent's environment —
that applies infrastructure without invoking Terraform at all. Denying the CLI verbs does
not deny applying. And `curl` cannot be denied: twelve checks depend on it.

**3. `Read()` rules do not govern Bash.** `Read(./**/*.tfvars)` constrains the **Read
tool**. Any subprocess reads the file regardless:

```sh
jq -R . terraform/cloudflare/secrets.tfvars    # matches Bash(jq *)
```

`jq` cannot be denied either — twenty-eight checks use it.

**4. A `Bash` allow-list cannot match the checks anyway.** They are compound shell strings
that do not begin with a command name:

```sh
ver=$(terraform version -json 2>/dev/null | jq -r '.terraform_version // empty');
pin=$(mise config get --file ./mise.toml tools.terraform | tr -d '[:space:]')
```

One invocation, five processes, no leading command name. Enumerating what such checks spawn
would grant `rm` and `sed` broadly and gate nothing.

## What that leaves

| Rule | Holds? |
|---|---|
| `Skill(infra-copilot:setup)` etc. | **Yes** — skill invocation is not a Bash path |
| `Bash(terraform apply)` | No — `mise exec --`, and REST |
| `Read(./**/*.tfvars)` | No — any Bash subprocess |
| `Edit(**)` / `Write(**)` | No — Bash writes files |
| A curated `Bash` allow-list | No — compound checks |

**Only `Skill()` denies are robust.** They are genuinely useful: denying
`Skill(infra-copilot:setup)`, `:import` and `:add` while allowing `:status` stops the
*workflows* that change things, which is a real reduction even though it does not stop a
determined or confused agent reaching the same effects by hand.

Write the `Bash` and `Read` denies too if you like — they raise the cost of an accident.
Do not describe them to anyone as a boundary.

> **Do not set `allowManagedPermissionRulesOnly`.** It locks the rule set, so any command
> your list misses becomes a hard block. The `status` scan alone runs twelve `curl`-based
> checks and launches a shipped shell script. You would be trading a guarantee you do not
> get for an outage you do.

## What would actually work

- **Tool-level**: an agent with no write tools at all. That is the read-only subagent in
  [`roadmap.md`](roadmap.md) (#19), and it is the only mechanism that makes `status`'s
  change-nothing promise something a host enforces rather than something the skill asserts
  about itself.
- **Sandbox-level**: filesystem and network isolation, so `jq` cannot read a path and
  `curl` cannot reach an endpoint regardless of which command wraps it. Outside this
  plugin's control, and the right layer for the secret-file and REST-apply cases.
- **Credential scoping**: the durable answer for apply. An HCP token without apply
  permission cannot apply, whatever command is used. That is a provider-side control and
  strictly stronger than anything expressible in host rules.

## The HCP token: what "the agent never sees secrets" does and does not cover

`protocol.md` states the model: the human signs up, mints credentials, and pastes secrets
into HCP, and the agent must never see that plaintext. That holds for the **Cloudflare API
token** and the **GitHub App credentials** — browser into HCP workspace variables, and the
agent only verifies their presence over the API.

It does **not** hold for the HCP token. Phase 0 has the human run `terraform login`, and
every later step reads the result:

```sh
export HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' \
  ~/.terraform.d/credentials.tfrc.json)
```

That token is in the agent's environment by design — the pivot the workflow turns on. Do
not deny the read; it breaks every HCP step, and a manual `export` puts the same secret in
the same environment through another door.

**Scope the token instead.** This is the one place where a real control exists: an HCP
token that cannot apply removes bypass 2 above at the source.

## Claude Code specifics

Precedence, highest first: managed settings → CLI flags → `.claude/settings.local.json` →
`.claude/settings.json` → `~/.claude/settings.json`. Rules evaluate **deny → ask → allow**,
first match wins. `/status` shows the active layers.

Managed settings live at a platform-specific **file**:

| Platform | Path |
|---|---|
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux / WSL | `/etc/claude-code/managed-settings.json` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` |

Check your Claude Code version's own documentation — these paths and the managed-only
field names are its to change, not this plugin's.

> **Merge, do not copy.** If that file exists it carries your other rules, hooks and
> marketplace restrictions. Writing a fresh document over it drops them. Back it up first.

Two matching traps worth knowing whatever you write: `Bash(terraform apply *)` does **not**
match a bare `terraform apply` — the wildcard needs an argument — and
`Bash(terraform version)` is exact, so it does not match `terraform version -json`, which
preflight runs.

## Other hosts

Unverified, and saying so beats describing a grammar nobody here has exercised.
**OpenCode** has a tri-state `permission` block plus per-agent tool maps — the per-agent
map is the interesting one, since it is tool-level rather than command-level. **Codex CLI**
and **Antigravity** expose no per-plugin deny grammar that could be confirmed; treat
restriction there as uninstall-only.

**Do not auto-write host configuration.** Any future skill offering to install this must
back up, merge rather than overwrite, prompt opt-in, and be idempotent. Codex's trust
prompt is the right surface for Codex.
