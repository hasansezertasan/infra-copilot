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

# Key mode: a service-account-key adoption (sensitive GOOGLE_CREDENTIALS, no
# TFC_GCP_PROVIDER_AUTH) has no federation trust, but the same question applies — does
# the run use the declared identity? — so it gets the variable-family and provider-block
# checks, with GOOGLE_CREDENTIALS as the one allowed credential and no provider identity
# argument at all (the key arrives through the environment), and then stops.
key_mode=false
if [ -z "$(var TFC_GCP_PROVIDER_AUTH)" ] \
    && printf '%s' "$vars" | jq -e 'any(.data[].attributes;
        .key == "GOOGLE_CREDENTIALS" and .category == "env" and .sensitive == true)' >/dev/null; then
    key_mode=true
fi

# The Google provider and SDK read credentials, tokens, and impersonation targets from a
# family of variables (GOOGLE_CREDENTIALS, GOOGLE_OAUTH_ACCESS_TOKEN,
# GOOGLE_CLOUD_KEYFILE_JSON, GCLOUD_KEYFILE_JSON, GOOGLE_IMPERSONATE_SERVICE_ACCOUNT,
# CLOUDSDK_AUTH_*, ...). Any of them would make the run use an identity other than the
# one verified below, so the family is refused wholesale rather than listed; only
# location settings, which carry no identity, are allowed through.
overrides=$(printf '%s' "$vars" | jq -r --argjson key_mode "$key_mode" '
    .data[].attributes | select(.category == "env") | .key
    | select(test("^(GOOGLE_|GCLOUD_|CLOUDSDK_)"))
    | select(IN("GOOGLE_PROJECT", "GOOGLE_REGION", "GOOGLE_ZONE",
                "GOOGLE_CLOUD_PROJECT", "CLOUDSDK_CORE_PROJECT") | not)
    | select($key_mode and . == "GOOGLE_CREDENTIALS" | not)')
[ -z "$overrides" ] \
    || fail "$NEW_PROVIDER_WORKSPACE sets Google credential or identity variables that override dynamic credentials — delete them: $(printf '%s' "$overrides" | tr '\n' ' ')"

# Identity can also come from the committed provider configuration: `credentials`,
# `access_token`, or `impersonate_service_account` set from a terraform-category
# variable would make the run use an identity no env check sees. Only the documented
# dynamic-credentials form of `credentials` (gcp.md, tagged configurations) passes. The
# scan is textual for HCL, structural for JSON, and fails closed: any line that starts
# with one of these names (so `credentials /* note */ = ...` too) anywhere in the leaf or
# the shared modules must be exactly one of the allowed forms, and so must any line
# assigning one of them mid-line. Only google provider blocks are read (see the lexer),
# so a compact `provider "google" { credentials = x }` is judged on its inner text. The
# exemption is anchored
# to the whole assignment (after grep -n's "N:" prefix): unanchored, the allowed text
# inside a trailing comment would excuse a static key before it.
# In key mode nothing is exempt: the pattern below can never match a real line.
if [ "$key_mode" = true ]; then
    allowed_hcl='^$never'
    allowed_json='^$never'
else
    allowed_hcl='^[0-9]+:[[:space:]]*credentials[[:space:]]*=[[:space:]]*try\(var\.tfc_gcp_dynamic_credentials\.(default|aliases\["[A-Za-z0-9_-]+"\])\.credentials,[[:space:]]*null\)[[:space:]]*(#.*)?$'
    allowed_json='^credentials = \$\{try\(var\.tfc_gcp_dynamic_credentials\.(default|aliases\["[A-Za-z0-9_-]+"\])\.credentials, ?null\)\}$'
fi
if [ -n "${NEW_PROVIDER:-}" ] && [ -d "terraform/$NEW_PROVIDER" ]; then
    static=$(find "terraform/$NEW_PROVIDER" terraform/modules -name '*.tf' -type f 2>/dev/null \
        | while IFS= read -r file; do
            # Comments are whitespace to HCL, so they are removed first by a small lexer
            # that knows where they cannot start: inside a quoted string (with escapes
            # and nested ${...}/%{...} templates, whose own strings nest) or a heredoc,
            # "/*" and "#" are data. A textual strip would treat "gs://b/*" as a comment
            # opener and hide every later line. Line comments are dropped (the exemption
            # below is anchored, so no comment text can excuse anything); string text is
            # kept. Every input line yields one output line, so grep -n numbers are real.
            awk '
            function top() { return sp > 0 ? st[sp] : "N" }
            # Only text inside a provider "google" / "google-beta" block is emitted:
            # a variable type such as object({ credentials = string }) or a module input
            # named credentials is not an identity argument. `head` holds the current
            # line so far, to recognise a block header when its "{" arrives.
            function emit(ch) { head = head ch; if (in_provider) out = out ch }
            {
                line = $0; out = ""; head = ""; n = length(line); i = 1
                if (heredoc != "") {
                    t = line; gsub(/^[[:space:]]+|[[:space:]]+$/, "", t)
                    if (t == heredoc) heredoc = ""
                    print ""; next
                }
                while (i <= n) {
                    c = substr(line, i, 1); c2 = substr(line, i, 2)
                    if (in_block) {
                        if (c2 == "*/") { in_block = 0; emit(" "); i += 2 } else i++
                        continue
                    }
                    if (top() == "S") {
                        if (c == "\\") { emit(c2); i += 2; continue }
                        if (substr(line, i, 3) == "$${" || substr(line, i, 3) == "%%{") {
                            emit(substr(line, i, 3)); i += 3; continue
                        }
                        if (c2 == "${" || c2 == "%{") { st[++sp] = "I"; br[sp] = 0; emit(c2); i += 2; continue }
                        if (c == "\"") sp--
                        emit(c); i++; continue
                    }
                    if (c2 == "/*") { in_block = 1; i += 2; continue }
                    if (c == "#" || c2 == "//") break
                    if (c == "\"") { st[++sp] = "S"; emit(c); i++; continue }
                    if (top() == "I") {
                        if (c == "{") br[sp]++
                        else if (c == "}") {
                            if (br[sp] == 0) { sp--; emit(c); i++; continue }
                            br[sp]--
                        }
                    } else if (c == "{") {
                        depth++
                        if (depth == 1 && head ~ /^[[:space:]]*provider[[:space:]]+"?google(-beta)?"?[[:space:]]*$/) {
                            in_provider = 1; head = head c; i++; continue
                        }
                    } else if (c == "}") {
                        if (depth > 0) depth--
                        if (depth == 0 && in_provider) { in_provider = 0; head = head c; i++; continue }
                    }
                    # Delimiter grammar as measured for Terraform in steps.yaml (hyphens allowed).
                    if (c2 == "<<" && match(substr(line, i), /^<<-?[A-Za-z_][A-Za-z0-9_-]*[[:space:]]*$/)) {
                        tag = substr(line, i); sub(/^<<-?/, "", tag); gsub(/[[:space:]]+$/, "", tag)
                        heredoc = tag; emit(substr(line, i)); break
                    }
                    emit(c); i++
                }
                print out
            }' "$file" \
                | grep -En '(^[[:space:]]*(credentials|access_token|impersonate_service_account)([^A-Za-z0-9_-]|$))|([^A-Za-z0-9_.-](credentials|access_token|impersonate_service_account)[[:space:]]*=)' \
                | grep -Ev "$allowed_hcl" \
                | sed "s|^|$file:|"
        done)
    # Phase 6 accepts JSON-syntax leaves too; the same keys in a google or google-beta
    # provider block are judged the same way, with the expression in "${...}" form.
    json_files=$(find "terraform/$NEW_PROVIDER" terraform/modules -name '*.tf.json' -type f 2>/dev/null)
    for file in $json_files; do
        # Only provider configurations: a variable or output that happens to be named
        # `credentials` is not an identity argument. Terraform JSON allows each level
        # to be an object or an array of objects.
        found=$(jq -r '
            def items: if type == "array" then .[] else . end;
            .provider? // empty | items | to_entries[]
            | select(.key | IN("google", "google-beta")) | .value | items
            | to_entries[]
            | select(.key | IN("credentials", "access_token", "impersonate_service_account"))
            | "\(.key) = \(.value | tostring)"' "$file" 2>/dev/null) \
            || cannot_verify "could not parse $file as JSON to look for provider identity arguments"
        bad=$(printf '%s\n' "$found" | sed '/^$/d' \
            | grep -Ev "$allowed_json" \
            | sed "s|^|$file: |" || true)
        [ -z "$bad" ] || static="$static${static:+
}$bad"
    done
    [ -z "$static" ] \
        || fail "the committed configuration sets a Google identity argument other than the one allowed for this mode (key mode: none; WIF: the dynamic-credentials form), so runs may not use the declared identity: $static"
fi

if [ "$key_mode" = true ]; then
    exit 0
fi

# Tagged configurations (TFC_GCP_*_<TAG>, TFC_DEFAULT_GCP_*) give provider aliases their
# own pool, provider, and accounts. This check verifies the default configuration only,
# so any tag makes its verdict incomplete — reported as unverifiable, never as green.
tagged=$(printf '%s' "$vars" | jq -r '
    .data[].attributes | select(.category == "env") | .key
    | select(test("^TFC_(DEFAULT_)?GCP_"))
    | select(IN("TFC_GCP_PROVIDER_AUTH", "TFC_GCP_PRINCIPAL_TYPE",
                "TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL", "TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL",
                "TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL", "TFC_GCP_WORKLOAD_PROVIDER_NAME",
                "TFC_GCP_PROJECT_NUMBER", "TFC_GCP_WORKLOAD_POOL_ID",
                "TFC_GCP_WORKLOAD_PROVIDER_ID", "TFC_GCP_WORKLOAD_IDENTITY_AUDIENCE") | not)')
[ -z "$tagged" ] \
    || cannot_verify "$NEW_PROVIDER_WORKSPACE declares tagged GCP configurations ($(printf '%s' "$tagged" | tr '\n' ' ')); this check verifies only the default one — verify each tag's pool, condition, and accounts by hand"

[ "$(var TFC_GCP_PROVIDER_AUTH)" = "true" ] \
    || fail "TFC_GCP_PROVIDER_AUTH is not 'true' on $NEW_PROVIDER_WORKSPACE"
# Everything below judges the service accounts HCP impersonates. In workload_pool mode
# HCP authenticates as the pool principal directly and impersonates nothing, so those
# accounts' policies would be decoys and the phase fence would constrain nothing.
[ "$(var TFC_GCP_PRINCIPAL_TYPE)" = "service_account" ] \
    || fail "TFC_GCP_PRINCIPAL_TYPE must be 'service_account' on $NEW_PROVIDER_WORKSPACE; this check verifies impersonated accounts, which workload_pool mode bypasses"

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
    # The prefix must end exactly at the delimiter after the workspace: without the `:`,
    # `...:workspace:gcp` is also a prefix of `...:workspace:gcp-evil`; with anything
    # after it (`:run_phase:plan`), one phase's tokens are refused and applies fail.
    elif printf '%s' "$term" \
        | grep -Eqx "assertion\.sub\.startsWith\( *'organization:$org_re:project:[^:']+:workspace:$ws_re:' *\)"; then
        # The prefix also names the workspace's HCP project, and a stale name (the
        # workspace was moved) rejects every token while looking right. It is checked
        # against the project the workspace is actually in.
        term_project=$(printf '%s' "$term" | sed -n "s/.*:project:\([^:']*\):workspace:.*/\1/p")
        hcp_project_id=$(printf '%s' "$workspace" | jq -r '.data.relationships.project.data.id // empty')
        [ -n "$hcp_project_id" ] \
            || cannot_verify "the workspace response names no HCP project to compare with the condition's '$term_project'"
        hcp_project=$(curl -sf "$hcp_api/projects/$hcp_project_id" -H "Authorization: Bearer $HCP_TOKEN" \
            | jq -r '.data.attributes.name // empty') \
            || cannot_verify "could not read HCP project $hcp_project_id to compare with the condition"
        [ -n "$hcp_project" ] || cannot_verify "HCP project $hcp_project_id has no readable name"
        [ "$term_project" = "$hcp_project" ] \
            || fail "attribute condition names HCP project '$term_project', but workspace $NEW_PROVIDER_WORKSPACE is in '$hcp_project'; every token would be rejected"
        org_bound=true
        ws_bound=true
    # No run-phase term: one provider serves both phases, so a condition naming one
    # phase rejects every token of the other (applies silently fail after a green plan).
    # Phase isolation lives on the IAM members instead. No bare project-name term either:
    # the sub prefix above already carries (and verifies) the project, and a stale name
    # rejects every token while its syntax still looks right.
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
# resolves each role a foreign federated principal holds to its permissions. Editing a
# custom role (iam.roles.update) counts too: a harmless role already bound can be given
# getAccessToken after this check has passed.
escalation_permissions='["iam.serviceAccounts.getAccessToken","iam.serviceAccounts.getOpenIdToken",
  "iam.serviceAccounts.signBlob","iam.serviceAccounts.signJwt",
  "iam.serviceAccounts.implicitDelegation","iam.serviceAccounts.actAs",
  "iam.serviceAccountKeys.create","iam.serviceAccountKeys.upload",
  "iam.serviceAccountKeys.enable",
  "iam.serviceAccounts.setIamPolicy",
  "resourcemanager.projects.setIamPolicy",
  "iam.roles.update","iam.roles.undelete",
  "iam.workloadIdentityPools.update","iam.workloadIdentityPools.delete",
  "iam.workloadIdentityPools.setIamPolicy",
  "iam.workloadIdentityPoolProviders.create","iam.workloadIdentityPoolProviders.update",
  "iam.workloadIdentityPoolProviders.undelete"]'

# $1 = members, one per line; prints the run phases they admit (plan, apply), one per
# line. The pool-wide member and attribute sets other than the run phase admit both; a
# run-phase set or a subject ending in :run_phase:X admits only X.
phases_admitted() {
    printf '%s\n' "$1" | while IFS= read -r m; do
        case "$m" in
            *"/attribute.terraform_run_phase/"*) printf '%s\n' "${m##*/}" ;;
            principal://*":run_phase:"*) printf '%s\n' "${m##*:run_phase:}" ;;
            principalSet://*) printf 'plan\napply\n' ;;
            principal://*) printf 'plan\napply\n' ;;
        esac
    done | sort -u
}

