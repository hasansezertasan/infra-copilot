"""The per-host capability table and the parity gate that keeps it honest.

Three surfaces need the same per-host fact -- the question tool a decision may
use, the dialect a subagent manifest must be written in, and the path a host
discovers a hook manifest at -- and `ai-rulez` generates none of them. These
tests are what stands in for a generator: they fail when a shipped artifact and
its record in hosts.yaml disagree.

Each case below is a failure that actually happened while establishing the
table, not a hypothetical.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate import (
    AGENT_FILENAME,
    AGENT_FORBIDDEN_PATH,
    EXPECTED_HOSTS,
    HOSTS_DOCUMENT,
    QUESTION_PROTOCOL_DOCUMENT,
    _field,
    _verified,
    host_records,
    validate_host_dialects,
    validate_question_protocol,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
#: Everything the two validators read. Copied per test so a case can corrupt one
#: file without the others going missing and masking the error under test.
FIXTURE_PATHS = (
    HOSTS_DOCUMENT,
    QUESTION_PROTOCOL_DOCUMENT,
    "hooks/hooks.json",
    "hooks/session-start.sh",
    f"agents/{AGENT_FILENAME}",
)
#: The single host whose agent actually ships. Read from the table rather than
#: named here, so this file cannot drift from it either.
AGENT_HOST = next(
    host for host, block in host_records(REPO_ROOT).items() if _verified(block, "agent")
)
AGENT_PATH = f"{_field(host_records(REPO_ROOT)[AGENT_HOST], 'agent', 'path').rstrip('/')}/{AGENT_FILENAME}"


def build_root(directory: str) -> Path:
    root = Path(directory)
    for relative in FIXTURE_PATHS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / relative, destination)
    return root


class HostRecordTests(unittest.TestCase):
    def test_exactly_one_host_owns_the_agent(self) -> None:
        """Root agents/ is one path with incompatible dialects, so only one can."""
        owners = [h for h, b in host_records(REPO_ROOT).items() if _verified(b, "agent")]
        self.assertEqual(owners, [AGENT_HOST], owners)

    def test_verified_flags_survive_a_trailing_comment(self) -> None:
        """A trailing comment is this file's dominant style.

        An anchored `$` after the flag turned every commented record into
        "unrecorded", which silently disabled the rules keyed on them -- the
        Claude hook rules among them.
        """
        records = host_records(REPO_ROOT)
        self.assertTrue(_verified(records["claude"], "hook"))
        self.assertIsNotNone(_verified(records["claude"], "question_tool"))

    def test_a_nested_key_cannot_clobber_a_real_record(self) -> None:
        """Keys under a later top-level mapping are not hosts.

        Matching any two-space-indented key anywhere reset the record to empty,
        and an empty block passes every rule while the gate reports green.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8")
                + "\ndefaults:\n  claude:\n    display_name: not a host\n",
                encoding="utf-8",
            )
            records = host_records(root)
            self.assertIn("display_name: Claude Code", records["claude"])
            self.assertEqual(validate_host_dialects(root), [])

    def test_repository_is_currently_consistent(self) -> None:
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])
        self.assertEqual(validate_question_protocol(REPO_ROOT), [])


class AgentDialectTests(unittest.TestCase):
    def test_a_foreign_dialect_in_the_shipped_slot_is_rejected(self) -> None:
        """The failure this whole table exists for, and it is silent both ways.

        Antigravity reported "agents: 1 processed" for Claude's comma-string form
        and then never listed the agent in `agy agent`. In the other direction,
        `claude plugin details` showed "Agents (1)" for an Antigravity-dialect
        file at root agents/ -- an agent whose whole tool grant is names Claude
        does not have.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tools: Read, Bash, Glob, Grep, Skill",
                    "tools:\n  - view_file\n  - grep_search\n  - run_command",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("dialect" in error for error in validate_host_dialects(root)),
            )

    def test_a_write_tool_in_the_record_is_rejected(self) -> None:
        """The scan is read-only and the recorded grant is what says so."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tool_names: [Read, Bash, Glob, Grep, Skill]",
                    "tool_names: [Read, Bash, Glob, Grep, Skill, Write]",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("Write" in error for error in validate_host_dialects(root)),
            )

    def test_an_agent_that_restates_the_scan_is_rejected(self) -> None:
        """A second copy of the runbook is a second behavioural authority."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8").replace("status.md", "my own inlined procedure"),
                encoding="utf-8",
            )
            self.assertTrue(
                any("delegate" in error for error in validate_host_dialects(root)),
            )

    def test_renaming_a_tool_in_the_table_fails_the_shipped_file(self) -> None:
        """The table is authoritative: editing it is what moves the gate."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "tool_names: [Read, Bash, Glob, Grep, Skill]",
                    "tool_names: [Read, Bash, Glob, Skill]",
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("dialect" in error for error in validate_host_dialects(root)),
            )


