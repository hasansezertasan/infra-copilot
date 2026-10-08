#!/bin/sh
# Check public HUMAN transfer evidence, never pull or display secret-bearing state.
set -eu
cannot_verify() { echo "CANNOT VERIFY state transfer: $1" >&2; exit 2; }
incomplete() { echo "INCOMPLETE state transfer: $1" >&2; exit 1; }
leaf=${1:-}
case "$leaf" in ''|*[!a-z0-9-]*) cannot_verify 'a declared leaf slug is required' ;; esac
history=$(git --no-optional-locks log --format=%H \
  -G '(^|[[:space:]])cloud[[:space:]]*\{|backend[[:space:]]*"remote"' \
  HEAD -- "terraform/$leaf/*.tf") || cannot_verify 'cannot read backend history'
# Terraform JSON can encode cloud/remote keys (including escaped spellings).
# Inspect historical JSON structurally instead of assuming HCL-shaped text.
if [ -z "$history" ]; then
  revisions=$(git --no-optional-locks log --format=%H HEAD -- "terraform/$leaf/*.tf.json") || exit 2
  for revision in $revisions; do
    files=$(git --no-optional-locks ls-tree -r --name-only "$revision" -- "terraform/$leaf/") || exit 2
    found=$(printf '%s\n' "$files" | while IFS= read -r file; do
      case "${file#terraform/$leaf/}" in
        (*/*) continue ;;
        (*.tf.json) : ;;
        (*) continue ;;
      esac
      snapshot=$(git --no-optional-locks show "$revision:$file") || exit 2
      status=0
      verdict=$(printf '%s' "$snapshot" | jq -er '
        any((.terraform // {}) | .. | objects;
          has("cloud") or ((.backend // {}) |
            if type == "object" then has("remote") else false end))') || status=$?
      if [ "$status" = 0 ] && [ "$verdict" = true ]; then
        printf '%s\n' hcp; break
      fi
      [ "$status" = 1 ] && [ "$verdict" = false ] || exit 2
    done) || cannot_verify 'cannot inspect historical Terraform JSON'
    if [ "$found" = hcp ]; then history=$revision; break; fi
  done
fi
if [ -z "$history" ]; then
  shallow=$(git --no-optional-locks rev-parse --is-shallow-repository) || exit 2
  [ "$shallow" = false ] || cannot_verify 'fetch complete history before ruling out an HCP cutover'
  exit 0
fi
backend_file="terraform/$leaf/backend.tf"
# Supported cutovers keep the complete, single backend declaration in the file
# the HUMAN reviewed. Do not borrow bucket/prefix text from unrelated leaf files.
for source_file in "terraform/$leaf/"*.tf; do
  [ -f "$source_file" ] || continue
  source_text=$(awk '!/^[[:space:]]*(#|\/\/)/ {text=text " " $0} END {print text}' "$source_file")
  declarations=$(printf '%s\n' "$source_text" |
    grep -oE '(^|[[:space:]{}])backend[[:space:]]*"[^"]+"[[:space:]]*\{' | wc -l | tr -d '[:space:]')
  if [ "$source_file" = "$backend_file" ]; then
    [ "$declarations" = 1 ] || incomplete 'put the single effective backend block in backend.tf'
  else
    [ "$declarations" = 0 ] || incomplete "backend declaration outside reviewed backend.tf: $source_file"
    ! printf '%s\n' "$source_text" | grep -Eq '(^|[[:space:]{}])cloud[[:space:]]*\{' ||
      incomplete "cloud declaration outside reviewed backend.tf: $source_file"
  fi
done
for source_file in "terraform/$leaf/"*.tf.json; do
  [ -f "$source_file" ] || continue
  json_backend=$(jq -er '[(.terraform // {}) | .. | objects | has("backend") or has("cloud")] | any' "$source_file") || {
    # jq -e returns 1 for the legitimate false result, not a read/parse failure.
    [ "$json_backend" = false ] || cannot_verify "cannot inspect $source_file"
  }
  [ "$json_backend" = false ] || incomplete "backend declaration outside reviewed backend.tf: $source_file"
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
