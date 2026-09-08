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
                "new-provider-workspace",
                "new-provider-plan-access",
                "new-provider-credentials",
                "new-provider-plan",
            ],
        )
        for name, step in self.steps.items():
            with self.subTest(step=name):
                self.assertIn("    phase: 6\n", step)
                self.assertIn("    check:", step)

    def test_inventory_is_a_manifest_check_not_router_prose(self) -> None:
        inventory = self.steps["new-provider-inventory"]
        self.assertIn("ADDITIONAL_PROVIDER_NAMES", inventory)
        self.assertIn("for leaf in terraform/*/", inventory)
        self.assertIn("cloudflare|github", inventory)
        self.assertIn("index($name) != null", inventory)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "terraform/gcp").mkdir(parents=True)
            untracked = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={**os.environ, "ADDITIONAL_PROVIDER_NAMES": "[]"},
                capture_output=True,
                text=True,
            )
            tracked = subprocess.run(
                ["/bin/sh", "-c", literal_check(inventory)],
                cwd=root,
                env={**os.environ, "ADDITIONAL_PROVIDER_NAMES": '["gcp"]'},
                capture_output=True,
                text=True,
            )
        self.assertEqual(untracked.returncode, 1)
        self.assertEqual(tracked.returncode, 0, tracked.stderr)

    def test_decision_is_not_inferred_from_the_leaf_directory(self) -> None:
        decision = self.steps["new-provider-decision"]
        self.assertIn(".infra-copilot/decisions.md", decision)
        self.assertIn("terraform/README.md", decision)
        self.assertIn("locked", decision)
        self.assertNotIn('check: "test -d terraform/gcp"', decision)

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
            '"trigger-patterns"',
            '"vcs-repo"',
            '".infra-copilot/config.md"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, workspace)
        self.assertIn('== ([$dir + "/**", ".infra-copilot/config.md"] | sort)', workspace)
        self.assertIn('($a["queue-all-runs"] == false)', workspace)

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

    def test_plan_access_reuses_repository_derived_inventory(self) -> None:
        access = self.steps["new-provider-plan-access"]
        self.assertIn("hcp-apply-scope.sh", access)
        self.assertIn("    tri_state: true", access)
        self.assertIn("`Plan`", access)
        self.assertIn("`Write`", access)

    def test_credentials_check_matches_declared_metadata(self) -> None:
        credentials = self.steps["new-provider-credentials"]
        self.assertIn("/vars", credentials)
        self.assertIn("NEW_PROVIDER_CREDENTIALS", credentials)
        for attribute in (".key", ".category", ".sensitive"):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, credentials)
        self.assertNotIn(".attributes.value", credentials)

    def test_first_plan_targets_the_parameterized_leaf(self) -> None:
        plan = self.steps["new-provider-plan"]
        self.assertIn('terraform/$NEW_PROVIDER', plan)
        self.assertIn("terraform init -input=false", plan)
        self.assertIn("terraform plan -input=false", plan)

    def test_router_and_status_use_the_durable_inventory(self) -> None:
        for path in (CONFIG, STATUS):
            with self.subTest(path=path.name):
                self.assertIn("additional_providers", path.read_text(encoding="utf-8"))
        add = ADD.read_text(encoding="utf-8")
        self.assertNotIn("None of steps 2–5 have `steps.yaml` entries", add)
        self.assertIn("shared resume protocol", add)
        self.assertNotIn("Workspace creation remains", add)
        status = STATUS.read_text(encoding="utf-8")
        self.assertRegex(status, r"every Phase 6 step except\s+`new-provider-plan`")


if __name__ == "__main__":
    unittest.main()
