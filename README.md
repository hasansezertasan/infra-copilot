# infra-copilot

Agent-agnostic, human-in-the-loop toolkit that bootstraps and maintains a
**Terraform + HCP Terraform + Cloudflare + GitHub** SaaS infrastructure repo.

The one idea behind it: **the human is the browser and the keyholder — everything
scriptable is the agent's.** There is exactly one class of thing a human must do that an
agent cannot: sit at a browser, sign up for a service, and mint or paste a credential.
Once an HCP Terraform token exists, the agent drives the rest end-to-end — creating
workspaces, setting variables, reading plans, importing existing resources — over each
provider's API, pausing only for the irreducibly human steps.

## Install

| Host | Install | Update | Invoke |
|---|---|---|---|
| [Claude Code](docs/install-claude-code.md) | `/plugin marketplace add hasansezertasan/infra-copilot`, then `/plugin install infra-copilot` | `/plugin update infra-copilot`, then restart | `/infra-setup`, `/infra-import`, `/infra-prune`, `/infra-add`, `/infra-status` |
| [Codex CLI](docs/install-codex.md) | `codex plugin marketplace add hasansezertasan/infra-copilot`, then enable it from `/plugins` and start a new session | `codex plugin marketplace upgrade infra-copilot`, then `codex plugin add infra-copilot@infra-copilot` and restart | Ask to use infra-copilot for setup, import, prune, add, or status; plugin-defined slash commands are not exposed |
| [Antigravity](docs/install-antigravity.md) | `agy plugin install https://github.com/hasansezertasan/infra-copilot` | Reinstall the plugin, then restart | `/infra-setup`, `/infra-import`, `/infra-prune`, `/infra-add`, `/infra-status`, or natural language |
| [OpenCode](docs/install-opencode.md) | `npx skills add hasansezertasan/infra-copilot --agent opencode --skill '*' -y` in the consuming repo, then restart | `npx skills update -p`, then restart | Ask OpenCode to use `infra-copilot`, `setup`, `import`, `prune`, `add`, or `status`; skills load on demand through the native `skill` tool |

On the three marketplace/plugin hosts, refresh the host marketplace or plugin after an
update and restart the session so changed skills are rediscovered. OpenCode has neither:
`npx skills update -p` rewrites files inside the consuming repo, so review the diff —
see [`docs/install-opencode.md`](docs/install-opencode.md).

The table is the index; each host name links to a page with that host's caveats — what
"update" actually updates, whether a restart is required, how to verify the install, and
on Codex why `/infra-setup` does not exist there. Per-host capabilities are recorded once
in [`hosts.md`](skills/infra-copilot/references/hosts.md); the install pages cite it
rather than restating it.

On OpenCode you can install a single skill and its dependencies rather than all six —
`--skill status --skill infra-copilot` is the read-only audit install, since every action
skill is a router over the `infra-copilot` hub and is inert without it. See
[`docs/install-opencode.md`](docs/install-opencode.md); `make closure SKILL=<name>`
prints any **action** skill's closure, derived from the links in its `SKILL.md`. The
`infra-copilot` hub is not a closure root — it owns no operations, so installed alone it
routes to nothing — and the command says so rather than printing one.

### Session announcement

On Claude Code, a `SessionStart` hook announces that the plugin is installed when the
working directory carries any of its markers — `.infra-copilot/config.md`, the legacy
`.claude/infra-copilot.local.md`, or a `terraform/` tree. Discovery otherwise depends on
a user's phrasing happening to match a skill description. It is
deliberately static: one file-existence test, no provider calls, no `git`, and it names
the skills rather than reporting any state, because state is re-derived by running each
step check. Silence it with `INFRA_COPILOT_HOOK_DISABLE=1`.

