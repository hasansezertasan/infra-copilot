# Installing infra-copilot on Claude Code

Per-host capabilities — question tool, slash-command support — live in
[`hosts.md`](../skills/infra-copilot/references/hosts.md). This page covers install only.

## Install

```text
/plugin marketplace add hasansezertasan/infra-copilot
/plugin install infra-copilot
```

Two steps: the first registers the marketplace, the second installs the plugin from it.

## Update

```text
/plugin update infra-copilot
```

Then **restart the session**. Skill descriptions are read into the prompt at session
start, so a running session keeps the versions it started with.

## Invoke

`/infra-setup`, `/infra-import`, `/infra-add`, `/infra-status`, or plain natural language
("use infra-copilot to check where infra stands").

A `SessionStart` hook announces the plugin when the working directory carries
`.infra-copilot/config.md`, the legacy `.claude/infra-copilot.local.md`, or a
`terraform/` tree. Silence it with `INFRA_COPILOT_HOOK_DISABLE=1`.

## Verify

Run `/infra-status` in any directory. In a repo with no config it reports the config as
missing and stops, naming `setup` as the skill that creates one — `status` is read-only
and never offers to scaffold. That report is a working install; a silent no-op or an
unknown-command error is not.
