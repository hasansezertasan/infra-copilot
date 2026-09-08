#!/bin/sh
# Assert that the HCP credential this repo's tooling would use can queue plans but
# CANNOT cause an apply. docs/policy.md works through every host-level control and
# finds only two that enforce anything; this is the one inside the repo's control.
#
# It checks the credential TERRAFORM would use, not $HCP_TOKEN. `terraform` never
# reads $HCP_TOKEN. It reads TF_TOKEN_app_terraform_io, then credentials configured
# in the CLI config. An earlier version verified $HCP_TOKEN alone, which proved
# nothing about an apply started through the Terraform CLI -- the primary way
# anything here would apply.
#
# Read-only, and deliberately NOT a dry `POST /runs/<id>/actions/apply`: if the
# token does hold apply rights and the run is confirmable, that probe applies
# production infrastructure -- the check would cause the thing it detects.
#
# Requires $ORG, $hcp_api and $REPO exported per references/config.md. $REPO is not
# optional: it tells this repository's workspaces from another repository's in the
# same organization, where both have a terraform/cloudflare working directory.
#
# Exit codes:
#   0  the credential can plan and cannot cause an apply, everywhere it can see
#   1  invariant BROKEN — a real verdict about the credential:
#        UNPROTECTED     it can apply, change workspace settings, or a workspace
#                        auto-applies what it queues. Asserted for EVERY visible
#                        workspace: the credential must not be able to change
#                        anything, anywhere.
#        OVER-RESTRICTED it cannot queue runs on a workspace belonging to $REPO.
#                        Scoped deliberately — this repo needs Plan only where it
#                        runs, and demanding it elsewhere would widen access for
#                        no reason.
#        SPLIT-BRAIN     $HCP_TOKEN and terraform's credential are different tokens
#   2  COULD NOT VERIFY — missing config, no credential, jq or curl missing, an API
#      read failed, unreadable evidence, or a managed leaf with no visible
#      workspace. Distinct from 1 on purpose: unreadable evidence proves nothing
#      and must never send anyone into a recovery flow. The shared resume protocol
#      must not execute this step's `run` on a 2.
#
# A verdict outranks uncertainty. If one workspace definitely allows an apply and
# another cannot be read, this exits 1 and names both: `status` renders 2 as "?,
# nothing to fix", which would bury proof that the boundary is open.
set -u

cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

# grep included: it detects the CLI-config credentials block below, and an absent
# grep would exit 127 rather than the tri-state 2 the step contract requires.
for tool in curl jq grep; do
    command -v "$tool" >/dev/null 2>&1 \
        || cannot_verify "$tool is not on PATH; preflight installs it"
done

# REPO is required, not optional. Skipping the correlation when it was unset let
# another repository's workspaces -- same working directory, different repo --
# satisfy this repo's inventory, which is the exact case the correlation exists for.
for required in ORG hcp_api REPO; do
    eval "value=\${$required:-}"
    [ -n "$value" ] || cannot_verify "$required is not set; export it per references/config.md"
done

# Checked before the credential is resolved, let alone sent. $hcp_api comes from a
# repo-local config file, so an edited or mistyped value would put a bearer token in
# a request to an arbitrary host -- over plaintext if the scheme were http.
[ "$hcp_api" = "https://app.terraform.io/api/v2" ] \
    || cannot_verify "\$hcp_api is '$hcp_api', not https://app.terraform.io/api/v2; refusing to send an HCP credential to an unexpected endpoint"

broken=""   # definite verdicts
unknown=""  # evidence that could not be read

