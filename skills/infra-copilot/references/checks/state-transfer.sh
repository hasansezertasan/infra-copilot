#!/bin/sh
# Check public HUMAN transfer evidence, never pull or display secret-bearing
# state. HCP detection is conservative and textual: HCL comments are stripped
# before inspection and Terraform JSON is parsed structurally, so neither
# comments between tokens nor escape-encoded JSON keys can make a previously
# HCP-routed leaf look genuinely new.
set -eu
cannot_verify() { echo "CANNOT VERIFY state transfer: $1" >&2; exit 2; }
incomplete() { echo "INCOMPLETE state transfer: $1" >&2; exit 1; }
leaf=${1:-}
case "$leaf" in ''|*[!a-z0-9-]*) cannot_verify 'a declared leaf slug is required' ;; esac

# Flatten HCL to one comment-free line, so tokens that only become adjacent
# after removing HCL comments are still detected. Bias: stripping comment text
# can only create false evidence requirements, never hide real tokens. Strings
# are not tracked; this is not a general parser.
flatten_hcl() {
    awk '
        BEGIN { inside_block = 0; whole = "" }
        {
            line = $0
            stripped = ""
            while (1) {
                if (inside_block) {
                    closer = index(line, "*/")
                    if (closer == 0) { line = ""; break }
                    line = substr(line, closer + 2)
                    inside_block = 0
                    continue
                }
                hash = index(line, "#")
                slash = index(line, "//")
                block = index(line, "/*")
                if (hash == 0) hash = 999999999
                if (slash == 0) slash = 999999999
                if (block == 0) block = 999999999
                if (hash == 999999999 && slash == 999999999 && block == 999999999) {
                    stripped = stripped line
                    break
                }
                if (hash < slash && hash < block) { stripped = stripped substr(line, 1, hash - 1); break }
                if (slash < block) { stripped = stripped substr(line, 1, slash - 1); break }
                stripped = stripped substr(line, 1, block - 1)
                rest = substr(line, block + 2)
                closer = index(rest, "*/")
                if (closer == 0) { inside_block = 1; break }
                line = substr(rest, closer + 2)
            }
            if (stripped != "") whole = whole " " stripped
        }
        END { print whole }
    '
}

hcl_hcp() {
    printf '%s\n' "$1" |
        grep -Eq '(^|[[:space:]{}])backend[[:space:]]*"remote"|(^|[[:space:]{}])cloud[[:space:]]*\{'
}

# History asks only whether an old revision configured HCP (cloud block or the
# remote backend). The current-tree layout check instead rejects every backend
# or cloud declaration outside the reviewed backend.tf.
HISTORY_FILTER='any((.terraform // {}) | .. | objects;
  has("cloud") or ((.backend // {}) | type == "object" and has("remote")))'
LAYOUT_FILTER='any((.terraform // {}) | .. | objects; has("cloud") or has("backend"))'

json_check() {
    status=0
    verdict=$(printf '%s\n' "$1" | jq -er "$2" 2>/dev/null) || status=$?
    case "$status" in
        0) printf '%s\n' "$verdict" ;;
        1) [ "$verdict" = false ] || cannot_verify "$3"
           printf '%s\n' false ;;
        *) cannot_verify "$3" ;;
    esac
}

