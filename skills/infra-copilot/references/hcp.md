<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:ad8003371a0133d9c5cd2cfe19e6fb219a7f7862f3b1d6571c5618f478ffaa7c
Source-Hash: blake3:37b19e0dd2de1cb9ff0b92da59e570fa812ccc8cc31ba8799488d20ad0e65715
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
  HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)
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
  safety toggles that matter — and *why each bites if wrong* — are in
  [`docs/setup.md#2`](docs/setup.md#2-hcp-terraform--workspaces): speculative
  plans **on**, path-scoped triggers, and — set in the UI — **fork** speculative plans
  **off**. Ready-to-run and **genuinely idempotent** — re-running reports an existing
  workspace as `✓ … already exists` (HCP answers a duplicate name with `422`); any other
  HTTP status surfaces as an error instead of a silent `jq` crash:

  ```sh
  export HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)
  # $ORG, $REPO sourced from config — see config.md
  : "${ORG:?run Step 0 (read config) first}"
  : "${REPO:?run Step 0 (read config) first}"   # the repo HCP watches via VCS

  # oauth-token-id from the VCS connection created in the vcs-connect step
  OAUTH_TOKEN_ID=$(curl -sf "https://app.terraform.io/api/v2/organizations/$ORG/oauth-clients" \
    -H "Authorization: Bearer $HCP_TOKEN" \
    | jq -r '.data[0].relationships["oauth-tokens"].data[0].id // empty')

  # jq -n builds the payload (correct quoting for free); curl -w captures the HTTP status
  # so we can tell "created" (201) from "already exists" (422 name-taken) from a real error.
  create_ws () {  # $1 = workspace name   $2 = working directory
    local resp code body
    resp=$(jq -n --arg name "$1" --arg dir "$2" --arg repo "$REPO" --arg tok "$OAUTH_TOKEN_ID" '
      {data:{type:"workspaces",attributes:{
        name:$name, "working-directory":$dir, "execution-mode":"remote",
        "auto-apply":false, "speculative-enabled":true, "file-triggers-enabled":true,
        "trigger-patterns":[$dir+"/**"], "queue-all-runs":false, "global-remote-state":false,
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

  # Gate with if/else, NOT `return`/`exit`: this block is run as a script by the agent,
  # where a top-level `return` errors AND falls through (creating a broken workspace),
  # and `exit` would kill an interactive shell if pasted. if/else is correct in every context.
  if [ -z "$OAUTH_TOKEN_ID" ]; then
    echo "No VCS oauth-token found — finish the vcs-connect step first; not creating workspaces." >&2
  else
    create_ws cloudflare terraform/cloudflare
    create_ws github-org  terraform/github
  fi
  ```

  > `trigger-patterns` (glob) requires `file-triggers-enabled: true` — that pair is the
  > path-scoping toggle. `speculative-enabled: true` is the master switch for plans on PRs.
  > The **fork** speculative-plan toggle is *separate* and has no clean create-time
  > attribute — confirm it's **off** in the workspace's UI → Settings → Version Control
  > (it defaults off; the label-gated flow in [`docs/ci.md`](docs/ci.md) replaces it for forks).

  Verify:
  ```sh
  for ws in cloudflare github-org; do
    curl -sf "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/$ws" \
      -H "Authorization: Bearer $HCP_TOKEN" \
      | jq -e '.data.attributes["auto-apply"] == false' >/dev/null \
      && echo "✓ $ws exists, auto-apply off"
  done
  ```

> The end state of Phases 0–1 (HCP-as-clickops today) is tracked for future
> Terraform-ification as a tracked improvement in this repo's issue tracker (see the
> repo's open issues). Until then these steps are API calls, not `.tf` files.
