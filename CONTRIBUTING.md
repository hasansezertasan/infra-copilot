# Contributing to Infra Copilot

This file is owned by the [copier-skill-repo](https://github.com/hasansezertasan/copier-skill-repo) template and is merged on `copier update`. Repo-specific guidance sits in the "Infra Copilot development" section below; expect to keep both sides when `copier update` conflicts here.

## How the repo works

- Skills live under `.ai-rulez/skills/<name>/`. That directory is the source of truth.
- `skills/` and the plugin and marketplace manifests are generated output. Never edit them by hand. `AGENTS.md` is hand-authored here, not generated.
- After changing anything under `.ai-rulez/`, run `npm run generate` and commit the result.
- `npm run check` is what CI runs. It fails when generated output has drifted.
- Node comes from `.node-version`.

## Infra Copilot development

### Most of the tree is generated

`skills/`, `commands/`, `.claude-plugin/`, `.codex-plugin/`, `.agents/plugins/`, `.pi/` and the Pi fields of
`package.json` are **generated output**. Editing them does nothing durable — the next
`npm run generate` overwrites your change, and CI fails with a hash mismatch that never
mentions the file you touched.

The sources are in **`.ai-rulez/`**.

```text
.ai-rulez/skills/<name>/SKILL.md          →  skills/<name>/SKILL.md
.ai-rulez/skills/infra-copilot/references/ →  skills/infra-copilot/references/
.ai-rulez/commands/<name>.md              →  commands/<name>.md
.ai-rulez/commands/<name>.md              →  .pi/prompts/<name>.md
.ai-rulez/config.toml                     →  .claude-plugin/*, .codex-plugin/plugin.json,
                                             .agents/plugins/marketplace.json, package.json (Pi fields)
```

Most generated files say so in a comment at the top, with the hash that proves it:

```markdown
<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:…
-->
```

Twenty-eight of the 69 have no such header — the outputs that are not Markdown:
`.agents/plugins/marketplace.json`, `.claude-plugin/marketplace.json`,
`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `package.json`, `config.md.example`, `decisions.md.example`, `steps.yaml`,
`checks/status-check-context.sh`, `checks/hcp-apply-scope.sh`, `checks/gcp-wif-trust.sh`,
`checks/hcp-bootstrap-workspaces.sh`, `checks/leaf-cloud.sh`,
`checks/hcp-github-app.sh`, `checks/hcp-current-plan.sh`,
`checks/provider-requirements.sh`, `checks/gha-latest-runs.sh`,
`checks/gha-provider-safety.sh`, `checks/gha-apply-gate.sh`,
`checks/leaf-routing.sh`, `checks/workflow-routing.sh`, `checks/gha-workflows.sh`, `checks/state-transfer.sh`,
`templates/apps/terraform-plan.json`, `templates/apps/terraform-apply.json`,
`templates/terraform-apply.yml`, `templates/terraform-plan.yml`, and
`templates/terraform-destroy.cjs` — so a missing header proves nothing.

`.ai-rulez-generated.json` is the authoritative list — 69 paths today. If a file is in
there, edit its source instead.

#### What is *not* generated

Hand-authored, and safe to edit directly:

| Path | Why it is hand-authored |
|---|---|
| `plugin.json` | Antigravity manifest; `ai-rulez` does not generate this surface |
| `scripts/validate.py`, `tests/` | The repository's own validators |
| `hooks/` | The SessionStart hook; `ai-rulez` has no hook support, so these are hand-authored |
| `agents/` | The `infra-auditor` subagent; `ai-rulez` has no agent surface. Which host this directory's dialect serves, and why the others go without, are recorded in [`hosts.md`](.ai-rulez/skills/infra-copilot/references/hosts.md) |
| `.github/workflows/`, `scripts/` | CI and the shell helpers |
| `.config/root-components.json` | The root components this repo ships on purpose (see below) |
| `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `docs/` | Documentation |

### The loop

```bash
# 0. once per clone: install the pinned tools (ai-rulez, markdownlint-cli2, skills)
npm ci
# 1. edit a source under .ai-rulez/
# 2. regenerate the host packages
npm run generate
# 3. run the checks CI runs on Linux
npm run check:all
# 4. commit sources AND generated output together
```

`python3` is also needed for `npm run validate` and `npm test`.

Generated files are committed on purpose, so users can install the plugin without having
`ai-rulez`. A commit that changes a source without its regenerated output fails
`ai-rulez verify --plugin`.

### Root components shipped on purpose

Both catalogs install the repository root, so `scripts/check-repo.mjs` fails on any path a host
loads from an installed plugin. This repo ships three deliberately, and lists each with its
reason in `.config/root-components.json`: `hooks/`, `agents/` and `commands/`. Adding another
needs an entry there with a reason; the check rejects an unknown name or an empty reason.

### Checks

`npm run check:all` runs every check CI runs on Linux. CI also runs a separate `Validate portable paths (Windows)` job, which runs `python scripts/validate.py` and the tests on `windows-latest`.

| Script | What it covers |
|---|---|
| `npm run check` | the template's check: workflow hardening, the Antigravity adapter, root components, the drift gate, `ai-rulez validate --strict` |
| `npm run lint` | markdownlint over the hand-authored Markdown |
| `npm run validate` | `scripts/validate.py` and upstream coherence (offline) |
| `npm test` | the validator tests under `tests/` |
| `npm run smoke-opencode` | installs a throwaway copy of the tree and asserts the OpenCode payload |
| `npm run smoke-closure` | installs one skill's derived closure and asserts it resolves exactly |
| `npm run check:all` | all of the above |
| `npm run closure -- <skill>` | prints the install arguments for one skill and its dependencies |
| `npm run check-upstream` | compares audited external versions with upstream (network; nightly in `upstream.yml`) |

The two smoke scripts are separate CI jobs on purpose: installing the plugin is a different claim
from the payloads being valid, and each job still blocks the merge. They run against a copy of the
working tree in a temp directory, so they write nothing into your checkout. That is deliberate:
`skills add --copy` produces `.agents/skills/` and `skills-lock.json`, and you may have your own local
install of either. If you ever clean those up by hand, note that `.agents/plugins/marketplace.json`
is tracked and required — never delete `.agents/` wholesale.

### Skill structure

Every `SKILL.md` addresses four concerns, and `npm run check:all` fails if one is missing:

| Section | Answers |
|---|---|
| workflow | what the agent does, in order |
| guardrails | what it must not do, and the preconditions |
| validation | how to know it is done |
| example | one concrete, worked case |

Matching is lenient — any H2 mentioning the word counts, so `## Example report` satisfies
`example`. The point is that each concern is findable, not that headings be identical.

The `infra-copilot` router is exempt from `example` only: it selects a skill and performs
no work, so it has nothing to demonstrate.

Use **one** name per concern across skills. `setup` once said `Done signal` while `import`
said `Success signal` for the same thing, which is why a test now rejects both spellings.

### Skill descriptions

A skill's frontmatter `description` loads into the host's prompt for **every session**,
whether or not the skill is used, so the total is capped: `npm run check:all` fails above
`MAX_DESCRIPTION_BUDGET` in `scripts/validate.py`, measured across all skills. Read the
current figure from that constant rather than from prose — an earlier draft of this
paragraph quoted a total and went stale within the same pull request.

The budget is aggregate rather than per-skill on purpose — it prices session context, so a
genuinely ambiguous skill may spend more as long as another spends less.

Write a description to answer **which skill**, not **whether this plugin exists**: the
`SessionStart` hook covers the second. In particular, do not enumerate trigger phrases;
the four action skills once carried 3.7 KB of them between them. Do keep the negative
routing that separates `add` from `import` — both act on a working repo, and the only
difference is whether the resource already exists at the provider.

### Tool versions

`package.json` is the **only** definition of the versions this repository invokes: `ai-rulez`,
`markdownlint-cli2` and `skills`, pinned exactly in `devDependencies`. The npm scripts run them
from `node_modules/.bin`, and Renovate's native npm manager keeps them current with no
configuration. Bump with `npm install <tool>@<version> --save-exact --save-dev` and commit
`package-lock.json` alongside.

### Versioning

`package.json` holds the canonical plugin version, the one file release-please bumps (the `node`
release type) and ai-rulez reads (`version_from`). Three generated manifests carry a copy:
`.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`.
`scripts/validate.py` asserts they agree with each other and with the newest release heading in
`CHANGELOG.md`, and that `release-please-config.json` bumps every copy it compares. The
generated Codex marketplace and the Antigravity `plugin.json` carry no version.

`validate_versions` discovers a top-level `version` and `plugins[0].version`. A version stored
anywhere else in a JSON manifest is not discovered. `validate_version_locations` scans every
tracked file for the current version and reports any outside `VERSIONED_FILES`, so a README badge
or a version-pinned install command is flagged in the commit that adds it. Drop the copy, or teach
`validate_versions` to compare it. If an unrelated number equals the version, list the file in
`UNRELATED_VERSION_FILES` with a reason; `package-lock.json` is already listed.

release-please cannot compute the source hash that `.ai-rulez-generated.json` records, so the
release workflow regenerates the output on the release PR branch (see "Release flow").

### Required checks

`main` is protected by a ruleset: changes land by squash-merged pull request, and the three
`Check` jobs (`check`, `Smoke-test the OpenCode payload`, `Validate portable paths (Windows)`)
must pass on the PR's head.

### Adapters

Behavior belongs in `.ai-rulez/skills/`; host manifests and commands are **adapters only** and must
not become a second source of truth. Claude-specific `allowed-tools` values live in command
frontmatter; workflow bodies stay host-neutral.

### Backend operation contracts

Action skill bodies outside `setup` use the named contracts in
[operations.md](.ai-rulez/skills/infra-copilot/references/operations.md).
The manifest records an `operation` and `implementation` for every backend-dependent
step. Several ordered members can implement one operation; preserve actor handoffs,
phase boundaries, per-provider iteration and tri-state outcomes. Status groups members
by operation and uses selected read-only evidence for mutating plan checks.

Add both backend implementations, a shared `both` implementation, or an explicit
`not_applicable` reason for a mechanism that does not exist in one backend. N/A is not
proof that the shared safety contract is satisfied. Keep execution-specific instructions
in the backend references. `npm run check:all` rejects backend names/selectors in non-setup
skill bodies and incomplete operation coverage.

## Skill layout

The template owns the scaffold, not a skill's content. A skill is a directory:

```text
.ai-rulez/skills/<name>/
├── SKILL.md       required
├── references/    optional: files the skill loads on demand
├── evals/         optional: test prompts and expected outcomes
└── scripts/       optional: helpers the skill runs
```

Only `SKILL.md` is required. The other directories are a convention the template describes and never creates, checks or overwrites.

## Commits and pull requests

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `<type>[(scope)][!]: <description>`.
- Pull request titles use the same format, because release-please builds the changelog and picks the next version from them.
- `feat` bumps the minor version, `fix` the patch. A `!` or a `BREAKING CHANGE:` footer marks a breaking change.
- Branch names are `<type>/<description>`, lowercase and hyphenated (`feature`, `bugfix`, `hotfix`, `release`, `chore`).

## Release flow

`package.json` is the sole version source. release-please bumps it, and bumps the generated plugin manifests alongside it, so no copy of the version is kept in sync by hand. The first release is 0.1.0. Before 1.0, a breaking change or a `feat` bumps the minor version and a `fix` bumps the patch.

1. On `main`, the `release` workflow runs the same `check` workflow as CI, then `scripts/release-guard.mjs`, which stops the release when the versions disagree.
2. release-please opens or updates a release PR with the version bump and the changelog. The workflow then regenerates the plugin output on that branch, because release-please cannot update the hash ledger `.ai-rulez-generated.json`: a read-only job runs `npm run generate` and `npm run check` and hands over a patch, and a separate job holding the write token applies it after checking that it touches only generated paths.
3. Review the whole PR, generated files included, and merge it once its checks pass.
4. The next `release` run creates the `vX.Y.Z` tag and GitHub Release for that merge, but only if it is the sole pending release (`scripts/release-merge.mjs`).

The artifact is the tagged repository tree; nothing is published to a registry.

## One-time repository setup

None of these settings can be read from the repository, so CI cannot catch a missing one. Do them once after creating the repo on GitHub.

- [ ] **Allow Actions to open pull requests.** Settings → Actions → General → Workflow permissions → tick "Allow GitHub Actions to create and approve pull requests". Without it release-please cannot open its release PR.
- [ ] **Protect `main`.** Settings → Rules (or Branches) → require a pull request and require the `check` status check to pass before merging.
- [ ] **Close and reopen the release PR before merging it.** release-please runs on the implicit `GITHUB_TOKEN`, and events created with that token start no workflow runs. The release PR therefore reports no required checks until you close and reopen it (`check.yml` runs on `reopened`). Every later update release-please pushes to that PR has the same problem, so reopen it again after each update, or at least once more on the final head right before merging. Instead of reopening, you can run the check on the release branch, which reports on the head commit: `gh workflow run check.yml --ref release-please--branches--main` (use the branch shown on the PR if its name differs).

`publish_to_npm` is off, so `package.json` is `"private": true` and no npm setup is needed. Pi users install from git.

## Recovery

If validation of a release merge fails transiently, rerun that merge's failed workflow. A new green push, or a manual run on a later commit, does not authorize releasing the older pending merge: `scripts/release-merge.mjs` allows a release only for the one pending release PR that merged as the commit being released.
