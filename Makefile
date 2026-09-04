# infra-copilot — canonical entry point for every check CI runs.
#
# `make check` is CI parity: if it passes locally it passes in .github/workflows.
# The pins below are the single source of truth for the tool versions this
# repository invokes; scripts/validate.py asserts README.md documents the same
# ones. Bump them here and nowhere else.

AI_RULEZ_VERSION    := 4.11.3
SKILLS_VERSION      := 1.5.23
MARKDOWNLINT_VERSION := 0.23.2

PYTHON ?= python3
AI_RULEZ := npx --yes ai-rulez@$(AI_RULEZ_VERSION)
SKILLS   := npx --yes skills@$(SKILLS_VERSION)
MARKDOWNLINT := npx --yes markdownlint-cli2@$(MARKDOWNLINT_VERSION)

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help
help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\n"} \
	  /^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo

.PHONY: generate
generate:  ## Regenerate the host packages from .ai-rulez/ (edit sources, never skills/)
	$(AI_RULEZ) generate --plugin

.PHONY: validate
validate:  ## Validate the ai-rulez config, the committed payloads, links, and adapters
	$(AI_RULEZ) validate
	$(AI_RULEZ) verify --plugin
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
# The copy is of the working tree, so uncommitted skill edits are covered.
.PHONY: smoke-opencode
smoke-opencode:  ## Install into a throwaway copy and assert the OpenCode skill payload
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
	cp -R . "$$tmp/repo" && \
	rm -rf "$$tmp/repo/.agents/skills" "$$tmp/repo/skills-lock.json" && \
	cd "$$tmp/repo" && \
	$(SKILLS) add . --agent opencode --skill '*' -y --copy && \
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
	for tool in node npx $(PYTHON); do \
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
lint:  ## Lint the hand-authored Markdown
	$(MARKDOWNLINT)

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
.PHONY: release
release:  ## Verify a release is ready to tag (see CONTRIBUTING for the bump itself)
	@version=$$($(PYTHON) -c "import re,pathlib; \
	  t=pathlib.Path('.ai-rulez/config.toml').read_text(); \
	  m=re.search(r'^\[plugin\](.*?)(?=^\[|\Z)', t, re.M|re.S); \
	  print(re.search(r'^version\s*=\s*\"([^\"]+)\"', m.group(1), re.M).group(1))"); \
	echo "release: canonical version is $$version"; \
	$(MAKE) generate check; \
	echo "release: ready. Tag with: git tag -a v$$version -m \"infra-copilot v$$version\" && git push origin v$$version"

.PHONY: check
check: lint validate test  ## Everything CI runs on a pull request
	@echo "all checks passed"

# smoke-opencode is NOT in `check`: it downloads the skills installer from the npm
# registry, and a slow registry is a 7-minute tail on every pull request (measured on
# #43, where the tests finished in 65s and the download took 421s). It runs as its own
# CI job so validation is never gated behind it.
.PHONY: check-all
check-all: check smoke-opencode  ## check plus the OpenCode install smoke test
	@echo "all checks passed"
