# Changelog

## 0.2.0 (unreleased)

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
- Added a per-host install guide under `docs/` for each of the four hosts, covering what
  "update" actually updates, whether a restart is required, how each host is invoked, and
  how to verify the install. `README.md` remains the index and links them; the guides cite
  `hosts.md` rather than restating capabilities, and `validate_layout` lists them.
- A skill's install closure is now derived from the links in its `SKILL.md`, so a single
  skill can be installed with what it needs: `--skill status --skill infra-copilot`.
  `make closure SKILL=<name>` prints it and `make smoke-closure` installs it.
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
