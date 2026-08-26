# infra-copilot — agent context

This repository *is* a set of agent instructions. When you are asked to change it, the
most likely way to get it wrong is to edit the wrong copy of a file.

## Rule 1: do not edit generated files

`skills/`, `commands/`, `.claude-plugin/`, and `.codex-plugin/` are generated from
`.ai-rulez/`. They are the obvious files to open — `skills/setup/SKILL.md` looks like the
skill — and editing them is silently undone by the next `make generate`.

Before editing any file under those paths, check `.ai-rulez-generated.json`. If the path
is listed (28 are), edit its source under `.ai-rulez/` instead, then run `make generate`.

Every generated file carries an `AI-RULEZ :: GENERATED FILE — DO NOT EDIT` header. Treat
that header as binding.

## File resolution

| To change… | Edit | Then |
|---|---|---|
| A skill's behavior | `.ai-rulez/skills/<name>/SKILL.md` | `make generate` |
| Shared protocol, phase manifest, provider docs | `.ai-rulez/skills/infra-copilot/references/…` | `make generate` |
| A slash command | `.ai-rulez/commands/<name>.md` | `make generate` |
| Plugin identity, version, keywords | `.ai-rulez/config.toml` | `make generate` |
| Antigravity manifest | `plugin.json` | hand-authored — edit directly |
| Codex marketplace | `.agents/plugins/marketplace.json` | hand-authored — edit directly |
| Repository validators | `scripts/validate.py`, `tests/` | `make check` |
| Tool pins | `Makefile` + `README.md` together | `make check` |

## Rule 2: run `make check`

Never invoke `npx ai-rulez`, `python3 scripts/validate.py`, or the `skills` installer
directly in documentation or in a commit's verification step. `make check` is CI parity.

## Architecture, in one paragraph

Four action skills — `setup`, `import`, `add`, `status` — are thin routers over one hub
skill, `infra-copilot`, whose `references/` directory owns the behavior: `steps.yaml` (a
phase-tagged step manifest with a `check` per step), `protocol.md` (the actor model, the
handoff block, the resume scan, preflight), provider deep-dives, and runbooks. Host
packages are adapters and must never become a second behavioral authority. State is never
assumed: every run re-derives it by executing each step's `check`.

## Conventions

- Conventional Branch names, Conventional Commits.
- No AI attribution in commits, PR titles, or bodies.
- Behavior in `.ai-rulez/skills/`; host-specific values in adapters only.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full loop and
[`docs/roadmap.md`](docs/roadmap.md) for what is deliberately unbuilt.