# Inspect one revision's top-level leaf files for committed HCP configuration;
# sets `found` to hcp/true/false.
inspect_revision() {
    revision=$1
    files=$(git --no-optional-locks ls-tree -r --name-only "$revision" -- "terraform/$leaf/") || {
        cannot_verify "cannot list $revision"
    }
    found=false
    while IFS= read -r file; do
        depth="${file#terraform/$leaf/}"
        [ "$depth" != "$file" ] || continue
        case "$depth" in
            (*/*) continue ;;
            (*.tf|*.tf.json) : ;;
            (*) continue ;;
        esac
        snapshot=$(git --no-optional-locks show "$revision:$file") || {
            cannot_verify "cannot read $file at $revision"
        }
        case "$depth" in
            (*.tf.json)
                found=$(json_check "$snapshot" "$HISTORY_FILTER" \
                    "cannot structurally inspect $file at $revision") || exit 2
                [ "$found" = true ] && found=hcp || found=false
                ;;
            (*.tf)
                if hcl_hcp "$(printf '%s\n' "$snapshot" | flatten_hcl)"; then
                    found=hcp
                else
                    found=false
                fi
                ;;
        esac
        [ "$found" = false ] || break
    done <<FILES
$files
FILES
}

history=''
revisions=$(git --no-optional-locks log --format=%H HEAD -- "terraform/$leaf/") || {
    cannot_verify 'cannot read backend history'
}
for revision in $revisions; do
    inspect_revision "$revision"
    [ "$found" = false ] || history=$revision
    [ "$history" = '' ] || break
done
if [ "$history" = '' ]; then
    shallow=$(git --no-optional-locks rev-parse --is-shallow-repository) || exit 2
    [ "$shallow" = false ] || cannot_verify 'fetch complete history before ruling out an HCP cutover'
    exit 0
fi

# The attestation hashes backend.tf alone, so it must hold the leaf's only
# backend declaration, with no competing backend/cloud syntax anywhere else.
backend_file="terraform/$leaf/backend.tf"
[ -f "$backend_file" ] || incomplete "declare the $leaf backend in $backend_file"
{
    printf '%s\n' "$backend_file"
    ls "terraform/$leaf/"*.tf "terraform/$leaf/"*.tf.json 2>/dev/null | sort -u || true
} | awk '!seen[$0]++' | while IFS= read -r source_file; do
    case "$source_file" in
        (*.tf|*.tf.json) : ;;
        (*) continue ;;
    esac
    if [ "$source_file" = "${source_file%.tf.json}" ]; then
        flattened=$(flatten_hcl < "$source_file")
        declarations=$(printf '%s\n' "$flattened" |
            grep -oE '(^|[[:space:]{}])backend[[:space:]]*"[^"]+"' | wc -l | tr -d '[:space:]')
        cloud_declarations=$(printf '%s\n' "$flattened" |
            grep -cE '(^|[[:space:]{}])cloud[[:space:]]*\{' || true)
    else
        verdict=$(json_check "$(cat "$source_file")" "$LAYOUT_FILTER" \
            "cannot structurally inspect $source_file") || exit 2
        if [ "$verdict" = true ]; then
            declarations=1
            cloud_declarations=1
        else
            declarations=0
            cloud_declarations=0
        fi
    fi
    if [ "$source_file" = "$backend_file" ]; then
        [ "$declarations" = 1 ] && [ "$cloud_declarations" = 0 ] ||
            incomplete 'put the single effective backend block in backend.tf'
    else
        [ "$declarations" = 0 ] && [ "$cloud_declarations" = 0 ] ||
            incomplete "backend or cloud declaration outside reviewed backend.tf: $source_file"
    fi
done
git ls-files --error-unmatch "$backend_file" .infra-copilot/config.md >/dev/null 2>&1 ||
    incomplete 'commit the destination backend and config'
git diff --quiet HEAD -- "$backend_file" .infra-copilot/config.md || exit 1
git diff --cached --quiet HEAD -- "$backend_file" .infra-copilot/config.md || exit 1
blob=$(git hash-object "$backend_file") || exit 2
transfers=${STATE_TRANSFERS-'{}'}
printf '%s' "$transfers" | jq -e --arg leaf "$leaf" --arg blob "$blob" '
  .[$leaf] as $transfer
  | ($transfer | type == "object")
    and $transfer.source_backend == "hcp"
    and $transfer.backend_blob == $blob
    and ($transfer.workspace_id | type == "string" and test("^ws-[A-Za-z0-9]+$"))
    and ($transfer.serial | type == "number" and . >= 0 and . == floor)
    and ($transfer.lineage | type == "string" and length > 0)
    and ($transfer.state_sha256 | type == "string" and test("^[a-f0-9]{64}$"))
    and $transfer.hcp_locked_before_pull == true
    and $transfer.destination_verified == true
    and ($transfer.verified_at | type == "string" and
      test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$") and
      (. as $raw | try strptime("%Y-%m-%dT%H:%M:%SZ") catch null
       | select(. != null) | mktime as $epoch
       | ($epoch | strftime("%Y-%m-%dT%H:%M:%SZ")) == $raw and $epoch <= now))
' >/dev/null || incomplete "record the frozen, verified HUMAN HCP transfer for $leaf"
