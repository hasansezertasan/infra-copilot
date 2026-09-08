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
# Real HCP returns the whole permissions block; the check requires can-update too,
# because settings include auto-apply and so are an elevation path.
PLAN_ONLY = {"can-queue-run": True, "can-queue-apply": False, "can-update": False}
CAN_APPLY = {"can-queue-run": True, "can-queue-apply": True, "can-update": False}
READ_ONLY = {"can-queue-run": False, "can-queue-apply": False, "can-update": False}
CAN_UPDATE = {"can-queue-run": True, "can-queue-apply": False, "can-update": True}

# Workspace name to working-directory, as hcp.md's create_ws sets it. `github-org`
# is the reason the check compares directories rather than names.
DIRECTORIES = {"cloudflare": "terraform/cloudflare", "github-org": "terraform/github"}
DEFAULT_LEAVES = ("terraform/cloudflare", "terraform/github")
#: Directory to the workspace name its `cloud` block targets -- what Terraform
#: actually addresses, and what the inventory compares against.
LEAF_WORKSPACE = {value: key for key, value in DIRECTORIES.items()}


@unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
class HcpApplyScopeTests(unittest.TestCase):
    def run_check(
        self,
        *,
        workspaces: list[tuple[str, dict[str, object] | None]] | None = None,
        leaves: list[str] | None = None,
        auto_apply: tuple[str, ...] = (),
        repo: str = "acme/infra",
        foreign: tuple[str, ...] = (),
        leaf_names: dict[str, str] | None = None,
        shift_on_recheck: bool = False,
        pagination: object = 1,
        fail_after_page: int | None = None,
        empty_after_page: int | None = None,
        body: str | None = None,
        env: dict[str, str] | None = None,
        curl_fails: bool = False,
        credential: str | None = TOKEN,
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
                    attributes: dict[str, object] = {
                        "name": name,
                        # Real workspaces carry these; the check compares the
                        # directory against the repo's terraform/<leaf>/ dirs and
                        # correlates the VCS identifier with $REPO.
                        "working-directory": DIRECTORIES.get(name, f"terraform/{name}"),
                        "vcs-repo": {
                            "identifier": "acme/elsewhere" if name in foreign else repo
                        },
                        "auto-apply": name in auto_apply,
                    }
                    if permissions is not None:
                        attributes["permissions"] = permissions
                    data.append({"id": f"ws-{name}", "attributes": attributes})
                body = json.dumps(
                    {"data": data, "meta": {"pagination": {"total-pages": pagination}}}
                )

            # The check runs with the consuming repo as its working directory, and
            # reads each leaf's `cloud` block for the workspace name it targets.
            for leaf in leaves if leaves is not None else DEFAULT_LEAVES:
                path = Path(directory) / leaf
                path.mkdir(parents=True)
                if leaf in (leaf_names or {}) or leaf in LEAF_WORKSPACE:
                    name = (leaf_names or {}).get(leaf) or LEAF_WORKSPACE[leaf]
                    (path / "versions.tf").write_text(
                        "terraform {\n  cloud {\n"
                        '    organization = "acme"\n'
                        f'    workspaces {{ name = "{name}" }}\n'
                        "  }\n}\n",
                        encoding="utf-8",
                    )

            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            # One readable stub: work out the page, then choose a body. Earlier
            # versions inlined the page arithmetic into nested `for`/`case` one
            # liners and got it wrong twice -- once reading "-sf" as the page
            # number, once failing to write the empty-page body at all.
            empty_body = '{"data":[],"meta":{"pagination":{"total-pages":9}}}'
            stub = [
                "#!/bin/sh",
                "exit 22" if curl_fails else "",
                'out=""; page=1; prev=""',
                'for a in "$@"; do',
                '  case "$prev" in -o) out="$a" ;; esac',
                '  case "$a" in',
                "    *page%5Bnumber%5D=*)",
                "      page=${a##*page%5Bnumber%5D=}",
                "      page=${page%%&*}",
                "      ;;",
                # Any URL this stub does not recognise is a bug in the test, not
                # a pass: an earlier harness in this repo silently stopped
                # matching and the tests kept passing.
                '    http*) case "$a" in *organizations/*/workspaces*) : ;; *) echo "unstubbed URL: $a" >&2; exit 99 ;; esac ;;',
                "  esac",
                '  prev="$a"',
                "done",
                f'if [ "$page" -gt {fail_after_page} ]; then exit 22; fi'
                if fail_after_page is not None
                else "",
                f'if [ "$page" -gt {empty_after_page} ]; then body={empty_body!r}; else body={body!r}; fi'
                if empty_after_page is not None
                else f"body={body!r}",
                # Count calls so the re-list can return a different id set, which
                # is what a workspace deleted mid-scan looks like.
                (
                    'n=$(cat "$TMPCOUNT" 2>/dev/null || echo 0); n=$((n + 1)); '
                    'printf "%s" "$n" > "$TMPCOUNT"\n'
                    f'if [ "$n" -gt {"1" if True else ""} ] && [ "$page" = 1 ]; then '
                    'body=$(printf "%s" "$body" | sed \'s/"ws-/"shifted-/\'); fi'
                )
                if shift_on_recheck
                else "",
                'if [ -n "$out" ]; then printf \'%s\' "$body" > "$out"; else printf \'%s\' "$body"; fi',
            ]
            curl = bin_dir / "curl"
            curl.write_text("\n".join(stub) + "\n", encoding="utf-8")
            curl.chmod(0o755)

            environment = dict(os.environ)
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            environment["TMPCOUNT"] = str(Path(directory) / "calls")
            environment.update(
                {
                    "HOME": str(home),
                    "ORG": "acme",
                    "REPO": repo,
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
        result = self.run_check(
            workspaces=[("cloudflare", READ_ONLY)], leaves=["terraform/cloudflare"]
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("OVER-RESTRICTED", result.stderr)
        self.assertNotIn("UNPROTECTED", result.stderr)

    def test_another_repositorys_read_only_workspace_is_not_over_restricted(self) -> None:
        """Plan is needed only where this repo runs.

        Demanding it on a workspace the team can merely read elsewhere would
        tell the operator to widen access to that workspace's plans, state and
        variables for nothing.
        """
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY), ("theirs", READ_ONLY)],
            leaves=["terraform/cloudflare"],
            foreign=("theirs",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_another_repositorys_appliable_workspace_is_still_unprotected(self) -> None:
        """The security assertion stays global: it must not apply anything."""
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY), ("theirs", CAN_APPLY)],
            leaves=["terraform/cloudflare"],
            foreign=("theirs",),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("UNPROTECTED", result.stderr)
        self.assertIn("theirs", result.stderr)

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
        result = self.run_check(
            workspaces=[("cloudflare", None)], leaves=["terraform/cloudflare"]
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("CANNOT VERIFY", result.stderr)

    def test_a_non_boolean_permission_cannot_be_verified(self) -> None:
        """`can-queue-apply: 0` is not `false`; it is unexpected evidence."""
        result = self.run_check(
            workspaces=[("cloudflare", {"can-queue-run": True, "can-queue-apply": 0})],
            leaves=["terraform/cloudflare"],
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
        result = self.run_check(workspaces=[], leaves=[])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no workspaces", result.stderr)

    def test_missing_configuration_cannot_be_verified(self) -> None:
        for variable in ("ORG", "hcp_api", "REPO"):
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
        for missing, present in (
            ("curl", "jq"),
            ("jq", "curl"),
            # grep detects the CLI-config credentials block; absent, the script
            # would exit 127 rather than the tri-state 2 the contract requires.
            ("grep", "curl"),
        ):
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory() as directory:
                    bin_dir = Path(directory)
                    for name in {present, "curl", "jq"} - {missing}:
                        stub = bin_dir / name
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
            ],
            leaves=[*DEFAULT_LEAVES, "terraform/gcp"],
            leaf_names={"terraform/gcp": "gcp"},
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("gcp", result.stderr)

    def test_a_managed_leaf_with_no_visible_workspace_cannot_be_verified(self) -> None:
        """The gap the visible set cannot show.

        Omit the Plan grant on one workspace and it vanishes from the list, so
        every visible entry is correct and the check would read green. The repo's
        own terraform/<leaf>/ directories are the independent inventory.
        """
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY)],
            leaves=["terraform/cloudflare", "terraform/github"],
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("terraform/github", result.stderr)
        self.assertIn("lacks the Plan grant", result.stderr)

    def test_a_string_permission_cannot_be_verified(self) -> None:
        """The JSON string "false" is not the boolean false.

        `tostring` rendered both as the same shell text, so a malformed response
        passed the exact-boolean check.
        """
        result = self.run_check(
            workspaces=[
                ("cloudflare", {"can-queue-run": "true", "can-queue-apply": "false"})
            ],
            leaves=["terraform/cloudflare"],
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("not a boolean", result.stderr)

    def test_no_terraform_directory_skips_the_inventory_comparison(self) -> None:
        """A repo before phase 1 has no leaves; that must not be a verdict."""
        result = self.run_check(workspaces=[("cloudflare", PLAN_ONLY)], leaves=[])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_auto_apply_is_a_verdict_even_when_apply_is_denied(self) -> None:
        """can-queue-apply false does not help if the workspace applies itself.

        A plan-capable credential queues a non-speculative run and HCP applies the
        successful plan. Phase 1 checks this for the bootstrap pair only, so
        workspaces `add` creates later are covered here or nowhere.
        """
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY)],
            leaves=["terraform/cloudflare"],
            auto_apply=("cloudflare",),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("auto-apply enabled", result.stderr)

    def test_settings_access_is_a_verdict(self) -> None:
        """Settings include auto-apply, so the boundary would be self-removable."""
        result = self.run_check(
            workspaces=[("cloudflare", CAN_UPDATE)], leaves=["terraform/cloudflare"]
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("self-removable", result.stderr)

    def test_a_verdict_outranks_later_unreadable_evidence(self) -> None:
        """status renders exit 2 as "nothing to fix", which would bury this.

        One workspace definitely allows an apply; a second cannot be read. The
        exit code must stay 1 and the output must carry both.
        """
        result = self.run_check(
            workspaces=[("cloudflare", CAN_APPLY), ("github-org", None)],
            leaves=list(DEFAULT_LEAVES),
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("UNPROTECTED", result.stderr)
        self.assertIn("could not be read", result.stderr)

    def test_unreadable_pagination_fails_closed(self) -> None:
        """Assuming one page would silently truncate the inventory."""
        result = self.run_check(pagination="lots")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("total-pages", result.stderr)

    def test_a_fractional_page_count_fails_closed(self) -> None:
        """`numbers` accepts 2.5, which POSIX `test -lt` rejects as an operand.

        The comparison errored and `|| break` read that as "no more pages", so
        the inventory truncated silently.
        """
        result = self.run_check(pagination=2.5)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("positive-integer", result.stderr)

    def test_an_integral_float_page_count_is_usable(self) -> None:
        """2.0 is two pages, but this jq renders it "2.0", which breaks `test`.

        It must be accepted and handed to the shell through floor, not rejected
        and not passed through verbatim.
        """
        result = self.run_check(pagination=2.0, fail_after_page=1)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("page 2", result.stderr)

    def test_a_zero_page_count_fails_closed(self) -> None:
        result = self.run_check(pagination=0)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("positive-integer", result.stderr)

    def test_a_verdict_survives_unreadable_pagination(self) -> None:
        """The inversion, on the page-level path this time.

        An earlier fix converted the per-workspace paths to accumulate and left
        every page-level path exiting straight out, so a proven apply capability
        was still discarded by unrelated pagination trouble.
        """
        result = self.run_check(
            workspaces=[("cloudflare", CAN_APPLY)],
            leaves=["terraform/cloudflare"],
            pagination="lots",
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("UNPROTECTED", result.stderr)
        self.assertIn("could not be read", result.stderr)

    def test_a_verdict_survives_an_unreadable_page(self) -> None:
        """Same for a page that cannot be fetched at all."""
        result = self.run_check(
            workspaces=[("cloudflare", CAN_APPLY)],
            leaves=["terraform/cloudflare"],
            pagination=3,
            fail_after_page=1,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("UNPROTECTED", result.stderr)
        self.assertIn("page 2", result.stderr)

    def test_a_cli_config_credentials_declaration_cannot_be_verified(self) -> None:
        """Terraform's docs do not state which source wins, so refuse to guess.

        Every form must refuse, including ones a same-line hostname regex missed:
        HCL treats comments as whitespace, so `credentials /* x */ "host"` is
        valid and slipped past, leaving an apply-capable token unexamined.
        """
        for body, label in (
            ('credentials "app.terraform.io" {\n  token = "other"\n}\n', "plain"),
            ('credentials /* managed */ "app.terraform.io" {\n  token = "x"\n}\n', "inline comment"),
            ('credentials\n  "app.terraform.io" {\n  token = "x"\n}\n', "wrapped"),
        ):
            with self.subTest(form=label):
                with tempfile.TemporaryDirectory() as directory:
                    config = Path(directory) / "terraformrc"
                    config.write_text(body, encoding="utf-8")
                    result = self.run_check(env={"TF_CLI_CONFIG_FILE": str(config)})
                    self.assertEqual(result.returncode, 2, result.stdout)
                    self.assertIn("credentials declaration", result.stderr)

    def test_another_repositorys_workspaces_do_not_satisfy_the_inventory(self) -> None:
        """working-directory is not unique across an organization.

        Two repos bootstrapped by this plugin both have terraform/cloudflare, so a
        credential that can only see the other repo's workspaces must not pass.
        """
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY)],
            leaves=["terraform/cloudflare"],
            repo="acme/other-infra",
            env={"REPO": "acme/infra"},
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("terraform/cloudflare", result.stderr)
        self.assertIn("acme/infra", result.stderr)

    def test_an_unexpected_api_endpoint_is_refused_before_any_request(self) -> None:
        """$hcp_api comes from a repo-local file, so it is not trusted input.

        The refusal must happen before the credential is resolved or sent, so the
        stub curl exits 99 on any URL it does not recognise and would surface a
        request that slipped through.
        """
        for endpoint in (
            "http://app.terraform.io/api/v2",
            "https://evil.example/api/v2",
            "https://app.terraform.io/api/v2/",
        ):
            with self.subTest(endpoint=endpoint):
                result = self.run_check(env={"hcp_api": endpoint})
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("refusing to send", result.stderr)

    def test_an_unset_repo_cannot_be_verified(self) -> None:
        """The correlation must not disable itself when REPO is missing.

        Skipping it let another repository's workspaces -- same working directory,
        different repo -- satisfy this repo's inventory, which is the case the
        correlation exists for.
        """
        result = self.run_check(env={"REPO": ""})
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("REPO", result.stderr)

    def test_an_empty_later_page_is_uncertain(self) -> None:
        """The set can shift between requests.

        Deleting an early workspace moves an entry back across the page
        boundary, so an empty later page means something may never have been
        inspected. Breaking silently would exit 0 on a partial scan.
        """
        result = self.run_check(pagination=3, empty_after_page=1)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("changed mid-scan", result.stderr)

    def test_an_empty_first_page_is_not_a_mid_scan_change(self) -> None:
        """No workspaces at all is its own message, not a shifting list."""
        result = self.run_check(workspaces=[], leaves=[])
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no workspaces", result.stderr)
        self.assertNotIn("changed mid-scan", result.stderr)

    def test_a_similar_workspace_does_not_satisfy_the_inventory(self) -> None:
        """Terraform targets a workspace by name, not by working directory.

        A stale `cloudflare-copy` connected to the same repo with the same
        working directory satisfied a repo-plus-directory match, while the plan
        the leaf actually runs could not be queued.
        """
        result = self.run_check(
            workspaces=[("cloudflare-copy", PLAN_ONLY)],
            leaves=["terraform/cloudflare"],
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("'cloudflare'", result.stderr)
        self.assertIn("terraform/cloudflare targets", result.stderr)

    def test_a_leaf_with_no_cloud_block_cannot_be_verified(self) -> None:
        """Without a declared name there is nothing to compare against."""
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY)],
            leaves=["terraform/cloudflare", "terraform/mystery"],
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("declares no cloud workspace name", result.stderr)

    def test_auto_apply_on_an_unqueueable_workspace_is_not_a_verdict(self) -> None:
        """Auto-apply this credential cannot trigger is not its problem.

        Reporting it sent the operator to change an unrelated workspace's policy.
        """
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY), ("theirs", READ_ONLY)],
            leaves=["terraform/cloudflare"],
            foreign=("theirs",),
            auto_apply=("theirs",),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_list_that_changes_mid_scan_is_uncertain(self) -> None:
        """A deleted workspace shifts later entries onto pages already read.

        The skipped entry is never inspected and the final page usually stays
        non-empty, so emptiness cannot be the signal. The id set is re-listed and
        compared instead.
        """
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY)],
            leaves=["terraform/cloudflare"],
            pagination=2,
            shift_on_recheck=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("changed while it was being read", result.stderr)

    def test_a_stable_list_over_two_pages_passes(self) -> None:
        """The re-list must not report a change when nothing changed."""
        result = self.run_check(
            workspaces=[("cloudflare", PLAN_ONLY)],
            leaves=["terraform/cloudflare"],
            pagination=2,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

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
