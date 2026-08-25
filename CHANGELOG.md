# Changelog

## 0.2.0 (unreleased)

- Skills split by function into four routers over a shared core:
  - `setup` (`/infra-setup`) — greenfield bootstrap, phases 0-4.
  - `import` (`/infra-import`) — adopt existing provider resources without recreating, phase 5.
  - `add` (`/infra-add`) — grow a bootstrapped repo: new repo/resource/provider, phase 6.
  - `status` (`/infra-status`) — read-only scan of the whole manifest → verdict + next skill.
- `.ai-rulez/skills/infra-copilot/references/` holds the single source of truth: `steps.yaml`
  (phase-tagged manifest), `protocol.md` (actor model, handoff, resume, preflight),
  `config.md`, provider deep-dives, and runbooks.
- Added Claude Code, Codex, Antigravity, and OpenCode packaging from the same canonical
  skills. Generated artifacts are managed with `ai-rulez`; CI verifies generated-file
  drift and local links.
- Moved consuming-repo configuration to `.infra-copilot/config.md` and design decisions to
  `.infra-copilot/decisions.md`, with templates and legacy Claude paths supported during
  migration.

## 0.1.0 (2026-08-05)

- Initial extraction of the `infra-setup` skill from an existing infra repo into a generic,
  org-agnostic Claude Code plugin.
