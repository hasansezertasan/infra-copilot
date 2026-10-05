<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:1d167d6ce7717bea44529953a0c574384ca4547fb7aba2092f5097568e70d5f6
Source-Hash: blake3:c9f2ea75fea5a68af83110818ebd2c862f0a97488346426b1173d85860ee8b73
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

## Cloudflare API token scopes

The persistent edit token needs **Edit** for every managed resource type, currently
Zone — DNS — Edit and Zone — Zone Settings — Edit. Widen scope before declaring a new
resource type. Use a separate short-lived **Read** token for discovery, scoped to the
specific account/zone and resource types, then revoke it when discovery finishes.

## GitHub App setup

Create an App under the managed organization and install it only on the managed
repositories. Grant Repository Administration (read/write), Contents (read), Metadata
(read), Pull requests (read/write), and Organization Members (read), Administration
(read/write) for the existing management scope. Adjust scope deliberately when managed
resource types change. Record the App ID and installation ID, generate a private key,
and store the full PEM and IDs with
[store-provider-credential](../operations.md#store-provider-credential).
The PEM includes its BEGIN/END delimiters and newlines; never commit it.

## Cloudflare API token

Mint a replacement with the existing managed-resource scopes, store it through
[store-provider-credential](../operations.md#store-provider-credential), and obtain a
no-op plan. Revoke the previous token only after the new token authenticates successfully.
If validation fails, restore the still-live old value and investigate.

## GitHub App private key

Generate a second private key while the old one remains active. Store the full new PEM
through [store-provider-credential](../operations.md#store-provider-credential), obtain a
no-op plan, then delete the old App key. Correct newline/delimiter problems before revoking
anything. The selected credential implementation owns the storage commands.
