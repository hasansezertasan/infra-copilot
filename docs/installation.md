# Installation

Infra Copilot publishes the same skills to five runtimes: Claude Code, Codex, OpenCode, Pi and Antigravity. The skills are generated into `skills/` and the plugin manifests at the repository root.

Your agent can do the install. Copy this prompt into your coding agent:

```text
Install the infra-copilot skills: pick the best installation method for
you from https://github.com/hasansezertasan/infra-copilot/blob/main/docs/installation.md

Stop once the install is confirmed and tell me how to invoke it. Do not start setup.
```

The prompt points at this page, not at a command, so the routes below can change without the prompt changing. It stops after the install on purpose: `setup` creates cloud and repository state and needs credentials only you can mint, so you start it yourself, in the repository you mean to bootstrap.

## For agents reading this page

You were pointed here to install the skills. Do this:

1. Pick the route in the table below that you can run yourself on your platform. Prefer a route native to your runtime over a manual clone.
2. If a route needs a slash command or an interactive step you cannot run, give the user the exact command and ask them to run it. Do not guess at another command.
3. Confirm the install with the route's confirm step.
4. Plugin and skills installs usually load in a new session, not in the conversation that installed them. If the skills are not available to you now, you may read `skills/<name>/SKILL.md` from a clone of this repository (a temporary clone is fine) to do the user's task in this conversation, and tell the user to start a new session so the installed skills load next time. Reading a clone is not an install: it registers nothing for later sessions.
5. If a route fails, fall back to the manual route. Report the install as done only after the route's confirm step succeeds. Never report it as done because you read a `SKILL.md` from a clone.
6. Do not install other agent skills or switch to a different route unless this one fails.
7. Do not run `setup`, `import`, `prune` or `add`, and do not create repositories, change repository settings or secrets, or push. Only the install is in scope.

## Routes

| Runtime | Install | Update | Confirm |
| --- | --- | --- | --- |
| Claude Code | `claude plugin marketplace add hasansezertasan/infra-copilot`, then `claude plugin install infra-copilot@infra-copilot` (in a session: `/plugin marketplace add hasansezertasan/infra-copilot` and `/plugin install infra-copilot@infra-copilot`) | `claude plugin marketplace update infra-copilot`, then `claude plugin update infra-copilot@infra-copilot` | `claude plugin list` shows the plugin and its version; run `/reload-plugins` or start a new session to load it |
| Codex | clone this repository, then `codex plugin marketplace add /absolute/path/to/infra-copilot` and `codex plugin add infra-copilot@infra-copilot`; start a new thread | pull the clone, then `codex plugin add infra-copilot@infra-copilot` again, and start a new thread (`marketplace upgrade` applies to Git marketplaces, not a local path; this update route has not been verified) | the plugin appears in Codex's plugin list in a new thread |
| OpenCode | git only; see [OpenCode](#opencode) | `git pull` in the clone | the skills are offered by OpenCode's `skill` tool in a new session |
| Pi | `pi install git:github.com/hasansezertasan/infra-copilot` (not published to npm) | `pi update git:github.com/hasansezertasan/infra-copilot` (a bare `pi update` updates Pi itself), then restart Pi or reload resources | invoke one of the skills with `/skill:<name>` |
| Antigravity | git only; see [Antigravity](#antigravity) | reinstall with the same command, then restart | `agy plugin list` shows the plugin as installed and enabled; restart Antigravity to load it |
| Manual | clone this repository, then copy `skills/*` into your agent's skills directory (reading `skills/<name>/SKILL.md` from the clone only lets you use the skills in the current conversation; it is not an install) | `git pull` in the clone, then copy `skills/*` again | `for d in <clone>/skills/*/; do diff -r "$d" "<destination>/$(basename "$d")"; done` prints nothing (compare skill by skill: the destination may hold skills from other sources) |

Per-host detail, scope and caveats: [Claude Code](install-claude-code.md), [Codex](install-codex.md), [Antigravity](install-antigravity.md), [OpenCode](install-opencode.md). Per-host capabilities (question tool, slash-command support) are recorded once in [`hosts.md`](../skills/infra-copilot/references/hosts.md).

The Pi package declares the `pi-package` keyword and a `pi.skills` entry per skill in `package.json`, written by `npm run generate`. To compare an installed version with the latest, use the version in `.claude-plugin/plugin.json` or the repository's latest GitHub release.

## OpenCode

OpenCode installs from git only. Clone the repository, then make each skill discoverable. OpenCode searches `.agents/skills/<name>/SKILL.md` in the project and `~/.agents/skills/<name>/SKILL.md` globally, so link every folder under `skills/` into one of those:

```sh
git clone https://github.com/hasansezertasan/infra-copilot
mkdir -p ~/.agents/skills
for skill in infra-copilot/skills/*/; do ln -s "$PWD/${skill%/}" ~/.agents/skills/; done
```

Alternatively, add the clone's `skills/` directory to OpenCode's configuration. The `skills` array comes from OpenCode's published config schema, which marks the older object form (with a `paths` key) deprecated; OpenCode's documentation pages do not describe this option, so it is unverified in practice:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": ["/absolute/path/to/infra-copilot/skills"]
}
```

To update, run `git pull` in the clone; nothing was copied.

> **Open question.** The official OpenCode documentation shows no way for an npm package to ship skills, so there is no npm route for OpenCode. If that changes, add it here.

## Antigravity

Antigravity installs the plugin straight from the Git URL, so the only artifact is the root `plugin.json` adapter. It carries the plugin name and description, and `scripts/check-repo.mjs` fails when it drifts from the generated Claude manifest.

```sh
agy plugin install https://github.com/hasansezertasan/infra-copilot
```

This installs into Antigravity's user plugin registry, so the skills are available across repositories. There is no in-place update verb: reinstall with the same command, then restart.

> **Unverified.** Installing from a Git URL has not been exercised against a remote; only `agy plugin validate` on a local clone has been run for this kind of repository, and it validates a source directory rather than proving an install. Confirm with `agy plugin list`, and prefer a supported runtime for production use until an install is verified.

## Then use it

Each request starts one skill. Say what you want in your own words.

| Ask your agent to | Skill |
| --- | --- |
| Bootstrap a new infra repo | `setup` |
| Adopt existing resources into Terraform | `import` |
| Remove resources from management | `prune` |
| Add a new managed resource | `add` |
| Report where the infra stands (read-only) | `status` |

Start with `status`: it is read-only and never offers to scaffold.
