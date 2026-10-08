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
    /^[^[:space:]#]/ {inside=0}
    /^  [a-zA-Z0-9_-]+:/ {inside=($0 == "  " name ":")}
    inside {print}
  ' "$1"
}
# Credentials must not be inherited by validation or change-detection jobs.
# Support only block permissions, so flow maps/aliases cannot conceal OIDC grants.
for file in .github/workflows/terraform-plan.yml .github/workflows/terraform-apply.yml; do
  awk '
    /^[[:space:]]*#/ {next}
    /^[[:space:]]*$/ {next}
    /(^|[[:space:]:,{\[])[&*][^[:space:]&*]/ {exit 1}
    /^[[:space:]]*["\047].*["\047]:/ {exit 1}
    permission_indent {
      value=$0; sub(/^ */, "", value)
      indent=length($0)-length(value)
      if (indent >= permission_indent) {
        if (indent != permission_indent || value !~ /^[a-z][a-z-]*: (read|write|none)[[:space:]]*$/) {exit 1}
      } else {permission_indent=0}
    }
    /^(    )?permissions:[[:space:]]*$/ {permission_indent=($0 ~ /^    / ? 6 : 2)}
    /^jobs:/ {jobs=1; next}
    /^[^[:space:]#]/ {jobs=0}
    jobs && /^  [^[:space:]#]/ && $0 !~ /^  [a-zA-Z0-9_-]+:[[:space:]]*$/ {exit 1}
    /permissions["\047]?:/ && $0 !~ /^(    )?permissions:[[:space:]]*$/ {exit 1}
    !jobs && /id-token/ && $0 !~ /^  id-token: none[[:space:]]*$/ {exit 1}
    !jobs && /(^|[^a-zA-Z0-9_])secrets([^a-zA-Z0-9_]|$)/ {exit 1}
  ' "$file" || {
    echo 'UNSAFE: workflow-wide credentials or unsupported permissions syntax' >&2
    exit 1
  }
  names=$(awk '/^jobs:/ {inside=1; next} inside && /^[^[:space:]#]/ {exit} inside && /^  [a-zA-Z0-9_-]+:/ {sub(/^  /, ""); sub(/:.*/, ""); print}' "$file")
  for name in $names; do
    block=$(job "$file" "$name")
    # Comments are guidance, not active credential references.
    active=$(printf '%s\n' "$block" | sed '/^[[:space:]]*#/d')
    if printf '%s\n' "$active" | grep -Eq 'id-token|(^|[^a-zA-Z0-9_])secrets([^a-zA-Z0-9_]|$)'; then
      case "$file:$name" in
        *terraform-plan.yml:plan-*)
          printf '%s\n' "$active" | grep -Eq '^    environment:' && exit 1
          printf '%s\n' "$active" | grep -Eq 'secrets\.(CLOUDFLARE_API_TOKEN|GH_APP_ID|GH_APP_INSTALLATION_ID|GH_APP_PEM)([^A-Za-z0-9_]|$)' && exit 1
          provider=${name#plan-}
          guard=$(printf '%s\n' "$block" | sed -n 's/^    if: //p')
          dot="needs.changes.outputs.$provider == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
          bracket="needs.changes.outputs['$provider'] == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
          [ "$guard" = "$dot" ] || [ "$guard" = "$bracket" ] || exit 1
          ;;
        *terraform-apply.yml:apply-*)
          [ "$(printf '%s\n' "$block" | grep -c '^    environment:' || true)" = 1 ] || exit 1
          printf '%s\n' "$block" | grep -Eq '^    environment: production[[:space:]]*$' || exit 1
          ;;
        *) echo 'UNSAFE: credentials available to an unguarded job' >&2; exit 1 ;;
      esac
    fi
  done
done
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
[ -n "${INFRA_COPILOT_REFERENCES:-}" ] && [ -r "$INFRA_COPILOT_REFERENCES/checks/gha-apply-gate.sh" ] || {
  echo 'CANNOT VERIFY: INFRA_COPILOT_REFERENCES does not contain checks/gha-apply-gate.sh; export it per references/config.md' >&2
  exit 2
}
# The same gate gha-environments checks: main-only environment, plus reviewers or a
# recorded apply-gate decision where the plan cannot offer reviewers.
gate=0
sh "$INFRA_COPILOT_REFERENCES/checks/gha-apply-gate.sh" >/dev/null || gate=$?
[ "$gate" = 0 ] || exit "$gate"
echo "SAFE: $NEW_PROVIDER rejects forks and applies are gated by the production environment"