class HookManifestTests(unittest.TestCase):
    def test_extra_top_level_key_in_the_root_manifest_is_rejected(self) -> None:
        """Antigravity counted a "_comment" sibling of "hooks" as a second hook.

        `agy plugin validate` reported "hooks: 2 processed" for a file declaring
        one, so a JSON comment key ships a junk hook rather than documentation.
        The rule covers every recorded manifest, not just the one host that
        miscounts: no manifest has a comment syntax to fall back on.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            manifest = root / "hooks/hooks.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["_comment"] = ["why this file exists"]
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(
                any("top-level keys" in error for error in validate_host_dialects(root)),
            )

    def test_a_manifest_no_record_verifies_is_rejected(self) -> None:
        """Codex's is absent on purpose; shipping it back must fail.

        Codex 0.154.0 fired no SessionStart hook from any candidate path, with
        or without `--enable plugin_hooks`.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks/hooks-codex.json").write_text("{}", encoding="utf-8")
            self.assertTrue(
                any("hooks-codex.json" in error for error in validate_host_dialects(root)),
            )

    def test_a_verified_host_missing_its_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks/hooks.json").unlink()
            self.assertTrue(
                any("ships no manifest" in error for error in validate_host_dialects(root)),
            )

    def test_a_root_variable_the_script_ignores_is_rejected(self) -> None:
        """The manifest guard and the output-shape branch must agree.

        A host exporting only the variable the script does not test runs the
        hook and then has its announcement emitted in another host's shape.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            script = root / "hooks/session-start.sh"
            script.write_text(
                script.read_text(encoding="utf-8").replace(
                    "${CLAUDE_PLUGIN_ROOT:-}", "${SOME_OTHER_ROOT:-}"
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("wrong shape" in error for error in validate_host_dialects(root)),
            )


class ReviewRegressionTests(unittest.TestCase):
    """Each case is a hole the PR review found in the gate itself."""

    def test_a_comment_between_entries_does_not_truncate_the_table(self) -> None:
        """An unindented comment is ordinary YAML, not a top-level key.

        Treating it as one closed the mapping and silently dropped every host
        after it -- and since each rule iterates the records returned, the gate
        stayed green while three of the four hosts stopped being checked.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "  antigravity:", "# --- an ordinary separator ---\n  antigravity:", 1
                ),
                encoding="utf-8",
            )
            self.assertEqual(set(host_records(root)), set(EXPECTED_HOSTS))
            self.assertEqual(validate_host_dialects(root), [])

    def test_a_dropped_host_fails_rather_than_going_unchecked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            document.write_text(text[: text.index("  opencode:")], encoding="utf-8")
            self.assertTrue(
                any("opencode" in error for error in validate_host_dialects(root)),
            )

    def test_wiring_at_an_unverified_path_is_rejected_whatever_its_dialect(self) -> None:
        """Codex records `toml_inherited` with no tool names.

        Gating the rejection on a renderable dialect meant nothing shipped under
        .codex/agents/ could ever be reported, though the rule promises to reject
        every artifact at an unverified path.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            manifest = root / ".codex/agents/infra-auditor.toml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('name = "infra-auditor"\n', encoding="utf-8")
            self.assertTrue(
                any(".codex/agents" in error for error in validate_host_dialects(root)),
            )

    def test_the_shared_agent_directory_is_not_reported_as_unverified(self) -> None:
        """Antigravity's unverified path IS Claude's verified one.

        The owner's dialect rule governs that file; reporting it twice would make
        the collision unshippable rather than recorded.
        """
        self.assertEqual(validate_host_dialects(REPO_ROOT), [])

    def test_a_hook_matcher_that_contradicts_the_record_is_rejected(self) -> None:
        """Antigravity takes "*" and Claude an explicit source list.

        A manifest carrying the wrong one is discovered and then never fires, and
        nothing compared the manifest against the recorded matcher.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            manifest = root / "hooks/hooks.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["hooks"]["SessionStart"][0]["matcher"] = "something-else"
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(
                any("matcher" in error for error in validate_host_dialects(root)),
            )

    def test_a_repo_relative_runbook_path_is_rejected(self) -> None:
        """The agent's working directory is the CONSUMING repository.

        A repo-relative `skills/infra-copilot/...` resolves into the consumer and
        finds nothing; it only looks correct from a source checkout of this repo.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / AGENT_PATH
            document.write_text(
                document.read_text(encoding="utf-8")
                + f"\nAlso read {AGENT_FORBIDDEN_PATH}status.md directly.\n",
                encoding="utf-8",
            )
            self.assertTrue(
                any("consuming repository" in error for error in validate_host_dialects(root)),
            )


class SecondReviewRegressionTests(unittest.TestCase):
    """Holes found by the review of the first round of review fixes."""

    def test_a_record_with_no_verification_state_is_rejected(self) -> None:
        """An unstated flag disabled every rule keyed on it.

        Deleting one `verified:` line left validate_host_dialects() green and a
        nonsense matcher passed with it -- the gate was simply off for that
        artifact rather than failing.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            start = text.index("      path: hooks/hooks.json")
            flag = text.index("      verified:", start)
            document.write_text(
                text[:flag] + text[text.index("\n", flag) + 1 :], encoding="utf-8"
            )
            self.assertTrue(
                any("usable `verified:` flag" in e for e in validate_host_dialects(root)),
            )

    def test_a_second_host_may_own_an_independent_agent_path(self) -> None:
        """Uniqueness is per directory, not global.

        Claude and Antigravity collide at root agents/, but .codex/agents/ is
        independent -- a global one-owner count made those rows impossible to
        graduate once their wiring was finally exercised.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    """      path: .codex/agents/          # <name>.toml, body under developer_instructions
      tools_dialect: toml_inherited # no tools key; the session's tools are inherited
      tool_names: []
      verified: false""",
                    """      path: .codex/agents/
      tools_dialect: comma_string
      tool_names: [Read, Bash, Glob, Grep, Skill]
      verified: true""",
                ),
                encoding="utf-8",
            )
            shipped = root / ".codex/agents"
            shipped.mkdir(parents=True)
            shutil.copy(root / AGENT_PATH, shipped / AGENT_FILENAME)
            self.assertEqual(validate_host_dialects(root), [])

    def test_two_hosts_may_not_own_the_same_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / HOSTS_DOCUMENT
            text = document.read_text(encoding="utf-8")
            start = text.index("  antigravity:")
            flag = text.index("      verified: false", text.index("    agent:", start))
            document.write_text(
                text[:flag] + "      verified: true" + text[flag + len("      verified: false") :],
                encoding="utf-8",
            )
            self.assertTrue(
                any("only one may" in e for e in validate_host_dialects(root)),
            )

    def test_the_antigravity_hook_is_not_shipped(self) -> None:
        """Discovery is not execution, and the table says so.

        `agy plugin validate` proves the root manifest is found; no probe hook
        ever fired there, in print mode or an interactive TUI session. Codex is
        excluded on exactly that basis, so this has to be too.
        """
        self.assertFalse((REPO_ROOT / "hooks.json").exists())
        self.assertFalse(_verified(host_records(REPO_ROOT)["antigravity"], "hook"))

    def test_a_root_manifest_shipped_anyway_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            (root / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
            self.assertTrue(
                any("hooks.json" in e and "unverified" in e for e in validate_host_dialects(root)),
            )


class QuestionProtocolTests(unittest.TestCase):
    def test_a_granted_tool_the_protocol_never_names_is_rejected(self) -> None:
        """The state this repository was actually in: a grant with no consumer.

        Three commands declared AskUserQuestion and validate.py pinned the
        string, while nothing ever told the agent to use it.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / QUESTION_PROTOCOL_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace("AskUserQuestion", "SomeOtherTool"),
                encoding="utf-8",
            )
            self.assertTrue(
                any("never says when to use it" in error for error in validate_question_protocol(root)),
            )

    def test_dropping_the_text_fallback_is_rejected(self) -> None:
        """Without it the rule silently means "skip the question" off Claude."""
        with tempfile.TemporaryDirectory() as directory:
            root = build_root(directory)
            document = root / QUESTION_PROTOCOL_DOCUMENT
            document.write_text(
                document.read_text(encoding="utf-8").replace(
                    "Other — enter a custom response", "just pick one"
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                any("custom response" in error for error in validate_question_protocol(root)),
            )


if __name__ == "__main__":
    unittest.main()
