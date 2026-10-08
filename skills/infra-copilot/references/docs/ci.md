<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:a6e3d24a326366e29881454896fe2d41864f49459860c87c7a8666ea025eaa76
Source-Hash: blake3:3a1aea29fb156f444383777bac370c3608f8b1160ee22ebb2fb1feceecee7e6d
Schema-Version: v1
-->

# Ci

Setup selects execution and remote state. Shared workflows use the contracts in
[operations](../operations.md).

Selection is per leaf, with both execution services active in mixed repositories.
Synchronize plan/apply workflow `CLOUDFLARE_BACKEND` and `GITHUB_BACKEND` literals with
effective config in the cutover PR; verify agreement before accepting runner evidence.
Keep HCP-routed leaves out of authenticated Actions jobs and preserve both services'
required contexts while both have active leaves. Additional provider routes follow their
own effective backend, not the default or the GitHub management leaf's backend.

- [Provision-execution](../operations.md#provision-execution): isolated state per leaf,
  path-scoped execution, approved applies and a pinned toolchain.
- [Get-plan](../operations.md#get-plan): revision-correlated plan evidence for review.
- [Read-run-status](../operations.md#read-run-status): read-only plan/apply evidence.
- [Required-check-context](../operations.md#required-check-context): a published plan
  context that actually gates merges.

State may contain credentials and sensitive resource attributes. Keep it out of git and
public logs. Protect state access and locking, and verify migration before removing its
previous storage. Human approval remains required before any apply.

Runner execution installs committed mise pins and lock through `jdx/mise-action`.
Service-managed execution configures its Terraform version from committed `mise.toml`.
Preserve parity with the local toolchain when updating pins.

## Toolchain in CI

Keep exact tool versions in the repository's committed `mise.toml` and `mise.lock`.
The selected [provision-execution](../operations.md#provision-execution) implementation
owns pin installation or executor-version configuration. Its reference documents the
mechanism; the get-plan contract verifies relevant inputs match the commit.
Do not introduce an independent executor version that diverges from the reviewed pin.
