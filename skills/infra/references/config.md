<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:a74eef0239ac5dd336a1ac939b7564014416be5cc391b32d583549f31b9e3d69
Source-Hash: blake3:42c7574fde1dc55e8f96bd54590bf4f29122805f262a3a990b60d7f7f4763ae5
Schema-Version: v1
-->


# Repo-local config contract

`infra-skills` is org-agnostic. Every value that used to be hardcoded for one org lives
in the **Config block**: a committed, non-secret section of the Infra repo's root
`README.md`, rendered by the Template. It is one fenced YAML block between marker
comments, under the `## Config` heading:

````text
<!-- infra:config start -->
```yaml
backend: object-storage
...
```
<!-- infra:config end -->
````

**No secrets** — those stay in HCP workspace variables (HCP mode) or GitHub Actions
secrets (object-storage mode). The block holds only public identifiers.

Inside the block, `# infra:customization start` and `# infra:customization end` enclose
the fields the Skills and humans write: `leaf_backends`, `state_transfers`, `github_apps`,
`hcp_status_check_id` and `additional_providers`. Everything outside them is a Template
answer, changed with the Template's own update flow. See
[Editing the Config block](#editing-the-config-block).

The locked choices live in the **Decisions table**, a second fixed README section between
`<!-- infra:decisions start -->` and `<!-- infra:decisions end -->`, with the columns
Decision, Choice, Status and Rationale. The checks read locked rows from it.

The old `.infra-copilot/` directory and the legacy `.claude/infra-copilot.local.md` file
are unsupported. See [Unsupported legacy state](#unsupported-legacy-state).

## Backend modes

infra-skills supports two execution modes:

| Mode | State backend | CI | Secrets | Plan visibility |
|------|---------------|-----|---------|-----------------|
| `object-storage` (recommended) | Cloud storage bucket (gcs/s3/azurerm) | GitHub Actions | GitHub Actions secrets | PR comment (repo access) |
| `hcp` | HCP Terraform `cloud {}` | HCP VCS integration | HCP workspace variables | HCP UI (auth required) |

The `backend` field is required and supplies the repository default; there is no implicit default.
Each declared leaf can override it through `leaf_backends`.
For a new setup, recommend `object-storage`: cloud storage state + GitHub Actions CI
puts plan output in the PR. HCP Terraform offers managed runs and a UI. Its free tier
is limited to 500 managed resources
([subscription plans](https://developer.hashicorp.com/terraform/cloud-docs/overview)),
but **infra-skills's HCP workflow requires a paid tier with team management even below
500 resources**: the mandatory `hcp-apply-scope` step uses a custom plan-only team and
team token, and free-tier organizations have only the owners team
([security model](https://developer.hashicorp.com/terraform/cloud-docs/architectural-details/security-model)).
Disclose both the resource limit and this paid-plan prerequisite before asking for the
backend choice; never substitute an apply-capable token to complete setup on the free tier.
Present HCP as a deliberate choice. Ask using the shared protocol's decision mechanism,
put object-storage first and mark it recommended, then record the choice as the Template's `backend` answer before any step runs. `backend` is
a Template answer outside the customization markers, so the Skills never write it themselves:
the Template renders it, or a human adds it by hand when it is missing.

### Migration: existing configs without backend

**Breaking change:** configs that omit `backend:` now stop at startup instead of
silently selecting HCP. This applies to all five action skills, including `infra-status`. Adding the field records the
existing mode; it does not move state or change how Terraform runs.

When `backend` is missing, empty, or invalid, emit a handoff explaining both values and
stop before preflight, any `when` evaluation, check, or run. Inspect existing Terraform
leaves for HCP `cloud {}` blocks, for example:

```sh
grep -lE '(^|[[:space:]])cloud[[:space:]]*\{' terraform/*/*.tf 2>/dev/null
```

If found, show the paths and offer a `backend: hcp` line for the human to add, to preserve the existing HCP
workflow. The match is a hint for the user's decision, never permission to choose a
backend automatically. Without that evidence, ask which mode the repo uses; absence of
a match is not evidence for object-storage. Wait for an explicit choice and for the human to add or correct `backend:` (the one
Template answer the migration handoff asks a person to edit), then re-read config, validate
the field, and export vars before resuming. The Skills never write it, and never touch the
other fields or the customization markers while doing so.
`infra-status` reports the missing/invalid field and the suggested migration but never writes
config; direct the user to add the field or run `infra-setup` to record their choice.

```text
┌─ HUMAN ACTION NEEDED ─────────────────────────────
│ Step:   config-backend — record an explicit backend
│ Why:    Checks require the repo's state and CI mode; there is no default.
│ Do this:
│   1. Choose backend: hcp (paid team management + runs/UI) or object-storage (bucket/Actions).
│   2. Record the existing mode in the README Config block and commit it.
│ When done, reply "done" and I'll verify.
└───────────────────────────────────────────────────
```

## Schema

### Common fields (both modes)

```yaml
backend: object-storage        # required: hcp | object-storage; recommended for new repos
leaf_backends: {}               # optional map: leaf name -> hcp | object-storage
state_transfers: {}             # public HUMAN cutover evidence, keyed by migrated leaf
github_apps:                    # handoff evidence when github uses Actions
  plan_app_id: ""               # public numeric ID, distinct from apply
  apply_app_id: ""
  reviewed_at: ""               # HUMAN UTC after permissions + secret scopes reviewed
  plan_manifest_blob: ""        # git hash-object of committed .github/apps/terraform-plan.json
  apply_manifest_blob: ""
github_org: <string>           # GitHub org slug
apex_domain: <string>          # e.g. example.dev
cloudflare_account_id: <hex>   # Cloudflare account ID
cloudflare_zone_id: <hex>      # Cloudflare zone ID for the apex domain
managed_repos:                 # repos Terraform manages; first entry is the primary repo
  - <owner/name>
additional_providers: []       # provider-adoption records; empty until add's new-provider flow starts
```

### HCP mode fields

These fields are required whenever any declared leaf's effective route is HCP.

```yaml
backend: hcp
hcp_org: <string>              # HCP Terraform organization slug (often == github_org)
hcp_status_check_id: ""        # regenerated by HCP after first VCS connect; leave "" until then
# ... common fields ...
```

### Object-storage mode fields

These fields are required whenever any declared leaf's effective route is object-storage,
including when `backend: hcp` remains the default.

```yaml
backend: object-storage
state_backend: gcs             # Terraform backend type: gcs | s3 | azurerm
state_bucket: <string>         # bucket name for state files (container name for azurerm)
state_prefix: terraform/state  # path prefix within bucket (default: terraform/state)
state_endpoint: ""             # S3-compatible endpoint URL (Cloudflare R2, MinIO); empty means AWS S3
state_lock_table: ""           # DynamoDB table for AWS S3 locking; empty with state_endpoint (use_lockfile); GCS/azurerm have native locking
state_region: ""               # region for S3, Azure resource group location, and the GCS bucket location (required to create a GCS bucket)
azure_storage_account: ""      # storage account name for azurerm backend
azure_resource_group: ""       # resource group for azurerm backend
# ... common fields ...
```

Each `additional_providers` entry is the durable input for one provider-neutral Phase 6
scan. It records public names and the *names and properties* of credential variables,
never their values. Select each entry's schema by its effective backend, not the default.
Mixed repositories therefore retain HCP fields for their HCP leaves and runner fields
for their object-storage leaves. Changing a route requires the corresponding credential
and identity handoff again; an HCP attestation never proves Actions authentication.

### Mixed cutover example

```yaml
backend: hcp
leaf_backends:
  github: object-storage
  gcp: object-storage
hcp_org: your-org
hcp_status_check_id: "<published context for remaining HCP leaves>"
state_backend: gcs
state_bucket: your-org-tf-state
state_prefix: terraform/state
additional_providers:
  - name: gcp
    mise_tools: [gcloud]
    mise_config_blob: ""
    mise_lock_blob: ""
    credentials_verified_at: ""
    credential_secrets: []
```

This fragment keeps Cloudflare in HCP and moves GitHub plus the declared GCP entry
to Actions; common fields still apply. Both service export sets are active. Set workflow
`CLOUDFLARE_BACKEND: hcp`, `GITHUB_BACKEND: object-storage`, and the Phase 6
`LEAF_GCP_BACKEND: object-storage` literal in both workflows. Validate agreement rather than
accepting the template defaults. Complete existing-state migration through
[the authoritative runbook](docs/object-storage-state.md#migrating-from-hcp).

### HCP mode additional_providers

```yaml
additional_providers:
  - name: gcp                 # lowercase leaf name: terraform/gcp
    workspace: gcp            # HCP workspace selected by the leaf's cloud block
    mise_tools:               # exact mise keys added for this provider; [] if none
      - gcloud
    mise_config_blob: ""      # HUMAN-reviewed `git hash-object mise.toml`
    mise_lock_blob: ""        # HUMAN-reviewed `git hash-object mise.lock`
    fork_speculative_plans_disabled: false # set true only after the HUMAN verifies the UI
    fork_speculative_plans_workspace_id: "" # immutable ws-... identity for that attestation
    credentials_verified_at: ""  # HUMAN records UTC after installing the declared variables
    credentials_backend: ""      # HUMAN records hcp with the completed handoff
    credential_variables:
      - key: TFC_GCP_PROVIDER_AUTH
        category: env         # env or terraform
        sensitive: false
```

### Object-storage mode additional_providers

```yaml
additional_providers:
  - name: gcp                 # lowercase leaf name: terraform/gcp
    mise_tools:               # exact mise keys added for this provider; [] if none
      - gcloud
    mise_config_blob: ""      # HUMAN-reviewed `git hash-object mise.toml`
    mise_lock_blob: ""        # HUMAN-reviewed `git hash-object mise.lock`
    credentials_verified_at: ""  # HUMAN records UTC after verifying the authentication handoff
    credentials_backend: ""      # HUMAN records object-storage with the completed handoff
    credential_secrets: []      # WIF identifiers are public; configure them in the workflow
```

In object-storage mode, `workspace`, `fork_speculative_plans_*`, and `credential_variables`
are not applicable — GitHub Actions handles CI and secrets. The `credential_secrets` field
replaces `credential_variables`. Each entry has `name`, boolean `required`, and `scope`:
`plan` for read-only repository secrets, `apply` for distinct production-only write secrets.
Names must be unique ignoring case. Existing entries without scope must be migrated; never
infer that an old repository credential is read-only. Remove repository copies of apply names.
For example: `[{name: GCP_READ_TOKEN, required: true, scope: plan},
{name: GCP_WRITE_TOKEN, required: true, scope: apply}]`.
It may be empty for keyless authentication such as Workload Identity Federation; public
provider and service-account identifiers belong in workflow configuration, not secrets.

In HCP mode, workspace names must be unique across this list and must not be `cloudflare` or
`github-org`; resume must never repoint an existing bootstrap workspace. Record every
provider CLI added to `mise.toml` in `mise_tools`; keys must be the same simple name as
the executable. Mark each corresponding pin with an immediately preceding
`# infra-skills:provider-cli <key>` comment. Every other non-bootstrap pin must carry an
immediately preceding `# infra-skills:general-tool <key>` comment. The phase inventory
requires every non-bootstrap pin to have exactly one classification, then compares the
flattened declarations only to provider markers. General-purpose tools therefore stay out
of provider inventory, while an unmarked or undeclared provider CLI is rejected. An empty
list is valid only when no provider tool was added. Before credentials are added, a
human must confirm the workspace UI's separate fork speculative-plan toggle is off,
change `fork_speculative_plans_disabled` from `false` to `true`, and record the verified
workspace's immutable `ws-...` ID in `fork_speculative_plans_workspace_id`; the HCP API
does not expose the toggle itself. A renamed or recreated workspace therefore invalidates
the attestation instead of inheriting it by name.

Leave `credentials_verified_at` empty until the HUMAN has installed or replaced every
declared workspace variable, then record that moment as a real, non-future strict UTC
`YYYY-MM-DDTHH:MM:SSZ` and commit the config. The first-plan check accepts only an HCP run
created after the entire recorded handoff second and after the workspace's latest HCP
update, so an older run cannot stand in for the current least-privilege credentials or
newly reconciled execution settings.

Bind that handoff to `credentials_backend: hcp | object-storage`. Clear both fields
whenever changing execution service, then record the destination backend and a fresh
timestamp after verifying destination custody/identity. Legacy attestations without the
backend field are HCP-only; they never prove an Actions handoff, including a default-mode
change with no leaf override.

Record every directly defined variable in the provider workspace, including every value required to
authenticate the provider. A flag such as
`TFC_GCP_PROVIDER_AUTH=true` is credential configuration even when it is intentionally
non-sensitive; a downloaded key normally has `sensitive: true`. An empty list is invalid
for an adopted provider. The exact metadata inventory prevents an old, undeclared
credential from remaining active in a reused workspace while still letting a later `infra-add`
or `infra-status` verify keys without reading their values or guessing provider-specific
conventions. Effective organization-, project-, or workspace-scoped variable sets make
this metadata inventory unverifiable, so the credential check pauses until they are
detached and the required variables are defined directly on the workspace.

Leave `mise_config_blob` and `mise_lock_blob` empty until the HUMAN has reviewed the
complete committed `mise.toml` and `mise.lock`. Then record the respective outputs of
`git hash-object mise.toml` and `git hash-object mise.lock`, commit both attestations with
the reviewed files, and run `mise trust mise.toml`. Path-level mise trust survives later
edits, so only these content-bound values prove the currently active configuration and
lock were reviewed together.

## Startup contract (the skill's first action)

Before running ANY step's `check` or `run`, the agent MUST:

1. Look for a legacy state directory first. If `.infra-copilot/` or
   `.claude/infra-copilot.local.md` exists, stop with the
   [unsupported message](#unsupported-legacy-state). Do not read it, copy it or migrate it.
2. Read `README.md` from the current repo (CWD) and extract the fenced YAML between
   `<!-- infra:config start -->` and `<!-- infra:config end -->`.
3. If the README or that block is **missing**, treat this as a `HUMAN` step: emit the
   handoff block, print this schema, and wait. The one exception is `infra-import`, which
   runs `template-adopt` first and reads config afterwards. Never guess values. Rendering the block
   belongs to the Template, so point the user at it rather than hand-writing the README.
   If the block is **present**, edits to it must respect the customization markers, see
   [Editing the Config block](#editing-the-config-block).
4. Once the block is read, validate `backend` is explicitly either `hcp` or `object-storage`.
   If missing, empty, or any other value, stop and emit the handoff described in
   [Migration: existing configs without backend](#migration-existing-configs-without-backend).
   Validate `leaf_backends` before preflight: absent means `{}`, but a present value
   must be a map, with unique keys drawn only from `cloudflare`, `github`, and the
   unique, valid `additional_providers[].name` declarations. Reject unknown keys,
   null/empty/invalid values, duplicate YAML keys, and malformed adoption records.
   Do not infer routing from existing cloud blocks or silently discard a typo.
   Effective backend is the leaf override when present, otherwise `backend`.
   Never guess a mode or reuse a prior shell's `BACKEND`. Only after validation,
   export the shell vars the checks reference. First, common vars for both modes:

   ```sh
   export BACKEND=<backend>  # required: hcp | object-storage
   export LEAF_BACKENDS='<leaf_backends as compact JSON; {} when absent>'
   export STATE_TRANSFERS='<state_transfers as compact JSON; {} when absent>'
   export GITHUB_ORG=<github_org>
   export DOMAIN=<apex_domain>
   export CF_ACCOUNT_ID=<cloudflare_account_id>
   export CF_ZONE_ID=<cloudflare_zone_id>
   export REPO=<managed_repos[0]>
   export ADDITIONAL_PROVIDER_NAMES='<additional_providers names as compact JSON>'
   export ADDITIONAL_PROVIDER_MISE_TOOLS='<all additional_providers mise_tools flattened as compact JSON>'
   export INFRA_REFERENCES=<absolute path to this references/ directory>
   ```

   Run `sh "$INFRA_REFERENCES/checks/leaf-routing.sh"`; exit 2 stops startup.
   Cold-start exception: if reviewed `jq` is not installed yet, derive the same public
   inventory directly from the validated config for the `toolchain-pin` HUMAN handoff
   only. Do not execute service checks. After that handoff installs the reviewed toolchain,
   execute the resolver and confirm its inventory before full preflight/resume. Read-only
   status reports unknown until the resolver can execute; it never installs tools.
   From its public JSON, export `EFFECTIVE_LEAF_BACKENDS` (the `effective` map),
   `HCP_LEAVES`, `OBJECT_STORAGE_LEAVES`, `HCP_BOOTSTRAP_LEAVES`, and
   `OBJECT_STORAGE_BOOTSTRAP_LEAVES` (compact JSON arrays), `HAS_HCP`,
   `HAS_OBJECT_STORAGE`, `HAS_HCP_BOOTSTRAP`, `HAS_OBJECT_STORAGE_BOOTSTRAP`
   (literal `true`/`false`), and `CLOUDFLARE_BACKEND`/`GITHUB_BACKEND` from the
   effective map. Do not eval config, JSON, or shell assignments from file content.
   Recompute the complete inventory on every config reload and credential refresh;
   clear stale implementation-specific and provider-entry exports first.
   `BACKEND` always remains the repository default, never the current leaf.
   Then export and validate the fields for every service present in that inventory:
   For `GITHUB_BACKEND=object-storage`, export `GH_PLAN_APP_ID`, `GH_APPLY_APP_ID`, and
   `GH_APPS_REVIEWED_AT` from `github_apps`; missing fields become empty so the HUMAN
   App handoff is red. Require distinct public IDs and strict non-future UTC review time.
   Secret updates invalidate that review until the HUMAN reviews custody/live permissions
   again. These public fields never authorize reading secret values.
   Export `GH_PLAN_MANIFEST_BLOB` and `GH_APPLY_MANIFEST_BLOB` from that record too;
   the handoff requires the committed customized manifests to match the reviewed hashes.

   **HCP service present** (`HAS_HCP=true`):

   ```sh
   export ORG=<hcp_org>
   export HCP_STATUS_CHECK_ID=<hcp_status_check_id>
    export ADDITIONAL_PROVIDER_WORKSPACES='<only HCP-routed additional_providers workspaces as compact JSON>'
   export hcp_api=https://app.terraform.io/api/v2
   # Terraform's own precedence: TF_TOKEN_app_terraform_io wins over the credentials
   # file. Follow it here, or HCP_TOKEN and `terraform` authenticate as different
   # identities and `hcp-apply-scope` reports SPLIT-BRAIN.
   export HCP_TOKEN=${TF_TOKEN_app_terraform_io:-$(jq -r '.credentials["app.terraform.io"].token' ~/.terraform.d/credentials.tfrc.json)}
   ```

   **Object-storage service present** (`HAS_OBJECT_STORAGE=true`):

   ```sh
   export STATE_BACKEND=<state_backend>      # gcs | s3 | azurerm
   export STATE_BUCKET=<state_bucket>
   export STATE_PREFIX=<state_prefix>        # default: terraform/state
   export STATE_ENDPOINT=<state_endpoint>    # for S3-compatible stores; empty for AWS S3, GCS, azurerm
   export STATE_LOCK_TABLE=<state_lock_table>  # for AWS S3; empty for S3-compatible, GCS, azurerm
   export STATE_REGION=<state_region>        # for S3 and azurerm; the bucket location for GCS
   export AZURE_STORAGE_ACCOUNT=<azure_storage_account>  # for azurerm
   export AZURE_RESOURCE_GROUP=<azure_resource_group>    # for azurerm
    export ADDITIONAL_PROVIDER_SECRETS='<only object-storage-routed [entry: {name, credential_secrets}, ...] as compact JSON>'
   ```

   If `additional_providers` is absent (legacy config), default it to `[]`. If the key is
   present, reject it unless its value is an array; never turn an explicitly malformed
   value into an empty list. `ADDITIONAL_PROVIDER_NAMES` is therefore always a JSON array,
   including `[]`; the always-run
   `new-provider-inventory` manifest step uses it to catch a Terraform leaf whose durable
   adoption record was never added or was deleted. `ADDITIONAL_PROVIDER_MISE_TOOLS` is
   likewise always a JSON array and is derived by flattening every entry's `mise_tools`;
   the inventory compares it with the explicitly marked provider keys in `mise.toml`.
   Then, for each `additional_providers` entry, instantiate the remaining Phase 6 steps
   and export common vars:

   ```sh
   export NEW_PROVIDER=<entry.name>
   export NEW_PROVIDER_BACKEND=<EFFECTIVE_LEAF_BACKENDS[entry.name]>
   export NEW_PROVIDER_MISE_TOOLS='<entry.mise_tools as compact JSON>'
   export NEW_PROVIDER_MISE_CONFIG_BLOB=<entry.mise_config_blob>
   export NEW_PROVIDER_MISE_LOCK_BLOB=<entry.mise_lock_blob>
   export NEW_PROVIDER_CREDENTIALS_VERIFIED_AT=<entry.credentials_verified_at>
   export NEW_PROVIDER_CREDENTIALS_BACKEND=<entry.credentials_backend; hcp only for an absent legacy field>
   ```

   Plus entry-specific vars selected by `NEW_PROVIDER_BACKEND`, not `BACKEND`:

   **HCP mode:**

   ```sh
   export NEW_PROVIDER_WORKSPACE=<entry.workspace>
   export NEW_PROVIDER_FORK_PLANS_DISABLED=<entry.fork_speculative_plans_disabled>
   export NEW_PROVIDER_FORK_PLANS_WORKSPACE_ID=<entry.fork_speculative_plans_workspace_id>
   export NEW_PROVIDER_CREDENTIALS='<entry.credential_variables as compact JSON>'
   ```

   **Object-storage mode:**

   ```sh
   export NEW_PROVIDER_SECRETS='<entry.credential_secrets as compact JSON>'
   ```

   For an entry written before `fork_speculative_plans_workspace_id` existed, export it
   as the empty string. That deliberately makes the fork-safety step red until the human
   binds the prior attestation to the current immutable workspace ID.
   Likewise, export a missing legacy `credentials_verified_at` as the empty string; that
   keeps credential and plan completion red until the HUMAN performs the current handoff.
   Export a missing legacy `mise_config_blob` as the empty string so a changed executable
   configuration cannot inherit an older path-level trust decision.
   Export a missing legacy `mise_lock_blob` as the empty string so a changed lock file
   cannot inherit an older toolchain review.

   Validate `name` against `^[a-z0-9][a-z0-9-]*$` before putting it into a path or URL.
   In HCP mode, also validate `workspace`. `NEW_PROVIDER_MISE_TOOLS`, `NEW_PROVIDER_CREDENTIALS`,
   and `NEW_PROVIDER_SECRETS` are JSON arrays because the manifest checks compare their
   structured contents with `jq`; do not flatten any into shell words. If `additional_providers` is empty and `infra-add` was invoked for a new
   provider, preserve the requested lowercase provider slug as `NEW_PROVIDER` and run the
   decision step once in bootstrap mode; that HUMAN step creates the first durable entry.
   Otherwise an empty list means Phase 6 is not applicable only after inventory is green.

   Do not export `TERRAFORM_VERSION` here. A greenfield repo may not have `mise` or
   `mise.toml` yet. Preflight bootstraps and validates the toolchain first, then exports
   the version from the exact committed repository file for Phase 1.

`INFRA_REFERENCES` is the absolute path to the `references/` directory of the
loaded skill — the directory holding this file. Steps whose `check` is a shipped script
resolve it from there, because a check runs with the consuming repo as its working
directory and cannot otherwise find files that ship with the skill.

Preflight gates it (`infra-references`), because unset it produces a bare shell
error rather than a diagnostic: the step runs `sh "/checks/..."`, and the script's own
"export it per config.md" message lives inside the file that could not be found.

`hcp_status_check_id` keeps its "regenerated by HCP, never invented" semantics — leave it
`""` until Phase 1's VCS connect emits it, then fill it in.

## Editing the Config block

The Skills write only between the `# infra:customization start` and
`# infra:customization end` comments inside the Config block, and refuse to edit anything
outside them. The Template owns the rest of the README, and a Template update keeps the
customization region and rewrites the remainder, so an edit outside the markers would
desync the block from the answers the Template recorded.

- **Balanced pair present** — change only the keys the step owns, and preserve every other
  byte between the markers verbatim. Do not reformat, reorder, or normalise the preserved region,
  even if it looks wrong.
- **An edit that would land outside the markers** — refuse it. Say which key is a Template
  answer and that it changes through the Template's update flow.
- **Markers missing, duplicated, or out of order** — treat it as a `HUMAN` step. Emit the
  handoff block, say which marker is wrong, and wait. **Never merge by inference.**

A preserved region that is merely stale costs a re-edit; a silently overwritten
`hcp_status_check_id` is unrecoverable from the repo alone, because the value was never
anywhere else.

## Unsupported legacy state

A repo that still has `.infra-copilot/` or `.claude/infra-copilot.local.md` predates the
README Config block. Both are unsupported and there is no migration code. When either
exists, every skill, `infra-import` included, reports that and stops before preflight, any
`when` evaluation, check or run. The human moves the values and deletes the path, then the
skill restarts; a repo made from the old `infra-template` GitHub template reaches
`template-adopt` that way:

```text
┌─ HUMAN ACTION NEEDED ─────────────────────────────
│ Step:   legacy-state — unsupported state directory
│ Why:    .infra-copilot/ and .claude/infra-copilot.local.md are no longer read.
│ Do this:
│   1. Note the public values you want to keep (orgs, apex domain, IDs, managed repos).
│   2. Delete the legacy path and commit.
│   3. Restart: the Template creates the README Config block and Decisions table, and asks
│      for those values; never write them by hand first.
│ When done, reply "done" and I'll restart.
└───────────────────────────────────────────────────
```

`infra-status` reports the same message read-only.

## Design decisions

Provider and authentication decisions belong in the Decisions table of the Infra repo's
README. Record each durable choice, its status, and its rationale there. The table is
the only decision record a check reads; Keep the Why is an optional home for long-form
rationale and no check depends on it. A decision that was never recorded is not locked,
so the safe default holds.

## Staged backend migration

`backend` remains the explicit repository default; `leaf_backends` records each declared
leaf's override. In each cutover PR, change the migrating leaf's override and synchronize
its static route in both Actions workflows. Remaining leaves retain their effective HCP
route, workspace connection, credentials and required plan contexts. Changing the default
later changes every leaf without an override, so review the complete effective inventory
before doing so; it is not a required final migration step.

Setup and status select checks per effective leaf and run prerequisites/protection for
every service still present. They can verify that mixed routing agrees with committed
configuration, but neither a skipped opposite implementation nor a green scan proves
state transfer, HCP writer retirement or an approved destination apply. Complete the
HUMAN-gated [migration runbook](docs/object-storage-state.md#migrating-from-hcp) for each
leaf, preserving the other leaves' execution and credentials throughout the window.
