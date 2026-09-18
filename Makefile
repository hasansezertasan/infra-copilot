# infra-copilot — canonical entry point for every check CI runs.
#
# `make check` is CI parity: if it passes locally it passes in .github/workflows.
# package.json pins the tool versions this repository invokes; the paths below just
# resolve what `npm ci` installed. Bump them there and nowhere else --
# scripts/validate.py asserts no Makefile or workflow reintroduces a `<tool>@<version>`.
#
# Absolute via $(CURDIR) because `smoke-opencode` runs the binary from a temp copy of
# the tree: a relative node_modules/.bin/skills would not resolve from there, and the
# failure reads as a bare "command not found" inside a directory nobody recognises.
# Every recipe quotes them for the same reason they are absolute: a checkout under a
# path with a space would otherwise run its first word and exit 127.

PYTHON ?= python3
AI_RULEZ := $(CURDIR)/node_modules/.bin/ai-rulez
SKILLS   := $(CURDIR)/node_modules/.bin/skills
MARKDOWNLINT := $(CURDIR)/node_modules/.bin/markdownlint-cli2
INSTALL_STAMP := node_modules/.install-stamp

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} \
	  /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo

# `npm ci` installs exactly the lockfile, so the transitive tree is pinned too.
#
# --include=dev because every tool here is a devDependency and npm defaults `omit` to
# `dev` when NODE_ENV=production. Without it a production-ish shell gets an install that
# exits 0 having written no binaries at all, and the stamp below would then record that
# as a success -- so every later target skips the install and fails on a missing tool.
#
# The target is a stamp rather than node_modules itself, because `npm ci` deletes the
# directory and recreates it as it goes: an install killed partway leaves node_modules
# newer than the lockfile, and a bare directory target would then call itself satisfied
# and run binaries that were never installed. Make only reaches the touch when npm ci
# exited 0, and npm ci having just deleted the directory took the old stamp with it.
$(INSTALL_STAMP): package-lock.json package.json
	npm ci --include=dev
	@touch $@

.PHONY: generate
generate: $(INSTALL_STAMP)  ## Regenerate the host packages from .ai-rulez/ (edit sources, never skills/)
	"$(AI_RULEZ)" generate --plugin

.PHONY: validate
validate: $(INSTALL_STAMP)  ## Validate the ai-rulez config, the committed payloads, links, and adapters
	"$(AI_RULEZ)" validate
	"$(AI_RULEZ)" verify --plugin
	$(PYTHON) scripts/validate.py
	$(PYTHON) scripts/check_upstream.py --offline

# Network, so deliberately not part of `check`: a rate limit must never fail a PR.
# Runs nightly in .github/workflows/upstream.yml.
.PHONY: check-upstream
check-upstream:  ## Compare audited external versions against current upstream releases
	$(PYTHON) scripts/check_upstream.py

.PHONY: test
# PYTHONDONTWRITEBYTECODE keeps __pycache__ out of the checkout; the repo has no
# .gitignore yet, so a local `make test` would otherwise leave the tree dirty.
test:  ## Run the repository validator tests
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests

# Proves the OpenCode payload is complete by installing the repository into a
# throwaway copy of itself. It runs in a temp directory on purpose: `skills add
# --copy` writes `.agents/skills/` and `skills-lock.json`, and a maintainer may
# already have their own local install of either. Deleting those would destroy
# state this target does not own, so it never writes to the real tree at all.
#
# The copy is of the working tree, so uncommitted skill edits are covered. node_modules
# is excluded from it: $(SKILLS) is an absolute path into the real checkout, so a second
# dependency tree would only be something for `skills add .` to walk. Excluded rather
# than copied and deleted, because the target now depends on $(INSTALL_STAMP) -- the
# tree is always there, and it holds ai-rulez's ~16MB binary.
.PHONY: smoke-opencode
smoke-opencode: $(INSTALL_STAMP)  ## Install into a throwaway copy and assert the OpenCode skill payload
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	mkdir "$$tmp/repo" && \
	tar --exclude node_modules -cf - . | tar -xf - -C "$$tmp/repo" && \
	rm -rf "$$tmp/repo/.agents/skills" "$$tmp/repo/skills-lock.json" && \
	cd "$$tmp/repo" && \
	"$(SKILLS)" add . --agent opencode --skill '*' -y --copy && \
	expected=$$(find skills -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d '[:space:]') && \
	actual=$$(find .agents/skills -name SKILL.md | wc -l | tr -d '[:space:]') && \
	if [ "$$actual" != "$$expected" ]; then \
	  echo "smoke-opencode: installed $$actual SKILL.md, expected $$expected (one per skills/*/)" >&2; \
	  exit 1; \
	fi && \
	test -f .agents/skills/infra-copilot/references/protocol.md && \
	test -f .agents/skills/infra-copilot/references/decisions.md.example && \
	echo "smoke-opencode: $$actual skills installed, references present"

