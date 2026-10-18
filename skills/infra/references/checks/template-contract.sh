#!/bin/sh
# Check the Template contract: the copier-infra release the Infra repo was rendered from
# must be at or above the minimum tag. Judged from `_commit` in .copier-answers.yml.
#   exit 0  a release tag at or above the minimum
#   exit 1  an older release tag; propose the Template's update
#   exit 2  cannot be judged (no or uncommitted answers file, bare commit, between-tags
#           value, another Template); hand off
# `--source-only` stops after the source check. Otherwise an optional first argument
# overrides the minimum; tests use it, nothing ambient can.
set -eu
source_only=false
if [ "${1:-}" = "--source-only" ]; then source_only=true; set --; fi
minimum=${1:-v0.1.0}
cannot_verify() { echo "CANNOT VERIFY Template contract: $1; hand off to the human, never assume it is compatible" >&2; exit 2; }

# Read one top-level scalar: drop a trailing comment, trim only the boundary whitespace and
# CR, and unquote one matching pair. Embedded characters are kept, so a value with a stray
# space or quote never normalises into an accepted one.
scalar() {
    sed -n "s/^$1:[[:space:]]*//p" .copier-answers.yml | head -n 1 | tr -d '\r' |
        sed -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\\(.*\\)'\$/\\1/"
}

[ -f .copier-answers.yml ] || cannot_verify 'no .copier-answers.yml, so no Template version is recorded'
# Judge only a committed record: an interrupted `copier update` leaves a modified answers
# file whose `_commit` is not yet reviewed, and every skill runs this check directly.
git ls-files --error-unmatch .copier-answers.yml >/dev/null 2>&1 &&
    git diff --quiet HEAD -- .copier-answers.yml 2>/dev/null &&
    git diff --cached --quiet HEAD -- .copier-answers.yml 2>/dev/null ||
    cannot_verify '.copier-answers.yml is not tracked and clean against HEAD and the index; commit or review it first'
# The version is only meaningful for copier-infra; another Template's tag proves nothing.
# Compare the parsed scalar against the canonical spellings of its GitHub source, never a
# pattern searched inside the raw line.
source=$(scalar _src_path)
case $source in
    gh:hasansezertasan/copier-infra|gh:hasansezertasan/copier-infra.git|\
    https://github.com/hasansezertasan/copier-infra|https://github.com/hasansezertasan/copier-infra.git|\
    git+https://github.com/hasansezertasan/copier-infra|git+https://github.com/hasansezertasan/copier-infra.git|\
    git@github.com:hasansezertasan/copier-infra|git@github.com:hasansezertasan/copier-infra.git) ;;
    *) cannot_verify "_src_path '$source' is not a copier-infra source" ;;
esac
[ "$source_only" = false ] || exit 0
recorded=$(scalar _commit)
[ -n "$recorded" ] || cannot_verify '.copier-answers.yml has no _commit'

# Only a bare vX.Y.Z release tag compares; a hash or v0.1.0-3-gabc1234 is indeterminate.
is_tag() { printf '%s\n' "$1" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; }
is_tag "$recorded" || cannot_verify "recorded _commit '$recorded' is not a vX.Y.Z release tag"
is_tag "$minimum" || cannot_verify "minimum '$minimum' is not a vX.Y.Z release tag"

# Compare numerically per component, never as text (0.10.0 is above 0.2.0).
older=$(awk -v a="${recorded#v}" -v b="${minimum#v}" 'BEGIN {
    split(a, x, "."); split(b, y, ".")
    for (i = 1; i <= 3; i++) {
        if (x[i] + 0 < y[i] + 0) { print 1; exit }
        if (x[i] + 0 > y[i] + 0) { print 0; exit }
    }
    print 0
}')
if [ "$older" = 1 ]; then
    echo "Template $recorded is older than the minimum $minimum; propose 'copier update' (from the repo root, tree clean) and review the diff" >&2
    exit 1
fi
