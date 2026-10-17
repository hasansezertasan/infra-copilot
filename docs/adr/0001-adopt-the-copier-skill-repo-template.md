# Adopt the copier-skill-repo template

Decided 2026-10-18. infra-copilot is generated from, and kept current by,
[copier-skill-repo](https://github.com/hasansezertasan/copier-skill-repo), rendered at `v0.4.2`
(`.copier-answers.yml`). It is the last of three skill repos to adopt it, and the outlier: it moved
from ai-rulez 4.11.3 to 5.3.0, from a literal plugin version to `package.json`, and from a Makefile
and Python validator to npm scripts. Skills, `CHANGELOG.md` and the shipped hook, subagent and slash
commands are untouched. The README changed only where it named `make`.

## Answers

`repo_name: infra-copilot`, `keywords` as before, `publish_to_npm: false`, `license: MIT`. The
placeholder skill was deleted after rendering. `package.json` is private, so Pi installs from git.

## Remaining differences from the template, and why

- **Root components.** The template's check fails on `hooks/`, `agents/` and `commands/` at the root.
  This repo ships all three on purpose (the SessionStart hook, the `infra-auditor` subagent, the five
  slash commands). The template gained an opt-in for this (copier-skill-repo#52, v0.4.0): they are
  listed with reasons in `.config/root-components.json`. Every other root component still fails.
- **Lint opt-outs** in `.ai-rulez/config.toml`, each with its reason there: `AR9T0` (the template's,
  for the Antigravity adapter), `AR401` and `AR402` (the skills cite files of the infrastructure
  repository they operate on), `AR005` (the check scripts read variables by name with `eval`, from a
  literal list), `AR014` and `AR028` (every authenticated call goes to the host in `$hcp_api`, which
  the rules cannot resolve, and the token travels in a header), `AR030` (the destructive path is
  gated by human approval, not by splitting the skill). `allowed_tools = ["Bash"]` accepts `AR007`:
  the commands run Terraform, `gh` and API calls.
- **`.config/root-components.json`, `scripts/smoke-*.sh`, `scripts/check_upstream.py`,
  `scripts/validate.py` and `tests/`** are repo-owned additions. `npm run check` is the template's
  check; `npm run check:all` adds `lint`, `validate`, `test` and the two smoke scripts, which is what
  CI runs. `check.yml` keeps three jobs (`check`, `Smoke-test the OpenCode payload`,
  `Validate portable paths (Windows)`), and `upstream.yml` stays, hardened to the template's level.
- **`validate_tool_pins` was replaced by `validate_exact_pins`.** The old check guarded a Makefile
  and a `TOOL_PACKAGES` list that no longer exist, so both went. Renovate's native npm manager keeps
  the three tools current, and the one rule that still matters stays: every `devDependency` is an
  exact version, not a range.
- **Version checks read `package.json`.** `validate_versions`, `validate_release_please` and the
  location scan keep their rules, repointed at `package.json` and the root `release-please-config.json`
  (`node` release type, `plugins[0].version` for the Claude marketplace). The generated Codex
  marketplace carries no version, so it is compared by nobody.
- **ai-rulez 5 output differs from 4.** Headers record a new source hash. The Claude marketplace gains
  `category`. The Codex marketplace is generated now and loses the owner, metadata and per-plugin
  description it carried by hand. `.pi/prompts/` is new, one prompt per slash command, and
  `package.json` carries the generated Pi fields and a `files` allowlist. ai-rulez 5.3.0 leaves the
  `../skills/...` links in those prompts unrewritten, so `validate.py` skips `.pi/`; the commands
  under `commands/` carry the same links and are still checked.
- **`plugin.json` (Antigravity)** takes the config's description, because the template's check
  requires it to equal the Claude manifest's.
- **Renovate** keeps its own `renovate.json` (the `github>` preset, the Monday schedule and the weekly
  tooling group) and not the template's. `copier update` will conflict there; keep this repo's side.
- **markdownlint** skips `docs/installation.md` and `CONTRIBUTING.md`, which are template-owned and
  unwrapped.
- **`CONTRIBUTING.md`.** `.github/CONTRIBUTING.md` was folded into the template's root file as an
  "Infra Copilot development" section; the template's release, setup and recovery sections replace
  the old ones. Expect `copier update` conflicts there and keep both sides.
- **Node** is 24 from `.node-version` (CI used 22); `engines` still allows 22.

## Before the merge

- **Replace `validate` with `check`** in the `main` ruleset's required status checks. This pull
  request renames the job, so while `validate` is required it can never report that check and cannot
  merge. Until it merges, any other open pull request waits for a `check` it has not run; rebase it
  after the merge. The other two required checks keep their names.

## After the merge

- Close Renovate's open pull requests for tools that moved into `package.json` configuration.
- Close the adoption ticket in copier-skill-repo (#13).
