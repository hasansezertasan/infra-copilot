#!/bin/sh
# Assert that the GCP Workload Identity Federation trust behind the HCP workspace is
# scoped to this organization and workspace. The issuer https://app.terraform.io is
# shared by every HCP customer, so a provider with no attribute condition — or one bound
# to the workspace name alone — lets another organization impersonate the service
# account. Nothing else in the plan path notices: the first plan is green either way.
#
# Read-only: HCP vars API reads with the plan-only token, then `gcloud ... describe` and
# `get-iam-policy`. Safe for infra-copilot:status.
#
# Requires $ORG, $NEW_PROVIDER_WORKSPACE, $hcp_api, and $HCP_TOKEN exported per
# references/config.md, and a gcloud login that can read the pool and service accounts.
#
# The provider and service accounts are located from the workspace's own non-sensitive
# TFC_GCP_* variables, so the check verifies the trust HCP actually uses rather than a
# second copy of its coordinates that could drift.
#
# Exit codes:
#   0  the trust is scoped to $ORG and $NEW_PROVIDER_WORKSPACE, and only that pool may
#      impersonate the run service accounts
#   1  trust BROKEN or incomplete — a real verdict about the configuration
#   2  COULD NOT VERIFY — missing inputs, an HCP read failed, or gcloud could not read
#      the pool (not logged in, no permission). Never evidence about the trust.
set -u

fail() { echo "$1" >&2; exit 1; }
cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

for name in ORG NEW_PROVIDER_WORKSPACE hcp_api HCP_TOKEN; do
    eval "value=\${$name:-}"
    [ -n "$value" ] || cannot_verify "$name is not set; export it per references/config.md"
done
[ "$hcp_api" = "https://app.terraform.io/api/v2" ] \
    || cannot_verify "hcp_api must be https://app.terraform.io/api/v2"

workspace=$(curl -sf "$hcp_api/organizations/$ORG/workspaces/$NEW_PROVIDER_WORKSPACE" \
    -H "Authorization: Bearer $HCP_TOKEN") \
    || cannot_verify "could not read workspace $NEW_PROVIDER_WORKSPACE"
ws_id=$(printf '%s' "$workspace" \
    | jq -er '.data.id | select(type == "string" and test("^ws-[A-Za-z0-9]+$"))' 2>/dev/null) \
    || cannot_verify "workspace response carried no ws- ID"

vars=$(curl -sf "$hcp_api/workspaces/$ws_id/vars?page%5Bsize%5D=100" \
    -H "Authorization: Bearer $HCP_TOKEN") \
    || cannot_verify "could not read variables of $NEW_PROVIDER_WORKSPACE"
printf '%s' "$vars" | jq -e '.data | type == "array"' >/dev/null 2>&1 \
    || cannot_verify "variables response was not a list"
printf '%s' "$vars" | jq -e '(.meta.pagination["next-page"] // null) == null' >/dev/null 2>&1 \
    || cannot_verify "more than 100 workspace variables; this check reads one page"

# $1 = key; prints the env variable's value. Empty when absent. A sensitive value reads
# back as null, which is itself a finding: these coordinates are not secrets, and hiding
# them makes the trust unverifiable.
var() {
    printf '%s' "$vars" | jq -r --arg key "$1" '
        [.data[].attributes | select(.category == "env" and .key == $key)][0]
        | if . == null then "" elif .sensitive then "<sensitive>" else (.value // "") end'
}

for key in GOOGLE_CREDENTIALS GOOGLE_APPLICATION_CREDENTIALS; do
    [ -z "$(var "$key")" ] \
        || fail "$key is set on $NEW_PROVIDER_WORKSPACE; it conflicts with dynamic credentials — delete it"
done

[ "$(var TFC_GCP_PROVIDER_AUTH)" = "true" ] \
    || fail "TFC_GCP_PROVIDER_AUTH is not 'true' on $NEW_PROVIDER_WORKSPACE"

provider_name=$(var TFC_GCP_WORKLOAD_PROVIDER_NAME)
if [ -z "$provider_name" ]; then
    number=$(var TFC_GCP_PROJECT_NUMBER)
    pool_id=$(var TFC_GCP_WORKLOAD_POOL_ID)
    provider_id=$(var TFC_GCP_WORKLOAD_PROVIDER_ID)
    [ -n "$number" ] && [ -n "$pool_id" ] && [ -n "$provider_id" ] \
        || fail "neither TFC_GCP_WORKLOAD_PROVIDER_NAME nor the PROJECT_NUMBER/WORKLOAD_POOL_ID/WORKLOAD_PROVIDER_ID triple is set"
    provider_name="projects/$number/locations/global/workloadIdentityPools/$pool_id/providers/$provider_id"
fi
case "$provider_name" in *"<sensitive>"*)
    fail "the workload provider variables are marked sensitive; they are coordinates, not secrets — unmark them so the trust can be verified" ;;
esac
printf '%s\n' "$provider_name" \
    | grep -Eq '^projects/[0-9]+/locations/global/workloadIdentityPools/[a-z0-9-]+/providers/[a-z0-9-]+$' \
    || fail "workload provider name is malformed: $provider_name"
