# Provider: GitHub (agent-first)

Deep dive for [Phase 3](../SKILL.md#phase-3--github) of the infra-setup skill. Canonical
bootstrap detail: [`setup.md#4`](../../../../docs/setup.md#4-github-app). Auth rationale + rotation:
[`secrets.md`](../../../../docs/secrets.md#github-app-setup).

## What this repo manages via GitHub

`perishdev/infra` and `perishdev/perishdev.github.io` repo settings, `main` branch
protection on both, and the `safe-to-plan` label — through the `integrations/github` v6
provider. State + App credentials live in the HCP `github-org` workspace.

## Why a GitHub App (not a PAT)

Apps aren't tied to a user, support fine-grained permissions, and rotate cleanly (multiple
active keys → overlap-then-cutover). A PAT dies with its owner and is coarse-grained. This
is a [locked decision](../../../../CLAUDE.md).

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

1. Create the App: `https://github.com/organizations/perishdev/settings/apps/new`
   (replace `perishdev` if the org slug differs). Permissions — start narrow:
   - **Repository**: Administration (R/W), Contents (R), Metadata (R), Pull requests (R/W).
   - **Organization**: Members (R), Administration (R/W).
   - "Where can this app be installed": **Only on this account**.
2. Create → note the **App ID**. Generate a **private key** (`.pem` downloads — treat like
   a password; include the full `-----BEGIN/END RSA PRIVATE KEY-----` lines when pasting).
3. **Install** on `perishdev`, scoped to `perishdev/infra` +
   `perishdev/perishdev.github.io`. Note the **Installation ID** from the install URL
   (`.../installations/<INSTALLATION_ID>`).
4. HCP → workspace **`github-org`** → Variables → four **Terraform** vars:
   - `github_owner` = `perishdev` *(not sensitive)*
   - `github_app_id` *(sensitive)*
   - `github_app_installation_id` *(sensitive)*
   - `github_app_pem` = full PEM contents *(sensitive)*

> **Shortcut worth offering the human — the GitHub App manifest flow.** Instead of
> clicking every permission, the agent can generate an App *manifest* (a JSON blob of
> the permissions above) and hand the human a tiny local HTML page that POSTs it to
> `https://github.com/organizations/perishdev/settings/apps/new`. GitHub then shows a
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
HCP_TOKEN=$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)
WS_ID=$(curl -sf "https://app.terraform.io/api/v2/organizations/perishdev/workspaces/github-org" \
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
  (`Terraform Cloud/perishdev/repo-id-CffUfWW6H1x6Bauq`). If the GitHub↔HCP OAuth
  connection is ever rebuilt, that string changes and **every PR is silently blocked**
  until `terraform/github/branch_protection.tf` is updated. See [`ci.md`](../../../../docs/ci.md).
- **Pages cert can wedge** (`https_certificate: null` for >15 min). Fix by removing +
  re-adding the custom domain via `gh api` — see [`setup.md`](../../../../docs/setup.md#github-pages-cert-stuck-at-null).

## Rotation

GitHub Apps support multiple active keys, so rotation is overlap-then-cutover: human
generates a new key + pastes it, agent proves it with a no-op `plan`, then human deletes
the old key. Steps in [`secrets.md`](../../../../docs/secrets.md#github-app-private-key).
