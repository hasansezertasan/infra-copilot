<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:5cc147ac16ae6d7fa6f4bf56ef99bb3f4bc8280344181240d185274568d5e61c
Source-Hash: blake3:3a9697a49dfbe82ce6e776a6cb9df377de2454c7b960f3fb5a5526b3b2b7c1ab
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

S3-compatible object stores (Cloudflare R2, MinIO, etc.) are **not currently supported** by automated verification. The `state-bucket` check uses AWS S3 APIs without custom endpoint support, and requires a DynamoDB lock table for S3. This is a repository verification requirement. Terraform also supports [native S3 lockfiles](https://developer.hashicorp.com/terraform/language/backend/s3#state-locking) with `use_lockfile`; that configuration is not covered by this check. Manual backend configuration may work but will not pass Phase 0 verification.

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

## State history and lifecycle

Each noncurrent state version is a complete snapshot and can contain secrets.
Versioning alone retains those snapshots indefinitely.
For a Terraform-managed GCS bucket, consider this lifecycle rule inside `google_storage_bucket` (see [Cloud Storage lifecycle conditions](https://docs.cloud.google.com/storage/docs/lifecycle#conditions)):

```hcl
lifecycle_rule {
  condition {
    num_newer_versions         = 50
    days_since_noncurrent_time = 90
    with_state                 = "ARCHIVED"
  }
  action { type = "Delete" }
}
```

All conditions must hold: delete only archived versions with at least 50 newer versions and at least 90 days since they became noncurrent.
A burst of applies cannot purge recent history.
Choose the count and age for your recovery needs; review existing lifecycle rules for broader deletions that could bypass this floor.
Configure equivalent noncurrent-version expiry for S3/Azure and test restore access.
Lifecycle expiry is different from a bucket retention policy: do not lock live state or lock objects against writes/deletion that Terraform needs for normal operation.

If a leaf manages its own state bucket, WIF pool/providers or apply-identity IAM binding, a change can apply successfully and then prevent every subsequent apply.
Preserve an independently authenticated project-owner recovery path before moving this plumbing into Terraform.
CI cannot repair lost access to its own backend or identity; for GCP, recover with `gcloud` as a project owner, then reconcile Terraform.

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

| Secret | Purpose | Scope |
|--------|---------|-------|
| `CLOUDFLARE_API_TOKEN_READ` | Cloudflare Read token | Repository, plan only |
| `GH_APP_READ_ID`, `GH_APP_READ_INSTALLATION_ID`, `GH_APP_READ_PEM` | Separate read-only GitHub App | Repository, plan only |
| `CLOUDFLARE_API_TOKEN` | Cloudflare Edit token | Production environment only |
| `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `GH_APP_PEM` | Write GitHub App | Production environment only |

Verify the production environment allows exactly `main` before installing write secrets.
Delete repository copies and rotate old write credentials previously exposed to branches.
Plan identities read state only and run `-lock=false`; apply identities write state and locks.
GitHub plans additionally use `-refresh=false`; apply refreshes live state on merge.

For cloud provider auth (GCS, S3, Azure), use Workload Identity Federation where possible — no long-lived credentials to store. See [GCP Workload Identity Federation](./object-storage-ci.md#gcp-workload-identity-federation) for the dedicated pool requirement, immutable ID pins, plan/apply provider separation, and Terraform HCL.

## Access control

- **Read state**: Anyone with bucket read access
- **Trigger CI**: Anyone who can open a PR; fork PRs run validation only.
- **Trigger credentialed plan**: The guarded same-repository branch path in the committed workflow
- **Confirm apply**: Reviewers in the `main`-only GitHub Environment where the plan offers them, otherwise the locked `Apply gate` decision (see [`object-storage-ci.md#github-environments`](./object-storage-ci.md#github-environments))
- **Direct apply**: Anyone with bucket write access + `terraform apply` locally

## Migrating from HCP

Treat each leaf as a cutover, with one writer at a time.
**Lock HCP → pull and scan → upload and verify → re-run the Actions plan → merge → disconnect HCP → verify the Actions apply → retire credentials.** Never merge the backend switch before its state is verified in the bucket: the merge triggers Actions apply, and missing state can make Terraform plan to create everything.
The apply template's empty-state guard is a second barrier; it cannot detect stale or partially copied state.
The human performs the state transfer, HCP changes, merge and apply approval; the agent prepares the PR and reads verification evidence under the shared protocol.

### Prepare the cutover PR

Provision the private, versioned bucket and Actions plan/apply identities first.
In one PR, remove the leaf's `cloud {}` block, add its `backend.tf`, configure Actions jobs for that leaf, and replace its HCP required check with the aggregate `plan` check (see [branch protection](object-storage-ci.md#branch-protection)).
Review the actual `Terraform Cloud/<org>/<workspace>` context; do not guess its name.
If branch protection is managed outside Terraform, schedule the settings change as part of this cutover and verify it immediately after merge.
Keep resource changes out of the backend PR so the first bucket-backed plan is a no-op.
Set a suitable apply timeout and retain the empty-state guard for every migrated leaf.

Prepare these changes on a branch, but **do not start credentialed plan jobs or initialize the destination before the upload** if their identity can write state.
Legacy plan identities with objectAdmin can make GCS `terraform init` create an empty
`default.tfstate`, preventing the later no-clobber upload. The shipped plan identity now
has objectViewer only; remove old write grants before starting its jobs.
Upload first, then open the PR/run its plans, or explicitly hold those jobs until transfer.
A draft PR alone does not suppress workflows.
If an earlier job already initialized the destination, stop and investigate that object and any lock before proceeding; never overwrite or delete an unverified destination.

A read-only GCS plan identity (`roles/storage.objectViewer`, with `-lock=false` for plans) may fail its first `terraform init` before state exists: initialization tries to create `default.tflock` and receives a `403 storage.objects.create` error.
That is an expected pre-transfer failure, not a reason to merge or grant the plan identity write access.
Upload state, then re-run the PR plan.
Do not grant plan objectAdmin to fix initialization. Fresh leaves use the separate
[HUMAN bootstrap procedure](#fresh-leaf-bootstrap) before their first read-only plan.

### Fresh leaf bootstrap

For a genuinely new state destination with no previous Terraform state, a HUMAN
initializes empty backend state before requiring its first PR plan. This avoids the
GCS first-plan/first-apply deadlock while preserving branch read-only IAM and main protection.
Never use this procedure for state migrations, resources already managed in another
state, or an unreadable destination. First adoption of existing **unmanaged** resources
is permitted only after verifying no previous state owns them; its first plan must contain
imports, with no unintended creates, destroys or changes.

1. Review the exact leaf backend, bucket/container, key/prefix and workspace. Verify
   with authorized backend access that the state object is genuinely absent, not hidden
   by a permission error, and that no writer or lock is active.
2. In a temporary directory controlled by the HUMAN, copy only the reviewed backend
   configuration and Terraform version requirement. No resources, modules, data sources,
   provider credentials in HCL, or import blocks. Use a separately authorized bootstrap
   identity with narrowly scoped state/lock write access; do not grant writes to plan or
   loosen the apply identity's OIDC trust to authorize a branch.
3. The HUMAN runs the pinned `terraform init` for that backend and workspace. For GCS,
   this creates the initial empty state and releases its initialization lock. Verify the
   destination object exists and `terraform state pull` shows empty resources, a lineage
   and valid state version. If that backend does not persist state on init, stop and
   follow its reviewed state-initialization procedure rather than assume readiness.
4. Remove temporary bootstrap access, then run the branch's read-only plan. It should
   show the reviewed first creates for new resources, or imports for existing unmanaged
   resources. The agent never performs this credentialed bootstrap.
5. For the first production resource creation, the HUMAN sets that leaf's
   `TF_ALLOW_EMPTY_STATE_<LEAF>` environment variable to `true`, reviews the planned
   creates (or import-only adoption), merges through the normal gate and verifies apply.
   Remove the opt-out afterward.

The bootstrap `backend-identity-trust` and additional-provider identity handoffs require
this state-readiness review before the first plan; repeat IAM review on resume.

### Freeze and pull from HCP

Pause merges and local applies for the leaf; wait for any active HCP apply to finish.
Lock the workspace **before pulling**, using the HCP UI or `POST /workspaces/:id/actions/lock` under `/api/v2`.
Confirm it is locked and no apply is still running.
An apply between pull and merge would leave the bucket with stale state even if the empty-state guard passes.
Locking prevents applies, but speculative PR plans can still run with HCP's privileged identity until the VCS connection is removed.

Use a clean copy of the current default branch, with the old HCP config, to avoid pulling from a locally edited backend.
Run these commands from the consuming repo in a private terminal, with HCP read credentials available; replace the leaf and workspace ID:

```sh
set -eu
umask 077
LEAF=github
HCP_WORKSPACE_ID=ws-REPLACE
CUTOVER_DIR=$(mktemp -d)
git fetch origin main
# Include shared modules and repo tool pins; adjust paths to match tracked files.
git archive origin/main terraform mise.toml mise.lock | tar -x -C "$CUTOVER_DIR"
# Review the archived pins from the trusted main branch before trusting this copy.
mise trust "$CUTOVER_DIR/mise.toml"
cd "$CUTOVER_DIR/terraform/$LEAF"
terraform init
terraform state list | LC_ALL=C sort > "$CUTOVER_DIR/resources-before.txt"
terraform state pull > "$CUTOVER_DIR/leaf.tfstate"
# Fetch metadata only; never print the state or its secret values to logs.
curl --fail --silent --show-error \
  --header "Authorization: Bearer $HCP_TOKEN" \
  "https://app.terraform.io/api/v2/workspaces/$HCP_WORKSPACE_ID/current-state-version" \
  > "$CUTOVER_DIR/hcp-version.json"
# The API metadata exposes serial, but lineage is in the raw state download.
STATE_DOWNLOAD_URL=$(jq -er '.data.attributes."hosted-state-download-url"' \
  "$CUTOVER_DIR/hcp-version.json")
curl --fail --silent --show-error "$STATE_DOWNLOAD_URL" > "$CUTOVER_DIR/hcp-current.tfstate"
jq -e --slurpfile metadata "$CUTOVER_DIR/hcp-version.json" \
  --slurpfile hcp "$CUTOVER_DIR/hcp-current.tfstate" \
  '(.serial | type == "number") and (.lineage | type == "string" and length > 0) and
   .serial == $metadata[0].data.attributes.serial and
   .serial == $hcp[0].serial and .lineage == $hcp[0].lineage' "$CUTOVER_DIR/leaf.tfstate"
```

Treat the download URL as a credential: keep it and both state files out of logs.
The [state-versions API](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/state-versions) returns a raw-state download URL; use that snapshot for lineage, not the metadata.
Stop on any serial/lineage mismatch, unreadable metadata or unexpected empty resource list.
Confirm the archived backend names the intended HCP workspace.
Keep the workspace locked throughout transfer and cutover; do not resume HCP applies to work around a failed upload.

### Scan before upload

Bucket state is readable by the plan identity, including branch-triggered plans allowed by its trust policy.
`sensitive = true` hides output in a plan but does not remove values from state.
Before uploading, inspect locally for `password`, `private_key`, `secret_data`, client keys, certificate keys and other provider-specific secrets, including outputs.
This conservative scan returns only a boolean, never secret values:

```sh
suspect=$(jq 'any(paths(scalars);
  any(.[]; type == "string" and
    test("password|private.?key|secret.?data|client.?key|cert(ificate)?.?key"; "i")))' \
  "$CUTOVER_DIR/leaf.tfstate") || exit 1
if [ "$suspect" != "false" ]; then
  echo "Potential secrets in state; stop and review locally before upload."
  exit 1
fi
```

Key-name scanning cannot prove that state is secret-free.
Review the provider schemas and values locally as well; stop if secrets are found.
Move secrets out of Terraform-managed state or revise the plan trust/access design before resuming, then pull and scan a fresh snapshot.

### Upload and verify before merge

For GCS's **default Terraform workspace**, the object is `gs://<bucket>/<state_prefix>/<leaf>/default.tfstate` (named workspaces use a different object name).
A normal `gcloud auth login` can copy it without Application Default Credentials (ADC); Terraform's GCS backend instead needs ADC or another supported backend credential source.
With the same private shell and protected directory from the pull:

```sh
STATE_BUCKET=your-org-tf-state
STATE_PREFIX=terraform/state
STATE_OBJECT="gs://$STATE_BUCKET/$STATE_PREFIX/$LEAF/default.tfstate"
gcloud storage cp --no-clobber --if-generation-match=0 \
  --content-type=application/json "$CUTOVER_DIR/leaf.tfstate" "$STATE_OBJECT"
gcloud storage cat "$STATE_OBJECT" > "$CUTOVER_DIR/uploaded.tfstate"
cmp "$CUTOVER_DIR/leaf.tfstate" "$CUTOVER_DIR/uploaded.tfstate"
jq -e --slurpfile source "$CUTOVER_DIR/leaf.tfstate" \
  '.serial == $source[0].serial and .lineage == $source[0].lineage' \
  "$CUTOVER_DIR/uploaded.tfstate"
```

`--no-clobber` skips an existing object; the generation precondition also prevents a racing writer from replacing one.
Do not count the copy's exit code as verification: read back and compare bytes, and stop to investigate any pre-existing destination.
Do not overwrite it or use `terraform state push -force`.
For S3/Azure, initialize an isolated destination configuration and use `terraform state push` with the protected snapshot, after verifying the destination is unused and freezing other writers.
If using `terraform init -migrate-state` with suitable backend credentials, keep the same freeze, backup, secret scan and verification gates; stop if HCP's lock prevents migration rather than unlocking it to permit competing runs.

From the PR's destination backend, with appropriate backend read credentials, initialize and compare sorted `terraform state list` output with `resources-before.txt`.
Verify serial and lineage against HCP's still-current state version again.
Re-run the PR's Actions plan after upload and require a successful **leaf** plan with the expected resources and no unintended changes; a green aggregate with a skipped leaf is insufficient.
Only then may the human merge the cutover PR.

### Disconnect HCP and retire credentials

Immediately after merge, keep the HCP workspace locked and remove its VCS connection: `PATCH /workspaces/:id` with this JSON:API body (see the [workspaces API](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/workspaces#update-a-workspace)):

```json
{"data":{"type":"workspaces","id":"ws-REPLACE","attributes":{"vcs-repo":null}}}
```

Inspect every nonterminal HCP run, including the merge-triggered run.
Read `GET /runs/:id` and inspect `data.attributes.status` and `data.attributes.actions` before choosing an action.
If `is-discardable` is true, use `POST /runs/:id/actions/discard` (documented for pending runs and runs awaiting confirmation).
Use `POST /runs/:id/actions/cancel` only when `is-cancelable` is true; the documented cancel operation normally interrupts planning or applying.
Reported cutovers saw queued-behind-lock runs reject discard with `409` and accept cancel, so do not select an operation from the queue label alone.
On `409`, re-read the run and its advertised actions instead of blindly switching endpoints.
If neither action is permitted, stop and keep the workspace locked while investigating.
Re-read run status and require a terminal cancelled/discarded outcome; an API error is not evidence that it stopped.
See the [runs API](https://developer.hashicorp.com/terraform/cloud-docs/api-docs/run) for supported actions.
Never confirm an HCP apply against the old state.
See [run management](https://developer.hashicorp.com/terraform/cloud-docs/workspaces/run/manage).

Delete the migrated workspace's `TFC_*` dynamic-credential variables and secret workspace variables (including the Cloudflare token and GitHub App PEM); check variable-set sources too.
Keep the workspace locked and disconnected as a temporary historical fallback if desired.
Its state becomes stale after the first Actions apply: restoring HCP requires another frozen, verified state transfer, not simply unlocking the workspace.

Verify the successful merge-SHA `apply-<leaf>` job under the production approval gate, its resource results, and the new required checks on a subsequent PR.
Once Actions applies run clean, remove the HCP WIF service-account bindings, then its providers/pool if no remaining leaf uses them.
Revoke obsolete HCP team/user tokens, remove local/CI copies, and rotate provider tokens and App keys that were ever stored in HCP.
Verify replacement credentials before revoking their old versions.
Do not revoke shared tokens, delete shared variable sets or remove shared WIF bindings while another HCP leaf still depends on them.
Delete HCP workspaces only after verified cutover and the chosen fallback window; workspace deletion is not an infrastructure destroy operation.

Delete the plaintext backups, downloaded state and temporary `.terraform` metadata after verification; never commit them or upload them as CI artifacts.
Remove only the recorded `CUTOVER_DIR` created for this cutover.

### Mixed-backend window

The config has one repo-wide `backend:` and no per-leaf overrides.
For a leaf-by-leaf migration, keep `backend: hcp` until the **last** leaf moves; change it to `object-storage` in that leaf's cutover PR.
During the mixed window, `status` cannot certify both halves: migrated leaves may fail HCP checks and object-storage steps are skipped.
Record leaf names, backend destinations, HCP lock/disconnect state, upload verification, plan/apply SHAs and pending cleanup in the cutover PR or repo-local migration notes, and inspect them manually.
Do not re-run setup across all leaves or treat the global scan as migration completion.

Customize workflows so Actions plans/applies target **only migrated leaves**, including changes-job outputs, path filters, job conditions, the validation matrix, and aggregate `plan` dependencies/status logic.
Shared-module/config changes must still fan out to all migrated leaves.
Retain HCP required contexts for leaves still on HCP; replace only the migrated leaf's context and keep `plan` required alongside the remaining HCP checks.
Remove each migrated workspace's VCS connection after its merge, and defer shared credential cleanup until the last dependent leaf is cut over.
