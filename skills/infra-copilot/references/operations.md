<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:9324955f3e5e3b8045f8b1f34bae5b809f75c15a002df03b7d184616216b477d
Source-Hash: blake3:3a1aea29fb156f444383777bac370c3608f8b1160ee22ebb2fb1feceecee7e6d
Schema-Version: v1
-->

# Execution operations

Setup records the execution choice in config. Config loading resolves that choice to
manifest implementations; action skills call these contracts without selecting a backend.
Implementation code and reference docs own all service-specific commands.

## Selection and resume

Every backend-dependent manifest step declares `operation` and `implementation`.
The agent resolves the validated per-leaf inventory in [config.md](config.md),
then evaluates each member's `when`. This is an agent contract plus executable checks;
there is no manifest runner that implicitly changes environment or filters loops.
Repository service steps select every service present (`HAS_HCP`/`HAS_OBJECT_STORAGE`),
even when it differs from the default. Bootstrap state configuration selects the bootstrap
subset (`HAS_*_BOOTSTRAP`, with loops over its JSON array). Credential and plan steps
select `CLOUDFLARE_BACKEND` or `GITHUB_BACKEND`. Phase 6 selects `NEW_PROVIDER_BACKEND`.
Shared checks select the target leaf's effective backend internally.
Never prefilter the manifest globally by `BACKEND`: mixed mode can select both implementations.
Reject missing, empty or invalid config choices before evaluating conditions.

Preserve manifest order, phase boundaries, actor handoffs, tri-state semantics and the
per-provider inventory loop. An operation can have several ordered implementation steps;
run every applicable member, never select just the first matching member. When a member
sets `refresh_credentials: true`, refresh the selected config exports immediately after
its check passes, before evaluating any later member. Resume at the
first red member. Group reports by `(phase, operation, provider entry)`, using the first
member's position, and keep the member ID for diagnostics. Never group across provider entries.
An operation is green only if all applicable members are green; failed outranks unknown,
unknown outranks pending. A null check remains human-gated. An explicit `not_applicable`
 is N/A with its reason, not green proof. Opposite implementations for a leaf are not reported as
unfinished operations. A member skipped by a provider condition is also N/A with its reason.

