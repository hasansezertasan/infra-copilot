---
type: Guide
title: Tech Stack
---

# Tech Stack

<!-- truth: start -->
- **Skill generation:** ai-rulez (sources in `.ai-rulez/`, generates to `skills/`, `commands/`, `.claude-plugin/`, `.codex-plugin/`)
- **Validation:** Python 3 (`scripts/validate.py`, `tests/`)
- **Build orchestration:** Make (canonical commands in `Makefile`)
- **Linting:** markdownlint-cli2
- **Host adapters:** Claude Code, Codex CLI, Antigravity
- **Target infrastructure:** Terraform, HCP Terraform, Cloudflare, GitHub
<!-- truth: end -->

## Tool versions

Pinned in `Makefile` only - the single source of truth:

- AI_RULEZ_VERSION (ai-rulez)
- SKILLS_VERSION (skills installer)
- MARKDOWNLINT_VERSION (markdownlint-cli2)

## File structure

| Path | Purpose |
|------|---------|
| `.ai-rulez/skills/` | Skill sources (edit here) |
| `.ai-rulez/commands/` | Command sources |
| `.ai-rulez/config.toml` | Plugin identity and version |
| `skills/` | Generated output (do not edit) |
| `commands/` | Generated output |
| `.claude-plugin/` | Generated Claude adapter |
| `.codex-plugin/` | Generated Codex adapter |
| `plugin.json` | Hand-authored Antigravity manifest |
| `scripts/` | Repository validators |
| `hooks/` | SessionStart hook (Claude-only) |
