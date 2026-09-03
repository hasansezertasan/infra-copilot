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



# The check is a POSIX shell script that runs on the agent's machine in a consuming
# repo. Under Git Bash on Windows, MSYS rewrites arguments that look like paths, so
# `repos/owner/name/...` reaches the stub as a mangled absolute path and the URL match
# fails. Exercising that is testing MSYS, not the check. The Windows CI job exists to
# prove `scripts/validate.py` handles portable paths, not to run shell scripts.
@unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
class StatusCheckContextTests(unittest.TestCase):
    """Each case pins one state the check must tell apart."""

    def run_check(
        self,
        *,
        protected: str = "true",
        required: str = HCP_OLD,
        pulls: str = "",
        commits: str = "",
        statuses: dict[str, list[str]] | None = None,
        head: str = "",
        head_exists: bool = False,
        authenticated: bool = True,
        fail_on: str = "",
    ) -> subprocess.CompletedProcess[str]:
        statuses = statuses or {}
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            status_cases = "\n".join(
                "    *commits/{sha}/status*) printf '%s\\n' \"{lines}\" ;;".format(
                    sha=sha, lines="\\n".join(entries)
                )
                for sha, entries in statuses.items()
            )
            stub = [
                "#!/bin/sh",
                # gh api exits 4 when authentication is required; the script keys off
                # that rather than a `gh auth status` pre-flight.
                f'{"" if authenticated else "exit 4"}',
                # Find the URL wherever it sits: flags such as --paginate shift it.
                'url=""',
                'for arg in "$@"; do case "$arg" in repos/*) url="$arg"; break ;; esac; done',
            ]
            if fail_on:
                stub.append(f'case "$url" in {fail_on}) exit 1 ;; esac')
            stub += [
                'case "$url" in',
                f'    */branches/main) echo "{protected}" ;;',
                # Commit-existence probe for a local HEAD outside the candidate lists.
                (
                    f'    */commits/{head}) echo "{head}" ;;'
                    if head and head_exists
                    else f'    */commits/{head}) exit 1 ;;'
                    if head
                    else "    */commits/__none__) : ;;"
                ),
                f"    *branches/main/protection) printf '%s\\n' \"{required}\" ;;",
                f"    *pulls\\?*) printf '%s\\n' \"{pulls}\" ;;",
                f"    *commits\\?*) printf '%s\\n' \"{commits}\" ;;",
                status_cases,
                "    *commits/*/status*) echo '' ;;",
                # Fail loudly on an unmatched URL. A silently-unmatched pattern makes
                # every case pass, which has already happened twice: once when
                # --paginate moved the URL out of $2, once when ?per_page was appended.
                '    *) echo "STUB: unmatched url [$url]" >&2; exit 99 ;;',
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
        result = self.run_check(commits="sha1", statuses={"sha1": [HCP_OLD]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("STUB: unmatched", result.stderr)

    def test_stale_context_on_an_open_pr_head_is_caught(self) -> None:
        """The incident: main still carries the old context, the PR carries the new one.

        Checking `main` first reports green here, which is how this shipped
        broken twice.
        """
        result = self.run_check(
            required=HCP_OLD,
            pulls="prsha",
            commits="mainsha",
            statuses={"prsha": [HCP_NEW], "mainsha": [HCP_OLD]},
            head="mainsha",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("BLOCKED", result.stderr)
        self.assertIn(HCP_OLD, result.stderr)

    def test_greenfield_without_protection_passes(self) -> None:
        """setup ends at green speculative plans, so protection is not applied yet."""
        result = self.run_check(protected="false")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_absent_protection_always_passes(self) -> None:
        """Even with HCP already publishing, which is the greenfield state.

        setup ends before applying branch_protection.tf while HCP is already
        posting aggregated statuses, so no signal here separates "not applied
        yet" from "removed". An earlier revision guessed from published
        statuses and blocked the greenfield flow.
        """
        result = self.run_check(
            protected="false",
            commits="sha1",
            statuses={"sha1": [HCP_OLD]},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_candidates_are_scoped_to_the_protected_branch(self) -> None:
        """The commits API defaults sha to the *default* branch, which need not be main.

        Unfiltered, the pulls request also admits PRs based on other branches.
        """
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("--paginate", script)
        self.assertIn("base=main", script)
        self.assertIn("sha=main", script)

    def test_a_late_finishing_old_run_cannot_clear_a_blocked_pr(self) -> None:
        """The failure mode that killed newest-timestamp selection.

        An in-flight pre-rebuild run finishing after the new-connection run made
        the newest status the old context, which matched `required`, so the
        check passed while the PR carrying the new context waited forever.
        """
        result = self.run_check(
            required=HCP_OLD,
            pulls="newpr latepr",
            commits="mainsha",
            statuses={"newpr": [HCP_NEW], "latepr": [HCP_OLD], "mainsha": [HCP_OLD]},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("newpr", result.stderr)

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

    def test_underprotected_is_reported_before_later_reads_can_fail(self) -> None:
        """A proven verdict must not be downgraded to CANNOT VERIFY.

        Once protection is known to require no HCP context the answer is
        settled; a rate-limited PR listing afterwards would otherwise hide it.
        """
        result = self.run_check(required="", fail_on="*pulls*")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("UNDERPROTECTED", result.stderr)

    def test_local_head_is_not_a_candidate(self) -> None:
        """HEAD adds nothing PR heads and recent commits do not already carry.

        No single gh exit code separates "not on the remote" from "the request
        failed", so a HEAD candidate could not be handled safely either way.
        """
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("rev-parse", script)
        result = self.run_check(
            commits="sha1", statuses={"sha1": [HCP_OLD]}, head="ignored"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_open_pr_is_checked_not_just_one(self) -> None:
        """One PR publishing the required context must not clear another that does not.

        Each PR is blocked independently, so a single global "current context"
        cannot express the invariant. Two attempts proved it: first-match let an
        old commit win, and newest-timestamp let a pre-rebuild run finishing
        late win.
        """
        result = self.run_check(
            required=HCP_OLD,
            pulls="oldpr newpr",
            commits="mainsha",
            statuses={
                "oldpr": [HCP_OLD],
                "newpr": [HCP_NEW],
                "mainsha": [HCP_OLD],
            },
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("BLOCKED", result.stderr)

    def test_per_commit_status_failure_does_not_report_green(self) -> None:
        result = self.run_check(fail_on="*commits/*/status*", commits="sha1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not read commit status", result.stderr)

    def test_unreadable_pr_head_does_not_fall_back_to_an_older_match(self) -> None:
        """PR head read fails while main carries a matching status.

        Treating that failure as "no status here" would accept main's older
        matching context and report a blocked PR as healthy.
        """
        result = self.run_check(
            required=HCP_OLD,
            pulls="prsha",
            commits="mainsha",
            statuses={"mainsha": [HCP_OLD]},
            fail_on="*commits/prsha/status*",
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("could not read commit status for prsha", result.stderr)

    def test_no_published_hcp_status_anywhere_is_unverifiable_not_broken(self) -> None:
        """Non-HCP statuses are filtered out by the jq selector, so nothing is published."""
        result = self.run_check(commits="sha1", statuses={"sha1": []})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_repo_variable_fails_loudly(self) -> None:
        result = subprocess.run(
            ["sh", str(SCRIPT)],
            env={k: v for k, v in os.environ.items() if k != "REPO"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("REPO is not set", result.stderr)

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
