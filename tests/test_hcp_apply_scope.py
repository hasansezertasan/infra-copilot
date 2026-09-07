"""Behavioural tests for the shipped hcp-apply-scope check.

The check is the only enforcing control docs/policy.md identifies inside this
repository's reach, so a false green means an agent holding apply rights on
production while the manifest reports the boundary as present.

It has to tell these apart: plan-only, can-apply, cannot-plan, a credential
that disagrees with $HCP_TOKEN, and every flavour of unreadable evidence.

These run the *shipped* script with `curl` stubbed on PATH and a real HOME
holding a real credentials file. `jq` is not stubbed -- stubbing it would test
the stub rather than the filters the script ships.
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

TOKEN = "plan-only.atlasv1.xxx"
PLAN_ONLY = {"can-queue-run": True, "can-queue-apply": False}
CAN_APPLY = {"can-queue-run": True, "can-queue-apply": True}
READ_ONLY = {"can-queue-run": False, "can-queue-apply": False}


@unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
class HcpApplyScopeTests(unittest.TestCase):
    def run_check(
        self,
        *,
        workspaces: list[tuple[str, dict[str, object] | None]] | None = None,
        body: str | None = None,
        env: dict[str, str] | None = None,
        curl_fails: bool = False,
        credential: str | None = TOKEN,
        total_pages: int = 1,
    ) -> subprocess.CompletedProcess[str]:
        if workspaces is None:
            workspaces = [("cloudflare", PLAN_ONLY), ("github-org", PLAN_ONLY)]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            (home / ".terraform.d").mkdir(parents=True)
            if credential is not None:
                (home / ".terraform.d/credentials.tfrc.json").write_text(
                    json.dumps({"credentials": {"app.terraform.io": {"token": credential}}}),
                    encoding="utf-8",
                )

            if body is None:
                data = []
                for name, permissions in workspaces:
                    attributes: dict[str, object] = {"name": name}
                    if permissions is not None:
                        attributes["permissions"] = permissions
                    data.append({"id": f"ws-{name}", "attributes": attributes})
                body = json.dumps(
                    {"data": data, "meta": {"pagination": {"total-pages": total_pages}}}
                )

            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            stub = [
                "#!/bin/sh",
                # -sf makes real curl exit non-zero on HTTP errors; the script keys
                # off that to report CANNOT VERIFY rather than a verdict.
                "exit 22" if curl_fails else "",
                'for arg in "$@"; do case "$arg" in',
                f"    *organizations/*/workspaces*) printf '%s' {json.dumps(body)!s} ;;",
                # Any URL the cases do not match is a bug in the test, not a pass.
                # An earlier harness in this repo silently stopped matching and the
                # tests kept passing.
                '    http*) echo "unstubbed URL: $arg" >&2; exit 99 ;;',
                "esac; done",
                "exit 0",
            ]
            curl = bin_dir / "curl"
            curl.write_text("\n".join(stub) + "\n", encoding="utf-8")
            curl.chmod(0o755)

            environment = dict(os.environ)
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            environment.update(
                {
                    "HOME": str(home),
                    "ORG": "acme",
                    "hcp_api": "https://app.terraform.io/api/v2",
                }
            )
            environment.pop("TF_TOKEN_app_terraform_io", None)
            environment.pop("HCP_TOKEN", None)
            for key, value in (env or {}).items():
                if value == "":
                    environment.pop(key, None)
                else:
                    environment[key] = value
            return subprocess.run(
                # Absolute interpreter so PATH controls only the tools under
                # test. Resolving `sh` through PATH made the missing-tool cases
                # depend on what the host keeps in /bin.
                ["/bin/sh", str(SCRIPT)],
                capture_output=True,
                text=True,
                env=environment,
                cwd=directory,
            )

    # ---- the states the check exists to tell apart ----

    def test_plan_only_credential_passes(self) -> None:
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_credential_that_can_apply_is_a_verdict(self) -> None:
        result = self.run_check(
            workspaces=[("cloudflare", CAN_APPLY), ("github-org", PLAN_ONLY)]
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("UNPROTECTED", result.stderr)
        self.assertIn("cloudflare", result.stderr)

    def test_reports_every_appliable_workspace(self) -> None:
        result = self.run_check(
            workspaces=[("cloudflare", CAN_APPLY), ("github-org", CAN_APPLY)]
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.count("UNPROTECTED"), 2, result.stderr)

    def test_a_credential_that_cannot_plan_is_reported_separately(self) -> None:
        """The fix is to grant Plan, not to remove Apply."""
        result = self.run_check(workspaces=[("cloudflare", READ_ONLY)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("OVER-RESTRICTED", result.stderr)
        self.assertNotIn("UNPROTECTED", result.stderr)

    # ---- the credential terraform would actually use ----

    def test_checks_the_terraform_credential_not_hcp_token(self) -> None:
        """`terraform` never reads $HCP_TOKEN, so verifying it proves nothing.

        Here HCP_TOKEN matches, and the credentials file is what gets checked.
        """
        result = self.run_check(env={"HCP_TOKEN": TOKEN})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_env_credential_takes_precedence_over_the_file(self) -> None:
        """TF_TOKEN_app_terraform_io wins for terraform, so it must win here."""
        result = self.run_check(
            credential="file-token",
            env={"TF_TOKEN_app_terraform_io": TOKEN, "HCP_TOKEN": TOKEN},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_disagreeing_hcp_token_is_a_verdict(self) -> None:
        """Two identities means verifying one says nothing about the other."""
        result = self.run_check(env={"HCP_TOKEN": "some-other-token"})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("SPLIT-BRAIN", result.stderr)

    def test_no_credential_at_all_cannot_be_verified(self) -> None:
        result = self.run_check(credential=None)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    # ---- unreadable evidence must never be a verdict ----

    def test_a_missing_permissions_block_cannot_be_verified(self) -> None:
        """Absent is not false: HCP told us nothing about this credential."""
        result = self.run_check(workspaces=[("cloudflare", None)])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_a_non_boolean_permission_cannot_be_verified(self) -> None:
        """`can-queue-apply: 0` is not `false`; it is unexpected evidence."""
        result = self.run_check(
            workspaces=[("cloudflare", {"can-queue-run": True, "can-queue-apply": 0})]
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("not a boolean", result.stderr)

    def test_a_non_json_body_cannot_be_verified(self) -> None:
        """curl -sf exits 0 on a 200, so a bad body must not become a verdict."""
        result = self.run_check(body="<html>gateway</html>")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_a_failed_read_cannot_be_verified(self) -> None:
        result = self.run_check(curl_fails=True)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_no_visible_workspaces_cannot_be_verified(self) -> None:
        """An empty list reads as "cannot apply anything" while proving nothing."""
        result = self.run_check(workspaces=[])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no workspaces", result.stderr)

    def test_missing_configuration_cannot_be_verified(self) -> None:
        for variable in ("ORG", "hcp_api"):
            with self.subTest(missing=variable):
                result = self.run_check(env={variable: ""})
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn(variable, result.stderr)

    def test_a_missing_tool_cannot_be_verified(self) -> None:
        """Without jq every filter returns empty, which must not read as a verdict.

        Each tool is removed while the other stays, so the message names the one
        actually missing. An earlier version of this test set PATH to /bin and was
        named for jq while really exercising curl -- /bin has neither.
        """
        for missing, present in (("curl", "jq"), ("jq", "curl")):
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory() as directory:
                    bin_dir = Path(directory)
                    stub = bin_dir / present
                    stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    stub.chmod(0o755)
                    # PATH holds only the tool that should be present. An earlier
                    # version appended /bin, which on Linux supplies both tools --
                    # so the "removal" removed nothing and CI failed while this
                    # passed on macOS.
                    result = self.run_check(env={"PATH": str(bin_dir)})
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn(f"{missing} is not on PATH", result.stderr)

    # ---- scope ----

    def test_covers_workspaces_beyond_the_bootstrap_pair(self) -> None:
        """`add` creates more workspaces; a hardcoded pair would miss them."""
        result = self.run_check(
            workspaces=[
                ("cloudflare", PLAN_ONLY),
                ("github-org", PLAN_ONLY),
                ("gcp", CAN_APPLY),
            ]
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("gcp", result.stderr)

    def test_never_posts_an_apply(self) -> None:
        """A dry POST apply would apply if the credential held the rights."""
        # Comments excluded: the header explains at length why it does not POST,
        # and naming the endpoint there is documentation, not a call.
        code = "\n".join(
            line
            for line in SCRIPT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("actions/apply", code)
        self.assertNotIn("POST", code)
        self.assertIn("curl -sf", code, "the check must still read the API")


if __name__ == "__main__":
    unittest.main()
