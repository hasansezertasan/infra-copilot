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

Fifteen of the 42 have no such header — the outputs that are not Markdown:
`.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`,
`.codex-plugin/plugin.json`, `config.md.example`, `decisions.md.example`, `steps.yaml`,
`checks/status-check-context.sh`, `checks/hcp-apply-scope.sh`, `checks/gcp-wif-trust.sh`,
`checks/hcp-bootstrap-workspaces.sh`, `checks/leaf-cloud.sh`,
`checks/hcp-current-plan.sh`, `checks/gha-latest-runs.sh`, `templates/terraform-apply.yml`, and
`templates/terraform-plan.yml` — so a missing header proves nothing.

`.ai-rulez-generated.json` is the authoritative list — 42 paths today. If a file is in
there, edit its source instead.

### What is *not* generated

Hand-authored, and safe to edit directly:

| Path | Why it is hand-authored |
|---|---|
| `plugin.json` | Antigravity manifest; `ai-rulez` does not generate this surface |
| `.agents/plugins/marketplace.json` | Codex marketplace; same reason |
| `scripts/validate.py`, `tests/` | The repository's own validators |
| `hooks/` | The SessionStart hook; `ai-rulez` has no hook support, so these are hand-authored |
| `agents/` | The `infra-auditor` subagent; `ai-rulez` has no agent surface. Which host this directory's dialect serves, and why the others go without, are recorded in [`hosts.md`](../.ai-rulez/skills/infra-copilot/references/hosts.md) |
| `Makefile`, `.github/workflows/` | Build and CI |
| `README.md`, `.github/CONTRIBUTING.md`, `AGENTS.md`, `docs/` | Documentation |

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
| `make lint` | markdownlint over the hand-authored Markdown |
| `make validate` | `ai-rulez validate`, `verify --plugin` (drift gate), `scripts/validate.py`, upstream coherence |
| `make test` | the validator tests under `tests/` |
| `make check` | the three above — what CI runs on a pull request |
| `make smoke-opencode` | installs a throwaway copy of the tree and asserts the OpenCode payload |
| `make check-all` | `check` plus the smoke test |
| `make clean` | removes `.agents/skills`, `skills-lock.json`, `__pycache__` |
| `make preflight` | checks `node`, `npm` and `python3` are present |

`smoke-opencode` is outside `check` on purpose: installing the plugin is a different
claim from the payloads being valid, so it is a separate CI job with its own signal, and
it still blocks the merge. It used to be separated for cost — `npx --yes skills@…`
resolved the installer on every run, 421 seconds against 65 for the tests — but `skills`
is pure JavaScript, and `npm ci` now installs it with the rest of the locked closure from
a cache every job shares. `ai-rulez` is the exception: its launcher pulls a ~16MB Go
binary from GitHub releases the first time each job runs it, which no npm cache holds.

`make smoke-opencode` runs against a copy of the working tree in a temp directory, so it
writes nothing into your checkout. That is deliberate: `skills add --copy` produces
`.agents/skills/` and `skills-lock.json`, and you may have your own local install of
either. If you ever do clean those up by hand, note that
`.agents/plugins/marketplace.json` is tracked and required — never delete `.agents/`
wholesale.

## Skill structure

Every `SKILL.md` addresses four concerns, and `make check` fails if one is missing:

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

## Skill descriptions

A skill's frontmatter `description` loads into the host's prompt for **every session**,
whether or not the skill is used, so the total is capped: `make check` fails above
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

## Tool versions

`package.json` is the **only** definition of the versions this repository invokes. The
`Makefile` runs `node_modules/.bin/<tool>`, so it names tools and never versions;
`scripts/validate.py` asserts every tool it runs resolves from `devDependencies`, and
rejects any `Makefile` or workflow that reintroduces a `<tool>@<version>` of its own.

Bump with `npm install <tool>@<version> --save-exact --save-dev` and commit
`package-lock.json` alongside. Renovate's native npm manager does the same, so an
existing entry stays current with no configuration.

`scripts/validate.py` scans those two files whole, comments included, so prose in
them may not spell a pin either — write `ai-rulez 4.11.3`, not `ai-rulez@4.11.3`, and
name a tool's path as `node_modules/.bin/<tool>` rather than reaching into a package.
Deciding which text was a comment meant deciding where a shell comment begins, and that
question has a whole grammar behind it; not asking it is cheaper than answering it, and
no comment here needs the `@`.

