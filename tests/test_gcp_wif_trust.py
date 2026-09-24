"""Behavioural tests for the shipped gcp-wif-trust check.

The check exists because a mis-scoped Workload Identity Federation trust is invisible
to every other signal: the plan is green whether or not another HCP organization could
also impersonate the service account. These run the *shipped* script with `curl` and
`gcloud` stubbed on PATH, one case per state it must tell apart.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills/infra-copilot/references/checks/gcp-wif-trust.sh"

POOL = "projects/123/locations/global/workloadIdentityPools/hcp-terraform"
PROVIDER_NAME = f"{POOL}/providers/hcp-terraform"
SA = "terraform@proj.iam.gserviceaccount.com"
SCOPED = (
    "assertion.terraform_organization_name == 'acme' && "
    "assertion.terraform_workspace_name == 'gcp'"
)


def env_var(key: str, value: str, sensitive: bool = False) -> dict:
    return {
        "attributes": {
            "key": key,
            "category": "env",
            "sensitive": sensitive,
            "value": None if sensitive else value,
        }
    }


# What `gcloud iam roles describe` returns per role, trimmed to what matters. The check
# judges these permissions, not role names.
ROLE_PERMISSIONS = {
    "roles/iam.serviceAccountTokenCreator": ["iam.serviceAccounts.getAccessToken",
                                             "iam.serviceAccounts.signBlob"],
    "roles/iam.serviceAccountKeyAdmin": ["iam.serviceAccountKeys.create"],
    "roles/iam.serviceAccountAdmin": ["iam.serviceAccounts.setIamPolicy"],
    "roles/iam.serviceAccountUser": ["iam.serviceAccounts.actAs"],
    "roles/iam.workloadIdentityPoolAdmin": ["iam.workloadIdentityPoolProviders.update"],
    "roles/resourcemanager.projectIamAdmin": ["resourcemanager.projects.setIamPolicy"],
    "roles/editor": ["iam.serviceAccountKeys.create", "storage.buckets.create"],
    "roles/cloudbuild.serviceAgent": ["iam.serviceAccounts.getAccessToken",
                                      "cloudbuild.builds.create"],
    "roles/storage.admin": ["storage.buckets.create", "storage.objects.delete"],
    "projects/proj/roles/keyUploader": ["iam.serviceAccountKeys.upload"],
    "projects/proj/roles/keyEnabler": ["iam.serviceAccountKeys.enable"],
    "projects/proj/roles/poolPolicy": ["iam.workloadIdentityPools.setIamPolicy"],
    "roles/iam.roleAdmin": ["iam.roles.update", "iam.roles.create"],
}

DEFAULT_VARS = [
    env_var("TFC_GCP_PROVIDER_AUTH", "true"),
    env_var("TFC_GCP_PRINCIPAL_TYPE", "service_account"),
    env_var("TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL", SA),
    env_var("TFC_GCP_WORKLOAD_PROVIDER_NAME", PROVIDER_NAME),
]


@unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
class GcpWifTrustTests(unittest.TestCase):
    def run_check(
        self,
        *,
        variables: list[dict] | None = None,
        condition: str = SCOPED,
        issuer: str = "https://app.terraform.io",
        state: str = "ACTIVE",
        members: list[str] | None = None,
        policies: dict[str, list[str]] | None = None,
        mapping: dict[str, str] | None = None,
        siblings: list[dict] | None = None,
        extra_bindings: list[dict] | None = None,
        project_bindings: list[dict] | None = None,
        varsets: int = 0,
        role_describe_error: bool = False,
        pool_bindings: list[dict] | None = None,
        tf_files: dict[str, str] | None = None,
        project_policies: dict[str, list[dict]] | None = None,
        describe_error: str = "",
        policy_error: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        variables = DEFAULT_VARS if variables is None else variables
        members = [f"principalSet://iam.googleapis.com/{POOL}/*"] if members is None else members
        provider = {
            "name": PROVIDER_NAME,
            "state": state,
            "oidc": {"issuerUri": issuer},
            "attributeCondition": condition,
            "attributeMapping": {
                "google.subject": "assertion.sub",
                "attribute.terraform_run_phase": "assertion.terraform_run_phase",
            } if mapping is None else mapping,
        }
        providers = [provider] + (siblings or [])

        def policy_for(entries: list[str]) -> dict:
            return {"bindings": [
                {"role": "roles/iam.workloadIdentityUser", "members": entries},
                *(extra_bindings or []),
            ]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workspace.json").write_text(json.dumps({"data": {
                "id": "ws-abc123",
                "relationships": {"project": {"data": {"id": "prj-1", "type": "projects"}}},
            }}))
            (root / "project-hcp.json").write_text(
                json.dumps({"data": {"id": "prj-1", "attributes": {"name": "Default Project"}}})
            )
            (root / "vars.json").write_text(
                json.dumps({"data": variables, "meta": {"pagination": {"next-page": None}}})
            )
            (root / "provider.json").write_text(json.dumps(provider))
            (root / "providers.json").write_text(json.dumps(providers))
            (root / "policy.json").write_text(json.dumps(policy_for(members)))
            (root / "project.json").write_text(json.dumps({"bindings": project_bindings or []}))
            project_cases = ""
            for index, (project, bindings) in enumerate((project_policies or {}).items()):
                (root / f"project{index}.json").write_text(json.dumps({"bindings": bindings}))
                project_cases += (
                    f"  *projects\\ get-iam-policy\\ {project}\\ *) cat '{root}/project{index}.json' ;;\n"
                )
            (root / "pool.json").write_text(json.dumps({"bindings": pool_bindings or []}))
            role_cases = ""
            for index, (role, permissions) in enumerate(ROLE_PERMISSIONS.items()):
                (root / f"role{index}.json").write_text(
                    json.dumps({"name": role, "includedPermissions": permissions})
                )
                # Trailing space-star: the role is followed by --format=json.
                role_cases += f"  *roles\\ describe\\ {role}\\ *) cat '{root}/role{index}.json' ;;\n"
            if role_describe_error:
                role_cases = "  *roles\\ describe*) echo 'PERMISSION_DENIED' >&2; exit 1 ;;\n"
            (root / "varsets.json").write_text(
                json.dumps({"data": [{"id": f"varset-{i}"} for i in range(varsets)]})
            )
            policy_cases = ""
            for index, (email, entries) in enumerate((policies or {}).items()):
                (root / f"policy{index}.json").write_text(json.dumps(policy_for(entries)))
                policy_cases += f"  *get-iam-policy\\ {email}*) cat '{root}/policy{index}.json' ;;\n"
            (root / "curl").write_text(
                "#!/bin/sh\n"
                'for arg in "$@"; do case "$arg" in\n'
                f"  */varsets*) cat '{root}/varsets.json'; exit 0 ;;\n"
                f"  */vars*) cat '{root}/vars.json'; exit 0 ;;\n"
                f"  */workspaces/gcp) cat '{root}/workspace.json'; exit 0 ;;\n"
                f"  */projects/prj-1) cat '{root}/project-hcp.json'; exit 0 ;;\n"
                "esac; done\nexit 22\n"
            )
            describe = (
                f"echo '{describe_error}' >&2; exit 1"
                if describe_error
                else f"cat '{root}/provider.json'"
            )
            policy_cmd = (
                "echo 'PERMISSION_DENIED' >&2; exit 1"
                if policy_error
                else f"cat '{root}/policy.json'"
            )
            (root / "gcloud").write_text(
                "#!/bin/sh\n"
                'case "$*" in\n'
                f"  *providers\\ describe*) {describe} ;;\n"
                f"  *providers\\ list*) cat '{root}/providers.json' ;;\n"
                f"  *workload-identity-pools\\ get-iam-policy*) cat '{root}/pool.json' ;;\n"
                + project_cases
                + f"  *projects\\ get-iam-policy*) cat '{root}/project.json' ;;\n"
                + role_cases
                + ("" if policy_error else policy_cases)
                + f"  *get-iam-policy*) {policy_cmd} ;;\n"
                "  *) exit 1 ;;\nesac\n"
            )
            for stub in ("curl", "gcloud"):
                (root / stub).chmod(0o755)
            repo = root / "repo"
            repo.mkdir()
            for relative, body in (tf_files or {}).items():
                target = repo / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body)
            return subprocess.run(
                ["/bin/sh", str(SCRIPT)],
                cwd=repo,
                env={
                    **os.environ,
                    "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                    "ORG": "acme",
                    "NEW_PROVIDER_WORKSPACE": "gcp",
                    "NEW_PROVIDER": "gcp",
                    "hcp_api": "https://app.terraform.io/api/v2",
                    "HCP_TOKEN": "t",
                },
                capture_output=True,
                text=True,
            )

    def assert_exit(self, result: subprocess.CompletedProcess[str], code: int) -> None:
        self.assertEqual(result.returncode, code, result.stderr)

    def test_scoped_trust_passes(self) -> None:
        self.assert_exit(self.run_check(), 0)

    def test_workspace_id_and_sub_prefix_forms_pass(self) -> None:
        for condition in (
            "assertion.terraform_organization_name == 'acme' && "
            "assertion.terraform_workspace_id == 'ws-abc123'",
            "assertion.sub.startsWith('organization:acme:project:Default Project:workspace:gcp:')",
        ):
            with self.subTest(condition=condition):
                self.assert_exit(self.run_check(condition=condition), 0)

    def test_split_provider_triple_is_accepted(self) -> None:
        variables = [
            *DEFAULT_VARS[:3],
            env_var("TFC_GCP_PROJECT_NUMBER", "123"),
            env_var("TFC_GCP_WORKLOAD_POOL_ID", "hcp-terraform"),
            env_var("TFC_GCP_WORKLOAD_PROVIDER_ID", "hcp-terraform"),
        ]
        self.assert_exit(self.run_check(variables=variables), 0)

    def test_unscoped_or_under_scoped_conditions_fail(self) -> None:
        for condition in (
            "",
            "assertion.terraform_workspace_name == 'gcp'",       # any org's "gcp"
            "assertion.terraform_organization_name == 'acme'",   # every workspace
            "assertion.terraform_organization_name == 'acme-evil' && "
            "assertion.terraform_workspace_name == 'gcp'",
            SCOPED + " || true",
            "!(" + SCOPED + ")",
            "assertion.sub.startsWith('organization:acme:project:Default Project:workspace:gcp-other:')",
            # No delimiter: also a prefix of workspace "gcp-evil".
            "assertion.sub.startsWith('organization:acme:project:p:workspace:gcp')",
            # Unverifiable narrowing terms are refused outright.
            SCOPED + " && assertion.terraform_project_name == 'Default Project'",
            # A stale HCP project in the subject prefix rejects every token.
            "assertion.sub.startsWith('organization:acme:project:Old Project:workspace:gcp:')",
            # A run-phase suffix on the subject prefix locks the other phase out too.
            "assertion.sub.startsWith('organization:acme:project:p:workspace:gcp:run_phase:plan')",
            # One provider serves both phases; naming one locks the other out.
            SCOPED + " && assertion.terraform_run_phase == 'plan'",
            # Every trusted-looking substring present, trust inverted or discarded:
            "assertion.sub.startsWith('organization:acme:project:p:workspace:gcp:') == false",
            # Mixed quotes re-pair after a rewrite and hide `|| true` inside a "literal".
            SCOPED + " && assertion.terraform_project_name == 'x\" && "
            "assertion.terraform_project_name == ' || true || "
            "assertion.terraform_project_name == \" && assertion.terraform_project_name == 'z\"",
            # Any double quote at all, even in an otherwise valid form.
            'assertion.sub.startsWith("organization:acme:project:p:workspace:gcp:")',
            # A // comment runs to a newline the check has collapsed.
            SCOPED + " && assertion.terraform_project_name == 'x' // '\n|| true",
            SCOPED + " && assertion.terraform_project_name == 'a\\' || true'",
            SCOPED + " ? true : true",
            "(" + SCOPED + ")",
        ):
            with self.subTest(condition=condition):
                self.assert_exit(self.run_check(condition=condition), 1)

    def test_wrong_issuer_or_inactive_provider_fails(self) -> None:
        self.assert_exit(self.run_check(issuer="https://app.terraform.io/"), 1)
        self.assert_exit(self.run_check(state="DELETED"), 1)

    def test_impersonation_from_another_pool_fails(self) -> None:
        other = "principalSet://iam.googleapis.com/projects/9/locations/global/workloadIdentityPools/x/*"
        self.assert_exit(
            self.run_check(members=[f"principalSet://iam.googleapis.com/{POOL}/*", other]), 1
        )
        self.assert_exit(self.run_check(members=["user:someone@example.com"]), 1)
        for extra in ("user:someone@example.com", "group:ops@example.com",
                      "serviceAccount:other@proj.iam.gserviceaccount.com"):
            with self.subTest(extra=extra):
                self.assert_exit(self.run_check(
                    members=[f"principalSet://iam.googleapis.com/{POOL}/*", extra]), 1)

    def test_split_accounts_fence_the_apply_account_by_run_phase(self) -> None:
        plan_sa = "plan@proj.iam.gserviceaccount.com"
        apply_sa = "apply@proj.iam.gserviceaccount.com"
        variables = [
            *DEFAULT_VARS,
            env_var("TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL", plan_sa),
            env_var("TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL", apply_sa),
        ]
        phase = f"principalSet://iam.googleapis.com/{POOL}/attribute.terraform_run_phase"
        fenced = {plan_sa: [f"{phase}/plan"], apply_sa: [f"{phase}/apply"]}
        self.assert_exit(self.run_check(variables=variables, policies=fenced), 0)
        for apply_members in (
            [f"principalSet://iam.googleapis.com/{POOL}/*"],   # pool-wide
            [f"{phase}/plan"],                                  # wrong phase
            [f"{phase}/apply", f"{phase}/plan"],
        ):
            with self.subTest(apply_members=apply_members):
                self.assert_exit(self.run_check(
                    variables=variables,
                    policies={plan_sa: [f"{phase}/plan"], apply_sa: apply_members},
                ), 1)
        # A constant mapping would label every token "apply".
        self.assert_exit(self.run_check(
            variables=variables, policies=fenced,
            mapping={"google.subject": "assertion.sub",
                     "attribute.terraform_run_phase": "'apply'"},
        ), 1)

    def test_other_active_providers_in_the_pool_fail(self) -> None:
        sibling = {"name": f"{POOL}/providers/github", "state": "ACTIVE",
                   "attributeCondition": ""}
        self.assert_exit(self.run_check(siblings=[sibling]), 1)
        self.assert_exit(self.run_check(siblings=[{**sibling, "disabled": True}]), 0)
        self.assert_exit(self.run_check(siblings=[{**sibling, "state": "DELETED"}]), 0)

    def test_token_creator_and_project_grants_are_judged_too(self) -> None:
        foreign = "principalSet://iam.googleapis.com/projects/9/locations/global/workloadIdentityPools/x/*"
        token_creator = "roles/iam.serviceAccountTokenCreator"
        self.assert_exit(self.run_check(
            extra_bindings=[{"role": token_creator, "members": [foreign]}]), 1)
        self.assert_exit(self.run_check(
            project_bindings=[{"role": token_creator, "members": [foreign]}]), 1)
        for role in ("roles/iam.serviceAccountKeyAdmin", "roles/iam.serviceAccountAdmin",
                     "roles/iam.serviceAccountUser", "roles/iam.workloadIdentityPoolAdmin",
                     "roles/resourcemanager.projectIamAdmin", "roles/editor"):
            with self.subTest(role=role):
                self.assert_exit(self.run_check(
                    project_bindings=[{"role": role, "members": [foreign]}]), 1)
        # Judged by permission, not by name: a service-agent role mints tokens too.
        self.assert_exit(self.run_check(
            project_bindings=[{"role": "roles/cloudbuild.serviceAgent", "members": [foreign]}]), 1)
        self.assert_exit(self.run_check(
            project_bindings=[{"role": "roles/storage.admin", "members": [foreign]}],
            role_describe_error=True), 2)
        # A custom role that uploads a key the attacker holds the private half of.
        self.assert_exit(self.run_check(
            project_bindings=[{"role": "projects/proj/roles/keyUploader", "members": [foreign]}]), 1)
        for role in ("projects/proj/roles/keyEnabler", "projects/proj/roles/poolPolicy",
                     "roles/iam.roleAdmin"):
            with self.subTest(role=role):
                self.assert_exit(self.run_check(
                    project_bindings=[{"role": role, "members": [foreign]}]), 1)
        # Grants on the pool itself never appear in the project policy.
        self.assert_exit(self.run_check(pool_bindings=[
            {"role": "roles/iam.workloadIdentityPoolAdmin", "members": [foreign]}]), 1)
        self.assert_exit(self.run_check(pool_bindings=[
            {"role": "roles/iam.workloadIdentityPoolAdmin", "members": ["user:admin@example.com"]}]), 0)
        # A condition may scope the grant away from the run accounts; it is not evaluated,
        # so the verdict is "cannot verify", never a false red or a false green.
        self.assert_exit(self.run_check(project_bindings=[{
            "role": "roles/iam.serviceAccountTokenCreator", "members": [foreign],
            "condition": {"expression": "resource.name == 'projects/-/serviceAccounts/other'"},
        }]), 2)
        # This pool's own principals are not resolved at all.
        self.assert_exit(self.run_check(
            project_bindings=[{"role": "roles/editor",
                               "members": [f"principalSet://iam.googleapis.com/{POOL}/*"]}],
            role_describe_error=True), 0)
        # Humans holding Token Creator are not what this check is about.
        self.assert_exit(self.run_check(
            project_bindings=[{"role": token_creator, "members": ["user:admin@example.com"]}]), 0)
        # A federated principal on an unrelated project role is direct resource access.
        self.assert_exit(self.run_check(
            project_bindings=[{"role": "roles/storage.admin", "members": [foreign]}]), 0)

    def test_plan_phase_token_creator_breaks_the_apply_fence(self) -> None:
        plan_sa = "plan@proj.iam.gserviceaccount.com"
        apply_sa = "apply@proj.iam.gserviceaccount.com"
        variables = [
            *DEFAULT_VARS,
            env_var("TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL", plan_sa),
            env_var("TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL", apply_sa),
        ]
        phase = f"principalSet://iam.googleapis.com/{POOL}/attribute.terraform_run_phase"
        fenced = {plan_sa: [f"{phase}/plan"], apply_sa: [f"{phase}/apply"]}
        token_creator = "roles/iam.serviceAccountTokenCreator"
        self.assert_exit(self.run_check(
            variables=variables, policies=fenced,
            extra_bindings=[{"role": token_creator, "members": [f"{phase}/plan"]}]), 1)
        self.assert_exit(self.run_check(
            variables=variables, policies=fenced,
            project_bindings=[{"role": token_creator, "members": [f"{phase}/plan"]}]), 1)

    def test_split_projects_fence_only_what_reaches_the_apply_account(self) -> None:
        plan_sa = "plan@planproj.iam.gserviceaccount.com"
        apply_sa = "apply@applyproj.iam.gserviceaccount.com"
        variables = [
            *DEFAULT_VARS[:2],
            env_var("TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL", plan_sa),
            env_var("TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL", apply_sa),
            DEFAULT_VARS[3],
        ]
        phase = f"principalSet://iam.googleapis.com/{POOL}/attribute.terraform_run_phase"
        fenced = {plan_sa: [f"{phase}/plan"], apply_sa: [f"{phase}/apply"]}
        token_creator = [{"role": "roles/iam.serviceAccountTokenCreator",
                          "members": [f"{phase}/plan"]}]
        # On the plan account's own project it cannot reach the apply account.
        self.assert_exit(self.run_check(variables=variables, policies=fenced,
                                        project_policies={"planproj": token_creator}), 0)
        # On the apply account's project, or the pool's, it can.
        self.assert_exit(self.run_check(variables=variables, policies=fenced,
                                        project_policies={"applyproj": token_creator}), 1)
        self.assert_exit(self.run_check(variables=variables, policies=fenced,
                                        project_policies={"123": token_creator}), 1)

    def test_variable_sets_and_default_accounts_fail(self) -> None:
        self.assert_exit(self.run_check(varsets=1), 1)
        variables = [
            *DEFAULT_VARS[:2],
            env_var("TFC_GCP_RUN_SERVICE_ACCOUNT_EMAIL", "123-compute@developer.gserviceaccount.com"),
            DEFAULT_VARS[3],
        ]
        self.assert_exit(self.run_check(variables=variables), 1)

    def test_every_google_credential_override_fails(self) -> None:
        for key in ("GOOGLE_OAUTH_ACCESS_TOKEN", "GOOGLE_CLOUD_KEYFILE_JSON",
                    "GCLOUD_KEYFILE_JSON", "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT",
                    "CLOUDSDK_AUTH_ACCESS_TOKEN_FILE", "GOOGLE_APPLICATION_CREDENTIALS"):
            with self.subTest(key=key):
                self.assert_exit(self.run_check(
                    variables=[*DEFAULT_VARS, env_var(key, "x")]), 1)
        # Location settings carry no identity.
        self.assert_exit(self.run_check(variables=[
            *DEFAULT_VARS, env_var("GOOGLE_PROJECT", "proj"), env_var("GOOGLE_REGION", "eu")]), 0)

    def test_static_identity_in_the_configuration_fails(self) -> None:
        dynamic = (
            'provider "google" {\n'
            '  project     = local.project_id\n'
            '  credentials = try(var.tfc_gcp_dynamic_credentials.default.credentials, null)\n'
            '}\n'
        )
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf": dynamic}), 0)
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
            'provider "google" {\n  project = local.project_id\n}\n'}), 0)
        # Compact blocks put the argument mid-line.
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
            'provider "google" { credentials = var.google_key }\n'}), 1)
        for line in ('  credentials = var.google_key\n',
                     '  credentials /* legacy */ = var.google_key\n',
                     '  credentials# note\n',
                     '  /* legacy */ credentials = var.google_key\n',
                     # A multi-line comment that ends just before the argument.
                     '  /* note\n  and here */ credentials = var.google_key\n',
                     # The allowed form inside a comment must not excuse the real value.
                     '  credentials = var.google_key # = try(var.tfc_gcp_dynamic_credentials'
                     '.default.credentials, null)\n',
                     '  access_token = var.token\n',
                     '  impersonate_service_account = "admin@proj.iam.gserviceaccount.com"\n'):
            with self.subTest(line=line):
                self.assert_exit(self.run_check(tf_files={
                    "terraform/gcp/providers.tf": 'provider "google" {\n' + line + '}\n'}), 1)
        # Commented out across lines is not configuration.
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
            'provider "google" {\n  /*\n  credentials = var.old_key\n  */\n}\n'}), 0)
        # A "/*" inside a string or heredoc is data, not a comment opener; a textual
        # strip would swallow every later line, static key included.
        static = '  credentials = var.google_key\n'
        for before in (
            'locals { note = "/*" }\n',
            'locals { bucket = "gs://b/*" }\n',
            'locals { x = "${format("/*%s", "y")}" }\n',
            'locals {\n  doc = <<EOT\n  /* not a comment\n  EOT\n}\n',
            'locals {\n  doc = <<-END-JSON\n  /* not a comment\n  END-JSON\n}\n',
            'locals { esc = "a \\" /* still a string" }\n',
        ):
            with self.subTest(before=before):
                self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
                    before + 'provider "google" {\n' + static + '}\n'}), 1)
        # Line comments are comments.
        for commented in ('  # credentials = var.old_key\n', '  // credentials = var.old_key\n'):
            with self.subTest(commented=commented):
                self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
                    'provider "google" {\n' + commented + '}\n'}), 0)
        # The aliased allowed form keeps its string subscript through the lexer.
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
            'provider "google" {\n  alias = "x"\n'
            '  credentials = try(var.tfc_gcp_dynamic_credentials.aliases["x"].credentials, null)\n'
            '}\n'}), 0)
        # Only google provider blocks carry identity arguments.
        for elsewhere in (
            'variable "tfc_gcp_dynamic_credentials" {\n'
            '  type = object({ default = object({ credentials = string }) })\n}\n',
            'module "x" {\n  source      = "./x"\n  credentials = var.k\n}\n',
            'provider "aws" {\n  access_token = var.t\n}\n',
        ):
            with self.subTest(elsewhere=elsewhere):
                self.assert_exit(self.run_check(
                    tf_files={"terraform/gcp/main.tf": elsewhere}), 0)
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
            'provider "google" { credentials = try(var.tfc_gcp_dynamic_credentials.default.credentials, null) }\n'}), 0)
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
            'provider google {\n  credentials = var.k\n}\n'}), 1)
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf":
            'provider "google-beta" {\n  nested {\n  }\n  access_token = var.t\n}\n'}), 1)
        # Shared modules configure providers too.
        self.assert_exit(self.run_check(tf_files={
            "terraform/gcp/main.tf": "",
            "terraform/modules/x/providers.tf": 'provider "google" {\n  credentials = file("k.json")\n}\n',
        }), 1)

    def test_json_syntax_configuration_is_scanned_too(self) -> None:
        dynamic = json.dumps({"provider": {"google": {
            "credentials": "${try(var.tfc_gcp_dynamic_credentials.default.credentials, null)}"}}})
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/providers.tf.json": dynamic}), 0)
        for body in (
            {"provider": {"google": {"credentials": "${var.google_key}"}}},
            {"provider": {"google-beta": [{"access_token": "${var.token}"}]}},
            {"provider": {"google": {"impersonate_service_account": "admin@proj.iam.gserviceaccount.com"}}},
        ):
            with self.subTest(body=body):
                self.assert_exit(self.run_check(
                    tf_files={"terraform/gcp/providers.tf.json": json.dumps(body)}), 1)
        self.assert_exit(self.run_check(
            tf_files={"terraform/gcp/providers.tf.json": "{not json"}), 2)
        # Keys outside a google provider block are not identity arguments.
        self.assert_exit(self.run_check(tf_files={"terraform/gcp/variables.tf.json":
            json.dumps({"variable": {"credentials": {"type": "string"}}})}), 0)

    def test_conditional_impersonation_binding_cannot_be_verified(self) -> None:
        self.assert_exit(self.run_check(extra_bindings=[{
            "role": "roles/iam.workloadIdentityUser",
            "members": [f"principalSet://iam.googleapis.com/{POOL}/*"],
            "condition": {"expression": "request.time < timestamp('2020-01-01T00:00:00Z')"},
        }]), 2)

    def test_tagged_configurations_cannot_be_verified(self) -> None:
        for key in ("TFC_GCP_PROVIDER_AUTH_ALIAS", "TFC_GCP_WORKLOAD_PROVIDER_NAME_ALIAS",
                    "TFC_DEFAULT_GCP_PROVIDER_AUTH"):
            with self.subTest(key=key):
                self.assert_exit(self.run_check(
                    variables=[*DEFAULT_VARS, env_var(key, "x")]), 2)

    def test_accounts_admit_every_phase_they_serve(self) -> None:
        phase = f"principalSet://iam.googleapis.com/{POOL}/attribute.terraform_run_phase"
        subject = f"principal://iam.googleapis.com/{POOL}/subject/organization:acme:project:p:workspace:gcp:run_phase:plan"
        # A shared account fenced to one phase breaks the other.
        for members in ([f"{phase}/plan"], [subject]):
            with self.subTest(members=members):
                self.assert_exit(self.run_check(members=members), 1)
        self.assert_exit(self.run_check(members=[f"{phase}/plan", f"{phase}/apply"]), 0)
        # A split plan account must admit plan.
        plan_sa = "plan@proj.iam.gserviceaccount.com"
        apply_sa = "apply@proj.iam.gserviceaccount.com"
        variables = [*DEFAULT_VARS,
                     env_var("TFC_GCP_PLAN_SERVICE_ACCOUNT_EMAIL", plan_sa),
                     env_var("TFC_GCP_APPLY_SERVICE_ACCOUNT_EMAIL", apply_sa)]
        self.assert_exit(self.run_check(variables=variables, policies={
            plan_sa: [f"{phase}/apply"], apply_sa: [f"{phase}/apply"]}), 1)

    def test_only_service_account_impersonation_is_verifiable(self) -> None:
        pool_mode = [DEFAULT_VARS[0], env_var("TFC_GCP_PRINCIPAL_TYPE", "workload_pool"),
                     *DEFAULT_VARS[2:]]
        self.assert_exit(self.run_check(variables=pool_mode), 1)
        self.assert_exit(self.run_check(variables=[DEFAULT_VARS[0], *DEFAULT_VARS[2:]]), 1)

    def test_conflicting_or_hidden_variables_fail(self) -> None:
        self.assert_exit(
            self.run_check(variables=[*DEFAULT_VARS, env_var("GOOGLE_CREDENTIALS", "", True)]), 1
        )
        hidden = [*DEFAULT_VARS[:3], env_var("TFC_GCP_WORKLOAD_PROVIDER_NAME", "", True)]
        self.assert_exit(self.run_check(variables=hidden), 1)
        self.assert_exit(self.run_check(variables=DEFAULT_VARS[1:]), 1)

    def test_unreadable_gcp_state_cannot_verify(self) -> None:
        self.assert_exit(self.run_check(describe_error="PERMISSION_DENIED"), 2)
        self.assert_exit(self.run_check(policy_error=True), 2)

    def test_missing_provider_is_a_verdict(self) -> None:
        self.assert_exit(self.run_check(describe_error="NOT_FOUND: provider"), 1)


if __name__ == "__main__":
    unittest.main()
