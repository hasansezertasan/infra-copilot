<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:2dfc2abbd17db2824d12a12b1a74ee0c6d2864f39b0d55bf73fa0be28f2b1fa2
Source-Hash: blake3:42c7574fde1dc55e8f96bd54590bf4f29122805f262a3a990b60d7f7f4763ae5
Schema-Version: v1
-->


# Importing existing Cloudflare resources

Use Cloudflare's own [`cf-terraforming`](https://github.com/cloudflare/cf-terraforming) CLI to bring resources that already exist in the `<apex-domain>` zone (and the parent Cloudflare account) under Terraform management without recreating them.

Why not a custom script: cf-terraforming is maintained by Cloudflare alongside the Terraform provider, so import ID formats and HCL schemas track provider changes automatically. A hand-rolled script would drift.

## Adopt the Template first

A repo with no committed `.copier-answers.yml` and no README Config block pre-dates the
[`copier-infra`](https://github.com/hasansezertasan/copier-infra) Template. That includes
every repo made from the former `infra-template` GitHub template. `infra-skills:infra-import`
adopts the Template before any import (the `template-adopt` step), so the Config block exists
and a later `copier update` has an answers file to merge from. A human reviews every
conflicting file; nothing the repo already has is overwritten silently.

1. **Legacy state first.** A repo made from `infra-template` may carry `.infra-copilot/` or
   `.claude/infra-copilot.local.md`. Those are unsupported and the skill stops before this
   step, without reading them ([config.md](../config.md#unsupported-legacy-state)). You move
   the values you want to keep (orgs, apex domain, account and zone IDs, managed repos) out of
   it yourself, delete it in its own reviewed commit and restart. Those values are the answers
   to the Template's questions below.
2. **Render into a scratch directory, never into the repo.** First collect every answer the
   way `template-render` does: clone the Template at its newest release tag, read its
   `copier.yml`, evaluate each question's `when` in file order, and ask the human each active
   question, validated against its `validator`. Answer from the repo's actual state, not the
   Template's defaults: `backend` is explicit and must match where the state really lives, as
   must the state bucket and identifiers. Then render with the pinned Copier, passing every
   answer with `--data` (`--defaults` only fills questions that were not active):

   ```sh
   scratch=$(mktemp -d)
   uv run --no-project --with-requirements "$INFRA_REFERENCES/copier-requirements.txt" \
     copier copy --vcs-ref <tag> --defaults --data key=value \
     gh:hasansezertasan/copier-infra "$scratch"
   ```

   Keep `$scratch`: the steps below read it.

   `copier copy` straight into the repo is the wrong move. With no terminal it stops at the
   first conflicting file, after writing the files before it and before writing the answers
   file; with `--overwrite` it replaces your files. Both leave the repo half-adopted.
3. **Reconcile** the scratch render into the repo, file by file. Absent in the repo: copy it.
   Identical: skip it. Different: show the human the diff and take their choice, as a
   conflict. `README.md` is always a conflict: show the human the diff before writing it,
   take the Template's Config block and Decisions table, and keep their prose around them.
   `mise.toml` and `mise.lock` are conflicts too, even when the repo has none: executable
   tool config is never copied in unreviewed, so show the human both files.
   Then compare the whole scratch render with the repo (`diff -rq -x .git -x .copier-answers.yml "$scratch" .`; the
   answers file is copied last, in step 4): every file the render has must now exist in the repo, or be a difference the
   human chose to keep. The check cannot do this later, because the scratch render is gone.
4. **Copy `.copier-answers.yml` last** and read its `_src_path`: it must be
   `gh:hasansezertasan/copier-infra`. A local checkout used as the source records its own
   path, which `template-contract` rejects. Run `mise trust --untrust` in the repo, which
   revokes any earlier trust of that path so a changed `mise.toml` is never trusted by
   accident, then commit the adoption **on a branch that does not apply**, never on the
   branch a push applies from: the reconciled `terraform/` files can change what an apply does.
5. **Check the contract, then the pins.** Run `template-contract`: the recorded `_commit` must
   be a release tag at or above the minimum. An older tag proposes `copier update`. Then run
   `toolchain-pin`, the human's review of the adopted `mise.toml` and `mise.lock`, before any
   pin-dependent preflight.
6. **Plan before merging, and before importing.** Adoption can change `terraform/` files the
   human accepted from the Template. Obtain the plan on the adoption branch and have the human
   review it before the branch merges or anything else can trigger an apply. The resource
   import below runs exactly as before.

Later, `copier update` three-way merges against the recorded `_commit`, so every file the
human kept differently shows as their change rather than being overwritten.

### Fixture run (2026-10-19)

Exercised once on a fixture repo (a hand-written `README.md`, `mise.toml` and
`terraform/cloudflare/versions.tf`, no answers file) with Copier 9.19.1 and Template `v0.1.0`:

- A direct `copier copy` into the fixture, with no terminal, stopped at the conflicting
  `versions.tf` with "Interactive session required". It had already written
  `backend.tf` and `main.tf`, left the answers file unwritten and exited 0.
- Rendering into a scratch directory from `gh:hasansezertasan/copier-infra` recorded
  `_src_path: gh:hasansezertasan/copier-infra` and `_commit: v0.1.0`. The same render from a
  local checkout recorded the local path instead, which `template-contract` rejects.
- Reconciling gave three conflicts (plus `mise.lock` and the rest, which were absent and so
  copied in; the run did not yet treat those as reviewable): `README.md`, `mise.toml` and `versions.tf`. Taking the
  Template's `README.md` Config block and `versions.tf` and keeping the human's `mise.toml`,
  then committing, turned `template-adopt` and `template-contract` green.
- `copier update` then ran on the adopted repo and kept `v0.1.0`.

## Discovery token

Before you run cf-terraforming, generate a separate, short-lived Cloudflare token with **Read** scopes on every resource type you're discovering. Don't reuse the persistent execution token (which has Edit scopes — broader than discovery needs).

1. <https://dash.cloudflare.com/profile/api-tokens> → **Create Token** → **Custom token**.
2. Permissions: pick **Read** on each resource type you're about to discover. Examples:
   - Zone — DNS — Read
   - Zone — Email Routing Rules — Read
   - Account — Email Routing Addresses — Read
3. **Account Resources**: Include — your account. **Zone Resources**: Include — Specific zone — `<apex-domain>`.
4. **TTL**: set to a day or a few hours. This is throwaway.
5. **Continue to summary** → **Create token** → copy the value (shown once).
6. Park it on your laptop until the run is done:

   ```sh
   read -s "?Paste Cloudflare discovery token: " CF_TOK
   echo
   echo "$CF_TOK" > /tmp/cf_token
   chmod 600 /tmp/cf_token
   unset CF_TOK
   ```

7. After cf-terraforming finishes: `rm /tmp/cf_token`, and revoke the token in the dashboard.

## Install

```sh
# Pin it. The support matrix below is version-specific, so an unpinned install
# documents one tool and runs another. cf-terraforming is not in mise's registry,
# so name the backend explicitly.
#
# Write the pin first, without installing: `mise use` installs as it writes, which
# would resolve the binary before the lock covering it exists. Add this line to the
# committed [tools] table by editing the file:
#
#     "github:cloudflare/cf-terraforming" = "0.30.0"
#
# Then lock it, and only then install from that lock:
touch mise.lock
mise lock                    # resolves the new pin into mise.lock
MISE_LOCKED=1 mise install "github:cloudflare/cf-terraforming"
git add mise.toml mise.lock  # commit the tool pin and refreshed lock together

# Installing does not activate. This pin is added after setup's activation, so the
# new binary is not on PATH yet — and an older system cf-terraforming would shadow
# it if it were. Refresh the environment, or run the commands below via `mise exec`:
eval "$(mise activate bash)"
mise exec -- cf-terraforming --version   # must report 0.30.0, not a system build

# or via the Go toolchain — an explicit tag, never @latest:
go install github.com/cloudflare/cf-terraforming/cmd/cf-terraforming@v0.30.0
```

> `0.30.0` is the version the matrix below was audited against. Newer releases exist;
> bump the pin and re-check the matrix in the same change, so the documented coverage and
> the installed binary never disagree. When you re-check a row, the authority is
> `internal/app/cf-terraforming/cmd/resource_to_endpoint_mapping.go` in the upstream tree,
> not the README: `generate` skips a resource only when that file gives it neither a `list`
> nor a `get` endpoint, and the README's v5 tables omit resources the file does map. That
> is how the route row here came to be wrong.

## What it supports

Coverage is **broad but not total** for the v5 provider. As of cf-terraforming v0.30 (October 2026):

The two questions are separate, and an earlier version of this table ran them together:
whether the tool *can* emit a resource is a fact about cf-terraforming, whereas whether it
belongs in this repo is our recommendation. Read the columns independently.

| Resource | `generate` emits it | Import it here |
|---|---|---|
| `cloudflare_dns_record` | yes | yes |
| `cloudflare_r2_bucket` | yes | yes |
| `cloudflare_pages_project` | yes | yes |
| `cloudflare_workers_kv_namespace` | yes | yes |
| `cloudflare_workers_custom_domain` | yes | yes |
| `cloudflare_workers_cron_trigger` | yes (needs `--resource-id`) | yes |
| `cloudflare_workers_script` | **no** — unmapped, so `generate` logs `Unsupported terraform v5 provider resource` and skips it | no |
| `cloudflare_workers_route` | yes (zone-scoped) | **no** — by choice, not because the tool cannot |
| Zone settings (`cloudflare_zone_setting`) | yes (needs `--resource-id` listing each setting) | yes |

For the script and route rows: Worker code typically lives in the app repo it serves, not in this infra repo. Importing the script here would tie its state to an empty `content` field, and a route whose script is absent from the same state is worse than no route at all. Define both in the app's own Terraform once that app exists — for the route that is our choice rather than a limit, so if your Workers code does live in this repo, importing it is fine.

## Generate HCL for the zone

```sh
export CLOUDFLARE_API_TOKEN=...        # token with read scopes for each resource type
export CLOUDFLARE_ZONE_ID=$CF_ZONE_ID
export CLOUDFLARE_ACCOUNT_ID=$CF_ACCOUNT_ID

cd terraform/cloudflare

terraform init -backend=false          # cf-terraforming requires an initialised dir

# Zone-scoped resources (DNS records) — --account and --zone are mutually exclusive.
mise exec -- cf-terraforming generate \
  --terraform-binary-path "$(mise which terraform)" \
  --resource-type "cloudflare_dns_record" \
  --zone "$CLOUDFLARE_ZONE_ID" \
  > generated.tf

# Account-scoped resources.
mise exec -- cf-terraforming generate \
  --terraform-binary-path "$(mise which terraform)" \
  --resource-type "cloudflare_r2_bucket,cloudflare_pages_project,cloudflare_workers_kv_namespace" \
  --account "$CLOUDFLARE_ACCOUNT_ID" \
  >> generated.tf
```

Without `--terraform-binary-path`, cf-terraforming downloads its own terraform binary into the current directory. The flag points it at the pinned one instead. `mise which terraform` is used rather than `which terraform` because the outer shell evaluates that substitution before `mise exec` runs, so an unactivated shell would hand over a system binary — or nothing.

`generated.tf` is the file the existing comment in `main.tf` references. Review it: rename resource labels to something readable (cf-terraforming uses `terraform_managed_resource` placeholders), drop anything you don't actually want managed, and commit.

## Emit `import` blocks

```sh
mise exec -- cf-terraforming import \
  --modern-import-block \
  --terraform-binary-path "$(mise which terraform)" \
  --resource-type "cloudflare_dns_record" \
  --zone "$CLOUDFLARE_ZONE_ID" \
  >> generated.tf

mise exec -- cf-terraforming import \
  --modern-import-block \
  --terraform-binary-path "$(mise which terraform)" \
  --resource-type "cloudflare_r2_bucket,cloudflare_pages_project,cloudflare_workers_kv_namespace" \
  --account "$CLOUDFLARE_ACCOUNT_ID" \
  >> generated.tf
```

`--modern-import-block` emits Terraform 1.5+ `import { to = ... id = "..." }` blocks rather than the legacy CLI commands. Append to the same file so resources and their imports stay co-located.

## Verify

```sh
terraform fmt generated.tf
terraform validate
# Obtain the plan through the get-plan operation: imports, never creates.
```

Use [import-resources](../operations.md#import-resources) and
[get-plan](../operations.md#get-plan) for execution and evidence. Commit the reviewed HCL
before accepting plan evidence; a local working tree is not evidence for the committed revision.
A create for an existing object means its address or import ID is wrong. Fix it before
opening a PR. Confirm the approved apply with
[read-run-status](../operations.md#read-run-status) before removing any import blocks.

## When to re-run

Re-run `cf-terraforming generate` whenever new resources appear in Cloudflare that you want Terraform to manage. The cleanest workflow is to write new resources directly in Terraform from the start; cf-terraforming is for one-time onboarding of legacy state, not steady-state operations.

The `import {}` blocks it emits are one-shot in the same way: after the run that applies them, they are inert instructions sitting in the leaf. Removing them is a separate PR with its own preconditions — [`prune.md`](prune.md), the `infra-skills:infra-prune` skill. Do not fold it into the import PR; the apply has to land first.

> Note: cf-terraforming is **not** intended for use in CI. It runs locally during onboarding, output is reviewed by a human, then committed.

## Worked example

- **`cloudflare_dns_record`** — pre-existing DNS records (e.g. email-routing records already set up before Terraform adoption) are good import candidates via this flow. Records with no prior existence (like GitHub Pages apex records or a `www` CNAME you're adding fresh) should instead be written directly into your `terraform/cloudflare/` config — no import needed.
- **`cloudflare_pages_project`**, **`cloudflare_r2_bucket`** — `cf-terraforming generate` discovers everything in the account, including resources unrelated to this repo's scope (other Pages projects, empty R2 buckets). Explicitly exclude anything outside the zone/domain this repo is meant to manage — don't import just because it was discovered.
