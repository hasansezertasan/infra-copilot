#!/bin/sh
# Verify the production environment gates object-storage applies.
# Exit 0 = gated, 1 = not gated, 2 = cannot verify. Run from the repository root.
#
# A main-only deployment branch policy is required on every plan: it stops other
# branches from running a job in `production`. Required reviewers are required where
# GitHub offers them to this repository (public repos, Enterprise orgs). Elsewhere the
# API rejects them, so a locked `Apply gate` row in .infra-copilot/decisions.md naming
# `merge-approval` or `dispatch` records the human gate instead.
set -eu
[ -n "${REPO:-}" ] || { echo 'CANNOT VERIFY: REPO is required' >&2; exit 2; }
env_json=$(gh api "repos/$REPO/environments/production" 2>/dev/null) || {
  echo 'CANNOT VERIFY: production environment could not be read' >&2
  exit 2
}
printf '%s\n' "$env_json" | jq -e '.protection_rules | type == "array"' >/dev/null 2>&1 || {
  echo 'CANNOT VERIFY: malformed environment response' >&2
  exit 2
}
printf '%s\n' "$env_json" | jq -e '
  .deployment_branch_policy.custom_branch_policies == true and
  .deployment_branch_policy.protected_branches == false
' >/dev/null || {
  echo 'UNSAFE: production environment needs a custom deployment branch policy' >&2
  exit 1
}
policies=$(gh api "repos/$REPO/environments/production/deployment-branch-policies" 2>/dev/null) || {
  echo 'CANNOT VERIFY: deployment branch policies could not be read' >&2
  exit 2
}
printf '%s\n' "$policies" | jq -e '
  [.branch_policies[]? | {name, type: (.type // "branch")}] == [{name: "main", type: "branch"}]
' >/dev/null 2>&1 || {
  echo 'UNSAFE: production deployment branch policy must allow exactly main' >&2
  exit 1
}
if printf '%s\n' "$env_json" | jq -e '
  any(.protection_rules[]; .type == "required_reviewers" and ((.reviewers // []) | length > 0))
' >/dev/null; then
  echo 'GATED: main-only production environment with required reviewers'
  exit 0
fi
visibility=$(gh api "repos/$REPO" -q .visibility 2>/dev/null) || {
  echo 'CANNOT VERIFY: repository visibility could not be read' >&2
  exit 2
}
# User-owned repositories have no org endpoint and cannot be on Enterprise.
plan=$(gh api "orgs/${REPO%%/*}" -q '.plan.name' 2>/dev/null) || plan=unknown
if [ "$visibility" = public ] || [ "$plan" = enterprise ]; then
  echo 'UNSAFE: required reviewers are available here; add them to the production environment' >&2
  exit 1
fi
awk -F '|' '
  function clean(v) { gsub(/^[[:space:]`]+|[[:space:]`]+$/, "", v); return tolower(v) }
  clean($2) == "apply gate" && (clean($3) == "merge-approval" || clean($3) == "dispatch") &&
    clean($4) == "locked" { found=1 }
  END { exit !found }' .infra-copilot/decisions.md 2>/dev/null || {
  echo 'UNSAFE: no required reviewers and no locked "Apply gate" decision (merge-approval or dispatch)' >&2
  exit 1
}
echo 'GATED: main-only production environment with a recorded apply gate'
