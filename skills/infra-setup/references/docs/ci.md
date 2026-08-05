# CI

This repo is **public**. Anyone can fork it and open a PR. The CI workflow assumes a hostile PR body and protects every secret accordingly.

## Trust boundary

| Surface | Visibility | Holds secrets? |
|---|---|---|
| Repo source, Issues, PRs, Actions logs | Public | no |
| HCP Terraform workspaces | Private (HCP) | yes — all Terraform-time secrets |
| GitHub Actions encrypted secrets | Private (repo settings) | none today (placeholder for `TF_API_TOKEN` if needed later) |
| Speculative `terraform plan` output | Linked from PR; lives in HCP UI | redacted by HCP |

## What runs on a PR

| Job | Where it runs | Triggered for fork PRs? | Secrets in scope |
|---|---|---|---|
| `terraform fmt` | GitHub Actions | yes | none |
| `terraform validate (terraform/cloudflare)` | GitHub Actions | yes | none (`init -backend=false`) |
| `terraform validate (terraform/github)` | GitHub Actions | yes | none (`init -backend=false`) |
| HCP speculative plan per workspace | HCP Terraform via VCS integration | **only when maintainer labels `safe-to-plan`** | yes — full workspace variables |

The first three are defined in this repo's `.github/workflows/ci.yml` (not part of this folded doc set). The HCP plan is triggered by HCP's own VCS integration when it detects a push to a watched branch — not by a GitHub Actions job. There is no `TF_API_TOKEN` in use today.

## What runs on merge to `main`

- HCP creates a real run for each workspace whose path filter matches the merged commit (`terraform/cloudflare/**` for the `cloudflare` workspace, `terraform/github/**` for `github-org`).
- The run plans then **stops at "needs confirmation"** — applies require a human click in HCP UI (or an authenticated `POST /runs/<id>/actions/apply`).
- Apply logs live in HCP, not GitHub Actions.

A docs-only push to `main` triggers no workspace runs. HCP still posts an aggregated commit status (success), so branch protection treats it as a passing rollup.

## Branch protection on `main`

Enforced via this repo's `terraform/github/branch_protection.tf` (not part of this folded doc set). All four required status checks must be green before merge:

- `terraform fmt`
- `terraform validate (terraform/cloudflare)`
- `terraform validate (terraform/github)`
- `Terraform Cloud/<your-org>/repo-id-<hcp-status-check-id>` — HCP's aggregated commit status

Plus: linear history, no force-push, no branch deletion, conversation resolution required. Admins can bypass for emergencies (`enforce_admins = false`).

> ⚠️ The HCP check name embeds a per-installation VCS-repo ID (`<hcp-status-check-id>`, i.e. `$HCP_STATUS_CHECK_ID` — see [`../config.md`](../config.md)). If the GitHub–HCP OAuth/App connection is ever rebuilt, that string changes and branch protection silently blocks every PR until `terraform/github/branch_protection.tf` is updated to match.

## Rules

1. **Never use `pull_request_target`** unless the workflow is reviewed line-by-line for fork-PR safety. The default trigger is `pull_request`, which gives fork PRs no access to secrets.
2. **Never `echo` secrets**, never pass them as command-line args (visible in `ps`). Use env vars and let the tool read them.
3. **Sensitive Terraform outputs**: mark `sensitive = true`. HCP redacts these from plan output.
4. **Fork-PR plans are opt-in.** A maintainer reviews the diff, decides whether it's safe to run against the real Cloudflare/GitHub account, then applies the `safe-to-plan` label.
5. **Apply requires a human.** No automated apply, ever. (The exception during this repo's bootstrap was deliberate API-driven applies after the speculative plan had been read; see commit history.)

## What to watch for in PR diffs from forks

Before applying `safe-to-plan`, scan the diff for:

- New `local_file` / `null_resource` / `external` data sources — these can exfiltrate values during a plan.
- New providers or modules pulled from untrusted sources — they execute code during `terraform init`.
- Changes to the workflow files themselves — fork-PR workflows run from the PR branch, so a malicious workflow edit is just as dangerous as malicious Terraform.
- Anything that reads a sensitive variable and writes it somewhere observable (a resource attribute, an output, a log).

If anything looks off, decline the label and ask for changes.
