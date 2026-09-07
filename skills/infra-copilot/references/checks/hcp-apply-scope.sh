#!/bin/sh
# Assert that the HCP credential this repo's tooling would use can queue plans but
# CANNOT apply them. docs/policy.md works through every host-level control and finds
# that only two things enforce anything; this is the one inside the repo's control.
#
# It checks the credential TERRAFORM would use, not $HCP_TOKEN. That distinction is
# the whole point: `terraform` never reads $HCP_TOKEN. It reads
# TF_TOKEN_app_terraform_io, or failing that ~/.terraform.d/credentials.tfrc.json,
# and the env var takes precedence. An earlier version of this check verified
# $HCP_TOKEN alone, which proved nothing about an apply started through the
# Terraform CLI -- the primary way anything here would apply. If the two differ, that is itself the finding: one of
# them is unverified, so neither result means anything.
#
# Read-only. It lists the workspaces the credential can see and inspects the
# `permissions` block HCP returns, which reports the calling token's own effective
# rights.
#
# Deliberately NOT a dry `POST /runs/<id>/actions/apply`. That probe is unsafe: if
# the token does hold apply rights and the run is confirmable, it applies production
# infrastructure -- the check would cause the thing it exists to detect.
#
# Requires $ORG and $hcp_api exported per references/config.md.
#
# Exit codes:
#   0  the credential can plan and cannot apply, on every workspace it can see
#   1  invariant BROKEN — a real verdict about the credential:
#        UNPROTECTED     it can apply some workspace
#        OVER-RESTRICTED it cannot queue runs on some workspace
#        SPLIT-BRAIN     $HCP_TOKEN and terraform's credential are different tokens
#   2  COULD NOT VERIFY — missing config, no credential found, jq or curl missing,
#      an API read failed, or HCP returned no usable permissions block. Distinct
#      from 1 on purpose: an unreadable check proves nothing about the credential
#      and must never send anyone into a recovery flow. The shared resume protocol
#      must not execute this step's `run` on a 2.
set -u

fail() { echo "$1" >&2; exit 1; }
cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

for tool in curl jq; do
    command -v "$tool" >/dev/null 2>&1 \
        || cannot_verify "$tool is not on PATH; preflight installs it"
done

for required in ORG hcp_api; do
    eval "value=\${$required:-}"
    [ -n "$value" ] || cannot_verify "$required is not set; export it per references/config.md"
done

# Resolve the credential terraform itself would use, in terraform's own order.
credentials="${HOME:-}/.terraform.d/credentials.tfrc.json"
if [ -n "${TF_TOKEN_app_terraform_io:-}" ]; then
    token=$TF_TOKEN_app_terraform_io
    source_description="TF_TOKEN_app_terraform_io"
elif [ -r "$credentials" ]; then
    token=$(jq -er '.credentials["app.terraform.io"].token' "$credentials" 2>/dev/null) \
        || cannot_verify "$credentials has no app.terraform.io token; run 'terraform login'"
    source_description=$credentials
else
    cannot_verify "no HCP credential found; set TF_TOKEN_app_terraform_io or run 'terraform login'"
fi

# A plan-only token here with an apply-capable $HCP_TOKEN (or the reverse) means the
# API calls in steps.yaml and `terraform` are two different identities, so verifying
# either one says nothing about the other.
if [ -n "${HCP_TOKEN:-}" ] && [ "$HCP_TOKEN" != "$token" ]; then
    fail "SPLIT-BRAIN: \$HCP_TOKEN is not the credential terraform would use ($source_description). The plugin's API calls and terraform would authenticate as different identities, so neither can be verified from the other. Export HCP_TOKEN from that same source per references/config.md."
fi

api() {  # $1 = path; prints the body, or reports CANNOT VERIFY
    curl -sf "$hcp_api/$1" -H "Authorization: Bearer $token" \
        || cannot_verify "could not read $1 as $source_description"
}

# Every workspace the credential can see, not a fixed pair. A team token lists only
# the workspaces its team may access, so this set is exactly the right scope -- and
# it picks up workspaces the `add` workflow creates later, which a hardcoded
# cloudflare/github-org loop silently ignored.
page=1
found=0
broken=""
seen_directories=""

