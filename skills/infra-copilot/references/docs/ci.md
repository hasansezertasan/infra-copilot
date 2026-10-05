<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:17050584d18c55fc4a3f33858f4c8a871972e67579952a8a16378b5e4b15cf68
Source-Hash: blake3:6712d29db04e3727de45cb87d8b0389e6199300dc2d02460a4c4452d25baf96f
Schema-Version: v1
-->

# Ci

Setup selects execution and remote state. Shared workflows use the contracts in
[operations](../operations.md).

- [Provision-execution](../operations.md#provision-execution): isolated state per leaf,
  path-scoped execution, approved applies and a pinned toolchain.
- [Get-plan](../operations.md#get-plan): revision-correlated plan evidence for review.
- [Read-run-status](../operations.md#read-run-status): read-only plan/apply evidence.
- [Required-check-context](../operations.md#required-check-context): a published plan
  context that actually gates merges.

State may contain credentials and sensitive resource attributes. Keep it out of git and
public logs. Protect state access and locking, and verify migration before removing its
previous storage. Human approval remains required before any apply.

Execution installs committed mise pins and lock through `jdx/mise-action`; preserve
parity with the local toolchain when updating pins.

## Toolchain in CI

Keep exact tool versions in the repository's committed `mise.toml` and `mise.lock`.
The selected [provision-execution](../operations.md#provision-execution) implementation
installs those pins, and the get-plan contract verifies relevant inputs match the commit.
Do not introduce an independent executor version that diverges from the reviewed pin.
