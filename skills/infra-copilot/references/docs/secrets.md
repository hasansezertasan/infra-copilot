<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:b22f8d640f99a742030be95e7b6aaba7eaf7b52de9e33e64c3806f4d784f9190
Source-Hash: blake3:12b3d3a72035a2f80cbef94c4a717cd26053ba55cd9fe7fcb436614d93955148
Schema-Version: v1
-->


# Secrets

This repo is **public**. Plaintext secrets must never be committed — not in code, not in CI logs, not in `terraform plan` output. A secret that lands in git history is compromised forever; rotation is the only fix.

## Where secrets live

| Secret | Store | Consumed by |
|---|---|---|
| Cloudflare API token | HCP Terraform workspace variable on `cloudflare`, marked sensitive | `terraform` runs in HCP |
| GitHub App ID, installation ID, private key (PEM) | HCP Terraform workspace variables on `github-org`, marked sensitive | `terraform` runs in HCP |
| HCP Terraform user API token | `~/.terraform.d/credentials.tfrc.json` (set by `terraform login`), per maintainer | local Terraform CLI; scripted HCP API calls |

**Nothing encrypted is committed to the repo.** No SOPS, no `git-crypt`. If we ever run our own hosts and need runtime secrets, we pick an out-of-band store then; until that day, all secrets in scope live in HCP workspace variables.

## Why HCP Terraform as the vault

- Workspace variables marked `sensitive` are encrypted at rest and redacted from run logs.
- Runs execute on HCP infrastructure; sensitive values are injected into the run environment, never echoed back to the laptop or to GitHub Actions logs.
- One place to rotate Terraform-time credentials.
- HCP's own state encryption covers everything Terraform writes during a run.

## Cloudflare API token scopes

The token loaded into the `cloudflare` workspace needs **Edit** on every kind of resource we manage. For the current set:

- Zone — DNS — Edit
- Zone — Zone Settings — Edit

If/when we add more resource types, add scope before declaring the resource. For one-shot discovery via [`import.md`](./import.md), a separate token with **Read** scopes works fine — the user generates it locally, uses it to populate `generated.tf`, then deletes it. The persistent HCP token only needs the scopes that match the resources Terraform actively manages.

## GitHub App setup

The GitHub provider authenticates as a GitHub App, not a PAT. Apps are not tied to a user, support fine-grained permissions, and rotate cleanly.

1. Create the app under the `<your-org>` org (Settings → Developer settings → GitHub Apps → New).
2. Permissions: Repository — Administration (read/write), Contents (read), Metadata (read), Pull requests (read/write). Organization — Members (read), Administration (read/write).
3. Install the app on the org, scoped to the repos Terraform manages (the `managed_repos` list in [`../config.md`](../config.md), currently e.g. `<owner/repo>`).
4. Generate a private key, store the **App ID**, **installation ID**, and **PEM** in the `github-org` HCP workspace as three sensitive variables (`github_app_id`, `github_app_installation_id`, `github_app_pem`).
5. The PEM must include the full `-----BEGIN/END RSA PRIVATE KEY-----` lines. Pasting just the base64 body works for the first request, then breaks on key rotation.

## Rotation

Rotate yearly or on any suspected exposure. The procedures below are zero-downtime — the new credential is in place and exercised before the old one is revoked.

### Cloudflare API token

1. <https://dash.cloudflare.com/profile/api-tokens> → **Create Token** → duplicate the scopes of the existing token.
2. Copy the new value.
3. HCP → workspace `cloudflare` → Variables → `cloudflare_api_token` → click the edit icon → paste new value → Save.
4. Trigger a no-op plan to confirm the new token works:
   ```sh
   cd terraform/cloudflare
   terraform plan        # expect: no changes; speculative plan in HCP authenticates with the new token
   ```
5. If the plan succeeds, return to the dashboard and **revoke the old token**.
6. If the plan fails, paste the old value back into the HCP variable; the old token is still live. Investigate.

### GitHub App private key

GitHub Apps support multiple active private keys, so rotation is overlap-then-cutover.

1. GitHub → org Settings → Developer settings → GitHub Apps → your app → **Private keys → Generate a private key**. A `.pem` downloads. Both old and new keys are now active.
2. HCP → workspace `github-org` → Variables → `github_app_pem` → paste the full new PEM contents (including `-----BEGIN/END-----` lines) → Save.
3. Trigger a no-op plan to confirm:
   ```sh
   cd terraform/github
   terraform plan
   ```
4. If the plan succeeds, return to the GitHub App's Private keys page and **delete the old key**.
5. If the plan fails — likely PEM newline mangling on paste — paste again carefully and retry.

### HCP API token (user or team)

- **User token**: each maintainer regenerates via `terraform login` after the previous token is revoked. Coordinate so the local CLI keeps working.
- **Team token** (`infra-meta-bot` or similar, when HCP-as-code arc lands): HCP UI → org Settings → Teams → token regenerate. Paste the new value into the meta-workspace's `TFE_TOKEN` env var.

In both cases: generate the new one *first*, paste it in, verify by triggering a plan against any workspace, then revoke the old.

### When NOT to rotate

- Routine "I forgot when I last rotated" — schedule a yearly calendar reminder, but don't rotate ad-hoc just to feel busy. Each rotation is a chance for a typo or PEM mangling to wedge a workspace.
- On a maintainer leaving — only rotate credentials they actually had access to. The HCP API token they used dies when their HCP user is removed; the underlying Cloudflare / GitHub App credentials aren't tied to a specific maintainer and don't need rotating unless they were ever exposed to that maintainer's local environment.

## Things that look like secrets but aren't

- Cloudflare account ID, zone ID — not secret, but reconnaissance signal. Fine to commit. Both live as `local`s in `terraform/cloudflare/main.tf`.
- GitHub org / repo names, GitHub App ID, installation ID — public anyway. App ID and installation ID are *marked* sensitive in the HCP variables for defense-in-depth, but they're not credentials.
- Resource IDs in Terraform state — state itself lives in HCP, never in the repo.
- The HCP organization name, workspace names — non-secret identifiers.
