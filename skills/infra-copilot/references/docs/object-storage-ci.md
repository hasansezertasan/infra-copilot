<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:e0e6d8fe49acd589031b5fda4b05eb994cd8cff0083a76d76e6e79e1a1895e73
Source-Hash: blake3:3900082067c36989bcac64abd343b9f9c855338d13b86f9ec73ae73e5531db95
Schema-Version: v1
-->

# Object-storage CI

## GitHub Actions

When `backend: object-storage` is set in [`../config.md`](../config.md), CI runs entirely in GitHub Actions instead of HCP's VCS integration. This section documents that mode.

## Trust boundary (object-storage mode)

| Surface | Visibility | Holds secrets? |
|---|---|---|
| Repo source, Issues, PRs, Actions logs | Public | no |
| GitHub Actions encrypted secrets | Private (repo settings) | yes — Cloudflare token, GitHub App creds |
| `terraform plan` output | PR comment | **sensitive values shown** unless marked `sensitive = true` |

Unlike HCP mode, plan output appears directly in PR comments. Mark all sensitive outputs with `sensitive = true` in your Terraform code.

## Workflows

Two workflows handle the Terraform lifecycle. See the templates for full implementations:

- [`../templates/terraform-plan.yml`](../templates/terraform-plan.yml) — runs on every PR that touches `terraform/**`
- [`../templates/terraform-apply.yml`](../templates/terraform-apply.yml) — runs on merge to `main` in the `main`-only `production` environment

The plan workflow uses `dorny/paths-filter` to detect which leaves changed, runs `terraform plan` for each, and posts the output as a PR comment. The apply workflow references a GitHub Environment (`production`) restricted to `main`, with required reviewers where GitHub offers them (see [GitHub Environments](#github-environments)).

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

The apply template reads `terraform state list` after initialization and refuses empty
state or any read error before applying.
For a truly new leaf's first creation only, set its production environment variable
`TF_ALLOW_EMPTY_STATE_CLOUDFLARE` or `TF_ALLOW_EMPTY_STATE_GITHUB` to the exact string
`true`, review the expected creates, then remove it after the first successful apply.
Keep the guard and use a separate variable for each additional leaf.
Never enable this opt-out to fix a migration or authentication failure.

The template sets `timeout-minutes: 120` on apply jobs; size it for the leaf's longest
provider operation plus the rest of the apply.
[Cloud SQL instance operations](https://github.com/hashicorp/terraform-provider-google/blob/main/website/docs/r/sql_database_instance.html.markdown#timeouts)
have a default provider timeout of 90 minutes, and GKE node-pool updates can also exceed
30 minutes. Adjust provider `timeouts` and job timeouts together for larger leaves.
A killed apply can leave a lock held and omit the final state write.

If an apply times out, first confirm its runner/process and provider operation have
stopped and no other writer is active. Inspect live resources and the latest state before
retrying; do not assume the timeout rolled changes back.
Using authorized backend credentials in the correct leaf/backend, a human may run
`terraform force-unlock <LOCK_ID>` only for the abandoned lock reported by Terraform.
[Force-unlock](https://developer.hashicorp.com/terraform/cli/commands/force-unlock)
removes the lock; it does not repair state or undo infrastructure changes.
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

# Service account for plan runs (state locking and reading)
resource "google_service_account" "plan" {
  account_id   = "tf-plan"
  display_name = "Terraform Plan runner"
}

resource "google_service_account_iam_member" "plan_wif" {
  service_account_id = google_service_account.plan.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.infra.workload_identity_pool_id}/attribute.repository_id/<repo-id>"
}

# Note: GCS backend acquires a state lock during plan, requiring objectAdmin to create and release .tflock objects
resource "google_storage_bucket_iam_member" "plan_state" {
  bucket = "<state-bucket>"
  role   = "roles/storage.objectAdmin"
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

# Grant storage permissions on the state bucket (objectAdmin needed for state locking)
gcloud storage buckets add-iam-policy-binding "gs://<state-bucket>" \
  --member="serviceAccount:tf-apply@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

gcloud storage buckets add-iam-policy-binding "gs://<state-bucket>" \
  --member="serviceAccount:tf-plan@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

#### GitHub secrets and workflow usage

Set repository secrets for the default or plan runner:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: `projects/<project-number>/locations/global/workloadIdentityPools/gha-infra/providers/plan`
- `GCP_SERVICE_ACCOUNT`: `tf-plan@<project-id>.iam.gserviceaccount.com`

For the production apply job in `terraform-apply.yml`, configure environment secrets under the `production` environment:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: `projects/<project-number>/locations/global/workloadIdentityPools/gha-infra/providers/apply`
- `GCP_SERVICE_ACCOUNT`: `tf-apply@<project-id>.iam.gserviceaccount.com`

**AWS:**

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
    aws-region: us-east-1
```

**Azure:**

```yaml
- uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

### Terraform providers

Set secrets as environment variables:

```yaml
env:
  CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
  GITHUB_APP_ID: ${{ secrets.GH_APP_ID }}
  GITHUB_APP_INSTALLATION_ID: ${{ secrets.GH_APP_INSTALLATION_ID }}
  GITHUB_APP_PEM_FILE: ${{ secrets.GH_APP_PEM }}
```

## Branch protection

Require the aggregate `plan` job: it runs even when no leaf changed and includes
validation plus every applicable leaf plan. Path-filtered per-leaf required checks can
be skipped without reporting, leaving unrelated PRs waiting forever.
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

Replace the migrated leaf's HCP context in the backend cutover PR, after uploading and
verifying its state and obtaining a successful Actions leaf plan.
For Terraform-managed protection, the merge's apply installs the new checks; for manually
managed protection, coordinate the settings update with the merge.
While HCP is locked its speculative plan can still satisfy the old context on the cutover
PR; verify this before merge. If it does not report, a maintainer must coordinate the
context transition without leaving subsequent PRs waiting for a disconnected workspace.
Keep HCP contexts for leaves still using it; see
[the staged cutover](object-storage-state.md#mixed-backend-window).
The `status-check-gha` step in [`../steps.yaml`](../steps.yaml) verifies a successful
Actions context; also inspect the live branch-protection settings.

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
