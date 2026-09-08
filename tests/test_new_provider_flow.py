"""Protect the resumable, provider-neutral Phase 6 contract."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STEPS = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/steps.yaml"
LEAF_CLOUD = (
    REPO_ROOT
    / ".ai-rulez/skills/infra-copilot/references/checks/leaf-cloud.sh"
)
ADD = REPO_ROOT / ".ai-rulez/skills/add/SKILL.md"
CONFIG = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/config.md"
HCP = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/hcp.md"
HCP_CURRENT_PLAN = (
    REPO_ROOT
    / ".ai-rulez/skills/infra-copilot/references/checks/hcp-current-plan.sh"
)
STATUS = REPO_ROOT / ".ai-rulez/skills/status/SKILL.md"


def phase_six_steps() -> dict[str, str]:
    text = STEPS.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^  - id: (new-provider-[^\n]+)\n", text, re.MULTILINE))
    return {
        match.group(1): text[match.start() : matches[index + 1].start()]
        if index + 1 < len(matches)
        else text[match.start() :]
        for index, match in enumerate(matches)
    }


def literal_check(step: str) -> str:
    match = re.search(r"^    check: \|\n(?P<body>(?:      .*\n)+)", step, re.MULTILINE)
    if match is None:
        raise AssertionError("step has no literal check")
    return "\n".join(
        line.removeprefix("      ") for line in match.group("body").splitlines()
    )


class NewProviderFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.steps = phase_six_steps()

    def test_phase_six_tracks_every_resumable_state_in_order(self) -> None:
        self.assertEqual(
            list(self.steps),
            [
                "new-provider-inventory",
                "new-provider-decision",
                "new-provider-leaf",
                "new-provider-toolchain",
                "new-provider-workspace-bootstrap",
                "new-provider-workspace",
                "new-provider-plan-access",
                "new-provider-fork-safety",
                "new-provider-credentials",
                "new-provider-plan",
            ],
        )
        for name, step in self.steps.items():
            with self.subTest(step=name):
                self.assertIn("    phase: 6\n", step)
                self.assertIn("    check:", step)

    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_inventory_is_a_manifest_check_not_router_prose(self) -> None:
        inventory = self.steps["new-provider-inventory"]
        self.assertIn("ADDITIONAL_PROVIDER_NAMES", inventory)
        self.assertIn("for leaf in terraform/*/", inventory)
        self.assertIn("cloudflare|github", inventory)
        self.assertIn("index($name) != null", inventory)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "terraform/gcp").mkdir(parents=True)
            (root / "terraform/gcp/versions.tf").write_text(
                'terraform { cloud { workspaces { name = "gcp" } } }\n',
                encoding="utf-8",
            )
            common_env = {
                **os.environ,
                "ADDITIONAL_PROVIDER_WORKSPACES": '["gcp"]',
                "INFRA_COPILOT_REFERENCES": str(LEAF_CLOUD.parent.parent),
            }
            untracked = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={**common_env, "ADDITIONAL_PROVIDER_NAMES": "[]"},
                capture_output=True,
                text=True,
            )
            tracked = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={**common_env, "ADDITIONAL_PROVIDER_NAMES": '["gcp"]'},
                capture_output=True,
                text=True,
            )
        self.assertEqual(untracked.returncode, 1)
        self.assertEqual(tracked.returncode, 0, tracked.stderr)

    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_inventory_skips_modules_and_rejects_workspace_collisions(self) -> None:
        inventory = self.steps["new-provider-inventory"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "terraform/modules/network").mkdir(parents=True)
            (root / "terraform/modules/network/main.tf").write_text(
                'variable "name" {}\n', encoding="utf-8"
            )
            base_env = {
                **os.environ,
                "INFRA_COPILOT_REFERENCES": str(LEAF_CLOUD.parent.parent),
            }
            module_only = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={
                    **base_env,
                    "ADDITIONAL_PROVIDER_NAMES": "[]",
                    "ADDITIONAL_PROVIDER_WORKSPACES": "[]",
                },
                capture_output=True,
                text=True,
            )
            collision = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={
                    **base_env,
                    "ADDITIONAL_PROVIDER_NAMES": '["gcp"]',
                    "ADDITIONAL_PROVIDER_WORKSPACES": '["cloudflare"]',
                },
                capture_output=True,
                text=True,
            )
        self.assertEqual(module_only.returncode, 0, module_only.stderr)
        self.assertNotEqual(collision.returncode, 0)

    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_inventory_rejects_reserved_bootstrap_leaf_names(self) -> None:
        inventory = self.steps["new-provider-inventory"]
        env = {
            **os.environ,
            "ADDITIONAL_PROVIDER_WORKSPACES": '["extra"]',
            "INFRA_COPILOT_REFERENCES": str(LEAF_CLOUD.parent.parent),
        }
        for name in ("cloudflare", "github"):
            result = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                env={**env, "ADDITIONAL_PROVIDER_NAMES": f'["{name}"]'},
                capture_output=True,
                text=True,
            )
            with self.subTest(name=name):
                self.assertNotEqual(result.returncode, 0)

    def test_decision_is_not_inferred_from_the_leaf_directory(self) -> None:
        decision = self.steps["new-provider-decision"]
        self.assertIn(".infra-copilot/decisions.md", decision)
        self.assertIn("terraform/README.md", decision)
        self.assertIn("locked", decision)
        self.assertIn('clean($2) == expected', decision)
        self.assertIn('clean($3) == "adopt"', decision)
        self.assertNotIn('check: "test -d terraform/gcp"', decision)
        self.assertIn("git diff --quiet HEAD", decision)
        self.assertIn("git diff --cached --quiet HEAD", decision)
        self.assertIn(
            'grep -Fq "terraform/$NEW_PROVIDER" terraform/README.md || exit 1',
            decision,
        )

    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_decision_requires_the_standardized_affirmative_row(self) -> None:
        decision = self.steps["new-provider-decision"]
        env = {
            **os.environ,
            "NEW_PROVIDER": "gcp",
            "NEW_PROVIDER_WORKSPACE": "gcp",
            "NEW_PROVIDER_MISE_TOOLS": '["gcloud"]',
            "NEW_PROVIDER_FORK_PLANS_DISABLED": "false",
            "NEW_PROVIDER_FORK_PLANS_WORKSPACE_ID": "",
            "NEW_PROVIDER_CREDENTIALS": (
                '[{"key":"TFC_GCP_PROVIDER_AUTH","category":"env",'
                '"sensitive":false}]'
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".infra-copilot").mkdir()
            (root / "terraform").mkdir()
            (root / "terraform/README.md").write_text(
                "terraform/gcp\n", encoding="utf-8"
            )
            (root / ".infra-copilot/config.md").write_text(
                "additional_providers:\n  - name: gcp\n", encoding="utf-8"
            )
            decisions = root / ".infra-copilot/decisions.md"
            decisions.write_text(
                "| Decision | Choice | Status |\n"
                "| Use AWS, not GCP | aws | locked |\n",
                encoding="utf-8",
            )
            negative = subprocess.run(
                ["/bin/sh", "-c", literal_check(decision)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )
            decisions.write_text(
                "| Decision | Choice | Status |\n"
                "| Provider: gcp | adopt | locked |\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                 "add", ".infra-copilot/config.md", ".infra-copilot/decisions.md",
                 "terraform/README.md"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                 "commit", "-qm", "test fixture"],
                cwd=root,
                check=True,
            )
            positive = subprocess.run(
                ["/bin/sh", "-c", literal_check(decision)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(negative.returncode, 0)
        self.assertEqual(positive.returncode, 0, positive.stderr)

    def test_explicit_adoption_bootstraps_an_empty_inventory(self) -> None:
        protocol = (
            REPO_ROOT
            / ".ai-rulez/skills/infra-copilot/references/protocol.md"
        ).read_text(encoding="utf-8")
        self.assertIn("new-provider-decision` once in bootstrap mode", protocol)
        self.assertIn("must never\ndiscard an explicit adoption request", protocol)

    def test_workspace_check_asserts_the_complete_safety_contract(self) -> None:
        workspace = self.steps["new-provider-workspace"]
        for marker in (
            '"working-directory"',
            '"execution-mode"',
            '"terraform-version"',
            '"auto-apply"',
            '"speculative-enabled"',
            '"file-triggers-enabled"',
            '"queue-all-runs"',
            '"global-remote-state"',
            '"trigger-patterns"',
            '"vcs-repo"',
            '".infra-copilot/config.md"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, workspace)
        self.assertIn('== ([$dir + "/**", ".infra-copilot/config.md"] | sort)', workspace)
        self.assertIn('($a["queue-all-runs"] == false)', workspace)
        self.assertIn('test "$hcp_api" = "https://app.terraform.io/api/v2"', workspace)
        self.assertIn("    tri_state: true", workspace)
        self.assertIn("*) exit 2", workspace)

        helper = HCP.read_text(encoding="utf-8").split(
            "  set_workspace_config () {", 1
        )[1].split("\n  }", 1)[0]
        for marker in (
            '"working-directory":$dir',
            '"execution-mode":"remote"',
            '"auto-apply":false',
            '"speculative-enabled":true',
            '"queue-all-runs":false',
            '"vcs-repo":{identifier:$repo',
            'branch:"main"',
        ):
            with self.subTest(reconciliation=marker):
                self.assertIn(marker, helper)
        self.assertIn('[ "$existing_repo" = "$REPO" ]', helper)
        self.assertIn("refusing to reconfigure workspace owned by", helper)
        self.assertIn("CONFIRM_WORKSPACE_ID", helper)

    @unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
    def test_leaf_check_reads_name_from_the_cloud_workspace_block(self) -> None:
        leaf = self.steps["new-provider-leaf"]
        self.assertIn("checks/leaf-cloud.sh", leaf)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "versions.tf").write_text(
                'resource "example" "x" { name = "gcp" }\n'
                'terraform { cloud { organization = "acme" } }\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                ["/bin/sh", str(LEAF_CLOUD), str(root), "workspace"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_leaf_check_validates_the_complete_cloud_target(self) -> None:
        leaf = self.steps["new-provider-leaf"]
        self.assertIn('grep -Fx "organization=$ORG"', leaf)
        self.assertIn("app.terraform.io", leaf)
        self.assertIn("workspaces.name=$NEW_PROVIDER_WORKSPACE", leaf)

    @unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
    def test_leaf_parser_keeps_reading_cloud_after_workspaces_closes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "versions.tf").write_text(
                """terraform {
  cloud {
    workspaces {
      name = "gcp"
    }
    hostname = "app.terraform.io"
    organization = "acme"
  }
}
""",
                encoding="utf-8",
            )
            values = {
                key: subprocess.run(
                    ["/bin/sh", str(LEAF_CLOUD), str(root), key],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                for key in ("workspace", "hostname", "organization")
            }
        self.assertEqual(
            values,
            {
                "workspace": "gcp",
                "hostname": "app.terraform.io",
                "organization": "acme",
            },
        )

    @unittest.skipUnless(os.name == "posix", "the check is a POSIX shell script")
    def test_leaf_parser_ignores_nested_host_and_organization_tags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "versions.tf").write_text(
                """terraform {
  cloud {
    workspaces {
      tags = {
        hostname = "attacker.example"
        organization = "wrong-org"
      }
    }
    hostname = "app.terraform.io"
    organization = "acme"
  }
}
""",
                encoding="utf-8",
            )
            values = {
                key: subprocess.run(
                    ["/bin/sh", str(LEAF_CLOUD), str(root), key],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                for key in ("hostname", "organization")
            }
            all_settings = subprocess.run(
                ["/bin/sh", str(LEAF_CLOUD), str(root), "all"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        self.assertEqual(
            values,
            {"hostname": "app.terraform.io", "organization": "acme"},
        )
        self.assertIn("hostname=app.terraform.io", all_settings)
        self.assertIn("organization=acme", all_settings)
        self.assertNotIn("attacker.example", all_settings)
        self.assertNotIn("wrong-org", all_settings)

    def test_toolchain_retrusts_after_the_leaf_before_provider_commands(self) -> None:
        leaf = self.steps["new-provider-leaf"]
        toolchain = self.steps["new-provider-toolchain"]
        self.assertIn("do not execute the CLI", leaf)
        self.assertIn("    actor: HUMAN", toolchain)
        self.assertIn("commit both reviewed files", toolchain)
        self.assertIn("mise trust mise.toml", toolchain)
        self.assertIn("MISE_LOCKED=1", toolchain)
        self.assertIn("NEW_PROVIDER_MISE_TOOLS", toolchain)
        self.assertIn("--dry-run-code", toolchain)
        self.assertIn("complete preflight", toolchain)

    def test_leaf_must_be_tracked_and_clean(self) -> None:
        leaf = self.steps["new-provider-leaf"]
        self.assertIn("git ls-files --error-unmatch", leaf)
        self.assertIn(".terraform.lock.hcl", leaf)
        self.assertIn("terraform init -backend=false", leaf)
        self.assertIn("git --no-optional-locks status --porcelain", leaf)

    def test_workspace_bootstrap_makes_the_creation_handoff_reachable(self) -> None:
        bootstrap = self.steps["new-provider-workspace-bootstrap"]
        self.assertIn("    tri_state: true", bootstrap)
        self.assertIn("404) exit 1", bootstrap)
        self.assertIn("*) exit 2", bootstrap)
        self.assertIn("create_ws", bootstrap)
        self.assertIn("resolve_oauth_token_id", bootstrap)

    def test_plan_access_reuses_repository_derived_inventory(self) -> None:
        access = self.steps["new-provider-plan-access"]
        self.assertIn("hcp-apply-scope.sh", access)
        self.assertIn('HCP_SCOPE_WORKSPACE="$NEW_PROVIDER_WORKSPACE"', access)
        self.assertIn("    tri_state: true", access)
        self.assertIn("`Plan`", access)
        self.assertIn("`Write`", access)
        self.assertNotIn("create_ws", access)

    def test_fork_plan_safety_is_durable_and_precedes_credentials(self) -> None:
        safety = self.steps["new-provider-fork-safety"]
        self.assertIn("    actor: HUMAN", safety)
        self.assertIn("NEW_PROVIDER_FORK_PLANS_DISABLED", safety)
        self.assertIn("NEW_PROVIDER_FORK_PLANS_WORKSPACE_ID", safety)
        self.assertIn("Version Control", safety)
        self.assertIn("fork", safety.lower())
        self.assertIn("git diff --quiet HEAD -- .infra-copilot/config.md", safety)
        self.assertIn("actual_id", safety)

    def test_credentials_check_matches_declared_metadata(self) -> None:
        credentials = self.steps["new-provider-credentials"]
        self.assertIn("/vars", credentials)
        self.assertIn("NEW_PROVIDER_CREDENTIALS", credentials)
        for attribute in (".key", ".category", ".sensitive"):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, credentials)
        self.assertNotIn(".attributes.value", credentials)
        self.assertIn('test "$hcp_api" = "https://app.terraform.io/api/v2"', credentials)
        self.assertIn("    tri_state: true", credentials)
        self.assertIn("page%5Bnumber%5D=$page", credentials)
        self.assertIn('["next-page"]', credentials)

    def test_first_plan_targets_the_parameterized_leaf(self) -> None:
        plan = self.steps["new-provider-plan"]
        self.assertIn("hcp-current-plan.sh", plan)
        self.assertIn("configuration-version relationship", plan)
        self.assertIn("configured upstream", plan)
        self.assertIn("gh pr create --draft", plan)
        self.assertIn("    tri_state: true", plan)
        helper = HCP_CURRENT_PLAN.read_text(encoding="utf-8")
        self.assertIn('attributes["commit-sha"] as $sha', helper)
        self.assertIn('"plan-only":true', helper)
        self.assertIn('"configuration-version":{data:', helper)
        self.assertIn("json-output-redacted", helper)
        self.assertIn('index("delete")', helper)
        self.assertIn('index("create")', helper)
        self.assertIn(".format_version", helper)
        self.assertIn(".terraform_version", helper)
        self.assertIn("truncated=true", helper)
        self.assertIn("bounded 500-run scan", helper)
        self.assertIn("still in flight", helper)
        self.assertIn("planned_and_saved|applied", helper)
        self.assertIn("the run-list head changed during pagination", helper)
        self.assertIn('git diff --quiet "$sha" HEAD', helper)
        self.assertIn('[ "$status" = policy_soft_failed ]', helper)
        self.assertIn("POLICY INTERVENTION", helper)
        self.assertLess(helper.index("status=$("), helper.index('if [ "$mode" = queue ]'))
        self.assertNotIn('git log -1 --format=%H -- "terraform/$NEW_PROVIDER"', helper)
        self.assertIn("plan_only,plan_and_apply,save_plan&", helper)
        self.assertNotIn("refresh_only", helper)

    @unittest.skipUnless(os.name == "posix", "the parser is a POSIX shell script")
    def test_leaf_parser_reads_terraform_json_cloud_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            leaf = Path(directory)
            (leaf / "versions.tf.json").write_text(
                '{"terraform":{"cloud":{"hostname":"app.terraform.io",'
                '"organization":"acme","workspaces":{"name":"gcp"}}}}',
                encoding="utf-8",
            )
            result = subprocess.run(
                ["/bin/sh", str(LEAF_CLOUD), str(leaf), "all"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cloud=present", result.stdout)
        self.assertIn("hostname=app.terraform.io", result.stdout)
        self.assertIn("organization=acme", result.stdout)
        self.assertIn("workspaces.name=gcp", result.stdout)

    @unittest.skipUnless(os.name == "posix", "the parser is a POSIX shell script")
    def test_leaf_parser_does_not_invent_a_json_cloud_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            leaf = Path(directory)
            (leaf / "main.tf.json").write_text(
                '{"resource":{"example":{"fixture":{"name":"test"}}}}',
                encoding="utf-8",
            )
            result = subprocess.run(
                ["/bin/sh", str(LEAF_CLOUD), str(leaf), "all"],
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("cloud=present", result.stdout)

    def test_inventory_covers_actual_provider_tool_keys(self) -> None:
        inventory = self.steps["new-provider-inventory"]
        self.assertIn("ADDITIONAL_PROVIDER_MISE_TOOLS", inventory)
        self.assertIn("mise config get --file ./mise.toml tools", inventory)
        self.assertIn("github:cloudflare/cf-terraforming", inventory)
        self.assertIn("($actual - $declared | length) == 0", inventory)

    @unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
    def test_inventory_rejects_an_undeclared_provider_tool(self) -> None:
        inventory = self.steps["new-provider-inventory"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (root / "terraform").mkdir()
            (root / "mise.toml").write_text(
                '[tools]\nterraform = "1.14.0"\ngh = "2.80.0"\n'
                'jq = "1.8.1"\ngcloud = "551.0.0"\n',
                encoding="utf-8",
            )
            fake_mise = bin_dir / "mise"
            fake_mise.write_text(
                "#!/bin/sh\n"
                "echo 'terraform = \"1.14.0\"'\n"
                "echo 'gh = \"2.80.0\"'\n"
                "echo 'jq = \"1.8.1\"'\n"
                "if [ -z \"${OMIT_GCLOUD:-}\" ]; then "
                "echo 'gcloud = \"551.0.0\"'; fi\n",
                encoding="utf-8",
            )
            fake_mise.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "ADDITIONAL_PROVIDER_NAMES": "[]",
                "ADDITIONAL_PROVIDER_WORKSPACES": "[]",
                "INFRA_COPILOT_REFERENCES": str(LEAF_CLOUD.parent.parent),
            }
            omitted = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={**env, "ADDITIONAL_PROVIDER_MISE_TOOLS": "[]"},
                capture_output=True,
                text=True,
            )
            declared = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={**env, "ADDITIONAL_PROVIDER_MISE_TOOLS": '["gcloud"]'},
                capture_output=True,
                text=True,
            )
            before_scaffolding = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={
                    **env,
                    "OMIT_GCLOUD": "1",
                    "ADDITIONAL_PROVIDER_MISE_TOOLS": '["gcloud"]',
                },
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(omitted.returncode, 0)
        self.assertEqual(declared.returncode, 0, declared.stderr)
        self.assertEqual(before_scaffolding.returncode, 0, before_scaffolding.stderr)

    def test_provider_preflight_is_activated_by_the_reviewed_entry(self) -> None:
        manifest = STEPS.read_text(encoding="utf-8")
        gcloud = manifest.split("  - tool: gcloud\n", 1)[1].split(
            "  - tool: infra-copilot-references\n", 1
        )[0]
        self.assertIn("NEW_PROVIDER_MISE_TOOLS", gcloud)
        self.assertNotIn("test -d terraform/gcp", gcloud)

    def test_router_and_status_use_the_durable_inventory(self) -> None:
        for path in (CONFIG, STATUS):
            with self.subTest(path=path.name):
                self.assertIn("additional_providers", path.read_text(encoding="utf-8"))
        add = ADD.read_text(encoding="utf-8")
        self.assertNotIn("None of steps 2–5 have `steps.yaml` entries", add)
        self.assertIn("shared resume protocol", add)
        self.assertNotIn("Workspace creation remains", add)
        status = STATUS.read_text(encoding="utf-8")
        self.assertIn("every Phase 6 step", status)
        self.assertIn("Phase 6 plan contents and durable completion", status)
        self.assertIn("resource-count", status)
        self.assertIn("destroys are\n   zero", status)

    def test_legacy_config_defaults_only_a_missing_provider_list(self) -> None:
        config = CONFIG.read_text(encoding="utf-8")
        self.assertIn(
            "additional_providers` is absent (legacy config), default it to `[]`",
            config,
        )
        self.assertIn("reject it unless its value is an array", config)
        for marker in (
            "ADDITIONAL_PROVIDER_WORKSPACES",
            "NEW_PROVIDER_MISE_TOOLS",
            "NEW_PROVIDER_FORK_PLANS_DISABLED",
            "NEW_PROVIDER_FORK_PLANS_WORKSPACE_ID",
        ):
            self.assertIn(marker, config)

    def test_hcp_workspace_creation_selects_a_repository_specific_oauth_token(self) -> None:
        hcp = HCP.read_text(encoding="utf-8")
        self.assertNotIn('.data[0].relationships["oauth-tokens"]', hcp)
        self.assertIn('select(.identifier == $repo)', hcp)
        self.assertIn("resolve_oauth_token_id", hcp)
        self.assertIn("select(length == 1)", hcp)
        self.assertIn("export the intended OAUTH_TOKEN_ID", hcp)


if __name__ == "__main__":
    unittest.main()
