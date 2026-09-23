#!/bin/sh
# Report the latest GitHub Actions plan and apply runs, the object-storage counterpart of
# the per-workspace run status HCP mode reads from the HCP API. Two lines, one per
# workflow: the plan run on the current branch (a PR's head branch, or a
# workflow_dispatch), and the apply run on main.
#
# Informational, not a manifest step. It judges no revision: the phase-4 `*-gha` checks
# own "does this commit plan", with their dirty-tree and ancestry rules. This answers the
# question those checks do not — what did CI last say — and a green step can sit next to
# a red apply on main, which is exactly the finding it exists to surface.
#
# Read-only: `gh run list` / `gh run view` reads and `git --no-optional-locks`. Safe for
# infra-copilot:status.
#
# Requires $REPO (owner/name) exported per references/config.md.
#
# Each line stands on its own: a read that fails marks that line `?` and the other line
# is still read and printed, so one unreadable workflow never discards a real result.
#
# Exit codes:
#   0  every latest run passed, is still in flight, or does not exist yet
#   1  a latest run FAILED — failure, timed_out, or startup_failure. Wins over 2: a
#      failure that was read is a finding even if the other line could not be.
#   2  COULD NOT VERIFY — missing REPO, no readable git worktree, or a line's read
#      failed (gh not authenticated, an API error). The `?` line names the cause; any other line is still a real
#      result. A 2 is never evidence of a failed run.
set -u

cannot_verify() { echo "CANNOT VERIFY: $1" >&2; exit 2; }

[ -n "${REPO:-}" ] || cannot_verify "REPO is not set; export it per references/config.md"

# A missing backend means hcp (references/config.md), exactly as the steps.yaml guards
# read it. Testing only for a non-empty non-object-storage value treated an unset
# BACKEND as object-storage and queried Actions on an HCP repo.
if [ "${BACKEND:-hcp}" != "object-storage" ]; then
    echo "not applicable: backend is ${BACKEND:-hcp (default)}; HCP runs are read from the HCP API"
    exit 0
fi

# The workflow-file probe below is relative, so anchor it at the repository root rather
# than wherever the caller happens to be; from a subdirectory both workflows would
# otherwise read as not installed. Either failure is CANNOT VERIFY, never a fall-through:
# probing the caller's directory instead reports verified absence for an unreadable repo.
top=$(git --no-optional-locks rev-parse --show-toplevel 2>/dev/null) && [ -n "$top" ] \
  || cannot_verify "not inside a readable git worktree; run from the repository"
cd "$top" || cannot_verify "could not enter the repository root $top"

err=$(mktemp) || cannot_verify "mktemp failed"
trap 'rm -f "$err"' EXIT

# $1 = a run or job's status, $2 = its conclusion. Prints the symbol and word.
verdict() {
    if [ "$1" != completed ]; then
        echo "⏳ in progress ($1)"
        return
    fi
    case $2 in
        success) echo "✓ passed" ;;
        failure|timed_out|startup_failure) echo "✗ failed ($2)" ;;
        skipped) echo "– skipped" ;;
        # cancelled, action_required, neutral, stale: the run ended without saying
        # whether the configuration plans. That is not a failure.
        *) echo "? $2" ;;
    esac
}

failed=0
unverified=0

# $1 = the line's prefix, $2 = cause. Marks the line unreadable and moves on.
unreadable() {
    echo "$1  ? could not verify: $2"
    unverified=1
}

# $1 = label, $2 = workflow file, $3 = branch
report() {
    prefix="$1  $2 @ ${3:-?}"
    if [ ! -f ".github/workflows/$2" ]; then
        echo "$1  $2  – not installed (.github/workflows/$2 is missing)"
        return
    fi
    if [ -z "$3" ]; then
        echo "$1  $2  ? detached HEAD: no branch to read runs for"
        return
    fi
    # --all: without it `--workflow` does not resolve a disabled workflow, so a workflow
    # disabled after a failed apply would hide that run — and fall into the "not
    # registered" branch below as "no runs yet".
    run=$(gh run list --repo "$REPO" --workflow "$2" --branch "$3" --all --limit 1 \
      --json databaseId,status,conclusion,headSha,event,url \
      --jq '.[0] // empty | "\(.databaseId)|\(.status)|\(.conclusion // "")|\(.headSha)|\(.event)|\(.url)"' \
      2>"$err")
    # gh exits 4 when authentication is required; see status-check-context.sh.
    case $? in
        0) : ;;
        4) unreadable "$prefix" "gh is not authenticated for this host; run 'gh auth login' or export GH_TOKEN"; return ;;
        *)
            # gh resolves --workflow through the API before listing runs, and GitHub
            # does not know a workflow file that has only been committed to a branch
            # and never run. That is the setup moment this report matters most, and it
            # means no runs yet, not an unreadable API.
            if grep -q 'could not find any workflows named' "$err"; then
                echo "$prefix  – no runs yet (GitHub has not registered $2 yet)"
            else
                unreadable "$prefix" "could not list $2 runs on $3 for $REPO"
            fi
            return ;;
    esac
    if [ -z "$run" ]; then
        echo "$prefix  – no runs yet"
        return
    fi
    # `|`, not a tab: tab is IFS whitespace, so an empty conclusion (a run still in
    # flight) would collapse into its neighbour and shift every later field.
    IFS='|' read -r id status conclusion sha event url <<EOF
$run
EOF
    outcome=$(verdict "$status" "$conclusion")
    case "$status/$conclusion" in
        completed/failure|completed/timed_out|completed/startup_failure) failed=1 ;;
    esac

    # The latest run on the branch need not be for the checkout: commits not pushed
    # yet have no run, and an older green would read as current. Say so.
    revision=$(printf '%s' "$sha" | cut -c1-7)
    if [ "$1" = plan ]; then
        head=$(git --no-optional-locks rev-parse HEAD 2>/dev/null)
        [ -n "$head" ] && [ "$head" != "$sha" ] \
            && revision="$revision, not HEAD $(printf '%s' "$head" | cut -c1-7)"
    fi

    # The run's own conclusion hides which leaf moved: a GitHub-only change skips
    # apply-cloudflare and the run still reads green. Name each leaf job, plus any
    # other job that failed or was cancelled — a `validate` failure fails the run, and
    # listing only leaf jobs would show every named job green beside a red run.
    jobs=$(gh run view "$id" --repo "$REPO" --json jobs \
      --jq '.jobs[] | select((.name | test("^(plan|apply)-")) or (.status == "completed" and (.conclusion == "failure" or .conclusion == "timed_out" or .conclusion == "startup_failure" or .conclusion == "cancelled"))) | "\(.name)|\(.status)|\(.conclusion // "")"' \
      2>"$err")
    if [ $? -ne 0 ]; then
        echo "$prefix  $outcome  run $id ($event, $revision)  ? jobs unreadable  $url"
        unverified=1
        return
    fi
    detail=""
    while IFS='|' read -r name job_status job_conclusion; do
        [ -n "$name" ] || continue
        detail="$detail  $name $(verdict "$job_status" "$job_conclusion")"
    done <<EOF
$jobs
EOF
    echo "$prefix  $outcome  run $id ($event, $revision)$detail  $url"
}

branch=$(git --no-optional-locks branch --show-current 2>/dev/null)
report plan terraform-plan.yml "$branch"
report apply terraform-apply.yml main

[ "$failed" = 0 ] || exit 1
[ "$unverified" = 0 ] || exit 2
exit 0
