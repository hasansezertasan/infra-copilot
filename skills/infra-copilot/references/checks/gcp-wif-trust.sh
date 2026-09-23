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
#   0  the trust is scoped to $ORG and $NEW_PROVIDER_WORKSPACE, it is the pool's only
#      active provider, no federated principal outside that pool holds a role on the run
#      service accounts or a role with impersonation or escalation permissions on their projects, and a
#      separate apply
#      account admits apply-phase identities only. Folder- and organization-level grants
#      are not read.
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

# Variables inherited from a variable set are invisible to the workspace vars API, so a
# set could supply GOOGLE_CREDENTIALS or override the coordinates read below. Same rule
# as new-provider-credentials: no attached sets, so the workspace list is the whole truth.
varsets=$(curl -sf "$hcp_api/workspaces/$ws_id/varsets?page%5Bsize%5D=1&page%5Bnumber%5D=1" \
    -H "Authorization: Bearer $HCP_TOKEN") \
    || cannot_verify "could not read variable sets of $NEW_PROVIDER_WORKSPACE"
varset_count=$(printf '%s' "$varsets" | jq -er '.data | select(type == "array") | length' 2>/dev/null) \
    || cannot_verify "variable-set response was not a list"
[ "$varset_count" -eq 0 ] \
    || fail "$NEW_PROVIDER_WORKSPACE has variable sets attached; their variables cannot be verified here — detach them and set the variables on the workspace"

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

# Which account each phase actually uses, with HCP's own fallback: a phase-specific
# email wins, otherwise the run email. Keeping the phase matters — when the two differ,
# the apply account is the privileged one and a plan must not be able to reach it.
run_email=$(var TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL)
plan_email=$(var TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL)
apply_email=$(var TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL)
plan_email=${plan_email:-$run_email}
apply_email=${apply_email:-$run_email}
[ -n "$plan_email" ] && [ -n "$apply_email" ] \
    || fail "no service-account email covers both phases; set TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL or both phase-specific emails on $NEW_PROVIDER_WORKSPACE"
case "$plan_email$apply_email" in *"<sensitive>"*)
    fail "a service-account email variable is marked sensitive; unmark it so the trust can be verified" ;;
esac
split=false
[ "$plan_email" = "$apply_email" ] || split=true

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

# The pool-wide member (`/*`) admits identities from every provider in the pool, so
# verifying one provider's condition proves nothing if a sibling has a weaker one. One
# active provider per pool is the only arrangement this check can vouch for.
siblings=$(gcloud iam workload-identity-pools providers list \
    --project="$number" --location=global --workload-identity-pool="$pool_id" \
    --format=json 2>"$err") \
    || cannot_verify "gcloud could not list the providers of pool $pool_id: $(head -1 "$err")"
