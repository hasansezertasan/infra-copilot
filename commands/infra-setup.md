---
description: "Shortcut that loads the infra-setup skill — agent-first, human-in-the-loop bootstrap of this Terraform + HCP infra repo."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

# /infra-setup

Explicit entry point for the [`infra-setup`](../skills/infra-setup/SKILL.md) skill. This
command and the skill are **the same procedure, two surfaces** — the command is the
tab-completable trigger; the skill is what auto-loads and holds the logic. Either way you
end up executing `SKILL.md`, so there's no divergent behaviour to reconcile.

Load `../skills/infra-setup/SKILL.md` and drive it end-to-end:

1. **Resume first.** Walk `../skills/infra-setup/references/steps.yaml` and run each step's
   `check` to find where setup already is. Report `✓` for green steps; resume at the first
   red one. Never assume state from a previous session.
2. **Respect the actor split.** Execute `AGENT` steps yourself. On a `HUMAN` step, stop and
   emit the handoff block, wait for `done`, then re-run the `check` before continuing —
   never fake a signup, a dashboard click, or a secret paste.
3. **Route to the deep-dives** under `../skills/infra-setup/references/` and to the canonical
   `docs/` sections for fine print. Don't duplicate them.
4. **Stop at the done signal** in SKILL.md and hand back to `CONTRIBUTING.md`.

If `$ARGUMENTS` names a phase or provider (e.g. `cloudflare`, `phase 3`), jump straight to
that phase after the resume scan.
