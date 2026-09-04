---
description: "Shortcut that loads the infra-copilot add skill — grow a bootstrapped repo: add a managed repo, a new resource, or a brand-new provider, ending on a green plan."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:36118fb05d84c27feee587a29494ec7d46173e31ae612164b6b6b947d05d7deb
Source-Hash: blake3:409d2df7c4e28a8d504f5130b167e1123f7862f944e3806e7bdb0d35ee0f6b3b
Schema-Version: v1
-->

# /infra-add

Explicit entry point for the [`add`](../skills/add/SKILL.md) skill — extend an
already-bootstrapped repo. Three flavors: add a managed GitHub repo, add a new resource to
an existing provider, or adopt a brand-new provider (e.g. GCP). Run after `/infra-setup`.

Load `../skills/add/SKILL.md` and drive it:

1. **Read config first** — [`config.md`](../skills/infra-copilot/references/config.md).
2. **Pick the flavor** (managed repo · new resource · new provider) per the skill. New
   providers are a **locked-design-decision change** — decide on the record first.
3. **Respect the actor split** — App-scope changes, token mint/paste, and the provider
   decision are `HUMAN`; wiring and plans are yours.
   Contract: [`protocol.md`](../skills/infra-copilot/references/protocol.md).
4. **Done = green plan** with the new thing as **will be created**, nothing unexpectedly
   destroyed. If the thing already exists at the provider, hand to `/infra-import` instead.

If `$ARGUMENTS` names the target (e.g. `repo owner/name`, `provider gcp`), start there.
