"""Behavioural tests for the hcp-login check in steps.yaml.

Presence alone used to satisfy it, so on a machine already narrowed by
`hcp-apply-scope` the plan-only team token counted as a completed login.
Bootstrapping a *second* repository then skipped the user-token handoff, and
`vcs-connect` could not read organization VCS settings while no workspace
existed yet for its fallback -- setup stalled with no way to ask for the
credential it needed.

/account/details exists only for a user token, so it separates them. Only a
definitive negative turns the check red: a transport failure must not block a
cold bootstrap on a flaky network.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/steps.yaml"


def extract_check() -> str:
    body = MANIFEST.read_text(encoding="utf-8")
    match = re.search(r"- id: hcp-login.*?check: \|\n(.*?)\n    produces:", body, re.S)
    assert match, "hcp-login's block check is no longer where this test looks"
    return textwrap.dedent(match.group(1))


@unittest.skipUnless(os.name == "posix", "the check is POSIX shell")
class HcpLoginCheckTests(unittest.TestCase):
    def run_check(
        self,
        *,
        code: str = "200",
        file_token: str | None = "user-token",
        env_token: str | None = None,
        curl_fails: bool = False,
        workspace_repo: str | None = None,
        workspace_names: tuple[str, ...] = ("cloudflare", "github-org"),
        workspace_version: str = "1.14.6",
        workspaces_readable: bool = True,
        hcp_api: str = "https://app.terraform.io/api/v2",
    ) -> subprocess.CompletedProcess[str]:
        """Run the extracted check with `curl` stubbed per URL.

        `workspace_repo` is the VCS identifier each named workspace reports.
        """
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            (home / ".terraform.d").mkdir(parents=True)
            if file_token is not None:
                (home / ".terraform.d/credentials.tfrc.json").write_text(
                    json.dumps({"credentials": {"app.terraform.io": {"token": file_token}}}),
                    encoding="utf-8",
                )
            calls = Path(directory) / "calls"
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            workspace_bodies: dict[str, str] = {}
            for name, leaf in (
                ("cloudflare", "terraform/cloudflare"),
                ("github-org", "terraform/github"),
            ):
                if workspace_repo and name in workspace_names:
                    workspace_bodies[name] = json.dumps(
                        {
                            "data": {
                                "attributes": {
                                    "working-directory": leaf,
                                    "execution-mode": "remote",
                                    "terraform-version": workspace_version,
                                    "auto-apply": False,
                                    "auto-destroy-at": None,
                                    "auto-destroy-activity-duration": None,
                                    "speculative-enabled": True,
                                    "file-triggers-enabled": True,
                                    "trigger-patterns": [
                                        f"{leaf}/**",
                                        "terraform/modules/**",
                                        ".infra-copilot/config.md",
                                        "mise.toml",
                                    ],
                                    "vcs-repo": {
                                        "identifier": workspace_repo,
                                        "branch": "main",
                                    },
                                }
                            }
                        }
                    )
            stub = [
                "#!/bin/sh",
                'url=""; for a in "$@"; do case "$a" in http*) url="$a" ;; esac; done',
                f'printf "%s\n" "$url" >> {str(calls)!r}',
                "exit 6" if curl_fails else "",
                'case "$url" in',
                "  *account/details*)" + f' printf "%s" {code!r} ;;',
                "  *workspaces/cloudflare*)"
                + (
                    f' printf "%s" {workspace_bodies["cloudflare"]!r} ;;'
                    if workspaces_readable and "cloudflare" in workspace_bodies
                    else " exit 22 ;;"
                ),
                "  *workspaces/github-org*)"
                + (
                    f' printf "%s" {workspace_bodies["github-org"]!r} ;;'
                    if workspaces_readable and "github-org" in workspace_bodies
                    else " exit 22 ;;"
                ),
                '  *) echo "unstubbed URL: $url" >&2; exit 99 ;;',
                "esac",
            ]
            (bin_dir / "curl").write_text("\n".join(stub) + "\n", encoding="utf-8")
            (bin_dir / "curl").chmod(0o755)

            environment = dict(os.environ)
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            environment.update(
                {
                    "HOME": str(home),
                    "hcp_api": hcp_api,
                    "ORG": "acme",
                    "REPO": "acme/infra",
                    "TERRAFORM_VERSION": "1.14.6",
                    "INFRA_COPILOT_REFERENCES": str(
                        REPO_ROOT / ".ai-rulez/skills/infra-copilot/references"
                    ),
                }
            )
            environment.pop("TF_TOKEN_app_terraform_io", None)
            if env_token is not None:
                environment["TF_TOKEN_app_terraform_io"] = env_token
            result = subprocess.run(
                ["/bin/sh", "-c", extract_check()],
                capture_output=True,
                text=True,
                env=environment,
                cwd=directory,
            )
            result.requests = (  # type: ignore[attr-defined]
                calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            )
            return result

    def test_a_user_token_is_green(self) -> None:
        self.assertEqual(self.run_check().returncode, 0)

    def test_an_environment_token_is_accepted(self) -> None:
        """The route hcp-apply-scope documents must keep phase 0 green."""
        result = self.run_check(file_token=None, env_token="user-token")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_team_token_is_red_with_the_reason(self) -> None:
        """The case that stalled a cold second repository."""
        for code in ("401", "403", "404"):
            with self.subTest(code=code):
                result = self.run_check(code=code)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("not a user token", result.stderr)
                self.assertIn("terraform login", result.stderr)

    def test_a_provisioned_repository_passes_with_a_team_token(self) -> None:
        """The steady state after the handoff.

        Requiring a user token universally made hcp-login the first red step on
        every later resume and on status, telling the operator to restore the
        apply-capable token phase 4 had just removed.
        """
        result = self.run_check(code="404", workspace_repo="acme/infra")
        self.assertEqual(result.returncode, 0, result.stderr)
        # The user-token probe must not even be attempted once provisioning is
        # established, or a 404 there would still decide the outcome.
        self.assertNotIn(
            "account/details", " ".join(result.requests), result.requests
        )

    def test_another_repositorys_workspace_is_not_provisioning_evidence(self) -> None:
        """A cold repo in a shared organization still needs the user token."""
        result = self.run_check(code="404", workspace_repo="acme/other")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not a user token", result.stderr)

    def test_a_partial_bootstrap_still_requires_a_user_token(self) -> None:
        """The missing workspace still needs an organization-scoped create."""
        result = self.run_check(
            code="404",
            workspace_repo="acme/infra",
            workspace_names=("cloudflare",),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not a user token", result.stderr)

    def test_workspace_drift_still_requires_a_user_token(self) -> None:
        """The agent needs the user identity to reconcile Phase 1 settings."""
        result = self.run_check(
            code="404",
            workspace_repo="acme/infra",
            workspace_version="0.1.0",
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not a user token", result.stderr)

    def test_an_unexpected_endpoint_never_receives_the_credential(self) -> None:
        """This check runs earliest, before the tri-state guards can refuse."""
        for endpoint in ("http://app.terraform.io/api/v2", "https://evil.example/api/v2"):
            with self.subTest(endpoint=endpoint):
                result = self.run_check(hcp_api=endpoint)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.requests, [], result.requests)
                self.assertIn("was not checked", result.stderr)

    def test_an_unreadable_workspace_list_falls_through(self) -> None:
        """Cannot establish provisioning, so the credential kind still decides."""
        result = self.run_check(code="404", workspaces_readable=False)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not a user token", result.stderr)

    def test_no_credential_is_red(self) -> None:
        self.assertEqual(self.run_check(file_token=None).returncode, 1)

    def test_a_transport_failure_leaves_presence_standing(self) -> None:
        """Offline must not block a bootstrap, nor claim the token is wrong."""
        result = self.run_check(curl_fails=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.strip(), "")

    def test_an_unexpected_status_leaves_presence_standing(self) -> None:
        """A 500 says nothing about which kind of token this is."""
        self.assertEqual(self.run_check(code="500").returncode, 0)


if __name__ == "__main__":
    unittest.main()
