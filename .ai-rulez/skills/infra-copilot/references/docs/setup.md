
# Setup

One-time, out-of-band steps to wire up the systems this repo manages. The Terraform code is speculative until these are done.

Run in order. Each step explains what it produces and where the value goes.

## 1. HCP Terraform — organization

1. Sign up at <https://app.terraform.io/> if needed (free tier is sufficient to start).
2. Run `terraform login` and approve the browser flow so the agent can verify every
   subsequent HCP step through the API.
3. Create an organization matching your `hcp_org` value (see [`../config.md`](../config.md)) — it must match the `organization` field in every `terraform/*/versions.tf`.
4. Inside the org, create a project named **`infra`**.

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
- **Terraform Version**: the exact `tools.terraform` value in the committed `mise.toml`.
  The setup workflow sets and verifies this through the API; do not leave it on latest.

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

1. **Pin the toolchain, review it, lock it, then install it.** Tool versions belong in
   the repo, not in user/global configuration. The setup workflow reads this exact file:

   ```toml
   # mise.toml
   [tools]
   terraform = "1.15.9"   # examples — use exact versions, never "latest" or a prefix
   gh = "2.81.0"
   jq = "1.8.1"
   ```

   ```sh
   cat -- mise.toml            # inspect the entire repository config before trusting it
   mise trust mise.toml
   touch mise.lock             # older mise releases only update an existing lockfile
   mise lock                   # populate/update it for common platforms
   # Install exactly what this repository pins. The bare `mise install` would also
   # pull in tools from your user-level config, and fail the locked install if any
   # of those are absent from *this* repo's lockfile.
   pinned=$(mise config get --file ./mise.toml tools |
     sed -n 's/^[[:space:]]*"\{0,1\}\([^"=[:space:]]*\)"\{0,1\}[[:space:]]*=.*/\1/p')
   MISE_LOCKED=1 mise install $pinned
   eval "$(mise activate bash)"   # or zsh/fish — install alone does not touch PATH
   ```

   Installing is not activating. `mise install --help` states plainly that
   "Installing alone will not activate the tools so they won't be in PATH", so a shell
   without the mise hook downloads the pinned toolchain and then keeps resolving
   `terraform` to whatever the system had — or to nothing. The pin is only enforced for
   commands that actually run the pinned binary, and every later command here plus every
   `check` in [`../steps.yaml`](../steps.yaml) invokes a bare binary. Confirm it took:

   ```sh
   command -v terraform && terraform version   # must resolve inside the mise install dir
   ```

   If you would rather not activate the shell, prefix each command instead —
   `mise exec -- terraform login`, `mise exec -- terraform version` — and run the
   preflight checks the same way.

   Review matters because trusting a repository config enables its templates, plugins,
   and other executable behavior. Review the whole file, regardless of its length.
   Initializing the empty lockfile makes `mise lock` write it even on releases that only
   print a proposed lock when no file exists. `mise lock` is the supported update command;
   `MISE_LOCKED=1` makes installation fail instead of resolving missing URLs outside the
   committed lock. Commit both files. The default workflow requires these two files so it
   can enforce one unambiguous pin source. Record the choice in
   [`../decisions.md.example`](../decisions.md.example). A repo standardizing on Nix,
   asdf, Devbox, or a container must replace the manifest's `pin` and `check` entries with
   checks that read that manager's committed file; active-environment commands are not a
   substitute for inspecting the repository pin.

   Do all of this — including the activation — **before** step 3: `terraform login`
   needs the pinned `terraform` on `PATH`, and installing without activating does not
   put it there.

2. **Verify the same Terraform version on every HCP workspace.** The Phase 1 API flow
   reads `tools.terraform` from the repository's `mise.toml`, sets `terraform-version`
   during workspace creation, reconciles existing workspaces, and checks the value on
   every resume scan. A workspace left on latest diverges on HashiCorp's next release.
   Bump `mise.toml`, `mise.lock`, and both remote workspaces as one change.

   Not every tool has an equally good pin. Worth knowing before you write `mise.toml`:

   | Tool | `mise.toml` key | mise backend | Caveat |
   |---|---|---|---|
   | `terraform` | `terraform` | `aqua:hashicorp/terraform` | First-class, checksummed |
   | `gcloud` | `gcloud` | `vfox:mise-plugins/vfox-gcloud` | Locks URLs, no checksums. Version parity, not artifact identity |
   | `cf-terraforming` | `"github:cloudflare/cf-terraforming"` | `github:cloudflare/cf-terraforming` | Absent from the registry, so the backend *is* the key |

   The backend column is informational. Write the key from the middle column: registry
   aliases such as `gcloud` resolve to their backend on their own, and the manifest's
   `pin` lookups read those short keys. Only a tool missing from the registry —
   `cf-terraforming` — needs its backend spelled out as the key.

3. If the Phase 0 token is absent or expired, re-run `terraform login`. It opens a browser
   and writes the user API token to `~/.terraform.d/credentials.tfrc.json`. The same token
   authenticates HCP API calls (see [`state.md`](./state.md#api-access)).
4. From any leaf directory: `terraform init` (authenticates to HCP automatically), then `terraform plan`. A VCS-connected workspace allows `plan` from CLI but blocks `apply` — that gate is intentional.

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
