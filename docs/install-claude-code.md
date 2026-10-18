# Installing infra-skills on Claude Code

Per-host capabilities — question tool, slash-command support — live in
[`hosts.md`](../skills/infra/references/hosts.md). This page covers install only.

## Install

```sh
claude plugin marketplace add hasansezertasan/infra-skills --scope project
claude plugin install infra-skills --scope project
```

Two steps: the first registers the marketplace, the second installs the plugin from it.
Project scope records the plugin in `.claude/settings.json`; commit that file to share the
project-scoped enablement with teammates. It does not pin the plugin version. For a
personal install across repositories, omit `--scope project` (the default is user scope).

If the install reports **"This plugin is disabled in your settings"**, check the
diagnostic for the settings file that disables it. Enable the plugin at that scope, or
remove the disabling entry there; a more-specific `local` setting overrides `project`.
For example, if the diagnostic names project settings:

```sh
claude plugin enable infra-skills@infra-skills --scope project
```

If it names `.claude/settings.local.json`, use `--scope local` instead, or remove the
disabling entry from that file.

## Update

```text
/plugin update infra-skills
```

Then **restart the session**. Skill descriptions are read into the prompt at session
start, so a running session keeps the versions it started with.

## Upgrading from infra-copilot

The plugin was renamed to `infra-skills`, so an existing `infra-copilot` install does not
update in place. Remove the old plugin with `claude plugin uninstall infra-copilot` (and remove its
marketplace entry), then install `infra-skills` as above and
restart the session. The old slash commands are gone; use the skill names below.

## Invoke

`/infra-skills:infra-setup`, `/infra-skills:infra-import`, `/infra-skills:infra-prune`,
`/infra-skills:infra-add`, `/infra-skills:infra-status`, or plain
natural language ("use infra-skills to check where infra stands").

A `SessionStart` hook announces the plugin when the working directory's `README.md` carries
the Config block markers, or the directory has a `terraform/` tree. Silence it with `INFRA_HOOK_DISABLE=1`.

## Verify

Run `/infra-skills:infra-status` in any directory. In a repo with no config it reports the config as
missing and stops, naming `infra-setup` as the skill that creates one — `infra-status` is read-only
and never offers to scaffold. That report is a working install; a silent no-op or an
unknown-command error is not.
