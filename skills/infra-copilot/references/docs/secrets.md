<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:b5372d1b501ce2778016e57202b3e7f7b8f2e0e4144c9c3d64efbfb4eea530b9
Source-Hash: blake3:1dc2bb768d75a6b5f133bcb28897bd2eec92647e797988f199e55974253b44f8
Schema-Version: v1
-->

# Secrets

This repository is public. Never commit plaintext credentials or expose them in logs,
plan output, state snapshots or pull request comments. A credential in git history must
be revoked and replaced.

## Where secrets live

Use [store-provider-credential](../operations.md#store-provider-credential).
The persistent Cloudflare edit token, and GitHub App ID, installation ID and full PEM,
are supplied by the selected execution service. Keep discovery credentials separate,
short-lived and read-only; revoke them when discovery finishes.

## Scope and rotation

Grant only permissions required by managed resources. A new resource type may require a
human to widen its credential scope before obtaining a plan. Store the replacement with
[store-provider-credential](../operations.md#store-provider-credential), obtain a no-op
[get-plan](../operations.md#get-plan), then revoke the old value only after successful
authentication. Restore the old value if validation fails. For App keys, generate a second
key first, store the full PEM including delimiters and newlines, verify, then delete the old key.

Identifiers such as account IDs and repository names are not credentials. State can still
contain sensitive values: keep it outside git and treat access as privileged.
