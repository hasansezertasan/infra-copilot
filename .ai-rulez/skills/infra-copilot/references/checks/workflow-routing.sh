#!/bin/sh
# Verify the supported static, top-level Actions routing literals against config.
# Reject ambiguous overrides/expressions instead of claiming to parse arbitrary YAML.
set -eu
fail() { echo "CANNOT VERIFY workflow routing: $1" >&2; exit 2; }
broken() { echo "BROKEN workflow routing: $1" >&2; exit 1; }
normalized=$(mktemp) || fail 'cannot allocate workflow scratch file'
trap 'rm -f "$normalized"' EXIT
job_block() {
    awk -v name="$1" '
        /^jobs:/ {jobs=1; next}
        /^[^[:space:]#]/ {jobs=0}
        jobs && /^  [a-zA-Z0-9_-]+:/ {inside=($0 == "  " name ":")}
        jobs && inside {print}
    ' "$normalized"
}
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
    [ -e "$file" ] || broken "$file is missing; provision the workflows"
    [ -r "$file" ] || fail "$file is unreadable"
    source_file=$file
    awk '{sub(/\r$/, ""); print}' "$file" > "$normalized" || fail "$file cannot be read"
    scan=$normalized
    # Only block environments are supported. Flow maps, aliases, merge keys and
    # quoted keys must not conceal a more-specific routing override.
    awk '
        /^[[:space:]]*#/ {next}
        /^[[:space:]]*["\047].*["\047][[:space:]]*:/ {exit 1}
        /(^|[[:space:]])["\047]?env["\047]?[[:space:]]*:/ &&
            $0 !~ /^[[:space:]]*env:[[:space:]]*(#.*)?$/ {exit 1}
        /^[[:space:]]*<</ {exit 1}
        /(^|[[:space:]:,\{\[])[&*][a-zA-Z_]/ {exit 1}
    ' "$scan" || fail "$source_file uses unsupported environment syntax"
    changes=$(job_block changes)
    [ -n "$changes" ] || broken "$source_file lacks changes job"
    printf '%s\n' "$changes" | grep -Eq '^    (if|needs|continue-on-error):' &&
        broken "$source_file backend routing must run unconditionally"
    route=$(printf '%s\n' "$changes" | awk '
        /^      - / {if (found) print block; block=""; found=0}
        {block=block $0 "\n"}
        /^        id: route[[:space:]]*$/ {found=1; count++}
        END {if (found) printf "%s", block; if (count != 1) exit 1}
    ') || broken "$source_file needs one route step in changes"
    printf '%s\n' "$route" | grep -Eq '^        (if|continue-on-error):' &&
        broken "$source_file route step must run unconditionally"
    case "$source_file" in
      *terraform-plan.yml)
        filter=$(printf '%s\n' "$changes" | awk '
          /^      - / {inside=($0 ~ /uses: dorny\/paths-filter@/); if (inside) count++}
          inside {print}
          END {if (count != 1) exit 1}
        ') || broken "$source_file needs one concrete PR path filter"
        printf '%s\n' "$filter" | grep -Fxq '        id: filter' || broken "$source_file lacks filter output identity"
        if printf '%s\n' "$filter" | grep -q 'predicate-quantifier:'; then
          printf '%s\n' "$filter" | grep -Eq '^          predicate-quantifier: some[[:space:]]*$' ||
            fail "$source_file requires any matching path, not all paths"
        fi ;;
    esac
    initializers=''; decisions=''; emissions=''
    for pair in $pairs; do
        leaf=${pair%%:*}; key=${pair#*:}
        case "$leaf" in [0-9]*) accessor="['$leaf']" ;; *) accessor=.$leaf ;; esac
        expected=$(printf '%s' "$routing" | jq -er --arg leaf "$leaf" '.effective[$leaf]') || exit 2
        # HCP-only additional leaves need no runner jobs. If any runner declaration
        # remains, verify it even though the leaf's Actions implementation is skipped.
        if [ "$leaf" != cloudflare ] && [ "$leaf" != github ] && [ "$expected" = hcp ] &&
           ! grep -Eq "$key|^  (plan|apply)-$leaf:" "$scan"; then
            continue
        fi
        grep -Eq "(^|[^A-Za-z0-9_])$key[\"']?[[:space:]]*:" "$scan" ||
            broken "$source_file is missing $key"
        value=$(awk -v key="$key" '
            /^[[:space:]]*#/ {next}
            /^[^[:space:]#]/ { global_env = ($0 ~ /^env:[[:space:]]*(#.*)?$/) }
            $0 ~ "(^|[^A-Za-z0-9_])" key "[\"\047]?[[:space:]]*:" {
                count++
                if (!global_env || $0 !~ "^  " key ":") bad=1
                line=$0; sub("^  " key ":[[:space:]]*", "", line)
                sub(/[[:space:]]+#.*$/, "", line); sub(/[[:space:]]*$/, "", line)
                value=line
            }
            END { if (count != 1 || bad) exit 1; print value }
        ' "$scan") || fail "$source_file must declare $key exactly once in its top-level env"
        # Bare or simply quoted literals are supported, never expressions.
        case "$value" in "'$expected'"|\""$expected"\"|"$expected") ;; *)
            echo "BROKEN workflow routing: $source_file $key=$value; effective config requires $expected" >&2
            exit 1 ;;
        esac
        # Verify the supported execution wiring, not merely decorative literals.
        output=$(printf '%s\n' "$changes" | awk -v leaf="$leaf" '
            /^    outputs:/ {inside=1; next}
            /^    [^[:space:]]/ {inside=0}
            inside && $0 ~ "^      " leaf ":" {print}
        ')
        [ "$output" = "      $leaf: \${{ steps.route.outputs$accessor }}" ] || {
            echo "BROKEN workflow routing: $source_file $leaf output bypasses route" >&2; exit 1;
        }
        case "$source_file" in
            *terraform-plan.yml) prefix=plan; suffix=" && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)" ;;
            *) prefix=apply; suffix='' ;;
        esac
        guard=$(job_block "$prefix-$leaf" | awk '/^    if:/ {sub(/^    if: /, ""); print}')
        [ -n "$guard" ] || broken "$source_file is missing $prefix-$leaf guard"
        [ "$guard" = "needs.changes.outputs$accessor == 'true'$suffix" ] ||
            broken "$source_file $prefix-$leaf does not use the supported routed job guard"
        slug=$(printf '%s' "$leaf" | tr '-' '_')
        case "$leaf" in cloudflare|github) variable=$slug ;; *) variable=leaf_$slug ;; esac
        changed=${key%_BACKEND}_CHANGED
        if [ "$prefix" = apply ]; then
            change_input="          $changed: 'true'"
        else
            change_input="          $changed: \${{ github.event_name == 'workflow_dispatch' && 'true' || steps.filter.outputs$accessor }}"
        fi
        printf '%s\n' "$route" | grep -Fxq "$change_input" ||
            broken "$source_file route lacks $changed input"
        if [ "$prefix" = plan ] && [ "$expected" = object-storage ]; then
            paths=$(printf '%s\n' "$filter" | awk -v leaf="$leaf" '
                /^            [a-zA-Z0-9_-]+:/ {inside=($0 == "            " leaf ":"); if (inside) count++}
                inside {print}
                END {if (count != 1) exit 1}
            ') || broken "$source_file has no unique $leaf path filter"
            printf '%s\n' "$paths" | awk '
                /^[[:space:]]*#/ {next}
                /^              [^[:space:]]/ &&
                  $0 !~ /^              - \047[a-zA-Z0-9_.\/*?-]+\047[[:space:]]*(#.*)?$/ {exit 1}
            ' || fail "$source_file $leaf uses unsupported filter path syntax"
            for required_path in "terraform/$leaf/**" 'terraform/modules/**' mise.toml mise.lock \
                .infra-copilot/config.md '.github/workflows/terraform-*.yml' .github/scripts/terraform-destroy.cjs; do
                printf '%s\n' "$paths" | grep -Fxq "              - '$required_path'" ||
                    broken "$source_file $leaf filter omits $required_path"
            done
            aggregate=$(job_block plan)
            dependencies=$(printf '%s\n' "$aggregate" | sed -n 's/^    needs: //p')
            printf '%s\n' "$dependencies" | grep -Eq "(^|[^a-z0-9-])plan-$leaf([^a-z0-9-]|$)" ||
                broken "$source_file aggregate omits plan-$leaf"
            printf '%s\n' "$aggregate" | grep -Fxq "          $changed: \${{ needs.changes.outputs$accessor }}" ||
                broken "$source_file aggregate lacks $changed input"
            result=plan_${slug}_result
            printf '%s\n' "$aggregate" | grep -Fq ".[\"plan-$leaf\"].result" ||
                broken "$source_file aggregate lacks plan-$leaf result"
            predicate=$(printf 'if [ "$%s" = "true" ] && [ "$%s" != "success" ]; then' "$changed" "$result")
            printf '%s\n' "$aggregate" | awk -v predicate="$predicate" '
                $0 == "          " predicate {inside=1; count++}
                inside && /^            exit 1$/ {fails++}
                /^          fi$/ {inside=0}
                END {if (count != 1 || fails != 1) exit 1}
            ' || broken "$source_file aggregate does not require successful changed $leaf plan"
        fi
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
    route_run=$(printf '%s\n' "$route" | awk '
        /^      - / {route=0; run=0}
        /^        id: route[[:space:]]*$/ {route=1; count++}
        route && /^        run: \|[[:space:]]*$/ {run=1; next}
        run && /^          / {sub(/^          /, ""); print; next}
        run && /^[[:space:]]*$/ {print ""; next}
        run {run=0}
        END {if (count != 1) exit 1}
    ') || fail "$source_file needs exactly one supported route step"
    # Order is significant: reject unguarded/later assignments and early writes.
    # Bootstrap leaves first, then additional leaves in lexical order.
    expected_run=$(printf '%s%s%s' "$initializers" "$decisions" "$emissions")
    [ "$expected_run" = "$route_run" ] || fail "$source_file route script differs from the supported backend gates"
done
