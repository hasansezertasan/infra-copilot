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
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            (home / ".terraform.d").mkdir(parents=True)
            if file_token is not None:
                (home / ".terraform.d/credentials.tfrc.json").write_text(
                    json.dumps({"credentials": {"app.terraform.io": {"token": file_token}}}),
                    encoding="utf-8",
                )
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            stub = bin_dir / "curl"
            stub.write_text(
                "#!/bin/sh\nexit 6\n" if curl_fails else f"#!/bin/sh\nprintf '%s' {code}\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            environment["HOME"] = str(home)
            environment["hcp_api"] = "https://app.terraform.io/api/v2"
            environment.pop("TF_TOKEN_app_terraform_io", None)
            if env_token is not None:
                environment["TF_TOKEN_app_terraform_io"] = env_token
            return subprocess.run(
                ["/bin/sh", "-c", extract_check()],
                capture_output=True,
                text=True,
                env=environment,
                cwd=directory,
            )

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
