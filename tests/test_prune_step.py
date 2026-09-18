"""The phase-5 prune step, and the migrate-import check it un-inverts.

`migrate-import` used to require at least one `will be imported`, so it went red
exactly when the migration finished — and stayed red forever, because the
correct terminal state is a plan reading `No changes.` The prune step is what
makes that terminal state reachable: it reads red while one-shot `import {}` /
`moved {}` blocks are still committed.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STEPS = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/steps.yaml"


def step(step_id: str) -> str:
    text = STEPS.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^  - id: (\S+)\n", text, re.MULTILINE))
    for index, match in enumerate(matches):
        if match.group(1) == step_id:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return text[match.start() : end]
    raise AssertionError(f"{step_id} is not in the manifest")


def literal_check(body: str) -> str:
    match = re.search(r"^    check: \|\n(?P<body>(?:      .*\n|\n)+)", body, re.MULTILINE)
    if match is None:
        raise AssertionError("step has no literal check")
    return "\n".join(
        line.removeprefix("      ") for line in match.group("body").splitlines()
    )


@unittest.skipUnless(os.name == "posix", "manifest checks are POSIX shell")
class PruneStepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.check = literal_check(step("prune-spent-imports"))

    def _run(
        self,
        files: dict[str, str],
        *,
        commit: bool = True,
        cwd: str = ".",
        delete: tuple[str, ...] = (),
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            env = {
                **os.environ,
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_SYSTEM": "/dev/null",
                "HOME": str(root),
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.invalid",
            }
            subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True)
            if commit:
                subprocess.run(["git", "add", "-A"], cwd=root, env=env, check=True)
                subprocess.run(
                    ["git", "commit", "-qm", "init"], cwd=root, env=env, check=True
                )
            for name in delete:
                (root / name).unlink()
            return subprocess.run(
                ["/bin/sh", "-c", self.check],
                cwd=root / cwd,
                env=env,
                capture_output=True,
                text=True,
            )

    def test_green_when_no_terraform_tree_exists(self) -> None:
        result = self._run({"README.md": "nothing here\n"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_green_when_only_configuration_blocks_remain(self) -> None:
        """The post-prune terminal state: resources stay, instructions are gone."""
        result = self._run(
            {
                "terraform/cloudflare/generated_dns.tf": (
                    'resource "cloudflare_dns_record" "www" {\n  name = "www"\n}\n'
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_red_while_import_blocks_are_committed(self) -> None:
        result = self._run(
            {
                "terraform/cloudflare/generated_dns.tf": (
                    'resource "cloudflare_dns_record" "www" {\n  name = "www"\n}\n'
                    "\nimport {\n  to = cloudflare_dns_record.www\n  id = \"abc\"\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("generated_dns.tf", result.stdout + result.stderr)
        # Both readings are named, because the check cannot tell them apart.
        self.assertIn("infra-copilot:prune", result.stderr)
        self.assertIn("infra-copilot:import", result.stderr)

    def test_red_for_moved_blocks_too(self) -> None:
        """#8's 99 leftovers were `moved`, not `import`."""
        result = self._run(
            {
                "terraform/cloudflare/dns.tf": (
                    "moved {\n  from = cloudflare_record.a\n"
                    "  to   = cloudflare_dns_record.a\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1)

    def test_uncommitted_files_are_not_evidence(self) -> None:
        """The blocks are pruned by a PR, so only committed ones count."""
        result = self._run(
            {"terraform/cloudflare/generated.tf": "import {\n  to = a.b\n}\n"},
            commit=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_worktree_deletion_is_not_a_prune(self) -> None:
        """Deleting the file on disk without committing leaves HEAD carrying it."""
        result = self._run(
            {"terraform/cloudflare/generated.tf": "import {\n  to = a.b\n}\n"},
            delete=("terraform/cloudflare/generated.tf",),
        )
        self.assertEqual(result.returncode, 1)

    def test_the_answer_does_not_depend_on_the_working_directory(self) -> None:
        """migrate-import ends with a bare `cd terraform/cloudflare`."""
        files = {
            "terraform/cloudflare/generated.tf": "import {\n  to = a.b\n}\n",
            "terraform/github/repos.tf": 'resource "github_repository" "a" {}\n',
        }
        for cwd in (".", "terraform/cloudflare", "terraform/github"):
            with self.subTest(cwd=cwd):
                self.assertEqual(self._run(files, cwd=cwd).returncode, 1)

    def test_javascript_in_a_heredoc_is_not_a_block(self) -> None:
        """`import { name } from "./x"` inside an inline Worker script is not HCL."""
        result = self._run(
            {
                "terraform/cloudflare/worker.tf": (
                    'resource "cloudflare_workers_script" "w" {\n'
                    "  content = <<-EOT\n"
                    '    import { handler } from "./handler.js"\n'
                    "    export default { fetch: handler }\n"
                    "  EOT\n"
                    "}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_word_import_in_prose_is_not_a_block(self) -> None:
        result = self._run(
            {
                "terraform/cloudflare/main.tf": (
                    "# imported from the dashboard; see import { } docs\n"
                    'variable "zone_id" { type = string }\n'
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class MigrateImportCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.step = step("migrate-import")

    def test_hcp_branch_accepts_the_post_apply_no_op(self) -> None:
        """The inversion: a finished migration plans `No changes.`, not imports."""
        hcp_branch = self.step.split("# HCP mode: local terraform plan", 1)[1]
        self.assertIn("No changes", hcp_branch)
        self.assertIn("will be imported", hcp_branch)
        # Still additive-only: a create/destroy/forget is never accepted.
        for rejected in (
            "grep -q 'will be created' \"$p\" && exit 1",
            "will be destroyed|will be deleted",
            "will no longer be managed|will be forgotten",
        ):
            self.assertIn(rejected, hcp_branch)

    def test_the_no_op_plan_still_needs_adoption_evidence(self) -> None:
        """A never-adopted zone also plans `No changes.` — the HCL is what separates them."""
        hcp_branch = self.step.split("# HCP mode: local terraform plan", 1)[1]
        self.assertIn("generated*.tf", hcp_branch)

    def test_generated_file_evidence_is_a_glob(self) -> None:
        """A real adoption splits cf-terraforming output by zone and resource type."""
        self.assertIn("terraform/cloudflare/generated*.tf", self.step)
        self.assertNotIn("--error-unmatch terraform/cloudflare/generated.tf", self.step)


if __name__ == "__main__":
    unittest.main()
