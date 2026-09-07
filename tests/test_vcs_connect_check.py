"""Behavioural tests for the vcs-connect check in steps.yaml.

The check became tri-state because the plan-only credential `hcp-apply-scope`
installs cannot read organization VCS settings. Without that, a resume scan
stopped at the first non-zero check and re-emitted the OAuth handoff, so
`setup` could never resume past phase 1 after the handoff -- and told the
human to redo a step that was already done.

It has to tell four states apart: connected (organization read), not connected,
connected but only provable from a workspace, and unreadable.

The check lives in the manifest rather than a shipped script, so these extract
it from steps.yaml and run it with `curl` stubbed. Extracting keeps the test
honest about drift: rewriting the check rewrites what runs here.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/steps.yaml"

GITHUB_CLIENT = '{"data":[{"attributes":{"service-provider":"github_app"}}]}'
NO_CLIENT = '{"data":[]}'
GITLAB_ONLY = '{"data":[{"attributes":{"service-provider":"gitlab"}}]}'
CONNECTED_WORKSPACE = '{"data":[{"attributes":{"vcs-repo":{"identifier":"acme/infra"}}}]}'
OTHER_WORKSPACE = '{"data":[{"attributes":{"vcs-repo":{"identifier":"acme/other"}}}]}'


def extract_check() -> str:
    body = MANIFEST.read_text(encoding="utf-8")
    match = re.search(r"- id: vcs-connect.*?check: \|\n(.*?)\n    produces:", body, re.S)
    assert match, "vcs-connect's block check is no longer where this test looks"
    return textwrap.dedent(match.group(1))


@unittest.skipUnless(os.name == "posix", "the check is POSIX shell")
class VcsConnectCheckTests(unittest.TestCase):
    def run_check(
        self, *, code: str, oauth_body: str, workspace_body: str = "{}", repo: str = "acme/infra"
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            # Two URLs, two bodies. The stub writes to whatever -o names, which is
            # how the check collects both responses in one temp file.
            stub = Path(directory) / "curl"
            stub.write_text(
                "#!/bin/sh\n"
                'out=""; prev=""; url=""\n'
                'for a in "$@"; do\n'
                '  case "$prev" in -o) out="$a" ;; esac\n'
                '  case "$a" in http*) url="$a" ;; esac\n'
                '  prev="$a"\n'
                "done\n"
                'case "$url" in\n'
                f'  *oauth-clients*) body={oauth_body!r}; printf "%s" "$body" > "${{out:-/dev/stdout}}"; printf "%s" {code!r} ;;\n'
                f'  *workspaces*) body={workspace_body!r};\n'
                f'    [ {workspace_body!r} != "{{}}" ] || exit 22\n'
                '    if [ -n "$out" ]; then printf "%s" "$body" > "$out"; else printf "%s" "$body"; fi ;;\n'
                '  *) echo "unstubbed: $url" >&2; exit 99 ;;\n'
                "esac\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{directory}:{environment['PATH']}"
            environment.update(
                {
                    "ORG": "acme",
                    "REPO": repo,
                    "HCP_TOKEN": "token",
                    "hcp_api": "https://app.terraform.io/api/v2",
                }
            )
            return subprocess.run(
                ["/bin/sh", "-c", extract_check()],
                capture_output=True,
                text=True,
                env=environment,
                cwd=directory,
            )

    def test_a_github_client_is_green(self) -> None:
        result = self.run_check(code="200", oauth_body=GITHUB_CLIENT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_client_is_red(self) -> None:
        """A readable answer of "not connected" is a verdict, not uncertainty."""
        result = self.run_check(code="200", oauth_body=NO_CLIENT)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_non_github_client_is_red(self) -> None:
        result = self.run_check(code="200", oauth_body=GITLAB_ONLY)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_forbidden_falls_back_to_workspace_evidence(self) -> None:
        """The case that made `setup` unresumable after the token handoff.

        The plan-only credential cannot read organization VCS settings, but a
        workspace connected to $REPO proves the same connection and is
        workspace-scoped.
        """
        result = self.run_check(
            code="403", oauth_body="{}", workspace_body=CONNECTED_WORKSPACE
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_forbidden_with_no_matching_workspace_cannot_be_verified(self) -> None:
        """Another repo's workspace is not evidence about this one."""
        result = self.run_check(
            code="403", oauth_body="{}", workspace_body=OTHER_WORKSPACE
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_forbidden_with_an_unreadable_workspace_list_cannot_be_verified(self) -> None:
        result = self.run_check(code="403", oauth_body="{}")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_a_server_error_cannot_be_verified(self) -> None:
        result = self.run_check(code="500", oauth_body="{}")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("500", result.stderr)

    def test_the_step_is_declared_tri_state(self) -> None:
        """Exit 2 is only honoured for steps carrying the flag."""
        block = re.search(
            r"- id: vcs-connect.*?(?=\n  - id: )",
            MANIFEST.read_text(encoding="utf-8"),
            re.S,
        )
        assert block
        self.assertIn("tri_state: true", block.group(0))


if __name__ == "__main__":
    unittest.main()
