#!/usr/bin/env bash
# The single-skill install the OpenCode guide documents. `skills add` resolves no
# dependencies, so the guide names each skill by hand -- this proves the list it
# names is still the whole closure. Without it, "install status and whatever it
# needs" is a sentence in a document, and the first skill to gain a dependency
# makes it wrong.
#
# A separate copy from smoke-opencode: `skills add` adds, so a subset install
# into a tree that already holds every skill would find them and prove nothing.
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/repo"
tar --exclude node_modules -cf - . | tar -xf - -C "$tmp/repo"
rm -rf "$tmp/repo/.agents/skills" "$tmp/repo/skills-lock.json"
cd "$tmp/repo"
closure=$(python3 scripts/validate.py --closure status)
# shellcheck disable=SC2086 # the closure is a list of arguments, split on purpose
skills add . --agent opencode $closure -y --copy
installed=$(find .agents/skills -name SKILL.md -exec dirname {} \; | xargs -n1 basename | sort | tr '\n' ' ')
if [ "$installed" != "infra-copilot status " ]; then
  echo "smoke-closure: $closure installed '$installed', expected 'infra-copilot status '" >&2
  exit 1
fi
test -f .agents/skills/infra-copilot/references/protocol.md
echo "smoke-closure: $closure resolves to $installed"
