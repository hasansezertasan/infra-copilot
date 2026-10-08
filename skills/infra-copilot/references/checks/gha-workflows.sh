#!/bin/sh
# Verify the supported template shape before setup can skip workflow creation.
# This is conservative textual evidence, not a general YAML/expression parser.
set -eu
[ "$#" -le 1 ] || exit 2
required_leaf=${1:-}
[ "$#" = 0 ] || [ -n "$required_leaf" ] || {
  echo 'CANNOT VERIFY: the requested provider is empty' >&2
  exit 2
}
case "$required_leaf" in
  *[!a-z0-9-]*) echo 'CANNOT VERIFY: invalid requested provider' >&2; exit 2 ;;
esac
[ -n "${INFRA_COPILOT_REFERENCES:-}" ] &&
  [ -r "$INFRA_COPILOT_REFERENCES/templates/terraform-apply.yml" ] || {
    echo 'CANNOT VERIFY: export INFRA_COPILOT_REFERENCES per references/config.md' >&2
    exit 2
  }
root=$(git --no-optional-locks rev-parse --show-toplevel) || exit 2
cd "$root"
plan=.github/workflows/terraform-plan.yml
apply=.github/workflows/terraform-apply.yml
for file in "$plan" "$apply"; do
  git cat-file -e "HEAD:$file" 2>/dev/null || exit 1
  dirty=$(git --no-optional-locks status --porcelain -- "$file") || exit 2
  [ -z "$dirty" ] || exit 1
  # Only the templates' block layout is supported; aliases and duplicate roots
  # cannot borrow evidence from an inactive declaration.
  awk '
    /^[[:space:]]*#/ {next}
    /TF_CLI_ARGS/ {exit 1}
    /(^|[[:space:]:,{\[])[&*][^[:space:]&*]/ {exit 1}
    /^[^[:space:]#]/ {key=$0; sub(/:.*/, "", key); if (++seen[key] > 1) exit 1}
  ' "$file" || exit 1
  [ "$(grep -Ec '^on:[[:space:]]*$' "$file" || true)" = 1 ] || exit 1
  [ "$(grep -Ec '^jobs:[[:space:]]*$' "$file" || true)" = 1 ] || exit 1
done
section() {
  awk -v key="$2" '
    /^[^[:space:]#]/ {inside=($0 == key ":")}
    inside && $0 !~ /^[[:space:]]*#/ {print}
  ' "$1"
}
job() {
  section "$1" jobs | awk -v name="$2" '
    /^  [^[:space:]#]/ {inside=($0 == "  " name ":")}
    inside {print}
  '
}
step() {
  awk -v name="$1" '
    /^      - / {inside=($0 == "      - name: " name)}
    inside && NF {sub(/[[:space:]]+$/, ""); print}
  '
}
apply_events=$(section "$apply" on)
dispatch_gate=false
if awk -F '|' '
  function clean(v) { gsub(/^[[:space:]`]+|[[:space:]`]+$/, "", v); return tolower(v) }
  clean($2) == "apply gate" && clean($3) == "dispatch" && clean($4) == "locked" {found=1}
  END {exit !found}
' .infra-copilot/decisions.md 2>/dev/null; then
  dispatch_gate=true
fi
if [ "$dispatch_gate" = true ]; then
  printf '%s\n' "$apply_events" | grep -q '^  push:$' && exit 1
else
  printf '%s\n' "$apply_events" | grep -q '^  push:$' || exit 1
  printf '%s\n' "$apply_events" | grep -Fxq '    branches: [main]' || exit 1
fi
printf '%s\n' "$apply_events" | grep -q '^  workflow_dispatch:$' || exit 1
printf '%s\n' "$apply_events" | awk '
  /^  [^[:space:]]/ && $0 != "  push:" && $0 != "  workflow_dispatch:" {exit 1}
  /^  [^[:space:]]/ {event=$0}
  /^    [^[:space:]]/ && ($0 != "    branches: [main]" || event != "  push:") {exit 1}
  /^      [^[:space:]]/ {exit 1}
' || exit 1
concurrency=$(section "$apply" concurrency)
printf '%s\n' "$concurrency" | grep -Fxq '  group: terraform-apply-${{ github.ref }}' || exit 1
printf '%s\n' "$concurrency" | grep -Fxq '  cancel-in-progress: false' || exit 1
# Duplicate nested declarations must not override the lines checked above.
for block in "$apply_events" "$concurrency"; do
  printf '%s\n' "$block" | awk '
    /^[[:space:]]*$/ {next}
    {key=$0; sub(/:.*/, "", key); if (++seen[key] > 1) exit 1}
  ' || exit 1
done
plan_events=$(section "$plan" on)
printf '%s\n' "$plan_events" | grep -q '^  pull_request:$' || exit 1
printf '%s\n' "$plan_events" | grep -q '^  workflow_dispatch:$' || exit 1
changes=$(job "$plan" changes)
printf '%s\n' "$changes" | grep -Eq '^    (if|needs|continue-on-error):' && exit 1
filter=$(printf '%s\n' "$changes" | awk '
  /^      - / {inside=($0 ~ /uses: dorny\/paths-filter@/)}
  inside {print}
')
[ "$(printf '%s\n' "$filter" | grep -c '^        id: filter$' || true)" = 1 ] || exit 1
[ "$(printf '%s\n' "$filter" | grep -c '^        if:' || true)" = 1 ] || exit 1
printf '%s\n' "$filter" | grep -Fxq "        if: github.event_name == 'pull_request'" || exit 1
expected_guard=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-apply.yml" apply-cloudflare |
  step "Refuse to apply a commit that is not main's tip")
[ -n "$expected_guard" ] || exit 2
expected_apply=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-apply.yml" apply-cloudflare |
  step 'Terraform Apply' | sed -n '/^        run:/p')
[ -n "$expected_apply" ] || exit 2
section "$apply" jobs | awk '
  /^  [^[:space:]]/ {key=$0; sub(/:.*/, "", key); if (++seen[key] > 1) exit 1}
' || exit 1
names=$(section "$apply" jobs | sed -n 's/^  \(apply-[a-z0-9-]*\):$/\1/p')
for leaf in cloudflare github $required_leaf; do
  printf '%s\n' "$names" | grep -Fxq "apply-$leaf" || exit 1
done
for name in $names; do
  leaf=${name#apply-}
  block=$(job "$apply" "$name")
  [ "$(printf '%s\n' "$block" | grep -c '^    environment:' || true)" = 1 ] || exit 1
  printf '%s\n' "$block" | grep -Fxq '    environment: production' || exit 1
  apply_step=$(printf '%s\n' "$block" | step 'Terraform Apply')
  # The supported apply always recomputes with default refresh and locking.
  [ "$(printf '%s\n' "$apply_step" | sed -n '/^        run:/p')" = "$expected_apply" ] || exit 1
  printf '%s\n' "$block" | grep -Eq '^    (if|needs|continue-on-error):' && exit 1
  printf '%s\n' "$apply_step" | grep -Eq '^        (if|continue-on-error):' && exit 1
  [ "$(printf '%s\n' "$block" | grep -Fc '      - name: Terraform Apply')" = 1 ] || exit 1
  guard=$(printf '%s\n' "$block" | step "Refuse to apply a commit that is not main's tip")
  [ "$guard" = "$expected_guard" ] || exit 1
  printf '%s\n' "$block" | awk '
    /      - name: Refuse to apply a commit that is not main/ {guard=1}
    /      - name: Terraform Apply/ {if (!guard) exit 1}
  ' || exit 1
  plan_job=$(job "$plan" "plan-$leaf")
  [ -n "$plan_job" ] || exit 1
  # Only read-only credentials may reach branch plans. No environment is allowed.
  printf '%s\n' "$plan_job" | grep -Eq '^    environment:' && exit 1
  # Only dot-form secret access is supported; bracket/whole-context forms are ambiguous.
  printf '%s\n' "$plan_job" | sed -E 's/secrets\.[A-Za-z_][A-Za-z0-9_]*//g' |
    grep -Eq '(^|[^A-Za-z0-9_])secrets([^A-Za-z0-9_]|$)' && exit 1
  printf '%s\n' "$plan_job" | grep -Eq 'secrets[[:space:]]*\[' && exit 1
  printf '%s\n' "$plan_job" | grep -Eq 'secrets\.(CLOUDFLARE_API_TOKEN|GH_APP_ID|GH_APP_INSTALLATION_ID|GH_APP_PEM)([^A-Za-z0-9_]|$)' && exit 1
  plan_step=$(printf '%s\n' "$plan_job" | step 'Terraform Plan')
  flags='-lock=false'
  [ "$leaf" != github ] || flags='-lock=false -refresh=false'
  printf '%s\n' "$plan_step" | grep -Fxq "          terraform plan $flags -no-color -out=tfplan 2>&1 | tee plan.txt" || exit 1
  # Cross-check provider credentials against their tier. Public backend coordinates
  # intentionally use environment overrides; effective IAM/trust is reviewed by HUMAN.
  case "$leaf" in
    cloudflare) inventory='[{"name":"CLOUDFLARE_API_TOKEN_READ","scope":"plan"},{"name":"CLOUDFLARE_API_TOKEN","scope":"apply"}]' ;;
    github) inventory='[{"name":"GH_APP_READ_ID","scope":"plan"},{"name":"GH_APP_READ_INSTALLATION_ID","scope":"plan"},{"name":"GH_APP_READ_PEM","scope":"plan"},{"name":"GH_APP_ID","scope":"apply"},{"name":"GH_APP_INSTALLATION_ID","scope":"apply"},{"name":"GH_APP_PEM","scope":"apply"}]' ;;
    *)
      if [ "${NEW_PROVIDER:-}" = "$leaf" ] && [ -n "${NEW_PROVIDER_SECRETS:-}" ]; then
        inventory=$NEW_PROVIDER_SECRETS
      else
        inventory=$(printf '%s' "${ADDITIONAL_PROVIDER_SECRETS:-[]}" | jq -ce --arg leaf "$leaf" '
          [.[] | select(.name == $leaf)] | select(length == 1) | .[0].credential_secrets') || {
          echo "CANNOT VERIFY: missing credential inventory for $leaf" >&2; exit 2;
        }
      fi
      ;;
  esac
  case "$leaf" in
    cloudflare|github) inventory=$(printf '%s' "$inventory" | jq -c 'map(. + {required: true})') || exit 2 ;;
  esac
  printf '%s' "$inventory" | jq -e '
    type == "array" and all(.[];
      (.name | type == "string" and test("^[A-Za-z_][A-Za-z0-9_]*$"))
      and (.scope == "plan" or .scope == "apply") and (.required | type == "boolean"))
    and length == (map(.name | ascii_upcase) | unique | length)' >/dev/null || exit 1
  for tier in plan apply; do
    tier_job=$(job "$([ "$tier" = plan ] && printf '%s' "$plan" || printf '%s' "$apply")" "$tier-$leaf")
    printf '%s\n' "$tier_job" | sed -E 's/secrets\.[A-Za-z_][A-Za-z0-9_]*//g' |
      grep -Eq '(^|[^A-Za-z0-9_])secrets([^A-Za-z0-9_]|$)' && exit 1
    references=$(printf '%s\n' "$tier_job" | grep -Eo 'secrets\.[A-Za-z_][A-Za-z0-9_]*' | cut -d . -f 2 | tr '[:lower:]' '[:upper:]' || true)
    printf '%s\n' "$references" | while IFS= read -r secret; do
      [ -n "$secret" ] || continue
      case "$secret" in
        GCP_WORKLOAD_IDENTITY_PROVIDER|GCP_SERVICE_ACCOUNT|AWS_ROLE_ARN|AZURE_CLIENT_ID|AZURE_TENANT_ID|AZURE_SUBSCRIPTION_ID) continue ;;
      esac
      printf '%s' "$inventory" | jq -e --arg name "$secret" --arg tier "$tier" '
        any(.[]; (.name | ascii_upcase) == $name and .scope == $tier)' >/dev/null || exit 1
    done || exit 1
    printf '%s' "$inventory" | jq -r --arg tier "$tier" '
      .[] | select(.scope == $tier and .required == true) | .name | ascii_upcase' |
      while IFS= read -r secret; do
        printf '%s\n' "$references" | grep -Fxq "$secret" || exit 1
      done || exit 1
  done
  [ "$(printf '%s\n' "$plan_job" | grep -c '^    needs:' || true)" = 1 ] || exit 1
  printf '%s\n' "$plan_job" | grep -Fxq '    needs: changes' || exit 1
  condition="    if: needs.changes.outputs.$leaf == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
  bracket="    if: needs.changes.outputs['$leaf'] == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
  printf '%s\n' "$plan_job" | grep -Fxq "$condition" ||
    printf '%s\n' "$plan_job" | grep -Fxq "$bracket" || exit 1
  [ "$(printf '%s\n' "$plan_job" | grep -c '^    if:' || true)" = 1 ] || exit 1
  output="      $leaf: \${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs.$leaf }}"
  printf '%s\n' "$changes" | grep -Fxq "$output" || exit 1
  [ "$(printf '%s\n' "$changes" | grep -c "^      $leaf:" || true)" = 1 ] || exit 1
done
echo 'READY: committed workflows support read-tier unlocked plans, converge every leaf and support dispatch; HUMAN IAM review is still required'
