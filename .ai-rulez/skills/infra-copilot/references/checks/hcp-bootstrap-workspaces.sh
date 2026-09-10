#!/bin/sh
# Verify the complete Phase 1 workspace invariant. This is shared by hcp-login
# (to decide whether a narrowed team token is the intended steady state) and
# workspaces-create (to decide whether reconciliation is complete).
set -eu

for required in hcp_api ORG REPO TERRAFORM_VERSION HCP_TOKEN; do
    eval "value=\${$required:-}"
    [ -n "$value" ] || exit 1
done

[ "$hcp_api" = "https://app.terraform.io/api/v2" ] || exit 1

for pair in "cloudflare:terraform/cloudflare" "github-org:terraform/github"; do
    ws=${pair%%:*}; dir=${pair#*:}
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
