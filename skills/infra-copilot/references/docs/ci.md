<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:2bc64a37ab546e193661638cd5bbddda5a566952722b6696488e7a309df622f7
Source-Hash: blake3:9aa2aa8744d0a9dd2de18163ff29e580322896aae85e0670e4e00e321ff80c3b
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

Runner execution installs committed mise pins and lock through `jdx/mise-action`.
Service-managed execution configures its Terraform version from committed `mise.toml`.
Preserve parity with the local toolchain when updating pins.

## Toolchain in CI

Keep exact tool versions in the repository's committed `mise.toml` and `mise.lock`.
The selected [provision-execution](../operations.md#provision-execution) implementation
owns pin installation or executor-version configuration. Its reference documents the
mechanism; the get-plan contract verifies relevant inputs match the commit.
Do not introduce an independent executor version that diverges from the reviewed pin.
