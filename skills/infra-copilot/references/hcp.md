<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:d2c26d231d4af10c0b1295d226bb04fedb15e14b64eeba1547f5c7dc56ce3974
Source-Hash: blake3:dd6bc476d5161553c461bfd223aa44250d8dfef3013e62b0d462dbd9445475a5
Schema-Version: v1
-->


# HCP bootstrap + workspaces (agent-first)

Deep dive for Phases 0–1 of the [`setup`](../../setup/SKILL.md) skill. Canonical detail:
[`docs/setup.md#1`](docs/setup.md#1-hcp-terraform--organization),
[`docs/setup.md#2`](docs/setup.md#2-hcp-terraform--workspaces),
[`docs/state.md`](docs/state.md).

## Phase 0 — bootstrap

The only unavoidable cold-start. Produces the HCP token that lets the agent script everything after.

- **`HUMAN` — hcp-login.** Sign up at <https://app.terraform.io/> if needed, then run
  `terraform login` locally (opens a browser and asks HCP for a user API token). `HUMAN`
  because it needs an interactive browser — but it's the *last* time a human touches the
  terminal for auth. Token lands in `~/.terraform.d/credentials.tfrc.json`; after the
  check passes, the agent re-exports `HCP_TOKEN` before continuing.
- **`HUMAN` — hcp-signup.** With the token now available for verification, create org
  **`<your-org>`** and project **`infra`**. (Org name must equal the `organization` field
  in every `terraform/*/versions.tf` — it does.)
- **`AGENT` — hcp-verify.** From here you own the HCP API:

  ```sh
  # $ORG sourced from config — see config.md
  HCP_TOKEN=${TF_TOKEN_app_terraform_io:-$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)}
  curl -sf "https://app.terraform.io/api/v2/organizations/$ORG" \
    -H "Authorization: Bearer $HCP_TOKEN" | jq -e '.data.id' \
    && echo "✓ HCP org reachable"
  ```

## Phase 1 — workspaces

Two workspaces, one per leaf. You create them via API; a human does the one-time
GitHub↔HCP connection through OAuth or the GitHub App (browser).

| Workspace | Leaf | VCS working dir | Path filter | Auto-apply |
|---|---|---|---|---|
| `cloudflare` | `terraform/cloudflare/` | `terraform/cloudflare` | `terraform/cloudflare/**` | **no** |
| `github-org` | `terraform/github/` | `terraform/github` | `terraform/github/**` | **no** |

- **`HUMAN` — vcs-connect.** In HCP → org Settings → VCS Providers, connect GitHub via
  OAuth or install the HCP Terraform GitHub App for this repo. For the App, also
  authorize it on the bootstrap user’s GitHub account. The agent discovers the HCP
  installation id under that user token; export `GITHUB_APP_INSTALLATION_ID=ghain-…`
  to select it explicitly. Never export both connection overrides. The
  [installations API](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/github-app-installations)
  is user-scoped; this evidence proves installation and authorization, while
  workspace creation verifies repository access. Keep the linked user token
  through bootstrap; team and organization tokens cannot create App links.
- **`AGENT` — workspaces-create.** Create both workspaces with the correct working
  directory, path-based run triggering, remote execution, and auto-apply **off**. The
  Terraform version is read from the committed `mise.toml` and applied to both workspaces.
  The safety toggles that matter — and *why each bites if wrong* — are in
  [`docs/setup.md#2`](docs/setup.md#2-hcp-terraform--workspaces): speculative
  plans **on**, path-scoped triggers, and — set in the UI — **fork** speculative plans
  **off**. Ready-to-run and **genuinely idempotent** — re-running reports an existing
  workspace as `✓ … already exists` (HCP answers a duplicate name with `422`); any other
  HTTP status surfaces as an error instead of a silent `jq` crash:

  ```sh
  # An already-exported HCP_TOKEN wins. Creating a workspace is organization-scoped,
  # and after the hcp-apply-scope handoff the machine's normal credential is a team
  # token with no organization permissions — so a human running this supplies an
  # admin credential deliberately, and resolving from the terraform credential
  # would overwrite it and fail the POST.
  export HCP_TOKEN=${HCP_TOKEN:-${TF_TOKEN_app_terraform_io:-$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)}}
  # $ORG, $REPO sourced from config — see config.md
  : "${ORG:?run Step 0 (read config) first}"
  : "${REPO:?run Step 0 (read config) first}"   # the repo HCP watches via VCS
  load_tf_version () {
    TERRAFORM_VERSION=$(mise config get --file ./mise.toml tools.terraform 2>/dev/null)
    printf '%s' "$TERRAFORM_VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.+-]+)?$' \
      || { echo "mise.toml must contain an exact tools.terraform version" >&2; return 1; }
  }

  # Select exactly one mechanism. Explicit overrides win; otherwise reuse the
  # connection proven on a bootstrap workspace, or discover a fresh connection.
  # GITHUB_APP_INSTALLATION_ID is HCP's ghain- id, not GitHub's numeric id.
  resolve_vcs_connection () {
    local workspace body candidates page count pages app rc
    VCS_CONNECTION=
    if [ -n "${OAUTH_TOKEN_ID:-}" ] && [ -n "${GITHUB_APP_INSTALLATION_ID:-}" ]; then
      echo "Export only OAUTH_TOKEN_ID or GITHUB_APP_INSTALLATION_ID, never both" >&2
      return 1
    fi
    if [ -n "${OAUTH_TOKEN_ID:-}" ]; then
      printf '%s' "$OAUTH_TOKEN_ID" | grep -Eq '^ot-[A-Za-z0-9]+$' || return 1
      VCS_CONNECTION=$(jq -n --arg id "$OAUTH_TOKEN_ID" '{"oauth-token-id":$id}')
      return 0
    fi
    if [ -n "${GITHUB_APP_INSTALLATION_ID:-}" ]; then
      app=$(sh "$INFRA_COPILOT_REFERENCES/checks/hcp-github-app.sh") || return 1
      VCS_CONNECTION=$(jq -n --arg id "$app" '{"github-app-installation-id":$id}')
      return 0
    fi
    candidates=$(mktemp) || return 1
    for workspace in cloudflare github-org; do
      body=$(curl -sf "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/$workspace" \
        -H "Authorization: Bearer $HCP_TOKEN") || continue
      printf '%s' "$body" | jq -c --arg repo "$REPO" '
        .data.attributes["vcs-repo"] | select(.identifier == $repo)
        | if (.["github-app-installation-id"] // "") != "" then
            {"github-app-installation-id":.["github-app-installation-id"]}
          elif (.["oauth-token-id"] // "") != "" then
            {"oauth-token-id":.["oauth-token-id"]}
          else empty end' >>"$candidates" || { rm -f "$candidates"; return 1; }
    done
    count=$(jq -s 'unique | length' "$candidates") || { rm -f "$candidates"; return 1; }
    if [ "$count" -gt 0 ]; then
      VCS_CONNECTION=$(jq -ser 'unique | select(length == 1) | .[0]' "$candidates")
      rc=$?
      rm -f "$candidates"
      [ "$rc" -eq 0 ] || { echo "Bootstrap workspaces use different connections; select one explicitly" >&2; return 1; }
      return 0
    fi
    pages=$(mktemp) || { rm -f "$candidates"; return 1; }
    page=1
    while :; do
      body=$(curl -sf \
        "https://app.terraform.io/api/v2/organizations/$ORG/oauth-clients?page%5Bsize%5D=100&page%5Bnumber%5D=$page" \
        -H "Authorization: Bearer $HCP_TOKEN") || { rm -f "$pages" "$candidates"; return 1; }
      printf '%s\n' "$body" >>"$pages"
      count=$(printf '%s' "$body" | jq -er '.data | arrays | length') \
        || { rm -f "$pages" "$candidates"; return 1; }
      [ "$count" -eq 100 ] || break
      page=$((page + 1))
    done
    jq -sc '[.[].data[]
      | select(.attributes["service-provider"] | test("^github"))
      | .relationships["oauth-tokens"].data[].id
      | {"oauth-token-id":.}] | unique[]' "$pages" >>"$candidates" \
      || { rm -f "$pages" "$candidates"; return 1; }
    app=$(sh "$INFRA_COPILOT_REFERENCES/checks/hcp-github-app.sh")
    rc=$?
    case "$rc" in
      0) jq -nc --arg id "$app" '{"github-app-installation-id":$id}' >>"$candidates" ;;
      1|4) ;; # no matching installation or no usable App authorization;
              # a sole organization-scoped OAuth candidate can still be used
      3) rm -f "$pages" "$candidates"; echo "Several App installations match; export GITHUB_APP_INSTALLATION_ID" >&2; return 1 ;;
      *) rm -f "$pages" "$candidates"; echo "Cannot read GitHub App installations; select a connection explicitly" >&2; return 1 ;;
    esac
    VCS_CONNECTION=$(jq -ser 'unique | select(length == 1) | .[0]' "$candidates")
    rc=$?
    rm -f "$pages" "$candidates"
    [ "$rc" -eq 0 ] || {
      echo "Could not select one VCS connection for $REPO; export the intended OAUTH_TOKEN_ID or GITHUB_APP_INSTALLATION_ID" >&2
      return 1
    }
  }

  # jq -n builds the payload (correct quoting for free); curl -w captures the HTTP status
  # so we can tell "created" (201) from "already exists" (422 name-taken) from a real error.
  create_ws () {  # $1 = workspace name   $2 = working directory
    local resp code body
    printf '%s' "${VCS_CONNECTION:-}" | jq -e '
      type == "object" and length == 1
      and ((.["oauth-token-id"] // "" | test("^ot-[A-Za-z0-9]+$"))
        or (.["github-app-installation-id"] // "" | test("^ghain-[A-Za-z0-9]+$")))' >/dev/null \
      || { echo "Resolve a VCS connection before creating a workspace" >&2; return 1; }
    resp=$(jq -n --arg name "$1" --arg dir "$2" --arg repo "$REPO" --argjson connection "$VCS_CONNECTION" \
      --arg tf_version "$TERRAFORM_VERSION" '
      {data:{type:"workspaces",attributes:{
        name:$name, "working-directory":$dir, "execution-mode":"remote",
        "terraform-version":$tf_version,
        "auto-apply":false, "auto-destroy-at":null, "auto-destroy-activity-duration":null,
        "speculative-enabled":true, "file-triggers-enabled":true,
        "trigger-patterns":[$dir+"/**", "terraform/modules/**", ".infra-copilot/config.md", "mise.toml"], "queue-all-runs":false, "global-remote-state":false,
        "vcs-repo":({identifier:$repo, branch:"main"} + $connection)}}}' \
      | curl -s -w '\n%{http_code}' -X POST "https://app.terraform.io/api/v2/organizations/$ORG/workspaces" \
          -H "Authorization: Bearer $HCP_TOKEN" \
          -H "Content-Type: application/vnd.api+json" -d @-)
    code=${resp##*$'\n'}; body=${resp%$'\n'*}     # split trailing "\n<status>" (var 'code' — zsh reserves 'status')
    case "$code" in
      201) echo "✓ $1 created" ;;
      422) echo "$body" | grep -qi 'already been taken' \
             && echo "✓ $1 already exists" \
             || { echo "✗ $1: HTTP 422 — $(echo "$body" | jq -r '.errors[0].detail // .errors[0].title')" >&2; return 1; } ;;
      *)   echo "✗ $1: HTTP $code — $(echo "$body" | jq -r '.errors[0].detail // .errors[0].title // .')" >&2; return 1 ;;
    esac
  }

  # PATCH only the repository identifier and branch, leaving the connection fields
  # untouched even when a different creation override is exported.
  # POST cannot update an existing workspace. Reconcile every setting asserted by the
  # verification below after either response so a 422 resume repairs partial drift.
  set_workspace_config () { # $1 = workspace name   $2 = working directory
    local ws_id payload workspace_body existing_repo existing_directory
    workspace_body=$(curl -sf "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/$1" \
      -H "Authorization: Bearer $HCP_TOKEN") || return 1
    ws_id=$(printf '%s' "$workspace_body" | jq -r '.data.id // empty') || return 1
    [ -n "$ws_id" ] || { echo "✗ $1: workspace id not found" >&2; return 1; }
    existing_repo=$(printf '%s' "$workspace_body" \
      | jq -r '.data.attributes["vcs-repo"].identifier // empty') || return 1
    [ "$existing_repo" = "$REPO" ] || {
      echo "✗ $1: refusing to reconfigure workspace owned by ${existing_repo:-no VCS repository}" >&2
      return 1
    }
    existing_directory=$(printf '%s' "$workspace_body" \
      | jq -r '.data.attributes["working-directory"] // empty') || return 1
    if [ "$existing_directory" != "$2" ] \
      && [ "${CONFIRM_WORKSPACE_ID:-}" != "$ws_id" ]; then
      echo "✗ $1: workspace $ws_id currently targets '${existing_directory:-repository root}', not '$2'; inspect it and export CONFIRM_WORKSPACE_ID=$ws_id to authorize repointing" >&2
      return 1
    fi
    payload=$(jq -n --arg id "$ws_id" --arg dir "$2" --arg repo "$REPO" \
      --arg tf_version "$TERRAFORM_VERSION" \
      '{data:{id:$id,type:"workspaces",attributes:{
        "working-directory":$dir, "execution-mode":"remote",
        "terraform-version":$tf_version,
        "auto-apply":false, "auto-destroy-at":null, "auto-destroy-activity-duration":null,
        "speculative-enabled":true, "file-triggers-enabled":true,
        "trigger-patterns":[$dir+"/**", "terraform/modules/**", ".infra-copilot/config.md", "mise.toml"], "queue-all-runs":false,
        "global-remote-state":false,
        "vcs-repo":{identifier:$repo, branch:"main"}}}}')
    curl -sf -X PATCH "https://app.terraform.io/api/v2/workspaces/$ws_id" \
      -H "Authorization: Bearer $HCP_TOKEN" \
      -H "Content-Type: application/vnd.api+json" -d "$payload" >/dev/null \
      && echo "✓ $1 safety, VCS, Terraform $TERRAFORM_VERSION, and trigger settings"
  }

  # Gate with if/else, NOT `return`/`exit`: this block is run as a script by the agent,
  # where a top-level `return` errors AND falls through (creating a broken workspace),
  # and `exit` would kill an interactive shell if pasted. if/else is correct in every context.
  if ! load_tf_version; then
    echo "Not creating or updating workspaces without a committed Terraform pin." >&2
  elif ! resolve_vcs_connection; then
    echo "No unambiguous VCS connection found — finish vcs-connect or select the connection explicitly; not creating workspaces." >&2
  else
    create_ws cloudflare terraform/cloudflare && set_workspace_config cloudflare terraform/cloudflare
    create_ws github-org  terraform/github && set_workspace_config github-org terraform/github
  fi
  ```

  > `trigger-patterns` (glob) requires `file-triggers-enabled: true` — that pair is the
  > path-scoping toggle. Both workspaces also watch the shared `.infra-copilot/config.md`
  > and shared `terraform/modules/**`, so public-identifier and module changes are
  > validated by both plans. They also watch `mise.toml`, so a Terraform pin change
  > cannot reuse an older plan. `speculative-enabled: true`
  > is the master switch for plans on PRs.
  > The **fork** speculative-plan toggle is *separate* and has no clean create-time
  > attribute — confirm it's **off** in the workspace's UI → Settings → Version Control
  > (it defaults off; the label-gated flow in [`docs/hcp-ci.md`](docs/hcp-ci.md#what-runs-on-a-pr) replaces it for forks).

  Verify:

  ```sh
  for pair in "cloudflare:terraform/cloudflare" "github-org:terraform/github"; do
    ws=${pair%%:*}; dir=${pair#*:}
    curl -sf "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/$ws" \
      -H "Authorization: Bearer $HCP_TOKEN" \
      | jq -e --arg dir "$dir" --arg repo "$REPO" --arg tf_version "$TERRAFORM_VERSION" '
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
      && echo "✓ $ws configured as declared"
  done
  ```

> The end state of Phases 0–1 (HCP-as-clickops today) is tracked for future
> Terraform-ification as a tracked improvement in this repo's issue tracker (see the
> repo's open issues). Until then these steps are API calls, not `.tf` files.

## Import-resources

Generate imports with a short-lived discovery token, then use the workspace's speculative
plan with persistent credentials supplied by workspace variables. Review and commit HCL
before accepting check evidence. Require imports without creates, destroys or forgotten
resources. Obtain read-only run evidence with [service status](hcp-status.md); the plan's
success alone does not prove that its imports have applied. Wait for a HUMAN-confirmed
apply before [pruning](docs/hcp-prune.md).

## Get-plan

For add, import or prune, select the leaf from the request and validated config: bootstrap
`cloudflare` and `github` use their existing cloud blocks; additional providers use the
entry's committed workspace binding. Never substitute another workspace or supply provider
secrets locally. The plan-only credential from config authenticates the CLI; workspace
variables supply provider authentication remotely.

Commit reviewed leaf/shared/config/tool changes before accepting evidence. From the
repository root, with `LEAF` set to the validated leaf name, run:

```sh
(
  : "${LEAF:?Select the target leaf from config first}"
  dirty=$(git --no-optional-locks status --porcelain -- "terraform/$LEAF" \
    terraform/modules .infra-copilot/config.md mise.toml mise.lock) || exit 2
  [ -z "$dirty" ] || { echo 'Commit relevant inputs before obtaining plan evidence' >&2; exit 1; }
  cd "terraform/$LEAF" || exit 1
  terraform init -input=false || exit 1
  terraform plan -input=false -no-color
)
```

This is an action operation: initialization writes `.terraform/` and can refresh the lock
file. It is never a status check. If initialization changes a tracked lock, review and
commit it, then repeat the plan so its inputs match the commit. Inspect the speculative
plan's output/run URL: expected creates for add, imports without creates/destroys for
import, and `No changes.` for prune. Never apply from this CLI workflow.

For read-only status, use [HCP run evidence](hcp-status.md) and the
[API lookup](docs/hcp-api.md) for the newest commit affecting the leaf, shared modules,
config and mise pins. Judge the newest run for that revision; an older success cannot
hide a newer failure. A dirty checkout, absent run or unreadable response is unknown.
