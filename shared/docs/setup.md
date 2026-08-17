# Setup

One-time, out-of-band steps to wire up the systems this repo manages. The Terraform code is speculative until these are done.

Run in order. Each step explains what it produces and where the value goes.

## 1. HCP Terraform — organization

1. Sign up at <https://app.terraform.io/> (free tier is sufficient to start).
2. Create an organization matching your `hcp_org` value (see [`../config.md`](../config.md)) — it must match the `organization` field in every `terraform/*/versions.tf`.
3. Inside the org, create a project named **`infra`**.

## 2. HCP Terraform — workspaces

For each Terraform leaf directory, create a VCS-linked workspace under the `infra` project:

| Leaf | Workspace name | VCS working directory |
|---|---|---|
| `terraform/cloudflare/` | `cloudflare` | `terraform/cloudflare` |
| `terraform/github/` | `github-org` | `terraform/github` |

For each workspace, in Settings → Version Control:

- VCS provider: GitHub (connect via OAuth, scope to this repo only).
- **Terraform Working Directory**: set as above.
- **Automatic Run Triggering**: set to **"Only trigger runs when files in specified paths change"**, path pattern `<working-dir>/**` (e.g. `terraform/cloudflare/**`). Without this, every push to `main` triggers every workspace — a docs-only commit will spuriously plan against Cloudflare and may fail on an unrelated change.
- **Automatic speculative plans**: **enabled**. This is the master toggle for plans on PRs; without it, PRs get no speculative plan and the GitHub status check never appears.
- **Speculative plans on PRs from forks**: **disabled**. This is a separate, fork-specific toggle. Without disabling it, anyone opening a fork PR can read the workspace's sensitive variables via a malicious `.tf` file. The label-gated plan flow in [`ci.md`](./ci.md) replaces it for fork PRs.

In Settings → General:

- **Execution mode**: Remote.
- **Auto-apply**: disabled (manual confirmation required).

## 3. Cloudflare API token

1. Go to <https://dash.cloudflare.com/profile/api-tokens> → **Create Token**.
2. **Custom token** with these permissions for the `<apex-domain>` zone and the account it belongs to:
   - Zone — DNS — Edit
   - Zone — Zone Settings — Edit
3. Account Resources: **Include — your account only**. Zone Resources: **Include — Specific zone — `<apex-domain>`**.
4. Copy the token (shown once).
5. In HCP → workspace **`cloudflare`** → Variables → add `cloudflare_api_token` as a **Terraform variable**, mark **Sensitive**, paste the token.

## Adding scopes to the Cloudflare token later

When you start managing a new Cloudflare resource type (e.g. Email Routing rules, Rulesets), the existing HCP token needs more permissions. **Edit, don't regenerate** — the value stays the same and HCP keeps working without re-pasting.

1. <https://dash.cloudflare.com/profile/api-tokens> → find the existing token → **⋯ → Edit**.
2. Under **Permissions**, click **+ Add more** and add the new rows. Examples:
   - Zone — Email Routing Rules — Edit
   - Account — Email Routing Addresses — Edit
   - Account — Rulesets — Edit (for redirect rules)
3. Confirm **Account Resources** and **Zone Resources** still match what they were.
4. **Continue to summary** → **Update token**. The token value does not change on a permission edit.

If the dashboard *does* regenerate the value (which happens if you click "Roll" or recreate instead of edit), copy the new value into HCP → workspace `cloudflare` → Variables → `cloudflare_api_token`.

## 4. GitHub App

The `github-org` workspace authenticates as a GitHub App, not a PAT.

1. Go to `https://github.com/organizations/<your-org>/settings/apps/new`.
2. Permissions (start narrow, widen on demand):
   - Repository: Administration (R/W), Contents (R), Metadata (R), Pull requests (R/W).
   - Organization: Members (R), Administration (R/W).
3. Where can this app be installed: **Only on this account**.
4. Create. Note the **App ID**.
5. Generate a **private key** (downloads as a `.pem`). Treat it like a password.
6. Install the app on the `<your-org>` org, scoped to the repos Terraform manages (the `managed_repos` list in [`../config.md`](../config.md), e.g. `<owner/repo>`). Note the **Installation ID** from the install URL (`.../installations/<INSTALLATION_ID>`).
7. In HCP → workspace **`github-org`** → Variables → add four Terraform variables:
   - `github_owner` = `<your-org>` (not sensitive)
   - `github_app_id` = the App ID (sensitive)
   - `github_app_installation_id` = the Installation ID (sensitive)
   - `github_app_pem` = paste the **full PEM contents**, including the `-----BEGIN/END RSA PRIVATE KEY-----` lines (sensitive)

## 5. HCP Terraform API token for CI

Not currently used. The CI workflow does only fork-safe `fmt` and `validate`; HCP triggers plans and applies via its own VCS integration, not from GitHub Actions.

Set this up only if a future CI workflow needs to call the HCP API directly:

1. HCP → User settings → Tokens → Create API token, scope minimal.
2. GitHub → repo settings → Secrets → New repository secret → `TF_API_TOKEN`.

## 6. Local development

1. Install Terraform ≥ 1.9.
2. `terraform login` — opens a browser, asks HCP for a user API token. Token lands in `~/.terraform.d/credentials.tfrc.json`. The same token is what authenticates HCP API calls if you want to script anything (see [`state.md`](./state.md#api-access)).
3. From any leaf directory: `terraform init` (authenticates to HCP automatically), then `terraform plan`. A VCS-connected workspace allows `plan` from CLI but blocks `apply` — that gate is intentional.

## 7. Importing existing Cloudflare resources

See [`import.md`](./import.md) for the `cf-terraforming` runbook. It uses Cloudflare's own CLI to generate HCL and Terraform 1.5+ `import` blocks for the existing zone, DNS records, R2 buckets, and Pages projects.

## Troubleshooting

### HCP doesn't post a status check on a PR

Usually one of three things:

1. The workspace's "Automatic speculative plans" master toggle is off (see step 2).
2. The path filter excludes the PR's diff. Check Settings → Version Control → Trigger Patterns. A docs-only PR correctly produces no per-workspace check; HCP rolls up to a single SUCCESS aggregated status.
3. The workspace's VCS webhook subscription drifted. Open Settings → Version Control and click **Update VCS settings** with no changes — that re-registers the webhook with GitHub.

### GitHub Pages cert stuck at `null`

If `gh api repos/<owner>/<repo>/pages` shows `https_certificate: null` and `protected_domain_state: null` for more than ~15 min after the DNS resolves, the cert provisioning flow has wedged. Fix:

```sh
gh api -X PUT repos/$REPO/pages -f 'cname='          # remove
gh api -X PUT repos/$REPO/pages -f "cname=$DOMAIN"   # re-add
```

Removing and re-adding the custom domain re-emits the event that kicks Let's Encrypt. Cert usually issues within a few minutes after that.

### Branch protection blocks a PR with no HCP check

If a PR's diff doesn't match any workspace's path filter, HCP posts a single SUCCESS for the aggregated commit status (we tested this — it works). If it doesn't, the workspace VCS webhook is probably the issue (see above).
