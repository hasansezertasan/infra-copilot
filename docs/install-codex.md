# Installing infra-copilot on Codex CLI

Per-host capabilities — including the fact that Codex exposes **no plugin-defined slash
commands** — live in [`hosts.md`](../skills/infra-copilot/references/hosts.md). This page
covers install only.

## Install

Three separate things, and skipping any one leaves the plugin invisible:

```sh
codex plugin marketplace add hasansezertasan/infra-copilot
```

1. Add the marketplace with the command above.
2. **Enable the plugin** from `/plugins`. Adding a marketplace does not enable what is in it.
3. **Start a new session.** Plugins are resolved at session start.

## Update

Two commands, and running only the first updates nothing you are running:

```sh
codex plugin marketplace upgrade infra-copilot
codex plugin add infra-copilot@infra-copilot
```

Marketplace state and the installed package cache are distinct. The first refreshes the
catalog Codex knows about; the second installs the refreshed version. Then restart.

## Invoke

**Natural language only.** Ask Codex to use infra-copilot for setup, import, add, or
status — for example "use infra-copilot to adopt our existing Cloudflare DNS records".

`/infra-setup` and the other slash commands **do not exist on Codex.** They are Claude
Code and Antigravity adapters. A missing-command error here is the host working as
documented, not a broken install; see the `Plugin slash commands` column in
[`hosts.md`](../skills/infra-copilot/references/hosts.md).

## Verify

Ask for infra status in any directory. In a repo with no config it reports the config as
missing and stops, naming `setup` as the skill that creates one — `status` is read-only
and never offers to scaffold. No response at all means the plugin was added but never
enabled, or the session predates it.
