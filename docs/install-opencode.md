# Installing infra-copilot on OpenCode

Per-host capabilities — the native question tool, and the fact that skills load through
the `skill` tool rather than slash commands — live in
[`hosts.md`](../skills/infra-copilot/references/hosts.md). This page covers install only.

OpenCode's model is different from the other three hosts: `npx skills add` **copies or
links files into the consuming repo** rather than installing into the host. That
difference drives everything below.

## Install

Run this **in the infra repo you are bootstrapping**, not in a global location:

```sh
npx skills add hasansezertasan/infra-copilot --agent opencode --skill '*' -y
```

Then restart the session.

### Installing only `status`

`status` is read-only, so it is the safe thing to install when you want to audit a repo
before touching it — `setup`'s description is written to trigger on "bootstrap this
repo", which is not what you want on a repo you are only inspecting.

Every action skill is a thin router over the `infra-copilot` hub skill and its
`references/` tree, so the hub is a hard dependency: installed alone, `status` is a file
whose every link is broken. The installer resolves no dependencies, so name both:

```sh
npx skills add hasansezertasan/infra-copilot --agent opencode \
    --skill status --skill infra-copilot -y
```

Repeat `--skill` per skill; a comma-separated list matches nothing. The same shape works
for `setup`, `import`, `prune`, and `add`. `make smoke-closure` installs this exact closure and
fails if it resolves to anything other than `status` plus the hub, so the pairing above
cannot silently rot. (`make smoke-opencode` installs all six and only counts them; it
would not notice.)

## Update

```sh
npx skills update -p
```

`-p` is project scope, matching where `add` wrote. Then restart.

Because files were copied into your repo, an update **rewrites files under your working
tree** — review the diff like any other change.

## What lands in git

`skills add` writes `.agents/skills/` and `skills-lock.json` into the consuming repo.
Decide deliberately: commit the lockfile for a reproducible install, and either commit or
ignore `.agents/skills/` depending on whether you want the payload vendored. Neither is
wrong; leaving them untracked and unmentioned is what causes surprise diffs.

## Invoke

Ask OpenCode to use `infra-copilot`, `setup`, `import`, `prune`, `add`, or `status`. Skills load
on demand through the native `skill` tool; there are no plugin-defined slash commands.

## Verify

```sh
npx skills list
```

The skills you named should be listed. Then ask for infra status: in a repo with no
config it reports the config as missing and stops, naming `setup` as the skill that
creates one — `status` is read-only and never offers to scaffold.
