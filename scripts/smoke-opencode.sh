#!/usr/bin/env bash
# Proves the OpenCode payload is complete by installing the repository into a
# throwaway copy of itself. It runs in a temp directory on purpose: `skills add
# --copy` writes `.agents/skills/` and `skills-lock.json`, and a maintainer may
# already have their own local install of either. Deleting those would destroy
# state this script does not own, so it never writes to the real tree.
#
# The copy is of the working tree, so uncommitted skill edits are covered.
# node_modules is excluded: `skills` comes from the PATH npm sets up, an
# absolute path into the real checkout, so a second dependency tree would only
# be something for `skills add .` to walk.
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/repo"
tar --exclude node_modules -cf - . | tar -xf - -C "$tmp/repo"
rm -rf "$tmp/repo/.agents/skills" "$tmp/repo/skills-lock.json"
cd "$tmp/repo"
skills add . --agent opencode --skill '*' -y --copy
expected=$(find skills -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d '[:space:]')
actual=$(find .agents/skills -name SKILL.md | wc -l | tr -d '[:space:]')
if [ "$actual" != "$expected" ]; then
  echo "smoke-opencode: installed $actual SKILL.md, expected $expected (one per skills/*/)" >&2
  exit 1
fi
test -f .agents/skills/infra/references/protocol.md
test -f .agents/skills/infra/references/decisions.md.example
test -f .agents/skills/infra/references/hosts.md
echo "smoke-opencode: $actual skills installed, references present"
