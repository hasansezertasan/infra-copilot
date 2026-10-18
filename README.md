# infra-skills

Agent-agnostic, human-in-the-loop toolkit that bootstraps and maintains a
**Terraform + Cloudflare + GitHub** SaaS infrastructure repo, with object-storage state
and GitHub Actions (recommended) or HCP Terraform managed runs.

The one idea behind it: **the human is the browser and the keyholder — everything
scriptable is the agent's.** There is exactly one class of thing a human must do that an
agent cannot: sit at a browser, sign up for a service, and mint or paste a credential.
After the backend and credentials are configured, the agent drives verification,
plans, and imports over each provider's API, pausing for the human steps.

## Install

The quickest way is to give your agent the prompt in
[`docs/installation.md`](docs/installation.md), which tells it to pick the install route
for its own host and stop once the install is confirmed. Or install yourself:

| Host | Install | Update | Invoke |
|---|---|---|---|
| [Claude Code](docs/install-claude-code.md) | `claude plugin marketplace add hasansezertasan/infra-skills --scope project`, then `claude plugin install infra-skills --scope project` | `/plugin update infra-skills`, then restart | `/infra-skills:infra-setup`, `/infra-skills:infra-import`, `/infra-skills:infra-prune`, `/infra-skills:infra-add`, `/infra-skills:infra-status` |
| [Codex CLI](docs/install-codex.md) | User-scope only: `codex plugin marketplace add hasansezertasan/infra-skills`, then enable it from `/plugins` and start a new session | `codex plugin marketplace upgrade infra-skills`, then `codex plugin add infra-skills@infra-skills` and restart | Ask to use infra-skills for setup, import, prune, add, or status; plugin-defined slash commands are not exposed |
| [Antigravity](docs/install-antigravity.md) | User-scope only: `agy plugin install https://github.com/hasansezertasan/infra-skills` | Reinstall the plugin, then restart | `/infra-skills:infra-setup`, `/infra-skills:infra-import`, `/infra-skills:infra-prune`, `/infra-skills:infra-add`, `/infra-skills:infra-status`, or natural language |
| [OpenCode](docs/install-opencode.md) | `npx skills add hasansezertasan/infra-skills --agent opencode --skill '*' -y` in the consuming repo, then restart | `npx skills update -p`, then restart | Ask OpenCode to use `infra-skills`, `infra-setup`, `import`, `prune`, `add`, or `status`; skills load on demand through the native `skill` tool |

On the three marketplace/plugin hosts, refresh the host marketplace or plugin after an
update and restart the session so changed skills are rediscovered. OpenCode has neither:
`npx skills update -p` rewrites files inside the consuming repo, so review the diff —
see [`docs/install-opencode.md`](docs/install-opencode.md).

**Upgrading from infra-copilot.** The plugin was renamed to `infra-skills`, and its skills are
now `infra-setup`, `infra-import`, `infra-prune`, `infra-add` and `infra-status`. The slash
commands (`/infra-setup` and the rest) are gone; invoke a skill by name, for example
`/infra-skills:infra-setup`. An existing install does not follow the rename: uninstall
`infra-copilot` and install `infra-skills` from the table above.

The table is the index; each host name links to a page with that host's caveats — what
"update" actually updates, whether a restart is required, how to verify the install, and
on Codex why `/infra-skills:infra-setup` does not exist there. Per-host capabilities are recorded once
in [`hosts.md`](skills/infra/references/hosts.md); the install pages cite it
rather than restating it.

On OpenCode you can install a single skill and its dependencies rather than all six —
`--skill infra-status --skill infra` is the read-only audit install, since every action
skill is a router over the `infra` hub and is inert without it. See
[`docs/install-opencode.md`](docs/install-opencode.md); `npm run closure -- <name>`
prints any **action** skill's closure, derived from the links in its `SKILL.md`. The
`infra` hub is not a closure root — it owns no operations, so installed alone it
routes to nothing — and the command says so rather than printing one.

### Session announcement

