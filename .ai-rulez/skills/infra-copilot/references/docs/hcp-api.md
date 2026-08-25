
# HCP Terraform API toolkit

The HCP REST API is the same surface the UI uses. Everything in this repo's day-to-day operations can be scripted against it, often more precisely than clicking through the web app.

## Authentication

`terraform login` deposits a user API token at `~/.terraform.d/credentials.tfrc.json`. That token is what authenticates every snippet below.

```sh
HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)
H_AUTH="Authorization: Bearer $HCP_TOKEN"
H_TYPE="Content-Type: application/vnd.api+json"
```

For org-level operations (managing teams, oauth clients), the user must be an org admin in HCP. For most read operations a workspace member token is enough.

The snippets below assume `$ORG` is exported per the startup contract in [`../config.md`](../config.md).

## Identifiers you'll need often

| Name | Value | How to find |
|---|---|---|
| Organization | `<your-org>` (`$ORG`) | the URL `app.terraform.io/app/<your-org>/...` |
| `cloudflare` workspace | `ws-xxxxxxxxxxxx` | `GET /organizations/$ORG/workspaces/cloudflare` |
| `github-org` workspace | `ws-xxxxxxxxxxxx` | `GET /organizations/$ORG/workspaces/github-org` |
| `infra` project | (find via API) | `GET /organizations/$ORG/projects` |
| GitHub OAuth client | (find via API) | `GET /organizations/$ORG/oauth-clients` |

## Find a workspace

```sh
WS_ID=$(curl -s "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/cloudflare" \
  -H "$H_AUTH" | jq -r '.data.id')
echo "$WS_ID"
```

## List recent runs on a workspace

```sh
curl -s "https://app.terraform.io/api/v2/workspaces/$WS_ID/runs?page%5Bsize%5D=10" \
  -H "$H_AUTH" \
  | jq '[.data[] | {
      id,
      status: .attributes.status,
      plan_only: .attributes."plan-only",
      message: (.attributes.message[:80])
    }]'
```

Note: **speculative runs are filtered out of the default list.** To see them, add `&filter[status]=planned_and_finished,planning,planned`. That's how you find a PR's speculative plan run.

## Read a plan summary (creates / updates / destroys / imports)

```sh
RUN_ID=run-xxxxxxxxxxxxxxxx
PLAN_ID=$(curl -s "https://app.terraform.io/api/v2/runs/$RUN_ID" \
  -H "$H_AUTH" | jq -r '.data.relationships.plan.data.id')

curl -sL "https://app.terraform.io/api/v2/plans/$PLAN_ID/json-output-redacted" \
  -H "$H_AUTH" \
  | jq '{
      summary: {
        creates:  ([.resource_changes[]? | select(.change.actions[]? == "create"  and (.change.importing // null) == null)] | length),
        imports:  ([.resource_changes[]? | select(.change.importing != null)] | length),
        updates:  ([.resource_changes[]? | select(.change.actions[]? == "update")] | length),
        destroys: ([.resource_changes[]? | select(.change.actions[]? == "delete")] | length)
      },
      by_action: [.resource_changes[] | "\(.change.actions | join(",")) \(.address)"]
    }'
```

This is faster and more precise than reading the HCP UI's plan output. Use it before merging any PR.

## Confirm an apply

After merge, HCP plans the run and sits at "needs confirmation." Confirm:

```sh
curl -s -X POST "https://app.terraform.io/api/v2/runs/$RUN_ID/actions/apply" \
  -H "$H_AUTH" -H "$H_TYPE" \
  -d '{"comment":"plan reviewed via API"}'
```

The HTTP 202 is the confirmation. Status transitions to `applying` then `applied` (or `errored`).

## Discard / cancel a run

```sh
# Plan reviewed, not what we wanted — discard before confirming apply
curl -s -X POST "https://app.terraform.io/api/v2/runs/$RUN_ID/actions/discard" \
  -H "$H_AUTH" -H "$H_TYPE" -d '{"comment":"discarding — see revert PR"}'

# Apply currently running and we want to stop
curl -s -X POST "https://app.terraform.io/api/v2/runs/$RUN_ID/actions/cancel" \
  -H "$H_AUTH"
```

