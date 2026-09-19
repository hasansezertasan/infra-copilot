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
  (#18). Which hosts ship one, the discovery path each uses, and the evidence behind
  every exclusion are recorded in
  [`hosts.md`](../skills/infra-copilot/references/hosts.md) — repeating them here would
  be a second copy that nothing keeps in step when a host graduates. A test fails if a
  manifest appears at a path no row marks shipped.
  ([#42](https://github.com/hasansezertasan/infra-copilot/issues/42))
- **The subagent ships to one host.** `infra-auditor` runs the scan in an isolated
  context on Claude. Claude and Antigravity both auto-discover root `agents/` and neither
  honours an override, and their `tools` shapes are incompatible, so the file carries
  Claude's and Antigravity goes without. Its read-only promise is still unenforced for
  the reason above — it is context isolation, not a sandbox.
  ([#19](https://github.com/hasansezertasan/infra-copilot/issues/19))
- **Host capability records are hand-maintained and unverifiable.** `hosts.md` states each
  host's native question tool and its modes and choice counts, and the protocol's
  *Asking a decision* rule reads it. Nothing can prove a row is true: no host publishes a
  machine-readable capability record, so validation gates citation and existence only.
  A row that *understates* a host degrades the question to text, which is the safe
  direction. A row that *overstates* one does not: the rule sees the request clear the
  record and issues a native call the host then rejects. ([#12](https://github.com/hasansezertasan/infra-copilot/issues/12))
- **Per-skill install exists on OpenCode only.** `--skill status --skill infra-copilot`
  installs one skill and its closure there. The other three hosts install the whole
  plugin because their native mechanisms offer no per-skill selection; a repo-specific
  installer that added one is explicitly not planned.

  ([#20](https://github.com/hasansezertasan/infra-copilot/issues/20))

## Not planned

- **A repo-specific multi-host installer.** Each host's native mechanism is the supported
  path. Installing by cloning into a hidden directory, copying, or symlinking is not
  supported and will not be documented.
- **A second behavioral authority.** Host packages stay adapters. Any rule that matters
  belongs in `.ai-rulez/skills/infra-copilot/references/`.
