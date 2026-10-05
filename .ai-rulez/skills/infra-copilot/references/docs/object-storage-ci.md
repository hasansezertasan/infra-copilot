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

The `status-check-gha` step in [`../steps.yaml`](../steps.yaml) verifies this alignment.

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
