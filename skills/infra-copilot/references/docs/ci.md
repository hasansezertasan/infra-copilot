<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:d6627e0fd1c69d10bc8572883b1a36c4d153ca3a18be73b8c57f4c2e1b3dd9cd
Source-Hash: blake3:1dc2bb768d75a6b5f133bcb28897bd2eec92647e797988f199e55974253b44f8
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
