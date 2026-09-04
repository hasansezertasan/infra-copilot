# Restricting what infra-copilot can do

**Claude Code's command-level permission rules cannot meaningfully constrain this
plugin.** That is the conclusion of trying, and it is worth more than the profile this
page used to ship.

Claude Code is the only grammar analysed here. The other hosts are
[unverified](#other-hosts) — and OpenCode's per-agent tool maps are a *tool-level*
mechanism, which is the category this page says can work, so do not read the conclusion as
covering it.

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
clobbers live resources. Applying is *intended* to be a human action through HCP's own
review — but nothing here enforces that, and the host rules below do not either. See
bypass 2.

That makes `Bash(terraform apply)` look like a cheap, effective guard. It is not.

## Six bypasses, all documented by this plugin

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
not deny applying. And `curl` cannot be denied: it is how the manifest's checks reach
every provider API.

**3. `Read()` rules do not govern Bash.** `Read(./**/*.tfvars)` constrains the **Read
tool**. Any subprocess reads the file regardless:

```sh
jq -R . terraform/cloudflare/secrets.tfvars    # matches Bash(jq *)
```

`jq` cannot be denied either — it parses every API response the checks read.

**4. A `Bash` allow-list cannot match the checks anyway.** They are compound shell strings
that do not begin with a command name:

```sh
ver=$(terraform version -json 2>/dev/null | jq -r '.terraform_version // empty');
pin=$(mise config get --file ./mise.toml tools.terraform | tr -d '[:space:]')
```

One invocation, five processes, no leading command name.

**This one is unverified, and may be wrong.** Claude Code documents compound Bash commands
as having their shell-separated segments evaluated independently, which would mean a rule
*can* match a segment of a check like this. I have not exercised the matcher, so treat
bypass 4 as an open question rather than a finding. It does not affect the conclusion:
bypasses 1, 2, 3, 5 and 6 are each about something other than compound matching —
wrapping, REST, the Read tool's scope, the command surface, and subprocess file access.

What does hold regardless is that enumerating what such checks spawn would grant `rm` and
`sed` broadly, which is a poor trade whatever the matcher does.

**5. The slash command is a second entry point.** `commands/infra-setup.md` describes
itself as *"the same procedure, two surfaces"*, and its frontmatter grants broad tools:

```yaml
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
```

Invoking `/infra-setup` does not require Claude to call the `Skill` tool, so
`Skill(infra-copilot:setup)` does not cover it. Every action skill has a matching command
— `/infra-setup`, `/infra-import`, `/infra-add` — so a rule set denying only the skills
leaves the primary invocation path open. If your host exposes a rule type for command
invocation, deny both surfaces; check its documentation rather than assuming one exists.

**6. Secret files are readable by any subprocess.** Worth stating separately from bypass
3: `Read(./.env)` and friends constrain the Read tool, so `cat .env`, `cat .env.local`,
`grep -r secret .` and `jq -R . terraform/github/.env.production` all still work. If you
write Read denies anyway, cover the variants — `./.env`, `./.env.*`, `./**/.env`,
`./**/.env.*`, `./**/*.tfvars`, `./**/*.tfvars.json` — because an exact `./.env` misses
`.env.local` even for direct Read-tool access. Treat them as tidiness, not protection.

## What that leaves

| Rule | Holds? |
|---|---|
| `Skill(infra-copilot:setup)` etc. | No — `/infra-setup` is a second entry point |
| `Bash(terraform apply)` | No — `mise exec --`, and REST |
| `Read(./**/*.tfvars)` | No — any Bash subprocess |
| `Edit(**)` / `Write(**)` | No — Bash writes files |
| A curated `Bash` allow-list | **Unverified** — see bypass 4 |

**Nothing in the table is a boundary**, with one row left open: whether a curated
allow-list can match compound checks depends on segment evaluation, which is bypass 4 and
which I have not exercised. If it does work, a least-privilege allow-list is worth
building — it would still not stop bypasses 1, 2, 3, 5 or 6, but it is not the dead end an
earlier draft of this page called it.

An earlier draft also claimed `Skill()` denies were load-bearing; the command surface is
why that was wrong too.

Write these rules anyway if you like — they raise the cost of an *accident*, which is
worth something when the risk is a confused agent rather than a hostile one. Do not
describe any of them as a boundary, and do not rely on them when pointing this plugin at
production.

> **Think twice about `allowManagedPermissionRulesOnly`.** It stops user and project
> rules being used, so your managed list is the only one that applies. What happens to a
> command your list does not cover depends on the active permission mode — see
> [Claude's settings documentation](https://code.claude.com/docs/en/settings). A single
> `status` scan runs the manifest's checks and launches a shipped shell script, so an
> incomplete list has a lot of surface to trip over. Confirm the behaviour in your own
> mode before enabling it, and remember you would be trading a guarantee this page argues
> you do not get.

## What would actually work

- **Sandbox-level**: filesystem and network isolation, so `jq` cannot read a path and
  `curl` cannot reach an endpoint regardless of which command wraps it. This is the only
  boundary for the **filesystem and unrestricted-network** cases — secret files, and any
  request the plugin can compose. It is outside the plugin's control.
- **A lower-privilege identity**: the durable answer for apply. A principal without apply
  permission on those workspaces cannot apply, whatever command is used. Note this is not
  the token phase 0 mints — see [the HCP token section](#the-hcp-token-what-the-agent-never-sees-secrets-does-and-does-not-cover).

**And what only narrows.** A read-only subagent (#19) is worth building — it isolates the
scan's context and removes `Edit` and `Write` — but it does **not** enforce
change-nothing, and this page would be contradicting itself to say otherwise. `status`
runs 21 shell checks: manifest checks, API reads, and a shipped script. It needs `Bash`,
and bypass 3 above establishes that `Bash` writes files. Remove `Bash` and the scan cannot
run at all. So the subagent reduces the surface for an accident; only a sandboxed
command runner turns it into a boundary.

## The HCP token: what "the agent never sees secrets" does and does not cover

`protocol.md` states the model: the human signs up, mints credentials, and pastes secrets
into HCP, and the agent must never see that plaintext. That holds for the **Cloudflare API
token** and the **GitHub App credentials** — browser into HCP workspace variables, and the
agent only verifies their presence over the API.

It also does not hold for the Cloudflare **discovery** token used by `import`.
`docs/import.md` has the human mint a short-lived read-only token and write it to
`/tmp/cf_token` for `cf-terraforming`, which the agent runs. A Bash-capable agent can read
that file until step 7 deletes it and the token is revoked — so the exposure is bounded in
time and scope, not absent. Keep that window short.

It does **not** hold for the HCP token either. Phase 0 has the human run `terraform login`, and
every later step reads the result:

```sh
export HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' \
  ~/.terraform.d/credentials.tfrc.json)
```

That token is in the agent's environment by design — the pivot the workflow turns on. Do
not deny the read; it breaks every HCP step, and a manual `export` puts the same secret in
the same environment through another door.

**Use a separate, lower-privilege identity.** This is the one place a real control
exists, but "scope the token" understates the work. `terraform login` mints an HCP **user**
API token, and a user token carries that user's permissions — `docs/state.md` says so
plainly: *"the same token authenticates every HCP REST endpoint, so anything you can do in
the UI you can script."* There is no apply scope to remove from it.

The control is therefore to provision a **different principal** — a user or team without
apply permission on the `cloudflare` and `github-org` workspaces — and run the agent as
that identity. Phase 0 neither provisions nor verifies such an identity, so this is
operator work today, and worth its own issue.

## Claude Code specifics

Precedence, highest first: managed settings → CLI flags → `.claude/settings.local.json` →
`.claude/settings.json` → `~/.claude/settings.json`. Rules evaluate **deny → ask → allow**,
first match wins. `/status` shows the active layers.

Managed settings live at a platform-specific file, named per platform in Claude Code's
[settings documentation](https://code.claude.com/docs/en/settings#settings-files). That
path list and the managed-only field names are Claude's to change, not this plugin's —
and two findings on this page were exactly that kind of drift, so read them there rather
than from a copy here.

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
