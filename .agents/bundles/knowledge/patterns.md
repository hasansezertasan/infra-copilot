---
type: Pattern
title: Project Patterns
---

# Project Patterns

> Consolidated learnings extracted from completed work.
> Read this file before starting new work to prime context.
> Update this file at flow completion with elevated patterns.

<!-- truth: start -->
## Authoritative sources

- **Code conventions, architecture, gotchas:** See [AGENTS.md](../../../AGENTS.md) and [CONTRIBUTING.md](../../../CONTRIBUTING.md) — those files are the single source of truth for repository rules.
- **Canonical commands:** Run `make help` or see the Makefile — it is the only definition of tool versions and targets.

## Skill structure

Every `SKILL.md` addresses four concerns (make check fails if missing):

| Section | Answers |
|---------|---------|
| workflow | what the agent does, in order |
| guardrails | what it must not do, preconditions |
| validation | how to know it is done |
| example | one concrete, worked case |

**Exemption:** The `infra-copilot` hub skill is exempt from `example` — it routes to action skills and performs no work itself (`SECTION_EXEMPTIONS` in `scripts/validate.py`).
<!-- truth: end -->

---

## Pattern Sources

| Pattern | Source | Date |
|---------|--------|------|
