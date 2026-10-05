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
  # Accept only the block event syntax used by the shipped templates. A flow/scalar
  # pull_request_target trigger must not evade a token check elsewhere in the file.
  on_count=$(grep -Ec "^(on|'on'|\"on\"):" "$file" || true)
  [ "$on_count" = 1 ] && grep -Eq '^on:[[:space:]]*$' "$file" || {
    echo 'UNSAFE: unsupported workflow event syntax' >&2
    exit 1
  }
  events=$(awk '
    /^on:[[:space:]]*$/ {inside=1; next}
    inside && /^[^[:space:]#]/ {exit}
    inside && /^  [^[:space:]#]/ {sub(/^  /, ""); sub(/:.*/, ""); print}
  ' "$file")
  [ -n "$events" ] || exit 1
  printf '%s\n' "$events" | while IFS= read -r event; do
    case "$file:$event" in
      *terraform-plan.yml:pull_request|*terraform-plan.yml:workflow_dispatch) ;;
      *terraform-apply.yml:push|*terraform-apply.yml:workflow_dispatch) ;;
      *) echo 'UNSAFE: unsupported workflow event; authenticated target events are forbidden' >&2; exit 1 ;;
    esac
  done || exit 1
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
condition=$(printf '%s\n' "$plan" | sed -n 's/^    if: //p')
expected="needs.changes.outputs.$NEW_PROVIDER == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
bracket_expected="needs.changes.outputs['$NEW_PROVIDER'] == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
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
