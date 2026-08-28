#!/bin/sh
# Assert that every status context branch protection REQUIRES is one HCP actually
# PUBLISHES. A required context nobody posts blocks every PR forever on
# "Expected — Waiting for status to be reported" while every other check reads green.
#
# Read-only: GitHub API reads plus a comparison in $TMPDIR. Safe for infra-copilot:status.
#
# Requires $REPO (owner/name) exported per references/config.md.
#
# Exit codes:
#   0  invariant holds, or nothing to verify yet (protection not applied; no HCP
#      status published anywhere yet)
#   1  invariant broken, or the evidence could not be read
set -u

fail() { echo "$1" >&2; exit 1; }

[ -n "${REPO:-}" ] || fail "REPO is not set; export it per references/config.md"

# gh api is an *authenticated* request even for public repos. Without this the first
# call exits 4 and the failure reads as a stale context rather than a missing login.
gh auth status >/dev/null 2>&1 || fail "gh is not authenticated; run 'gh auth login' or export GH_TOKEN, then re-run"

# A greenfield repo has no protection yet: setup ends at green speculative plans
# without applying branch_protection.tf. Absent protection is "not yet", not "broken".
protected=$(gh api "repos/$REPO/branches/main" --jq '.protected') \
  || fail "could not read repos/$REPO/branches/main"
[ "$protected" = true ] || exit 0

required=$(gh api "repos/$REPO/branches/main/protection" \
  --jq '.required_status_checks.contexts[]? | select(startswith("Terraform Cloud/"))') \
  || fail "could not read branch protection for $REPO"

if [ -z "$required" ]; then
    fail "UNDERPROTECTED: branch protection requires no 'Terraform Cloud/' context, so HCP plans do not gate merges. PRs are mergeable without a plan — this is not a stale-context incident."
fi

# Compare $required against the contexts published on one commit.
compare() {
    tmp=$(mktemp) || fail "mktemp failed"
    printf '%s\n' "$1" > "$tmp"
    missing=$(printf '%s\n' "$required" | grep -vxF -f "$tmp")
    rm -f "$tmp"
    [ -z "$missing" ] && return 0
    echo "BLOCKED: required but never published (seen on $2): $missing" >&2
    return 1
}

# Freshest evidence first. Open PR heads matter most: after the connection is rebuilt,
# main still carries the OLD context while the blocked PR's head carries the new one.
# Trusting main here would report green on exactly the incident this exists to catch.
candidates=$(gh api "repos/$REPO/pulls?state=open&sort=updated&direction=desc&per_page=20" \
  --jq '.[].head.sha') || fail "could not list open pull requests for $REPO"

# Local HEAD comes AFTER the PR heads on purpose. Running /infra-status from a main
# checkout puts an old main commit at HEAD, still carrying the old context; trusting it
# first reports green on the incident. If HEAD is a pushed PR branch its sha is already
# in the list above, so this only adds value for an unpushed or PR-less branch.
head_sha=$(git rev-parse HEAD 2>/dev/null) || head_sha=""
[ -n "$head_sha" ] && candidates="$candidates $head_sha"

recent=$(gh api "repos/$REPO/commits?per_page=20" --jq '.[].sha') \
  || fail "could not list commits for $REPO"
candidates="$candidates $recent"

seen=""
for sha in $candidates; do
    case " $seen " in *" $sha "*) continue ;; esac
    seen="$seen $sha"
    reported=$(gh api "repos/$REPO/commits/$sha/status" --jq '.statuses[].context' 2>/dev/null) \
      || continue
    printf '%s\n' "$reported" | grep -q '^Terraform Cloud/' || continue
    compare "$reported" "$sha"
    exit $?
done

# Nothing anywhere carries an HCP status. Unverifiable, not broken.
exit 0
