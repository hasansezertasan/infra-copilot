<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:99aa84a30339be78bbcb9d4c7a15aa82ff8d0976d9d45958bd15d88065bade84
Source-Hash: blake3:05d7f09cd76066549971585bf00212d19d4a9f144003f0fc95f8fa947396d1d6
Schema-Version: v1
-->


# Importing existing Cloudflare resources

Use Cloudflare's own [`cf-terraforming`](https://github.com/cloudflare/cf-terraforming) CLI to bring resources that already exist in the `<apex-domain>` zone (and the parent Cloudflare account) under Terraform management without recreating them.

Why not a custom script: cf-terraforming is maintained by Cloudflare alongside the Terraform provider, so import ID formats and HCL schemas track provider changes automatically. A hand-rolled script would drift.

## Discovery token

Before you run cf-terraforming, generate a separate, short-lived Cloudflare token with **Read** scopes on every resource type you're discovering. Don't reuse the HCP token (which has Edit scopes — broader than discovery needs).

1. <https://dash.cloudflare.com/profile/api-tokens> → **Create Token** → **Custom token**.
2. Permissions: pick **Read** on each resource type you're about to discover. Examples:
   - Zone — DNS — Read
   - Zone — Email Routing Rules — Read
   - Account — Email Routing Addresses — Read
3. **Account Resources**: Include — your account. **Zone Resources**: Include — Specific zone — `<apex-domain>`.
4. **TTL**: set to a day or a few hours. This is throwaway.
5. **Continue to summary** → **Create token** → copy the value (shown once).
6. Park it on your laptop until the run is done:
   ```sh
   read -s "?Paste Cloudflare discovery token: " CF_TOK
   echo
   echo "$CF_TOK" > /tmp/cf_token
   chmod 600 /tmp/cf_token
   unset CF_TOK
   ```
7. After cf-terraforming finishes: `rm /tmp/cf_token`, and revoke the token in the dashboard.

## Install

```sh
brew tap cloudflare/cloudflare
brew install cloudflare/cloudflare/cf-terraforming
# or:
go install github.com/cloudflare/cf-terraforming/cmd/cf-terraforming@latest
```

## What it supports

Coverage is **broad but not total** for the v5 provider. As of cf-terraforming v0.27 (May 2026):

| Resource | Supported by `generate` |
|---|---|
| `cloudflare_dns_record` | yes |
| `cloudflare_r2_bucket` | yes |
| `cloudflare_pages_project` | yes |
| `cloudflare_workers_kv_namespace` | yes |
| `cloudflare_workers_custom_domain` | yes |
| `cloudflare_workers_cron_trigger` | yes (needs `--resource-id`) |
| `cloudflare_workers_script` | **no** — bundle content can't be round-tripped; define in the app repo |
| `cloudflare_workers_route` | **no** — define manually alongside the script |
| Zone settings (`cloudflare_zone_setting`) | yes (needs `--resource-id` listing each setting) |

For the script/route gap: Worker code typically lives in the app repo it serves, not in this infra repo. Importing the resource here would tie its state to an empty `content` field. Define the route + script in the app's own Terraform once that app exists.

## Generate HCL for the zone

```sh
export CLOUDFLARE_API_TOKEN=...        # token with read scopes for each resource type
export CLOUDFLARE_ZONE_ID=$CF_ZONE_ID
export CLOUDFLARE_ACCOUNT_ID=$CF_ACCOUNT_ID

cd terraform/cloudflare

terraform init -backend=false          # cf-terraforming requires an initialised dir

# Zone-scoped resources (DNS records) — --account and --zone are mutually exclusive.
cf-terraforming generate \
  --terraform-binary-path "$(which terraform)" \
  --resource-type "cloudflare_dns_record" \
  --zone "$CLOUDFLARE_ZONE_ID" \
  > generated.tf

# Account-scoped resources.
cf-terraforming generate \
  --terraform-binary-path "$(which terraform)" \
  --resource-type "cloudflare_r2_bucket,cloudflare_pages_project,cloudflare_workers_kv_namespace" \
  --account "$CLOUDFLARE_ACCOUNT_ID" \
  >> generated.tf
```

Without `--terraform-binary-path`, cf-terraforming downloads its own terraform binary into the current directory. The flag tells it to reuse the one already on PATH.

`generated.tf` is the file the existing comment in `main.tf` references. Review it: rename resource labels to something readable (cf-terraforming uses `terraform_managed_resource` placeholders), drop anything you don't actually want managed, and commit.

## Emit `import` blocks

```sh
cf-terraforming import \
  --modern-import-block \
  --terraform-binary-path "$(which terraform)" \
  --resource-type "cloudflare_dns_record" \
  --zone "$CLOUDFLARE_ZONE_ID" \
  >> generated.tf

cf-terraforming import \
  --modern-import-block \
  --terraform-binary-path "$(which terraform)" \
  --resource-type "cloudflare_r2_bucket,cloudflare_pages_project,cloudflare_workers_kv_namespace" \
  --account "$CLOUDFLARE_ACCOUNT_ID" \
  >> generated.tf
```

`--modern-import-block` emits Terraform 1.5+ `import { to = ... id = "..." }` blocks rather than the legacy CLI commands. Append to the same file so resources and their imports stay co-located.

## Verify

```sh
terraform fmt generated.tf
terraform validate
terraform plan      # expect: every existing resource shown as "will import", nothing as "will create"
```

`terraform plan` from the CLI is allowed against a VCS-connected HCP workspace (it runs as a speculative plan in HCP); `terraform apply` from the CLI is intentionally blocked. The plan output streams back to your terminal with a link to the HCP run.

If `plan` shows any `create` for a resource that already exists, the resource name or import ID in `generated.tf` is wrong — fix before opening a PR. The real apply happens when the PR merges and a maintainer confirms in HCP (or scripts the confirm via `POST /api/v2/runs/<id>/actions/apply`).

## When to re-run

Re-run `cf-terraforming generate` whenever new resources appear in Cloudflare that you want Terraform to manage. The cleanest workflow is to write new resources directly in Terraform from the start; cf-terraforming is for one-time onboarding of legacy state, not steady-state operations.

> Note: cf-terraforming is **not** intended for use in CI. It runs locally during onboarding, output is reviewed by a human, then committed.

## Worked example

- **`cloudflare_dns_record`** — pre-existing DNS records (e.g. email-routing records already set up before Terraform adoption) are good import candidates via this flow. Records with no prior existence (like GitHub Pages apex records or a `www` CNAME you're adding fresh) should instead be written directly into your `terraform/cloudflare/` config — no import needed.
- **`cloudflare_pages_project`**, **`cloudflare_r2_bucket`** — `cf-terraforming generate` discovers everything in the account, including resources unrelated to this repo's scope (other Pages projects, empty R2 buckets). Explicitly exclude anything outside the zone/domain this repo is meant to manage — don't import just because it was discovered.
