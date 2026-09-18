"""The per-host record and the derived skill closure.

Both exist because a fact was stated in more than one place: the four hosts'
capabilities, and "which skills does this skill need." These assert the gate that
keeps the single copy single.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.validate import (
    ROUTER_SKILLS,
    host_records,
    skill_closure,
    validate_host_contract,
)


HOSTS_TABLE = """# Host capability records

| Host | Native question tool | Modes | Install guide |
|---|---|---|---|
| Claude Code | `AskUserQuestion` | single | `docs/install-claude-code.md` |
| Codex CLI | `request_user_input` | single | `docs/install-codex.md` |
"""
GUIDE = "See [`hosts.md`](../skills/infra-copilot/references/hosts.md)."
PROTOCOL = """# Protocol

### Asking a decision

Use the host's tool only when [`hosts.md`](hosts.md) records `AskUserQuestion` for it.
"""


def build_repository(root: Path, **overrides: str) -> Path:
    """A minimal tree shaped like the real one, with named files overridden."""
    files = {
        "skills/infra-copilot/references/hosts.md": HOSTS_TABLE,
        "skills/infra-copilot/references/protocol.md": PROTOCOL,
        ".ai-rulez/skills/infra-copilot/references/protocol.md": PROTOCOL,
        "docs/install-claude-code.md": GUIDE,
        "docs/install-codex.md": GUIDE,
        "README.md": (
            "| [Claude Code](docs/install-claude-code.md) |\n"
            "| [Codex CLI](docs/install-codex.md) |\n"
        ),
    }
    files.update(overrides)
    for relative, content in files.items():
        if content is None:
            continue
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


class HostRecordTests(unittest.TestCase):
    def test_parses_tool_and_guide_from_each_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            self.assertEqual(
                host_records(root),
                {
                    "Claude Code": ("AskUserQuestion", "docs/install-claude-code.md"),
                    "Codex CLI": ("request_user_input", "docs/install-codex.md"),
                },
            )

    def test_accepts_a_consistent_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(validate_host_contract(build_repository(Path(directory))), [])

    def test_rejects_a_row_whose_install_guide_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(Path(directory))
            (root / "docs/install-codex.md").unlink()
            self.assertIn(
                "skills/infra-copilot/references/hosts.md: Codex CLI names "
                "docs/install-codex.md, which is missing",
                validate_host_contract(root),
            )

    def test_rejects_a_guide_that_restates_instead_of_citing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{"docs/install-codex.md": "Codex uses `request_user_input`."},
            )
            self.assertIn(
                "docs/install-codex.md: does not link references/hosts.md; per-host "
                "capabilities must be cited there, not restated here",
                validate_host_contract(root),
            )

    def test_rejects_a_guide_absent_from_the_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory), **{"docs/install-emacs.md": GUIDE}
            )
            self.assertIn(
                "docs/install-emacs.md: install guide is not listed in "
                "skills/infra-copilot/references/hosts.md",
                validate_host_contract(root),
            )

    def test_rejects_a_readme_that_does_not_link_a_guide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{"README.md": "[Claude Code](docs/install-claude-code.md)"},
            )
            self.assertIn(
                "README.md: install table does not link docs/install-codex.md",
                validate_host_contract(root),
            )

    def test_rejects_a_protocol_that_names_no_question_tool(self) -> None:
        """The AskUserQuestion grant in commands/ had no consumer for four releases.

        Deleting the protocol rule would silently restore that state, so the rule's
        absence has to be an error rather than a quiet regression.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/protocol.md": (
                        "### Asking a decision\n\nRead [`hosts.md`](hosts.md)."
                    )
                },
            )
            self.assertIn(
                "skills/infra-copilot/references/protocol.md: its '### Asking a "
                "decision' section names no question tool from "
                "skills/infra-copilot/references/hosts.md; the allowed-tools grant in "
                "commands/ would have no consumer",
                validate_host_contract(root),
            )

    def test_rejects_a_protocol_that_does_not_reference_the_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/protocol.md": (
                        "### Asking a decision\n\nUse `AskUserQuestion`."
                    )
                },
            )
            self.assertIn(
                "skills/infra-copilot/references/protocol.md: does not link hosts.md",
                validate_host_contract(root),
            )

    def test_rejects_a_protocol_missing_the_decision_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/protocol.md": (
                        "See [`hosts.md`](hosts.md) and use `AskUserQuestion`."
                    )
                },
            )
            self.assertIn(
                "skills/infra-copilot/references/protocol.md: has no "
                "'### Asking a decision' section",
                validate_host_contract(root),
            )

    def test_the_english_word_question_does_not_satisfy_the_tool_check(self) -> None:
        """`question` is OpenCode's tool name, so a substring test is nearly vacuous."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/hosts.md": HOSTS_TABLE.replace(
                        "`AskUserQuestion`", "`question`"
                    ).replace("`request_user_input`", "`question`"),
                    "skills/infra-copilot/references/protocol.md": (
                        "### Asking a decision\n\nAsk a questionnaire per "
                        "[`hosts.md`](hosts.md)."
                    ),
                },
            )
            self.assertIn(
                "skills/infra-copilot/references/protocol.md: its '### Asking a "
                "decision' section names no question tool from "
                "skills/infra-copilot/references/hosts.md; the allowed-tools grant in "
                "commands/ would have no consumer",
                validate_host_contract(root),
            )

    def test_an_added_column_does_not_break_every_row(self) -> None:
        """hosts.md invites new per-host columns; a last-column anchor forbids them."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/hosts.md": HOSTS_TABLE.replace(
                        "`docs/install-claude-code.md` |",
                        "`docs/install-claude-code.md` | `hooks/hooks.json` |",
                    )
                },
            )
            self.assertEqual(
                host_records(root)["Claude Code"],
                ("AskUserQuestion", "docs/install-claude-code.md"),
            )
            self.assertEqual(validate_host_contract(root), [])

    def test_rejects_a_row_whose_tool_cell_is_not_an_identifier(self) -> None:
        """A dropped row used to resurface as an unrelated orphan-guide complaint."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/hosts.md": HOSTS_TABLE.replace(
                        "`request_user_input`", "request_user_input"
                    )
                },
            )
            self.assertIn(
                "skills/infra-copilot/references/hosts.md: Codex CLI has no question "
                "tool in column 2; it must be a backticked identifier such as "
                "`AskUserQuestion`",
                validate_host_contract(root),
            )

    def test_a_bare_path_mention_is_not_a_citation(self) -> None:
        """"See references/hosts.md" used to pass while the page had no link."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{"docs/install-codex.md": "See references/hosts.md for capabilities."},
            )
            self.assertIn(
                "docs/install-codex.md: does not link references/hosts.md; per-host "
                "capabilities must be cited there, not restated here",
                validate_host_contract(root),
            )

    def test_a_readme_that_only_mentions_a_guide_is_not_linking_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "README.md": (
                        "| [Claude Code](docs/install-claude-code.md) |\n"
                        "| Codex CLI — see docs/install-codex.md |\n"
                    )
                },
            )
            self.assertIn(
                "README.md: install table does not link docs/install-codex.md",
                validate_host_contract(root),
            )

    def test_a_tool_named_outside_the_decision_section_does_not_count(self) -> None:
        """The gate exists so deleting the rule fails; a document-wide search let a
        mention in any other section stand in for the rule itself."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/protocol.md": (
                        "# Protocol\n\n### Asking a decision\n\n"
                        "Read [`hosts.md`](hosts.md).\n\n"
                        "## Preflight\n\nHistorically we used `AskUserQuestion`.\n"
                    )
                },
            )
            self.assertIn(
                "skills/infra-copilot/references/protocol.md: its '### Asking a "
                "decision' section names no question tool from "
                "skills/infra-copilot/references/hosts.md; the allowed-tools grant in "
                "commands/ would have no consumer",
                validate_host_contract(root),
            )

    def test_a_protocol_that_only_names_the_record_is_not_citing_it(self) -> None:
        """The guide and README checks were tightened; this one was left behind."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{
                    "skills/infra-copilot/references/protocol.md": (
                        "### Asking a decision\n\nSee hosts.md, then use "
                        "`AskUserQuestion`."
                    )
                },
            )
            self.assertIn(
                "skills/infra-copilot/references/protocol.md: does not link hosts.md",
                validate_host_contract(root),
            )

    def test_reports_an_unparseable_table_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_repository(
                Path(directory),
                **{"skills/infra-copilot/references/hosts.md": "# no table here\n"},
            )
            self.assertEqual(
                validate_host_contract(root),
                [
                    "skills/infra-copilot/references/hosts.md: no host capability rows "
                    "parsed; each row needs a `tool` column and a `docs/install-*.md` "
                    "column"
                ],
            )


