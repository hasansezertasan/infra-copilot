<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:0f5e1b1eb4f9a05ed50fc56e5cd7e74e3eec4347a4dfe3e58f51f8b00a8f8114
Source-Hash: blake3:3a1aea29fb156f444383777bac370c3608f8b1160ee22ebb2fb1feceecee7e6d
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

Choose custody by each leaf's effective route. A mixed repository can use HCP workspace
variables for Cloudflare and Actions secrets for GitHub, or the reverse. Validate and
refresh both service export sets when needed, and clear the previous provider entry's
exports before switching entries. An HCP credential attestation does not verify runner
authentication after cutover; complete the destination handoff and a fresh plan first.

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
repositories. Grant Repository Administration (read/write), Actions (read), Contents
(read), Metadata (read), and Pull requests (read/write); Actions read is required to read
environments and deployment branch policies on refresh. Grant Organization Members
(read/write) and Administration (read/write). Members write is required when Terraform
manages organization or team membership; read-only access only lets the provider inspect
memberships. Adjust scope deliberately when managed resource types change. Record the App
ID and installation ID, generate a private key, and store the full PEM and IDs with
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
