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
RUNBOOK = REPO_ROOT / ".ai-rulez/skills/infra-copilot/references/docs/prune.md"


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

    def test_a_non_repository_cannot_be_verified(self) -> None:
        """Exit 2, not 1: ignorance must not route anyone to `prune`."""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["/bin/sh", "-c", self.check],
                cwd=directory,
                env={**os.environ, "GIT_CEILING_DIRECTORIES": directory},
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_the_step_declares_itself_tri_state(self) -> None:
        self.assertIn("tri_state: true", step("prune-spent-imports"))

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

    def test_red_for_a_json_leaf_too(self) -> None:
        """Phase 6 accepts `*.tf.json` as leaf configuration; so must this."""
        result = self._run(
            {
                "terraform/gcp/main.tf.json": (
                    '{\n  "import": [\n    { "to": "google_project.p", "id": "p" }\n  ]\n}\n'
                ),
            }
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("main.tf.json", result.stdout + result.stderr)

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

    def test_an_inline_comment_after_the_opener_is_still_a_block(self) -> None:
        """`moved {  # renamed in #8` is a block opener; missing it reads falsely green."""
        result = self._run(
            {
                "terraform/cloudflare/dns.tf": (
                    "moved {  # renamed in #8\n"
                    "  from = cloudflare_record.a\n"
                    "  to   = cloudflare_dns_record.a\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1)

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


@unittest.skipUnless(os.name == "posix", "the runbook's helpers are POSIX shell")
class RunbookHelperTests(unittest.TestCase):
    """The `held` / `held_under` snippets are the safety rail; run them, don't trust them.

    Every address shape here cost a review round: an aggregate `to` that state
    never prints verbatim, a move that only adds `count`, a module key with a
    dot in it, and a sibling whose name merely starts the same.
    """

    STATE = (
        "aws_instance.web[0]\n"
        'module.zone["example.com"].module.child.aws_instance.new\n'
        "module.parent.aws_instance.newer_thing\n"
        'cloudflare_dns_record.this["www"]\n'
    )

    def setUp(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        # Each helper runs from its `name() {` line to the first `}` in column 0.
        found = re.findall(r"^(held(?:_under)?\(\) \{\n.*?\n\})$", text, re.S | re.M)
        self.assertEqual(len(found), 2, f"expected both helpers, got {found}")
        oneline = re.findall(r"^(exactly\(\) \{.*\})$", text, re.M)
        self.assertEqual(len(oneline), 1, f"expected `exactly`, got {oneline}")
        self.helpers = "\n".join(found + oneline)

    def _ask(self, call: str) -> bool:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.write_text(self.STATE, encoding="utf-8")
            script = f'{self.helpers}\n{call} "{state}"'
            return (
                subprocess.run(
                    ["/bin/sh", "-c", script], capture_output=True, text=True
                ).returncode
                == 0
            )

    def test_an_aggregate_address_is_held_through_its_instances(self) -> None:
        """`x` → `x[0]`: state has only the instance, and that is the evidence."""
        self.assertTrue(self._ask("held 'aws_instance.web'"))

    def test_held_does_not_leak_across_a_name_boundary(self) -> None:
        self.assertFalse(self._ask("held 'aws_instance.we'"))

    def test_a_module_relative_address_survives_a_dotted_key(self) -> None:
        """`module.zone["example.com"]` is why the call path is not split on dots."""
        self.assertTrue(self._ask("held_under 'aws_instance.new'"))

    def test_held_under_does_not_match_a_longer_sibling(self) -> None:
        self.assertFalse(self._ask("held_under 'aws_instance.newer'"))

    def test_removing_an_index_needs_exact_matching_both_ways(self) -> None:
        """`x[0]` -> `x` pre-apply: `held x` is true on the strength of `x[0]` itself."""
        self.assertTrue(self._ask("held 'aws_instance.web'"))          # why it is unsafe
        self.assertFalse(self._ask("exactly 'aws_instance.web'"))      # not applied yet
        self.assertTrue(self._ask("exactly 'aws_instance.web[0]'"))    # old still there

    def test_the_runbook_separates_the_two_index_directions(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("`moved` **adding** an index", text)
        self.assertIn("`moved` **removing** an index", text)

    def test_the_state_snapshot_outlives_the_helpers(self) -> None:
        """Deleting it in the helper block leaves every later check reading nothing."""
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertLess(
            text.index("held_under() {"),
            text.rindex('rm -f "$state"'),
            "the snapshot is removed before the checks that read it",
        )
        self.assertEqual(text.count('rm -f "$state"'), 2)  # the instruction, and the step

    def test_an_unmigrated_address_is_reported_absent(self) -> None:
        self.assertFalse(self._ask("held_under 'aws_instance.old'"))
        self.assertFalse(self._ask("held 'aws_instance.old'"))
