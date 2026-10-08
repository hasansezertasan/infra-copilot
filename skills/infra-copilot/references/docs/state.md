<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:7e31a670f136a46634d8f1cc5947ef151c271d4fae2f2fdb67650139bbe83f35
Source-Hash: blake3:df4dd5f62bb68e7d55e30a3b3d425b39ce7e6fa03d7740dffbb1393a44ba0165
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

The selected execution implementation configures its toolchain from committed pins.
Preserve parity with the local toolchain when updating them.
