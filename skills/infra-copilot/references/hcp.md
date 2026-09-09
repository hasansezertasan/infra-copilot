<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:9e2cb2b0ecc165c05b75b5eee4f56c91755de7ef1ce8d9e8e99a636ebccb9d38
Source-Hash: blake3:7d6a9fa43884df986635c88d96268c935efb54f524dafafef5676fe96a9fd244
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
GitHub↔HCP OAuth connection (browser).

| Workspace | Leaf | VCS working dir | Path filter | Auto-apply |
|---|---|---|---|---|
| `cloudflare` | `terraform/cloudflare/` | `terraform/cloudflare` | `terraform/cloudflare/**` | **no** |
| `github-org` | `terraform/github/` | `terraform/github` | `terraform/github/**` | **no** |

- **`HUMAN` — vcs-connect.** In HCP → org Settings → VCS Providers, connect GitHub via
  OAuth, scoped to this repo only. (Browser-only OAuth handshake.)
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

  # Reuse the OAuth token already proven to serve $REPO. Phase 6 can derive it
  # from either bootstrap workspace. During the initial Phase 1 bootstrap there
  # is no workspace yet, so an organization with exactly one GitHub OAuth token
  # is unambiguous; an organization with several must export OAUTH_TOKEN_ID
  # explicitly instead of silently taking whichever connection sorts first.
  resolve_oauth_token_id () {
    local workspace body token page count pages
    if [ -n "${OAUTH_TOKEN_ID:-}" ]; then
      printf '%s' "$OAUTH_TOKEN_ID" | grep -Eq '^ot-[A-Za-z0-9]+$' \
        || { echo "OAUTH_TOKEN_ID is not an HCP OAuth token id" >&2; return 1; }
      return 0
    fi
    for workspace in cloudflare github-org; do
      body=$(curl -sf "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/$workspace" \
        -H "Authorization: Bearer $HCP_TOKEN") || continue
      token=$(printf '%s' "$body" | jq -er --arg repo "$REPO" '
        .data.attributes["vcs-repo"]
        | select(.identifier == $repo)
        | .["oauth-token-id"]
        | select(type == "string" and length > 0)' 2>/dev/null) || continue
      OAUTH_TOKEN_ID=$token
      return 0
    done

    pages=$(mktemp) || return 1
    : >"$pages" || { rm -f "$pages"; return 1; }
    page=1
    while : ; do
      body=$(curl -sf \
        "https://app.terraform.io/api/v2/organizations/$ORG/oauth-clients?page%5Bsize%5D=100&page%5Bnumber%5D=$page" \
        -H "Authorization: Bearer $HCP_TOKEN") \
        || { rm -f "$pages"; return 1; }
      printf '%s\n' "$body" >>"$pages"
      count=$(printf '%s' "$body" | jq -er '.data | length' 2>/dev/null) \
        || { rm -f "$pages"; return 1; }
      [ "$count" -eq 100 ] || break
      page=$((page + 1))
    done
    token=$(jq -ser '
      [.[].data[]
        | select(.attributes["service-provider"] | test("^github"))
        | .relationships["oauth-tokens"].data[].id]
      | unique
      | select(length == 1)
      | .[0]' "$pages" 2>/dev/null) || token=
    rm -f "$pages"
    [ -n "$token" ] || {
      echo "Could not select one VCS connection for $REPO; export the intended OAUTH_TOKEN_ID" >&2
      return 1
    }
    OAUTH_TOKEN_ID=$token
  }

  # jq -n builds the payload (correct quoting for free); curl -w captures the HTTP status
  # so we can tell "created" (201) from "already exists" (422 name-taken) from a real error.
  create_ws () {  # $1 = workspace name   $2 = working directory
    local resp code body
    resp=$(jq -n --arg name "$1" --arg dir "$2" --arg repo "$REPO" --arg tok "$OAUTH_TOKEN_ID" \
      --arg tf_version "$TERRAFORM_VERSION" '
      {data:{type:"workspaces",attributes:{
        name:$name, "working-directory":$dir, "execution-mode":"remote",
        "terraform-version":$tf_version,
        "auto-apply":false, "auto-destroy-at":null, "auto-destroy-activity-duration":null,
        "speculative-enabled":true, "file-triggers-enabled":true,
        "trigger-patterns":[$dir+"/**", "terraform/modules/**", ".infra-copilot/config.md", "mise.toml"], "queue-all-runs":false, "global-remote-state":false,
        "vcs-repo":{identifier:$repo, "oauth-token-id":$tok, branch:"main"}}}}' \
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
      --arg tok "$OAUTH_TOKEN_ID" --arg tf_version "$TERRAFORM_VERSION" \
      '{data:{id:$id,type:"workspaces",attributes:{
        "working-directory":$dir, "execution-mode":"remote",
        "terraform-version":$tf_version,
        "auto-apply":false, "auto-destroy-at":null, "auto-destroy-activity-duration":null,
        "speculative-enabled":true, "file-triggers-enabled":true,
        "trigger-patterns":[$dir+"/**", "terraform/modules/**", ".infra-copilot/config.md", "mise.toml"], "queue-all-runs":false,
        "global-remote-state":false,
        "vcs-repo":{identifier:$repo, "oauth-token-id":$tok, branch:"main"}}}}')
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
  elif ! resolve_oauth_token_id; then
    echo "No unambiguous VCS oauth-token found — finish vcs-connect or select the connection explicitly; not creating workspaces." >&2
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
  > (it defaults off; the label-gated flow in [`docs/ci.md`](docs/ci.md) replaces it for forks).

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