number=$(printf '%s' "$provider_name" | cut -d/ -f2)
pool_id=$(printf '%s' "$provider_name" | cut -d/ -f6)
provider_id=$(printf '%s' "$provider_name" | cut -d/ -f8)

emails=$(for key in TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL \
    TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL; do var "$key"; done | sed '/^$/d' | sort -u)
[ -n "$emails" ] || fail "no TFC_GCP_*_SERVICE_ACCOUNT_EMAIL is set on $NEW_PROVIDER_WORKSPACE"
case "$emails" in *"<sensitive>"*)
    fail "a service-account email variable is marked sensitive; unmark it so the trust can be verified" ;;
esac

err=$(mktemp) || cannot_verify "mktemp failed"
trap 'rm -f "$err"' EXIT
provider=$(gcloud iam workload-identity-pools providers describe "$provider_id" \
    --project="$number" --location=global --workload-identity-pool="$pool_id" \
    --format=json 2>"$err")
if [ $? -ne 0 ]; then
    grep -q NOT_FOUND "$err" && fail "workload identity provider $provider_name does not exist"
    cannot_verify "gcloud could not read $provider_name: $(head -1 "$err")"
fi

issuer=$(printf '%s' "$provider" | jq -r '.oidc.issuerUri // ""')
[ "$issuer" = "https://app.terraform.io" ] \
    || fail "provider issuer is '$issuer', expected https://app.terraform.io"
printf '%s' "$provider" | jq -e '.state == "ACTIVE" and (.disabled // false) == false' >/dev/null \
    || fail "provider $provider_name is not ACTIVE"

condition=$(printf '%s' "$provider" | jq -r '.attributeCondition // ""' | tr -s '[:space:]' ' ' | tr '"' "'")
[ -n "$condition" ] \
    || fail "provider has no attribute condition: ANY HCP organization's workspace can impersonate the service account"

# The condition is judged against an allowlist, never searched for evidence. Searching
# is unsound: `startsWith(...) == false` or a ternary ending `? true : true` contains
# every trusted-looking substring while trusting everyone else. So the whole condition
# must be a conjunction of `&&` terms, and every term must match one anchored form below
# exactly — each is an equality or prefix test against a literal, so every one only ever
# narrows the trust. Anything else, however strict it really is, is refused rather than
# evaluated; restate it in these forms.
org_re=$(printf '%s' "$ORG" | sed 's/[.[\*^$/]/\\&/g')
ws_re=$(printf '%s' "$NEW_PROVIDER_WORKSPACE" | sed 's/[.[\*^$/]/\\&/g')
org_bound=false
ws_bound=false
terms=$(printf '%s' "$condition" | sed 's/&&/\
/g')
while IFS= read -r term; do
    term=$(printf '%s' "$term" | sed 's/^ *//; s/ *$//')
    if printf '%s' "$term" | grep -Eqx "assertion\.terraform_organization_name *== *'$org_re'"; then
        org_bound=true
    elif printf '%s' "$term" | grep -Eqx "assertion\.terraform_workspace_name *== *'$ws_re'" \
        || printf '%s' "$term" | grep -Eqx "assertion\.terraform_workspace_id *== *'$ws_id'"; then
        ws_bound=true
    elif printf '%s' "$term" \
        | grep -Eqx "assertion\.sub\.startsWith\( *'organization:$org_re:project:[^:']+:workspace:$ws_re(:[^']*)?' *\)"; then
        org_bound=true
        ws_bound=true
    elif printf '%s' "$term" \
        | grep -Eqx "assertion\.(terraform_run_phase|terraform_project_name|aud) *== *'[^']*'"; then
        :
    else
        fail "attribute condition term is not one of the verifiable forms (see gcp.md): $term"
    fi
done <<EOF_TERMS
$terms
EOF_TERMS
[ "$org_bound" = true ] || fail "attribute condition does not bind organization $ORG: $condition"
[ "$ws_bound" = true ] \
    || fail "attribute condition binds the organization but not workspace $NEW_PROVIDER_WORKSPACE ($ws_id): $condition"

pool_path="projects/$number/locations/global/workloadIdentityPools/$pool_id"
for email in $emails; do
    policy=$(gcloud iam service-accounts get-iam-policy "$email" --format=json 2>"$err") \
        || cannot_verify "gcloud could not read the IAM policy of $email: $(head -1 "$err")"
    # Every member of the role, not only pool principals: a user:, group:, or
    # serviceAccount: member holding workloadIdentityUser can impersonate the account too.
    members=$(printf '%s' "$policy" | jq -r '
        [.bindings[]? | select(.role == "roles/iam.workloadIdentityUser") | .members[]] | .[]')
    [ -n "$members" ] || fail "no workload identity principal may impersonate $email"
    foreign=$(printf '%s\n' "$members" \
        | grep -Ev "^principal(Set)?://iam\.googleapis\.com/$pool_path/" || true)
    [ -z "$foreign" ] \
        || fail "$email is impersonable from outside $pool_path, whose condition this check did not verify: $foreign"
done

exit 0
