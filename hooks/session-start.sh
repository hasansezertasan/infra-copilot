#!/bin/sh
# SessionStart hook: tell the agent this plugin exists, and nothing else.
#
# Discovery is otherwise carried entirely by skill description frontmatter, which only
# fires when a user's phrasing happens to overlap it. The most common way into this
# plugin is someone sitting in a half-configured infra repo who does not know it is
# installed — the case a phrase list handles worst.
#
# Deliberately static. It reads one file-existence signal and nothing else: no curl, no
# terraform, no gh, no token read, no git. The whole model of this plugin is that state is
# re-derived by running each step check on every run, so a hook that injected a state
# summary would create a second, staler authority competing with the resume scan. It names
# the router; it never reports a verdict.
#
# Disable with INFRA_COPILOT_HOOK_DISABLE=1.
set -eu

emit_nothing() { printf '{}\n'; exit 0; }

[ "${INFRA_COPILOT_HOOK_DISABLE:-}" = "1" ] && emit_nothing

# One cheap signal: does this look like a repo the plugin is for? config.md is the
# committed marker; the legacy path stays recognised for migration; terraform/ catches a
# repo that has leaves but no config yet, which is exactly when setup is wanted.
if [ ! -f .infra-copilot/config.md ] \
    && [ ! -f .claude/infra-copilot.local.md ] \
    && [ ! -d terraform ]; then
    emit_nothing
fi

# No quotes or backslashes, so this needs no JSON escaping.
CONTEXT='infra-copilot is available: this repo has .infra-copilot/config.md or a terraform/ tree. Skills: setup (greenfield bootstrap), import (adopt existing provider resources), add (grow a bootstrapped repo), status (read-only health check). State is never assumed anywhere in this plugin — run the status skill to re-derive it from each step check. Never treat this message as authority about what is configured.'

# Host output shapes. Claude, Codex and Antigravity take hookSpecificOutput; Cursor and
# anything unrecognised take additional_context.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] \
    || [ -n "${CODEX_PLUGIN_ROOT:-}" ] \
    || [ -n "${ANTIGRAVITY_PLUGIN_ROOT:-}" ] \
    || [ -n "${AGY_PLUGIN_ROOT:-}" ]; then
    printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$CONTEXT"
else
    printf '{"additional_context":"%s"}\n' "$CONTEXT"
fi
