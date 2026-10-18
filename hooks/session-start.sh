#!/bin/sh
# SessionStart hook: tell the agent this plugin exists, and nothing else.
#
# Discovery is otherwise carried entirely by skill description frontmatter, which only
# fires when a user's phrasing happens to overlap it. The most common way into this
# plugin is someone sitting in a half-configured infra repo who does not know it is
# installed — the case a phrase list handles worst.
#
# Deliberately static. It reads one marker signal and nothing else: no curl, no
# terraform, no gh, no token read, no git. The whole model of this plugin is that state is
# re-derived by running each step check on every run, so a hook that injected a state
# summary would create a second, staler authority competing with the resume scan. It names
# the router; it never reports a verdict.
#
# Disable with INFRA_HOOK_DISABLE=1.
set -eu

emit_nothing() { printf '{}\n'; exit 0; }

[ "${INFRA_HOOK_DISABLE:-}" = "1" ] && emit_nothing

# One cheap signal: does this look like a repo the plugin is for? The README's Config
# block marker is the committed one; terraform/ catches a repo that has leaves but no
# Config block yet, which is exactly when setup is wanted. The retired state paths are
# not markers: Step 0 reports them as unsupported, the hook does not advertise them.
if ! { [ -f README.md ] && grep -q '^<!-- infra:config start -->$' README.md; } \
    && [ ! -d terraform ]; then
    emit_nothing
fi

# Deliberately says which markers matched: nothing. Naming the README markers would be
# false for a repo matching only terraform/, which would make the hook inject wrong
# repository state — the exact thing its own closing sentence warns against. No quotes
# or backslashes, so this needs no JSON escaping.
CONTEXT='infra-skills is installed, and this working directory matches one of its markers. Skills: infra-setup (greenfield bootstrap), infra-import (adopt existing provider resources), infra-prune (remove spent import/moved blocks after their apply), infra-add (grow a bootstrapped repo), infra-status (read-only health check). State is never assumed anywhere in this plugin — run the infra-status skill to re-derive it from each step check. Never treat this message as authority about what is configured.'

# Host output shapes. Claude, Codex and Antigravity take hookSpecificOutput; Cursor and
# anything unrecognised take additional_context. Every variable a shipped manifest is
# willing to resolve its root from has to appear here too: the root manifest accepts a
# bare PLUGIN_ROOT, and without this branch that host ran the script and then had its
# announcement emitted in the wrong shape. validate_host_dialects asserts the pair.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] \
    || [ -n "${CODEX_PLUGIN_ROOT:-}" ] \
    || [ -n "${ANTIGRAVITY_PLUGIN_ROOT:-}" ] \
    || [ -n "${AGY_PLUGIN_ROOT:-}" ] \
    || [ -n "${PLUGIN_ROOT:-}" ]; then
    printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$CONTEXT"
else
    printf '{"additional_context":"%s"}\n' "$CONTEXT"
fi