# $1 = email, $2 = ERE every federated member must match, $3 = what that means,
# $4 = phases the account must admit ("plan apply", "plan", or "apply")
verify_account() {
    policy=$(gcloud iam service-accounts get-iam-policy "$1" --format=json 2>"$err") \
        || cannot_verify "gcloud could not read the IAM policy of $1: $(head -1 "$err")"
    # workloadIdentityUser is the documented grant, so every member of it — user:, group:
    # and serviceAccount: included — must be this pool's.
    # A condition on that binding (expired, or false for these tokens) can keep the
    # expected member from ever impersonating the account — and a split apply account
    # is not exercised by the speculative plan. Unevaluated, so unverifiable.
    printf '%s' "$policy" | jq -e '
        any(.bindings[]?; .role == "roles/iam.workloadIdentityUser" and .condition != null)' \
        >/dev/null \
        && cannot_verify "$1's workloadIdentityUser binding carries an IAM condition this check cannot evaluate; confirm by hand that it admits the expected tokens, or remove it"
    wiu=$(printf '%s' "$policy" | jq -r '
        [.bindings[]? | select(.role == "roles/iam.workloadIdentityUser") | .members[]] | .[]')
    [ -n "$wiu" ] || fail "no workload identity principal may impersonate $1"
    foreign=$(printf '%s\n' "$wiu" | grep -Ev "$2" || true)
    [ -z "$foreign" ] || fail "$1 is impersonable by members outside $3: $foreign"
    # The binding must also let in every phase that uses this account, or that phase's
    # runs cannot authenticate — a shared account fenced to plan passes the speculative
    # plan and fails the first apply.
    admitted=$(phases_admitted "$wiu")
    for phase in $4; do
        printf '%s\n' "$admitted" | grep -Fx "$phase" >/dev/null \
            || fail "$1 serves the $phase phase, but its workloadIdentityUser members admit only: $(printf '%s' "$admitted" | tr '\n' ' ')"
    done
    # A federated principal in ANY binding on the account is judged the same way: Token
    # Creator mints tokens just as well, and a role granted to a foreign pool or to the
    # plan phase would bypass the condition or the phase fence.
    federated=$(printf '%s' "$policy" | jq -r '
        [.bindings[]? | .members[] | select(test("^principal(Set)?://"))] | unique | .[]')
    foreign=$(printf '%s\n' "$federated" | sed '/^$/d' | grep -Ev "$2" || true)
    [ -z "$foreign" ] || fail "$1 grants a role to federated principals outside $3: $foreign"
}

if [ "$split" = true ]; then
    verify_account "$plan_email" "$pool_member" "$pool_path" "plan"
    verify_account "$apply_email" "$apply_only" \
        "$pool_path/attribute.terraform_run_phase/apply (a plan could otherwise mint apply credentials)" "apply"
else
    verify_account "$apply_email" "$pool_member" "$pool_path" "plan apply"
fi
# The rule for anything that can reach the apply account or mutate the verified pool.
if [ "$split" = true ]; then strict=$apply_only; else strict=$pool_member; fi

# The pool is a resource with its own IAM policy, invisible in the project policy. A
# federated principal outside the rule holding any role on it could administer the pool
# and loosen the condition verified above, so it is judged like a run account's policy.
pool_policy=$(gcloud iam workload-identity-pools get-iam-policy "$pool_id" \
    --project="$number" --location=global --format=json 2>"$err") \
    || cannot_verify "gcloud could not read the IAM policy of pool $pool_id: $(head -1 "$err")"
federated=$(printf '%s' "$pool_policy" | jq -r '
    [.bindings[]? | .members[] | select(test("^principal(Set)?://"))] | unique | .[]')
foreign=$(printf '%s\n' "$federated" | sed '/^$/d' | grep -Ev "$strict" || true)
[ -z "$foreign" ] || fail "pool $pool_id grants a role on itself to federated principals outside the trust: $foreign"

# Project-level grants are inherited by every service account in the project, so a
# federated principal holding an impersonation role there reaches the run accounts
# without appearing on their own policies. Folder and organization grants are inherited
# too and are NOT read here; gcp.md says so rather than letting exit 0 imply it.
# The run accounts' projects, and the pool's own project (by number), which may differ:
# a pool admin there could rewrite the condition this check verified.
# Each project is judged by the strictest thing it protects. With split accounts, the
# apply-phase fence applies where a grant can reach the apply account or mutate the
# verified pool; a project holding only the plan account needs just the pool rule, so a
# plan-phase principal may hold roles there. The pool's project is named by number and
# the accounts' by ID, so one project can appear twice; each pass is still correct for
# what it protects, erring strict.
project_of() {
    case "$1" in
        *@*.iam.gserviceaccount.com) p=${1#*@}; printf '%s\n' "${p%.iam.gserviceaccount.com}" ;;
        *) fail "$1 is not a user-managed service account (<name>@<project>.iam.gserviceaccount.com); create a dedicated one per gcp.md" ;;
    esac
}
plan_project=$(project_of "$plan_email") || exit 1
apply_project=$(project_of "$apply_email") || exit 1
projects="$number $strict
$apply_project $strict"
[ "$plan_project" = "$apply_project" ] || projects="$projects
$plan_project $pool_member"
printf '%s\n' "$projects" | while read -r project project_rule; do
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
rc=$?
[ "$rc" -eq 0 ] || exit "$rc"

exit 0
