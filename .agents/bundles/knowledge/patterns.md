---
type: Pattern
title: Project Patterns
---

# Project Patterns

> Consolidated learnings extracted from completed work.
> Read this file before starting new work to prime context.
> Update this file at flow completion with elevated patterns.

<!-- truth: start -->
## Code Conventions

- Conventional Branch names: `<type>/<description>` (e.g., `feature/issue-10-makefile`)
- Conventional Commits: `<type>(scope): <description>`
- No AI attribution in commits, PR titles, or bodies
- Behavior belongs in `.ai-rulez/skills/`; host manifests are adapters only

## Architecture

- Four action skills (setup, import, add, status) are thin routers over one hub skill (infra-copilot)
- Hub skill's `references/` directory owns the behavior: `steps.yaml`, `protocol.md`, provider deep-dives
- State is never assumed: every run re-derives it by executing each step's `check`
- Host packages are adapters and must never become a second behavioral authority

## Gotchas

- Most of the tree is generated - check `.ai-rulez-generated.json` before editing
- 11 of 34 generated files have no header warning (JSON manifests, shell scripts)
- Never invoke `npx ai-rulez`, `python3 scripts/validate.py` directly - use `make check`
- `.agents/plugins/marketplace.json` is tracked and required - never delete `.agents/` wholesale

## Skill structure

Every `SKILL.md` addresses four concerns (make check fails if missing):

| Section | Answers |
|---------|---------|
| workflow | what the agent does, in order |
| guardrails | what it must not do, preconditions |
| validation | how to know it is done |
| example | one concrete, worked case |
<!-- truth: end -->

---

## Pattern Sources

| Pattern | Source | Date |
|---------|--------|------|
