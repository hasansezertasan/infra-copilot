---
name: import
description: "Adopt EXISTING infrastructure that already lives at a provider into Terraform management WITHOUT recreating it — generate HCL + import blocks (cf-terraforming) and verify the plan shows imports, not creates. Use this WHENEVER resources already exist somewhere (a live domain, DNS records, repos already on GitHub) and Terraform doesn't yet manage them — especially to stop a plan from recreating live things. Trigger on: 'our domain/DNS/records already exist, pull them into Terraform', 'the live zone is already up, adopt it', 'bring the existing repos under Terraform management', 'terraform plan wants to CREATE things that already exist', 'stop terraform recreating prod', 'run cf-terraforming', 'generate import blocks', 'migrate existing infra into state'. Run AFTER infra-copilot:setup reaches green plans. Not for standing up a fresh repo (infra-copilot:setup) or provisioning brand-new resources that don't exist yet (infra-copilot:add)."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:23c08b05d4be5136cef653a3b77a762a6b21d8d8d1ebd9103a7438f42c4171b5
Source-Hash: blake3:82270fcd354335dcf4a9f860a7b106f87ff7b707ad351472abded6a1bbd75335
Schema-Version: v1
-->

# infra-copilot: import

Adopt resources that **already exist** at a provider (a live apex domain, its DNS records,
existing repos) so Terraform manages them **without recreating** them. This is the
migration path you run once `infra-copilot:setup` has proven credentials and green plans.

This file is a **router**: the reusable machinery — actor model, handoff, resume,
preflight — lives in [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md); the manifest in
[`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml) (**phase 5**); the canonical runbook in
[`../infra-copilot/references/docs/import.md`](../infra-copilot/references/docs/import.md) and the cross-provider pattern in
[`../infra-copilot/references/migration.md`](../infra-copilot/references/migration.md).

> **Why a separate skill?** Import is destructive if done wrong (a stray `create` recreates
> live DNS). It has its own credential (a throwaway **read-only** discovery token, never the
> HCP edit token) and its own success signal. Keeping it distinct from `setup` means you
> only reach for it deliberately, when there's pre-existing infra to adopt.

## Precondition

`infra-copilot:setup` phases 0–4 are green — HCP is reachable, both workspaces exist,
credentials are proven. If not, run `setup` first; import needs the target provider's
workspace working (the `cloudflare` leaf for a zone/DNS import, `github-org` for repos) and
a green speculative plan to diff the imports against.

## Branch on the provider first

Which provider owns the resources decides the path. Only Cloudflare has a **turnkey**
scripted flow today; every other provider uses the **same import-block pattern by hand**.
Don't run the Cloudflare steps for a GitHub request — you'd mint an irrelevant token and
write `terraform/cloudflare/generated.tf` for repos that live in the GitHub leaf.

- **Cloudflare** (zone, DNS records) — turnkey. The phase-5 steps below drive
  `cf-terraforming` end to end.
- **GitHub repos, or any other provider** — no scripted step yet. Follow the universal
  pattern in [`../infra-copilot/references/migration.md`](../infra-copilot/references/migration.md): write `import` blocks
  (`import { to = <resource> id = "<existing-id>" }`) in the matching leaf
  (`terraform/github/` for repos), then `terraform plan`. Same success signal — imports,
  not creates. No cf-terraforming and no Cloudflare discovery token are involved; use a
  read-only listing (e.g. `gh repo list`) to enumerate ids.

## Cloudflare turnkey steps (phase 5)

| Step | Actor | What |
|---|---|---|
| `migrate-discovery-token` | `HUMAN` | Mint a short-lived **read-only** Cloudflare token (DNS·Read, etc.), scoped to the zone, TTL a few hours. Never the HCP edit token. |
| `migrate-import` | `AGENT` | `cf-terraforming generate` + import blocks (`--modern-import-block`) into `terraform/cloudflare/generated.tf`, then `terraform plan`. |

The manifest's phase-5 steps are Cloudflare-specific — for other providers, there's no
`check` to resume against; verify by hand with the same imports-not-creates plan diff.

## How to run

1. **Read config first** (shared protocol, Step 0) and export the org vars —
   [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Resume scan** over phase 5 of [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml). The
   discovery token is ephemeral (`check: ~`, no scriptable check) — treat it as a `HUMAN`
   step every run and delete it afterward.
3. **Follow the runbook** [`../infra-copilot/references/docs/import.md`](../infra-copilot/references/docs/import.md) for the
   `cf-terraforming` invocation and the import-block workflow; the cross-provider pattern
   (applying the same generate→import→verify loop to other providers) is in
   [`../infra-copilot/references/migration.md`](../infra-copilot/references/migration.md).
4. **Respect the actor split** — the human mints/deletes the throwaway token; you generate
   HCL, write import blocks, and read the plan. See
   [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md).

## Success signal

`terraform plan` shows **every existing resource as "will be imported"** and **nothing as
"will be created."** The step's `check` captures one plan to a private temp file and fails
if any `will be created` appears — a create means Terraform doesn't recognize a live
resource and would duplicate it. If a change *legitimately* adds a new resource alongside
imports, review by hand (and consider whether that new resource belongs in
`infra-copilot:add` instead).

Once green: delete the throwaway discovery token, commit `generated.tf`, and the resources
are under management.
