<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:385fe9fe867118f1d5a55ac1f53ca0d2a00091a303ff03bac259c3e146bfe914
Source-Hash: blake3:ad43e66d469ee9233069460521d0eba5996844a9124ac98be94a6ff68475da4c
Schema-Version: v1
-->

# Object-storage execution

The implementation selected by a leaf's effective `object-storage` backend uses GitHub Actions to execute
Terraform against per-leaf GCS, S3 or Azure state. The shared contracts are in
[operations](operations.md). The full [runner CI recipes](docs/object-storage-ci.md) document authentication and environments.
State provisioning, IAM and migration commands are in
[object-storage state](docs/object-storage-state.md).

## Provision-execution

Install [plan](templates/terraform-plan.yml) and [apply](templates/terraform-apply.yml)
workflows, with one leaf job and isolated state key per provider. Include the leaf,
`terraform/modules/**`, `.infra-copilot/config.md`, `mise.toml` and `mise.lock` in the
path filter. Add the leaf to validation, the changes output, the aggregate plan's `needs`,
and the apply job condition. Use the committed mise lock via `jdx/mise-action`.

Only `OBJECT_STORAGE_LEAVES` may initialize, authenticate, plan or apply in Actions.
Keep HCP leaves in validation but out of credential-bearing runner execution. Set static
top-level `CLOUDFLARE_BACKEND`/`GITHUB_BACKEND` in both workflows to the effective config
values in the same reviewed cutover PR. Verify with `checks/workflow-routing.sh` before
accepting evidence; the template's object-storage defaults do not resolve config.
For additional providers, extend change routing, job conditions and the aggregate to
the entry's effective backend. Add a top-level static route literal named after the
uppercase slug with hyphens replaced by underscores, prefixed with `LEAF_` and followed
by `_BACKEND` (e.g. `LEAF_GCP_PROD_BACKEND`). Use corresponding `LEAF_<SLUG>_CHANGED`
inputs and `leaf_<slug_with_underscores>` shell variables. Preserve the supported route
script grouping: all false initializers, guarded true decisions, then output writes,
bootstrap leaves first and additional leaves in lexical order. Include both workflow
paths in plan filters and every Actions provider in the aggregate's dependencies
and changed-leaf success predicates. Run the workflow agreement check with `ROUTING_PROVIDER` set to
`NEW_PROVIDER` for that entry to verify both workflows against effective config.
The Phase 6 workflow and plan checks enforce this.
Apply routing uses static true change inputs, converging all object-storage leaves on
every main push/dispatch; plan routing combines dispatch with PR-filter outputs.
An override to HCP must disable that provider's runner auth/init/plan/apply path.
In mixed mode retain both Actions and HCP protection contexts regardless of which
service manages the GitHub leaf itself. Never reconnect migrated HCP workspaces.

