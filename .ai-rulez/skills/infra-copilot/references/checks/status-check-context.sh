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
#   0  invariant holds, or there is nothing to verify yet (greenfield: no protection
#      applied and no HCP status published anywhere)
#   1  invariant BROKEN — a real verdict about the repository (BLOCKED or UNDERPROTECTED)
#   2  COULD NOT VERIFY — missing REPO, gh not authenticated, or an API read failed.
#      Distinct from 1 on purpose: an unreadable check proves nothing about branch
#      protection and must never send anyone into a recovery flow. The shared resume
#      protocol must not execute this step's `run` on a 2.
set -u

fail() { echo "$1" >&2; exit 1; }
cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

[ -n "${REPO:-}" ] || cannot_verify "REPO is not set; export it per references/config.md"

# gh api is an *authenticated* request even for public repos, and exits 4 specifically
# when authentication is required. Checking that code beats a `gh auth status` pre-flight:
# without filters that command tests every account on every host and exits 1 if any of
# them has a problem, so one stale account on an unrelated host would report a missing
# login while a perfectly usable github.com account sat right there.
protected=$(gh api "repos/$REPO/branches/main" --jq '.protected')
case $? in
    0) : ;;
    4) cannot_verify "gh is not authenticated for this host; run 'gh auth login' or export GH_TOKEN, then re-run" ;;
    *) cannot_verify "could not read repos/$REPO/branches/main" ;;
esac

# Absent protection is not this check's business. setup ends at green speculative plans
# without applying branch_protection.tf, and HCP already posts aggregated statuses by
# then, so no observable signal here separates "not applied yet" from "removed". Guessing
# from published statuses blocked the greenfield flow. Whether protection *should* exist
# is a separate invariant owned by whatever applies that resource.
if [ "$protected" != true ]; then
    exit 0
fi

required=$(gh api "repos/$REPO/branches/main/protection" \
      --jq '.required_status_checks.contexts[]? | select(startswith("Terraform Cloud/"))') \
  || cannot_verify "could not read branch protection for $REPO"

# Decide this before any further reads. The verdict is already proven, and a rate-limited
# PR or commit request afterwards would turn it into CANNOT VERIFY and hide the fact that
# merges are proceeding ungated.
if [ -z "$required" ]; then
    fail "UNDERPROTECTED: branch protection requires no 'Terraform Cloud/' context, so HCP plans do not gate merges. PRs are mergeable without a plan — this is not a stale-context incident."
fi

# Which context is published *now* is decided by the status timestamps, not by the order
# candidates come back in. Ordering by list position was wrong three ways: an old main
# commit at HEAD, a PR-less checkout, and an older PR sorting first on updated_at while a
# later PR carries the new context. All three reported green on the incident.
published=""

collect() {  # $1 = sha, $2 = "tolerate" to allow a read failure
    # --paginate: the combined-status endpoint defaults to 30 contexts per page, and a
    # commit with more than that could hide the HCP status outside the first page.
    reported=$(gh api --paginate "repos/$REPO/commits/$1/status?per_page=100" \
      --jq '.statuses[] | select(.context | startswith("Terraform Cloud/")) | "\(.updated_at) \(.context)"' 2>/dev/null)
    if [ $? -ne 0 ]; then
        [ "${2:-}" = tolerate ] && return 0
        cannot_verify "could not read commit status for $1"
    fi
    [ -n "$reported" ] && published="$published
$reported"
    return 0
}

# --paginate, because a repo with more than one page of open PRs can hide the head that
# carries the newly published context behind 20 older PRs with recent comments.
prs=$(gh api --paginate "repos/$REPO/pulls?state=open&sort=updated&direction=desc&per_page=100" \
  --jq '.[].head.sha') || cannot_verify "could not list open pull requests for $REPO"
recent=$(gh api "repos/$REPO/commits?per_page=20" --jq '.[].sha') \
  || cannot_verify "could not list commits for $REPO"

seen=""
for sha in $prs $recent; do
    case " $seen " in *" $sha "*) continue ;; esac
    seen="$seen $sha"
    collect "$sha"
done

# Local HEAD is deliberately not a candidate. Open PR heads cover every pushed branch
# with a PR, recent commits cover main, and selection is by newest timestamp — so HEAD
# contributes nothing those two do not already carry. It also could not be handled
# safely: no single gh exit code distinguishes "this commit is not on the remote" from
# "the request failed", so tolerating a failure risked accepting an older matching
# context while propagating it would break ordinary unpushed branches.

published=$(printf '%s\n' "$published" | grep '^[0-9]' || true)

# Nothing anywhere carries an HCP status. Unverifiable, not broken.
[ -n "$published" ] || exit 0

# Lexicographic sort is chronological for the ISO-8601 UTC timestamps this API returns.
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
