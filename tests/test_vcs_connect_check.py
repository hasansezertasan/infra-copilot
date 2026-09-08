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
def workspace(identifier: str, *, connection: str = "oauth", pages: int = 1) -> str:
    """One workspace, connected by `oauth`, `app`, or not at all (`none`).

    hcp.md's create_ws connects through oauth-token-id, so that is the shape the
    real flow produces -- an earlier fix required the App field and rejected it.
    """
    markers = {
        "oauth": '"oauth-token-id":"ot-1","github-app-installation-id":null',
        "app": '"oauth-token-id":null,"github-app-installation-id":"ghi-1"',
        "none": '"oauth-token-id":null,"github-app-installation-id":null',
    }[connection]
    return (
        '{"data":[{"attributes":{"vcs-repo":{"identifier":"%s",%s}}}],'
        '"meta":{"pagination":{"total-pages":%d}}}' % (identifier, markers, pages)
    )


CONNECTED_WORKSPACE = workspace("acme/infra")
OTHER_WORKSPACE = workspace("acme/other")
#: Right identifier, but no VCS connection at all.
UNCONNECTED_WORKSPACE = workspace("acme/infra", connection="none")


def extract_check() -> str:
    body = MANIFEST.read_text(encoding="utf-8")
    match = re.search(r"- id: vcs-connect.*?check: \|\n(.*?)\n    produces:", body, re.S)
    assert match, "vcs-connect's block check is no longer where this test looks"
    return textwrap.dedent(match.group(1))


@unittest.skipUnless(os.name == "posix", "the check is POSIX shell")
class VcsConnectCheckTests(unittest.TestCase):
    def run_check(
        self,
        *,
        code: str,
        oauth_body: str,
        workspace_body: str = "{}",
        repo: str = "acme/infra",
        later_pages: dict[int, str] | None = None,
        transport_fails: bool = False,
        hcp_api: str = "https://app.terraform.io/api/v2",
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            # Two URLs, two bodies. The stub writes to whatever -o names, which is
            # how the check collects both responses in one temp file.
            stub = Path(directory) / "curl"
            stub.write_text(
                "#!/bin/sh\n"
                + ("exit 6\n" if transport_fails else "")
                + 'out=""; prev=""; url=""\n'
                'for a in "$@"; do\n'
                '  case "$prev" in -o) out="$a" ;; esac\n'
                '  case "$a" in http*) url="$a" ;; esac\n'
                '  prev="$a"\n'
                "done\n"
                'printf "%s\\n" "$url" >> "$CALLS"\n'
                'case "$url" in\n'
                f'  https://app.terraform.io/api/v2/organizations/*/oauth-clients*) body={oauth_body!r}; printf "%s" "$body" > "${{out:-/dev/stdout}}"; printf "%s" {code!r} ;;\n'
                f'  https://app.terraform.io/api/v2/organizations/*/workspaces*)\n'
                f'    page=1\n'
                f'    for a in "$@"; do case "$a" in *page%5Bnumber%5D=*) page=${{a##*page%5Bnumber%5D=}}; page=${{page%%&*}} ;; esac; done\n'
                + "".join(
                    f'    [ "$page" != {number} ] || body={page_body!r}\n'
                    for number, page_body in (later_pages or {}).items()
                )
                + f'    [ "$page" = 1 ] && body={workspace_body!r} || true\n'
                f'    [ "${{body:-}}" != "" ] || body={workspace_body!r}\n'
                f'    [ {workspace_body!r} != "{{}}" ] || exit 22\n'
                '    if [ -n "$out" ]; then printf "%s" "$body" > "$out"; else printf "%s" "$body"; fi ;;\n'
                '  *) echo "unstubbed: $url" >&2; exit 99 ;;\n'
                "esac\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{directory}:{environment['PATH']}"
            calls = Path(directory) / "calls"
            environment["CALLS"] = str(calls)
            environment.update(
                {
                    "ORG": "acme",
                    "REPO": repo,
                    "HCP_TOKEN": "token",
                    "hcp_api": hcp_api,
                }
            )
            result = subprocess.run(
                ["/bin/sh", "-c", extract_check()],
                capture_output=True,
                text=True,
                env=environment,
                cwd=directory,
            )
            # Attached so a test can assert no request was attempted at all.
            result.requests = (  # type: ignore[attr-defined]
                calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            )
            return result

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

    def test_unparseable_json_is_reported_as_a_cause(self) -> None:
        """jq -e exits 5 on invalid JSON and 4 on empty input.

        The step is tri-state, and protocol.md honours 0, 1 and 2 only, so those
        codes must not escape as an unexpected exit.
        """
        for body, label in (("not json", "invalid"), ("", "empty")):
            with self.subTest(body=label):
                result = self.run_check(code="200", oauth_body=body)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("could not be parsed", result.stderr)

    def test_the_oauth_connection_this_manifest_creates_is_evidence(self) -> None:
        """create_ws connects through oauth-token-id, not a GitHub App.

        Requiring the App field rejected every workspace the documented flow
        provisions, so the fallback exited 2 and blocked resume -- the state it
        was added to prevent.
        """
        result = self.run_check(
            code="403", oauth_body="{}", workspace_body=workspace("acme/infra")
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_github_app_connection_is_also_evidence(self) -> None:
        result = self.run_check(
            code="403",
            oauth_body="{}",
            workspace_body=workspace("acme/infra", connection="app"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_workspace_with_no_vcs_connection_is_not_evidence(self) -> None:
        """Matching identifier alone does not show a connection exists."""
        result = self.run_check(
            code="403", oauth_body="{}", workspace_body=UNCONNECTED_WORKSPACE
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("VCS-connected", result.stderr)

    def test_a_transport_failure_names_itself(self) -> None:
        """A tri-state 2 with empty stderr gives the operator nothing to fix."""
        result = self.run_check(code="", oauth_body="{}", transport_fails=True)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("did not complete", result.stderr)

    def test_the_fallback_follows_pagination(self) -> None:
        """The workspace may sit past the first page of a large organization."""
        result = self.run_check(
            code="403",
            oauth_body="{}",
            workspace_body=workspace("acme/other", pages=2),
            later_pages={2: workspace("acme/infra", pages=2)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_fallback_stops_when_pagination_is_unreadable(self) -> None:
        result = self.run_check(
            code="403",
            oauth_body="{}",
            workspace_body='{"data":[],"meta":{"pagination":{"total-pages":"lots"}}}',
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("total-pages", result.stderr)

    def test_a_server_error_cannot_be_verified(self) -> None:
        result = self.run_check(code="500", oauth_body="{}")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("500", result.stderr)

    def test_an_unexpected_api_endpoint_is_refused_before_any_request(self) -> None:
        """These requests are separate from hcp-apply-scope's own guard.

        The stub exits 99 on an unrecognised URL, so a request that slipped
        through the guard would surface rather than pass quietly.
        """
        for endpoint in (
            "http://app.terraform.io/api/v2",
            "https://evil.example/api/v2",
        ):
            with self.subTest(endpoint=endpoint):
                result = self.run_check(
                    code="200", oauth_body=GITHUB_CLIENT, hcp_api=endpoint
                )
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("refusing to send", result.stderr)
                # The point is that the credential never leaves the machine, so
                # assert no request was attempted rather than only that the exit
                # code is right.
                self.assertEqual(result.requests, [], result.requests)

    def test_the_allowed_endpoint_does_reach_the_stub(self) -> None:
        """Guards the assertion above: it must fail for a real reason."""
        result = self.run_check(code="200", oauth_body=GITHUB_CLIENT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.requests, "no request was recorded at all")

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
