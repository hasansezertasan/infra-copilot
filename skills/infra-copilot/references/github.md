<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:5c8a428dc38d4a39c950b2a98fcf8810edb436ceeccd2d15861522056f412794
Source-Hash: blake3:2f24b784fafb5b8019ab593df0dfa258690e7be4f24a796e658e8413d33b6ba7
Schema-Version: v1
-->


# Provider: GitHub (agent-first)

Deep dive for [Phase 3](../../setup/SKILL.md) of the infra-copilot:setup skill. Canonical
bootstrap detail: [`setup.md#4`](docs/setup.md#4-github-app). Auth rationale + rotation:
[`secrets.md`](docs/secrets.md#github-app-setup).

## What this repo manages via GitHub

This repo's managed repos (`managed_repos` in `.infra-copilot/config.md` — e.g.
`<owner/repo>` and, if applicable, an org-Pages repo) — their settings, `main` branch
protection, and the `safe-to-plan` label — through the `integrations/github` v6
provider. State + App credentials live in the HCP `github-org` workspace.

## Why a GitHub App (not a PAT)

Apps aren't tied to a user, support fine-grained permissions, and rotate cleanly (multiple
active keys → overlap-then-cutover). A PAT dies with its owner and is coarse-grained. This
is a locked decision — see this repo's `.infra-copilot/decisions.md`.

## The actor split

| Action | Actor | Why |
|---|---|---|
| Create the App + generate private key | **HUMAN** | Browser flow; the `.pem` downloads once. |
| Install the App on the org, scoped to repos | **HUMAN** | Browser install + consent. |
| Paste App ID / installation ID / PEM into HCP | **HUMAN** | Agent must never see the PEM. |
| Verify the four vars exist | **AGENT** | HCP API. |
| Prove the App works (`plan`) | **AGENT** | Speculative plan in HCP. |
| Repo/Pages introspection (`gh api`) | **AGENT** | Read-only, agent-owned. |

## HUMAN — create, install, paste (`gh-app`)

1. Create the App: `https://github.com/organizations/<your-org>/settings/apps/new`
   (substitute your GitHub org slug — `$GITHUB_ORG`). Permissions — start narrow:
   - **Repository**: Administration (R/W), Actions (R), Contents (R), Metadata (R), Pull requests (R/W).
     Actions (R) reads environments and deployment branch policies on refresh.
   - **Organization**: Members (R/W), Administration (R/W).
     Members (R/W) is required when Terraform manages organization or team membership; read-only access
     only lets the provider inspect memberships.
   - "Where can this app be installed": **Only on this account**.
2. Create → note the **App ID**. Generate a **private key** (`.pem` downloads — treat like
   a password; include the full `-----BEGIN/END RSA PRIVATE KEY-----` lines when pasting).
3. **Install** on `<your-org>`, scoped to the repos in `managed_repos` (e.g. `<owner/repo>`
   and, if applicable, an org-Pages repo). Note the **Installation ID** from the install URL
   (`.../installations/<INSTALLATION_ID>`).
4. HCP → workspace **`github-org`** → Variables → four **Terraform** vars:
   - `github_owner` = `<your-org>` *(not sensitive)*
   - `github_app_id` *(sensitive)*
   - `github_app_installation_id` *(sensitive)*
   - `github_app_pem` = full PEM contents *(sensitive)*

> **Shortcut worth offering the human — the GitHub App manifest flow.** Instead of
> clicking every permission, the agent can generate an App *manifest* (a JSON blob of
> the permissions above) and hand the human a tiny local HTML page that POSTs it to
> `https://github.com/organizations/<your-org>/settings/apps/new`. GitHub then shows a
> single "Create GitHub App" confirmation with permissions pre-filled — trimming ~a
> dozen clicks to one. Caveat that keeps us on the manual path by default: the flow
> redirects back with a temporary `code` that must be exchanged
> (`POST /app-manifests/{code}/conversions`) within **one hour** to retrieve the App ID
> and PEM — and that exchange hands the **PEM to whoever runs it**. Letting the agent do
> the exchange would break the never-see-the-plaintext rule, so if you use the manifest
> flow, the *human* performs the code exchange. Details:
> <https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest>.
> Installation + Installation-ID capture is a browser step either way.

