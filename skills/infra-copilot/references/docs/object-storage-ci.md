<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:4fa1a5daa23f899ca66c028045538b85ec197a5adb97501f611f18df7844f18b
Source-Hash: blake3:e4fb66e379afe94b7cc1566779804e5711ef442e5cc011a3a6758aa150e5e7bb
Schema-Version: v1
-->

# Object-storage CI

## GitHub Actions

When `backend: object-storage` is set in [`../config.md`](../config.md), CI runs entirely in GitHub Actions instead of HCP's VCS integration. This section documents that mode.

## Trust boundary (object-storage mode)

| Surface | Visibility | Holds secrets? | Reachable from |
|---|---|---|---|
| Repo source, Issues, PRs, Actions logs | Public | no | Anyone |
| Read-only repository secrets | Private settings | yes — plan token and read App | Any same-repository branch; forks excluded by workflow |
| Write production environment secrets | Private settings | yes — apply token and write App | Only `main` jobs in `production` |
| Backend state | Private bucket | potentially secret values | Plan and apply identities |
| `terraform plan` output | PR comment | **sensitive values shown** unless marked `sensitive = true` | Anyone viewing the PR |

Unlike HCP mode, plan output appears directly in PR comments. Mark all sensitive outputs with `sensitive = true` in your Terraform code.
Read-only credentials still expose readable data and state to branch code. They must not grant
resource/state writes, secret-value reads outside state, or impersonation of apply. Do not
put apply credentials in repository secrets or organization secrets accessible to this repo.

## Workflows

Two workflows handle the Terraform lifecycle. See the templates for full implementations:

- [`../templates/terraform-plan.yml`](../templates/terraform-plan.yml) — runs on every PR that touches `terraform/**`
- [`../templates/terraform-apply.yml`](../templates/terraform-apply.yml) — runs on every push to `main` or manual dispatch in the `main`-only `production` environment

