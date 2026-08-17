# Changelog

## 0.1.0 (unreleased)

- Initial extraction from an existing infra repo into a generic, org-agnostic plugin.
- Skills split by function into four routers over a shared core:
  - `setup` (`/infra-setup`) — greenfield bootstrap, phases 0–4.
  - `import` (`/infra-import`) — adopt existing provider resources without recreating, phase 5.
  - `add` (`/infra-add`) — grow a bootstrapped repo: new repo/resource/provider, phase 6.
  - `status` (`/infra-status`) — read-only scan of the whole manifest → verdict + next skill.
- `shared/` (plugin root) holds the single source of truth: `steps.yaml` (phase-tagged manifest),
  `protocol.md` (actor model, handoff, resume, preflight), `config.md`, provider deep-dives, `docs/`.
