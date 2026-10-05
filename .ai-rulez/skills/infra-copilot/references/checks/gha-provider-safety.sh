#!/bin/sh
# Verify the supported workflow shape before a new leaf receives credentials.
set -eu
[ -n "${NEW_PROVIDER:-}" ] && [ -n "${REPO:-}" ] || {
  echo 'CANNOT VERIFY: NEW_PROVIDER and REPO are required' >&2
  exit 2
}
case "$NEW_PROVIDER" in
  *[!a-z0-9-]*|'') echo 'CANNOT VERIFY: invalid provider name' >&2; exit 2 ;;
esac
root=$(git --no-optional-locks rev-parse --show-toplevel) || exit 2
cd "$root"
for file in .github/workflows/terraform-plan.yml .github/workflows/terraform-apply.yml; do
  git cat-file -e "HEAD:$file" 2>/dev/null || exit 1
  dirty=$(git --no-optional-locks status --porcelain -- "$file") || exit 2
  [ -z "$dirty" ] || exit 1
  # This gate recognizes the shipped workflow dialect, not arbitrary YAML.
  # Alternate syntax must receive human review, never a green guess.
  if grep -Eq '^[[:space:]]*pull_request_target[[:space:]]*:' "$file"; then
    echo 'UNSAFE: pull_request_target is not supported for authenticated Terraform' >&2
    exit 1
  fi
done
job() {
  awk -v name="$2" '
    /^  [a-zA-Z0-9_-]+:/ {inside=($0 == "  " name ":")}
    inside {print}
  ' "$1"
}
# Ambiguous duplicate declarations are not supported evidence.
for entry in 'terraform-plan.yml plan' 'terraform-apply.yml apply'; do
  file=${entry% *}
  prefix=${entry#* }
  count=$(grep -Fc "  $prefix-$NEW_PROVIDER:" ".github/workflows/$file" || true)
  [ "$count" = 1 ] || exit 1
done
plan=$(job .github/workflows/terraform-plan.yml "plan-$NEW_PROVIDER")
apply=$(job .github/workflows/terraform-apply.yml "apply-$NEW_PROVIDER")
[ -n "$plan" ] && [ -n "$apply" ] || exit 1
condition=$(printf '%s\n' "$plan" | sed -n 's/^    if: //p' | tr -d '[:space:]')
expected="needs.changes.outputs.$NEW_PROVIDER == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
expected=$(printf '%s' "$expected" | tr -d '[:space:]')
bracket_expected="needs.changes.outputs['$NEW_PROVIDER'] == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
bracket_expected=$(printf '%s' "$bracket_expected" | tr -d '[:space:]')
[ "$condition" = "$expected" ] || [ "$condition" = "$bracket_expected" ] || {
  echo 'UNSAFE: plan job must use the supported job-level same-repository fork guard' >&2
  exit 1
}
environment_count=$(printf '%s\n' "$apply" | grep -c '^    environment:' || true)
[ "$environment_count" = 1 ] || exit 1
printf '%s\n' "$apply" | grep -Eq '^    environment: production[[:space:]]*$' || {
  echo 'UNSAFE: apply job must use the protected production environment' >&2
  exit 1
}
body=$(gh api "repos/$REPO/environments/production") || {
  echo 'CANNOT VERIFY: production environment could not be read' >&2
  exit 2
}
printf '%s\n' "$body" | jq -e '.protection_rules | type == "array"' >/dev/null || {
  echo 'CANNOT VERIFY: malformed environment response' >&2
  exit 2
}
printf '%s\n' "$body" | jq -e '
  any(.protection_rules[]?; .type == "required_reviewers" and ((.reviewers // []) | length > 0))
' >/dev/null || {
  echo 'UNSAFE: production environment has no required reviewers' >&2
  exit 1
}
echo "SAFE: $NEW_PROVIDER rejects forks and applies require production approval"
