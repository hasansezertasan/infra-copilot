# Installing infra-copilot on Claude Code

Per-host capabilities — question tool, slash-command support — live in
[`hosts.md`](../skills/infra-copilot/references/hosts.md). This page covers install only.

## Install

```sh
claude plugin marketplace add hasansezertasan/infra-copilot --scope project
claude plugin install infra-copilot --scope project
```

Two steps: the first registers the marketplace, the second installs the plugin from it.
Project scope records the plugin in `.claude/settings.json`; commit that file to share the
project-scoped enablement with teammates. It does not pin the plugin version. For a
personal install across repositories, omit `--scope project` (the default is user scope).

If the install reports **"This plugin is disabled in your settings"**, enable the
project-scoped plugin and commit the updated settings:

```sh
claude plugin enable infra-copilot@infra-copilot --scope project
```

## Update

```text
/plugin update infra-copilot
```

Then **restart the session**. Skill descriptions are read into the prompt at session
start, so a running session keeps the versions it started with.

## Invoke

`/infra-setup`, `/infra-import`, `/infra-prune`, `/infra-add`, `/infra-status`, or plain
natural language ("use infra-copilot to check where infra stands").

A `SessionStart` hook announces the plugin when the working directory carries
`.infra-copilot/config.md`, the legacy `.claude/infra-copilot.local.md`, or a
`terraform/` tree. Silence it with `INFRA_COPILOT_HOOK_DISABLE=1`.

## Verify

Run `/infra-status` in any directory. In a repo with no config it reports the config as
missing and stops, naming `setup` as the skill that creates one — `status` is read-only
and never offers to scaffold. That report is a working install; a silent no-op or an
unknown-command error is not.
