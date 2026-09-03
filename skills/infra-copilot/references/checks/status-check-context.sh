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

# Every open PR is blocked independently, so each is checked independently. Selecting a
# single "current" context globally cannot work, and two attempts proved it: first-match
# let an old commit win, and newest-timestamp lets a pre-rebuild run that finishes late
# win — in both cases the old context matches `required`, the check passes, and the PR
# carrying the new context waits forever.
hcp_contexts() {  # $1 = sha; prints its Terraform Cloud contexts, one per line
    gh api --paginate "repos/$REPO/commits/$1/status?per_page=100" \
      --jq '.statuses[] | select(.context | startswith("Terraform Cloud/")) | .context'
}

# Only PRs that target the protected branch, and only its history. Unfiltered, the pulls
# request admits PRs based on unrelated branches, and the commits request defaults to the
# repository's default branch, which need not be main.
prs=$(gh api --paginate "repos/$REPO/pulls?state=open&base=main&per_page=100" \
  --jq '.[].head.sha') || cannot_verify "could not list open pull requests for $REPO"
recent=$(gh api "repos/$REPO/commits?sha=main&per_page=20" --jq '.[].sha') \
  || cannot_verify "could not list commits on main for $REPO"

# $1 = sha, $2 = human label. Returns 1 if this candidate publishes HCP contexts but not
# every required one.
verify() {
    published=$(hcp_contexts "$1") \
      || cannot_verify "could not read commit status for $1"
    [ -n "$published" ] || return 0          # no HCP status here: nothing to compare
    tmp=$(mktemp) || cannot_verify "mktemp failed"
    printf '%s\n' "$published" > "$tmp"
    missing=$(printf '%s\n' "$required" | grep -vxF -f "$tmp")
    rm -f "$tmp"
    [ -z "$missing" ] && return 0
    echo "BLOCKED: $2 ($1) publishes [$(printf '%s' "$published" | tr '\n' ' ')] but branch protection requires: $missing" >&2
    return 1
}

evidence=0
broken=0
for sha in $prs; do
    published=""
    verify "$sha" "open PR head" || broken=1
    [ -n "$published" ] && evidence=1
done

# main's history is a fallback only: it proves nothing about a PR, but with no open PR
# publishing a status it is the only evidence available.
if [ "$evidence" = 0 ]; then
    for sha in $recent; do
        published=""
        verify "$sha" "commit on main" || broken=1
        if [ -n "$published" ]; then evidence=1; break; fi
    done
fi

[ "$broken" = 0 ] || exit 1

# No HCP status published anywhere. Unverifiable, not broken.
exit 0