Cancel is the harder of the two — partial state is possible mid-apply.

## Wait for a run to reach a terminal state

```sh
poll_run() {
  local rid=$1
  while :; do
    local st
    st=$(curl -s "https://app.terraform.io/api/v2/runs/$rid" \
      -H "$H_AUTH" | jq -r '.data.attributes.status')
    echo "$st"
    case "$st" in
      applied|errored|canceled|discarded|force_canceled|planned_and_finished)
        return 0
        ;;
    esac
    sleep 15
  done
}
```

## List variables on a workspace

```sh
curl -s "https://app.terraform.io/api/v2/workspaces/$WS_ID/vars" \
  -H "$H_AUTH" \
  | jq '[.data[] | {
      id,
      key: .attributes.key,
      category: .attributes.category,
      sensitive: .attributes.sensitive
    }]'
```

Sensitive variable values are never returned by the API — only `"sensitive": true` and no `value` field. This is how it should be.

## Find the run for a specific commit

Correlate on the run's configuration version, never on the run message. A message is free
text: `Merge ...` subjects match every merge commit, and a truncated SHA can appear in a
run that tested something else. The commit actually tested lives on the configuration
version's ingress attributes, so include them and match `commit-sha` exactly.

```sh
COMMIT_SHA=$(git rev-parse HEAD)
curl -s "https://app.terraform.io/api/v2/workspaces/$WS_ID/runs?page%5Bsize%5D=20&include=configuration_version.ingress_attributes" \
  -H "$H_AUTH" \
  | jq --arg sha "$COMMIT_SHA" '
      [(.included // [])[]
        | select(.type == "ingress-attributes")
        | select(.attributes."commit-sha" == $sha)
        | .id] as $ingress
      | [(.included // [])[]
          | select(.type == "configuration-versions")
          | select((.relationships."ingress-attributes".data.id // "") as $id | $ingress | index($id))
          | .id] as $configs
      | [.data[]
          | select((.relationships."configuration-version".data.id // "") as $id | $configs | index($id))
          | {
              id,
              status: .attributes.status,
              speculative: .attributes."plan-only",
              green: (.attributes.status | . == "planned_and_finished" or . == "applied")
            }]'
```

Do not add a `filter[status]` to that request. An `errored` run on the current commit has
to stay visible; filtering it out hides the failure and leaves an older run looking
authoritative. Read the result as:

- one or more entries with `"green": true` — this exact commit planned or applied cleanly.
- entries present, none green — this commit was tested and is failing or still running
  (`planning`, `planned`, `errored`, `canceled`).
- empty — this commit has never been tested in that workspace. CLI-driven runs carry no
  ingress attributes and so never correlate; report `?` instead of falling back to an
  older run.

## Trigger a manual plan from the API

Useful for "the workspace's auto-trigger didn't fire" debugging.

```sh
curl -s -X POST "https://app.terraform.io/api/v2/runs" \
  -H "$H_AUTH" -H "$H_TYPE" \
  -d "{
    \"data\": {
      \"attributes\": { \"message\": \"manual diagnostic\" },
      \"type\": \"runs\",
      \"relationships\": {
        \"workspace\": { \"data\": { \"type\": \"workspaces\", \"id\": \"$WS_ID\" } }
      }
    }
  }"
```

## Things the API can do that the UI can't

- **Read the full structured plan JSON** (`plans/<id>/json-output-redacted`). The UI shows a rendered diff; the API gives you the underlying data to script against.
- **Atomic operations across multiple workspaces** in a script — the UI is one workspace at a time.
- **Audit / activity scripting** — list every run by every user, filter by date, dump to CSV.

## What still needs the UI

- The "Update VCS settings" button that re-registers the webhook with GitHub. The API equivalent exists but is fiddly; UI click is fastest.
- Inspecting workspace settings interactively when you don't know what you're looking for.

## Full API reference

<https://developer.hashicorp.com/terraform/cloud-docs/api-docs>
