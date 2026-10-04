#!/bin/sh
# Enumerate configuration providers without backend initialization or state access.
# Terraform parses an isolated copy with only cloud/backend blocks removed. Missing
# modules or invalid configuration are unknown (2), never missing selections (1).
set -u
[ "$#" -eq 1 ] && [ -d "$1" ] || exit 2
leaf=$1
scratch=$(mktemp -d) || exit 2
trap 'rm -rf "$scratch"' EXIT
found=false
for file in "$leaf"/*.tf "$leaf"/*.tf.json; do
    [ -f "$file" ] || continue
    found=true
    name=${file##*/}
    case "$file" in
        *.tf.json)
            jq 'def strip_backend:
                  if type == "array" then map(strip_backend)
                  elif type == "object" then del(.cloud, .backend, .state_store)
                  else . end;
                if has("terraform") then .terraform |= strip_backend else . end' \
                "$file" >"$scratch/$name" || exit 2 ;;
        *)
            # Tokenize structure, masking comments, strings and heredocs. Keep all
            # provider/resource declarations, including implicit requirements and
            # overrides. A backend is a direct child of a top-level terraform block.
            awk '
              function emit(text) { if (!skip) out = out text }
              {
                sub(/\r$/, "", $0)
                if (heredoc) {
                  emit($0 "\n")
                  end = $0
                  if (indent) sub(/^[ \t]*/, "", end)
                  if (end == marker) heredoc = 0
                  next
                }
                line = $0 "\n"
                for (i = 1; i <= length(line); i++) {
                  c = substr(line, i, 1); pair = substr(line, i, 2)
                  if (comment) {
                    if (pair == "*/") { comment = 0; emit(" "); i++ }
                    else if (c == "\n") emit(c)
                    continue
                  }
                  if (quoted) {
                    emit(c)
                    if (escaped) escaped = 0
                    else if (c == "\\") escaped = 1
                    else if (c == "\"") quoted = 0
                    continue
                  }
                  if (pair == "/*") { comment = 1; emit(" "); i++; continue }
                  if (c == "#" || pair == "//") { emit("\n"); break }
                  if (c == "\"") { quoted = 1; emit(c); continue }
                  if (pair == "<<") {
                    rest = substr(line, i)
                    if (match(rest, /^<<-?[ \t]*[A-Za-z_][A-Za-z0-9_-]*/)) {
                      marker = substr(rest, 1, RLENGTH)
                      indent = (marker ~ /^<<-/)
                      sub(/^<<-?[ \t]*/, "", marker)
                      heredoc = 1; emit(rest); break
                    }
                  }
                  if (c ~ /[A-Za-z_]/) {
                    word = c; start = length(out) + 1
                    while (substr(line, i + 1, 1) ~ /[A-Za-z0-9_-]/) {
                      i++; word = word substr(line, i, 1)
                    }
                    emit(word); continue
                  }
                  if (c == "{") {
                    if (!skip && depth == 1 && blocks[1] == "terraform" &&
                        (word == "cloud" || word == "backend" || word == "state_store")) {
                      out = substr(out, 1, start - 1); skip = depth + 1
                    }
                    depth++; blocks[depth] = word; word = ""; emit(c)
                  } else if (c == "}") {
                    if (skip == depth) { skip = 0; depth-- }
                    else { emit(c); depth-- }
                    word = ""
                  } else {
                    emit(c)
                    if (c !~ /[[:space:]]/) word = ""
                  }
                }
              }
              END {
                if (comment || quoted || heredoc || depth != 0 || skip) exit 2
                printf "%s", out
              }
            ' "$file" >"$scratch/$name" || exit 2 ;;
    esac
done
[ "$found" = true ] || exit 2
# Reuse only the module inventory from an initialized leaf, resolving relative
# module directories against the original leaf. No backend metadata or state is
# copied. An uninstalled child module remains unknown rather than being skipped.
if [ -f "$leaf/.terraform/modules/modules.json" ]; then
    absolute_leaf=$(cd "$leaf" && pwd -P) || exit 2
    mkdir -p "$scratch/.terraform/modules" || exit 2
    jq --arg leaf "$absolute_leaf" --arg scratch "$scratch" '
      .Modules |= map(if .Key == "" then .Dir = $scratch
                      elif (.Dir | startswith("/")) then .
                      else .Dir = ($leaf + "/" + .Dir) end)' \
      "$leaf/.terraform/modules/modules.json" \
      >"$scratch/.terraform/modules/modules.json" || exit 2
fi
# Never reuse TF_DATA_DIR, workspace selection, injected CLI flags, or CLI config
# from the consuming checkout. This copy contains no backend metadata or state.
TF_DATA_DIR="$scratch/.terraform" TF_WORKSPACE=default TF_CLI_CONFIG_FILE=/dev/null \
    TF_CLI_ARGS= TF_CLI_ARGS_providers= CHECKPOINT_DISABLE=1 \
    terraform -chdir="$scratch" providers -no-color >"$scratch/providers" || exit 2
# A successful provider-free configuration needs no lock entries.
sed -n 's/.*provider\[\([^]]*\)\].*/\1/p' "$scratch/providers" >"$scratch/required" || exit 2
sort -u "$scratch/required" || exit 2
