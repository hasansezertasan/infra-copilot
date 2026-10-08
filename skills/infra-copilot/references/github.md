<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:a5be3b5f918ef922c28085fc527c9614444cd476282d3e0228bab3f6a458b88d
Source-Hash: blake3:fae0c3b8a008dabb9a223be842cfe6cf3a26e36abde3911ba25a9f638ee5f96f
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

For object-storage/GitHub Actions, create a second App with only Read permissions for
plan and store `GH_APP_READ_ID`, `GH_APP_READ_INSTALLATION_ID`, `GH_APP_READ_PEM` at
repository scope. The write App's `GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `GH_APP_PEM`
belong only in the exact-main `production` environment. Remove repository copies.
For this apply App, upgrade Contents to R/W: GitHub requires it to return merge settings
on refresh. Keep the separate plan App's Contents permission Read only.
GitHub plans use `-lock=false -refresh=false`: read-only callers cannot accurately read
merge settings or ruleset bypass actors; production apply refreshes last-applied state.
See [the credential tiers and migration](docs/object-storage-ci.md#terraform-providers).

GitHub Apps support multiple active keys, so rotation is overlap-then-cutover: human
generates a new key and pastes it, verifies the execution that uses that App, then deletes
the old key. HCP or a read-App replacement can be verified by its no-op plan. An
object-storage write-App replacement requires a HUMAN-authorized production run;
a branch plan uses the separate read App and cannot validate the write key.
Steps in [`secrets.md`](docs/secrets.md#github-app-private-key).
