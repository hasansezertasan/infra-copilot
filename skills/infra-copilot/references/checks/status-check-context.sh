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

# gh api is an *authenticated* request even for public repos. Without this the first call
# exits 4 and the failure reads as a stale context rather than a missing login.
gh auth status >/dev/null 2>&1 \
  || cannot_verify "gh is not authenticated; run 'gh auth login' or export GH_TOKEN, then re-run"

protected=$(gh api "repos/$REPO/branches/main" --jq '.protected') \
  || cannot_verify "could not read repos/$REPO/branches/main"

required=""
if [ "$protected" = true ]; then
    required=$(gh api "repos/$REPO/branches/main/protection" \
      --jq '.required_status_checks.contexts[]? | select(startswith("Terraform Cloud/"))') \
      || cannot_verify "could not read branch protection for $REPO"
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

# A local HEAD is only tolerated when the API never listed it — an unpushed branch
# legitimately has no statuses. If it *was* listed it has already been read above, and a
# failure there was fatal, so a swallowed failure can no longer hide a stale main match.
head_sha=$(git rev-parse HEAD 2>/dev/null) || head_sha=""
if [ -n "$head_sha" ]; then
    case " $seen " in
        *" $head_sha "*) : ;;
        *) collect "$head_sha" tolerate ;;
    esac
fi

published=$(printf '%s\n' "$published" | grep '^[0-9]' || true)

if [ "$protected" != true ]; then
    # Absent protection is "not applied yet" only on a genuinely greenfield repo. If HCP
    # has ever published a status here, the repo is established and its protection was
    # removed or disabled — merges are no longer gated.
    [ -z "$published" ] && exit 0
    fail "UNDERPROTECTED: main has no branch protection, but HCP publishes statuses here, so protection was removed or disabled. Merges are not gated by a plan — re-apply terraform/github/branch_protection.tf."
fi

if [ -z "$required" ]; then
    fail "UNDERPROTECTED: branch protection requires no 'Terraform Cloud/' context, so HCP plans do not gate merges. PRs are mergeable without a plan — this is not a stale-context incident."
fi

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
