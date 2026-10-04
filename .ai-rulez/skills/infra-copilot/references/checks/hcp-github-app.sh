#!/bin/sh
# Print one HCP installation id for REPO. 1 = absent; 2 = unreadable; 3 = ambiguous.
set -u
[ "${hcp_api:-https://app.terraform.io/api/v2}" = "https://app.terraform.io/api/v2" ] || exit 2
[ -n "${REPO:-}" ] && [ -n "${HCP_TOKEN:-}" ] || exit 2
case "${GITHUB_APP_INSTALLATION_ID:-}" in
    "") ;;
    ghain-*) printf '%s' "$GITHUB_APP_INSTALLATION_ID" | grep -Eq '^ghain-[A-Za-z0-9]+$' || exit 1 ;;
    *) echo "Use the HCP ghain- id, not GitHub's numeric installation id" >&2; exit 1 ;;
esac
body=$(mktemp) || exit 2
pages=$(mktemp) || { rm -f "$body"; exit 2; }
trap 'rm -f "$body" "$pages"' EXIT
page=1
while :; do
    curl -sf "https://app.terraform.io/api/v2/github-app/installations?page%5Bsize%5D=100&page%5Bnumber%5D=$page" \
        -H "Authorization: Bearer $HCP_TOKEN" >"$body" || exit 2
    count=$(jq -er '.data | arrays | length' "$body") || exit 2
    cat "$body" >>"$pages"
    printf '\n' >>"$pages"
    total=$(jq -r '.meta.pagination["total-pages"] // empty' "$body") || exit 2
    if [ -n "$total" ]; then
        printf '%s' "$total" | grep -Eq '^[1-9][0-9]*$' || exit 2
        [ "$page" -lt "$total" ] || break
    else
        [ "$count" -eq 100 ] || break
        echo "Cannot verify all App installations: full page without pagination metadata" >&2
        exit 2
    fi
    page=$((page + 1))
done
jq -sc --arg owner "${REPO%%/*}" --arg id "${GITHUB_APP_INSTALLATION_ID:-}" '
    [.[].data[]
      | select((.attributes.name | ascii_downcase) == ($owner | ascii_downcase))
      | select($id == "" or .id == $id)
      | .id | select(type == "string" and test("^ghain-[A-Za-z0-9]+$"))]
    | unique' "$pages" >"$body" || exit 2
count=$(jq 'length' "$body") || exit 2
[ "$count" -le 1 ] || exit 3
jq -er 'select(length == 1) | .[0]' "$body"
rc=$?
case "$rc" in 0) exit 0 ;; 1|4) exit 1 ;; *) exit 2 ;; esac
