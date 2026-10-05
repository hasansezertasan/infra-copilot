<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:944ef4f99f279f8290cb4f5541f19987bd96bf1a4383f348747a409d8e965940
Source-Hash: blake3:c9f2ea75fea5a68af83110818ebd2c862f0a97488346426b1173d85860ee8b73
Schema-Version: v1
-->

# State

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
