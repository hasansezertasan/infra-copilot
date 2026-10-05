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