No other host ships one. Which hosts do, the discovery path each uses, and the evidence
behind every exclusion are recorded in
[`hosts.md`](skills/infra-copilot/references/hosts.md), which is the single capability
record — repeating any of it here would be a second copy that nothing keeps in step when
a host graduates. See [#42](https://github.com/hasansezertasan/infra-copilot/issues/42).

## Configure

`infra-copilot` is org-agnostic — it carries no hardcoded organization, domain, or
account IDs. The **consuming repo** (the infra repo you're bootstrapping) must carry a
committed, non-secret config file:

```text
.infra-copilot/config.md
```

It's Markdown with a YAML frontmatter block holding only public identifiers:

```yaml
---
hcp_org: <string>              # HCP Terraform organization slug
github_org: <string>           # GitHub org slug (often == hcp_org)
apex_domain: <string>          # e.g. example.dev
cloudflare_account_id: <hex>   # Cloudflare account ID
cloudflare_zone_id: <hex>      # Cloudflare zone ID for the apex domain
managed_repos:                 # repos Terraform manages; first entry is the VCS repo HCP watches
  - <owner/name>
hcp_status_check_id: ""        # regenerated by HCP after first VCS connect; leave "" until then
---
```

**No secrets go in this file.** Secrets (Cloudflare API token, GitHub App credentials,
etc.) live exclusively in HCP Terraform workspace variables — the agent never sees their
plaintext; a human pastes them directly into HCP.

Full schema, the shell-export contract, and the startup behavior when the file is
missing: [`config.md`](skills/infra-copilot/references/config.md). A fillable template ships at
[`config.md.example`](skills/infra-copilot/references/config.md.example).

Existing `.claude/infra-copilot.local.md` files remain readable as a migration fallback.
Move their contents unchanged to `.infra-copilot/config.md`; do not maintain both. Provider
and authentication decisions belong in `.infra-copilot/decisions.md`; copy the shipped
[`decisions.md.example`](skills/infra-copilot/references/decisions.md.example) and migrate
any legacy `CLAUDE.md` decision table into it.

## Restricting what it can do

**Claude Code's command-level permission rules cannot meaningfully constrain this
plugin**, and
[`docs/policy.md`](docs/policy.md) shows why with six bypasses the plugin's own
documentation supplies — `mise exec -- terraform apply` sidesteps a Terraform deny,
`curl -X POST .../runs/<id>/actions/apply` applies without Terraform at all, `Read()`
rules do not govern Bash subprocesses, and `/infra-setup` reaches the same procedure
without invoking the denied skill. One further bypass — whether a curated allow-list can
match a compound check — is documented as unverified rather than asserted.

**No rule type holds**, including `Skill()` denies. Write them if you like — they raise
the cost of an accident — but not as a boundary.

What does work: sandbox isolation, or — for apply specifically — **running the agent as a
principal that lacks apply permission**. Note that is not the token `terraform login`
mints: a user token carries its user's permissions, so this needs a separate identity that
phase 0 does not create. Where
[`hosts.md`](skills/infra-copilot/references/hosts.md) marks the subagent row shipped, the
`infra-auditor` subagent runs the scan in an isolated context and its grant carries no
`Edit` or `Write`; everywhere else the scan runs inline with the session's own tools. Even
where it ships, that does not enforce change-nothing: the scan runs manifest-defined shell
checks, so it needs `Bash`, and `Bash` writes files. It is a context boundary and a
narrowed surface, not a sandbox.

The document also states which secrets never reach the agent and which one does.

## Skills

The work is split by function. Each skill is a thin router over the `infra-copilot` hub
skill and its self-contained [`references/`](skills/infra-copilot/references/) directory.
That directory owns the manifest, protocol, provider guidance, and runbooks once; generated
host packages copy the whole hub skill so relative links remain valid everywhere.

| Skill | Command | Does |
|---|---|---|
| [`infra-copilot`](skills/infra-copilot/SKILL.md) | natural language | Routes a general request to the smallest matching workflow. |
| [`setup`](skills/setup/SKILL.md) | `/infra-setup` | **Greenfield bootstrap** (phases 0–4): HCP org/login, workspaces, Cloudflare token, GitHub App, first plan. |
| [`import`](skills/import/SKILL.md) | `/infra-import` | **Adopt existing** provider resources into Terraform without recreating them (cf-terraforming import blocks). |
| [`prune`](skills/prune/SKILL.md) | `/infra-prune` | **Retire the spent blocks** an adoption leaves behind — `import {}` / `moved {}` go inert once applied. Ends on `No changes.` |
| [`add`](skills/add/SKILL.md) | `/infra-add` | **Grow** the repo: a managed repo, a new resource, or a brand-new provider (e.g. GCP). |
| [`status`](skills/status/SKILL.md) | `/infra-status` | **Read-only** health check — scans every step and reports where infra stands. Changes nothing. |

## Usage

In the consuming repo, use the host invocation above (or say "use infra-copilot to set up
infra"). The skill reads your
config, runs a resume scan against the manifest to discover where setup already stands, and
drives every step tagged `AGENT` itself — verifying, provisioning, planning. When it hits a
step tagged `HUMAN` (a signup, a credential mint, a secret paste) it stops, prints a handoff
block with precise instructions, and waits for you to reply `done` before continuing.

It's idempotent: re-run any skill any time. An all-green resume scan means "already done,
nothing to do." Not sure where you are? Run `/infra-status` first — it tells you which skill
to reach for.

## Maintaining host packages

Canonical behavior lives only in `.ai-rulez/skills/` and `.ai-rulez/commands/`. Claude
Code, Codex, and Antigravity consume the committed root adapters generated from those
sources. OpenCode installs the same root skills through the portable `skills` installer;
it does not need a second generated `.opencode/` copy. The native Codex marketplace and
Antigravity manifest remain small hand-authored adapters because `ai-rulez` does not
currently generate those install surfaces. Claude-compatible `allowed-tools` values live
only in command frontmatter as adapter permissions; workflow bodies remain host-neutral.

Run everything through `make` — it is what CI runs, so a green `make check` locally is a
green pipeline:

```bash
make            # list targets
make generate   # regenerate the host packages after editing .ai-rulez/
make check      # everything CI runs: validate + test + OpenCode smoke test
```

Individual targets (`make validate`, `make test`, `make smoke-opencode`) exist for
narrowing down a failure.

`make check-upstream` is separate because it reads the network. The shipped references
cite external facts whose currency matters — a `cf-terraforming` coverage matrix, two
provider majors, an action pinned by SHA in shipped CI — and it compares each against the
current upstream release. It runs nightly rather than on pull requests, so a rate limit
can never fail a PR. The audited facts and what each one affects live in
[`scripts/upstream.json`](scripts/upstream.json); `make check` verifies offline that the
docs still cite them.

Versions that are only illustrative are deliberately not tracked — the worked `mise.toml`
in the setup runbook names example versions whose requirement is being *exact*, not being
*newest*, and gating them produced recurring failures with no decision attached.

[`package.json`](package.json) is the single definition of the tool versions this
repository invokes; `npm ci` installs them and the `Makefile` runs them from
`node_modules/.bin`. Renovate's native npm manager keeps them current, so a tool added to
`devDependencies` is covered the moment it lands. `scripts/validate.py` asserts every tool
the `Makefile` runs resolves from `devDependencies`, and that no `Makefile` or workflow
reintroduces a `<tool>@<version>` of its own.

`make check` deliberately excludes `smoke-opencode`, which installs the plugin into a
throwaway copy of the tree: "the plugin installs" is a different claim from "the payloads
are valid", so it gets its own CI job and its own signal, and failing it still blocks the
merge. `make check-all` runs both locally.

Generated files are committed so users can install without having `ai-rulez`. CI runs the
same validation and fails if generated payloads drift or local Markdown links break.

## Releasing

The canonical version lives in `.ai-rulez/config.toml`; generated host manifests must
never be versioned independently.

1. Update `[plugin].version` and move the matching `CHANGELOG.md` section out of
   "unreleased".
2. Run `make generate` and `make check`, then merge the release commit to `main`.
3. Create an annotated tag with the exact canonical version and push it:

   ```bash
   git tag -a vX.Y.Z -m "infra-copilot vX.Y.Z"
   git push origin vX.Y.Z
   ```

The release workflow validates the tagged tree, rejects a tag/version mismatch, and
creates the GitHub Release with generated notes. The tagged repository tree is the
installable artifact; there is no separate npm or Python package to publish.

## Adding a skill

The plugin is meant to grow. To add a new capability, drop a new directory under
`.ai-rulez/skills/` with its own `SKILL.md` — route it over the protocol and manifest under
`.ai-rulez/skills/infra-copilot/references/` rather than re-copying that machinery.
Regenerate the host packages before opening a pull request. Extension points: drift
detection, cost review, additional providers.

## License

MIT — see [`LICENSE`](LICENSE).
