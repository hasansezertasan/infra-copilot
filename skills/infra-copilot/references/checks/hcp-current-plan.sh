#!/bin/sh
# Verify that the newest HCP run for the current commit and workspace is a safe plan.
# Exit 0 = safe evidence, 1 = tested but unsafe/failed or not yet tested, 2 = unreadable.
set -u
mode=${1:-check}
case "$mode" in check|queue) : ;; *) echo "usage: $0 [check|queue]" >&2; exit 2 ;; esac

cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

for tool in curl jq git; do
    command -v "$tool" >/dev/null 2>&1 || cannot_verify "$tool is not on PATH"
done
for required in ORG REPO NEW_PROVIDER NEW_PROVIDER_WORKSPACE HCP_TOKEN hcp_api; do
    eval "value=\${$required:-}"
    [ -n "$value" ] || cannot_verify "$required is not set"
done
[ "$hcp_api" = "https://app.terraform.io/api/v2" ] \
    || cannot_verify "refusing to send the HCP token to unexpected endpoint '$hcp_api'"

commit_sha=$(git rev-parse HEAD 2>/dev/null) || cannot_verify "HEAD is not a commit"
workspace_body=$(curl -sf "$hcp_api/organizations/$ORG/workspaces/$NEW_PROVIDER_WORKSPACE" \
    -H "Authorization: Bearer $HCP_TOKEN") || cannot_verify "workspace could not be read"
