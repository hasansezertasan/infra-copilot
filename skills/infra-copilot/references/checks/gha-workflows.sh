#!/bin/sh
# Verify the supported template shape before setup can skip workflow creation.
# This is conservative textual evidence, not a general YAML/expression parser.
set -eu
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
printf '%s\n' "$apply_events" | grep -q '^  push:$' || exit 1
printf '%s\n' "$apply_events" | grep -q '^  workflow_dispatch:$' || exit 1
printf '%s\n' "$apply_events" | awk '
  /^  [^[:space:]]/ && $0 != "  push:" && $0 != "  workflow_dispatch:" {exit 1}
  /^  [^[:space:]]/ {event=$0}
  /^    [^[:space:]]/ && ($0 != "    branches: [main]" || event != "  push:") {exit 1}
  /^      [^[:space:]]/ {exit 1}
' || exit 1
printf '%s\n' "$apply_events" | grep -Fxq '    branches: [main]' || exit 1
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
section "$apply" jobs | awk '
  /^  [^[:space:]]/ {key=$0; sub(/:.*/, "", key); if (++seen[key] > 1) exit 1}
' || exit 1
names=$(section "$apply" jobs | sed -n 's/^  \(apply-[a-z0-9-]*\):$/\1/p')
for leaf in cloudflare github; do
  printf '%s\n' "$names" | grep -Fxq "apply-$leaf" || exit 1
done
for name in $names; do
  leaf=${name#apply-}
  block=$(job "$apply" "$name")
  header=$(printf '%s\n' "$block" | sed '/^    steps:/,$d')
  apply_step=$(printf '%s\n' "$block" | step 'Terraform Apply')
  printf '%s\n' "$header" "$apply_step" | grep -Eq '^[[:space:]]+(if|needs|continue-on-error):' && exit 1
  [ "$(printf '%s\n' "$block" | grep -Fc '      - name: Terraform Apply')" = 1 ] || exit 1
  guard=$(printf '%s\n' "$block" | step "Refuse to apply a commit that is not main's tip")
  [ "$guard" = "$expected_guard" ] || exit 1
  printf '%s\n' "$block" | awk '
    /      - name: Refuse to apply a commit that is not main/ {guard=1}
    /      - name: Terraform Apply/ {if (!guard) exit 1}
  ' || exit 1
  plan_job=$(job "$plan" "plan-$leaf")
  [ -n "$plan_job" ] || exit 1
  condition="    if: needs.changes.outputs.$leaf == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
  bracket="    if: needs.changes.outputs['$leaf'] == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
  printf '%s\n' "$plan_job" | grep -Fxq "$condition" ||
    printf '%s\n' "$plan_job" | grep -Fxq "$bracket" || exit 1
  [ "$(printf '%s\n' "$plan_job" | grep -c '^    if:' || true)" = 1 ] || exit 1
  output="      $leaf: \${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs.$leaf }}"
  printf '%s\n' "$changes" | grep -Fxq "$output" || exit 1
  [ "$(printf '%s\n' "$changes" | grep -c "^      $leaf:" || true)" = 1 ] || exit 1
done
echo 'READY: committed workflows converge every leaf and support dispatch'
