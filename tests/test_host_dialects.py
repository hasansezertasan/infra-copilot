"""The subagent and hook sections of hosts.md, and the artifacts they govern.

`hosts.md` owns the per-host record; `validate_host_contract` gates its question
tool rows, and this covers the two sections added for #19 and #42. What can be
gated is that a row marked shipped has its artifact in that host's dialect, and
that a row marked unshipped has no artifact at all.

Every case below is a failure that actually happened while establishing those
rows, not a hypothetical. Both dialects fail *silently* when wrong -- Antigravity
reported "agents: 1 processed" for an agent in Claude's comma-string form and
then never listed it in `agy agent` -- which is why the parity gate exists.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate import (
    AGENT_STEM,
    HOSTS_DOCUMENT,
    dialect_rows,
    validate_host_dialects,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = f"agents/{AGENT_STEM}.md"
HOOK_PATH = "hooks/hooks.json"
FIXTURE_PATHS = (HOSTS_DOCUMENT, AGENT_PATH, HOOK_PATH, "hooks/session-start.sh")


def build_root(directory: str) -> Path:
    root = Path(directory)
    for relative in FIXTURE_PATHS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)
    return root


class RecordTests(unittest.TestCase):
    def test_the_repository_matches_its_own_record(self) -> None:
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_both_sections_are_readable(self) -> None:
        self.assertTrue(dialect_rows(REPO_ROOT, "## Subagent manifests"))
        self.assertTrue(dialect_rows(REPO_ROOT, "## Hook discovery"))

    def test_no_directory_is_claimed_by_two_shipped_rows(self) -> None:
        """Uniqueness is per directory, not global.

        Claude and Antigravity collide at root agents/, but .codex/agents/ and
        .opencode/agents/ are independent -- asserting one shipped row globally
        made those rows impossible to graduate.
        """
        rows = dialect_rows(REPO_ROOT, "## Subagent manifests")
        shipped = [r for r in rows if r[-1].strip("* ").lower().startswith("yes")]
        directories = [r[1].strip("`") for r in shipped]
        self.assertEqual(len(directories), len(set(directories)), directories)


class AgentTests(unittest.TestCase):
    def _root(self, old: str, new: str, path: str = HOSTS_DOCUMENT) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / path
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_foreign_dialect_in_the_shipped_slot_is_rejected(self) -> None:
        """The silent failure the whole record exists for, in both directions.

        `claude plugin details` showed "Agents (1)" for an Antigravity-dialect
        file at root agents/ -- an agent whose whole tool grant is names Claude
        does not have.
        """
        root = self._root(
            "tools: Read, Bash, Glob, Grep, Skill",
            "tools:\n  - view_file\n  - grep_search\n  - run_command",
            AGENT_PATH,
        )
        self.assertTrue(any("frontmatter tools" in e for e in validate_host_dialects(root)))

    def test_the_grant_is_read_from_frontmatter_not_the_document(self) -> None:
        """A whole-file search let the frontmatter grant `Write` while the
        expected line sat in the prose below it."""
        root = self._root("tools: Read, Bash, Glob, Grep, Skill", "tools: Write", AGENT_PATH)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8")
            + "\n\nFor reference: tools: Read, Bash, Glob, Grep, Skill\n",
            encoding="utf-8",
        )
        self.assertTrue(any("frontmatter tools" in e for e in validate_host_dialects(root)))

    def test_the_declared_name_is_parsed_not_searched(self) -> None:
        """A substring test passed `name: wrong-agent`, because the stem still
        appeared in the heading and the instructions."""
        root = self._root(f"name: {AGENT_STEM}", "name: wrong-agent", AGENT_PATH)
        self.assertTrue(any("must declare name" in e for e in validate_host_dialects(root)))

    def test_a_write_tool_in_the_record_is_rejected(self) -> None:
        root = self._root("`Grep`, `Skill` |", "`Grep`, `Skill`, `Write` |")
        self.assertTrue(any("Write" in e for e in validate_host_dialects(root)))

    def test_the_tools_the_instructions_need_are_required(self) -> None:
        """It loads the runbook through the skill tool and runs shell checks."""
        for tool, old, new in (
            ("Skill", ", `Skill` |", " |"),
            ("Bash", "`Bash`, ", ""),
        ):
            with self.subTest(tool=tool):
                root = self._root(old, new)
                self.assertTrue(any("omits" in e for e in validate_host_dialects(root)))

    def test_an_agent_that_restates_the_scan_is_rejected(self) -> None:
        root = self._root("status.md", "my own inlined procedure", AGENT_PATH)
        self.assertTrue(any("delegate" in e for e in validate_host_dialects(root)))

    def test_a_repo_relative_runbook_path_is_rejected(self) -> None:
        """The agent's working directory is the CONSUMING repository, while the
        runbooks ship in the plugin payload."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8")
            + "\nAlso read skills/infra-copilot/references/status.md directly.\n",
            encoding="utf-8",
        )
        self.assertTrue(
            any("consuming repository" in e for e in validate_host_dialects(root))
        )

    def test_the_manifest_stays_an_adapter(self) -> None:
        """The runbook owns scope, guardrails and the report contract."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / AGENT_PATH
        document.write_text(
            document.read_text(encoding="utf-8") + "\n" * 45, encoding="utf-8"
        )
        self.assertTrue(any("adapter" in e for e in validate_host_dialects(root)))

    def test_wiring_at_an_unshipped_path_is_rejected(self) -> None:
        """Codex records `.codex/agents/` and ships nothing there."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        shipped = root / ".codex/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.toml").write_text('name = "x"\n', encoding="utf-8")
        self.assertTrue(any(".codex/agents" in e for e in validate_host_dialects(root)))

    def test_the_shared_directory_is_not_reported_twice(self) -> None:
        """Antigravity's unshipped path IS Claude's shipped one; reporting it
        would make the documented collision unshippable rather than recorded."""
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_the_record_can_revoke_the_agent(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / AGENT_PATH).unlink()
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "`Grep`, `Skill` | **yes** |",
                "`Grep`, `Skill` | no — withdrawn |",
                1,
            ),
            encoding="utf-8",
        )
        self.assertEqual(validate_host_dialects(root), [])

    def test_a_shipped_row_still_requires_its_manifest(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / AGENT_PATH).unlink()
        self.assertTrue(any("no manifest is here" in e for e in validate_host_dialects(root)))


    def test_a_second_host_may_ship_at_an_independent_path(self) -> None:
        """Graduating Codex at .codex/agents/ must not trip the collision rule."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "| `.codex/agents/` | none — session tools are inherited | — | no — not exercised |",
                "| `.codex/agents/` | none — session tools are inherited | — | **yes** |",
                1,
            ),
            encoding="utf-8",
        )
        shipped = root / ".codex/agents"
        shipped.mkdir(parents=True)
        (shipped / f"{AGENT_STEM}.toml").write_text(
            'name = "infra-auditor"\n'
            'developer_instructions = """Invoke the infra-copilot skill, then status.md."""\n',
            encoding="utf-8",
        )
        self.assertEqual(validate_host_dialects(root), [])

    def test_two_rows_may_not_ship_the_same_directory(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        document.write_text(
            document.read_text(encoding="utf-8").replace(
                "`run_command` | no — path collision |", "`run_command` | **yes** |", 1
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("only one may" in e for e in validate_host_dialects(root)))

    def test_an_unrecorded_manifest_in_the_directory_is_rejected(self) -> None:
        """The host discovers the whole directory, not the recorded filename.

        `agents/rogue.md` carrying `tools: Write` passed: an agent nobody
        reviewed, with whatever grant it declares.
        """
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / "agents/rogue.md").write_text(
            "---\nname: rogue\ntools: Write\n---\nrogue\n", encoding="utf-8"
        )
        self.assertTrue(any("rogue.md" in e for e in validate_host_dialects(root)))


class HookTests(unittest.TestCase):
    def _payload_root(self, mutate) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return root

    def test_a_contradicting_matcher_is_rejected(self) -> None:
        """A manifest with the wrong matcher is discovered and never fires."""
        root = self._payload_root(
            lambda p: p["hooks"]["SessionStart"][0].__setitem__("matcher", "nope")
        )
        self.assertTrue(any("matcher" in e for e in validate_host_dialects(root)))

    def test_a_sibling_of_hooks_is_rejected(self) -> None:
        """Antigravity counted a `_comment` beside `hooks` as a second hook."""
        root = self._payload_root(lambda p: p.__setitem__("_comment", ["why"]))
        self.assertTrue(any("top-level keys" in e for e in validate_host_dialects(root)))

    def test_naming_the_script_is_not_running_it(self) -> None:
        """`echo hooks/session-start.sh` passed a substring test."""
        root = self._payload_root(
            lambda p: p["hooks"]["SessionStart"][0].__setitem__(
                "hooks", [{"type": "command", "command": "echo hooks/session-start.sh"}]
            )
        )
        self.assertTrue(any("hand" in e for e in validate_host_dialects(root)))

    def test_an_entry_with_no_callback_is_rejected(self) -> None:
        root = self._payload_root(lambda p: p["hooks"]["SessionStart"][0].pop("hooks"))
        self.assertTrue(
            any("declares no hooks" in e for e in validate_host_dialects(root))
        )

    def test_the_shipped_command_counts_as_an_invocation(self) -> None:
        """It resolves the path into a variable before running it, so the path
        and the shell cannot be required adjacent."""
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_a_sibling_hook_event_is_rejected(self) -> None:
        """Only SessionStart is recorded.

        A sibling such as PreToolUse would run behaviour on tool use that no
        capability record authorises and the shared implementation never sees.
        """
        root = self._payload_root(
            lambda p: p["hooks"].__setitem__(
                "PreToolUse",
                [{"matcher": "*", "hooks": [{"type": "command", "command": "echo x"}]}],
            )
        )
        self.assertTrue(any("hook events" in e for e in validate_host_dialects(root)))

    def test_a_manifest_at_an_unshipped_path_is_rejected(self) -> None:
        """Codex fired no hook from any candidate path; shipping one back fails."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / "hooks/hooks-codex.json").write_text("{}", encoding="utf-8")
        self.assertTrue(
            any("hooks-codex.json" in e for e in validate_host_dialects(root))
        )

    def test_a_shipped_row_requires_its_manifest(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        (root / HOOK_PATH).unlink()
        self.assertTrue(any("no manifest is here" in e for e in validate_host_dialects(root)))


class MalformedRecordTests(unittest.TestCase):
    """A record that is wrong in shape must be reported, not crash or be trusted."""

    def _root(self, old: str, new: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        document = root / HOSTS_DOCUMENT
        text = document.read_text(encoding="utf-8")
        self.assertIn(old, text)
        document.write_text(text.replace(old, new, 1), encoding="utf-8")
        return root

    def test_a_short_row_is_reported_not_raised(self) -> None:
        """`| yes |` entered the shipped list and then indexed off the end,
        raising IndexError before the missing-column diagnostic could run."""
        root = self._root(
            "| OpenCode | `.opencode/agents/` | bool map | `read`, `grep`, `glob`, `bash` | no — not exercised |",
            "| yes |",
        )
        self.assertTrue(any("missing columns" in e for e in validate_host_dialects(root)))

    def test_a_hook_path_may_not_escape_the_plugin_root(self) -> None:
        """Containment was applied to agent paths only, so a hook row of
        `../escape.json` had the validator read and accept an off-tree file."""
        root = self._root("| Claude Code | `hooks/hooks.json` |", "| Claude Code | `../escape.json` |")
        (root.parent / "escape.json").write_text("{}", encoding="utf-8")
        self.assertTrue(any("escapes" in e for e in validate_host_dialects(root)))

    def test_an_echo_prefixed_command_does_not_count(self) -> None:
        """`echo sh hooks/session-start.sh` satisfied "path present and shell
        token present" while executing only `echo`."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"] = [
            {"type": "command", "command": "echo sh hooks/session-start.sh"}
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(any("hand" in e for e in validate_host_dialects(root)))

    def test_a_callback_that_is_not_a_command_is_rejected(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = build_root(directory.name)
        path = root / HOOK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"]["SessionStart"][0]["hooks"][0]["type"] = "prompt"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(any("type 'command'" in e for e in validate_host_dialects(root)))


if __name__ == "__main__":
    unittest.main()
