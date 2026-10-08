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
sh "$INFRA_COPILOT_REFERENCES/checks/workflow-routing.sh" || exit $?
plan=.github/workflows/terraform-plan.yml
apply=.github/workflows/terraform-apply.yml
helper=.github/scripts/terraform-destroy.cjs
[ -r "$INFRA_COPILOT_REFERENCES/templates/terraform-destroy.cjs" ] || exit 2
git cat-file -e "HEAD:$helper" 2>/dev/null || exit 1
dirty=$(git --no-optional-locks status --porcelain -- "$helper") || exit 2
[ -z "$dirty" ] || exit 1
cmp -s "$helper" "$INFRA_COPILOT_REFERENCES/templates/terraform-destroy.cjs" || exit 1
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
    {sub(/\r$/, "")}
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
run_body() {
  awk '
    /^        run:/ {inside=1}
    inside {print}
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
expected_destroy=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-apply.yml" apply-cloudflare |
  step 'Refuse destructive apply without opt-in')
[ -n "$expected_destroy" ] || exit 2
expected_apply_run=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-apply.yml" apply-cloudflare |
  step 'Terraform Apply' | run_body)
[ -n "$expected_apply_run" ] || exit 2
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
  apply_step=$(printf '%s\n' "$block" | step 'Terraform Apply')
  printf '%s\n' "$block" | grep -Eq '^    continue-on-error:' && exit 1
  [ "$(printf '%s\n' "$block" | grep -c '^    needs:' || true)" = 1 ] || exit 1
  printf '%s\n' "$block" | grep -Fxq '    needs: changes' || exit 1
  condition="    if: needs.changes.outputs.$leaf == 'true'"
  bracket="    if: needs.changes.outputs['$leaf'] == 'true'"
  printf '%s\n' "$block" | grep -Fxq "$condition" ||
    printf '%s\n' "$block" | grep -Fxq "$bracket" || exit 1
  printf '%s\n' "$apply_step" | grep -Eq '^        (if|continue-on-error):' && exit 1
  [ "$(printf '%s\n' "$block" | grep -Fc '      - name: Terraform Apply')" = 1 ] || exit 1
  guard=$(printf '%s\n' "$block" | step "Refuse to apply a commit that is not main's tip")
  [ "$guard" = "$expected_guard" ] || exit 1
  destroy=$(printf '%s\n' "$block" | step 'Refuse destructive apply without opt-in')
  wanted_destroy=$(printf '%s\n' "$expected_destroy" | sed "s/leaf: 'cloudflare'/leaf: '$leaf'/")
  [ "$destroy" = "$wanted_destroy" ] || exit 1
  saved_plan=$(printf '%s\n' "$block" | step 'Terraform Plan')
  printf '%s\n' "$saved_plan" | grep -Fxq "        working-directory: terraform/$leaf" || exit 1
  printf '%s\n' "$saved_plan" | grep -Fxq '        run: terraform plan -no-color -out=tfplan' || exit 1
  expected_saved_plan=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-apply.yml" apply-cloudflare |
    step 'Terraform Plan' | run_body)
  actual_saved_plan=$(printf '%s\n' "$saved_plan" | run_body)
  [ "$actual_saved_plan" = "$expected_saved_plan" ] || exit 1
  printf '%s\n' "$saved_plan" | grep -Eq '^        (if|continue-on-error):' && exit 1
  printf '%s\n' "$apply_step" | grep -Fxq "        working-directory: terraform/$leaf" || exit 1
  actual_apply_run=$(printf '%s\n' "$apply_step" | run_body)
  [ "$actual_apply_run" = "$expected_apply_run" ] || exit 1
  printf '%s\n' "$block" | grep -Fxq '      pull-requests: read' || exit 1
  printf '%s\n' "$block" | awk '
    /^      - / {
      if (state == 1 && $0 != "      - name: Refuse destructive apply without opt-in") exit 1
      if (state == 2 && $0 != "      - name: Refuse to apply a commit that is not main\047s tip") exit 1
      if (state == 3 && $0 != "      - name: Terraform Apply") exit 1
    }
    /      - name: Terraform Plan/ {if (++plan != 1) exit 1; state=1}
    /      - name: Refuse destructive apply without opt-in/ {if (state != 1 || ++destroy != 1) exit 1; state=2}
    /      - name: Refuse to apply a commit that is not main/ {if (state != 2 || ++guard != 1) exit 1; state=3}
    /      - name: Terraform Apply/ {if (state != 3) exit 1; state=4}
    END {if (guard != 1 || plan != 1 || destroy != 1 || state != 4) exit 1}
  ' || exit 1
  plan_job=$(job "$plan" "plan-$leaf")
  [ -n "$plan_job" ] || exit 1
  [ "$(printf '%s\n' "$plan_job" | grep -c '^    needs:' || true)" = 1 ] || exit 1
  printf '%s\n' "$plan_job" | grep -Fxq '    needs: changes' || exit 1
  condition="    if: needs.changes.outputs.$leaf == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
  bracket="    if: needs.changes.outputs['$leaf'] == 'true' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)"
  printf '%s\n' "$plan_job" | grep -Fxq "$condition" ||
    printf '%s\n' "$plan_job" | grep -Fxq "$bracket" || exit 1
  [ "$(printf '%s\n' "$plan_job" | grep -c '^    if:' || true)" = 1 ] || exit 1
  case "$leaf" in [0-9]*) accessor="['$leaf']" ;; *) accessor=.$leaf ;; esac
  output="      $leaf: \${{ steps.route.outputs$accessor }}"
  printf '%s\n' "$changes" | grep -Fxq "$output" || exit 1
  [ "$(printf '%s\n' "$changes" | grep -c "^      $leaf:" || true)" = 1 ] || exit 1
  leaf_filter=$(printf '%s\n' "$filter" | awk -v name="$leaf" '
    /^            [^[:space:]]/ {inside=($0 == "            " name ":")}
    inside {print}
  ')
  printf '%s\n' "$leaf_filter" | grep -Fxq "              - '.github/workflows/terraform-*.yml'" || exit 1
  printf '%s\n' "$leaf_filter" | grep -Fxq "              - '.github/scripts/terraform-destroy.cjs'" || exit 1
  pr_plan=$(printf '%s\n' "$plan_job" | step 'Terraform Plan')
  printf '%s\n' "$pr_plan" | grep -Fxq '        id: plan' || exit 1
  printf '%s\n' "$pr_plan" | grep -Fxq "        working-directory: terraform/$leaf" || exit 1
  printf '%s\n' "$pr_plan" | grep -Eq '^        (if|continue-on-error):' && exit 1
  expected_plan_body=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-plan.yml" plan-cloudflare |
    step 'Terraform Plan' | run_body)
  actual_plan_body=$(printf '%s\n' "$pr_plan" | run_body)
  [ "$actual_plan_body" = "$expected_plan_body" ] || exit 1
  inventory=$(printf '%s\n' "$plan_job" | step 'Summarize Destructive Changes')
  expected_inventory=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-plan.yml" plan-cloudflare |
    step 'Summarize Destructive Changes' | sed "s/cloudflare/$leaf/g")
  [ "$inventory" = "$expected_inventory" ] || exit 1
  report=$(printf '%s\n' "$plan_job" | step 'Post Plan to PR')
  expected_report=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-plan.yml" plan-cloudflare |
    step 'Post Plan to PR' | sed "s/cloudflare/$leaf/g")
  [ "$report" = "$expected_report" ] || exit 1
  status=$(printf '%s\n' "$plan_job" | step 'Check Plan Status')
  expected_status=$(job "$INFRA_COPILOT_REFERENCES/templates/terraform-plan.yml" plan-cloudflare |
    step 'Check Plan Status')
  [ "$status" = "$expected_status" ] || exit 1
  printf '%s\n' "$plan_job" | awk '
    /^      - / {
      if (state == 1 && $0 != "      - name: Summarize Destructive Changes") exit 1
      if (state == 2 && $0 != "      - name: Post Plan to PR") exit 1
      if (state == 3 && $0 != "      - name: Check Plan Status") exit 1
    }
    /      - name: Terraform Plan/ {if (++plan != 1) exit 1; state=1}
    /      - name: Summarize Destructive Changes/ {if (state != 1 || ++inventory != 1) exit 1; state=2}
    /      - name: Post Plan to PR/ {if (state != 2 || ++report != 1) exit 1; state=3}
    /      - name: Check Plan Status/ {if (state != 3 || ++status != 1) exit 1; state=4}
    END {if (plan != 1 || inventory != 1 || report != 1 || status != 1 || state != 4) exit 1}
  ' || exit 1
done
echo 'READY: committed workflows and helper converge every leaf with destructive opt-in'
