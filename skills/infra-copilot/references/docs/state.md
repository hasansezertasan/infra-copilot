<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:8160399c0ee6fb7450eefb89f657847035631b39b0e5d5629273ee4e857140e9
Source-Hash: blake3:69b7da0679988f1d38f2dc3644479b9497b771bc6b5b03839228bb36b130fa87
Schema-Version: v1
-->


# Terraform state

State lives in **HCP Terraform** (formerly Terraform Cloud). It is never stored locally, never committed, and never exposed to public CI logs.

## Why HCP Terraform

- Managed remote backend with built-in locking — no S3 + DynamoDB to operate.
- Runs execute on HCP infrastructure, so the Cloudflare token and GitHub App key never leave HCP and never appear in GitHub Actions logs.
- Free tier covers small teams. Easy to migrate off later (state is a JSON blob).

## Organization

- **HCP org**: `<your-org>` (`hcp_org` in [`../config.md`](../config.md)).
- **Project**: `infra` (one project per repo).

## Workspaces

One workspace per concern. We split per environment only when a change to one environment must not affect another (different account, different apex domain, or a real isolation requirement). Today neither concern needs that.

| Workspace | Manages | VCS path filter | Auto-apply? |
|---|---|---|---|
| `cloudflare` | the `<apex-domain>` zone + all DNS records (Email Routing + GitHub Pages) | `terraform/cloudflare/**`, `.infra-copilot/config.md` | no — manual apply |
| `github-org` | the repos in `managed_repos` (e.g. `<owner/repo>`) — repo settings, `main` branch protection, `safe-to-plan` label | `terraform/github/**`, `.infra-copilot/config.md` | no — manual apply |

Both are VCS-linked to this repo's `main` branch. Speculative plans run on PRs (see [`ci.md`](./ci.md)); applies stop at "needs confirmation" until a human (or authenticated API call) approves them.

There is no `cloudflare-staging` workspace because we manage a single apex domain in a single Cloudflare account. Staging surfaces (`staging.<domain>`, `app-staging` Worker, etc.) would live as additional resources inside the `cloudflare` workspace. Revisit if we ever add a second apex domain or move staging into a separate account.

## Variables

Each workspace declares:

- **Terraform variables (non-sensitive)** — set in HCP UI: Cloudflare account ID is a *local* in `terraform/cloudflare/main.tf` rather than a variable, because it's not a credential; zone ID likewise. The GitHub workspace's `github_owner` is set as a non-sensitive var.
- **Sensitive variables** — Cloudflare API token, GitHub App credentials (App ID, installation ID, PEM). Marked `sensitive`; HCP redacts from logs and never echoes back.
- **Environment variables** — none today. Used only for provider-level config that has to live in env (`TF_LOG`, etc.).

Variable values live in HCP, not in the repo. The repo declares `variable "x" {}` blocks; HCP supplies the values at run time.

## Access

- **Read state**: workspace members in HCP.
- **Trigger speculative plan**: anyone who can push a branch (own-repo) or open a PR with the `safe-to-plan` label (fork).
- **Confirm apply**: workspace admins, or an authenticated `POST /api/v2/runs/<id>/actions/apply` with a token that holds apply rights on the workspace. A personal token from `terraform login` does; a team token granted only the workspace `Plan` permission does not, which is the point of the `hcp-apply-scope` step.
- **Manage workspace settings**: org admins.

## API access

A `terraform login` writes an HCP **user** API token to `~/.terraform.d/credentials.tfrc.json`. The same token authenticates every HCP REST endpoint, so anything you can do in the UI you can script — including applying. That is the default, not the target state: it is what makes the agent's credential the only real boundary, and why `hcp-apply-scope` asks for a plan-only team token for everything after phase 1. That step's `run` in [`steps.yaml`](../steps.yaml) carries the procedure and its two limits.

Read an endpoint with the token Step 0 already resolved. Re-deriving it from the
credentials file would discard an environment-selected token, and — if a user token is
still on disk — silently swap in an apply-capable identity:

```sh
# Same precedence as config.md Step 0. Omit these two lines if HCP_TOKEN is already set.
HCP_TOKEN=${TF_TOKEN_app_terraform_io:-$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)}
curl -s "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/cloudflare" \
  -H "Authorization: Bearer $HCP_TOKEN" | jq '.data.id'
```

Useful for reading plan summaries before merging a PR, confirming applies after a clean plan, and inspecting runs that didn't post status back to GitHub.

## Migrating away

If HCP ever stops being the right choice: `terraform state pull` from each workspace, `terraform state push` to the new backend. Code stays unchanged except for the `cloud {}` block (replace with `backend "..." {}`). This is the main reason for picking a managed backend now rather than self-hosting state on day one.

---

## Object-storage backend

When `backend: object-storage` is set in [`../config.md`](../config.md), state lives in a cloud storage bucket instead of HCP Terraform. This mode uses GitHub Actions for CI instead of HCP's VCS integration.