.PHONY: preflight
preflight:  ## Check the tools every other target needs are present
	@missing=""; \
	for tool in node npm $(PYTHON); do \
	  command -v "$$tool" >/dev/null || missing="$$missing $$tool"; \
	done; \
	if [ -n "$$missing" ]; then \
	  echo "preflight: missing:$$missing" >&2; exit 1; \
	fi; \
	echo "preflight: node $$(node --version), $(PYTHON) $$($(PYTHON) --version 2>&1 | cut -d" " -f2)"

# Rules live in .markdownlint-cli2.jsonc, chosen to match the prose style already in the
# repository. Generated trees are excluded there: their content is owned by .ai-rulez/
# sources, so linting the output would report each finding once per host package.
.PHONY: lint
lint: $(INSTALL_STAMP)  ## Lint the hand-authored Markdown
	"$(MARKDOWNLINT)"

# Removes only build output. `.agents/plugins/marketplace.json` is tracked and required
# by validate_layout, so `.agents/` is never removed wholesale.
.PHONY: clean
clean:  ## Remove build artifacts from the working tree
	rm -rf .agents/skills skills-lock.json
	find . -name __pycache__ -type d -prune -not -path "./.git/*" -exec rm -rf {} +
	@echo "clean: removed .agents/skills, skills-lock.json and __pycache__"

# The canonical version is [plugin].version in .ai-rulez/config.toml; ai-rulez propagates
# it into the three generated manifests. `.agents/plugins/marketplace.json` is
# hand-authored and must be edited by hand, and CHANGELOG.md carries the heading --
# validate_versions checks all of them, so `check` fails until they agree.
#
# Read with tomllib, as .github/workflows/release.yml does: a regex over the [plugin]
# table breaks on valid TOML that ai-rulez accepts, such as a comment after the table
# header. Needs Python 3.11+, which only affects this maintainer target.
#
# generate and check-all are separate recursive invocations so an inherited -j cannot run
# them concurrently, which would let the drift verifier read files ai-rulez is rewriting.
#
# check-all, not check: `check` deliberately omits the OpenCode smoke test, so using it
# here would print "ready to tag" while the test that release.yml runs could still fail.
.PHONY: release
release:  ## Verify a release is ready to tag (see CONTRIBUTING for the bump itself)
	@version=$$($(PYTHON) -c "import sys,tomllib; \
	  sys.exit('make release needs Python 3.11+ for tomllib') if sys.version_info < (3,11) else None; \
	  print(tomllib.load(open('.ai-rulez/config.toml','rb'))['plugin']['version'])")
	@$(MAKE) generate
	@if [ -n "$$(git status --porcelain)" ]; then \
	  echo "release: generation changed the worktree, or it was already dirty:" >&2; \
	  git status --short >&2; \
	  echo "release: commit these before tagging — the tag would point at HEAD without them." >&2; \
	  exit 1; \
	fi
	@$(MAKE) check-all
	@version=$$($(PYTHON) -c "import tomllib; \
	  print(tomllib.load(open('.ai-rulez/config.toml','rb'))['plugin']['version'])"); \
	echo "release: v$$version is ready and the worktree is clean."; \
	echo "release: git tag -a v$$version -m \"infra-copilot v$$version\" && git push origin v$$version"

.PHONY: check
check: lint validate test  ## Everything CI runs on a pull request
	@echo "all checks passed"

# smoke-opencode is NOT in `check`: it installs the plugin into a throwaway copy of the
# tree, which is a different failure than "the payloads are valid" and is worth its own
# CI job and its own signal. The 421s registry tail that originally forced the split
# (measured on #43, against an on-demand package-runner download) is gone: that tail was
# `skills`, which is pure JavaScript, and `npm ci` now installs it with the rest of the
# locked closure from a cache both jobs share. One fetch is not cached -- ai-rulez ships
# a launcher that pulls its ~16MB Go binary from GitHub releases the first time a job
# runs it, which is why `make validate` still needs the network.
.PHONY: check-all
check-all: check smoke-opencode  ## check plus the OpenCode install smoke test
	@echo "all checks passed"
