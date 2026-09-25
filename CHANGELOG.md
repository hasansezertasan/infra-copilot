# Changelog

## [0.2.0](https://github.com/hasansezertasan/infra-copilot/compare/v0.1.0...v0.2.0) (2026-09-24)


### Features

* add a `prune` skill and make phase-5 completion mean "no spent blocks" ([#73](https://github.com/hasansezertasan/infra-copilot/issues/73)) ([03032c0](https://github.com/hasansezertasan/infra-copilot/commit/03032c09281e52fc1923a2670658ac1062fe6604))
* add a Makefile and make it the only definition of tool pins ([#27](https://github.com/hasansezertasan/infra-copilot/issues/27)) ([206a25b](https://github.com/hasansezertasan/infra-copilot/commit/206a25be91b4fb3bf6df535c1964016a9ce96006))
* add a per-host capability record, per-host install guides, and derived skill closures ([#72](https://github.com/hasansezertasan/infra-copilot/issues/72)) ([302f8fd](https://github.com/hasansezertasan/infra-copilot/commit/302f8fdd3040ab98f61e97db34398aabcc40fae6))
* add a per-host capability table and the parity gate that proves it ([#74](https://github.com/hasansezertasan/infra-copilot/issues/74)) ([02c724e](https://github.com/hasansezertasan/infra-copilot/commit/02c724ed60134027598db81a58ee95d10f0e40b5))
* add a plan-only HCP identity step and the check that proves it ([#58](https://github.com/hasansezertasan/infra-copilot/issues/58)) ([1c8265a](https://github.com/hasansezertasan/infra-copilot/commit/1c8265a14f43533dafae2f2a0ba50ef9c71aab53))
* add agent-agnostic tooling ([#4](https://github.com/hasansezertasan/infra-copilot/issues/4)) ([d2831e1](https://github.com/hasansezertasan/infra-copilot/commit/d2831e1592682970618fb51b73336dbfabf423c3))
* add lint, clean, release and preflight targets, and unblock CI ([#45](https://github.com/hasansezertasan/infra-copilot/issues/45)) ([8c79888](https://github.com/hasansezertasan/infra-copilot/commit/8c7988881f8d66f6ff4102f4617cca45b5727fcb))
* announce the plugin with a static SessionStart hook ([#43](https://github.com/hasansezertasan/infra-copilot/issues/43)) ([ba093f9](https://github.com/hasansezertasan/infra-copilot/commit/ba093f9bcdd5a37e82759d4357618d734a7d2087))
* assert the HCP status check context matches what HCP publishes ([#34](https://github.com/hasansezertasan/infra-copilot/issues/34)) ([5ca32f6](https://github.com/hasansezertasan/infra-copilot/commit/5ca32f66d89da64f10d9710e294a3f89b4598b4d))
* gate the external versions cited in shipped guidance ([#39](https://github.com/hasansezertasan/infra-copilot/issues/39)) ([3ce6c6b](https://github.com/hasansezertasan/infra-copilot/commit/3ce6c6bb580bdef826d32c0e5e3599c635951497))
* **gcp:** make the GCP reference an active WIF runbook and verify the trust scope ([#79](https://github.com/hasansezertasan/infra-copilot/issues/79)) ([310f154](https://github.com/hasansezertasan/infra-copilot/commit/310f154eb46cb0bd693cd182ddbe5b66e6e68011))
* make new-provider adoption resumable ([#61](https://github.com/hasansezertasan/infra-copilot/issues/61)) ([8f1e416](https://github.com/hasansezertasan/infra-copilot/commit/8f1e416a7b0041e8704c18efa9ccfc378f226749))
* pin the toolchain instead of checking a version floor ([#7](https://github.com/hasansezertasan/infra-copilot/issues/7)) ([5b9642c](https://github.com/hasansezertasan/infra-copilot/commit/5b9642c8fc1eb99d944db1c2620d2ef9de62549e))
* preserve hand-edited scaffold regions with customization markers ([#54](https://github.com/hasansezertasan/infra-copilot/issues/54)) ([cc216b1](https://github.com/hasansezertasan/infra-copilot/commit/cc216b1f299e5130c369fda518f4b8d67dfd5be1))
* **status:** report latest GitHub Actions runs in object-storage mode ([#81](https://github.com/hasansezertasan/infra-copilot/issues/81)) ([5f3a487](https://github.com/hasansezertasan/infra-copilot/commit/5f3a4876aa8e626c9755a1fcb49a3f6f7417d0c6))
* support object-storage backend as alternative to HCP ([#66](https://github.com/hasansezertasan/infra-copilot/issues/66)) ([dae0821](https://github.com/hasansezertasan/infra-copilot/commit/dae082102f50628f58b28a666bea3d432ab85602))
* **upstream:** validate shipped HCP API paths against go-tfe's OpenAPI spec ([#80](https://github.com/hasansezertasan/infra-copilot/issues/80)) ([c24b4a6](https://github.com/hasansezertasan/infra-copilot/commit/c24b4a6f31cbdda94113d0179ef50b1d1cd4c43e))
* **validate:** flag plugin version copies outside compared files ([#82](https://github.com/hasansezertasan/infra-copilot/issues/82)) ([f7d39ff](https://github.com/hasansezertasan/infra-copilot/commit/f7d39ff56d924b63d3478f6deb779702c7d91b75))


### Bug Fixes

* address post-merge review findings on object-storage backend ([#71](https://github.com/hasansezertasan/infra-copilot/issues/71)) ([65c76b8](https://github.com/hasansezertasan/infra-copilot/commit/65c76b8328fcc49f516c13d73c93481fce39f773))
* address the review that landed after [#45](https://github.com/hasansezertasan/infra-copilot/issues/45) merged ([#48](https://github.com/hasansezertasan/infra-copilot/issues/48)) ([a6e77fd](https://github.com/hasansezertasan/infra-copilot/commit/a6e77fd370f113b5ec799320e146de6d2873dd17))
* **agents:** repair wayfinding commands and drop the lease protocol ([#78](https://github.com/hasansezertasan/infra-copilot/issues/78)) ([ec853ca](https://github.com/hasansezertasan/infra-copilot/commit/ec853cabd4760cfb4a5f295b8834a6bab083c99d))
* check the CHANGELOG version and discover manifests instead of listing them ([#32](https://github.com/hasansezertasan/infra-copilot/issues/32)) ([c96d950](https://github.com/hasansezertasan/infra-copilot/commit/c96d9505a3df240a32c9dd7c3585207d6eb1e482))
* gate the INFRA_COPILOT_REFERENCES export ([#38](https://github.com/hasansezertasan/infra-copilot/issues/38)) ([a144978](https://github.com/hasansezertasan/infra-copilot/commit/a14497846d4218345eb1e1957aba31e9e3f274b1))
* make template bootstrap portable ([#46](https://github.com/hasansezertasan/infra-copilot/issues/46)) ([a987333](https://github.com/hasansezertasan/infra-copilot/commit/a9873331c6b3e0513d7eb5a91d03f5d13fb5cbcb))
* make toolchain bootstrap resumable ([#41](https://github.com/hasansezertasan/infra-copilot/issues/41)) ([faf3ee1](https://github.com/hasansezertasan/infra-copilot/commit/faf3ee173ab0b29aec96f3a21d55c3e928afb41e))
* preserve PATH in repo config sync check ([#51](https://github.com/hasansezertasan/infra-copilot/issues/51)) ([2b610f2](https://github.com/hasansezertasan/infra-copilot/commit/2b610f247663a33ce5a31b0cd48de37683bed612))
* **release:** approve the release PR's check run instead of dispatching it ([#86](https://github.com/hasansezertasan/infra-copilot/issues/86)) ([6b2ef4b](https://github.com/hasansezertasan/infra-copilot/commit/6b2ef4bc08bd1dc252643b2c7f642790a616ccbe))
* require markers to be real comments sitting inside the frontmatter ([#57](https://github.com/hasansezertasan/infra-copilot/issues/57)) ([3bb510c](https://github.com/hasansezertasan/infra-copilot/commit/3bb510c6619757510e3043194298d770a5a565a1))
* verify each open PR independently, and scope candidates to main ([#35](https://github.com/hasansezertasan/infra-copilot/issues/35)) ([03a9da0](https://github.com/hasansezertasan/infra-copilot/commit/03a9da0824853c5f952e52016736fad2f8b72268))


### Performance Improvements

* halve the per-session cost of skill descriptions ([#44](https://github.com/hasansezertasan/infra-copilot/issues/44)) ([142d01f](https://github.com/hasansezertasan/infra-copilot/commit/142d01fd9eae33c14ed9bdc4d38be7951d6c45cd))

## 0.2.0 (summary)

- `references/gcp.md` is now a runbook rather than a template: the Workload Identity
  Federation setup is complete (trust scoped to one HCP organization and workspace, the
  `TFC_GCP_*` variable inventory, no `credentials` argument for a single configuration),
  and it documents the adoption hazards found on a real keyless adoption —
  `disable_on_destroy`, authoritative IAM resources, the self-managing identity, the
  project-wide effective ceiling, and Google-managed resources to exclude.
  `references/migration.md` fixes the `google_storage_bucket` import ID, tabulates GCP
  import IDs, and adds the `-generate-config-out` failure modes and a verification
  checklist.
- Added the `new-provider-gcp-wif-trust` Phase 6 step and `checks/gcp-wif-trust.sh`,
  which verify from the workspace's own `TFC_GCP_*` variables that the WIF provider's
  issuer and attribute condition bind the HCP organization and workspace and that only
  that pool can impersonate the service accounts. `new-provider-decision` now also
  requires a locked `<provider> authentication` row, for every provider, and in HCP mode
  a Workload Identity Federation choice must match the credential inventory.
- Skills split by function into five routers over a shared core:
  - `setup` (`/infra-setup`) — greenfield bootstrap, phases 0-4.
  - `import` (`/infra-import`) — adopt existing provider resources without recreating, phase 5.
  - `prune` (`/infra-prune`) — remove the spent one-shot `import {}` / `moved {}` blocks an
    adoption leaves behind, once their apply has landed, phase 5.
  - `add` (`/infra-add`) — grow a bootstrapped repo: new repo/resource/provider, phase 6.
  - `status` (`/infra-status`) — read-only scan of the whole manifest → verdict + next skill.
- `.ai-rulez/skills/infra-copilot/references/` holds the single source of truth: `steps.yaml`
  (phase-tagged manifest), `protocol.md` (actor model, handoff, resume, preflight),
  `config.md`, provider deep-dives, and runbooks.
- Added Claude Code, Codex, Antigravity, and OpenCode packaging from the same canonical
  skills. Generated artifacts are managed with `ai-rulez`; CI verifies generated-file
  drift and local links.
- Fixed the phase-5 `migrate-import` check, which required a pending `will be imported`
  and so went permanently red once the migration finished; it now also accepts the
  post-apply no-op plan, and reads cf-terraforming output as `generated*.tf` rather than a
  single hardcoded `generated.tf`.
- Added `references/hosts.md`, the single per-host capability record (native question tool,
  modes, choice counts, slash-command support), and a **Asking a decision** section in
  `protocol.md` that reads it: use the host's native question tool only when that tool is
  declared, allowed, and recorded as supporting the request — otherwise render the same
  request as text. This gives the `AskUserQuestion` grant in `commands/` a consumer.
- `make check-upstream` now checks every HCP API path the shipped guidance calls against
  the OpenAPI spec `hashicorp/go-tfe` ships, as of its latest release. Paths are compared
  by shape, so `$ORG`, `<id>` and `{organization_name}` need no mapping. A missing path is
  reported for review rather than as a removal, because the spec omits documented
  endpoints — the run `discard` and `cancel` actions, recorded in `scripts/upstream.json`
  with their docs links.
- Added a per-host install guide under `docs/` for each of the four hosts, covering what
  "update" actually updates, whether a restart is required, how each host is invoked, and
  how to verify the install. `README.md` remains the index and links them; the guides cite
  `hosts.md` rather than restating capabilities, and `validate_layout` lists them.
- A skill's install closure is now derived from the links in its `SKILL.md`, so a single
  skill can be installed with what it needs: `--skill status --skill infra-copilot`.
  `make closure SKILL=<name>` prints it and `make smoke-closure` installs it.
- Ancestry that git cannot evaluate — a shallow clone missing an older commit — reports
  `?` rather than "not an ancestor", which had read as an unfinished import.
- The scan requires a leaf directory (`terraform/<leaf>/<file>`), so a stray
  `terraform/main.tf` no longer reports a block the runbook has no leaf to process; and an
  empty `"import": []` collection is a key with no block under it, not a leftover.
- Backend-specific prune mechanics live only in `docs/prune.md`. The manifest `run:`, the
  router and the command adapter say which evidence the backend allows and defer for the
  detail, rather than each carrying a copy that drifts when the procedure changes.
- `migrate-import` is tri-state: a `gh` failure — an outage, an expired login (`gh` exits
  4), an unreadable log — now exits 2 (`?`) instead of 1, so an absence of evidence stops
  being reported as an unfinished import.
- The phase-5 completion predicate reads the leaf holding the blocks rather than always
  Cloudflare, so an applied HCP GitHub import is no longer unrepresentable.
- The runbook's discovery matches `import /* … */ {` headers, which the scanner already
  counted, and the object-storage plan pair no longer asks for a before-plan the shipped
  workflow cannot produce on an unchanged revision.
- `prune-spent-imports` scans exactly what the runbook discovers — a leaf's root-level
  files — so a nested `terraform/<leaf>/modules/...` tree no longer holds phase 5 red with
  nothing the runbook will offer as a candidate.
- The `import` router resumes over its own two steps rather than all of phase 5, so a
  correct import no longer resumes into the prune procedure before its apply lands.
- Status reports phase 5 as `?` rather than routing to `prune` when object-storage blocks
  live outside `terraform/cloudflare`: the discriminator is that leaf's check, and no
  equivalent exists for the others.
- The HCP completion counts see imports, not moves — a pending `moved {}` plans as zero
  added, changed and destroyed — so the counts half is evidence only for `import` blocks.
- The HCL scan is string-aware in one pass, which replaces every lexical special case it
  had accumulated — the end-of-line anchor, the comment strip, the expression-position
  allow-list, the bounded header-comment state, and the rule against tracking `/* */`.
  All of them answered one question (is this position inside a string?) in five partial
  ways. A heredoc after `?` now opens like any other, a marker inside a free-standing
  comment opens nothing, and commented-out HCL is a comment, so it is no longer reported.
- The object-storage phase-5 discriminator defers to `migrate-import` instead of
  restating it: that check already reads the plan job log and requires a successful
  `apply-cloudflare` **job** the revision descends from. The prose copy checked only the
  run — which a GitHub-only run satisfies — and correlated against `target_sha`, which the
  check's own comment rules out because on a prune branch that is the prune commit.
- `prune` joins the shared protocol roster in `protocol.md`, and the closure assertion
  derives the action skills from `skills/` instead of listing them, so a new skill cannot
  be silently excluded from either again.
- Prune completion is stated per leaf: the leaf's clean post-edit plan is its signal, not
  `prune-spent-imports`, which scans every leaf and stays red until the last is pruned.
- Heredoc delimiters may contain hyphens (`<<END-JSON`), matching `checks/leaf-cloud.sh`
  and Terraform itself; without it, such a body scanned as HCL and its JavaScript reported
  as a live block.
- The object-storage prune path no longer requires local backend access: state membership
  is a pre-filter, not the evidence, so where the bucket credential lives only in GitHub
  Actions the plan pair is read from the workflow and carries the decision alone.
- The object-storage pending-vs-applied discriminator correlates the apply run with the
  import commit rather than with `HEAD`, which any earlier apply would have satisfied.
- A heredoc opener is recognized only in an expression position (after `=`, `(`, `,`, `:`
  or `[`, the five measured against terraform `fmt`), so stripping a `#` from a value like
  `command = "cat <<EOF#"` can no longer manufacture one and hide the blocks below it.
- The status runbook now names the object-storage discriminator between a pending import
  and an applied one, since `migrate-import` returns 0 for both and the surrounding
  evidence was HCP-only. It does so by deferring to that check rather than restating it:
  the check validates the leaf's own `apply-cloudflare` job and its ancestry, which a
  run-level test would not — a GitHub-only run satisfies that.
- Header block comments are followed across lines, but only from a line already shaped
  like a one-shot header. Terraform 1.16.1 `fmt` rejects `import` with the brace on the
  next line and rejects a comment line between them, so `import /* a\n b */ {` is the only
  cross-line header HCL admits and that entry condition is complete for the grammar —
  an assignment carrying `/*` still cannot start a region.
- The heredoc tag is matched unquoted, as Terraform's spec defines it (`<<`/`<<-` plus a
  bare identifier, never `<<"EOT"`): the optional quote was borrowed from shell and let
  `command = "cat <<EOF"` match on the string's own closing quote and hide every block
  below. Inline block comments in a header (`import /* see #123 */ {`) are stripped within
  a line, statelessly, so a legal header still matches.
- The HCL scan no longer tracks `/* */` across lines: an unquoted `/*` search cannot tell a comment
  opener from `target = "example.com/*"`, the canonical Cloudflare page-rule glob, and one
  of those discarded every line after it. Commented-out blocks now report as leftovers,
  which is the harmless direction and asks for a real cleanup.
- The HCL scan strips CR before matching (a consuming repo need not normalize line
  endings) and anchors heredoc openers at end of line after removing comments, so
  `# Example: <<EOF` or `cmd = "cat <<EOF"` no longer opens a phantom heredoc that hides
  every block below it.
- `prune-spent-imports` parses instead of pattern-matching: each committed blob is read
  once, `jq` decides Terraform JSON and an awk pass that tracks heredoc bodies and `/* */`
  regions decides HCL. Fixes a multiline JavaScript `import {` in a heredoc reading as a
  block, and `.tf.json` at four spaces or minified reading as clean, and retires the
  block-comment and nested-key ceilings the line regex had documented.
- Scoped pruning to leaves: one-shot blocks under `terraform/modules/` are never removed,
  and `prune-spent-imports` no longer counts them. Every consuming state reads a module's
  blocks separately and that set is not closed, so a `moved` block there is the module's
  upgrade path (Terraform calls removing one a breaking change) and an `import` block is
  spent only per consumer. Retires the module-relative address matching and the consumer
  walk that tried to prove otherwise.
- Moved consuming-repo configuration to `.infra-copilot/config.md` and design decisions to
  `.infra-copilot/decisions.md`, with templates and legacy Claude paths supported during
  migration.

## 0.1.0 (2026-08-05)

- Initial extraction of the `infra-setup` skill from an existing infra repo into a generic,
  org-agnostic Claude Code plugin.