note_unknown() { unknown="${unknown}  - $1
"; }

# ── Which credential would terraform use ────────────────────────────────────────
# Terraform's documented order is TF_TOKEN_<host>, then credentials in the CLI
# config. What it does NOT document is which wins between a hand-written
# `credentials` block in the CLI config file and the credentials.tfrc.json that
# `terraform login` writes. Rather than guess, refuse to verify when a CLI-config
# block for this host exists: verifying the wrong token would be worse than
# admitting we cannot tell.
cli_config=${TF_CLI_CONFIG_FILE:-${HOME:-}/.terraformrc}
credentials="${HOME:-}/.terraform.d/credentials.tfrc.json"

if [ -n "${TF_TOKEN_app_terraform_io:-}" ]; then
    token=$TF_TOKEN_app_terraform_io
    source_description="TF_TOKEN_app_terraform_io"
elif [ -r "$cli_config" ] && grep -q 'credentials' "$cli_config" 2>/dev/null; then
    # Deliberately coarse: any `credentials` keyword in the CLI config refuses. A
    # same-line regex for the hostname missed valid HCL -- comments count as
    # whitespace, so `credentials /* managed */ "app.terraform.io"` is legal and
    # slipped past, leaving an apply-capable CLI-config token unexamined. Parsing
    # HCL is out of scope for a POSIX check, so anything that might declare a
    # credential is undeterminable rather than assumed irrelevant.
    cannot_verify "$cli_config contains a credentials declaration. Terraform's docs do not state whether it or $credentials wins, and this check does not parse HCL, so which token terraform uses cannot be determined. Remove it, or set TF_TOKEN_app_terraform_io so the source is unambiguous."
elif [ -r "$credentials" ]; then
    token=$(jq -er '.credentials["app.terraform.io"].token' "$credentials" 2>/dev/null) \
        || cannot_verify "$credentials has no app.terraform.io token; run 'terraform login'"
    source_description=$credentials
else
    cannot_verify "no HCP credential found; set TF_TOKEN_app_terraform_io or run 'terraform login'"
fi

# A plan-only token here beside an apply-capable $HCP_TOKEN means the API calls in
# steps.yaml and terraform are two different identities, so verifying either says
# nothing about the other.
if [ -n "${HCP_TOKEN:-}" ] && [ "$HCP_TOKEN" != "$token" ]; then
    broken="${broken}SPLIT-BRAIN: \$HCP_TOKEN is not the credential terraform would use ($source_description), so the plugin's API calls and terraform authenticate as different identities and neither can be verified from the other. Export HCP_TOKEN from that same source per references/config.md.
"
fi

# ── Every workspace the credential can see ──────────────────────────────────────
# Not a fixed pair: the `add` workflow creates more, and a hardcoded list would
# ignore them.
boolean () {  # $1 = json object, $2 = key path expression; prints true/false
    printf '%s' "$1" | jq -er "$2 | if type == \"boolean\" then tostring else \"not-a-boolean\" end" 2>/dev/null
}

page=1
found=0
# Terraform targets a workspace by NAME, declared in each leaf's `cloud` block.
# Matching on repository plus working-directory let the wrong workspace satisfy
# the inventory: a stale `cloudflare-copy` connected to the same repo with the
# same working directory passed, while the plan the leaf actually runs could not
# be queued.
leaf_workspace_name () {  # $1 = leaf dir; prints its name, or TAGS, or nothing
    # Scoped to the `workspaces` block, and `name` must be a whole attribute key.
    # An unanchored match read `hostname = "app.terraform.io"` -- legal in a cloud
    # block for Terraform Enterprise -- as the workspace name, which reported a
    # correctly configured leaf as unverifiable. `tags` is mutually exclusive with
    # `name` and selects a set rather than one workspace, and its map form can
    # itself contain a `name` key, so it is reported as TAGS rather than guessed.
    awk '
        /(^|[^[:alnum:]_])cloud[[:space:]]*{/ { incloud = 1; next }
        incloud && /(^|[^[:alnum:]_])workspaces[[:space:]]*{/ { inws = 1 }
        inws && /(^|[^[:alnum:]_])tags[[:space:]]*=/ { print "TAGS"; exit }
        inws && match($0, /(^|[^[:alnum:]_])name[[:space:]]*=[[:space:]]*"[^"]*"/) {
            value = substr($0, RSTART, RLENGTH)
            sub(/^[^"]*"/, "", value)
            sub(/"$/, "", value)
            print value
            exit
        }
        inws && /}/ { inws = 0 }
    ' "$1"/*.tf 2>/dev/null
}

seen_repo_names=""
ids=""      # workspace ids seen, to detect the list changing mid-scan

# Nothing inside this loop exits directly. Once a page has been processed the
# script may already hold a definite verdict, and `status` renders exit 2 as "?,
# nothing to fix" -- so an unrelated read failure here would hide proof that the
# credential can apply. Uncertainty is recorded and the final selection below
# decides. The first version fixed this for per-workspace values only and left
# every page-level path exiting straight out.
while : ; do
    if ! body=$(curl -sf "$hcp_api/organizations/$ORG/workspaces?page%5Bsize%5D=100&page%5Bnumber%5D=$page" \
        -H "Authorization: Bearer $token"); then
        note_unknown "page $page of the workspace list for $ORG could not be read as $source_description"
        break
    fi

    if ! count=$(printf '%s' "$body" | jq -e '.data | length' 2>/dev/null); then
        note_unknown "page $page of the workspace list for $ORG was not the expected JSON"
        break
    fi
    ids="$ids $(printf '%s' "$body" | jq -r '.data[].id' 2>/dev/null | tr '\n' ' ')"
    if [ "$count" -eq 0 ] 2>/dev/null; then
        # An empty first page means no workspaces. An empty later page means the
        # set shifted between requests -- deleting an early workspace moves an
        # entry back across the boundary -- so something may never have been
        # inspected. Breaking silently would exit 0 on a partial scan.
        [ "$page" -eq 1 ] || note_unknown "page $page of $ORG came back empty although earlier pages were full, so the workspace list changed mid-scan and some may not have been inspected"
        break
    fi

    index=0
    while [ "$index" -lt "$count" ]; do
        if ! entry=$(printf '%s' "$body" | jq -e ".data[$index]" 2>/dev/null); then
            note_unknown "workspace $index on page $page of $ORG could not be read"
            index=$((index + 1))
            continue
        fi
        if ! name=$(printf '%s' "$entry" | jq -er '.attributes.name' 2>/dev/null); then
            note_unknown "a workspace on page $page of $ORG has no name"
            index=$((index + 1))
            continue
        fi
        index=$((index + 1))
        found=$((found + 1))

        # The type is asserted inside jq, before any conversion. `tostring` alone
        # renders the JSON string "false" and the boolean false as the same shell
        # text. `// empty` is also wrong: jq's alternative operator treats false as
        # absent, which made the state this check confirms read as a missing block.
        apply=$(boolean "$entry" '.attributes.permissions["can-queue-apply"]')
        plan=$(boolean "$entry" '.attributes.permissions["can-queue-run"]')
        update=$(boolean "$entry" '.attributes.permissions["can-update"]')
        auto=$(boolean "$entry" '.attributes["auto-apply"]')

        for pair in "can-queue-apply:$apply" "can-queue-run:$plan" \
                    "can-update:$update" "auto-apply:$auto"; do
            case ${pair#*:} in
                true|false) : ;;
                *) note_unknown "workspace '$name' reported ${pair%%:*} as '${pair#*:}', not a boolean" ;;
            esac
        done

        [ "$apply" != true ] || broken="${broken}UNPROTECTED: the credential in $source_description can apply runs on workspace '$name'.
"
        # can-queue-apply false does not help if the workspace applies on its own:
        # a plan-capable credential queues a non-speculative run and HCP applies the
        # successful plan. Phase 1 checks this for the bootstrap pair only, so
        # workspaces `add` creates later are covered here or nowhere.
        # Requires can-queue-run too. Auto-apply on a workspace this credential
        # cannot queue is not reachable by it, and reporting it sent the operator
        # to change an unrelated workspace's policy.
        if [ "$auto" = true ] && [ "$plan" = true ]; then
            broken="${broken}UNPROTECTED: workspace '$name' has auto-apply enabled and this credential can queue runs there, so a run it starts is applied without confirmation.
"
        fi
        # Settings include auto-apply itself, so this is an elevation path even when
        # the apply permission is denied.
        [ "$update" != true ] || broken="${broken}UNPROTECTED: the credential can update settings on workspace '$name', including auto-apply, so the boundary is self-removable.
"
        # `working-directory` is not unique across an organization: two repos
        # bootstrapped by this plugin both have terraform/cloudflare. Only count a
        # directory toward this repo's inventory when the workspace is connected to
        # this repo.
        directory=$(printf '%s' "$entry" | jq -r '.attributes["working-directory"] // empty' 2>/dev/null)
        identifier=$(printf '%s' "$entry" | jq -r '.attributes["vcs-repo"].identifier // empty' 2>/dev/null)
        ours=false
        if [ "$identifier" = "$REPO" ]; then
            ours=true
            seen_repo_names="$seen_repo_names $name"
        fi

        # Scoped to this repository, unlike the assertions above. The step needs
        # Plan only where this repo runs; a workspace the team can merely read
        # elsewhere in the organization is not this repo's business, and telling
        # the operator to grant Plan on it would widen access to that workspace's
        # plans, state and variables for nothing.
        if [ "$ours" = true ] && [ "$apply" = false ] && [ "$plan" = false ]; then
            broken="${broken}OVER-RESTRICTED: the credential cannot queue runs on workspace '$name', which belongs to $REPO, so plan steps cannot work there. Grant the team the workspace 'Plan' permission, not 'Read'.
"
        fi
    done

    # Fail closed, and hand the shell a plain integer. `numbers` accepts 2.0 and
    # 1e3, and this jq does not normalise them -- `tostring` yields "2.0" and
    # "1E+3", both of which POSIX `test -lt` rejects as operands. The comparison
    # then errored and `|| break` read that as "no more pages", truncating the
    # inventory silently. Integral values are accepted and rendered through
    # `floor`; genuinely fractional ones are rejected.
    if ! total_pages=$(printf '%s' "$body" | jq -er '
            .meta.pagination["total-pages"]
            | if type == "number" and . == floor and . > 0
              then (floor | tostring) else empty end
        ' 2>/dev/null); then
        note_unknown "page $page of $ORG carried no positive-integer meta.pagination.total-pages, so later pages could not be reached"
        break
    fi
    [ "$page" -lt "$total_pages" ] || break
    page=$((page + 1))
done

[ "$found" -gt 0 ] || note_unknown "the credential can see no workspaces in $ORG, so its rights cannot be determined"

# The visible set cannot reveal a workspace hidden by the very grant being checked:
# omit Plan on one leaf and it vanishes from the list, leaving every visible entry
# correct. So compare against an inventory derived from the repository instead.
# A workspace deleted mid-scan shifts later entries onto pages already read, and
# the skipped one is never inspected; one added after its page was read lands on a
# page the first scan never requested. Neither shows up as an empty page, and the
# API offers no snapshot -- so the whole list is read a second time, following
# pagination afresh, and both the id set and the page count are compared. Running
# it unconditionally costs one extra request for the handful of workspaces this
# plugin creates, and an earlier `page > 1` guard meant a single full page that
# gained a second page was never re-read at all.
recheck=""
verify_page=1
verify_pages=1
while : ; do
    again=$(curl -sf "$hcp_api/organizations/$ORG/workspaces?page%5Bsize%5D=100&page%5Bnumber%5D=$verify_page" \
        -H "Authorization: Bearer $token") || { recheck="unreadable"; break; }
    recheck="$recheck $(printf '%s' "$again" | jq -r '.data[].id' 2>/dev/null | tr '\n' ' ')"
    verify_pages=$(printf '%s' "$again" | jq -er '.meta.pagination["total-pages"]
                    | if type == "number" and . == floor and . > 0
                      then (floor | tostring) else empty end' 2>/dev/null) \
        || { recheck="unreadable"; break; }
    [ "$verify_page" -lt "$verify_pages" ] || break
    verify_page=$((verify_page + 1))
done
first_set=$(printf '%s' "$ids" | tr ' ' '\n' | grep -v '^$' | sort | tr '\n' ' ')
again_set=$(printf '%s' "$recheck" | tr ' ' '\n' | grep -v '^$' | sort | tr '\n' ' ')
# Comparing page counts as well was redundant -- a workspace added on a new page
# changes the id set too -- and `pages_seen` goes stale when the scan breaks
# early, which would have reported a change that never happened.
if [ "$first_set" != "$again_set" ]; then
    note_unknown "the workspace list in $ORG changed while it was being read, so an entry may have shifted between pages or landed on a page this scan never requested; re-run when the organization is not being modified"
fi

for leaf in terraform/*/; do
    [ -d "$leaf" ] || continue    # no terraform/ yet: nothing to compare
    directory=${leaf%/}
    expected=$(leaf_workspace_name "$directory")
    if [ "$expected" = TAGS ]; then
        note_unknown "$directory selects its workspaces by tags rather than a name, so which workspace it targets cannot be determined from the repository"
        continue
    fi
    if [ -z "$expected" ]; then
        note_unknown "$directory declares no cloud workspace name, so the workspace it targets cannot be identified"
        continue
    fi
    case " $seen_repo_names " in
        *" $expected "*) continue ;;
    esac
    note_unknown "workspace '$expected', which $directory targets, is not visible to this credential and connected to $REPO: either it does not exist, or the credential lacks the Plan grant on it"
done

if [ -n "$broken" ]; then
    printf '%s' "$broken" >&2
    [ -z "$unknown" ] || printf 'Additionally, evidence that could not be read:\n%s' "$unknown" >&2
    exit 1
fi
if [ -n "$unknown" ]; then
    # Not via cannot_verify(): command substitution eats the trailing newlines of a
    # multi-line list, which printed the prefix with an empty body.
    printf 'CANNOT VERIFY: evidence this check needs could not be read:\n%s' "$unknown" >&2
    exit 2
fi