class SkillClosureTests(unittest.TestCase):
    @staticmethod
    def write_skill(root: Path, name: str, body: str) -> None:
        path = root / ".ai-rulez/skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    def test_router_links_are_not_dependencies(self) -> None:
        """The hub links every action skill; needing none of them is the point.

        A naive "any ../<skill>/ link" rule makes the hub depend on all four, and
        every closure becomes the full install -- which is the behavior this whole
        change exists to replace.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_skill(root, "infra-copilot", "[setup](../setup/SKILL.md)")
            self.write_skill(root, "setup", "[p](../infra-copilot/references/protocol.md)")
            self.assertEqual(skill_closure("infra-copilot", root), ["infra-copilot"])
            self.assertEqual(skill_closure("setup", root), ["infra-copilot", "setup"])

    def test_closure_is_transitive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_skill(root, "prune", "[s](../status/references/scan.md)")
            self.write_skill(root, "status", "[p](../infra-copilot/references/protocol.md)")
            self.write_skill(root, "infra-copilot", "no dependencies")
            self.assertEqual(
                skill_closure("prune", root), ["infra-copilot", "prune", "status"]
            )

    def test_a_cycle_terminates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_skill(root, "a", "[b](../b/references/x.md)")
            self.write_skill(root, "b", "[a](../a/references/x.md)")
            self.assertEqual(skill_closure("a", root), ["a", "b"])


class ShippedClosureTests(unittest.TestCase):
    def test_every_action_skill_needs_the_hub(self) -> None:
        """What docs/install-opencode.md tells users to type, asserted here offline.

        make smoke-closure proves the same thing by installing it; this catches the
        regression without the npm download.
        """
        for skill in ("setup", "import", "add", "status"):
            with self.subTest(skill=skill):
                self.assertEqual(skill_closure(skill), sorted([skill, "infra-copilot"]))

    def test_the_hub_contributes_only_itself_as_a_dependency(self) -> None:
        """As a closure *member* the hub adds nothing else; as a root it is rejected.

        Both halves matter: routing links must not inflate an action skill's closure
        to all five, and `--closure infra-copilot` must not hand back an install that
        is a router with nothing to route to.
        """
        self.assertEqual(skill_closure("infra-copilot"), ["infra-copilot"])
        self.assertIn("infra-copilot", ROUTER_SKILLS)


class ClosureCommandTests(unittest.TestCase):
    @staticmethod
    def run_closure(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "scripts/validate.py", *arguments],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_prints_install_arguments_for_an_action_skill(self) -> None:
        result = self.run_closure("--closure", "status")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "--skill infra-copilot --skill status")

    def test_rejects_the_router_as_a_root(self) -> None:
        result = self.run_closure("--closure", "infra-copilot")
        self.assertEqual(result.returncode, 2)
        self.assertIn("owns no operations", result.stderr)

    def test_rejects_an_unknown_skill(self) -> None:
        result = self.run_closure("--closure", "nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no skill named 'nope'", result.stderr)

    def test_rejects_a_closure_whose_dependency_is_unshipped(self) -> None:
        """Only the root was checked, so an unshipped dependency was still printed."""
        shipped = Path(__file__).resolve().parents[1] / "skills/infra-copilot/SKILL.md"
        moved = shipped.with_suffix(".md.moved")
        shipped.rename(moved)
        try:
            result = self.run_closure("--closure", "status")
        finally:
            moved.rename(shipped)
        self.assertEqual(result.returncode, 2)
        self.assertIn("skills/infra-copilot", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_rejects_an_unrecognised_flag_instead_of_validating(self) -> None:
        """A typo'd flag used to fall through and print the success banner on stdout,
        which `make smoke-closure` would have captured as the closure."""
        result = self.run_closure("--clsoure", "status")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