Adding a *new* tool takes one more edit: `TOOL_PACKAGES` in `scripts/validate.py`, which
lists the same three packages. The duplication is deliberate — it is what makes deleting
a tool from `devDependencies` fail instead of silently shrinking what the validator
guards (the #22 failure) — so `make check` rejects a manifest entry it does not know, and
says so by name. Renovate needs no such edit; this is only the repository's own check.

## Releasing

Releases are cut by [release-please](https://github.com/googleapis/release-please).
`.github/workflows/release.yml` runs on every push to `main`. It runs `make check-all`,
then release-please opens or updates a release PR from the Conventional Commit titles
merged since the last tag. `feat` bumps the minor version and `fix` the patch. While the
version is below 1.0, a breaking change also bumps only the minor version
(`bump-minor-pre-major`).

The release PR bumps every version copy `validate_versions` compares and adds the
`CHANGELOG.md` section, and the release workflow runs `check` on it (see *Repository
setup*). Merging it is the release: the next run of the workflow runs `check-all` on the
merged tree, then creates the `vX.Y.Z` tag and the GitHub Release. Nobody edits a version
string or a changelog heading by hand, and a tag pushed by hand publishes nothing.

The tagged repository tree is the installable artifact; there is no separate npm or
Python package to publish.

Because squash merging uses the PR title as the commit message, the PR title decides what
the release notes say. A `chore`, `docs` or `test` title releases nothing on its own.

The config lives in `.config/`: `release-please-config.json` lists the files to bump, and
`release-please-manifest.json` records the last released version.

Renovate leaves the release PR alone: it only rebases and updates the `renovate/*`
branches it created, and release-please's branch is `release-please--branches--main…`.
Renovate's `chore(deps)` titles do not bump the version, so they release nothing by
themselves.

### Repository setup

The workflow uses the default `GITHUB_TOKEN`, so there is no secret to store. It needs
one repository setting: **Settings → Actions → General → Allow GitHub Actions to create
and approve pull requests**. Without it release-please cannot open the release PR.

GitHub starts no `pull_request` workflow for a branch that `GITHUB_TOKEN` pushes, so the
release PR would show no `check` runs. A `workflow_dispatch` sent with `GITHUB_TOKEN` is
the exception, so the release workflow dispatches `check.yml` on the release branch after
every rewrite, once the regenerated commit is pushed. The runs land on the branch head
and show on the PR. A GitHub App token would also trigger them, but it is a stored
credential with write access to `main`.

`main` is protected by a ruleset: changes land by pull request, and the three `check`
jobs (`validate`, `Smoke-test the OpenCode payload`, `Validate portable paths (Windows)`)
must pass on the PR's head. Every release-please rewrite moves the head to a commit with
no checks, so the release PR cannot be merged between a rewrite and its regenerated,
checked commit.

### Recovering a release

The release is created only by the run for the release PR's own merge commit, after
`check-all` passes on it. If that run fails, or is replaced while still queued by a newer
push, no release is created. release-please then leaves the merged PR labelled
`autorelease: pending` and refuses to open the next release PR until it is resolved:

- A transient failure: re-run the failed or cancelled run for that merge commit from the
  Actions tab.
- `check-all` genuinely failed: merge the fix. The merged release PR already moved every
  version copy and the manifest to the new version, so release-please will not propose it
  again. Once the release workflow's `validate` job passes on the fix commit, create the
  release by hand on that commit, then mark the release PR as released so release-please
  continues from it:

  ```bash
  gh release create vX.Y.Z --target <fix-commit-sha> --title vX.Y.Z --generate-notes
  gh pr edit <release-pr> --remove-label "autorelease: pending" --add-label "autorelease: tagged"
  ```

### The first release

The manifest starts at `0.1.0`, the only tag, so the first release PR proposes the next
minor version, which the version copies already name. That version's `(summary)` section
in `CHANGELOG.md` was written by hand before release-please; the release PR adds its
generated section for the same version above it and leaves the summary as it is. No
release after that has a hand-written section.

## Versioning

The canonical plugin version is `[plugin].version` in `.ai-rulez/config.toml`. Four
manifests carry a copy — three generated (`.claude-plugin/marketplace.json`,
`.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`) and one hand-authored
(`.agents/plugins/marketplace.json`). `scripts/validate.py` asserts all four agree with
each other and with the newest release heading in `CHANGELOG.md`. A release heading is
any `##` heading, or a `###` heading that opens with `[`, which is how release-please
writes a patch release.

release-please bumps all five files in the release PR, including the generated
manifests. The bump also changes the source hash that `.ai-rulez-generated.json` and
every generated Markdown header record, which release-please cannot compute, so the
release workflow runs `make generate` on the PR branch and pushes the result. That keeps
`ai-rulez verify --plugin` green on the release PR.
`validate_release_please` fails any PR that adds a compared file without adding it to
`extra-files` in `.config/release-please-config.json`. Without that check, the first
failure would come on the release PR itself.

`validate_versions` discovers version strings inside those manifests, but only in two
shapes: a top-level `version`, and `plugins[*].version`. Adding another JSON manifest to
`JSON_MANIFESTS` is enough for those two locations to be compared, and a manifest there
with no version in either is reported unless it is listed in `VERSIONLESS_MANIFESTS`.

A version stored anywhere else in a JSON manifest — `metadata.version`, say — is **not**
discovered, and if the same file also has a recognised field the unrecognised copy can
drift silently behind a passing check.

**A copy anywhere else fails `make check` when it is written.**
`validate_version_locations` scans every file git tracks for the current plugin version
and reports any file outside `VERSIONED_FILES` — the manifests, `CHANGELOG.md`, and
`.ai-rulez/config.toml` — that spells it, including a `v` prefix. Tracked only, so a
local `.venv` or gitignored build output cannot fail a check CI passes. A README badge, a
shell installer, or a version-pinned command in an install doc is flagged in the commit
that adds it — once it is staged. Either drop it, or teach `validate_versions` to compare
it and add it to `VERSIONED_FILES` in the same commit.

The scan matches only the *current* version, so it catches a copy when it is added, not
after a bump leaves it stale. That is why registering it matters. If an unrelated number
happens to equal the plugin version, list the file in `UNRELATED_VERSION_FILES` with a
reason. `package-lock.json` is already listed.

## Conventions

- Branches: [Conventional Branch](https://conventional-branch.github.io/) —
  `<type>/<description>`, e.g. `feature/issue-10-makefile`.
- Commits and PR titles: [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) —
  `<type>(scope): <description>`.
- Behavior belongs in `.ai-rulez/skills/`; host manifests and commands are **adapters
  only** and must not become a second source of truth. Claude-specific `allowed-tools`
  values live in command frontmatter; workflow bodies stay host-neutral.
