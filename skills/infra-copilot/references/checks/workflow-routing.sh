#!/bin/sh
# Verify the supported static, top-level Actions routing literals against config.
# Reject ambiguous overrides/expressions instead of claiming to parse arbitrary YAML.
set -eu
fail() { echo "CANNOT VERIFY workflow routing: $1" >&2; exit 2; }
routing=$(sh "${INFRA_COPILOT_REFERENCES:?}/checks/leaf-routing.sh") || exit 2
pairs='cloudflare:CLOUDFLARE_BACKEND github:GITHUB_BACKEND'
for provider in $(printf '%s' "$routing" | jq -r '.effective | keys[] | select(. != "cloudflare" and . != "github")'); do
    key=LEAF_$(printf '%s' "$provider" | tr '[:lower:]-' '[:upper:]_')_BACKEND
    pairs="$pairs $provider:$key"
done
if [ -n "${ROUTING_PROVIDER:-}" ]; then
    printf '%s' "$routing" | jq -e --arg leaf "$ROUTING_PROVIDER" '.effective | has($leaf)' >/dev/null \
        || fail 'ROUTING_PROVIDER is not a declared leaf'
fi
[ "$#" -gt 0 ] || set -- .github/workflows/terraform-plan.yml .github/workflows/terraform-apply.yml
for file do
    case "$file" in .github/workflows/terraform-plan.yml|.github/workflows/terraform-apply.yml) ;; *) fail 'unsupported workflow path' ;; esac
    [ -r "$file" ] || fail "$file is missing or unreadable"
    # Only block environments are supported. Flow maps, aliases, merge keys and
    # quoted keys must not conceal a more-specific routing override.
    awk '
        /^[[:space:]]*#/ {next}
        /(^|[[:space:]])["\047]?env["\047]?[[:space:]]*:/ &&
            $0 !~ /^[[:space:]]*env:[[:space:]]*(#.*)?$/ {exit 1}
        /^[[:space:]]*<</ {exit 1}
        /(^|[[:space:]:,\{\[])[&*][a-zA-Z_]/ {exit 1}
    ' "$file" || fail "$file uses unsupported environment syntax"
    initializers=''; decisions=''; emissions=''
    for pair in $pairs; do
        leaf=${pair%%:*}; key=${pair#*:}
        expected=$(printf '%s' "$routing" | jq -er --arg leaf "$leaf" '.effective[$leaf]') || exit 2
        # HCP-only additional leaves need no runner jobs. If any runner declaration
        # remains, verify it even though the leaf's Actions implementation is skipped.
        if [ "$leaf" != cloudflare ] && [ "$leaf" != github ] && [ "$expected" = hcp ] &&
           ! grep -Eq "$key|^  (plan|apply)-$leaf:" "$file"; then
            continue
        fi
        value=$(awk -v key="$key" '
            /^[[:space:]]*#/ {next}
            /^[^[:space:]#]/ { global_env = ($0 ~ /^env:[[:space:]]*(#.*)?$/) }
            $0 ~ key "[\"\047]?[[:space:]]*:" {
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
        # Verify the supported execution wiring, not merely decorative literals.
        grep -Fxq "      $leaf: \${{ steps.route.outputs.$leaf }}" "$file" || {
            echo "BROKEN workflow routing: $file $leaf output bypasses route" >&2; exit 1;
        }
        case "$file" in
            *terraform-plan.yml) prefix=plan; suffix=" && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)" ;;
            *) prefix=apply; suffix='' ;;
        esac
        guard=$(awk -v name="$prefix-$leaf" '
            /^  [a-zA-Z0-9_-]+:/ {inside=($0 == "  " name ":")}
            inside && /^    if:/ {sub(/^    if: /, ""); print}
        ' "$file")
        [ "$guard" = "needs.changes.outputs.$leaf == 'true'$suffix" ] ||
            fail "$file $prefix-$leaf does not use the supported routed job guard"
        slug=$(printf '%s' "$leaf" | tr '-' '_')
        case "$leaf" in cloudflare|github) variable=$slug ;; *) variable=leaf_$slug ;; esac
        changed=${key%_BACKEND}_CHANGED
        grep -Fxq "          $changed: \${{ steps.filter.outputs.$leaf }}" "$file" ||
            fail "$file route lacks $changed input"
        initialization="$variable=false"
        decision=$(printf 'if [ "$%s" = "object-storage" ] && [ "$%s" = "true" ]; then\n  %s=true\nfi' "$key" "$changed" "$variable")
        emission=$(printf 'echo "%s=$%s" >> "$GITHUB_OUTPUT"' "$leaf" "$variable")
        # The supported route consists solely of false initializers, guarded true
        # assignments and output writes. No later assignment can undo a backend gate.
        initializers="$initializers$initialization
"
        decisions="$decisions$decision
"
        emissions="$emissions$emission
"
    done
    route_run=$(awk '
        /^      - / {route=0; run=0}
        /^        id: route[[:space:]]*$/ {route=1; count++}
        route && /^        run: \|[[:space:]]*$/ {run=1; next}
        run && /^          / {sub(/^          /, ""); print; next}
        run {run=0}
        END {if (count != 1) exit 1}
    ' "$file") || fail "$file needs exactly one supported route step"
    # Order is significant: reject unguarded/later assignments and early writes.
    # Bootstrap leaves first, then additional leaves in lexical order.
    expected_run=$(printf '%s%s%s' "$initializers" "$decisions" "$emissions")
    [ "$expected_run" = "$route_run" ] || fail "$file route script differs from the supported backend gates"
done
