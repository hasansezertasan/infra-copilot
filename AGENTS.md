# infra-copilot — agent context

This repository *is* a set of agent instructions. When you are asked to change it, the
most likely way to get it wrong is to edit the wrong copy of a file.

## Rule 1: do not edit generated files

`skills/`, `commands/`, `.claude-plugin/`, and `.codex-plugin/` are generated from
`.ai-rulez/`. They are the obvious files to open — `skills/setup/SKILL.md` looks like the
skill — and editing them is silently undone by the next `make generate`.

Before editing any file under those paths, check `.ai-rulez-generated.json`. If the path
is listed (40 are), edit its source under `.ai-rulez/` instead, then run `make generate`.

Most generated files carry an `AI-RULEZ :: GENERATED FILE — DO NOT EDIT` header, but
**13 of the 40 do not** — every non-Markdown output, because a Markdown comment is not
valid in them: the JSON manifests (`marketplace.json`, `plugin.json`),
`config.md.example`, `decisions.md.example`, `steps.yaml`, shell checks
(`hcp-apply-scope.sh`, `hcp-bootstrap-workspaces.sh`, `hcp-current-plan.sh`,
`leaf-cloud.sh`, `status-check-context.sh`), and the YAML workflow templates
(`terraform-apply.yml`, `terraform-plan.yml`). Absence of the header is not evidence a
file is safe to edit. The manifest is the authority; the header is only a convenience.

## File resolution

| To change… | Edit | Then |
|---|---|---|
| A skill's behavior | `.ai-rulez/skills/<name>/SKILL.md` | `make generate` |
| Shared protocol, phase manifest, provider docs | `.ai-rulez/skills/infra-copilot/references/…` | `make generate` |
| A host's question tool or capabilities | `.ai-rulez/skills/infra-copilot/references/hosts.md` | `make generate` |
| A host's install instructions | `docs/install-<host>.md` | hand-authored — edit directly |
| A slash command | `.ai-rulez/commands/<name>.md` | `make generate` |
| Plugin identity, version, keywords | `.ai-rulez/config.toml` | `make generate` |
| Antigravity manifest | `plugin.json` | hand-authored — edit directly |
| Codex marketplace | `.agents/plugins/marketplace.json` | hand-authored — edit directly |
| Repository validators | `scripts/validate.py`, `tests/` | `make check` |
| The SessionStart hook | `hooks/session-start.sh`, `hooks/hooks.json` | hand-authored — `ai-rulez` has no hook support |
| Tool pins | `package.json` + `package-lock.json`; a *new* tool also needs `TOOL_PACKAGES`. Never write `<tool>@<version>` in a `Makefile` or workflow, comments included | `make check` |

## Rule 2: run `make check`

Never invoke `npx ai-rulez`, `python3 scripts/validate.py`, or the `skills` installer
directly in documentation, in a commit's verification step, or in the Linux CI job.
`make check` is CI parity.

This governs **this repository's own workflow**. The install guides under `docs/` address
a different audience: those commands run in the *consuming* repo, which has no copy of
this Makefile, so they name each host's native installer — `npx skills add` on OpenCode,
`/plugin install` on Claude Code. That is the supported public install path and has been
the README's since #4. The rule binds maintainer instructions, not user instructions.

One deliberate exception: the `windows-paths` job in `.github/workflows/check.yml` calls
`python scripts/validate.py` and the tests directly, because `make` is not guaranteed on
`windows-latest`. That job exists to prove paths stay portable, not to be CI parity. Leave
it as it is.

## Architecture, in one paragraph

Five action skills — `setup`, `import`, `prune`, `add`, `status` — are thin routers over one hub
skill, `infra-copilot`, whose `references/` directory owns the behavior: `steps.yaml` (a
phase-tagged step manifest with a `check` per step), `protocol.md` (the actor model, the
handoff block, the resume scan, preflight), provider deep-dives, and runbooks. Host
packages are adapters and must never become a second behavioral authority. State is never
assumed: every run re-derives it by executing each step's `check`.

## Conventions

- Conventional Branch names, Conventional Commits.
- No AI attribution in commits, PR titles, or bodies.
- Behavior in `.ai-rulez/skills/`; host-specific values in adapters only. One declared
  exception: `references/hosts.md` records what differs per host (native question tool
  and its capabilities, slash-command support) because the rules that read it are
  host-neutral and ship identically to all four hosts. The rule still binds what it was
  written for — a skill body must never name a host's tool; it reads the record instead.
  Change a capability there, not in an adapter.

See [`CONTRIBUTING.md`](.github/CONTRIBUTING.md) for the full loop and
[`docs/roadmap.md`](docs/roadmap.md) for what is deliberately unbuilt.
