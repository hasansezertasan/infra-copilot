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
#   1  invariant BROKEN — a real verdict about the repository
#   2  COULD NOT VERIFY — missing REPO, gh not authenticated, or an API read failed.
#      Distinct from 1 on purpose: an unreadable check proves nothing about branch
#      protection, and must not send anyone into a recovery flow.
set -u

fail() { echo "$1" >&2; exit 1; }
cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

[ -n "${REPO:-}" ] || cannot_verify "REPO is not set; export it per references/config.md"

# gh api is an *authenticated* request even for public repos. Without this the first
# call exits 4 and the failure reads as a stale context rather than a missing login.
gh auth status >/dev/null 2>&1 || cannot_verify "gh is not authenticated; run 'gh auth login' or export GH_TOKEN, then re-run"

# A greenfield repo has no protection yet: setup ends at green speculative plans
# without applying branch_protection.tf. Absent protection is "not yet", not "broken".
protected=$(gh api "repos/$REPO/branches/main" --jq '.protected') \
  || cannot_verify "could not read repos/$REPO/branches/main"
[ "$protected" = true ] || exit 0

required=$(gh api "repos/$REPO/branches/main/protection" \
  --jq '.required_status_checks.contexts[]? | select(startswith("Terraform Cloud/"))') \
  || cannot_verify "could not read branch protection for $REPO"

if [ -z "$required" ]; then
    fail "UNDERPROTECTED: branch protection requires no 'Terraform Cloud/' context, so HCP plans do not gate merges. PRs are mergeable without a plan — this is not a stale-context incident."
fi

# Which context is published *now* is decided by the status timestamps, not by the order
# candidates happen to come back in. Ordering by list position was wrong three ways: an
# old main commit at HEAD, a PR-less checkout, and an older PR that sorts first on
# updated_at while a later PR carries the new context. Every one of those reported green
# on the incident. The newest status wins regardless of which candidate carried it.
published=""

collect() {  # $1 = sha, $2 = "tolerate" to allow a read failure
    reported=$(gh api "repos/$REPO/commits/$1/status" \
      --jq '.statuses[] | select(.context | startswith("Terraform Cloud/")) | "\(.updated_at) \(.context)"' 2>/dev/null)
    if [ $? -ne 0 ]; then
        [ "${2:-}" = tolerate ] && return 0
        cannot_verify "could not read commit status for $1"
    fi
    [ -n "$reported" ] && published="$published
$reported"
    return 0
}

candidates=$(gh api "repos/$REPO/pulls?state=open&sort=updated&direction=desc&per_page=20" \
  --jq '.[].head.sha') || cannot_verify "could not list open pull requests for $REPO"
recent=$(gh api "repos/$REPO/commits?per_page=20" --jq '.[].sha') \
  || cannot_verify "could not list commits for $REPO"

# A local HEAD may be unpushed, so a failed read there is tolerated rather than fatal.
head_sha=$(git rev-parse HEAD 2>/dev/null) || head_sha=""
[ -n "$head_sha" ] && collect "$head_sha" tolerate

seen=""
for sha in $candidates $recent; do
    case " $seen " in *" $sha "*) continue ;; esac
    seen="$seen $sha"
    [ "$sha" = "$head_sha" ] && continue
    collect "$sha"
done

published=$(printf '%s\n' "$published" | grep '^[0-9]')
# Nothing anywhere carries an HCP status. Unverifiable, not broken.
[ -n "$published" ] || exit 0

# Lexicographic sort is chronological for ISO-8601 UTC timestamps, which is what the
# commit status API returns.
newest_at=$(printf '%s\n' "$published" | sort | tail -1 | cut -d' ' -f1)
current=$(printf '%s\n' "$published" | grep "^$newest_at " | cut -d' ' -f2- | sort -u)

tmp=$(mktemp) || cannot_verify "mktemp failed"
printf '%s\n' "$current" > "$tmp"
missing=$(printf '%s\n' "$required" | grep -vxF -f "$tmp")
rm -f "$tmp"

if [ -n "$missing" ]; then
    fail "BLOCKED: required but not published by the current connection (newest status at $newest_at publishes: $(printf '%s' "$current" | tr '\n' ' ')): $missing"
fi
exit 0