The plan workflow uses `dorny/paths-filter` to detect which leaves changed, runs `terraform plan` for each, and posts the output as a PR comment. Manual plan dispatch skips the PR path filter and plans every leaf.
The apply workflow applies every leaf on each push, including unchanged leaves, so a newer run catches up changes from superseded or failed runs.
To retry an apply, dispatch the workflow on `main`; each apply job refuses a ref other than `main` or a commit that is no longer its tip.
Concurrency is scoped by ref so a dispatch from another branch cannot replace a pending `main` run.
Setup checks committed workflows against the supported template layout before skipping creation.
Legacy filters, conditional applies, missing dispatch support, or missing main-tip guards make the step incomplete.
A locked dispatch-only Apply gate is supported; it must omit the push trigger.
Keep the templates' guard and expression layout when customizing provider authentication.
The apply workflow references a GitHub Environment (`production`) restricted to `main`, with required reviewers where GitHub offers them (see [GitHub Environments](#github-environments)).

## GitHub Environments

The apply workflow runs in a GitHub Environment named `production`:

1. Go to repo **Settings → Environments** and create environment `production`
2. Under **Deployment branches and tags**, choose **Selected branches and tags** and add
   exactly `main`. This is required on every plan: it is what stops a pushed branch from
   running a job in `production` and receiving the apply credentials.
3. Enable **Required reviewers** and add approvers *if GitHub offers them to this repo*.
   For private repositories they exist only on GitHub Enterprise; Free, Pro and Team reject
   the rule with `422 … ensure the billing plan supports the required reviewers protection rule`.
   Public repositories get them on every plan.

As Terraform:

```hcl
resource "github_repository_environment" "production" {
  repository  = "infra"
  environment = "production"
  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_environment_deployment_policy" "main" {
  repository     = "infra"
  environment    = github_repository_environment.production.environment
  branch_pattern = "main"
}
```

With reviewers, an apply waits for environment approval, like HCP's "confirm apply".
Where reviewers are available the `gha-environments` check requires them.

Where they are not, pick one of these human gates and lock it as an `Apply gate` row in
`.infra-copilot/decisions.md` (choice `merge-approval` or `dispatch`, status `locked`):

- **Merge is the approval** (`merge-approval`). Apply runs automatically on push to `main`.
  The human gate is the reviewed PR plan plus the required review in `main`'s branch
  protection. The apply recomputes its plan, so it can differ from the reviewed one if state
  or `main` moved in between (see the header of
  [`../templates/terraform-apply.yml`](../templates/terraform-apply.yml)).
- **Dispatch gate** (`dispatch`). Apply runs only on `workflow_dispatch`, and the apply
  identity's WIF/OIDC trust pins `assertion.actor_id` (or the triggering actor) to named
  maintainers, so nobody else's run can obtain the apply identity. That trust condition is
  a HUMAN IAM review; the check cannot see it.

The `gha-environments` check (`checks/gha-apply-gate.sh`) verifies the main-only branch
policy, then either live required reviewers or, where GitHub cannot offer them, the locked
decision.

## Apply state guard and timeouts

The apply template reads `terraform state list` after initialization and refuses empty state or any read error before applying, unless first creation is explicitly authorized.
For a truly new leaf's first creation only, set its production environment variable `TF_ALLOW_EMPTY_STATE_CLOUDFLARE` or `TF_ALLOW_EMPTY_STATE_GITHUB` to the exact string `true`, review the expected creates, then remove it after the first successful apply.
Keep the guard and use a separate variable for each additional leaf.
The opt-out bypasses the state-list guard because a new S3 leaf can have no state file at all; Terraform apply must still authenticate to and read its backend successfully.
Never enable this opt-out to fix a migration or authentication failure.

The template sets `timeout-minutes: 120` on apply jobs; size it for the leaf's longest provider operation plus the rest of the apply. [Cloud SQL instance operations](https://github.com/hashicorp/terraform-provider-google/blob/main/website/docs/r/sql_database_instance.html.markdown#timeouts) have a default provider timeout of 90 minutes, and GKE node-pool updates can also exceed 30 minutes.
Adjust provider `timeouts` and job timeouts together for larger leaves.
A killed apply can leave a lock held and omit the final state write.

If an apply times out, first confirm its runner/process and provider operation have stopped and no other writer is active.
Inspect live resources and the latest state before retrying; do not assume the timeout rolled changes back.
Using authorized backend credentials in the correct leaf/backend, a human may run `terraform force-unlock <LOCK_ID>` only for the abandoned lock reported by Terraform. [Force-unlock](https://developer.hashicorp.com/terraform/cli/commands/force-unlock) removes the lock; it does not repair state or undo infrastructure changes.
Reconcile any missing state/resources and review a fresh plan before the next apply.

## Authentication

### Cloud provider (GCS/S3/Azure)

Use Workload Identity Federation / OIDC — no stored credentials:

**GCS:**

```yaml
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
    service_account: ${{ secrets.GCP_SERVICE_ACCOUNT }}
```

See [GCP Workload Identity Federation](#gcp-workload-identity-federation) below for the complete pool and provider setup, attribute conditions, and IAM bindings.

### GCP Workload Identity Federation

When using GCS as the state backend (or managing GCP infrastructure in GitHub Actions), use
Workload Identity Federation (WIF) instead of storing long-lived service account keys in
repository secrets.

#### Trust hazards

Without strict attribute conditions, naive GitHub Actions OIDC configurations introduce
severe vulnerabilities:

1. **Pool-wide bindings leak across repositories.** `principalSet://…/workloadIdentityPools/<pool>/attribute.X/Y`
   matches tokens admitted by **any** provider in that pool. If another repository's provider
   shares the pool and its service account binding matches an attribute (such as `attribute.environment/dev`),
   any token admitted into the pool with that attribute can impersonate that repository's service account.
2. **Branch tokens get apply credentials.** A condition that checks only the repository name admits every
   branch, pull request, workflow file, and event. Untrusted feature branches can mint apply-grade credentials.
3. **Target events run fork code with base-repo tokens.** Workflows triggered by `pull_request_target` or
   `workflow_run` run in the context of the base repository and mint base-repo OIDC tokens while having access
   to checkout untrusted fork code.

#### Security rules

- **One dedicated pool per repository.** Never add a provider to a pool shared with another repository.
- **Pin immutable repository and owner IDs.** Match `assertion.repository_id` and
  `assertion.repository_owner_id`, not names. Repository and organization renames or re-creations preserve
  names but generate new immutable IDs. Obtain these with:

  ```sh
  gh api repos/<owner>/<repo> -q '.id, .owner.id'
  ```

- **Split plan and apply providers:**
  - **Apply provider (`apply`):** Constrained to `assertion.ref == 'refs/heads/main'`,
    `assertion.workflow_ref` pinned to the apply workflow on `main` (or `assertion.job_workflow_ref` if invoked as a reusable workflow), and
    `has(assertion.environment) && assertion.environment == 'production'`.
  - **Plan provider (`plan`):** Allowed only on safe plan events (`assertion.event_name in ['pull_request', 'push', 'workflow_dispatch']`)
    and explicitly requires `!has(assertion.environment)`, ensuring plan tokens can never pass as apply tokens
    and target events are refused.
- **Plan workflow provenance:** Direct workflows on pull requests carry a dynamic ref suffix
  (such as `@refs/pull/<pr>/merge`), so checking `startsWith('<owner>/<repo>/.github/workflows/terraform-plan.yml@')`
  restricts tokens to the plan workflow file while admitting branch PR runs. To protect against
  branch authors altering the plan workflow on feature branches to misuse state locking permissions,
  delegate plan execution to a reusable workflow pinned to `main` (for example,
  `<owner>/<repo>/.github/workflows/reusable-plan.yml@refs/heads/main`) and condition on the exact
  `assertion.job_workflow_ref == '<owner>/<repo>/.github/workflows/reusable-plan.yml@refs/heads/main'`.
- **Avoid mapping claims omitted by workflows:** GitHub only supplies `environment` to jobs bound
  to an environment, and only supplies `job_workflow_ref` to jobs invoked as reusable workflows. Because
  Google evaluates every attribute-mapping CEL expression during token exchange, referencing absent claims
  causes token exchange to fail before attribute conditions run. Define separate attribute mappings: the
  `plan` provider maps claims present in plan runs (`sub`, `repository_id`, `repository_owner_id`, `ref`,
  `event_name`, `workflow_ref`), while the `apply` provider additionally maps `environment`.
- **Map a bounded WIF subject:** Google STS limits `google.subject` to 127 bytes. GitHub's
  default `assertion.sub` can exceed this limit on repositories with long names or ref paths (producing
  >127 bytes), failing token exchange before conditions run. Map `google.subject` to the compact,
  immutable `assertion.repository_id` instead.
- **Differentiate service account bindings:** Because both providers feed the same pool, do not use the
  pool-wide `/*` principal set. Bind the apply service account to the specific principal attribute that only
  apply tokens carry (for example, `principalSet://iam.googleapis.com/projects/<project-number>/locations/global/workloadIdentityPools/<pool>/attribute.environment/production`),
  and bind the plan service account to `principalSet://iam.googleapis.com/projects/<project-number>/locations/global/workloadIdentityPools/<pool>/attribute.repository_id/<repo-id>`.
  Because the pool is dedicated to this repository and only the apply provider admits `assertion.environment == 'production'`,
  binding to `attribute.environment/production` avoids depending on mutable or format-changing subject (`sub`) claims.

#### Terraform HCL configuration

```hcl
resource "google_iam_workload_identity_pool" "infra" {
  workload_identity_pool_id = "gha-infra" # dedicated to this repository
  display_name              = "GitHub Actions (infra)"
}

locals {
  gha_mapping_plan = {
    "google.subject"                = "assertion.repository_id"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
    "attribute.event_name"          = "assertion.event_name"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
  }
  gha_mapping_apply = {
    "google.subject"                = "assertion.repository_id"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
    "attribute.event_name"          = "assertion.event_name"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
    "attribute.environment"         = "assertion.environment"
  }
  repo_pin = "assertion.repository_id == '<repo-id>' && assertion.repository_owner_id == '<owner-id>'"
}

resource "google_iam_workload_identity_pool_provider" "apply" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.infra.workload_identity_pool_id
  workload_identity_pool_provider_id = "apply"
  display_name                       = "GitHub Actions apply"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
  attribute_mapping = local.gha_mapping_apply
  attribute_condition = join(" && ", [
    local.repo_pin,
    "assertion.ref == 'refs/heads/main'",
    "assertion.workflow_ref == '<owner>/<repo>/.github/workflows/terraform-apply.yml@refs/heads/main'",
    "has(assertion.environment) && assertion.environment == 'production'",
  ])
}

resource "google_iam_workload_identity_pool_provider" "plan" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.infra.workload_identity_pool_id
  workload_identity_pool_provider_id = "plan"
  display_name                       = "GitHub Actions plan"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
  attribute_mapping = local.gha_mapping_plan
  # For direct workflows: startsWith admits PR merge refs while pinning the workflow path.
  # For reusable workflows: replace startsWith with exact pinning to refs/heads/main:
  #   "has(assertion.job_workflow_ref) && assertion.job_workflow_ref == '<owner>/<repo>/.github/workflows/reusable-plan.yml@refs/heads/main'"
  attribute_condition = join(" && ", [
    local.repo_pin,
    "assertion.event_name in ['pull_request', 'push', 'workflow_dispatch']",
    "assertion.workflow_ref.startsWith('<owner>/<repo>/.github/workflows/terraform-plan.yml@')",
    "!has(assertion.environment)",
  ])
}

data "google_project" "current" {}

# Service account for plan runs (state reading only)
resource "google_service_account" "plan" {
  account_id   = "tf-plan"
  display_name = "Terraform Plan runner"
}

resource "google_service_account_iam_member" "plan_wif" {
  service_account_id = google_service_account.plan.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.infra.workload_identity_pool_id}/attribute.repository_id/<repo-id>"
}

# Plans use -lock=false: this identity cannot create or release locks or write state.
resource "google_storage_bucket_iam_member" "plan_state" {
  bucket = "<state-bucket>"
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.plan.email}"
}

# Service account for apply runs (state bucket access plus infrastructure permissions)
resource "google_service_account" "apply" {
  account_id   = "tf-apply"
  display_name = "Terraform Apply runner"
}

resource "google_service_account_iam_member" "apply_wif" {
  service_account_id = google_service_account.apply.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.infra.workload_identity_pool_id}/attribute.environment/production"
}

resource "google_storage_bucket_iam_member" "apply_state" {
  bucket = "<state-bucket>"
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.apply.email}"
}
```

#### gcloud setup commands

To configure the pool, providers, and service accounts using `gcloud`:

```sh
PROJECT_ID="<project-id>"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
POOL="gha-infra"
REPO_ID=$(gh api repos/<owner>/<repo> -q '.id')
OWNER_ID=$(gh api repos/<owner>/<repo> -q '.owner.id')

# Enable required Google Cloud services
gcloud services enable \
  cloudresourcemanager.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com serviceusage.googleapis.com \
  --project="$PROJECT_ID"

# Create a dedicated pool
gcloud iam workload-identity-pools create "$POOL" \
  --project="$PROJECT_ID" \
  --location=global \
  --display-name="GitHub Actions ($POOL)"

MAPPING_PLAN="google.subject=assertion.repository_id,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref,attribute.event_name=assertion.event_name,attribute.workflow_ref=assertion.workflow_ref"
MAPPING_APPLY="google.subject=assertion.repository_id,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref,attribute.event_name=assertion.event_name,attribute.workflow_ref=assertion.workflow_ref,attribute.environment=assertion.environment"
REPO_PIN="assertion.repository_id == '$REPO_ID' && assertion.repository_owner_id == '$OWNER_ID'"

# Create the apply provider
gcloud iam workload-identity-pools providers create-oidc "apply" \
  --project="$PROJECT_ID" \
  --location=global \
  --workload-identity-pool="$POOL" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="$MAPPING_APPLY" \
  --attribute-condition="$REPO_PIN && assertion.ref == 'refs/heads/main' && assertion.workflow_ref == '<owner>/<repo>/.github/workflows/terraform-apply.yml@refs/heads/main' && has(assertion.environment) && assertion.environment == 'production'"

# Create the plan provider (constrained to plan workflow)
gcloud iam workload-identity-pools providers create-oidc "plan" \
  --project="$PROJECT_ID" \
  --location=global \
  --workload-identity-pool="$POOL" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="$MAPPING_PLAN" \
  --attribute-condition="$REPO_PIN && assertion.event_name in ['pull_request', 'push', 'workflow_dispatch'] && assertion.workflow_ref.startsWith('<owner>/<repo>/.github/workflows/terraform-plan.yml@') && !has(assertion.environment)"

# Create service accounts and bind IAM
gcloud iam service-accounts create tf-apply --project="$PROJECT_ID" --display-name="Terraform Apply"
gcloud iam service-accounts create tf-plan --project="$PROJECT_ID" --display-name="Terraform Plan"

gcloud iam service-accounts add-iam-policy-binding "tf-apply@$PROJECT_ID.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.environment/production"

gcloud iam service-accounts add-iam-policy-binding "tf-plan@$PROJECT_ID.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.repository_id/$REPO_ID"

# Apply can write state/locks; plan can only read state.
gcloud storage buckets add-iam-policy-binding "gs://<state-bucket>" \
  --member="serviceAccount:tf-apply@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

gcloud storage buckets add-iam-policy-binding "gs://<state-bucket>" \
  --member="serviceAccount:tf-plan@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

#### GitHub secrets and workflow usage

Set repository secrets for the default or plan runner:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: `projects/<project-number>/locations/global/workloadIdentityPools/gha-infra/providers/plan`
- `GCP_SERVICE_ACCOUNT`: `tf-plan@<project-id>.iam.gserviceaccount.com`

For the production apply job in `terraform-apply.yml`, configure environment secrets under the `production` environment:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: `projects/<project-number>/locations/global/workloadIdentityPools/gha-infra/providers/apply`
- `GCP_SERVICE_ACCOUNT`: `tf-apply@<project-id>.iam.gserviceaccount.com`

These identifiers are public coordinates, not write keys. The environment overrides are
required, but trust and effective IAM enforce the boundary even if a branch learns the
apply coordinates. Verify distinct service accounts, remove old plan objectAdmin grants,
and check inherited/project grants and impersonation paths too. Secret-name listing alone
cannot verify IAM or that an environment value differs from its repository counterpart.

#### GCP resource refresh permissions

For a GCP resource leaf, state read access alone is insufficient. Grant the plan account
only the viewer roles needed by the actual resource types. A mixed services/IAM/service
accounts/Artifact Registry/storage/Compute/GKE/Cloud SQL/monitoring/WIF/Secret Manager leaf
can require these project roles (omit those for absent resource types):

- `roles/artifactregistry.reader`
- `roles/cloudsql.viewer`
- `roles/compute.viewer`
- `roles/container.clusterViewer`
- `roles/iam.securityReviewer`
- `roles/iam.serviceAccountViewer`
- `roles/iam.workloadIdentityPoolViewer`
- `roles/monitoring.viewer`
- `roles/secretmanager.viewer`
- `roles/serviceusage.serviceUsageViewer`
- `roles/storage.bucketViewer`

`iam.securityReviewer` permits `getIamPolicy` refresh for IAM members across resource
types and exposes every IAM policy in the project; explicitly accept that visibility.
Secret Manager Viewer reads metadata, not secret versions (`versions.access`). Never add
Secret Accessor or basic `roles/viewer`: basic Viewer can read BigQuery table data, and a
PR can add a data source. Inspect current predefined roles with `gcloud iam roles describe`
and tailor them further where needed. WIF permissions are named
`iam.googleapis.com/workloadIdentityPools.get`, not `iam.workloadIdentityPools.get`.
Unlike an HCP PR plan using a project-IAM-admin/secretmanager.admin identity, these plans
cannot use PR-added data sources to read Secret Manager values or mutate cloud resources.
GCP plans keep refresh enabled; use `-lock=false` without `-refresh=false`.

**AWS:**

Create separate plan/apply roles. Plan gets `s3:ListBucket` on the state bucket and
`s3:GetObject` on the leaf state prefix (plus narrowly scoped KMS decrypt if required).
It gets no S3 writes or DynamoDB lock mutations. Apply gets state Get/Put/Delete and
lock permissions: S3 lockfile Get/Put/Delete when `use_lockfile` is enabled, or
DynamoDB DescribeTable/GetItem/PutItem/DeleteItem for the configured lock table.
Scope policies to the actual bucket, prefixes, table and encryption key.
Cloud-resource refresh needs per-service read actions, not AdministratorAccess or broad
data-reading policies; exclude secret-value APIs and `sts:AssumeRole` into apply.

Both role trust policies must use the GitHub OIDC audience `sts.amazonaws.com` and exact
subjects. The plan role may allow `repo:<owner>/<repo>:pull_request` and explicitly
listed branch subjects for dispatch; do not wildcard repository or environment subjects.
Apply allows only `repo:<owner>/<repo>:environment:production`. GitHub's exact-main
deployment policy is required because that environment subject does not encode the ref.
Use repository `AWS_ROLE_ARN` for plan and a production environment override pointing
to the separate apply role. For a dispatch gate, enforce the named triggering actor via
an independently verified trust/gate mechanism; the default AWS subject does not carry it.

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
    aws-region: us-east-1
```

**Azure:**

Create separate applications/service principals: plan has Storage Blob Data Reader on
the state container; apply has Storage Blob Data Contributor, including lease/lock access.
Configure backend Entra ID authentication (`use_azuread_auth = true`), not account keys
or permission to list storage account keys. Cloud refresh uses resource-specific metadata
read roles/custom actions; no secret-value APIs, write actions or apply impersonation.
Federated credentials use audience `api://AzureADTokenExchange`, issuer
`https://token.actions.githubusercontent.com` and exact subjects: plan PR and explicitly
listed dispatch branches; apply `repo:<owner>/<repo>:environment:production` only.
The exact-main production policy is mandatory here too. Store plan `AZURE_CLIENT_ID`,
`AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` at repository scope and production overrides
for the distinct apply principal. Inspect effective RBAC and all federated credentials.

```yaml
- uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

### Terraform providers

Plan jobs have no environment and use read-only repository secrets:

```yaml
env:
  CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN_READ }}
  GITHUB_APP_ID: ${{ secrets.GH_APP_READ_ID }}
  GITHUB_APP_INSTALLATION_ID: ${{ secrets.GH_APP_READ_INSTALLATION_ID }}
  GITHUB_APP_PEM_FILE: ${{ secrets.GH_APP_READ_PEM }}
```

Create two Cloudflare tokens: plan has Zone DNS/Zone Settings Read, apply has Edit,
both restricted to the managed account/zones. Create two GitHub Apps: plan has only
Read permissions; apply uses the write permissions in [GitHub](../github.md).
Install each on the managed repositories; never reuse the write App PEM for plan.
GitHub hides merge settings and ruleset `bypass_actors` from read-only callers, so the
GitHub plan uses `-refresh=false` to compare against last-applied state without phantom
updates. It does not report live drift; imports/data sources may still make API calls.
All plans use `-lock=false` and may race applies; production apply refreshes and locks
its own recomputed plan, never a branch's saved `tfplan`.

Apply jobs set `environment: production` and use `CLOUDFLARE_API_TOKEN`, `GH_APP_ID`,
`GH_APP_INSTALLATION_ID`, `GH_APP_PEM` stored **only** there. Install with
`gh secret set <name> --repo <owner>/<repo> --env production`. Verify the exact-main
policy first, then delete repository copies with `gh secret delete <name> --repo <owner>/<repo>`.
Rotate previously branch-accessible write keys and revoke old values after validating
the protected apply. `gh secret list --repo <owner>/<repo>` must show read names and no
write names; `gh secret list --repo <owner>/<repo> --env production` must show write names.
Secret checks prove placement, not permissions or identity separation; a HUMAN verifies both.
Additional-provider `credential_secrets` entries declare `scope: plan` or `scope: apply`
with distinct names; an empty inventory still requires separate read/write keyless identities.

## Branch protection

Require the aggregate `plan` job: it runs even when no leaf changed and includes validation plus every applicable leaf plan.
Path-filtered per-leaf required checks can be skipped without reporting, leaving unrelated PRs waiting forever.
Required status checks reference GitHub Actions job names, not HCP contexts:

```hcl
required_status_checks {
  strict = true
  contexts = [
    "validate (cloudflare)",
    "validate (github)",
    "plan"  # aggregate plan check from terraform-plan.yml
  ]
}
```

Replace the migrated leaf's HCP context in the backend cutover PR, after uploading and verifying its state and obtaining a successful Actions leaf plan.
For Terraform-managed protection, the merge's apply installs the new checks; for manually managed protection, coordinate the settings update with the merge.
While HCP is locked its speculative plan can still satisfy the old context on the cutover PR; verify this before merge.
If it does not report, a maintainer must coordinate the context transition without leaving subsequent PRs waiting for a disconnected workspace.
Keep HCP contexts for leaves still using it; see [the staged cutover](object-storage-state.md#mixed-backend-window).
The `status-check-gha` step in [`../steps.yaml`](../steps.yaml) verifies a successful Actions context; also inspect the live branch-protection settings.

## Fork PRs

Fork PRs cannot access repository secrets. The plan workflow should:

1. Skip provider-authenticated steps for fork PRs
2. Run `terraform validate` only (with `-backend=false`)
3. Require maintainer review before any authenticated operation

The template uses `github.event.pull_request.head.repo.full_name == github.repository` to gate authenticated steps.

## Comparison: HCP vs GitHub Actions

| Aspect | HCP mode | Object-storage mode |
|--------|----------|---------------------|
| Plan visibility | HCP UI (login required) | PR comment (repo access) |
| Apply approval | HCP confirm button | Environment reviewers (Enterprise or public repos), or merge approval + `main`-only environment |
| Secrets storage | HCP workspace variables | GitHub Actions secrets |
| Run logs | HCP | GitHub Actions |
| Cost | HCP pricing | GitHub Actions minutes |
| Vendor dependency | Terraform Cloud | None (cloud storage only) |
