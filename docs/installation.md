# Installation

Your agent is the interface. Install infra-copilot once, then ask your agent to bootstrap
or audit a Terraform + Cloudflare + GitHub infra repo; you do not run the individual
commands yourself.

Copy this prompt into your coding agent:

```text
Install the infra-copilot skills: pick the best installation method for you from
https://github.com/hasansezertasan/infra-copilot/blob/main/docs/installation.md

Stop once the install is confirmed and tell me how to invoke it. Do not start setup.
```

The prompt points at this page, not at a command, so the routes can change without the
prompt changing. It stops after the install on purpose: `setup` creates cloud and
repository state and needs credentials only you can mint, so you start it yourself, in the
repository you mean to bootstrap.

## Then use it

Each request starts one skill. Say what you want in your own words.

| Ask your agent to | Skill |
|---|---|
| Bootstrap a new infra repo | `setup` |
| Adopt existing resources into Terraform | `import` |
| Remove resources from management | `prune` |
| Add a new managed resource | `add` |
| Report where the infra stands (read-only) | `status` |

Start with `status`: it is read-only and never offers to scaffold.

## For agents reading this page

You were pointed here to install the skills. Do this:

1. Identify which host you are running in: Claude Code, Codex CLI, Antigravity or
   OpenCode. Use the matching install page below; it holds the exact commands, scope and
   caveats. Do not restate or guess them from memory.
2. If the install needs a slash command or an interactive step you cannot run, give the
   user the exact command and ask them to run it. Do not guess at another command.
3. Mind the scope. Codex and Antigravity install for the user across every repository.
   Claude Code defaults to user scope; `--scope project` writes `.claude/settings.json`
   in the current repository. OpenCode copies files into the current repository
   (`.agents/skills/`, `skills-lock.json`). Install where the page says, and tell the user
   which files changed.
4. Confirm with the page's **Verify** section. Plugin installs load in a new session, not
   in the conversation that installed them: tell the user to restart, and do not report
   the install as done until you have either verified it or said it needs a restart.
5. Do not install other skills or switch to a different host's route. Do not run `setup`,
   `import`, `prune` or `add`, and do not create repositories, change settings or secrets,
   or push. Only the install is in scope.

### Routes

| Host | Install page | Scope |
|---|---|---|
| Claude Code | [install-claude-code.md](install-claude-code.md) | project or user |
| Codex CLI | [install-codex.md](install-codex.md) | user only |
| Antigravity | [install-antigravity.md](install-antigravity.md) | user only |
| OpenCode | [install-opencode.md](install-opencode.md) | the consuming repository |

Per-host capabilities (question tool, slash-command support) are recorded once in
[`hosts.md`](../skills/infra-copilot/references/hosts.md). Tell the user which route you
used, whether you verified it, and whether a new session is needed.
