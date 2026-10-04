"""Behavioural tests for the vcs-connect check in steps.yaml.

The check became tri-state because the plan-only credential `hcp-apply-scope`
installs cannot read organization VCS settings. Without that, a resume scan
stopped at the first non-zero check and re-emitted the OAuth handoff, so
`setup` could never resume past phase 1 after the handoff -- and told the
human to redo a step that was already done.

It has to tell four states apart: connected (organization read), not connected,
connected but only provable from a workspace, and unreadable. An organization
with no GitHub OAuth client may still be connected through the GitHub App, which
workspace evidence shows (#89), or user-scoped installation discovery before
the first workspace exists (#95).

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


def oauth_page(*providers: str, total_pages: int = 1, fill: bool = False) -> str:
    """An oauth-clients page. `fill` pads it to the 100-entry page size.

    A short page is treated as the last one, so a multi-page test has to make
    the earlier page genuinely full.
    """
    entries = [f'{{"attributes":{{"service-provider":"{p}"}}}}' for p in providers]
    if fill:
        pad = '{"attributes":{"service-provider":"gitlab"}}'
        entries += [pad] * (100 - len(entries))
    return (
        '{"data":[%s],"meta":{"pagination":{"total-pages":%d}}}'
        % (",".join(entries), total_pages)
    )
NO_CLIENT = '{"data":[]}'
GITLAB_ONLY = '{"data":[{"attributes":{"service-provider":"gitlab"}}]}'
def workspace(identifier: str, *, connection: str = "oauth", pages: int = 1) -> str:
    """One workspace, connected by `oauth`, `app`, or not at all (`none`).

    hcp.md supports either connection; OAuth remains the default fixture so
    the narrowed-token fallback keeps covering it.
    """
    markers = {
        "oauth": '"oauth-token-id":"ot-1","github-app-installation-id":null',
        "app": '"oauth-token-id":null,"github-app-installation-id":"ghi-1"',
        "none": '"oauth-token-id":null,"github-app-installation-id":null',
        "empty-app": '"oauth-token-id":null,"github-app-installation-id":""',
    }[connection]
    return (
        '{"data":[{"attributes":{"vcs-repo":{"identifier":"%s",%s}}}],'
        '"meta":{"pagination":{"total-pages":%d}}}' % (identifier, markers, pages)
    )


def workspace_page(identifier: str, *, pages: int) -> str:
    """A full 100-entry workspace page; a shorter one is read as the last."""
    entry = '{"attributes":{"vcs-repo":{"identifier":"%s","oauth-token-id":null}}}' % identifier
    return '{"data":[%s],"meta":{"pagination":{"total-pages":%d}}}' % (
        ",".join([entry] * 100),
        pages,
    )


CONNECTED_WORKSPACE = workspace("acme/infra")
OTHER_WORKSPACE = workspace("acme/other")
#: Right identifier, but no VCS connection at all.
UNCONNECTED_WORKSPACE = workspace("acme/infra", connection="none")
#: A readable workspace list with nothing in it -- a fresh organization.
NO_WORKSPACES = '{"data":[],"meta":{"pagination":{"total-pages":1}}}'


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
        app_body: str = NO_CLIENT,
        app_unreadable: bool = False,
        workspace_body: str = "{}",
        repo: str = "acme/infra",
        later_pages: dict[int, str] | None = None,
        later_oauth_pages: dict[int, str] | None = None,
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
                f'  https://app.terraform.io/api/v2/organizations/*/oauth-clients*)\n'
                f'    page=1\n'
                f'    for a in "$@"; do case "$a" in *page%5Bnumber%5D=*) page=${{a##*page%5Bnumber%5D=}}; page=${{page%%&*}} ;; esac; done\n'
                + "".join(
                    f'    [ "$page" != {number} ] || body={page_body!r}\n'
                    for number, page_body in (later_oauth_pages or {}).items()
                )
                + f'    [ "${{body:-}}" != "" ] || body={oauth_body!r}\n'
                f'    printf "%s" "$body" > "${{out:-/dev/stdout}}"; printf "%s" {code!r} ;;\n'
                f'  https://app.terraform.io/api/v2/github-app/installations*) {"exit 22" if app_unreadable else f"printf %s {app_body!r}"} ;;\n'
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
                    "INFRA_COPILOT_REFERENCES": str(MANIFEST.parent),
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

    def test_fresh_app_installation_is_green_without_workspaces(self) -> None:
        result = self.run_check(code="200", oauth_body=NO_CLIENT,
            workspace_body=NO_WORKSPACES,
            app_body='{"data":[{"id":"ghain-test","attributes":{"name":"acme"}}]}')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_app_evidence_unreadable_is_unknown(self) -> None:
        result = self.run_check(code="200", oauth_body=NO_CLIENT,
            workspace_body=NO_WORKSPACES, app_unreadable=True)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_malformed_app_response_is_unknown(self) -> None:
        result = self.run_check(code="200", oauth_body=NO_CLIENT,
            workspace_body=NO_WORKSPACES, app_body='{"errors":[]}')
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_other_owners_installation_is_red(self) -> None:
        result = self.run_check(code="200", oauth_body=NO_CLIENT,
            workspace_body=NO_WORKSPACES,
            app_body='{"data":[{"id":"ghain-test","attributes":{"name":"other"}}]}')
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_ambiguous_app_installations_are_red(self) -> None:
        result = self.run_check(code="200", oauth_body=NO_CLIENT,
            workspace_body=NO_WORKSPACES,
            app_body='{"data":[{"id":"ghain-one","attributes":{"name":"acme"}},'
                     '{"id":"ghain-two","attributes":{"name":"acme"}}]}')
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_github_client_is_green(self) -> None:
        result = self.run_check(code="200", oauth_body=GITHUB_CLIENT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_client_is_red(self) -> None:
        """A readable answer of "not connected" is a verdict, not uncertainty."""
        result = self.run_check(
            code="200", oauth_body=NO_CLIENT, workspace_body=NO_WORKSPACES
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_no_client_with_a_github_app_workspace_is_green(self) -> None:
        """Issue #89: an App-only organization has no OAuth client at all.

        Exiting 1 on the empty list kept the step permanently red although every
        workspace was VCS-connected.
        """
        result = self.run_check(
            code="200",
            oauth_body=NO_CLIENT,
            workspace_body=workspace("acme/infra", connection="app"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_github_client_does_not_accept_an_oauth_token_workspace(self) -> None:
        """With every client read and none GitHub, the token is another provider's.

        Accepting it would let a GitLab workspace for the same owner/name turn
        the step green.
        """
        result = self.run_check(
            code="200", oauth_body=GITLAB_ONLY, workspace_body=CONNECTED_WORKSPACE
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("GitHub App", result.stderr)

    def test_no_client_with_an_app_workspace_for_another_repo_is_red(self) -> None:
        result = self.run_check(
            code="200",
            oauth_body=NO_CLIENT,
            workspace_body=workspace("acme/other", connection="app"),
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_no_client_after_every_oauth_page_reaches_the_app_fallback(self) -> None:
        """The total-pages exit is the other way the listing can complete."""
        result = self.run_check(
            code="200",
            oauth_body=oauth_page(total_pages=1, fill=True),
            workspace_body=workspace("acme/infra", connection="app"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_client_finds_an_app_workspace_on_a_later_page(self) -> None:
        result = self.run_check(
            code="200",
            oauth_body=NO_CLIENT,
            workspace_body=workspace_page("acme/other", pages=2),
            later_pages={2: workspace("acme/infra", connection="app", pages=2)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_short_workspace_page_without_pagination_metadata_is_conclusive(self) -> None:
        """Mirrors the oauth-clients rule: a short page is the last one."""
        result = self.run_check(
            code="200", oauth_body=NO_CLIENT, workspace_body='{"data":[]}'
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_workspace_list_without_a_data_array_cannot_be_verified(self) -> None:
        """An errors body is not an empty last page, so it is not a verdict."""
        for body in ('{"errors":[{"status":"500"}]}', '{"data":null}'):
            with self.subTest(body=body):
                result = self.run_check(
                    code="200", oauth_body=NO_CLIENT, workspace_body=body
                )
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("not the expected JSON", result.stderr)

    def test_total_pages_outranks_a_short_workspace_page(self) -> None:
        """A short page that promises a successor is not the last one."""
        result = self.run_check(
            code="403",
            oauth_body="{}",
            workspace_body=workspace("acme/other", pages=2),
            later_pages={2: workspace("acme/infra", pages=2)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_empty_app_installation_id_is_not_evidence(self) -> None:
        result = self.run_check(
            code="200",
            oauth_body=GITLAB_ONLY,
            workspace_body=workspace("acme/infra", connection="empty-app"),
        )
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_no_client_with_repo_unset_cannot_be_verified(self) -> None:
        """Without $REPO nothing can match, so red would be a guess."""
        result = self.run_check(
            code="200", oauth_body=NO_CLIENT, workspace_body=NO_WORKSPACES, repo=""
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("REPO is unset", result.stderr)

    def test_no_client_with_an_unreadable_workspace_list_cannot_be_verified(self) -> None:
        """An App connection may exist; not being able to look is not a verdict."""
        result = self.run_check(code="200", oauth_body=NO_CLIENT)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no GitHub OAuth client", result.stderr)

    def test_a_github_client_on_a_later_page_is_found(self) -> None:
        """Reading only the first page concluded "no GitHub client".

        The resume protocol then re-emitted the OAuth handoff for a connection
        that exists. The first page is padded to the page size, since a short
        page is treated as the last one.
        """
        result = self.run_check(
            code="200",
            oauth_body=oauth_page(total_pages=2, fill=True),
            later_oauth_pages={2: oauth_page("github_app", total_pages=2)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_full_page_without_pagination_metadata_cannot_be_verified(self) -> None:
        """A full page might have a successor; a short one cannot."""
        result = self.run_check(
            code="200", oauth_body='{"data":[%s]}' % ",".join(
                ['{"attributes":{"service-provider":"gitlab"}}'] * 100
            )
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("filled a page", result.stderr)

    def test_a_short_page_without_pagination_metadata_is_conclusive(self) -> None:
        """meta.pagination is not required in HCP's schema.

        Demanding it unconditionally would report CANNOT VERIFY for every
        organization whose response omits it.
        """
        result = self.run_check(
            code="200", oauth_body='{"data":[]}', workspace_body=NO_WORKSPACES
        )
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_a_non_github_client_is_red(self) -> None:
        result = self.run_check(
            code="200", oauth_body=GITLAB_ONLY, workspace_body=NO_WORKSPACES
        )
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
            workspace_body=workspace_page("acme/other", pages=2),
            later_pages={2: workspace("acme/infra", pages=2)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_fallback_stops_when_pagination_is_unreadable(self) -> None:
        result = self.run_check(
            code="403",
            oauth_body="{}",
            workspace_body=workspace_page("acme/other", pages=2).replace(
                '"total-pages":2', '"total-pages":"lots"'
            ),
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
