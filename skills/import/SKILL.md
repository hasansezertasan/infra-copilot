---
name: import
description: "Adopt infrastructure that already exists at a provider into Terraform without recreating it, verifying the plan shows imports rather than creates. Use when a plan wants to create things that are already live; runs after infra-copilot:setup reaches green plans. Not for things that do not exist yet (infra-copilot:add), nor for removing the spent blocks afterwards (infra-copilot:prune)."
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:8d2bc00a51ff17068c38722f40181449679305efec50d15e84a8edaba13f1ff6
Source-Hash: blake3:da0d0850d69ff4a20c9cbbefe9088a8fe5ba2c636a99b00a89d6fafe6456e7b0
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
> persistent edit token) and its own success signal. Keeping it distinct from `setup` means you
> only reach for it deliberately, when there's pre-existing infra to adopt.

## Guardrails

`infra-copilot:setup` phases 0–4 are green: the target leaf's execution, credential
storage and first plan are proven. Otherwise run `setup` first. Obtain plans through
[get-plan](../infra-copilot/references/operations.md#get-plan), and verify adoption through
[import-resources](../infra-copilot/references/operations.md#import-resources).

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
  (`terraform/github/` for repos), then obtain [get-plan](../infra-copilot/references/operations.md#get-plan). Same success signal — imports,
  not creates. No cf-terraforming and no Cloudflare discovery token are involved; use a
  read-only listing (e.g. `gh repo list`) to enumerate ids.

## Cloudflare turnkey steps (phase 5)

| Step | Actor | What |
|---|---|---|
| `migrate-discovery-token` | `HUMAN` | Mint a short-lived **read-only** Cloudflare token (DNS·Read, etc.), scoped to the zone, TTL a few hours. Never the persistent edit token. |
| `migrate-import` | `AGENT` | `cf-terraforming generate` + import blocks (`--modern-import-block`) into `terraform/cloudflare/generated.tf`, then obtain the selected plan. |

The manifest's phase-5 steps are Cloudflare-specific — for other providers, there's no
`check` to resume against; verify by hand with the same imports-not-creates plan diff.

Phase 5 has a third step, `prune-spent-imports`, which is provider-neutral and **not this
skill's**: it reads red while one-shot blocks are still committed, and
[`../prune/SKILL.md`](../prune/SKILL.md) owns it. Leave it red here — it only clears after
this import applies.

## Workflow

1. **Read config first** (shared protocol, Step 0) and export the org vars —
   [`../infra-copilot/references/config.md`](../infra-copilot/references/config.md).
2. **Resume scan** over `migrate-discovery-token` and `migrate-import` in
   [`../infra-copilot/references/steps.yaml`](../infra-copilot/references/steps.yaml) — **those two steps only**, not all of
   phase 5. `prune-spent-imports` is red for the whole of a correct import and belongs to
   another skill; scanning it here would make the shared protocol resume at it and run the
   prune procedure before this apply has landed. The
   discovery token is ephemeral (`check: ~`, no scriptable check) — treat it as a `HUMAN`
   step every run and delete it afterward.

   A green `migrate-import` does **not** mean there is nothing left to adopt. Terraform
   cannot see an object it does not manage, so a repo whose first adoption applied plans
   `No changes.` even with a hundred untouched records still live at the provider. Green
   only says the committed config has no *pending* imports. When the user names something
   to adopt, run discovery and confirm that thing is in state — never close the request on
   the resume scan alone.
3. **Follow the runbook** [`../infra-copilot/references/docs/import.md`](../infra-copilot/references/docs/import.md) for the
   `cf-terraforming` invocation and the import-block workflow; the cross-provider pattern
   (applying the same generate→import→verify loop to other providers) is in
   [`../infra-copilot/references/migration.md`](../infra-copilot/references/migration.md).
4. **Respect the actor split** — the human mints/deletes the throwaway token; you generate
   HCL, write import blocks, and read the plan. See
   [`../infra-copilot/references/protocol.md`](../infra-copilot/references/protocol.md).

## Validation

`terraform plan` shows **every existing resource as "will be imported"** and **nothing as
"will be created."** The step's `check` captures one plan to a private temp file and fails
if any `will be created` appears — a create means Terraform doesn't recognize a live
resource and would duplicate it. If a change *legitimately* adds a new resource alongside
imports, review by hand (and consider whether that new resource belongs in
`infra-copilot:add` instead).

**Commit the reviewed HCL before expecting the step to go green.** The check plans what is
committed and refuses a dirty `terraform/cloudflare`, because a local plan reads the
working tree while the execution service applies the commit. So the order is: generate, review, commit, obtain the selected plan to see the imports, then run the check. Committing is not applying —
the apply still happens on merge, confirmed by a human.

Once green: delete the throwaway discovery token, and the resources are under management.

**Then hand off to `infra-copilot:prune`** — but only after this PR has merged *and
applied*. The `import` blocks are one-shot; once the run executes them they are inert, and
[`../prune/SKILL.md`](../prune/SKILL.md) removes them in a second PR that ends on
`No changes.` Removing them any earlier turns every pending import into a create.

## Example

The shape to expect for a zone already serving traffic:

```text
# terraform/cloudflare
Plan: 0 to add, 0 to change, 0 to destroy.
  ~ cloudflare_dns_record.this["www"] will be imported
  ~ cloudflare_zone.this          will be imported
```

`0 to add` is the point. A single `will be created` for a record that is already live
means Terraform does not recognise it and an apply would duplicate it.
