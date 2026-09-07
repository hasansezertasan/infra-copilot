"""Behavioural tests for the shipped hcp-apply-scope check.

The check is the only enforcing control docs/policy.md identifies inside this
repository's reach, so a false green here means an agent holding apply rights
on production while the manifest reports the boundary as present. It has to
tell four states apart: plan-only, can-apply, cannot-plan, and unreadable.

These run the *shipped* script with `curl` stubbed on PATH. `jq` is real --
stubbing it would test the stub rather than the filter the script actually
ships.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills/infra-copilot/references/checks/hcp-apply-scope.sh"

PLAN_ONLY = {"can-queue-run": True, "can-queue-apply": False}
CAN_APPLY = {"can-queue-run": True, "can-queue-apply": True}
READ_ONLY = {"can-queue-run": False, "can-queue-apply": False}


@unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
class HcpApplyScopeTests(unittest.TestCase):
    def run_check(
        self,
        *,
        permissions: dict[str, dict[str, bool] | None] | None = None,
        env: dict[str, str] | None = None,
        curl_fails: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run the shipped script against a stubbed HCP.

        `permissions` maps workspace name to its permissions block, or None to
        omit the block entirely -- absent and false are different findings.
        """
        if permissions is None:
            permissions = {"cloudflare": PLAN_ONLY, "github-org": PLAN_ONLY}
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            cases = []
            for workspace, block in permissions.items():
                attributes: dict[str, object] = {"name": workspace}
                if block is not None:
                    attributes["permissions"] = block
                payload = json.dumps({"data": {"id": "ws-1", "attributes": attributes}})
                cases.append(
                    f"    *workspaces/{workspace}) printf '%s' '{payload}' ;;"
                )
            stub = [
                "#!/bin/sh",
                # -sf makes real curl exit non-zero on HTTP errors; the script
                # keys off that to report CANNOT VERIFY rather than a verdict.
                "exit 22" if curl_fails else "",
                'for arg in "$@"; do case "$arg" in',
                *cases,
                # Any URL the cases do not match is a bug in the test, not a
                # pass. An earlier harness in this repo silently stopped
                # matching and the tests kept passing.
                "    http*) echo \"unstubbed URL: $arg\" >&2; exit 99 ;;",
                "esac; done",
                "exit 0",
            ]
            (bin_dir / "curl").write_text("\n".join(stub) + "\n", encoding="utf-8")
            (bin_dir / "curl").chmod(0o755)

            environment = dict(os.environ)
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            environment.update(
                {
                    "ORG": "acme",
                    "HCP_TOKEN": "token",
                    "hcp_api": "https://app.terraform.io/api/v2",
                }
            )
            if env is not None:
                for key, value in env.items():
                    if value == "":
                        environment.pop(key, None)
                    else:
                        environment[key] = value
            return subprocess.run(
                ["sh", str(SCRIPT)],
                capture_output=True,
                text=True,
                env=environment,
                cwd=directory,
            )

    def test_plan_only_token_passes(self) -> None:
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_token_that_can_apply_is_a_verdict_not_a_cannot_verify(self) -> None:
        """Exit 1: this is a real finding about the credential."""
        result = self.run_check(
            permissions={"cloudflare": CAN_APPLY, "github-org": PLAN_ONLY}
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("UNPROTECTED", result.stderr)
        self.assertIn("cloudflare", result.stderr)

    def test_reports_every_workspace_that_can_apply(self) -> None:
        """Checking only the first would hide the second."""
        result = self.run_check(
            permissions={"cloudflare": CAN_APPLY, "github-org": CAN_APPLY}
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.count("UNPROTECTED"), 2, result.stderr)

    def test_a_token_that_cannot_plan_is_reported_separately(self) -> None:
        """The fix is to grant Plan, not to remove Apply."""
        result = self.run_check(
            permissions={"cloudflare": READ_ONLY, "github-org": PLAN_ONLY}
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("OVER-RESTRICTED", result.stderr)
        self.assertNotIn("UNPROTECTED", result.stderr)

    def test_a_missing_permissions_block_cannot_be_verified(self) -> None:
        """Absent is not false: HCP told us nothing about this token."""
        result = self.run_check(permissions={"cloudflare": None})
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_a_failed_read_cannot_be_verified(self) -> None:
        result = self.run_check(curl_fails=True)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_missing_configuration_cannot_be_verified(self) -> None:
        for variable in ("ORG", "HCP_TOKEN", "hcp_api"):
            with self.subTest(missing=variable):
                result = self.run_check(env={variable: ""})
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(variable, result.stderr)

    def test_never_posts_an_apply(self) -> None:
        """A dry POST apply would apply if the token held the rights.

        The check must stay a read; this pins that it sends no POST and touches
        no apply endpoint.
        """
        # Comments excluded: the script's header explains at length why it does
        # not POST an apply, and naming the endpoint there is the documentation,
        # not a call. Matching the raw file failed on its own rationale.
        code = "\n".join(
            line
            for line in SCRIPT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("actions/apply", code)
        self.assertNotIn("POST", code)
        self.assertIn("curl -sf", code, "the check must still read the workspace")


if __name__ == "__main__":
    unittest.main()
