<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:05a7b325295440acaee621cb47a955769a7029bec977196185d394c3194d7669
Source-Hash: blake3:3a1aea29fb156f444383777bac370c3608f8b1160ee22ebb2fb1feceecee7e6d
Schema-Version: v1
-->

# State

Setup selects execution and remote state. Shared workflows use the contracts in
[operations](../operations.md).

Resolve state per declared leaf: `leaf_backends[leaf]` overrides the required `backend`
default. Mixed repositories retain isolated HCP and object-storage state simultaneously.
Before converting an existing HCP leaf, follow the authoritative
[migration runbook](object-storage-state.md#migrating-from-hcp); backend text alone is not
proof that state moved. Never infer a fresh leaf from an empty destination bucket.

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
