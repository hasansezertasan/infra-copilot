<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:fd137515c562368b266d27c55955f5514136c09e37dc2904de6eda4a4b32e1be
Source-Hash: blake3:1dc2bb768d75a6b5f133bcb28897bd2eec92647e797988f199e55974253b44f8
Schema-Version: v1
-->

# Object-storage state

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
