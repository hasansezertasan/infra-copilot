<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:8eea54ee08ae7794d9a0de93c2d04da2837b59fa0313dcf2766369d4dd9b07cc
Source-Hash: blake3:0701b063a68b5dc12bcd2d634e041e74cf431681c98eab86a076c7e32a5cbead
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
- [`../templates/terraform-apply.yml`](../templates/terraform-apply.yml) — runs on merge to `main`, gated by environment approval

The plan workflow uses `dorny/paths-filter` to detect which leaves changed, runs `terraform plan` for each, and posts the output as a PR comment. The apply workflow references a GitHub Environment (`production`) that requires reviewer approval before any apply proceeds.

## GitHub Environments

The apply workflow references a GitHub Environment for approval gating:

1. Go to repo **Settings → Environments**
2. Create environment `production`
3. Enable **Required reviewers** and add approvers
4. Optionally add deployment branch rules (e.g., only `main`)

This replaces HCP's "confirm apply" button. An apply waits for environment approval before running.

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
| Apply approval | HCP confirm button | GitHub Environment reviewers |
| Secrets storage | HCP workspace variables | GitHub Actions secrets |
| Run logs | HCP | GitHub Actions |
| Cost | HCP pricing | GitHub Actions minutes |
| Vendor dependency | Terraform Cloud | None (cloud storage only) |