Provision execution before adding provider secrets. The new leaf's apply job must set
`environment: production`. A HUMAN restricts that environment to `main` and adds required reviewers or records an apply gate ([GitHub Environments](docs/object-storage-ci.md#github-environments)).
The `new-provider-identity-trust-gha` HUMAN step checks cloud IAM trust: the OIDC subject must bind the exact repository and permitted
branch or protected environment, never a wildcard repository or arbitrary fork. Verify
state isolation, locking and the exact runner service account/role before authorizing it.
The `new-provider-workflow-gha` check verifies structural presence; it does not establish
trust or credentials. Complete fork safety and the human IAM review before storing them.

## Plan-access

There is no HCP workspace team grant or local Terraform Cloud API token here. The
manifest records that specific grant check as `not_applicable`; it does not assert that
a runner's cloud identity is incapable of applying. GitHub's token does not itself grant
state/provider permissions: runner OIDC and provider secrets do. A HUMAN must review those
grants during execution provisioning. Use a distinct restricted plan identity where the
provider supports it, and protect the apply identity with production approval.

The agent may dispatch `terraform-plan.yml` on its branch, inspect run logs and query
metadata. It must never dispatch an apply, approve an environment deployment, weaken
reviewers, or run credential-bearing Terraform locally to bypass approval. Existing
same-repository branches execute trusted code; review workflow and Terraform changes
before allowing credentials to run. Fork exclusion is not a sandbox for malicious code
already admitted into the repository.

## Fork-safety

Each `plan-<provider>` job uses the job-level conjunction of its path filter with:
`(github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository)`.
Do not use `pull_request_target` to execute changed Terraform. Secrets and OIDC belong
only in those guarded jobs. Grant `id-token: write` at job scope, never workflow
scope, so change detection and fork validation cannot request OIDC tokens. Apply jobs use the protected production environment.

Run `sh "$INFRA_COPILOT_REFERENCES/checks/gha-provider-safety.sh"` with `NEW_PROVIDER` and
`REPO` exported before storing credentials. It verifies committed, clean workflows in
the supported template syntax, credential access across all jobs, the new job's exact
fork guard, its production environment
and the same apply gate `gha-environments` checks (`checks/gha-apply-gate.sh`). YAML anchors, aliases and quoted permission keys are
unsupported and rejected. It accepts only the templates' block event syntax and exact guard expression, preserving
quoted literal contents. It rejects unfamiliar syntax rather than guessing that a
textual occurrence elsewhere protects the job. IAM trust is a separate HUMAN review.

## Store-provider-credential

A HUMAN stores Cloudflare's token as `CLOUDFLARE_API_TOKEN`, and the GitHub App ID,
installation ID and full PEM as `GH_APP_ID`, `GH_APP_INSTALLATION_ID` and
`GH_APP_PEM` repository secrets. See the template's variable mapping; the App
PEM is a multiline value, including its BEGIN/END delimiters. Never echo or return secret
values to the agent. For additional providers, use `credential_secrets` from their config
entry; the manifest checks required names and the committed `credentials_verified_at`
attestation. A secret-list read proves names only: obtain a successful provider plan to
prove the installed credential authenticates. State credentials use the separate cloud
OIDC identity, not the Cloudflare discovery token.

Rotate with overlap: mint the replacement, replace the secret out of band, obtain a no-op
plan on a trusted branch, then revoke the old value. Retain the old value until verification
succeeds; restore it on failure. GitHub Apps allow overlapping keys: store the full new
PEM, verify, then delete the old key. Rotate exposed cloud identities by updating their IAM
trust and reviewing current deployments, not by storing long-lived keys in the repository.

## Get-plan

Commit relevant changes first; reject dirty leaf, shared modules, config or mise pins.
Resolve the target in `OBJECT_STORAGE_LEAVES` and verify workflow agreement first.
Both plan and apply workflow files are relevant committed inputs for dirty-tree and
revision correlation. A pre-cutover green run cannot validate newer routing or identity
changes merely because the Terraform leaf itself did not change.
Push the branch and dispatch `terraform-plan.yml` with the explicit branch ref when no
PR run exists. Find the newest applicable `pull_request` or `workflow_dispatch` run on
that branch; verify its SHA includes the newest relevant input commit and has a successful
`plan-<leaf>` job. A successful aggregate with a skipped leaf is not plan evidence.
Read that job's logs without posting credential-bearing output to public comments.
Older green runs cannot override newer failures.

## Import-resources

Discovery and `terraform init -backend=false` for generation run locally with a separate
read-only token. Persistent provider and state authentication stay in the runner.
Commit generated HCL and import blocks, push, obtain the leaf's plan and inspect its logs:
require imports, no creates, destroys or forgotten resources. Do not mistake a skipped
leaf job for a no-op. The shared `migrate-import` check correlates evidence with committed
inputs; a `No changes` result requires evidence of a successful relevant apply. A green
scan does not replace discovery of explicitly requested live objects.

Wait for the merge's successful `apply-<leaf>` job through production approval before
pruning. A green workflow with a skipped apply job is insufficient. Retain import blocks
until this evidence exists; the agent never executes or approves the apply.

## Prune-blocks

Local `terraform state list` and local plans cannot assume runner-only state credentials.
Use the workflow's plan for the committed deletion. State membership filters are N/A
locally; they are not the proof. A before-plan on an unchanged branch can be skipped by
paths-filter, so never count it as a no-op. Only after confirming the import/move apply
landed, delete candidate leaf blocks, commit, push and obtain `plan-<leaf>` for that change.
Require `No changes.` with no imports, moves, creates, changes or destroys; otherwise
restore the blocks and stop. One PR per leaf, separate from the adoption PR.

## Read-run-status

Read [latest runs](checks/gha-latest-runs.sh) using
`sh "$INFRA_COPILOT_REFERENCES/checks/gha-latest-runs.sh"`. Export the validated config
and repository/reference variables first. It reports the latest branch plan and `main`
apply independently, including every leaf job and other failed jobs. Preserve its
outcomes: success, failure, in progress, unknown, no runs and not installed. A result for
an earlier SHA is not evidence for HEAD. Exit 1 means a failed run was read, exit 2 means
at least one line was unreadable; a readable failure wins over an unreadable other line.
These informational lines never replace the manifest's current-revision checks or move
the first-red verdict.

For operation completion, use get-plan's revision/leaf correlation. A pending or skipped
job is unknown; failed is red. Phase 6 get-plan is green on a safe first plan with expected creates; deployed-resource
completion additionally requires approved apply evidence for committed inputs. A skipped
job is never proof of either stage. Phase 5 completion requires approved apply evidence, or a no-op plan
with zero imports, creates and destroys for retained import blocks. For `moved` blocks,
counts alone cannot prove the move applied: require applied evidence or the prune plan.

## Required-check-context

Use the aggregate `plan` job name as the required branch-protection context, including
all managed leaf jobs in its `needs`. Run `status-check-gha` to verify a successful plan
job on the current branch, and inspect branch protection before changing required names.
A stale required context blocks PRs; removing plan protection allows unreviewed changes.
Report these separately from an unreadable API result. Do not weaken protection during
status. The current check does not prove that branch protection itself is installed.
