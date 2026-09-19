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

    def test_a_module_moved_block_is_not_a_leftover(self) -> None:
        """Terraform calls removing one a breaking change: it is the upgrade path.

        Counting it here would hold phase 5 red over a block the runbook now
        refuses to remove — permanently, with no workflow able to clear it.
        """
        result = self._run(
            {
                "terraform/modules/dns/main.tf": (
                    "moved {\n  from = cloudflare_record.a\n"
                    "  to   = cloudflare_dns_record.a\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_module_import_block_is_out_of_scope_too(self) -> None:
        """Spent per consumer, and that set is not closed — so not this step's call."""
        result = self._run(
            {
                "terraform/modules/dns/main.tf.json": (
                    '{\n  "import": [\n    { "to": "cloudflare_dns_record.a", "id": "x" }\n  ]\n}\n'
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_leaf_is_still_red_when_a_module_is_clean(self) -> None:
        """The exclusion is a directory, not a switch that turns the scan off."""
        result = self._run(
            {
                "terraform/modules/dns/main.tf": (
                    "moved {\n  from = a.b\n  to = a.c\n}\n"
                ),
                "terraform/cloudflare/dns.tf": (
                    "moved {\n  from = cloudflare_record.a\n"
                    "  to   = cloudflare_dns_record.a\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1)
        reported = result.stdout + result.stderr
        self.assertIn("terraform/cloudflare/dns.tf", reported)
        self.assertNotIn("modules", reported)

    def test_a_multiline_heredoc_import_is_not_a_block(self) -> None:
        """The common JS formatting: `import {` alone on a line, inside a heredoc.

        The end-of-line anchor that fixed the single-line form matches this one
        exactly; only tracking the heredoc body settles it.
        """
        result = self._run(
            {
                "terraform/cloudflare/worker.tf": (
                    'resource "cloudflare_worker_script" "w" {\n'
                    "  content = <<-EOT\n"
                    "    import {\n      handler,\n    } from \"./mod.js\"\n"
                    "  EOT\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_an_unindented_heredoc_import_is_not_a_block_either(self) -> None:
        """Column 0 inside the body, which no indentation heuristic could exclude."""
        result = self._run(
            {
                "terraform/cloudflare/worker.tf": (
                    'resource "cloudflare_worker_script" "w" {\n'
                    "  content = <<EOT\n"
                    "import {\n  handler,\n} from \"./mod.js\"\n"
                    "EOT\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_glob_in_a_string_does_not_hide_the_rest_of_the_file(self) -> None:
        """`target = "example.com/*"` is the canonical Cloudflare page-rule value.

        Tracking /* */ regions meant one of these discarded every line after it,
        block included — which is why the tracking is gone.
        """
        result = self._run(
            {
                "terraform/cloudflare/pr.tf": (
                    'resource "cloudflare_page_rule" "redirect" {\n'
                    '  target = "example.com/*"\n}\n\n'
                    "import {\n  to = cloudflare_dns_record.www\n  id = \"abc\"\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_commented_out_block_is_reported(self) -> None:
        """The accepted ceiling, and the harmless direction.

        A spent block commented out rather than deleted is still something to
        clean up, so reporting it is arguably right rather than merely tolerable.
        """
        result = self._run(
            {
                "terraform/cloudflare/dns.tf": (
                    "/*\nimport {\n  to = a.b\n  id = \"x\"\n}\n*/\n"
                    'resource "cloudflare_dns_record" "a" {\n  name = "a"\n}\n'
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_json_indentation_is_not_structure(self) -> None:
        """Four spaces and minified both used to read green with blocks committed."""
        for name, body in (
            ("four", '{\n    "import": [\n        { "to": "a.b", "id": "x" }\n    ]\n}\n'),
            ("min", '{"import":[{"to":"a.b","id":"x"}]}'),
        ):
            with self.subTest(shape=name):
                result = self._run({f"terraform/cloudflare/{name}.tf.json": body})
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_nested_json_key_named_import_is_not_a_block(self) -> None:
        """The other direction: `locals.import` is configuration, not a leftover."""
        result = self._run(
            {
                "terraform/cloudflare/main.tf.json": (
                    '{\n  "locals": [\n    { "import": "not a block" }\n  ]\n}\n'
                ),
            }
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unparseable_json_is_not_evidence_either_way(self) -> None:
        """Terraform would reject it too; exit 2, not a clean bill of health."""
        result = self._run({"terraform/cloudflare/broken.tf.json": "{ not json\n"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_crlf_line_endings_do_not_hide_a_block(self) -> None:
        """A consuming repo need not normalize; a trailing \\r defeated both matches."""
        result = self._run(
            {
                "terraform/cloudflare/crlf.tf": (
                    'import {\r\n  to = a.b\r\n  id = "x"\r\n}\r\n'
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_heredoc_marker_in_a_comment_or_string_opens_nothing(self) -> None:
        """A phantom heredoc swallows the rest of the file, block included."""
        result = self._run(
            {
                "terraform/cloudflare/a.tf": (
                    "# Example: <<EOF is how you write a heredoc\n"
                    'resource "null_resource" "r" {\n'
                    '  triggers = { cmd = "cat <<EOF" }\n}\n\n'
                    "import {\n  to = cloudflare_dns_record.www\n  id = \"abc\"\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_string_ending_in_a_heredoc_marker_opens_nothing(self) -> None:
        """`command = "cat <<EOF"` — the marker is last on the line but quoted.

        The earlier fix anchored the opener at end of line, which the trailing
        ` }` in its own test satisfied; a string that *ends* the line did not.
        Terraform heredoc tags are unquoted by spec, so allowing an optional
        quote was the bug: it matched on the string's own closing quote.
        """
        result = self._run(
            {
                "terraform/cloudflare/a.tf": (
                    'resource "null_resource" "r" {\n'
                    '  command = "cat <<EOF"\n}\n\n'
                    "import {\n  to = cloudflare_dns_record.www\n  id = \"abc\"\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_an_inline_block_comment_in_a_header_is_still_a_block(self) -> None:
        """`import /* see #123 */ {` is a legal header; HCL allows a comment there."""
        result = self._run(
            {
                "terraform/cloudflare/b.tf": (
                    "import /* imported in #123 */ {\n"
                    "  to = cloudflare_dns_record.api\n  id = \"def\"\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_multiline_comment_in_a_header_is_still_a_block(self) -> None:
        """The one cross-line header HCL admits.

        Verified against terraform 1.16.1 `fmt -check`: `import` with `{` on the
        next line is rejected, and so is a comment on its own line between them,
        so a header comment always starts on the keyword's line. That makes the
        entry condition complete for the grammar rather than a heuristic.
        """
        result = self._run(
            {
                "terraform/cloudflare/a.tf": (
                    "import /* imported\n in #123 */ {\n"
                    "  to = cloudflare_dns_record.www\n  id = \"abc\"\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_glob_cannot_enter_the_header_comment_state(self) -> None:
        """The guard against re-introducing the region tracking that ate files.

        `hdr` is entered only from a line already shaped like a header, so an
        assignment carrying `/*` cannot start it however many follow.
        """
        result = self._run(
            {
                "terraform/cloudflare/pr.tf": (
                    'resource "cloudflare_page_rule" "a" {\n'
                    '  target = "example.com/*"\n}\n\n'
                    'resource "cloudflare_page_rule" "b" {\n'
                    '  target = "other.example/*"\n}\n\n'
                    "moved {\n  from = a.b\n  to = a.c\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_comment_stripping_cannot_manufacture_a_heredoc(self) -> None:
        """`command = "cat <<EOF#"` is valid HCL; the `#` strip leaves a bare tag.

        The opener must sit in an expression position — `cat ` is not one — so
        nothing opens and the block below is still found.
        """
        result = self._run(
            {
                "terraform/cloudflare/a.tf": (
                    'resource "null_resource" "r" {\n'
                    '  command = "cat <<EOF#"\n}\n\n'
                    "import {\n  to = cloudflare_dns_record.www\n  id = \"abc\"\n}\n"
                ),
            }
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_a_real_heredoc_still_opens_from_every_expression_position(self) -> None:
        """The five positions measured against terraform fmt: = ( , : [ ."""
        for pos, line in (
            ("assign", "  x = <<EOT"),
            ("call", "  x = jsonencode(<<EOT"),
            ("arg", '  x = join("", [<<EOT'),
            ("tuple", "  x = [<<EOT"),
            ("object", "  x = { k : <<EOT"),
        ):
            with self.subTest(position=pos):
                result = self._run(
                    {
                        "terraform/cloudflare/a.tf": (
                            'resource "null_resource" "r" {\n'
                            f"{line}\nimport {{\nEOT\n}}\n"
                        ),
                    }
                )
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )

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




@unittest.skipUnless(os.name == "posix", "the runbook's helpers are POSIX shell")
class RunbookHelperTests(unittest.TestCase):
    """The `held` / `exactly` snippets are the safety rail; run them, don't trust them.

    Every address shape here cost a review round: an aggregate `to` that state
    never prints verbatim, a move that only adds `count`, and a sibling whose
    name merely starts the same. `held_under` used to live here too; it served
    module-relative addresses, and went with the module case when pruning was
    scoped to leaves.
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
        found = re.findall(r"^(held\(\) \{\n.*?\n\})$", text, re.S | re.M)
        self.assertEqual(len(found), 1, f"expected `held`, got {found}")
        self.assertNotIn(
            "held_under", text, "held_under outlived the module case it served"
        )
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

    def test_removing_an_index_needs_exact_matching_both_ways(self) -> None:
        """`x[0]` -> `x` pre-apply: `held x` is true on the strength of `x[0]` itself."""
        self.assertTrue(self._ask("held 'aws_instance.web'"))          # why it is unsafe
        self.assertFalse(self._ask("exactly 'aws_instance.web'"))      # not applied yet
        self.assertTrue(self._ask("exactly 'aws_instance.web[0]'"))    # old still there

    def test_the_runbook_separates_the_two_index_directions(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("`moved` **adding** an index", text)
        self.assertIn("`moved` **removing** a resource index", text)

    def test_a_plan_pair_outranks_the_address_table(self) -> None:
        """The table is a filter; Terraform parses its own addresses, awk does not."""
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("The plan pair decides", text)
        self.assertLess(
            text.index("The plan pair decides"),
            text.index("State membership filters first"),
            "the authority must be stated before the heuristic",
        )
        self.assertIn("the plan pair is the decision and the table is noise", text)

    def test_the_state_snapshot_outlives_the_helpers(self) -> None:
        """Deleting it in the helper block leaves every later check reading nothing."""
        text = RUNBOOK.read_text(encoding="utf-8")
        self.assertLess(
            text.index("held() {"),
            text.rindex('rm -f "$state"'),
            "the snapshot is removed before the checks that read it",
        )
        self.assertEqual(text.count('rm -f "$state"'), 2)  # the instruction, and the step

    def test_an_unmigrated_address_is_reported_absent(self) -> None:
        self.assertFalse(self._ask("held 'aws_instance.old'"))


class FileLayoutTests(unittest.TestCase):
    """A `unittest.main()` above a test class skips it and still reports OK."""

    def test_nothing_is_defined_after_the_main_guard(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        guard = text.index('if __name__ == "__main__":')
        self.assertNotIn(
            "\nclass ", text[guard:], "a class after the guard never runs directly"
        )


if __name__ == "__main__":
    unittest.main()
