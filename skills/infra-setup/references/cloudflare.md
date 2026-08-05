# Provider: Cloudflare (agent-first)

Deep dive for [Phase 2](../SKILL.md#phase-2--cloudflare) of the infra-setup skill. What the
agent does, what the human must do, and how to prove it. Canonical bootstrap detail:
[`setup.md#3`](../../../../docs/setup.md#3-cloudflare-api-token). Token scopes + rotation:
[`secrets.md`](../../../../docs/secrets.md#cloudflare-api-token-scopes).

## What this repo manages via Cloudflare

The `perish.dev` zone and all its DNS records (Email Routing + GitHub Pages), through the
`cloudflare/cloudflare` v5 provider. State + token live in the HCP `cloudflare` workspace.

## The actor split

| Action | Actor | Why |
|---|---|---|
| Mint the scoped API token | **HUMAN** | No API to bootstrap the *first* token; it's a dashboard-only action. |
| Paste token into HCP (sensitive var) | **HUMAN** | The agent must never see the plaintext. |
| Verify var presence + shape | **AGENT** | HCP API, no secret exposure. |
| Prove the token works (`plan`) | **AGENT** | Speculative plan runs in HCP. |
| Read account/zone IDs (for porting) | **AGENT** | Cloudflare API, once a token exists. |

## HUMAN — mint + paste (`cf-token`)

The agent emits a handoff block; the human does exactly this:

1. <https://dash.cloudflare.com/profile/api-tokens> → **Create Token** → **Custom token**.
2. Permissions for the `perish.dev` zone and its account:
   - Zone — DNS — **Edit**
   - Zone — Zone Settings — **Edit**
   - *(add a row per new resource type before Terraform manages it — Email Routing Rules,
     Rulesets, etc. Edit the token later, don't regenerate — see
     [`setup.md`](../../../../docs/setup.md#adding-scopes-to-the-cloudflare-token-later).)*
3. **Account Resources**: Include — your account. **Zone Resources**: Include —
   Specific zone — `perish.dev`.
4. Copy the token (shown once).
5. HCP → workspace **`cloudflare`** → Variables → add `cloudflare_api_token` as a
   **Terraform** variable, mark **Sensitive**, paste.

> The token needs **Edit** because the persistent workspace *manages* resources. For
> one-time *discovery* during migration, a separate **Read** token is used and thrown
> away — see [`migration.md`](./migration.md) and [`import.md`](../../../../docs/import.md#discovery-token).

## AGENT — verify

The value is redacted, so the agent verifies presence + `sensitive == true`, then proves
the token with a plan:

```sh
HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)
WS_ID=$(curl -sf "https://app.terraform.io/api/v2/organizations/perishdev/workspaces/cloudflare" \
  -H "Authorization: Bearer $HCP_TOKEN" | jq -r '.data.id')

curl -sf "https://app.terraform.io/api/v2/workspaces/$WS_ID/vars" \
  -H "Authorization: Bearer $HCP_TOKEN" \
  | jq -e '.data[] | select(.attributes.key=="cloudflare_api_token") | .attributes.sensitive==true' \
  && echo "✓ token present + sensitive"

cd terraform/cloudflare && terraform init && terraform plan   # green = token works
```

## AGENT — reading account + zone IDs (porting)

These are **not secrets** (they're `local`s in `terraform/cloudflare/main.tf`:
`account_id = d8a72309…`, `zone_id = 78ff9bdc…`), so reading them doesn't need the
persistent Edit token — and the agent should **not** touch that token (the
never-see-the-plaintext rule holds). Two clean ways to get the IDs when porting:

- **Human reads them off the dashboard** — account ID is in the URL / right-hand
  sidebar; zone ID is on the domain's Overview page. Paste them back to the agent.
- **Agent uses the short-lived *read-only* discovery token** (the same throwaway token
  minted for migration — see [`migration.md`](./migration.md)), never the Edit token:

  ```sh
  export CF_READ_TOKEN=...   # throwaway READ token, deleted right after — NOT the HCP Edit token

  # Account ID
  curl -sf "https://api.cloudflare.com/client/v4/accounts" \
    -H "Authorization: Bearer $CF_READ_TOKEN" | jq -r '.result[0].id'

  # Zone ID for the new domain
  curl -sf "https://api.cloudflare.com/client/v4/zones?name=<new-domain>" \
    -H "Authorization: Bearer $CF_READ_TOKEN" | jq -r '.result[0].id'
  ```

Write the results into `terraform/cloudflare/main.tf` `locals`. See the Porting table in
[`SKILL.md`](../SKILL.md#porting-to-another-organization).

## Rotation

Zero-downtime, agent-assisted: human mints the new token and pastes it; agent runs a no-op
`plan` to prove it; only then does the human revoke the old one. Steps in
[`secrets.md`](../../../../docs/secrets.md#cloudflare-api-token).
