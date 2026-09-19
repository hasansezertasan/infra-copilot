<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:7c71517bdebe4952e3181f9a46fcfc15eb1695c0c31c841bebb69a8e9e04121c
Source-Hash: blake3:a2da6ec7ad999e5cdd5b3714c12d7d4a743adace6ab0bbaea904a011b16c141d
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

This is also the table to extend for other per-host dialects — subagent manifests
([#19](https://github.com/hasansezertasan/infra-copilot/issues/19)) and hook discovery
paths ([#42](https://github.com/hasansezertasan/infra-copilot/issues/42)) — as a column
or a sibling section here, rather than as a second per-host table somewhere else.
