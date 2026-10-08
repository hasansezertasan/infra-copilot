#!/bin/sh
# Verify the complete Phase 1 workspace invariant. This is shared by hcp-login
# (to decide whether a narrowed team token is the intended steady state) and
# workspaces-create (to decide whether reconciliation is complete).
set -eu

routing=$(sh "${INFRA_COPILOT_REFERENCES:?}/checks/leaf-routing.sh") || exit 2
leaves=$(printf '%s' "$routing" | jq -er '.hcp_bootstrap_leaves | .[]') || {
    [ "$(printf '%s' "$routing" | jq -r '.has_hcp_bootstrap')" = false ] && exit 0
    exit 2
}

for required in hcp_api ORG REPO TERRAFORM_VERSION HCP_TOKEN; do
    eval "value=\${$required:-}"
    [ -n "$value" ] || exit 1
done

[ "$hcp_api" = "https://app.terraform.io/api/v2" ] || exit 1

for leaf in $leaves; do
    dir="terraform/$leaf"
    case "$leaf" in cloudflare) ws=cloudflare ;; github) ws=github-org ;; *) exit 2 ;; esac
    curl -sf "$hcp_api/organizations/$ORG/workspaces/$ws" \
        -H "Authorization: Bearer $HCP_TOKEN" \
        | jq -e --arg dir "$dir" --arg repo "$REPO" \
            --arg tf_version "$TERRAFORM_VERSION" '
            .data.attributes as $a
            | ($a["working-directory"] == $dir)
              and ($a["execution-mode"] == "remote")
              and ($a["terraform-version"] == $tf_version)
              and ($a["auto-apply"] == false)
              and ($a["auto-destroy-at"] == null)
              and ($a["auto-destroy-activity-duration"] == null)
              and ($a["speculative-enabled"] == true)
              and ($a["file-triggers-enabled"] == true)
              and ((($a["trigger-patterns"]) // []) | index($dir + "/**") != null)
              and ((($a["trigger-patterns"]) // []) | index("terraform/modules/**") != null)
              and ((($a["trigger-patterns"]) // []) | index(".infra-copilot/config.md") != null)
              and ((($a["trigger-patterns"]) // []) | index("mise.toml") != null)
              and (($a["vcs-repo"].identifier // "") == $repo)
              and (($a["vcs-repo"].branch // "") == "main")' >/dev/null \
        || exit 1
done
