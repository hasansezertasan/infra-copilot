---
description: "Shortcut that loads the infra-copilot add skill — grow a bootstrapped repo: add a managed repo, a new resource, or a brand-new provider, ending on a green plan."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

# /infra-add

Explicit entry point for the [`add`](../skills/add/SKILL.md) skill — extend an
already-bootstrapped repo. Three flavors: add a managed GitHub repo, add a new resource to
an existing provider, or adopt a brand-new provider (e.g. GCP). Run after `/infra-setup`.

Load `../skills/add/SKILL.md` and drive it:

1. **Read config first** — [`config.md`](../shared/config.md).
2. **Pick the flavor** (managed repo · new resource · new provider) per the skill. New
   providers are a **locked-design-decision change** — decide on the record first.
3. **Respect the actor split** — App-scope changes, token mint/paste, and the provider
   decision are `HUMAN`; wiring and plans are yours.
   Contract: [`protocol.md`](../shared/protocol.md).
4. **Done = green plan** with the new thing as **will be created**, nothing unexpectedly
   destroyed. If the thing already exists at the provider, hand to `/infra-import` instead.

If `$ARGUMENTS` names the target (e.g. `repo owner/name`, `provider gcp`), start there.
