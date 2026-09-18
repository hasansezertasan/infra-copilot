# Host capability records (shared)

`infra-copilot` ships to four hosts that differ in ways a running skill has to know
about. This file is the **single record** of those differences. Every other document —
the install guides, `README.md`, and [`protocol.md`](protocol.md) — cites it rather than
restating it, so there is one place to change when a host changes.

| Host | Native question tool | Modes | Choices | Custom input | Plugin slash commands | Install guide |
|---|---|---|---|---|---|---|
| Claude Code | `AskUserQuestion` | binary, single, multi | 2–4 | yes | yes | `docs/install-claude-code.md` |
| Codex CLI | `request_user_input` | binary, single | 2–3 | not recorded | **no** | `docs/install-codex.md` |
| Antigravity | `ask_question` | binary, single, multi | 2–4 | not recorded | yes | `docs/install-antigravity.md` |
| OpenCode | `question` | binary, single, multi | 2–4 | not recorded | no — skills load through the native `skill` tool | `docs/install-opencode.md` |

`not recorded` means nobody has verified that capability on that host. What to do about it
depends on which column it appears in, and
[`protocol.md`](protocol.md#asking-a-decision) states both:

- **Modes or choices** — the request does not clear the record, so render it as text.
- **Custom input** — still use the native tool, and add `Other` as an explicit choice
  rather than relying on the host to offer a free-text field.

**Plugin slash commands** is why the install guides differ on invocation. On Codex the
natural-language spellings are the entire public interface — `/infra-setup` does not
exist there, and reporting that as a broken install is the most likely false bug report.

## Maintaining this table

Hand-authored: no host publishes a machine-readable capability record, so there is
nothing to generate this from. `scripts/validate.py` gates what it can — that every row
names a question tool, that the install guide each row names exists, that every guide
under `docs/` appears here, and that `protocol.md` still references this table and a tool
from it. It cannot verify a capability claim; only a session on that host can.

A row is **not** permission to assume the tool is available. Hosts gate tools per
session, so the rule in `protocol.md` requires the named tool to be currently declared
*and* allowed before this table's capabilities matter at all.

This is also the table to extend for other per-host dialects — subagent manifests
([#19](https://github.com/hasansezertasan/infra-copilot/issues/19)) and hook discovery
paths ([#42](https://github.com/hasansezertasan/infra-copilot/issues/42)) — as a column
or a sibling section here, rather than as a second per-host table somewhere else.