For status, use the selected [read-run-status](#read-run-status) implementation for checks
that mutate the working tree. Never execute a step's `run` or a local plan during status.
A current-revision failure stays red; unreadable evidence is unknown. Latest-run information
is separate from operation completion and cannot move the first-red verdict.

## Implementation inventory

| Operation | `hcp` members | `object-storage` members |
|---|---|---|
| `bootstrap-state` | `hcp-login`, `hcp-signup`, `hcp-verify` | `state-bucket`, `backend-config`, `backend-identity` |
| `provision-execution` | `vcs-connect`, `workspaces-create` | `gha-workflows`, `gha-environments` |
| `store-cloudflare-credential` | `cf-token` | `cf-token-gha` |
| `store-github-credential` | `gh-app` | `gh-app-gha` |
| `plan-cloudflare` | `plan-cloudflare` | `plan-cloudflare-gha` |
| `plan-github` | `plan-github` | `plan-github-gha` |
| `plan-access` | `hcp-apply-scope` | `gha-plan-access` |
| `required-check-context` | `status-check-context` | `status-check-gha` |
| `provision-provider-execution` | `new-provider-workspace-bootstrap`, `new-provider-workspace` | `new-provider-workflow-gha` |
| `provider-plan-access` | `new-provider-plan-access` | `new-provider-plan-access-gha` |
| `provider-fork-safety` | `new-provider-fork-safety` | `new-provider-fork-safety-gha` |
| `store-provider-credential` | `new-provider-credentials` | `new-provider-secrets-gha` |
| `provider-identity-trust` | `new-provider-gcp-wif-trust` | `new-provider-identity-trust-gha` |
| `plan-provider` | `new-provider-plan` | `new-provider-plan-gha` |
| `sync-execution-config` | `repo-config-sync` (shared) | `repo-config-sync` (shared) |
| `provider-inventory` | `new-provider-inventory` (shared) | `new-provider-inventory` (shared) |
| `provider-decision` | `new-provider-decision` (shared) | `new-provider-decision` (shared) |
| `provider-leaf` | `new-provider-leaf` (shared) | `new-provider-leaf` (shared) |
| `import-resources` | `migrate-import` (shared check) | `migrate-import` (shared check) |
| `prune-blocks` | `prune-spent-imports` (shared inventory check) | `prune-spent-imports` (shared inventory check) |

## Shared configuration operations

`sync-execution-config` refreshes consuming-repo literals after a reviewed config change.
Synchronize static Actions `CLOUDFLARE_BACKEND` and `GITHUB_BACKEND` values in both plan
and apply workflows with effective config in the same cutover PR; template defaults are
object-storage, not a config resolver. Verify workflow agreement before accepting any
Actions evidence or enabling apply. Additional provider workflow routes must agree too.
Mixed protection requires both selected required-check-context implementations and all
effective leaf plan contexts, independent of the backend of the GitHub management leaf.
Remove obsolete HCP required contexts only for migrated leaves; preserve remaining HCP,
Actions, fmt and validate contexts. Migrated workspaces must not be recreated, reconnected,
or granted new plan rights; retained legacy workspaces are migration evidence only.
`provider-inventory` enumerates declared and actual leaves/tool pins;
`provider-decision` requires a committed, human-approved adoption record; `provider-leaf`
writes the isolated Terraform leaf with the selected state configuration. These shared
checks implement both selections internally; service-specific configuration stays inside
the implementation code, never in an action router.

## Bootstrap-state

Establish authenticated remote state, isolated per leaf, with committed tool pins.
For an existing HCP leaf, a passing configuration check verifies its backend text and
routing only. Complete the HUMAN-gated
[cutover runbook](docs/object-storage-state.md#migrating-from-hcp): verified transfer before
merge, retirement of that workspace's writers, destination apply verification, and
credential retirement that preserves every remaining HCP leaf. A green resume scan must
not skip these migration gates or certify them from an empty destination or a backend block.
Implementation: [service bootstrap](hcp.md), [runner state](docs/object-storage-state.md).

## Provision-execution

Provision isolated execution per leaf, pinned tooling, paths including shared inputs,
review before apply, and a required plan context. Additional providers use
`provision-provider-execution` with the same contract.
Implementation: [service execution](hcp.md), [runner execution](object-storage.md#provision-execution).

## Store-provider-credential

A HUMAN stores the scoped credential out of band, without exposing its value to the
agent, git, logs or plans. Verify inventory plus authentication with a plan; secret-name
existence alone does not verify the value. The named bootstrap credential operations use
this same contract. Rotate by storing a replacement, verifying a no-op plan, then revoking
its predecessor. Implementation: [service custody](docs/hcp-secrets.md),
[runner custody](object-storage.md#store-provider-credential).

## Get-plan

Obtain a plan for the target leaf and relevant committed inputs. Reject dirty relevant
paths, skipped leaf jobs, stale revisions and unreadable evidence. Match the leaf and its
latest applicable run; an older green result cannot override a newer failure. Confirm
expected creates for add; for import reject creates, destroys and forgotten resources;
for prune require a no-op. Bootstrap `plan-cloudflare`, `plan-github`, and Phase 6
`plan-provider` use this contract.
Implementation: [service plans](hcp.md#get-plan), [runner plans](object-storage.md#get-plan).

## Read-run-status

Read plan and apply evidence without initializing Terraform or changing tracked files.
Report result, revision, leaf and run URL. Never turn absent, skipped or unreadable
results into success. Verify plan contents and actual apply completion separately.
Implementation: [service status](hcp-status.md), [runner status](object-storage.md#read-run-status).

## Required-check-context

Verify the configured required plan context is actually published for the repository.
Distinguish blocked merges, under-protection and unreadable evidence; do not repair
protection from a status run. Implementation: [service context](docs/hcp-ci.md#hcp-status-check-context),
[runner context](object-storage.md#required-check-context).

## Plan-access

The agent may obtain and inspect plans but never approve or execute applies. Report an
unreadable permission as unknown. `provider-plan-access` extends this contract per leaf.
An implementation-specific team-grant mechanism can be N/A, but the approval boundary
still applies. Implementation: [service permissions](hcp.md),
[runner permissions](object-storage.md#plan-access).

## Provider-fork-safety

Before credential storage, exclude untrusted fork code from authenticated execution.
The configured execution must also preserve human approval before apply. Implementation:
[service fork attestation](hcp.md), [runner fork guard](object-storage.md#fork-safety).

## Provider-identity-trust

Verify keyless identity bindings against the selected execution's exact trusted subject;
never reuse another implementation's subject. The selected identity implementation owns
this review. A scriptable check may be
replaced by an explicit HUMAN ephemeral review when the cloud trust cannot be read
uniformly; status reports it human-gated, never green.
Implementation: [service trust](gcp.md), [runner trust](object-storage.md#provision-execution).

## Import-resources

Generate reviewed HCL and imports, commit them, obtain [get-plan](#get-plan), then wait
for approved apply. Green inventory never proves all live objects are adopted: discovery
runs for every explicitly requested object. Implementation: [service import](hcp.md#import-resources),
[runner import](object-storage.md#import-resources).

## Prune-blocks

Prove leaf-local instruction blocks have applied before deletion, then obtain a no-op
plan for the committed deletion. State membership is only a filter; the plan decides.
Implementation: [service prune](docs/hcp-prune.md), [runner prune](object-storage.md#prune-blocks).
