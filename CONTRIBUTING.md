# Contributing to infra-copilot

## Read this first: most of the tree is generated

`skills/`, `commands/`, `.claude-plugin/`, and `.codex-plugin/` are **generated output**.
Editing them does nothing durable — the next `make generate` overwrites your change, and
CI fails with a hash mismatch that never mentions the file you touched.

The sources are in **`.ai-rulez/`**.

```text
.ai-rulez/skills/<name>/SKILL.md          →  skills/<name>/SKILL.md
.ai-rulez/skills/infra-copilot/references/ →  skills/infra-copilot/references/
.ai-rulez/commands/<name>.md              →  commands/<name>.md
.ai-rulez/config.toml                     →  .claude-plugin/*, .codex-plugin/plugin.json
```

Most generated files say so in a comment at the top, with the hash that proves it:

```markdown
<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:…
-->
```

Six of the 28 have no such header — `.claude-plugin/marketplace.json`,
`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `config.md.example`,
`decisions.md.example`, and `steps.yaml` — so a missing header proves nothing.

`.ai-rulez-generated.json` is the authoritative list — 28 paths today. If a file is in
there, edit its source instead.

### What is *not* generated

Hand-authored, and safe to edit directly:

| Path | Why it is hand-authored |
|---|---|
| `plugin.json` | Antigravity manifest; `ai-rulez` does not generate this surface |
| `.agents/plugins/marketplace.json` | Codex marketplace; same reason |
| `scripts/validate.py`, `tests/` | The repository's own validators |
| `Makefile`, `.github/workflows/` | Build and CI |
| `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `AGENTS.md`, `docs/` | Documentation |

## The loop

```bash
# 1. edit a source under .ai-rulez/
# 2. regenerate the host packages
make generate
# 3. run exactly what CI runs
make check
# 4. commit sources AND generated output together
```

Generated files are committed on purpose, so users can install the plugin without having
`ai-rulez`. A commit that changes a source without its regenerated output fails
`ai-rulez verify --plugin`.

## Checks

`make check` is CI parity — if it passes locally, the pipeline passes.

| Target | What it covers |
|---|---|
| `make validate` | `ai-rulez validate`, `verify --plugin` (drift gate), `scripts/validate.py` |
| `make test` | the validator tests under `tests/` |
| `make smoke-opencode` | installs a throwaway copy of the tree and asserts the OpenCode payload |
| `make check` | all of the above |

`make smoke-opencode` runs against a copy of the working tree in a temp directory, so it
writes nothing into your checkout. That is deliberate: `skills add --copy` produces
`.agents/skills/` and `skills-lock.json`, and you may have your own local install of
either. If you ever do clean those up by hand, note that
`.agents/plugins/marketplace.json` is tracked and required — never delete `.agents/`
wholesale.

## Tool versions

`Makefile` is the **only** definition of the versions this repository invokes
(`AI_RULEZ_VERSION`, `SKILLS_VERSION`). `scripts/validate.py` asserts that `README.md`
documents the same versions, and rejects any workflow that reintroduces its own pin.

Bump them in the `Makefile` and update the README in the same commit.

## Versioning

The canonical plugin version is `[plugin].version` in `.ai-rulez/config.toml`. Four
manifests carry a copy — three generated (`.claude-plugin/marketplace.json`,
`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`) and one hand-authored
(`.agents/plugins/marketplace.json`, which must be bumped by hand). `scripts/validate.py`
asserts all four agree with each other and with the newest `## ` heading in
`CHANGELOG.md`.

`validate_versions` discovers version strings inside those manifests, so adding another
JSON manifest to `JSON_MANIFESTS` is enough for it to be compared — and a manifest there
that carries *no* version is reported unless it is listed in `VERSIONLESS_MANIFESTS`.

**A version string in any other kind of file is still invisible to it.** A README badge,
a shell installer, a version-pinned command in an install doc: none of those are JSON
manifests, so adding one means extending `scripts/validate.py` in the same commit.
Otherwise the check silently narrows as the repo grows.

## Conventions

- Branches: [Conventional Branch](https://conventional-branch.github.io/) —
  `<type>/<description>`, e.g. `feature/issue-10-makefile`.
- Commits and PR titles: [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) —
  `<type>(scope): <description>`.
- Behavior belongs in `.ai-rulez/skills/`; host manifests and commands are **adapters
  only** and must not become a second source of truth. Claude-specific `allowed-tools`
  values live in command frontmatter; workflow bodies stay host-neutral.
