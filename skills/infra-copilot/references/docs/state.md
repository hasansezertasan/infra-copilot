<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:2683957cff4f8c81564df487865dd1fc8bb5201e5f5b2a3af8b817054a05669f
Source-Hash: blake3:33ad831ff6e8838b81bc7996e6b64131b3837eb8734e2f82d3173c58846bae2b
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
| `cloudflare` | the `<apex-domain>` zone + all DNS records (Email Routing + GitHub Pages) | `terraform/cloudflare/**` | no — manual apply |
| `github-org` | the repos in `managed_repos` (e.g. `<owner/repo>`) — repo settings, `main` branch protection, `safe-to-plan` label | `terraform/github/**` | no — manual apply |

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
- **Confirm apply**: workspace admins, or an authenticated `POST /api/v2/runs/<id>/actions/apply` with a personal HCP API token.
- **Manage workspace settings**: org admins.

## API access

A `terraform login` writes an HCP user API token to `~/.terraform.d/credentials.tfrc.json`. The same token authenticates every HCP REST endpoint, so anything you can do in the UI you can script via:

```sh
HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)
curl -s "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/cloudflare" \
  -H "Authorization: Bearer $HCP_TOKEN" | jq '.data.id'
```

Useful for reading plan summaries before merging a PR, confirming applies after a clean plan, and inspecting runs that didn't post status back to GitHub.

## Migrating away

If HCP ever stops being the right choice: `terraform state pull` from each workspace, `terraform state push` to the new backend. Code stays unchanged except for the `cloud {}` block (replace with `backend "..." {}`). This is the main reason for picking a managed backend now rather than self-hosting state on day one.