## AGENT — verify

### Versioned App manifests

For object-storage leaves, copy
[`templates/apps/terraform-plan.json`](templates/apps/terraform-plan.json) and
[`templates/apps/terraform-apply.json`](templates/apps/terraform-apply.json) into the
consuming repository's `.github/apps/`. These are provider Apps: plan is read-only, apply
can manage repository settings and organization memberships. Adapt permissions to the
actual resources and installation scope, give each App a unique name, and replace the
example homepage and callback URLs with human-controlled URLs. Permission edits require
a live App-settings update and, where GitHub requires it, installation-owner approval;
committing JSON alone does not change an installed App.

The HUMAN submits each JSON as the `manifest` form field to the organization App creation
URL described above, then exchanges the returned one-hour code and stores the resulting
PEM privately. Never commit the conversion response or ask an agent to perform the
exchange. Keep the committed manifest synchronized with approved live permissions so
drift can be reviewed and the App recreated. Store plan credentials in repository secrets
and apply credentials in the protected `production` environment; see
[Actions provider authentication](docs/object-storage-ci.md#terraform-providers).
After reviewing the distinct public App IDs, live permissions, and secret stores,
record those IDs plus strict UTC `reviewed_at` under `github_apps` in the consuming config
and commit it. Missing evidence or a secret update newer than that review keeps the
handoff incomplete. Re-review when live permissions change; metadata cannot prove
permissions or reveal which PEM was installed.
Commit both customized manifest copies and record their `git hash-object` values as
`plan_manifest_blob` and `apply_manifest_blob` in the same review record. Missing,
uncommitted, or changed manifests invalidate the handoff until reviewed again.

### HCP variable verification

```sh
HCP_TOKEN=${TF_TOKEN_app_terraform_io:-$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)}
WS_ID=$(curl -sf "https://app.terraform.io/api/v2/organizations/$ORG/workspaces/github-org" \
  -H "Authorization: Bearer $HCP_TOKEN" | jq -r '.data.id')

curl -sf "https://app.terraform.io/api/v2/workspaces/$WS_ID/vars" \
  -H "Authorization: Bearer $HCP_TOKEN" | jq -e '
    [.data[].attributes.key] as $k
    | ("github_owner"|IN($k[])) and ("github_app_id"|IN($k[]))
      and ("github_app_installation_id"|IN($k[])) and ("github_app_pem"|IN($k[]))' \
  && echo "✓ all four github vars present"

cd terraform/github && terraform init && terraform plan   # green = App auth works
```

## Watch-outs the agent should flag

- **PEM newline mangling** on paste is the most common failure — it works for the first
  request then breaks on rotation. If `plan` fails with an auth error, re-paste the PEM
  carefully (full BEGIN/END lines).
- **The branch-protection status-check name embeds a per-installation VCS ID**
  (`Terraform Cloud/<your-org>/<hcp-status-check-id>`, i.e. `$HCP_STATUS_CHECK_ID`). If the
  GitHub↔HCP OAuth connection is ever rebuilt, that string changes and **every PR is
  silently blocked** until `terraform/github/branch_protection.tf` is updated. See
  [`hcp-ci.md`](docs/hcp-ci.md#hcp-status-check-context).
- **Pages cert can wedge** (`https_certificate: null` for >15 min). Fix by removing +
  re-adding the custom domain via `gh api` — see [`setup.md`](docs/setup.md#github-pages-cert-stuck-at-null).

## Rotation

GitHub Apps support multiple active keys, so rotation is overlap-then-cutover: human
generates a new key + pastes it, agent proves it with a no-op `plan`, then human deletes
the old key. Steps in [`secrets.md`](docs/secrets.md#github-app-private-key).
