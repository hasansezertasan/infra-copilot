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
        }
        policy = {"bindings": [{"role": "roles/iam.workloadIdentityUser", "members": members}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workspace.json").write_text(json.dumps({"data": {"id": "ws-abc123"}}))
            (root / "vars.json").write_text(
                json.dumps({"data": variables, "meta": {"pagination": {"next-page": None}}})
            )
            (root / "provider.json").write_text(json.dumps(provider))
            (root / "policy.json").write_text(json.dumps(policy))
            (root / "curl").write_text(
                "#!/bin/sh\n"
                'for arg in "$@"; do case "$arg" in\n'
                f"  */vars*) cat '{root}/vars.json'; exit 0 ;;\n"
                f"  */workspaces/gcp) cat '{root}/workspace.json'; exit 0 ;;\n"
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
                f"  *get-iam-policy*) {policy_cmd} ;;\n"
                "  *) exit 1 ;;\nesac\n"
            )
            for stub in ("curl", "gcloud"):
                (root / stub).chmod(0o755)
            return subprocess.run(
                ["/bin/sh", str(SCRIPT)],
                env={
                    **os.environ,
                    "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                    "ORG": "acme",
                    "NEW_PROVIDER_WORKSPACE": "gcp",
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
            'assertion.sub.startsWith("organization:acme:project:Default Project:workspace:gcp")',
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
            'assertion.sub.startsWith("organization:acme:project:p:workspace:gcp-other")',
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