others=$(printf '%s' "$siblings" | jq -r --arg self "$provider_name" '
    .[]? | select(.state == "ACTIVE" and (.disabled // false) == false)
    | .name | select(. != $self)') \
    || cannot_verify "provider list for pool $pool_id was not JSON"
[ -z "$others" ] \
    || fail "pool $pool_id admits identities through other active providers whose conditions this check does not verify — give each its own pool, or disable them: $others"

if [ "$split" = true ]; then
    # With separate accounts, the apply account is fenced by the run-phase attribute. A
    # mapping that is not the token's own claim (a constant, say) makes that fence
    # meaningless, so it is verified rather than assumed.
    printf '%s' "$provider" \
        | jq -e '.attributeMapping["attribute.terraform_run_phase"] == "assertion.terraform_run_phase"' \
          >/dev/null \
        || fail "plan and apply use different service accounts, but the provider does not map attribute.terraform_run_phase to assertion.terraform_run_phase"
fi

condition=$(printf '%s' "$provider" | jq -r '.attributeCondition // ""' | tr -s '[:space:]' ' ')
[ -n "$condition" ] \
    || fail "provider has no attribute condition: ANY HCP organization's workspace can impersonate the service account"

# Before any term is read, the condition's alphabet is fenced so that where a CEL string
# literal starts and ends is unambiguous. Rewriting `"` to `'` was not: CEL allows `"`
# inside '...' and `'` inside "...", so a rewrite can re-pair quotes and hide `|| true`
# inside what then looks like a literal. Likewise `\` escapes, and `//` starts a comment
# that runs to a newline this check has already collapsed. Only single-quoted literals
# with no escapes remain, which every accepted form below needs and no bypass can use.
printf '%s' "$condition" | grep -Eq "^[A-Za-z0-9_.:=&'() -]+\$" \
    || fail "attribute condition uses characters outside [A-Za-z0-9_.:=&'() -] (double quotes, backslashes, slashes, ||, !, ?); restate it with single-quoted literals in the forms gcp.md lists: $condition"

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
    # The prefix must end at a delimiter: `...:workspace:gcp` is also a prefix of
    # `...:workspace:gcp-evil:run_phase:apply`, so the trailing `:` is required.
    elif printf '%s' "$term" \
        | grep -Eqx "assertion\.sub\.startsWith\( *'organization:$org_re:project:[^:']+:workspace:$ws_re:[^']*' *\)"; then
        org_bound=true
        ws_bound=true
    elif printf '%s' "$term" \
        | grep -Eqx "assertion\.(terraform_run_phase|terraform_project_name) *== *'[^']*'"; then
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
pool_member="^principal(Set)?://iam\.googleapis\.com/$pool_path/"
apply_only="^principalSet://iam\.googleapis\.com/$pool_path/attribute\.terraform_run_phase/apply\$"

# Permissions that reach a run account without its own policy: minting tokens or
# signatures as it, creating a key for it, attaching it to a resource (actAs), granting
# any of those, or loosening the provider condition this check verified. Judging roles
# by name cannot be complete — service-agent roles such as roles/cloudbuild.serviceAgent
# also carry getAccessToken, and custom roles can carry anything — so the project pass
# resolves each role a foreign federated principal holds to its permissions.
escalation_permissions='["iam.serviceAccounts.getAccessToken","iam.serviceAccounts.getOpenIdToken",
  "iam.serviceAccounts.signBlob","iam.serviceAccounts.signJwt",
  "iam.serviceAccounts.implicitDelegation","iam.serviceAccounts.actAs",
  "iam.serviceAccountKeys.create","iam.serviceAccountKeys.upload",
  "iam.serviceAccountKeys.enable",
  "iam.serviceAccounts.setIamPolicy",
  "resourcemanager.projects.setIamPolicy",
  "iam.workloadIdentityPools.update","iam.workloadIdentityPools.delete",
  "iam.workloadIdentityPools.setIamPolicy",
  "iam.workloadIdentityPoolProviders.create","iam.workloadIdentityPoolProviders.update",
  "iam.workloadIdentityPoolProviders.undelete"]'

# $1 = email, $2 = ERE every federated member must match, $3 = what that means
verify_account() {
    policy=$(gcloud iam service-accounts get-iam-policy "$1" --format=json 2>"$err") \
        || cannot_verify "gcloud could not read the IAM policy of $1: $(head -1 "$err")"
    # workloadIdentityUser is the documented grant, so every member of it — user:, group:
    # and serviceAccount: included — must be this pool's.
    wiu=$(printf '%s' "$policy" | jq -r '
        [.bindings[]? | select(.role == "roles/iam.workloadIdentityUser") | .members[]] | .[]')
    [ -n "$wiu" ] || fail "no workload identity principal may impersonate $1"
    foreign=$(printf '%s\n' "$wiu" | grep -Ev "$2" || true)
    [ -z "$foreign" ] || fail "$1 is impersonable by members outside $3: $foreign"
    # A federated principal in ANY binding on the account is judged the same way: Token
    # Creator mints tokens just as well, and a role granted to a foreign pool or to the
    # plan phase would bypass the condition or the phase fence.
    federated=$(printf '%s' "$policy" | jq -r '
        [.bindings[]? | .members[] | select(test("^principal(Set)?://"))] | unique | .[]')
    foreign=$(printf '%s\n' "$federated" | sed '/^$/d' | grep -Ev "$2" || true)
    [ -z "$foreign" ] || fail "$1 grants a role to federated principals outside $3: $foreign"
}

if [ "$split" = true ]; then
    verify_account "$plan_email" "$pool_member" "$pool_path"
    verify_account "$apply_email" "$apply_only" \
        "$pool_path/attribute.terraform_run_phase/apply (a plan could otherwise mint apply credentials)"
    project_rule=$apply_only
else
    verify_account "$apply_email" "$pool_member" "$pool_path"
    project_rule=$pool_member
fi

# The pool is a resource with its own IAM policy, invisible in the project policy. A
# federated principal outside the rule holding any role on it could administer the pool
# and loosen the condition verified above, so it is judged like a run account's policy.
pool_policy=$(gcloud iam workload-identity-pools get-iam-policy "$pool_id" \
    --project="$number" --location=global --format=json 2>"$err") \
    || cannot_verify "gcloud could not read the IAM policy of pool $pool_id: $(head -1 "$err")"
federated=$(printf '%s' "$pool_policy" | jq -r '
    [.bindings[]? | .members[] | select(test("^principal(Set)?://"))] | unique | .[]')
foreign=$(printf '%s\n' "$federated" | sed '/^$/d' | grep -Ev "$project_rule" || true)
[ -z "$foreign" ] || fail "pool $pool_id grants a role on itself to federated principals outside the trust: $foreign"

# Project-level grants are inherited by every service account in the project, so a
# federated principal holding an impersonation role there reaches the run accounts
# without appearing on their own policies. Folder and organization grants are inherited
# too and are NOT read here; gcp.md says so rather than letting exit 0 imply it.
# The run accounts' projects, and the pool's own project (by number), which may differ:
# a pool admin there could rewrite the condition this check verified.
projects=$number
for email in $(printf '%s\n%s\n' "$plan_email" "$apply_email" | sort -u); do
    case "$email" in
        *@*.iam.gserviceaccount.com) project=${email#*@}; project=${project%.iam.gserviceaccount.com} ;;
        *) fail "$email is not a user-managed service account (<name>@<project>.iam.gserviceaccount.com); create a dedicated one per gcp.md" ;;
    esac
    projects="$projects
$project"
done
for project in $(printf '%s\n' "$projects" | sort -u); do
    project_policy=$(gcloud projects get-iam-policy "$project" --format=json 2>"$err") \
        || cannot_verify "gcloud could not read the IAM policy of project $project: $(head -1 "$err")"
    # Each (role, member) pair where the member is federated and outside the rule. Pool
    # principals that pass the rule may hold anything; only strangers are resolved.
    # A binding's IAM condition can scope it away from the run accounts (resource.name on
    # another account, say). Evaluating CEL is out of reach here, so a dangerous grant
    # under a condition is reported as unverifiable rather than as broken or safe.
    pairs=$(printf '%s' "$project_policy" | jq -r '
        .bindings[]? | .role as $r | (if .condition then "conditional" else "unconditional" end) as $c
        | .members[] | select(test("^principal(Set)?://")) | "\($r) \($c) \(.)"' | sed '/^$/d')
    printf '%s\n' "$pairs" | while read -r role scope member; do
        [ -n "$role" ] || continue
        printf '%s\n' "$member" | grep -Eq "$project_rule" && continue
        permissions=$(gcloud iam roles describe "$role" --format=json 2>"$err") \
            || { echo "CANNOT VERIFY: gcloud could not describe $role held by $member on project $project: $(head -1 "$err")" >&2; exit 2; }
        hit=$(printf '%s' "$permissions" | jq -r --argjson bad "$escalation_permissions" '
            [.includedPermissions[]? | select(. as $p | $bad | index($p))] | join(", ")')
        [ -z "$hit" ] && continue
        if [ "$scope" = conditional ]; then
            echo "CANNOT VERIFY: project $project grants $role ($hit) to federated principal $member under an IAM condition this check cannot evaluate; confirm by hand that the condition excludes the run accounts and the pool" >&2
            exit 2
        fi
        echo "project $project grants $role to federated principal $member, whose permissions ($hit) reach the run accounts or the pool" >&2
        exit 1
    done
    rc=$?
    [ "$rc" -eq 0 ] || exit "$rc"
done

exit 0
