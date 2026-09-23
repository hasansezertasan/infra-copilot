# Provider: GCP (agent-first)

Runbook for adopting Google Cloud as a Phase 6 additional provider. GCP is **opt-in**:
there is no `terraform/gcp/` leaf and no `gcp` HCP workspace until a consuming repo
records the decision below. Everything here was exercised end to end on a real keyless
adoption (~140 resources imported, `0 to add, 0 to change, 0 to destroy`), and the
hazards are listed in roughly the order a first-timer meets them.

## Prerequisite: make the decision (HUMAN + docs)

The provider-neutral `new-provider-decision` entry in [`steps.yaml`](steps.yaml) stays
**red** until GCP is intentionally adopted. Before writing provider code:

1. Add two locked rows to `.infra-copilot/decisions.md`: decision `Provider: gcp` with
   choice `adopt`, and decision `GCP authentication` with choice
   `Workload Identity Federation` (or `service-account key`, with the reason WIF could
   not be arranged). Auth is a decision, not a default: a key is a long-lived secret
   with a rotation burden, and choosing it should be deliberate and visible.
   `new-provider-decision` stays red until both rows are locked, and until the choice
   agrees with the credential inventory in step 3. The choice must be exactly
   `Workload Identity Federation` (the inventory declares `TFC_GCP_PROVIDER_AUTH`) or
   exactly `service-account key` (it declares `GOOGLE_CREDENTIALS` and not
   `TFC_GCP_PROVIDER_AUTH`); any other wording stays red.