while : ; do
    body=$(api "organizations/$ORG/workspaces?page%5Bsize%5D=100&page%5Bnumber%5D=$page") || exit 2

    count=$(printf '%s' "$body" | jq -e '.data | length' 2>/dev/null) \
        || cannot_verify "workspace list for $ORG was not the expected JSON"
    [ "$count" -gt 0 ] 2>/dev/null || break

    index=0
    while [ "$index" -lt "$count" ]; do
        entry=$(printf '%s' "$body" | jq -e ".data[$index]" 2>/dev/null) \
            || cannot_verify "could not read workspace $index of $ORG"
        name=$(printf '%s' "$entry" | jq -er '.attributes.name' 2>/dev/null) \
            || cannot_verify "a workspace in $ORG has no name"

        # The type is asserted inside jq, before any conversion. `tostring` alone
        # renders the JSON string "false" and the boolean false as the same shell
        # text, so a malformed response passed the exact-boolean check below.
        # `// empty` is also wrong here: jq's alternative operator treats `false`
        # as absent, which made the state this check exists to confirm read as a
        # missing block.
        permission () {  # $1 = permission key; prints true/false, or fails
            printf '%s' "$entry" | jq -er --arg key "$1" '
                .attributes.permissions[$key]
                | if type == "boolean" then tostring else "not-a-boolean" end
            ' 2>/dev/null
        }
        apply=$(permission can-queue-apply) \
            || cannot_verify "workspace $name returned no readable permissions block"
        plan=$(permission can-queue-run) \
            || cannot_verify "workspace $name returned no readable permissions block"

        # Exact booleans only. Anything else -- null, 0, a string, a renamed field --
        # is absence of evidence, not evidence of absence.
        case "$apply" in
            true) broken="${broken}UNPROTECTED: the credential in $source_description can apply runs on workspace '$name'. Nothing else in this plugin constrains it. Provision a plan-only identity per this step's run.
" ;;
            false) : ;;
            *) cannot_verify "workspace $name reported can-queue-apply as '$apply', not a boolean" ;;
        esac
        case "$plan" in
            true|false) : ;;
            *) cannot_verify "workspace $name reported can-queue-run as '$plan', not a boolean" ;;
        esac
        if [ "$apply" = false ] && [ "$plan" = false ]; then
            broken="${broken}OVER-RESTRICTED: the credential cannot queue runs on workspace '$name', so plan steps cannot work there. Grant the team the workspace 'Plan' permission, not 'Read'.
"
        fi

        directory=$(printf '%s' "$entry" | jq -r '.attributes["working-directory"] // empty' 2>/dev/null)
        [ -z "$directory" ] || seen_directories="$seen_directories $directory"

        found=$((found + 1))
        index=$((index + 1))
    done

    total_pages=$(printf '%s' "$body" | jq -r '.meta.pagination["total-pages"] // 1' 2>/dev/null)
    case "$total_pages" in
        ''|*[!0-9]*) total_pages=1 ;;
    esac
    [ "$page" -lt "$total_pages" ] || break
    page=$((page + 1))
done

# No workspaces at all proves nothing: a team with no access reads as "cannot apply
# anything" while telling us nothing about the credential's rights.
[ "$found" -gt 0 ] \
    || cannot_verify "the credential in $source_description can see no workspaces in $ORG, so its rights cannot be determined"

# The visible set cannot reveal a workspace hidden by the very grant being checked:
# omit Plan for one leaf and it simply vanishes from the list, leaving every visible
# entry correct and the check green. So compare against an inventory derived from
# the repository instead -- each terraform/<leaf>/ directory is a workspace's
# working-directory, which is independent of what the credential can see.
for leaf in terraform/*/; do
    [ -d "$leaf" ] || continue                      # no terraform/ yet: nothing to compare
    directory=${leaf%/}
    case " $seen_directories " in
        *" $directory "*) continue ;;
    esac
    # Cannot tell "no grant" from "workspace not created yet" without an
    # organization-level read the plan-only credential is not meant to have, and
    # guessing either way would be a verdict this cannot support.
    cannot_verify "no workspace visible for $directory: either it has no workspace yet, or the credential in $source_description lacks the Plan grant on it. Grant the team Plan on that workspace, or finish phase 1 for it, then re-run."
done

[ -z "$broken" ] || fail "$(printf '%s' "$broken")"
