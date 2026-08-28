<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:43dfe6626e0d4cf591e126b9baf3758bce1094062cf6c14a3be8c4ef72bceccd
Source-Hash: blake3:6def8ee868d1c22d06efeb02c42e5cf1f6daaf5cfabff189382ed8e95e796258
Schema-Version: v1
-->


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

The first three are defined in this repo's `.github/workflows/ci.yml` (not part of this folded doc set).

## Toolchain in CI

Those three jobs must run the **same** Terraform the repository pins, or the parity the
toolchain decision claims is only true locally. `mise.toml` and `mise.lock` are committed
precisely so CI can reproduce the pin, so install from them before any `terraform` step:

```yaml
- uses: jdx/mise-action@c2a87611a18de5b3828c5652fe268e992400cb5c # v4.3.0
```

The action installs mise, runs `mise install`, and — per its own `install_args`
documentation — **adds `--locked` automatically when a repo lockfile is present**, so CI
resolves from `mise.lock` rather than picking its own version. It also puts the mise shims
directory on `PATH` (`add_shims_to_path`, on by default), so the later `terraform fmt` and
`terraform validate` steps get the pinned binary without further wiring.

Do **not** substitute `hashicorp/setup-terraform` with its own `terraform_version`: that is
a second, independently chosen version, which is exactly the drift the pin exists to stop.
Bumping Terraform then means editing `mise.toml`, `mise.lock`, and both HCP workspaces —
and CI follows automatically instead of being a fourth place to remember.

Unlike local setup, the bare `mise install` this action runs is safe here: the leak that
form has locally is user-level config bleeding into the request, and a fresh runner has
none. If your workflow reuses a self-hosted runner with a user-level mise config, pass
`install_args` naming this repo's tools instead.
 The HCP plan is triggered by HCP's own VCS integration when it detects a push to a watched branch — not by a GitHub Actions job. There is no `TF_API_TOKEN` in use today.

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

### HCP status check context

> ⚠️ The HCP check name embeds a per-installation VCS-repo ID (`<hcp-status-check-id>`, i.e. `$HCP_STATUS_CHECK_ID` — see [`../config.md`](../config.md)). If the GitHub–HCP OAuth/App connection is ever rebuilt, that string changes and branch protection silently blocks every PR until `terraform/github/branch_protection.tf` is updated to match.

This has happened. A second OAuth client was created; HCP publishes one aggregated status per repo, so PR reporting moved to the newer connection, the `repo-id` changed, and every subsequent PR stalled on `Expected — Waiting for status to be reported`. Nothing went red — the required context simply never arrived. One PR was merged anyway through the `enforce_admins = false` bypass, which is the dangerous part: bypassing is the natural reaction to a check that never comes.

The warning above did not prevent it, because prose cannot. The `status-check-context` step in [`../steps.yaml`](../steps.yaml) now asserts it: every required `Terraform Cloud/…` context must appear among the contexts HCP actually posted on a recent commit.

```sh
sh "$INFRA_COPILOT_REFERENCES/checks/status-check-context.sh"
```

**Read the replacement context out of that output** rather than picking a commit yourself.
Choosing the right commit is the hard part — the check gathers statuses across open PR
heads, recent commits and local `HEAD`, then selects the one with the newest `updated_at`,
because an older commit can still carry the pre-reconnection context. Its `BLOCKED`
message names both sides:

```text
BLOCKED: required but not published by the current connection
  (newest status at 2026-08-27T09:14:02Z publishes: Terraform Cloud/acme/repo-id-4711):
  Terraform Cloud/acme/repo-id-2100
```

The context in parentheses is what HCP publishes now — the string to put in
`branch_protection.tf`. The one after the colon is the stale entry to remove.

It is a string comparison, not a timing heuristic. If no recent commit carries any
`Terraform Cloud/` status the check passes rather than failing — there is nothing to
compare against, and a repo whose leaves are simply idle is not broken.

**When it goes red**, read the published string from the second command and in
`terraform/github/branch_protection.tf` replace **only** the stale `Terraform Cloud/…`
entry with it. Keep `terraform fmt` and both `terraform validate` contexts listed above
exactly as they are — replacing the whole list would drop them and allow merges with no CI
at all. Do not invent the ID; HCP regenerates it.

#### Break-glass: the fix cannot merge through the normal path

The stale required context blocks **every** PR — including the one carrying the
`branch_protection.tf` correction. And per [What runs on merge to `main`](#what-runs-on-merge-to-main),
the HCP run that actually applies that file is only created *after* the merge, and then
waits for a human confirmation. So editing the file is necessary but not sufficient: the
normal workflow cannot deliver it.

Pick one, and record which in `.infra-copilot/decisions.md`:

**A — Relax protection out of band, then reconcile immediately (preferred).**

1. Remove the stale context from the required list — GitHub UI, or the dedicated
   endpoint, which takes only the status-check settings rather than the whole protection
   object. **Send the full list you want to keep**, since the field is replaced wholesale:

   ```sh
   gh api -X PATCH \
     "repos/$REPO/branches/main/protection/required_status_checks" \
     -F strict=true \
     -f 'contexts[]=terraform fmt' \
     -f 'contexts[]=terraform validate (terraform/cloudflare)' \
     -f 'contexts[]=terraform validate (terraform/github)'
   ```

   That is the documented list minus the stale HCP context. Keep the other three: dropping
   them would let merges through with no CI at all.
2. Merge the `branch_protection.tf` PR through the now-unblocked normal flow.
3. Confirm the HCP apply, then re-run the `status-check-context` check. The applied
   Terraform is what restores the intended protection — out-of-band state is temporary and
   must not be left as the source of truth.

**B — Reviewed admin bypass.**

Merge the correction using the `enforce_admins = false` bypass, then confirm the HCP apply.
Faster, but it merges code no required check verified, so a second reviewer should read the
diff first. Prefer A unless protection cannot be edited.

Either way the window between steps is one where `main` is less protected than intended.
Keep it short, and do not batch unrelated changes into the unblocking PR.

## Rules

1. **Never use `pull_request_target`** unless the workflow is reviewed line-by-line for fork-PR safety. The default trigger is `pull_request`, which gives fork PRs no access to secrets.
2. **Never `echo` secrets**, never pass them as command-line args (visible in `ps`). Use env vars and let the tool read them.
3. **Sensitive Terraform outputs**: mark `sensitive = true`. HCP redacts these from plan output.
4. **Fork-PR plans are opt-in.** A maintainer reviews the diff, decides whether it's safe to run against the real Cloudflare/GitHub account, then applies the `safe-to-plan` label.
5. **Apply requires a human.** No automated apply, ever. (A deliberate exception: API-driven applies performed only after the speculative plan has been read.)

## What to watch for in PR diffs from forks

Before applying `safe-to-plan`, scan the diff for:

- New `local_file` / `null_resource` / `external` data sources — these can exfiltrate values during a plan.
- New providers or modules pulled from untrusted sources — they execute code during `terraform init`.
- Changes to the workflow files themselves — fork-PR workflows run from the PR branch, so a malicious workflow edit is just as dangerous as malicious Terraform.
- Anything that reads a sensitive variable and writes it somewhere observable (a resource attribute, an output, a log).

If anything looks off, decline the label and ask for changes.