2. Note the new leaf in `terraform/README.md`.
3. Add GCP to `.infra-copilot/config.md`'s `additional_providers`, including every HCP
   variable the chosen auth needs — for WIF, those listed under
   [HCP workspace variables](#hcp-workspace-variables); for a key, only
   `GOOGLE_CREDENTIALS` (`category: env`, `sensitive: true`) — plus
   `mise_tools: [gcloud]`, and an initially false fork speculative-plan attestation with
   empty workspace-ID and credential-verification fields. Never mix the two inventories:
   the WIF trust check runs exactly when the inventory declares `TFC_GCP_PROVIDER_AUTH`.
4. Then, and only then, follow the parameterized Phase 6 steps.

## Auth: Workload Identity Federation (keyless)

Prefer **WIF** over a downloaded service-account JSON key. HCP presents a short-lived
OIDC token for each run; GCP exchanges it for temporary credentials of a service account.
**No long-lived key to store, paste, or rotate.** A service-account key is the fallback
only if WIF can't be arranged; it would live as a sensitive HCP var exactly like the
Cloudflare token, with all the rotation burden that implies.

## The actor split

| Action | Actor | Why |
|---|---|---|
| Create GCP project, link billing | **HUMAN** | Billing consent is browser + payment; irreducibly human. |
| Create the WIF pool, provider, and Terraform service account | **HUMAN** | Grants project-IAM authority; runs on the human's own `gcloud` login, never on a credential handed to the agent. |
| Verify the pool, provider condition, and bindings | **AGENT** | Read-only `gcloud ... describe` / `get-iam-policy`. |
| Paste SA key into HCP *(only if not using WIF)* | **HUMAN** | Agent must never see the key. |
| Create the `gcp` HCP workspace | **HUMAN** | The post-handoff mutation needs a temporary user/org token intentionally withheld from the agent. |
| Discover and generate import HCL | **AGENT** | Read-only `gcloud ... list` + `terraform plan -generate-config-out`. |
| First `plan` | **AGENT** | Speculative run in HCP. |

The WIF bootstrap is HUMAN for the same reason workspace creation is: the identity it
creates can grant itself any role on the project (see
[the effective ceiling](#least-privilege-role-lists-overclaim)), so creating it is a
privileged mutation. The agent writes the exact commands; the human runs them.

## Phases

### HUMAN — project + billing

1. Create a GCP project (`gcloud projects create <id>` is possible, but billing linkage
   and the initial org/consent are browser steps). Note the **project ID** and the
   **project number** (`gcloud projects describe <id> --format='value(projectNumber)'`).
2. Link a billing account (browser).

### Toolchain — pin `gcloud`

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

Once the provider entry declares `gcloud` in `mise_tools`, manifest preflight requires an
exact `tools.gcloud` pin and compares it against the installed SDK version — the
`Google Cloud SDK` field of `gcloud version`, not the `core` component, which is a
release date rather than a version. Status reports missing or drifted pins.

### HUMAN — create the WIF trust

Run on the human's own `gcloud` login (`gcloud auth login`), with the values filled in.
`<hcp-org>` and `<workspace>` are the HCP organization and the `gcp` workspace name from
config; `<project-number>` is numeric, not the project ID.

```sh
PROJECT_ID=<project-id>
PROJECT_NUMBER=<project-number>
POOL=hcp-terraform
PROVIDER=hcp-terraform
SA=terraform

mise exec -- gcloud config set project "$PROJECT_ID"
mise exec -- gcloud services enable \
  cloudresourcemanager.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com sts.googleapis.com serviceusage.googleapis.com

mise exec -- gcloud iam workload-identity-pools create "$POOL" \
  --location=global --display-name="HCP Terraform"

mise exec -- gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
  --location=global --workload-identity-pool="$POOL" \
  --issuer-uri="https://app.terraform.io" \
  --attribute-mapping="google.subject=assertion.sub,attribute.aud=assertion.aud,attribute.terraform_run_phase=assertion.terraform_run_phase,attribute.terraform_organization_name=assertion.terraform_organization_name,attribute.terraform_workspace_name=assertion.terraform_workspace_name,attribute.terraform_workspace_id=assertion.terraform_workspace_id" \
  --attribute-condition="assertion.terraform_organization_name == '<hcp-org>' && assertion.terraform_workspace_name == '<workspace>'"

mise exec -- gcloud iam service-accounts create "$SA" --display-name="HCP Terraform (gcp workspace)"

# Only principals that passed the provider's condition exist in the pool; let them
# impersonate the service account.
mise exec -- gcloud iam service-accounts add-iam-policy-binding \
  "$SA@$PROJECT_ID.iam.gserviceaccount.com" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/*"

# Then grant the service account the project roles its resources need, one
# `gcloud projects add-iam-policy-binding` per role — and read the next section first.
```

What each piece is for:

- **Issuer** `https://app.terraform.io` — no trailing slash. Every HCP customer's tokens
  come from this issuer, so the issuer alone trusts the whole world.
- **Attribute condition** — the security-relevant line. Without it, *any* workspace in
  *any* HCP organization can impersonate the service account. Condition on the
  organization **and** the workspace; the workspace name alone is not enough, because
  another org can create a workspace with the same name. HashiCorp's own minimum is
  "the audience and the name of the organization". For a condition that survives
  renames, match `assertion.terraform_workspace_id` (`ws-…`, from the fork-safety step)
  instead of the name.
- **Audience** — leave `--allowed-audiences` unset. HCP's default audience is the
  provider's full resource name (`//iam.googleapis.com/projects/<n>/locations/global/workloadIdentityPools/<pool>/providers/<provider>`),
  which is exactly what GCP accepts by default. Set both sides only if you set
  `TFC_GCP_WORKLOAD_IDENTITY_AUDIENCE`.

Optional, and worth it with this repo's plan-only posture: create a second, read-only
service account for plans and set `TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL` to it, keeping the
privileged one for `TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL`. Then narrow each
`workloadIdentityUser` binding by the mapped run phase instead of the pool-wide `/*`:

```sh
# apply account: only apply-phase tokens may impersonate it
--member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.terraform_run_phase/apply"
# plan account: only plan-phase tokens
--member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/attribute.terraform_run_phase/plan"
```

A speculative plan — including one a pull request triggers — then cannot mint
apply-grade credentials, even if the workspace variables were edited. Keep one active
provider per pool: a second provider (for GitHub Actions, say) belongs in its own pool.

### AGENT — verify the trust (read-only)

The `new-provider-gcp-wif-trust` step runs
`sh "$INFRA_COPILOT_REFERENCES/checks/gcp-wif-trust.sh"` on every resume and status scan.
It locates the provider and service accounts from the workspace's own non-sensitive
`TFC_GCP_*` variables, then fails unless all of these hold:

- no variable set is attached (its variables are invisible to the workspace vars API);
- the issuer is exactly `https://app.terraform.io` and the provider is active;
- the provider is the pool's only active provider — the pool-wide `/*` member admits
  every provider's identities, so a sibling with a weaker condition would bypass this one;
- the condition binds both the organization and the workspace (forms below);
- every member of `workloadIdentityUser` on the service accounts is this pool's, and no
  federated (`principal://`, `principalSet://`) member outside it holds *any* role on
  them — Token Creator mints tokens just as well;
- no federated principal outside the pool holds any role on the pool itself (its own
  IAM policy, which the project policy does not show);
- no federated principal outside the pool holds, on the service accounts' projects or
  the pool's (where grants are inherited), a role whose permissions reach them. Roles are
  resolved with `gcloud iam roles describe` and judged by permission, not name — service
  agent roles such as `roles/cloudbuild.serviceAgent` also mint tokens. The permissions
  are minting tokens or signatures as an account, creating, uploading, or re-enabling
  its keys (a key is a login), `actAs`, setting account, project, or pool IAM policy, and
  changing the pool or its providers (which could loosen this very condition). Such a grant under an IAM
  condition exits 2: the check does not evaluate conditions, so confirm by hand that it
  excludes the run accounts and the pool;
- when plan and apply use different accounts, the apply account (and those project
  grants) admit only `attribute.terraform_run_phase/apply`, and the provider maps that
  attribute from `assertion.terraform_run_phase` — a constant would label every run an
  apply.

It exits 2, not 1, when `gcloud` cannot read what it needs, so a missing login is never
mistaken for a broken trust. **Not covered:** grants inherited from folders or the
organization; audit those by hand if your hierarchy uses them. The step runs unless the credential inventory
is a list without `TFC_GCP_PROVIDER_AUTH` — a key-based adoption, or another provider —
so an unreadable inventory runs the check rather than skipping it.

The condition is matched against an allowlist, not searched. First, it may contain only
`A-Z a-z 0-9 _ . : = & ' ( ) -` and spaces: that rules out double quotes (CEL allows
`"` inside `'…'`, so mixed quotes can hide `|| true` inside an apparent literal),
backslash escapes, `//` comments, `||`, `!`, and ternaries. Then it must be `&&`-joined
terms, each exactly one of these forms — a term in any other form fails even if it is
strict, because a substring search would also accept `startsWith(...) == false`:

- `assertion.terraform_organization_name == '<hcp-org>'`
- `assertion.terraform_workspace_name == '<workspace>'` or
  `assertion.terraform_workspace_id == '<ws-id>'`
- `assertion.sub.startsWith('organization:<hcp-org>:project:<project>:workspace:<workspace>:')`
  — binds both at once. The trailing `:` is required: without it, workspace `gcp` is
  also a prefix of workspace `gcp-evil`. HashiCorp's published example omits it.
- `assertion.terraform_run_phase == '<phase>'` or
  `assertion.terraform_project_name == '<project>'` — optional further narrowing

Only `assertion.*` claims are accepted, not mapped `attribute.*` names, and only
single-quoted literals. The audience needs no term: GCP already rejects a token whose
audience is not the provider's own. To look by hand:

```sh
mise exec -- gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --location=global --workload-identity-pool="$POOL" \
  --format='value(attributeCondition,oidc.issuerUri,state)'
mise exec -- gcloud iam service-accounts get-iam-policy "$SA@$PROJECT_ID.iam.gserviceaccount.com"
```

An empty condition is a failed check, not a style note.

### HCP workspace variables

For WIF, declare these in the provider entry's `credential_variables`, all
`category: env`, `sensitive: false` — none of them is a secret, which is the point of
WIF:

| Key | Value |
|---|---|
| `TFC_GCP_PROVIDER_AUTH` | `true` |
| `TFC_GCP_PRINCIPAL_TYPE` | `service_account` |
| `TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL` | `terraform@<project-id>.iam.gserviceaccount.com` |
| `TFC_GCP_WORKLOAD_PROVIDER_NAME` | `projects/<project-number>/locations/global/workloadIdentityPools/<pool>/providers/<provider>` |

`TFC_GCP_WORKLOAD_PROVIDER_NAME` can instead be the triple `TFC_GCP_PROJECT_NUMBER`,
`TFC_GCP_WORKLOAD_POOL_ID`, `TFC_GCP_WORKLOAD_PROVIDER_ID`; pick one form. Add
`TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL` / `TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL` if you split
plan and apply identities.

A key-based adoption declares only `GOOGLE_CREDENTIALS` (`category: env`,
`sensitive: true`, the key JSON pasted by the human) and none of the `TFC_GCP_*`
variables, so `new-provider-gcp-wif-trust` is skipped.

> **With WIF, never set `GOOGLE_CREDENTIALS` or `GOOGLE_APPLICATION_CREDENTIALS`** in the workspace
> (or an attached variable set). HashiCorp's docs are explicit that both conflict with
> dynamic credentials. It is the first thing people reach for when auth fails, and it
> makes the failure worse, not better. The `new-provider-credentials` inventory check
> rejects undeclared variables, so an added one turns that step red.

### Provider block

A single, default dynamic-credentials configuration needs **no `credentials` argument**:
HCP injects the credentials into the run environment and the provider picks them up.
Locally (and in object-storage mode, after `google-github-actions/auth`), the same block
falls back to Application Default Credentials, so `gcloud auth application-default login`
is all a local-execution `validate` or `console` needs.

```hcl
# terraform/gcp/providers.tf
provider "google" {
  project = local.project_id
  region  = local.region
}
```

With a remote-execution HCP workspace, a `terraform plan` typed on a laptop still runs in
HCP with the dynamic credentials; ADC is only used for work that executes locally.

Only if you use **tagged** configurations (several service accounts, provider aliases)
does HCP hand credentials through a variable, and then the provider must read it. Keep
the variable optional so local runs still fall back to ADC:

```hcl
variable "tfc_gcp_dynamic_credentials" {
  description = "Set by HCP Terraform for tagged GCP dynamic-credential configurations."
  sensitive   = true
  default     = null
  type = object({
    default = object({ credentials = string })
    aliases = map(object({ credentials = string }))
  })
}

provider "google" {
  project     = local.project_id
  region      = local.region
  credentials = try(var.tfc_gcp_dynamic_credentials.default.credentials, null)
}
```

`try(...)` collapses to `null` when the variable is unset, which is the provider's
"use ADC" value.

### HUMAN — HCP workspace bootstrap (Phase 6)

Follow the provider-neutral `new-provider-workspace-bootstrap`, workspace verification,
and plan-access handoffs in Phase 6. Create `gcp` with working dir `terraform/gcp`, path
filter `terraform/gcp/**`, remote execution, and auto-apply **off** using a privileged
token yourself, then restore the plan-only agent credential. Set the variables above
during the later `new-provider-credentials` handoff. If using a SA key instead of WIF,
paste it only during that handoff.

### AGENT — first commit-correlated plan (Phase 6)

```sh
sh "$INFRA_COPILOT_REFERENCES/checks/hcp-current-plan.sh" queue
```

First ensure the committed branch is pushed and has an open pull request, as the
provider-neutral `new-provider-plan` action requires. Wait for HCP to finish, then use
the same helper without `queue` to verify the newest run for the exact commit and its
structured plan; a local CLI plan is not durable Phase 6 evidence.

## Adoption hazards

Each of these produced a config that `validate` and `fmt` accept and a plan that looks
plausible. Several fail silently or weeks later, which is why they are rules here rather
than advice.

### `disable_on_destroy = false` on every `google_project_service`

Before google provider v7, `disable_on_destroy` defaulted to `true`: **deleting a
`google_project_service` line from config disables that API on the live project.** On a
project running GKE or Cloud SQL, a config cleanup becomes an outage. v7 removed the
default, but generated config, older pins, and copied snippets still carry `true`.

Set `disable_on_destroy = false` explicitly on every `google_project_service`, whatever
the provider version. Removing the resource then only stops Terraform tracking the
service; the API stays enabled. This is the highest-severity item on the list, and it is
invisible until someone tidies the file.

### `google_project_iam_member`, never `_binding` or `_policy`

`_member` is non-authoritative: Terraform manages only the exact (role, member) pairs
declared and never removes one it doesn't know about. `_binding` is authoritative per
role and `_policy` for the whole project — either will delete bindings absent from
config, including ones a human or another system added, and `_policy` can lock everyone
out. For an adoption this is not a style preference; it is the difference between
additive and destructive.

### The identity that manages its own IAM can revoke itself

The Terraform service account's own `google_project_iam_member` bindings show up in
discovery like everything else, and adopting them looks tidy. It is a trap: the account
holds `roles/resourcemanager.projectIamAdmin`, so a plan that drops one of those blocks
revokes the account's ability to grant it back, and a partial apply leaves no recovery
path *through Terraform*.

**Don't adopt the bootstrap identity.** The WIF pool, its provider, the Terraform
service account, its `workloadIdentityUser` binding, and its project-role bindings were
created by the HUMAN bootstrap above and stay outside the leaf — exclude them during
[discovery](#what-not-to-adopt), exactly like service agents. The same holds for any
provider whose credential lives in the state it manages.

If you adopt them anyway, keep them in a hand-maintained file (see
[regeneration](migration.md#-generate-config-out-failure-modes)) with
`lifecycle { prevent_destroy = true }` on each, which turns a replacement or an in-place
destroy into a plan-time error. Know its limit: `prevent_destroy` lives in the resource
block, so **deleting the block deletes the guard** and the next plan destroys the
binding. To stop managing one, retire it without revoking it (Terraform 1.7+):

```hcl
removed {
  from = google_project_iam_member.terraform_project_iam_admin
  lifecycle { destroy = false }
}
```

### Least-privilege role lists overclaim

A role list scoped one role per resource type reads as minimal. But
`roles/resourcemanager.projectIamAdmin` together with `roles/iam.serviceAccountAdmin`
lets the account grant itself — or a service account it creates — any role on the
project. The direct grants are scoped; the **effective ceiling is project-wide**. Say so
in the decision's rationale instead of letting a reader infer a tighter boundary. The
plan/apply service-account split above is what actually narrows exposure: plans never
hold the IAM-admin roles.

### What not to adopt

Google creates and maintains a class of resources in every project. Adopting them makes
Terraform fight the owning service. The test for each discovered resource: *did a Google
service create this, and does it still maintain it?* If yes, don't adopt it.

- **Service agents.** Filtering on the `gcp-sa-*` domain is **insufficient**; agents
  also live on `container-analysis`, `containerregistry`, `service-networking`, the App
  Engine service domain, and others. Most follow the canonical form
  `serviceAccount:service-<project-number>@…`, which is the better discriminator — but
  not all: the Google APIs service agent is `<project-number>@cloudservices.gserviceaccount.com`.
  Exclude both patterns, then read what is left rather than trusting the filter.
- **Default service accounts.** `<project-id>@appspot.gserviceaccount.com`,
  `<project-number>-compute@developer.gserviceaccount.com`, and the legacy
  `<project-number>@cloudbuild.gserviceaccount.com` are auto-created; Terraform deleting
  one breaks App Engine, Compute, or Cloud Build.
- **Google-created buckets.** These look like ordinary resources: the App Engine default
  (`<project-id>.appspot.com`) and staging (`staging.<project-id>.appspot.com`) buckets,
  the Cloud Build bucket (`<project-id>_cloudbuild`), and Infrastructure Manager's
  `<project-number>-<region>-blueprint-config` buckets. The staging bucket carries a
  service-managed delete lifecycle rule, so adopting it makes Terraform revert App Engine
  every time that rule changes.
- **The bootstrap identity** — see above.

An exclusion that looks complete but matches only one domain is worse than none: it
produces a config you *believe* is clean.

### Adoption scope order

Foundation first, in one pass: enabled services, service accounts, project IAM
bindings, buckets, Artifact Registry repositories. These are declarative, carry no
downtime risk, and a misread plan cannot destroy data.

Defer GKE, Cloud SQL, Compute instances, and VPC/firewall rules to their own passes, one
resource type at a time. Those are live systems where a misread import proposes
**replacement**.

## Migrating existing GCP resources

Same pattern as every other provider: **import, don't recreate**. There is no
first-party equivalent to `cf-terraforming`; `mise exec -- gcloud ... list` + Terraform
1.5+ `import` blocks + `terraform plan -generate-config-out` is the path. The import-ID
table, the generator's two failure modes, and the verification checklist are in
[`migration.md`](./migration.md#gcp).

## Leaf skeleton

```text
terraform/gcp/
  versions.tf     # required_providers { google }, cloud { organization=<your-org>, workspaces{name="gcp"} }
  providers.tf    # google provider, no credentials argument (dynamic credentials / ADC)
  main.tf         # project-level locals (project_id, region — non-secret, like cloudflare/main.tf)
  imports.tf      # one-shot import blocks; removed by the prune PR after the apply
  generated.tf    # -generate-config-out output, kept purely generated
  *.tf            # hand-maintained resources, one file per concern
```

Nothing here ships until the decision is recorded. YAGNI — a repo carries no provider it
doesn't use.
