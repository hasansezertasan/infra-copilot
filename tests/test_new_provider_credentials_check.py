"""Behavioural tests for the new-provider-credentials check in steps.yaml.

HCP's workspace vars endpoint is not paginated: its OpenAPI spec declares no page
parameters and no `meta` in the response. The check used to demand
`meta.pagination` on every page, so it exited 2 (CANNOT VERIFY) for every
workspace, forever (#90).

Like the vcs-connect tests, these extract the check from steps.yaml and run it
with `curl` stubbed, so rewriting the check rewrites what runs here.
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

DECLARED = [
    {"key": "GOOGLE_CREDENTIALS", "category": "env", "sensitive": True},
    {"key": "project_id", "category": "terraform", "sensitive": False},
]


def variables(declared: list[dict[str, object]]) -> list[dict[str, object]]:
    """Workspace vars as HCP lists them; a sensitive value reads back as null."""
    return [
        {"id": f"var-{index}", "type": "vars", "attributes": {
            **entry, "value": None if entry["sensitive"] else "x", "hcl": False,
        }}
        for index, entry in enumerate(declared)
    ]


#: The real response shape: `data` only, no `meta`, no `links`.
UNPAGINATED = json.dumps({"data": variables(DECLARED)})


def extract_check() -> str:
    body = MANIFEST.read_text(encoding="utf-8")
    match = re.search(
        r"- id: new-provider-credentials\n.*?check: \|\n(.*?)\n    tri_state:", body, re.S
    )
    assert match, "new-provider-credentials' check is no longer where this test looks"
    return textwrap.dedent(match.group(1))


@unittest.skipUnless(os.name == "posix", "the check is POSIX shell")
class NewProviderCredentialsCheckTests(unittest.TestCase):
    def run_check(
        self,
        *,
        vars_body: str = UNPAGINATED,
        varsets: int = 0,
        declared: list[dict[str, object]] = DECLARED,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (root / "vars.json").write_text(vars_body, encoding="utf-8")
            (root / "varsets.json").write_text(
                json.dumps({"data": [{"id": f"varset-{i}"} for i in range(varsets)],
                            "meta": {"pagination": {"next-page": None}}}),
                encoding="utf-8",
            )
            stub = bin_dir / "curl"
            stub.write_text(
                "#!/bin/sh\n"
                'for a in "$@"; do case "$a" in http*) url="$a" ;; esac; done\n'
                'printf "%s\\n" "$url" >> "$CALLS"\n'
                'case "$url" in\n'
                '  */organizations/acme/workspaces/gcp) echo \'{"data":{"id":"ws-abc"}}\' ;;\n'
                f'  */workspaces/ws-abc/varsets*) cat "{root}/varsets.json" ;;\n'
                f'  */workspaces/ws-abc/vars*) cat "{root}/vars.json" ;;\n'
                '  *) echo "unstubbed: $url" >&2; exit 99 ;;\n'
                "esac\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)

            repo = root / "repo"
            (repo / ".infra-copilot").mkdir(parents=True)
            (repo / ".infra-copilot/config.md").write_text("config\n", encoding="utf-8")
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run([*git, "add", "."], cwd=repo, check=True)
            subprocess.run([*git, "commit", "-qm", "config"], cwd=repo, check=True)

            calls = root / "calls"
            environment = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "CALLS": str(calls),
                "hcp_api": "https://app.terraform.io/api/v2",
                "ORG": "acme",
                "NEW_PROVIDER_WORKSPACE": "gcp",
                "HCP_TOKEN": "token",
                "NEW_PROVIDER_CREDENTIALS": json.dumps(declared),
                "NEW_PROVIDER_CREDENTIALS_VERIFIED_AT": "2026-01-01T00:00:00Z",
            }
            result = subprocess.run(
                ["/bin/sh", "-c", extract_check()],
                capture_output=True,
                text=True,
                env=environment,
                cwd=repo,
            )
            result.requests = (  # type: ignore[attr-defined]
                calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            )
            return result

    def test_an_unpaginated_response_matching_the_inventory_is_green(self) -> None:
        """Issue #90: the real response has no meta.pagination and must verify."""
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_vars_request_sends_no_page_parameters(self) -> None:
        """The endpoint declares none; sending them implied a paging that does not exist."""
        result = self.run_check()
        vars_calls = [url for url in result.requests if url.endswith("/vars") or "/vars?" in url]  # type: ignore[attr-defined]
        self.assertEqual(vars_calls, ["https://app.terraform.io/api/v2/workspaces/ws-abc/vars"])

    def test_more_than_a_page_size_of_variables_is_still_one_complete_list(self) -> None:
        """No page size applies, so a long list is not a partial one."""
        declared = DECLARED + [
            {"key": f"extra_{i:03}", "category": "terraform", "sensitive": False}
            for i in range(120)
        ]
        result = self.run_check(
            vars_body=json.dumps({"data": variables(declared)}), declared=declared
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_undeclared_variable_is_red(self) -> None:
        extra = DECLARED + [{"key": "LEFTOVER", "category": "env", "sensitive": False}]
        result = self.run_check(vars_body=json.dumps({"data": variables(extra)}))
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_missing_declared_variable_is_red(self) -> None:
        result = self.run_check(vars_body=json.dumps({"data": variables(DECLARED[:1])}))
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_an_attached_variable_set_is_red(self) -> None:
        result = self.run_check(varsets=1)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_a_named_next_page_cannot_be_verified(self) -> None:
        """Should HCP start paginating, one response would be a partial inventory."""
        body = json.dumps({
            "data": variables(DECLARED),
            "meta": {"pagination": {"current-page": 1, "next-page": 2}},
        })
        result = self.run_check(vars_body=body)
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_pagination_metadata_without_a_next_page_is_green(self) -> None:
        body = json.dumps({
            "data": variables(DECLARED),
            "meta": {"pagination": {"current-page": 1, "next-page": None}},
        })
        result = self.run_check(vars_body=body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_body_without_a_data_array_cannot_be_verified(self) -> None:
        for body in ('{"errors":[{"status":"404"}]}', "not json", '{"data":null}'):
            with self.subTest(body=body):
                self.assertEqual(self.run_check(vars_body=body).returncode, 2)


if __name__ == "__main__":
    unittest.main()
