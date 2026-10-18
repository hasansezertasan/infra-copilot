#!/bin/sh
# Resolve validated agent exports; never infer routing from state. Public JSON only.
# Exit 2 is invalid/unreadable routing, before any service calls.
set -eu
fail() { echo "CANNOT VERIFY routing: $1" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || fail 'jq is required'
case ${BACKEND:-} in hcp|object-storage) ;; *) fail 'BACKEND must be explicit' ;; esac
[ -n "${ADDITIONAL_PROVIDER_NAMES:-}" ] || fail 'ADDITIONAL_PROVIDER_NAMES is required (use [])'
overrides=${LEAF_BACKENDS-'{}'}
result=$(jq -cen --arg default "$BACKEND" --argjson names "$ADDITIONAL_PROVIDER_NAMES" \
    --argjson overrides "$overrides" '
    def backend: . == "hcp" or . == "object-storage";
    if ($names | type) != "array" then error("names must be an array") else . end
    | if all($names[]; type == "string" and test("^[a-z0-9][a-z0-9-]*$")
             and . != "cloudflare" and . != "github" and . != "modules")
         and (($names | unique | length) == ($names | length))
      then . else error("invalid or duplicate declared leaf") end
    | (["cloudflare", "github"] + $names) as $declared
    | if ($overrides | type) != "object" then error("leaf_backends must be a map") else . end
    | if all($overrides | to_entries[];
          .key as $key | ($declared | index($key)) != null and (.value | backend))
      then . else error("unknown leaf or invalid backend override") end
    | reduce $declared[] as $leaf ({}; .[$leaf] = ($overrides[$leaf] // $default))
    | . as $effective
    | {effective: $effective,
       hcp_leaves: [$declared[] | select($effective[.] == "hcp")],
       object_storage_leaves: [$declared[] | select($effective[.] == "object-storage")],
       hcp_bootstrap_leaves: ["cloudflare", "github" | select($effective[.] == "hcp")],
       object_storage_bootstrap_leaves: ["cloudflare", "github" | select($effective[.] == "object-storage")]}
    | . + {has_hcp: (.hcp_leaves | length > 0),
           has_object_storage: (.object_storage_leaves | length > 0),
           has_hcp_bootstrap: (.hcp_bootstrap_leaves | length > 0),
           has_object_storage_bootstrap: (.object_storage_bootstrap_leaves | length > 0)}
    ') || fail 'invalid declared leaves or leaf_backends'
for directory in terraform/*/; do
    [ -d "$directory" ] || continue
    leaf=${directory%/}; leaf=${leaf##*/}
    [ "$leaf" != modules ] || continue
    printf '%s' "$result" | jq -e --arg leaf "$leaf" '.effective | has($leaf)' >/dev/null \
        || fail "undeclared Terraform leaf $leaf; record adoption before preflight"
done
printf '%s\n' "$result"
