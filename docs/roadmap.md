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

- **No staleness gate on external facts.** The references hardcode 23 provider API paths, a
  dated `cf-terraforming` coverage claim, and exact tool versions. Nothing checks any of
  them against reality. ([#13](https://github.com/hasansezertasan/infra-copilot/issues/13))
- **No permissions guidance.** The skills drive three provider APIs and handle an HCP
  token; there is no `docs/policy.md` and no managed-settings template.
  ([#14](https://github.com/hasansezertasan/infra-copilot/issues/14))
- **No SessionStart hook and no subagents.** Discovery rests entirely on skill
  descriptions, and the read-only `status` scan runs in the main context.
  ([#18](https://github.com/hasansezertasan/infra-copilot/issues/18),
  [#19](https://github.com/hasansezertasan/infra-copilot/issues/19))
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
