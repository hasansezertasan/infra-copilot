"""Behavioural tests for the shipped status-check-context check.

The check is a shell script that talks to four GitHub endpoints and has to tell
five states apart: protection not applied, protection misconfigured, context
stale, context matching, and no evidence published yet. Three review rounds
found bugs in it that an ad-hoc harness caught and nothing committed would
have. These run the *shipped* script with `gh` and `git` stubbed on PATH.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills/infra-copilot/references/checks/status-check-context.sh"

HCP_OLD = "Terraform Cloud/acme/repo-id-111"
HCP_NEW = "Terraform Cloud/acme/repo-id-222"
OLD_AT = "2026-01-01T00:00:00Z"
NEW_AT = "2026-06-01T00:00:00Z"


class StatusCheckContextTests(unittest.TestCase):
    """Each case pins one state the check must tell apart."""

    def run_check(
        self,
        *,
        protected: str = "true",
        required: str = HCP_OLD,
        pulls: str = "",
        commits: str = "",
        statuses: dict[str, list[tuple[str, str]]] | None = None,
        head: str = "",
        authenticated: bool = True,
        fail_on: str = "",
    ) -> subprocess.CompletedProcess[str]:
        statuses = statuses or {}
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            status_cases = "\n".join(
                "    *commits/{sha}/status) printf '%s\\n' \"{lines}\" ;;".format(
                    sha=sha,
                    lines="\\n".join(f"{at} {context}" for at, context in entries),
                )
                for sha, entries in statuses.items()
            )
            stub = [
                "#!/bin/sh",
                f'[ "$1" = "auth" ] && exit {0 if authenticated else 1}',
            ]
            if fail_on:
                stub.append(f'case "$2" in {fail_on}) exit 1 ;; esac')
            stub += [
                'case "$2" in',
                f'    */branches/main) echo "{protected}" ;;',
                f"    *branches/main/protection) printf '%s\\n' \"{required}\" ;;",
                f"    *pulls\\?*) printf '%s\\n' \"{pulls}\" ;;",
                f"    *commits\\?*) printf '%s\\n' \"{commits}\" ;;",
                status_cases,
                "    *commits/*/status) echo '' ;;",
                "esac",
                "exit 0",
            ]
            (bin_dir / "gh").write_text("\n".join(stub) + "\n", encoding="utf-8")
            (bin_dir / "git").write_text(
                f'#!/bin/sh\n[ -n "{head}" ] && echo "{head}"\nexit 0\n', encoding="utf-8"
            )
            for stub in ("gh", "git"):
                (bin_dir / stub).chmod(0o755)
            env = {
                **os.environ,
                "REPO": "acme/infra",
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            return subprocess.run(
                ["sh", str(SCRIPT)], env=env, capture_output=True, text=True
            )

    def test_passes_when_context_matches(self) -> None:
        result = self.run_check(commits="sha1", statuses={"sha1": [(OLD_AT, HCP_OLD)]})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_context_on_an_open_pr_head_is_caught(self) -> None:
        """The incident: main still carries the old context, the PR carries the new one.

        Checking `main` first reports green here, which is how this shipped
        broken twice.
        """
        result = self.run_check(
            required=HCP_OLD,
            pulls="prsha",
            commits="mainsha",
            statuses={"prsha": [(NEW_AT, HCP_NEW)], "mainsha": [(OLD_AT, HCP_OLD)]},
            head="mainsha",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("BLOCKED", result.stderr)
        self.assertIn(HCP_OLD, result.stderr)

    def test_greenfield_without_protection_passes(self) -> None:
        """setup ends at green speculative plans, so protection is not applied yet."""
        result = self.run_check(protected="false")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_protection_without_an_hcp_context_is_underprotected(self) -> None:
        result = self.run_check(required="")
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNDERPROTECTED", result.stderr)

    def test_unauthenticated_gh_is_not_reported_as_a_stale_context(self) -> None:
        """Exit 2, not 1: an unreadable check proves nothing about protection."""
        result = self.run_check(authenticated=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("CANNOT VERIFY", result.stderr)
        self.assertIn("not authenticated", result.stderr)

    def test_missing_repo_variable_fails_loudly(self) -> None:
        result = subprocess.run(
            ["sh", str(SCRIPT)],
            env={k: v for k, v in os.environ.items() if k != "REPO"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("REPO is not set", result.stderr)

    def test_no_published_hcp_status_anywhere_is_unverifiable_not_broken(self) -> None:
        """Non-HCP statuses are filtered out by the jq selector, so nothing is published."""
        result = self.run_check(commits="sha1", statuses={"sha1": []})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_context_wins_no_matter_which_candidate_is_listed_first(self) -> None:
        """An older PR sorting first must not decide what is published now.

        Ordering by list position was wrong three separate ways; the newest
        status timestamp decides, whichever candidate carried it.
        """
        result = self.run_check(
            required=HCP_OLD,
            pulls="oldpr newpr",
            commits="mainsha",
            statuses={
                "oldpr": [(OLD_AT, HCP_OLD)],
                "newpr": [(NEW_AT, HCP_NEW)],
                "mainsha": [(OLD_AT, HCP_OLD)],
            },
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("BLOCKED", result.stderr)

    def test_per_commit_status_failure_does_not_report_green(self) -> None:
        result = self.run_check(fail_on="*commits/*/status", commits="sha1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not read commit status", result.stderr)

    def test_unreadable_pr_head_does_not_fall_back_to_an_older_match(self) -> None:
        """The sharpest form: the PR head read fails, main carries a matching status.

        Treating that failure as "no status here" would accept main's older
        matching context and report a blocked PR as healthy.
        """
        result = self.run_check(
            required=HCP_OLD,
            pulls="prsha",
            commits="mainsha",
            statuses={"mainsha": [(OLD_AT, HCP_OLD)]},
            fail_on="*commits/prsha/status",
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("could not read commit status for prsha", result.stderr)

    def test_api_read_failures_do_not_report_green(self) -> None:
        for endpoint, label in (
            ("*/branches/main", "branch"),
            ("*protection", "protection"),
            ("*pulls\\?*", "pull requests"),
            ("*commits\\?*", "commits"),
        ):
            with self.subTest(endpoint=label):
                result = self.run_check(fail_on=endpoint, commits="sha1")
                self.assertEqual(result.returncode, 2, f"{label} failure read as green")


if __name__ == "__main__":
    unittest.main()
