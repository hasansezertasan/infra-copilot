# Roadmap

What is deliberately not built yet, so its absence reads as a decision rather than an
oversight. Each item links to the issue that owns it.

## Known gaps in shipped guidance

- **GCP is a template, not a runbook.** `references/gcp.md` is marked *TEMPLATE — not
  active*, and its Workload Identity Federation section has a literal `...` where the
  pool, provider, attribute mapping, and trust condition belong. ([#6](https://github.com/hasansezertasan/infra-copilot/issues/6))
- **Nothing owns the post-adoption prune.** `import {}` and `moved {}` blocks are one-shot
  instructions that go inert once applied, and no skill or step removes them. Phase-5
  completion currently means the opposite of the correct end state.
  ([#9](https://github.com/hasansezertasan/infra-copilot/issues/9))
- **Phases 5 and 6 are expected-red for most repos.** Import only matters if resources
  pre-exist; GCP is a template. `status` says so rather than reporting them as failures.
  This is intended, not a gap.

## Known gaps in the repository itself

- **API endpoint paths have no staleness gate.** The references hardcode 23 provider API
  paths. The `cf-terraforming` coverage claim, both provider majors and the SHA-pinned CI
  action *are* now gated — see `scripts/upstream.json` and `make check-upstream` (#13) —
  but endpoint paths are not, because HCP Terraform publishes no machine-readable API
  schema to diff them against. Any such check would be a hand-maintained second copy of
  the same strings, rotting in step with what it checks. Recorded as a deliberate limit
  rather than a to-do.
- **Illustrative versions are deliberately ungated.** The worked `mise.toml` in
  `docs/setup.md` names example `terraform`, `gh` and `jq` versions. Their requirement is
  being exact, not current, so they are not in the upstream manifest. Not an oversight.
- **Host permission rules cannot constrain this plugin.** `docs/policy.md` documents
  four bypasses the plugin's own guidance supplies, so no profile ships and none should
  (#14). Only `Skill()` denies hold. The gaps that remain are not documentation gaps:
  they need a tool-level boundary (#19), sandbox isolation, or an HCP token scoped without
  apply permission. Per-plugin restriction on Codex and Antigravity is separately
  unverified.
- **`status`'s read-only promise is unenforced.** Only a tool-level boundary can enforce
  it — the read-only subagent below, which `docs/policy.md` now names as the sole
  mechanism that would.
  ([#19](https://github.com/hasansezertasan/infra-copilot/issues/19))
- **The SessionStart hook is Claude-only.** It ships and is auto-discovered there (#18),
  but Codex, Antigravity and OpenCode wiring is unverified and not shipped.
  ([#42](https://github.com/hasansezertasan/infra-copilot/issues/42))
- **No subagents.** The read-only, context-heavy `status` scan runs in the main context.
  ([#19](https://github.com/hasansezertasan/infra-copilot/issues/19))
- **Host question capability is undeclared.** Three commands grant `AskUserQuestion` — a
  Claude-only tool — that nothing instructs the agent to use. The *handoff* block for
  unblocking a `HUMAN` step is already specified host-neutrally in `protocol.md`; the gap is
  the undeclared per-host capability, and what a *choosing* step (which provider flavor,
  whether to adopt a discovered resource) should do where native question tools differ.
  ([#12](https://github.com/hasansezertasan/infra-copilot/issues/12))
- **Install is all-or-nothing.** There is no way to install `status` alone.
  ([#20](https://github.com/hasansezertasan/infra-copilot/issues/20))

## Not planned

- **A repo-specific multi-host installer.** Each host's native mechanism is the supported
  path. Installing by cloning into a hidden directory, copying, or symlinking is not
  supported and will not be documented.
- **A second behavioral authority.** Host packages stay adapters. Any rule that matters
  belongs in `.ai-rulez/skills/infra-copilot/references/`.
