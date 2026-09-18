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
- **Phases 5 and 6 are normally not applicable.** Import only matters if resources
  pre-exist, and the provider-neutral Phase 6 has no instances until
  `additional_providers` is populated. Once an entry or an extra Terraform leaf exists,
  its checks are real resumable state; `status` must not call an interrupted adoption
  healthy. GCP remains a template until #6 fills in its WIF runbook.

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
- **Claude Code's command-level rules cannot constrain this plugin.** `docs/policy.md`
  documents the bypasses the plugin's own guidance supplies, so no profile ships and none
  should (#14). **No rule type holds** — including `Skill()` denies, which the
  `/infra-setup`, `/infra-import` and `/infra-add` commands reach around. The gaps that
  remain are not documentation gaps: they need sandbox isolation, or the agent running as
  a **separate lower-privilege HCP principal** — not a scope removed from the user token
  `terraform login` mints, which has none ([#52](https://github.com/hasansezertasan/infra-copilot/issues/52)).
  Per-plugin restriction on Codex and Antigravity is separately unverified.
- **`status`'s read-only promise is unenforced, and the subagent did not fix that.** The
  scan runs manifest-defined shell checks, so it needs `Bash`, and `Bash` writes files — removing
  `Edit`/`Write` narrows the surface without creating a boundary, and removing `Bash`
  stops the scan working. `infra-auditor` shipped for the context isolation (#19); only a
  sandboxed command runner would enforce the promise.
  ([#19](https://github.com/hasansezertasan/infra-copilot/issues/19))
- **The SessionStart hook is still Claude-only.** It ships and is auto-discovered there
  (#18). Antigravity's *discovery* path is now known — the root `hooks.json`, not
  `hooks/hooks.json` — but discovery is not execution: a probe hook reduced to `touch`
  never fired, in print mode or an interactive TUI session. Codex gates plugin hooks
  behind an experimental flag *and* an interactive trust review, and none fired from any
  candidate path. OpenCode has no hook mechanism. All three are recorded `verified:
  false` in `hosts.yaml` with the evidence, and a test fails if a manifest is shipped at
  a path no record verifies.
  ([#42](https://github.com/hasansezertasan/infra-copilot/issues/42))
- **The subagent ships to one host.** `infra-auditor` runs the scan in an isolated
  context on Claude. Claude and Antigravity both auto-discover root `agents/` and neither
  honours an override, and their `tools` shapes are incompatible, so the file carries
  Claude's and Antigravity goes without. Its read-only promise is still unenforced for
  the reason above — it is context isolation, not a sandbox.
  ([#19](https://github.com/hasansezertasan/infra-copilot/issues/19))
- **Only Claude's question tool is verified.** `protocol.md` now specifies what a
  *choosing* step does, and `hosts.yaml` carries a `question_tool` record per host. Only
  Claude's is exercised, so the other three always take the text fallback; their modes
  and choice limits were read off a tool name, not run. A row graduates by being
  exercised. ([#12](https://github.com/hasansezertasan/infra-copilot/issues/12))
- **Install is all-or-nothing.** There is no way to install `status` alone.
  ([#20](https://github.com/hasansezertasan/infra-copilot/issues/20))

## Not planned

- **A repo-specific multi-host installer.** Each host's native mechanism is the supported
  path. Installing by cloning into a hidden directory, copying, or symlinking is not
  supported and will not be documented.
- **A second behavioral authority.** Host packages stay adapters. Any rule that matters
  belongs in `.ai-rulez/skills/infra-copilot/references/`.