## Supported backends

Supported backends with automated verification:

| Backend | Locking | Region field | Notes |
|---------|---------|--------------|-------|
| `gcs` | Native | N/A (bucket location) | Best for GCP-heavy repos |
| `s3` | DynamoDB table | Required | Set `state_lock_table` |
| `azurerm` | Native (blob lease) | Required (location) | Azure Storage container (set `azure_storage_account`, `azure_resource_group`) |

S3-compatible object stores (Cloudflare R2, MinIO, etc.) are **not currently supported** by automated verification. The `state-bucket` check uses AWS S3 APIs without custom endpoint support, and there is no alternative locking mechanism for stores without DynamoDB. Manual backend configuration may work but will not pass Phase 0 verification.

## Bucket setup

Create a versioned, private bucket before running `terraform init`:

**GCS:**

```sh
gcloud storage buckets create gs://$STATE_BUCKET \
  --location=us --uniform-bucket-level-access --versioning
```

**S3 + DynamoDB:**

```sh
# us-east-1:
aws s3api create-bucket --bucket "$STATE_BUCKET" --region us-east-1
# outside us-east-1:
# aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$STATE_REGION" \
#   --create-bucket-configuration LocationConstraint="$STATE_REGION"

aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api put-public-access-block --bucket "$STATE_BUCKET" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws dynamodb create-table --table-name "$STATE_LOCK_TABLE" \
  --region "$STATE_REGION" \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

**Azure (Blob Storage):**

```sh
az group create --name "$AZURE_RESOURCE_GROUP" --location "$STATE_REGION"
az storage account create --name "$AZURE_STORAGE_ACCOUNT" --resource-group "$AZURE_RESOURCE_GROUP" --sku Standard_LRS --encryption-services blob
# Enable blob versioning for state history recovery
az storage account blob-service-properties update --account-name "$AZURE_STORAGE_ACCOUNT" --enable-versioning true
az storage container create --account-name "$AZURE_STORAGE_ACCOUNT" --name "$STATE_BUCKET" --public-access off
```

## Backend configuration

Each leaf needs a `backend.tf` with the backend block. The `state_prefix` config field sets the path prefix; each leaf appends its name:

**GCS example (`terraform/cloudflare/backend.tf`):**

```hcl
terraform {
  backend "gcs" {
    bucket = "your-org-tf-state"
    prefix = "terraform/state/cloudflare"
  }
}
```

**S3 example (`terraform/cloudflare/backend.tf`):**

```hcl
terraform {
  backend "s3" {
    bucket         = "your-org-tf-state"
    key            = "terraform/state/cloudflare/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-locks"
    encrypt        = true
  }
}
```

**AzureRM example (`terraform/cloudflare/backend.tf`):**

```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "your-resource-group"
    storage_account_name = "yourstorageaccount"
    container_name       = "your-org-tf-state"
    key                  = "terraform/state/cloudflare/terraform.tfstate"
    use_azuread_auth     = true  # Required for federated identity (no access keys)
  }
}
```

## Variables (secrets)

In object-storage mode, secrets live in **GitHub Actions secrets** instead of HCP workspace variables:

| Secret | Purpose |
|--------|---------|
| `CLOUDFLARE_API_TOKEN` | Cloudflare provider auth |
| `GH_APP_ID` | GitHub App ID |
| `GH_APP_INSTALLATION_ID` | GitHub App installation ID |
| `GH_APP_PEM` | GitHub App private key |

For cloud provider auth (GCS, S3, Azure), use Workload Identity Federation where possible — no long-lived credentials to store.

## Access control

- **Read state**: Anyone with bucket read access
- **Trigger plan**: Anyone who can open a PR (GitHub Actions runs on `pull_request`)
- **Confirm apply**: Reviewers in the GitHub Environment (see [`ci.md#github-actions`](./ci.md#github-actions))
- **Direct apply**: Anyone with bucket write access + `terraform apply` locally

## Migrating from HCP

1. Ensure each leaf is initialized with the current HCP backend: `terraform init`
2. For each leaf, pull and save a state backup outside the repo with restrictive permissions:

   ```sh
   umask 077 && terraform state pull > /tmp/$(basename "$PWD")-state.json
   ```

3. Update each leaf's `versions.tf`: remove `cloud {}`, add `backend "..." {}`
4. Run `terraform init -migrate-state` in each leaf (or `terraform init` and `terraform state push /tmp/<leaf>-state.json` if configuring from scratch)
5. Verify `terraform state list` matches the resources in the destination backend before deleting any HCP workspaces
6. **Delete the plaintext state backups** — they may contain sensitive values:

   ```sh
   # Delete only the backups created in step 2 (cloudflare-state.json, github-state.json, etc.)
   rm -f /tmp/cloudflare-state.json /tmp/github-state.json
   ```