ws_id=$(printf '%s' "$workspace_body" | jq -er \
    --arg repo "$REPO" --arg dir "terraform/$NEW_PROVIDER" '
      .data
      | select(.attributes["vcs-repo"].identifier == $repo)
      | select(.attributes["working-directory"] == $dir)
      | .id | select(type == "string" and length > 0)' 2>/dev/null) \
    || cannot_verify "workspace identity does not match the configured repository and leaf"
resource_count=$(printf '%s' "$workspace_body" | jq -er '
    .data.attributes["resource-count"]
    | select(type == "number" and . == floor and . >= 0)' 2>/dev/null) \
    || cannot_verify "workspace resource-count is not a non-negative integer"

pages=$(mktemp) || cannot_verify "could not create a private run-list file"
trap 'rm -f "$pages"' EXIT
: >"$pages"
page=1
truncated=false
while : ; do
    body=$(curl -sf \
      "$hcp_api/workspaces/$ws_id/runs?page%5Bsize%5D=100&page%5Bnumber%5D=$page&filter%5Boperation%5D=plan_only,plan_and_apply,save_plan&include=configuration_version.ingress_attributes" \
      -H "Authorization: Bearer $HCP_TOKEN") \
      || cannot_verify "run page $page could not be read"
    printf '%s' "$body" | jq -e '
      (.data | type == "array")
      and ((.included // []) | type == "array")
      and (.meta.pagination | type == "object")
      and ((.meta.pagination["next-page"] == null)
        or (.meta.pagination["next-page"]
          | type == "number" and . == floor and . > 0))' >/dev/null 2>&1 \
      || cannot_verify "run page $page was malformed"
    printf '%s\n' "$body" >>"$pages"
    next_page=$(printf '%s' "$body" | jq -r '.meta.pagination["next-page"] // empty') \
      || cannot_verify "run page $page pagination could not be parsed"
    [ -n "$next_page" ] || break
    [ "$next_page" -eq $((page + 1)) ] \
      || cannot_verify "run pagination was not monotonic"
    if [ "$page" -ge 5 ]; then
      truncated=true
      break
    fi
    page=$next_page
done

if ! latest=$(jq -ser --arg sha "$commit_sha" '
  [.[].included[]?
    | select(.type == "ingress-attributes" and .attributes["commit-sha"] == $sha)
    | .id] as $ingress
  | [.[].included[]?
      | select(.type == "configuration-versions")
      | select((.relationships["ingress-attributes"].data.id // "") as $id
          | $ingress | index($id))
      | .id] as $configs
  | [.[].data[]
      | select((.relationships["configuration-version"].data.id // "") as $id
          | $configs | index($id))]
  | sort_by(.attributes["created-at"])
  | reverse
  | .[0] // empty' "$pages" 2>/dev/null); then
    [ "$truncated" = false ] || cannot_verify \
      "HEAD was absent from the bounded 500-run scan and older pages remain"
    exit 1
fi

if [ "$mode" = queue ]; then
    cv_id=$(printf '%s' "$latest" | jq -er '
      .relationships["configuration-version"].data.id
      | select(type == "string" and length > 0)') \
      || cannot_verify "no VCS configuration version for HEAD can be retried"
    payload=$(jq -n --arg ws "$ws_id" --arg cv "$cv_id" '
      {data:{type:"runs", attributes:{"plan-only":true,
        message:"infra-copilot Phase 6 commit-correlated plan"}, relationships:{
        workspace:{data:{type:"workspaces",id:$ws}},
        "configuration-version":{data:{type:"configuration-versions",id:$cv}}
      }}}') || cannot_verify "could not build the run request"
    response=$(mktemp) || cannot_verify "could not create a private run-response file"
    code=$(curl -sS -o "$response" -w '%{http_code}' -X POST "$hcp_api/runs" \
      -H "Authorization: Bearer $HCP_TOKEN" \
      -H "Content-Type: application/vnd.api+json" -d "$payload") \
      || { rm -f "$response"; cannot_verify "the plan request did not complete"; }
    if [ "$code" != 201 ]; then
      detail=$(jq -r '.errors[0].detail // .errors[0].title // "unknown error"' \
        "$response" 2>/dev/null)
      rm -f "$response"
      echo "HCP refused the commit-correlated plan (HTTP $code): $detail" >&2
      exit 1
    fi
    run_id=$(jq -r '.data.id // empty' "$response" 2>/dev/null)
    rm -f "$response"
    echo "Queued commit-correlated plan ${run_id:-successfully}; wait for it to finish."
    exit 0
fi

status=$(printf '%s' "$latest" | jq -er '.attributes.status') \
    || cannot_verify "matched run has no status"
case "$status" in
  planned_and_finished|applied) : ;;
  errored|canceled|discarded|force_canceled) exit 1 ;;
  pending|fetching|fetching_completed|pre_plan_running|pre_plan_completed|queuing|plan_queued|planning|planned|cost_estimating|cost_estimated|policy_checking|policy_override|policy_soft_failed|policy_checked|confirmed|post_plan_running|post_plan_completed|planned_and_saved|applying) \
    cannot_verify "the newest commit-correlated run is still in flight ($status); wait" ;;
  *) cannot_verify "the newest commit-correlated run has unknown status '$status'" ;;
esac
plan_id=$(printf '%s' "$latest" | jq -er \
    '.relationships.plan.data.id | select(type == "string" and length > 0)') \
    || cannot_verify "matched run has no plan id"
plan_json=$(curl -sfL "$hcp_api/plans/$plan_id/json-output-redacted" \
    -H "Authorization: Bearer $HCP_TOKEN") \
    || cannot_verify "matched run's structured plan could not be read"
summary=$(printf '%s' "$plan_json" | jq -ec '
  select((.format_version | type) == "string")
  | select((.terraform_version | type) == "string")
  | select(((.resource_changes // []) | type) == "array")
  | [(.resource_changes // [])[]?.change.actions] as $actions
  | {creates: ([$actions[] | select(index("create"))] | length),
     destroys: ([$actions[] | select(index("delete"))] | length)}' 2>/dev/null) \
  || cannot_verify "matched run's structured plan was malformed"
creates=$(printf '%s' "$summary" | jq -r '.creates')
destroys=$(printf '%s' "$summary" | jq -r '.destroys')
[ "$destroys" -eq 0 ] || exit 1
[ "$creates" -gt 0 ] || [ "$resource_count" -gt 0 ]
