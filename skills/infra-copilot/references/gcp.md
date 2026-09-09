<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:159788603da6593705d729c3e528b02b432a6c1ef99c6a1c308b68285ae5c524
Source-Hash: blake3:08d9efc8383f0e500d20ec1cac749a5477e465d3aff4d7c196663f1f6651891f
Schema-Version: v1
-->


# Provider: GCP (TEMPLATE — not active)

> **Status: TEMPLATE. No GCP resources are managed by this repo today.**
>
> GCP is **not** a managed provider. There is no `terraform/gcp/` leaf, no `gcp` HCP
> workspace, and no GCP entry in this repo's `.infra-copilot/decisions.md`.
> Adopting GCP is a **design decision that must be made first** — per that decisions file,
> update the decisions table and this repo's root `terraform/README.md` **before** any
> code or provisioning. This file is the forward-looking template for *when* that day
> comes, written in the same agent-first shape as the live providers.

## Prerequisite: make the decision (HUMAN + docs)

The provider-neutral `new-provider-decision` entry in [`steps.yaml`](steps.yaml) stays
**red** until GCP is intentionally adopted. Before writing provider code:

1. Add a locked row to `.infra-copilot/decisions.md` with decision `Provider: gcp` and
   choice `adopt` (put purpose and auth rationale in the context column).
2. Note the new leaf in `terraform/README.md`.
3. Add GCP to `.infra-copilot/config.md`'s `additional_providers`, including every HCP
   variable used for authentication, `mise_tools: [gcloud]`, and an initially false fork
   speculative-plan attestation with empty workspace-ID and credential-verification fields.
4. Then, and only then, follow the parameterized Phase 6 steps.

## Recommended auth: Workload Identity Federation (keyless)

Prefer **WIF** over a downloaded service-account JSON key. WIF lets HCP present a
short-lived OIDC token that GCP exchanges for temporary credentials — **no long-lived key
to store, paste, or rotate.** A service-account key is the fallback only if WIF can't be
arranged; it would live as a sensitive HCP var exactly like the Cloudflare token, with all
the rotation burden that implies.

## The actor split (projected)

| Action | Actor | Why |
|---|---|---|
| Create GCP project, link billing | **HUMAN** | Billing consent is browser + payment; irreducibly human. |
| Enable APIs, create SA / WIF pool | **AGENT** | `gcloud` / GCP API, once auth exists. |
| Approve the WIF trust / OAuth consent | **HUMAN** | One browser consent for the federation trust. |
| Paste SA key into HCP *(only if not using WIF)* | **HUMAN** | Agent must never see the key. |
| Create the `gcp` HCP workspace | **HUMAN** | The plan-only agent credential cannot create organization workspaces. |
| First `plan` | **AGENT** | Speculative run in HCP. |

## Phases (projected)

### HUMAN — project + billing

1. Create a GCP project (`gcloud projects create <id>` is possible, but billing linkage
   and the initial org/consent are browser steps). Note the **project ID**.
2. Link a billing account (browser).

### AGENT — enable APIs + set up auth

> ⚠ **Illustrative, not runnable as-is.** The `...` below is a real gap — the WIF pool,
> provider, attribute mapping, and trust condition must be completed against HCP's actual
> OIDC issuer/audience at adoption time. Treat this as the shape, not the procedure; fill
> it in (and replace this warning) when GCP is actually adopted.

`gcloud` is a pinned tool like any other — add it to `mise.toml` before this phase.
Its mise backend (`vfox:mise-plugins/vfox-gcloud`) locks download URLs but not checksums,
so you get version parity rather than artifact identity; that is enough for the contract in
[`docs/setup.md`](docs/setup.md#6-local-development), and worth knowing rather than
discovering. On macOS its post-install step tries to `sudo`-install a system Python and
fails; that is harmless, since the SDK ships its own.

Mark and pin it under the plain `gcloud` key —
`# infra-copilot:provider-cli gcloud` followed by `gcloud = "551.0.0"` — not the backend string.
mise's registry aliases `gcloud` to that vfox backend, so the short name resolves to it;
the backend is named above so you know what you are getting, not as the key to write.
This is the opposite of `cf-terraforming`, which is absent from the registry and therefore
does need its backend spelled out in the key. Preflight reads `tools.gcloud`, so a
backend-qualified key would leave that lookup empty.

Once `terraform/gcp` exists, manifest preflight requires an exact `tools.gcloud` pin and
compares it against the installed SDK version — the `Google Cloud SDK` field of
`gcloud version`, not the `core` component, which is a release date rather than a version.
Status reports missing or drifted pins.

```sh
mise exec -- gcloud config set project <PROJECT_ID>
mise exec -- gcloud services enable cloudresourcemanager.googleapis.com iam.googleapis.com <needed-apis>

# WIF (preferred): create a workload identity pool + provider trusting HCP's OIDC issuer,
# and a service account with least-privilege roles that HCP may impersonate.
mise exec -- gcloud iam workload-identity-pools create hcp-pool --location=global ...
```

Provider block goes in `terraform/gcp/providers.tf`, using `google`/`google-beta`, with
impersonation rather than a key file.

### HUMAN — HCP workspace bootstrap (Phase 6)

Follow the provider-neutral `new-provider-workspace-bootstrap`, workspace verification,
and plan-access handoffs in Phase 6. Create `gcp` with working dir `terraform/gcp`, path
filter `terraform/gcp/**`, remote execution, and auto-apply **off** using a privileged
token yourself, then restore the plan-only agent credential. If using a SA key instead
of WIF, paste it only during the later HUMAN credential handoff.

### AGENT — first commit-correlated plan (Phase 6)

```sh
sh "$INFRA_COPILOT_REFERENCES/checks/hcp-current-plan.sh" queue
```

First ensure the committed branch is pushed and has an open pull request, as the
provider-neutral `new-provider-plan` action requires. Wait for HCP to finish, then use
the same helper without `queue` to verify the newest run for the exact commit and its
structured plan; a local CLI plan is not durable Phase 6 evidence.

## Migrating existing GCP resources

Same pattern as every other provider: **import, don't recreate**. GCP resources are
adopted with Terraform 1.5+ `import` blocks and either handwritten HCL or
`terraform plan -generate-config-out`. There is no first-party equivalent to
`cf-terraforming`; `mise exec -- gcloud ... list` + import blocks is the path. See
[`migration.md`](./migration.md#gcp).

## Leaf skeleton (for when it lands)

```text
terraform/gcp/
  versions.tf     # required_providers { google }, cloud { organization=<your-org>, workspaces{name="gcp"} }
  providers.tf    # google provider, WIF impersonation (no key file)
  main.tf         # project-level locals (project_id, region — non-secret, like cloudflare/main.tf)
  *.tf            # one file per resource concern
```

Nothing here ships until the decision is recorded. YAGNI — the repo deliberately carries
no provider it doesn't use.
