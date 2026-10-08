#!/bin/sh
# Verify the supported static, top-level Actions routing literals against config.
# Reject ambiguous overrides/expressions instead of claiming to parse arbitrary YAML.
set -eu
fail() { echo "CANNOT VERIFY workflow routing: $1" >&2; exit 2; }
routing=$(sh "${INFRA_COPILOT_REFERENCES:?}/checks/leaf-routing.sh") || exit 2
pairs='cloudflare:CLOUDFLARE_BACKEND github:GITHUB_BACKEND'
if [ -n "${ROUTING_PROVIDER:-}" ]; then
    printf '%s' "$routing" | jq -e --arg leaf "$ROUTING_PROVIDER" '.effective | has($leaf)' >/dev/null \
        || fail 'ROUTING_PROVIDER is not a declared leaf'
    key=$(printf '%s' "$ROUTING_PROVIDER" | tr '[:lower:]-' '[:upper:]_')_BACKEND
    pairs="$pairs $ROUTING_PROVIDER:$key"
fi
[ "$#" -gt 0 ] || set -- .github/workflows/terraform-plan.yml .github/workflows/terraform-apply.yml
for file do
    case "$file" in .github/workflows/terraform-plan.yml|.github/workflows/terraform-apply.yml) ;; *) fail 'unsupported workflow path' ;; esac
    [ -r "$file" ] || fail "$file is missing or unreadable"
    for pair in $pairs; do
        leaf=${pair%%:*}; key=${pair#*:}
        expected=$(printf '%s' "$routing" | jq -er --arg leaf "$leaf" '.effective[$leaf]') || exit 2
        value=$(awk -v key="$key" '
            /^[^[:space:]#]/ { global_env = ($0 == "env:") }
            $0 ~ "^[[:space:]]*" key "[[:space:]]*:" {
                count++
                if (!global_env || $0 !~ "^  " key ":") bad=1
                line=$0; sub("^  " key ":[[:space:]]*", "", line)
                sub(/[[:space:]]+#.*$/, "", line); sub(/[[:space:]]*$/, "", line)
                value=line
            }
            END { if (count != 1 || bad) exit 1; print value }
        ' "$file") || fail "$file must declare $key exactly once in its top-level env"
        # Bare or simply quoted literals are supported, never expressions.
        case "$value" in "'$expected'"|\""$expected"\"|"$expected") ;; *)
            echo "BROKEN workflow routing: $file $key=$value; effective config requires $expected" >&2
            exit 1 ;;
        esac
    done
done
