#!/bin/sh
# Assert that the HCP token in the agent's environment can queue plans but CANNOT
# apply them. docs/policy.md works through every host-level control and finds that
# only two things enforce anything; this is the one inside the repository's control.
#
# Read-only. It reads each workspace and inspects the `permissions` block HCP
# returns, which reports the *calling token's* effective rights on that workspace.
#
# Deliberately NOT a dry `POST /runs/<id>/actions/apply`. That was the obvious
# probe and it is unsafe: if the token turns out to hold apply rights and the run
# is confirmable, the probe applies production infrastructure — the check would
# cause the thing it exists to detect. A read of the permissions block is direct
# evidence of the same fact and cannot change anything.
#
# Requires $ORG, $HCP_TOKEN and $hcp_api exported per references/config.md.
#
# Exit codes:
#   0  the token can plan and cannot apply, on every workspace checked
#   1  invariant BROKEN — a real verdict about the credential:
#        UNPROTECTED    the token can apply, so nothing constrains it
#        OVER-RESTRICTED the token cannot queue plans, so the plugin cannot work
#   2  COULD NOT VERIFY — missing config, an API read failed, or HCP returned no
#      permissions block. Distinct from 1 on purpose: an unreadable check proves
#      nothing about the credential and must never send anyone into a recovery
#      flow. The shared resume protocol must not execute this step's `run` on a 2.
set -u

fail() { echo "$1" >&2; exit 1; }
cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

for required in ORG HCP_TOKEN hcp_api; do
    eval "value=\${$required:-}"
    [ -n "$value" ] || cannot_verify "$required is not set; export it per references/config.md"
done

broken=""

for ws in cloudflare github-org; do
    body=$(curl -sf "$hcp_api/organizations/$ORG/workspaces/$ws" \
        -H "Authorization: Bearer $HCP_TOKEN") \
        || cannot_verify "could not read workspace $ws in organization $ORG"

    # `tostring`, NOT `// empty`. jq's alternative operator treats `false` as
    # absent, so `can-queue-apply: false` -- the state this check exists to
    # confirm -- came back indistinguishable from a missing block and reported
    # CANNOT VERIFY on a correctly configured token. Absent yields "null" here,
    # which is a real finding of its own: HCP told us nothing about this token.
    apply=$(printf '%s' "$body" | jq -r '.data.attributes.permissions["can-queue-apply"] | tostring')
    plan=$(printf '%s' "$body" | jq -r '.data.attributes.permissions["can-queue-run"] | tostring')

    [ "$apply" != null ] || cannot_verify "workspace $ws returned no can-queue-apply permission"

    if [ "$apply" = true ]; then
        broken="${broken}UNPROTECTED: the HCP token can apply runs on workspace '$ws'. Nothing else in this plugin constrains it — see docs/policy.md. Provision a plan-only identity and re-export HCP_TOKEN.
"
        continue
    fi

    # Only meaningful once apply is denied. Reported separately because the fix is
    # the opposite direction: grant Plan rather than remove Apply.
    if [ "$plan" != true ]; then
        broken="${broken}OVER-RESTRICTED: the HCP token cannot queue runs on workspace '$ws', so plan steps cannot work. The team needs the workspace 'Plan' permission, not 'Read'.
"
    fi
done

[ -z "$broken" ] || fail "$(printf '%s' "$broken")"
