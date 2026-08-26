# infra-copilot — canonical entry point for every check CI runs.
#
# `make check` is CI parity: if it passes locally it passes in .github/workflows.
# The pins below are the single source of truth for the tool versions this
# repository invokes; scripts/validate.py asserts README.md documents the same
# ones. Bump them here and nowhere else.

AI_RULEZ_VERSION := 4.11.3
SKILLS_VERSION   := 1.5.23

PYTHON ?= python3
AI_RULEZ := npx --yes ai-rulez@$(AI_RULEZ_VERSION)
SKILLS   := npx --yes skills@$(SKILLS_VERSION)

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

.PHONY: test
test:  ## Run the repository validator tests
	$(PYTHON) -m unittest discover -s tests

# Installs this repo into itself to prove the OpenCode payload is complete, then
# removes the two artifacts that produces. Self-cleaning matters because this
# target now runs on developer machines and not only on a throwaway CI runner:
# `.agents/skills/` and `skills-lock.json` are untracked build output, while
# `.agents/plugins/marketplace.json` is tracked and must survive.
.PHONY: smoke-opencode
smoke-opencode:  ## Install into this repo and assert the OpenCode skill payload
	@trap 'rm -rf .agents/skills skills-lock.json' EXIT; \
	$(SKILLS) add . --agent opencode --skill '*' -y --copy; \
	expected=$$(find skills -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d '[:space:]'); \
	actual=$$(find .agents/skills -name SKILL.md | wc -l | tr -d '[:space:]'); \
	if [ "$$actual" != "$$expected" ]; then \
	  echo "smoke-opencode: installed $$actual SKILL.md, expected $$expected (one per skills/*/)" >&2; \
	  exit 1; \
	fi; \
	test -f .agents/skills/infra-copilot/references/protocol.md; \
	test -f .agents/skills/infra-copilot/references/decisions.md.example; \
	echo "smoke-opencode: $$actual skills installed, references present"

.PHONY: check
check: validate test smoke-opencode  ## Everything CI runs
	@echo "all checks passed"
