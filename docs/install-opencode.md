# Installing infra-skills on OpenCode

Per-host capabilities — the native question tool, and the fact that skills load through
the `skill` tool rather than slash commands — live in
[`hosts.md`](../skills/infra/references/hosts.md). This page covers install only.

OpenCode's model is different from the other three hosts: `npx skills add` **copies or
links files into the consuming repo** rather than installing into the host. That
difference drives everything below.

## Install

Run this **in the infra repo you are bootstrapping**, not in a global location. `skills
add` installs into the project by default; `-g` selects global scope. (The `-p` flag is
for `skills update`, not `skills add`.)

```sh
npx skills add hasansezertasan/infra-skills --agent opencode --skill '*' -y
```

Then restart the session.

### Installing only `infra-status`

`infra-status` is read-only, so it is the safe thing to install when you want to audit a repo
before touching it — `infra-setup`'s description is written to trigger on "bootstrap this
repo", which is not what you want on a repo you are only inspecting.

Every action skill is a thin router over the `infra` hub skill and its
`references/` tree, so the hub is a hard dependency: installed alone, `infra-status` is a file
whose every link is broken. The installer resolves no dependencies, so name both:

```sh
npx skills add hasansezertasan/infra-skills --agent opencode \
    --skill infra-status --skill infra -y
```

Repeat `--skill` per skill; a comma-separated list matches nothing. The same shape works
for `infra-setup`, `infra-import`, `infra-prune`, and `infra-add`. `npm run smoke-closure` installs
this exact closure and
fails if it resolves to anything other than `infra-status` plus the hub, so the pairing above
cannot silently rot. (`npm run smoke-opencode` installs all six and only counts them; it
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

## Upgrading from infra-copilot

The plugin was renamed to `infra-skills`, so an existing `infra-copilot` install does not
update in place. Remove the old install by deleting the old `infra-copilot` skill folders from
`.agents/skills/`, then install `infra-skills` as above and
restart the session. The old slash commands are gone; use the skill names below.

## Invoke

Ask OpenCode to use `infra-skills`, `infra-setup`, `infra-import`, `infra-prune`, `infra-add`, or
`infra-status`. Skills load
on demand through the native `skill` tool; there are no plugin-defined slash commands.

## Verify

```sh
npx skills list
```

The skills you named should be listed. Then ask for infra status: in a repo with no
config it reports the config as missing and stops, naming `infra-setup` as the skill that
creates one — `infra-status` is read-only and never offers to scaffold.
