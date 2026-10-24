---
name: infra-import
description: "Adopt infrastructure that already exists at a provider into Terraform without recreating it, verifying the plan shows imports rather than creates. Use when a plan wants to create things that are already live; runs after infra-skills:infra-setup reaches green plans. Not for things that do not exist yet (infra-skills:infra-add), nor for removing the spent blocks afterwards (infra-skills:infra-prune)."
allowed-tools: Read, Bash, Edit, Write, Glob, Grep, AskUserQuestion
---

<!--
AI-RULEZ :: GENERATED FILE — DO NOT EDIT
Content-Hash: blake3:c698a50778f22a2921110a47fc4bf57ce0ed3db74847d885049d69f18abda366
Source-Hash: blake3:42c7574fde1dc55e8f96bd54590bf4f29122805f262a3a990b60d7f7f4763ae5
Schema-Version: v1
-->

# infra-import

Adopt resources that **already exist** at a provider (a live apex domain, its DNS records,
existing repos) so Terraform manages them **without recreating** them. This is the
migration path you run once `infra-skills:infra-setup` has proven credentials and green plans.

This file is a **router**: the reusable machinery — actor model, handoff, resume,
preflight — lives in [`../infra/references/protocol.md`](../infra/references/protocol.md); the manifest in
[`../infra/references/steps.yaml`](../infra/references/steps.yaml) (**phase 5**); the canonical runbook in
[`../infra/references/docs/import.md`](../infra/references/docs/import.md) and the cross-provider pattern in
[`../infra/references/migration.md`](../infra/references/migration.md).

> **Why a separate skill?** Import is destructive if done wrong (a stray `create` recreates
> live DNS). It has its own credential (a throwaway **read-only** discovery token, never the
> persistent edit token) and its own success signal. Keeping it distinct from `setup` means you
> only reach for it deliberately, when there's pre-existing infra to adopt.

## Guardrails

`infra-skills:infra-setup` phases 0–4 are green: the target leaf's execution, credential
storage and first plan are proven. Otherwise run `setup` first. The exception is the
Template itself: a repo that pre-dates it cannot have run setup, so `template-adopt` (below)
comes first, and then `infra-setup`, which resumes on the now-rendered repo and proves
phases 0–4, before any import step runs. Obtain plans through
[get-plan](../infra/references/operations.md#get-plan), and verify adoption through
[import-resources](../infra/references/operations.md#import-resources).

## Branch on the provider first

Which provider owns the resources decides the path. Only Cloudflare has a **turnkey**
scripted flow today; every other provider uses the **same import-block pattern by hand**.
Don't run the Cloudflare steps for a GitHub request — you'd mint an irrelevant token and
write `terraform/cloudflare/generated.tf` for repos that live in the GitHub leaf.

- **Cloudflare** (zone, DNS records) — turnkey. The phase-5 steps below drive
  `cf-terraforming` end to end.
- **GitHub repos, or any other provider** — no scripted step yet. Follow the universal
  pattern in [`../infra/references/migration.md`](../infra/references/migration.md): write `import` blocks
  (`import { to = <resource> id = "<existing-id>" }`) in the matching leaf
  (`terraform/github/` for repos), then obtain [get-plan](../infra/references/operations.md#get-plan). Same success signal — imports,
  not creates. No cf-terraforming and no Cloudflare discovery token are involved; use a
  read-only listing (e.g. `gh repo list`) to enumerate ids.

## Adopt the Template first (phase 5)

`template-adopt` runs before any resource import. A repo with no committed
`.copier-answers.yml` and no README Config block — including one created from the old
`infra-template` GitHub template — gets the Template rendered into a scratch directory and
reconciled into the repo, **a human reviewing every conflicting file**. The procedure is
[`../infra/references/docs/import.md`](../infra/references/docs/import.md#adopt-the-template-first). Never run
`copier copy` into the repo itself, and never overwrite a file that differs without the
human's say. Once it is green the later Template update works, and the import steps below run
exactly as before.

## Cloudflare turnkey steps (phase 5)

| Step | Actor | What |
|---|---|---|
| `migrate-discovery-token` | `HUMAN` | Mint a short-lived **read-only** Cloudflare token (DNS·Read, etc.), scoped to the zone, TTL a few hours. Never the persistent edit token. |
| `migrate-import` | `AGENT` | `cf-terraforming generate` + import blocks (`--modern-import-block`) into `terraform/cloudflare/generated.tf`, then obtain the selected plan. |

The manifest's phase-5 steps are Cloudflare-specific — for other providers, there's no
`check` to resume against; verify by hand with the same imports-not-creates plan diff.

Phase 5 has a third step, `prune-spent-imports`, which is provider-neutral and **not this
skill's**: it reads red while one-shot blocks are still committed, and
[`../infra-prune/SKILL.md`](../infra-prune/SKILL.md) owns it. Leave it red here — it only clears after
this import applies.

## Workflow

1. **Adopt the Template, then read config** (shared protocol, Step 0). On a repo with
   no answers file and no Config block, run `template-adopt` first. Then read config and
   export the org vars — [`../infra/references/config.md`](../infra/references/config.md).
   After an adoption, hand off to `infra-skills:infra-setup` and continue here only once its
   phases 0–4 are green; adopting the Template proves none of them.
2. **Resume scan** over `template-adopt`, `template-contract`, `toolchain-pin`,
   `migrate-discovery-token` and `migrate-import` in
   [`../infra/references/steps.yaml`](../infra/references/steps.yaml) — **those five steps only**, not all of
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
3. **Follow the runbook** [`../infra/references/docs/import.md`](../infra/references/docs/import.md) for the
   `cf-terraforming` invocation and the import-block workflow; the cross-provider pattern
   (applying the same generate→import→verify loop to other providers) is in
   [`../infra/references/migration.md`](../infra/references/migration.md).
4. **Respect the actor split** — the human mints/deletes the throwaway token; you generate
   HCL, write import blocks, and read the plan. See
   [`../infra/references/protocol.md`](../infra/references/protocol.md).

## Validation

`terraform plan` shows **every existing resource as "will be imported"** and **nothing as
"will be created."** The step's `check` captures one plan to a private temp file and fails
if any `will be created` appears — a create means Terraform doesn't recognize a live
resource and would duplicate it. If a change *legitimately* adds a new resource alongside
imports, review by hand (and consider whether that new resource belongs in
`infra-skills:infra-add` instead).

**Commit the reviewed HCL before expecting the step to go green.** The check plans what is
committed and refuses a dirty `terraform/cloudflare`, because a local plan reads the
working tree while the execution service applies the commit. So the order is: generate, review, commit, obtain the selected plan to see the imports, then run the check. Committing is not applying —
the apply still happens on merge, confirmed by a human.

Once green: delete the throwaway discovery token, and the resources are under management.

**Then hand off to `infra-skills:infra-prune`** — but only after this PR has merged *and
applied*. The `import` blocks are one-shot; once the run executes them they are inert, and
[`../infra-prune/SKILL.md`](../infra-prune/SKILL.md) removes them in a second PR that ends on
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
