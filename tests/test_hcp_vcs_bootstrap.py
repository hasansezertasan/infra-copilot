"""Execute the shipped HCP helpers with a mocked API."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / ".ai-rulez/skills/infra-copilot/references"
HCP = REFS / "hcp.md"


@unittest.skipUnless(os.name == "posix", "shell helpers require POSIX")
class HcpVcsBootstrapTests(unittest.TestCase):
    def run_helper(self, command, *, app=None, oauth=None, existing=None, overrides=None, app_pages=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = {
                "apps": {"data": app or []},
                "app_pages": app_pages or {},
                "oauth": {"data": oauth or []},
                "workspace": {"data": {"id": "ws-test", "attributes": {
                    "working-directory": "terraform/github",
                    "vcs-repo": existing or {"identifier": "acme/infra",
                        "github-app-installation-id": "ghain-existing"},
                }}},
            }
            (root / "fixtures").write_text(json.dumps(fixtures))
            stub = root / "curl"
            stub.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
f = json.loads(Path(os.environ["FIXTURES"]).read_text())
url = next(x for x in a if x.startswith("https://"))
method = a[a.index("-X")+1] if "-X" in a else "GET"
if method != "GET":
    value = a[a.index("-d")+1]
    payload = sys.stdin.read() if value == "@-" else value
    with open(os.environ["PAYLOADS"], "a") as out:
        out.write(json.dumps({"method": method, "payload": json.loads(payload)})+"\\n")
    print("{}")
    if "-w" in a: print("201")
elif "/github-app/installations" in url:
    page = url.split("page%5Bnumber%5D=")[-1]
    code = os.environ.get("APP_STATUS", "200")
    if os.environ.get("APP_TRANSPORT_FAILS") == "yes": sys.exit(6)
    if "-sf" in a and code != "200": sys.exit(22)
    body = json.dumps(f["app_pages"].get(page, f["apps"]))
    if "-o" in a: Path(a[a.index("-o")+1]).write_text(body)
    else: print(body)
    if "-w" in a: print(code)
elif "/oauth-clients" in url:
    print(json.dumps(f["oauth"]))
elif "/workspaces/" in url:
    if os.environ.get("HAS_WORKSPACE") == "yes": print(json.dumps(f["workspace"]))
    else: sys.exit(22)
else:
    sys.exit(99)
""")
            stub.chmod(0o755)
            env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                   "FIXTURES": str(root / "fixtures"), "PAYLOADS": str(root / "payloads"),
                   "ORG": "hcp-org", "REPO": "acme/infra", "HCP_TOKEN": "test",
                   "TERRAFORM_VERSION": "1.14.0",
                   "INFRA_COPILOT_REFERENCES": str(REFS)}
            for key in ("OAUTH_TOKEN_ID", "GITHUB_APP_INSTALLATION_ID"):
                env.pop(key, None)
            env.update(overrides or {})
            body = HCP.read_text().split("  load_tf_version () {", 1)[1]
            body = "load_tf_version () {" + body.split("  # Gate with if/else", 1)[0]
            result = subprocess.run(["bash", "-c", textwrap.dedent(body) + "\n" + command],
                                    env=env, capture_output=True, text=True)
            payloads = root / "payloads"
            return result, [json.loads(line) for line in payloads.read_text().splitlines()] if payloads.exists() else []

    def test_fresh_app_org_can_create_workspace(self):
        result, payloads = self.run_helper(
            'resolve_vcs_connection && create_ws github-org terraform/github',
            app=[{"id": "ghain-test", "attributes": {"name": "acme"}}])
        self.assertEqual(result.returncode, 0, result.stderr)
        vcs = payloads[0]["payload"]["data"]["attributes"]["vcs-repo"]
        self.assertEqual(vcs["github-app-installation-id"], "ghain-test")
        self.assertNotIn("oauth-token-id", vcs)

    def test_fresh_oauth_org_can_create_workspace(self):
        result, payloads = self.run_helper(
            'resolve_vcs_connection && create_ws github-org terraform/github',
            oauth=[{"attributes": {"service-provider": "github"},
                    "relationships": {"oauth-tokens": {"data": [{"id": "ot-test"}]}}}])
        self.assertEqual(result.returncode, 0, result.stderr)
        vcs = payloads[0]["payload"]["data"]["attributes"]["vcs-repo"]
        self.assertEqual(vcs["oauth-token-id"], "ot-test")
        self.assertNotIn("github-app-installation-id", vcs)

    def test_mixed_fresh_connections_require_selection(self):
        result, payloads = self.run_helper('resolve_vcs_connection && create_ws github-org terraform/github',
            app=[{"id": "ghain-test", "attributes": {"name": "acme"}}],
            oauth=[{"attributes": {"service-provider": "github"},
                    "relationships": {"oauth-tokens": {"data": [{"id": "ot-test"}]}}}])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payloads, [])

    def test_multiple_apps_do_not_silently_select_oauth(self):
        result, _ = self.run_helper('resolve_vcs_connection',
            app=[{"id": key, "attributes": {"name": "acme"}}
                 for key in ("ghain-one", "ghain-two")],
            oauth=[{"attributes": {"service-provider": "github"},
                    "relationships": {"oauth-tokens": {"data": [{"id": "ot-test"}]}}}])
        self.assertNotEqual(result.returncode, 0)

    def test_explicit_app_must_match_repo_owner(self):
        result, _ = self.run_helper('resolve_vcs_connection',
            app=[{"id": "ghain-test", "attributes": {"name": "other"}}],
            overrides={"GITHUB_APP_INSTALLATION_ID": "ghain-test"})
        self.assertNotEqual(result.returncode, 0)

    def test_explicit_app_is_verified_and_used(self):
        result, payloads = self.run_helper(
            'resolve_vcs_connection && create_ws github-org terraform/github',
            app=[{"id": "ghain-test", "attributes": {"name": "ACME"}}],
            overrides={"GITHUB_APP_INSTALLATION_ID": "ghain-test"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payloads[0]["payload"]["data"]["attributes"]["vcs-repo"]
                         ["github-app-installation-id"], "ghain-test")

    def test_existing_app_connection_is_reused_for_new_leaf(self):
        result, payloads = self.run_helper(
            'resolve_vcs_connection && create_ws gcp terraform/gcp',
            overrides={"HAS_WORKSPACE": "yes"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payloads[0]["payload"]["data"]["attributes"]["vcs-repo"]
                         ["github-app-installation-id"], "ghain-existing")

    def test_creation_without_resolution_sends_no_payload(self):
        result, payloads = self.run_helper('create_ws github-org terraform/github')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payloads, [])

    def test_app_discovery_reads_later_pages(self):
        result, payloads = self.run_helper(
            'resolve_vcs_connection && create_ws github-org terraform/github',
            app_pages={
                "1": {"data": [{"id": "ghain-other", "attributes": {"name": "other"}}],
                      "meta": {"pagination": {"total-pages": 2}}},
                "2": {"data": [{"id": "ghain-later", "attributes": {"name": "acme"}}]},
            })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payloads[0]["payload"]["data"]["attributes"]["vcs-repo"]
                         ["github-app-installation-id"], "ghain-later")

    def test_patch_preserves_oauth_with_app_override(self):
        result, payloads = self.run_helper(
            'set_workspace_config github-org terraform/github',
            existing={"identifier": "acme/infra", "oauth-token-id": "ot-existing"},
            overrides={"GITHUB_APP_INSTALLATION_ID": "ghain-other", "HAS_WORKSPACE": "yes"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payloads[0]["payload"]["data"]["attributes"]["vcs-repo"],
                         {"identifier": "acme/infra", "branch": "main"})

    def test_oauth_only_user_without_app_authorization_can_bootstrap(self):
        for code in ("401", "403"):
            with self.subTest(code=code):
                result, payloads = self.run_helper(
                    'resolve_vcs_connection && create_ws github-org terraform/github',
                    oauth=[{"attributes": {"service-provider": "github"},
                            "relationships": {"oauth-tokens": {"data": [{"id": "ot-test"}]}}}],
                    overrides={"APP_STATUS": code})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payloads[0]["payload"]["data"]["attributes"]["vcs-repo"]
                                 ["oauth-token-id"], "ot-test")

    def test_app_network_failure_does_not_silently_select_oauth(self):
        result, payloads = self.run_helper(
            'resolve_vcs_connection && create_ws github-org terraform/github',
            oauth=[{"attributes": {"service-provider": "github"},
                    "relationships": {"oauth-tokens": {"data": [{"id": "ot-test"}]}}}],
            overrides={"APP_TRANSPORT_FAILS": "yes"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payloads, [])

    def test_app_denial_without_oauth_refuses_creation(self):
        result, payloads = self.run_helper(
            'resolve_vcs_connection && create_ws github-org terraform/github',
            overrides={"APP_STATUS": "403"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payloads, [])

    def test_patch_preserves_app_with_oauth_override(self):
        result, payloads = self.run_helper(
            'set_workspace_config github-org terraform/github',
            overrides={"OAUTH_TOKEN_ID": "ot-other", "HAS_WORKSPACE": "yes"})
        self.assertEqual(result.returncode, 0, result.stderr)
        vcs = payloads[0]["payload"]["data"]["attributes"]["vcs-repo"]
        self.assertEqual(vcs, {"identifier": "acme/infra", "branch": "main"})

    def test_numeric_github_id_is_rejected(self):
        result, payloads = self.run_helper('resolve_vcs_connection',
            overrides={"GITHUB_APP_INSTALLATION_ID": "12345"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payloads, [])

    def test_two_explicit_mechanisms_are_rejected(self):
        result, _ = self.run_helper('resolve_vcs_connection',
            overrides={"OAUTH_TOKEN_ID": "ot-test", "GITHUB_APP_INSTALLATION_ID": "ghain-test"})
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
