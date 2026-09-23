<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:c60c410947ce1755750a683ece83ac68054f29994b55905b015eb0576dcb9e49
Source-Hash: blake3:09c61f5dbe9e5fc5cec13d71908b4d6239ede990746de888a691725a84afd15c
Schema-Version: v1
-->

# Host capability records (shared)

`infra-copilot` ships to four hosts that differ in ways a running skill has to know
about. This file is the **single record** of those differences. Every other document —
the install guides, `README.md`, and [`protocol.md`](protocol.md) — cites it rather than
restating it, so there is one place to change when a host changes.

| Host | Native question tool | Modes | Choices | Custom input | Plugin slash commands | Install guide |
|---|---|---|---|---|---|---|
| Claude Code | `AskUserQuestion` | binary, single, multi | 2–4 | host-supplied | yes | `docs/install-claude-code.md` |
| Codex CLI | `request_user_input` | binary, single | 2–3 | host-supplied | **no** | `docs/install-codex.md` |
| Antigravity | `ask_question` | binary, single, multi | 2–4 | not recorded | yes | `docs/install-antigravity.md` |
| OpenCode | `question` | binary, single, multi | 2–4 | not recorded | no — skills load through the native `skill` tool | `docs/install-opencode.md` |

**Custom input** says who supplies the free-text `Other` option, because it decides what
the **Choices** ceiling counts:

- `host-supplied` — the tool adds `Other` itself and the caller must **not** send one.
  Three explicit options on Codex is three choices, not four.
- `caller-supplied` or `not recorded` — send `Other` as an explicit option, and count it.

`not recorded` means nobody has verified that capability on that host, so it is treated
as `caller-supplied`: sending a redundant `Other` costs a duplicate line, while omitting
a needed one silently removes the escape hatch. A `not recorded` **mode or choice count**
is different — the request does not clear the record, so it is rendered as text.

**Plugin slash commands** is why the install guides differ on invocation. On Codex the
natural-language spellings are the entire public interface — `/infra-setup` does not
exist there, and reporting that as a broken install is the most likely false bug report.

## Subagent manifests ([#19](https://github.com/hasansezertasan/infra-copilot/issues/19))

One agent ships — `infra-auditor`, which runs the read-only `status` scan in its own
context. Every host below discovers subagents; they disagree on where and in what
dialect, and a wrong dialect **fails silently** on both hosts that were tested.

| Host | Discovery path | `tools` dialect | Tool names | Invocation tool | Shipped |
|---|---|---|---|---|---|
| Claude Code | `agents/` | comma string | `Read`, `Bash`, `Glob`, `Grep`, `Skill` | `Task` | **yes** |
| Antigravity | `agents/` | YAML list | `view_file`, `grep_search`, `find_by_name`, `run_command` | not recorded | no — path collision |
| Codex CLI | `.codex/agents/` | none — session tools are inherited | — | not recorded | no — not exercised |
| OpenCode | `.opencode/agents/` | bool map | `read`, `grep`, `glob`, `bash` | not recorded | no — not exercised |

**Invocation tool** is what a caller uses to reach the agent, and the delegation rule in
[`protocol.md`](protocol.md) requires it to be declared and allowed before delegating —
a shipped row says the agent exists, never that this session can reach it. `not recorded`
means nobody has established the name on that host, which is one more reason those rows
are not shipped: there would be nothing to check the availability gate against.

**Only one host per discovery directory.** Claude and Antigravity both auto-discover the
*same* root `agents/` directory and neither honours an override — an `agents` key in the
hand-authored root `plugin.json` was ignored by `agy plugin install`, and `ai-rulez`
silently drops one from the generated `.claude-plugin/plugin.json`. The directory
therefore carries Claude's dialect, and Antigravity loads nothing from it. That absence is
silent and harmless; shipping the YAML list instead would hand Claude an agent whose whole
tool grant is names it does not have.

The restriction is the *directory*, not the plugin. `.codex/agents/` and
`.opencode/agents/` are nobody else's, so those rows can graduate alongside Claude's
without displacing it — `validate.py` counts owners per resolved directory for exactly
that reason, and a global count would have made them ungraduatable. What blocks them is
that neither has been exercised, which is what their `Shipped` cell says.

How each was established, since a wrong dialect raises no error:

- Claude reads **root `agents/`**, not `.claude-plugin/agents/`. With
  `claude plugin details infra-copilot`, hiding `.claude-plugin/agents/` still reported
  `Agents (1)`; hiding root `agents/` reported `Agents (0)`.
- Antigravity needs the **YAML list**. A probe plugin written in Claude's comma-string
  form was reported `agents: 1 processed` by `agy plugin validate` and then never appeared
  in `agy agent`; re-authored as the list above, it appeared.

## Hook discovery ([#42](https://github.com/hasansezertasan/infra-copilot/issues/42))

The `SessionStart` announcement ships on Claude Code only. Every other row records a
discovery fact that was established and an execution fact that was not — discovery is not
execution, and shipping a manifest that never fires is indistinguishable from one that
works until someone needs it.

| Host | Manifest path | Matcher | Root variable | Shipped |
|---|---|---|---|---|
| Claude Code | `hooks/hooks.json` | `startup{pipe}resume{pipe}clear{pipe}compact` | `CLAUDE_PLUGIN_ROOT` | **yes** |
| Antigravity | `hooks.json` (repository **root**, not `hooks/`) | `*` | `ANTIGRAVITY_PLUGIN_ROOT` | no — never observed firing |
| Codex CLI | `hooks/hooks-codex.json` | `*` | `CODEX_PLUGIN_ROOT` | no — gated, never observed firing |
| OpenCode | — | — | — | no mechanism |

**Root variable** is the one this host exports, and a manifest may resolve its root only
from its own. The variables are not interchangeable: a Claude manifest reading
`CODEX_PLUGIN_ROOT` finds nothing, exits before running the script, and the announcement
silently disappears — which is indistinguishable from a working hook until someone looks
for it.

`{pipe}` stands for a literal `|` in the matcher: a Markdown table cell cannot carry one,
and escaping it (`\|`) would put an escape into a value that is compared byte-for-byte
against the shipped manifest.

- **Antigravity** discovers the root manifest: `agy plugin validate` reports
  `hooks: skipped (not found)` for this repository's `hooks/hooks.json` and
  `hooks: 1 processed` once a root `hooks.json` exists. Execution could not be shown — a
  probe reduced to `touch <sentinel>` never fired under `agy -p`, nor in an interactive
  TUI session driven through a pty that initialised and created a conversation. The root
  manifest also takes **no top-level keys besides `hooks`**: a `_comment` array beside it
  was counted as a second hook (`hooks: 2 processed`), which is why this rationale lives
  here rather than in that file.
- **Codex** fired no `SessionStart` hook from root `hooks.json`, `hooks/hooks.json`, or
  `hooks/hooks-codex.json`, with and without `--enable plugin_hooks`, and with
  `"hooks": "./hooks.json"` in `.codex-plugin/plugin.json`. Plugin hooks are gated behind
  that experimental flag *and* an interactive trust review ("hooks need review before they
  can run") that a non-interactive session cannot satisfy.
- **OpenCode** has no hook manifest at all; it installs by copying skills into the
  consuming repository, so there is no plugin root to discover one from.

Every host's manifest runs the one shared implementation, `hooks/session-start.sh`.
Adapters carry the discovery path and the matcher; the behaviour is not theirs to restate.

## Maintaining this table

Hand-authored: no host publishes a machine-readable capability record, so there is
nothing to generate this from. The `host-supplied` values come from each host's own tool
contract — Claude Code's `AskUserQuestion` documents that `Other` is provided
automatically and must not be listed, and Codex reported the same for
`request_user_input` while reviewing the pull request that added this file.
`scripts/validate.py` gates what it can — that every row
names a question tool, that the install guide each row names exists, that every guide
under `docs/` appears here, and that `protocol.md` still references this table and a tool
from it. It cannot verify a capability claim; only a session on that host can.

A row is **not** permission to assume the tool is available. Hosts gate tools per
session, so the rule in `protocol.md` requires the named tool to be currently declared
*and* allowed before this table's capabilities matter at all.

The subagent and hook sections above were added as sibling sections here, rather than as
a second per-host table elsewhere, for the reason this file already gives: one place to
change when a host changes. `scripts/validate.py` holds the shipped artifacts to them —
the agent manifest's dialect and declared name, each hook manifest's matcher and that it
hands `hooks/session-start.sh` to a shell — and refuses a manifest at any path a row
records as unshipped, so wiring cannot appear on a guess.