On Claude Code, a `SessionStart` hook announces that the plugin is installed when the
working directory carries any of its markers — the Config block markers in the root
`README.md`, or a `terraform/` tree. Discovery otherwise depends on
a user's phrasing happening to match a skill description. It is
deliberately static: one marker test, no provider calls, no `git`, and it names
the skills rather than reporting any state, because state is re-derived by running each
step check. Silence it with `INFRA_HOOK_DISABLE=1`.

No other host ships one. Which hosts do, the discovery path each uses, and the evidence
behind every exclusion are recorded in
[`hosts.md`](skills/infra/references/hosts.md), which is the single capability
record — repeating any of it here would be a second copy that nothing keeps in step when
a host graduates. See [#42](https://github.com/hasansezertasan/infra-skills/issues/42).

## Configure

`infra-skills` is org-agnostic — it carries no hardcoded organization, domain, or
account IDs. The **Infra repo** (the repo you're bootstrapping) must carry a
committed, non-secret Config block in its root `README.md`: one fenced YAML block between
`<!-- infra:config start -->` and `<!-- infra:config end -->` under a `## Config` heading,
holding only public identifiers. Its locked choices live in a Decisions table, a second
README section between `<!-- infra:decisions start -->` and `<!-- infra:decisions end -->`.
The [Template](#scaffolding-the-repository-with-copier-infra) renders both:

```yaml
backend: object-storage       # required: hcp | object-storage; choose explicitly during setup
github_org: <string>           # GitHub org slug
apex_domain: <string>          # e.g. example.dev
cloudflare_account_id: <hex>   # Cloudflare account ID
cloudflare_zone_id: <hex>      # Cloudflare zone ID for the apex domain
managed_repos:                 # repos Terraform manages; first entry is the primary repo
  - <owner/name>
state_backend: gcs            # gcs | s3 | azurerm
state_bucket: <string>
state_prefix: terraform/state
```

**No secrets go in the Config block.** Secrets (Cloudflare API token, GitHub App credentials,
etc.) live in GitHub Actions secrets (object-storage mode) or HCP workspace variables
(HCP mode) — a human saves them directly there, and the agent never sees their plaintext.

Full schema, the shell-export contract, and the startup behavior when the block is
missing: [`config.md`](skills/infra/references/config.md). A reference excerpt ships at
[`config.md.example`](skills/infra/references/config.md.example). The Skills write only
between the `# infra:customization` comments inside the block and refuse to edit outside them.

### Scaffolding the repository with copier-infra

[`copier-infra`](https://github.com/hasansezertasan/copier-infra) is a Copier template that
renders a consuming repo shaped for this contract: the README Config block and
Decisions table with an explicit `backend:` and its matching fields, a `backend.tf` per Terraform root,
`mise.toml` and `mise.lock` at the repo root, plus `AGENTS.md`. It asks
only for the public identifiers in the config above. `infra-setup` renders it for you on an empty
directory, with the Copier version pinned in
[`copier-requirements.txt`](skills/infra/references/copier-requirements.txt), and checks
that the recorded Template release is at or above the minimum (the Template contract). To render
it by hand instead:

```sh
copier() { uv run --no-project --with-requirements \
  https://raw.githubusercontent.com/hasansezertasan/infra-skills/main/skills/infra/references/copier-requirements.txt \
  copier "$@"; }
copier copy gh:hasansezertasan/copier-infra infra
cd infra
git init && git add -A && git commit -m "chore: scaffold infrastructure repository"
```

Copier does not initialize Git, and setup's checks and `copier update` both read tracked files
and `HEAD`, so commit the render first. Install infra-skills and start the agent inside
`infra`, then ask it to use infra-skills to set up the new repository, with the host
invocation from the install table above (`/infra-skills:infra-setup` on Claude Code and
Antigravity); it
reads the committed config and resumes from where the scan reports. Change values later with
`copier update` (the same pinned function, run from the repo root) and review the diff,
rather than hand-editing the Config block or `backend.tf`, so the config and the Terraform
literals stay aligned.
`copier recopy` re-renders over local edits; use it only for deliberate recovery, on a clean
tree, after reading the diff.

Treat any change to `backend`, `state_backend`, `state_bucket` or `state_prefix` after
rendering as a state migration, not an answer change. Copier rewrites `backend.tf` but moves
no state, and the state-transfer check only demands transfer evidence once it detects an HCP
backend in history, so an empty new destination can be accepted and the next plan may propose
recreating managed resources. Follow
[`object-storage-state.md`](skills/infra/references/docs/object-storage-state.md#migrating-from-hcp)
for an HCP cutover, and move state yourself, with the same verification, for any other
location change.

HCP mode requires a paid tier with team management for this workflow's plan-only team
token, even below the free tier's 500-resource limit. The
[backend comparison](skills/infra/references/config.md#backend-modes) explains
this prerequisite before setup asks for the choice.

**Migration:** `backend:` is now required. Existing HCP repos must add `backend: hcp`
to keep their current workflow. All action skills stop with a handoff when it is missing;
`infra-setup` offers to record HCP when existing `cloud {}` blocks are found. This records the
existing mode without moving state. See the
[migration guidance](skills/infra/references/config.md#migration-existing-configs-without-backend),
including HCP-specific fields.

The old `.infra-copilot/` directory and `.claude/infra-copilot.local.md` file are
**unsupported**: the Skills report them and stop, and there is no migration code. Move the
values into the README Config block and Decisions table by hand, then delete the old paths.
Provider and authentication decisions belong in the Decisions table; the shipped
[`decisions.md.example`](skills/infra/references/decisions.md.example) shows its rows.

## Restricting what it can do

**Claude Code's command-level permission rules cannot meaningfully constrain this
plugin**, and
[`docs/policy.md`](docs/policy.md) shows why with six bypasses the plugin's own
documentation supplies — `mise exec -- terraform apply` sidesteps a Terraform deny,
`curl -X POST .../runs/<id>/actions/apply` applies without Terraform at all, `Read()`
rules do not govern Bash subprocesses, and `/infra-skills:infra-setup` reaches the same procedure
without invoking the denied skill. One further bypass — whether a curated allow-list can
match a compound check — is documented as unverified rather than asserted.

**No rule type holds**, including `Skill()` denies. Write them if you like — they raise
the cost of an accident — but not as a boundary.

What does work: sandbox isolation, or — for apply specifically — **running the agent as a
principal that lacks apply permission**. Note that is not the token `terraform login`
mints: a user token carries its user's permissions, so this needs a separate identity that
phase 0 does not create. Where
[`hosts.md`](skills/infra/references/hosts.md) marks the subagent row shipped, the
`infra-auditor` subagent runs the scan in an isolated context and its grant carries no
`Edit` or `Write`; everywhere else the scan runs inline with the session's own tools. Even
where it ships, that does not enforce change-nothing: the scan runs manifest-defined shell
checks, so it needs `Bash`, and `Bash` writes files. It is a context boundary and a
narrowed surface, not a sandbox.

The document also states which secrets never reach the agent and which one does.

## Skills

The work is split by function. Each skill is a thin router over the `infra` hub
skill and its self-contained [`references/`](skills/infra/references/) directory.
That directory owns the manifest, protocol, provider guidance, and runbooks once; generated
host packages copy the whole hub skill so relative links remain valid everywhere.

| Skill | Command | Does |
|---|---|---|
| [`infra`](skills/infra/SKILL.md) | natural language | Routes a general request to the smallest matching workflow. |
| [`infra-setup`](skills/infra-setup/SKILL.md) | `/infra-skills:infra-setup` | **Greenfield bootstrap** (phases 0–4): renders the [`copier-infra`](https://github.com/hasansezertasan/copier-infra) Template, explicit backend choice, state + CI, Cloudflare token, GitHub App, first plan. |
| [`infra-import`](skills/infra-import/SKILL.md) | `/infra-skills:infra-import` | **Adopt existing** provider resources into Terraform without recreating them (cf-terraforming import blocks). |
| [`infra-prune`](skills/infra-prune/SKILL.md) | `/infra-skills:infra-prune` | **Retire the spent blocks** an adoption leaves behind — `import {}` / `moved {}` go inert once applied. Ends on `No changes.` |
| [`infra-add`](skills/infra-add/SKILL.md) | `/infra-skills:infra-add` | **Grow** the repo: a managed repo, a new resource, or a brand-new provider (e.g. GCP). |
| [`infra-status`](skills/infra-status/SKILL.md) | `/infra-skills:infra-status` | **Read-only** health check — scans every step and reports where infra stands. Changes nothing. |

## Usage

In the consuming repo, use the host invocation above (or say "use infra-skills to set up
infra"). The skill reads your
config, runs a resume scan against the manifest to discover where setup already stands, and
drives every step tagged `AGENT` itself — verifying, provisioning, planning. When it hits a
step tagged `HUMAN` (a signup, a credential mint, a secret paste) it stops, prints a handoff
block with precise instructions, and waits for you to reply `done` before continuing.

It's idempotent: re-run any skill any time. An all-green resume scan means "already done,
nothing to do." Not sure where you are? Run `/infra-skills:infra-status` first — it tells you which
skill
to reach for.

## Maintaining host packages

Canonical behavior lives only in `.ai-rulez/skills/`. Claude
Code, Codex, and Pi consume the committed root output generated from those sources
(the Codex marketplace and the Pi package fields included). OpenCode installs the same root
skills through the portable `skills` installer; it does not need a second generated
`.opencode/` copy. The Antigravity manifest (`plugin.json`) remains a small hand-authored
adapter because `ai-rulez` does not generate that install surface. Claude-compatible
`allowed-tools` values live
only in command frontmatter as adapter permissions; workflow bodies remain host-neutral.

Run everything through npm scripts — `npm run check:all` is what CI runs, so a green run locally
is a green pipeline:

```bash
npm run generate   # regenerate the host packages after editing .ai-rulez/
npm run check:all  # everything CI runs: check + lint + validate + test + OpenCode smoke tests
```

Individual scripts (`npm run check`, `npm run lint`, `npm run validate`, `npm test`,
`npm run smoke-opencode`) exist for narrowing down a failure.

`npm run check-upstream` is separate because it reads the network. The shipped references
cite external facts whose currency matters — a `cf-terraforming` coverage matrix, two
provider majors, an action pinned by SHA in shipped CI — and it compares each against the
current upstream release. It also checks every HCP API path the guidance calls against
the OpenAPI spec HashiCorp ships in `go-tfe`. It runs nightly rather than on pull
requests, so a rate limit can never fail a PR. The audited facts and what each one affects live in
[`scripts/upstream.json`](scripts/upstream.json); `npm run validate` verifies offline that the
docs still cite them.

Versions that are only illustrative are deliberately not tracked — the worked `mise.toml`
in the setup runbook names example versions whose requirement is being *exact*, not being
*newest*, and gating them produced recurring failures with no decision attached.

[`package.json`](package.json) is the single definition of the tool versions this
repository invokes; `npm ci` installs them and the npm scripts run them from
`node_modules/.bin`. Renovate's native npm manager keeps them current, so a tool added to
`devDependencies` is covered the moment it lands.

`npm run check` deliberately excludes `smoke-opencode` and `smoke-closure`, which install the plugin
into a throwaway copy of the tree: "the plugin installs" is a different claim from "the payloads
are valid", so it gets its own CI job and its own signal, and failing it still blocks the
merge. `npm run check:all` runs everything locally.

Generated files are committed so users can install without having `ai-rulez`. CI runs the
same validation and fails if generated payloads drift or local Markdown links break.

## Adding a skill

The plugin is meant to grow. To add a new capability, drop a new directory under
`.ai-rulez/skills/` with its own `SKILL.md` — route it over the protocol and manifest under
`.ai-rulez/skills/infra/references/` rather than re-copying that machinery.
Regenerate the host packages before opening a pull request. Extension points: drift
detection, cost review, additional providers.

## License

MIT — see [`LICENSE`](LICENSE).
