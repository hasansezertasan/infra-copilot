---
description: "Shortcut that loads the infra-copilot setup skill — agent-first, human-in-the-loop greenfield bootstrap of a Terraform + HCP + Cloudflare + GitHub SaaS infra repo."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:4cac816ee44f608e34f08e16fe13ed1db32528bb389a46990dc31191929206ca
Source-Hash: blake3:bec1f2b69ca5a7448a2c6f00c25d34c1ad6aa0422c3ed6456a0c0d998abead83
Schema-Version: v1
-->

# /infra-setup

Explicit entry point for the [`setup`](../skills/setup/SKILL.md) skill — the greenfield
bootstrap (phases 0–4). This command and the skill are **the same procedure, two
surfaces**: the command is the tab-completable trigger; the skill is what auto-loads and
holds the logic.

Load `../skills/setup/SKILL.md` and drive it end-to-end:

1. **Read config first.** Load `.infra-copilot/config.md`, or use
   `.claude/infra-copilot.local.md` as the migration fallback, and export the org vars
   (shared protocol Step 0 / [`config.md`](../skills/infra-copilot/references/config.md)) before the scan. If both
   are missing, offer to scaffold the agent-neutral path and wait.
2. **Resume first.** Walk phases 0–4 of [`steps.yaml`](../skills/infra-copilot/references/steps.yaml) and run
   each step's `check` to find where setup stands. Report `✓` for green; resume at the
   first red. Never assume state from a previous session.
3. **Respect the actor split.** Execute `AGENT` steps yourself. On a `HUMAN` step, stop and
   emit the handoff block, wait for `done`, then re-run the `check` — never fake a signup,
   a dashboard click, or a secret paste. Contract: [`protocol.md`](../skills/infra-copilot/references/protocol.md).
4. **Route to the deep-dives** under `../skills/infra-copilot/references/` for the fine print. Don't duplicate them.
5. **Stop at the done signal** in the skill. If existing resources need adopting, continue
   with `/infra-import`.

If `$ARGUMENTS` names a phase or provider (e.g. `cloudflare`, `phase 3`), jump straight to
that phase after the resume scan.
