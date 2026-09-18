# Installing infra-copilot on Antigravity

Per-host capabilities — question tool, slash-command support — live in
[`hosts.md`](../skills/infra-copilot/references/hosts.md). This page covers install only.

There is no `.antigravity/` directory in this repository: Antigravity installs the plugin
straight from the Git URL, so no host-specific manifest is generated for it.

## Install

```sh
agy plugin install https://github.com/hasansezertasan/infra-copilot
```

## Update

Reinstall the plugin with the same command, then **restart**. There is no in-place
`update` verb — reinstalling is the update path.

## Invoke

`/infra-setup`, `/infra-import`, `/infra-add`, `/infra-status`, or natural language.

## Verify

Run `/infra-status` in any directory. In a repo with no config it reports the config as
missing and stops, naming `setup` as the skill that creates one — `status` is read-only
and never offers to scaffold. That report is a working install.
