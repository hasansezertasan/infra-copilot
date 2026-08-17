---
name: import
description: "Adopt EXISTING infrastructure that already lives at a provider into Terraform management WITHOUT recreating it — generate HCL + import blocks (cf-terraforming) and verify the plan shows imports, not creates. Use this WHENEVER resources already exist somewhere (a live domain, DNS records, repos already on GitHub) and Terraform doesn't yet manage them — especially to stop a plan from recreating live things. Trigger on: 'our domain/DNS/records already exist, pull them into Terraform', 'the live zone is already up, adopt it', 'bring the existing repos under Terraform management', 'terraform plan wants to CREATE things that already exist', 'stop terraform recreating prod', 'run cf-terraforming', 'generate import blocks', 'migrate existing infra into state'. Run AFTER infra-copilot:setup reaches green plans. Not for standing up a fresh repo (infra-copilot:setup) or provisioning brand-new resources that don't exist yet (infra-copilot:add)."
---

# infra-copilot: import

Adopt resources that **already exist** at a provider (a live apex domain, its DNS records,
existing repos) so Terraform manages them **without recreating** them. This is the
migration path you run once `infra-copilot:setup` has proven credentials and green plans.

This file is a **router**: the reusable machinery — actor model, handoff, resume,
preflight — lives in [`../shared/protocol.md`](../shared/protocol.md); the manifest in
[`../shared/steps.yaml`](../shared/steps.yaml) (**phase 5**); the canonical runbook in
[`../shared/docs/import.md`](../shared/docs/import.md) and the cross-provider pattern in
[`../shared/migration.md`](../shared/migration.md).

> **Why a separate skill?** Import is destructive if done wrong (a stray `create` recreates
> live DNS). It has its own credential (a throwaway **read-only** discovery token, never the
> HCP edit token) and its own success signal. Keeping it distinct from `setup` means you
> only reach for it deliberately, when there's pre-existing infra to adopt.

## Precondition

`infra-copilot:setup` phases 0–4 are green — HCP is reachable, both workspaces exist,
credentials are proven. If not, run `setup` first; import needs a working `cloudflare`
workspace and a green speculative plan to diff against.

## Scope (phase 5)

| Step | Actor | What |
|---|---|---|
| `migrate-discovery-token` | `HUMAN` | Mint a short-lived **read-only** Cloudflare token (DNS·Read, etc.), scoped to the zone, TTL a few hours. Never the HCP edit token. |
| `migrate-import` | `AGENT` | `cf-terraforming generate` + import blocks (`--modern-import-block`) into `terraform/cloudflare/generated.tf`, then `terraform plan`. |

## How to run

1. **Read config first** (shared protocol, Step 0) and export the org vars —
   [`../shared/config.md`](../shared/config.md).
2. **Resume scan** over phase 5 of [`../shared/steps.yaml`](../shared/steps.yaml). The
   discovery token is ephemeral (`check: ~`, no scriptable check) — treat it as a `HUMAN`
   step every run and delete it afterward.
3. **Follow the runbook** [`../shared/docs/import.md`](../shared/docs/import.md) for the
   `cf-terraforming` invocation and the import-block workflow; the cross-provider pattern
   (applying the same generate→import→verify loop to other providers) is in
   [`../shared/migration.md`](../shared/migration.md).
4. **Respect the actor split** — the human mints/deletes the throwaway token; you generate
   HCL, write import blocks, and read the plan. See
   [`../shared/protocol.md`](../shared/protocol.md).

## Success signal

`terraform plan` shows **every existing resource as "will be imported"** and **nothing as
"will be created."** The step's `check` captures one plan to a private temp file and fails
if any `will be created` appears — a create means Terraform doesn't recognize a live
resource and would duplicate it. If a change *legitimately* adds a new resource alongside
imports, review by hand (and consider whether that new resource belongs in
`infra-copilot:add` instead).

Once green: delete the throwaway discovery token, commit `generated.tf`, and the resources
are under management.
