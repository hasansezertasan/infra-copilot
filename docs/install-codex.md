# Installing infra-skills on Codex CLI

Per-host capabilities — including the fact that Codex exposes **no plugin-defined slash
commands** — live in [`hosts.md`](../skills/infra/references/hosts.md). This page
covers install only.

## Install

Codex CLI currently has no project-scope option for plugin marketplaces or installs;
plugins are installed in the user's Codex configuration and are available across repos.
If you need an install limited to one repository, Codex does not currently provide that
through its plugin installer.

Three separate things, and skipping any one leaves the plugin invisible:

```sh
codex plugin marketplace add hasansezertasan/infra-skills
```

1. Add the marketplace with the command above.
2. **Enable the plugin** from `/plugins`. Adding a marketplace does not enable what is in it.
3. **Start a new session.** Plugins are resolved at session start.

## Update

Two commands, and running only the first updates nothing you are running:

```sh
codex plugin marketplace upgrade infra-skills
codex plugin add infra-skills@infra-skills
```

Marketplace state and the installed package cache are distinct. The first refreshes the
catalog Codex knows about; the second installs the refreshed version. Then restart.

## Upgrading from infra-copilot

The plugin was renamed to `infra-skills`, so an existing `infra-copilot` install does not
update in place. Remove the old plugin with the plugin manager (`/plugins`), then install
`infra-skills` as above and
restart the session. The old slash commands are gone; use the skill names below.

## Invoke

**Natural language only.** Ask Codex to use infra-skills for setup, import, prune, add,
or status — for example "use infra-skills to adopt our existing Cloudflare DNS records".

`/infra-skills:infra-setup` and the other slash commands **do not exist on Codex.** They are Claude
Code and Antigravity adapters. A missing-command error here is the host working as
documented, not a broken install; see the `Plugin slash commands` column in
[`hosts.md`](../skills/infra/references/hosts.md).

## Verify

Ask for infra status in any directory. In a repo with no config it reports the config as
missing and stops, naming `infra-setup` as the skill that creates one — `infra-status` is read-only
and never offers to scaffold. No response at all means the plugin was added but never
enabled, or the session predates it.
